import json

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from registration.models import Delegate, UIUCPromoCode
from registration.payment import eventbrite_client
from registration.payment.eventbrite_client import EventbriteError


def _get_authenticated_delegate(request):
    """Returns the requesting user's Delegate, or None if unauthenticated / no Delegate exists."""
    if not request.user.is_authenticated:
        return None
    try:
        return request.user.delegate
    except Delegate.DoesNotExist:
        return None


@require_GET
def delegate_status(request):
    """
    GET /registration/delegate-status/

    Returns the authenticated delegate's verification/payment state so the
    frontend can resume the flow after a reload or an abandoned checkout.
    """
    delegate = _get_authenticated_delegate(request)
    if delegate is None:
        return JsonResponse({"is_authenticated": False})

    unredeemed = {
        promo.ticket_type: promo.code
        for promo in UIUCPromoCode.objects.filter(delegate=delegate, redeemed_at__isnull=True)
    }

    return JsonResponse(
        {
            "is_authenticated": True,
            "is_uiuc_verified": delegate.is_uiuc_verified,
            "ticket_type": delegate.ticket_type,
            "payment_status": delegate.payment_status,
            "has_unredeemed_promo": unredeemed,
        }
    )


@require_POST
@ratelimit(key="user_or_ip", rate="10/h", block=True)
def uiuc_promo_code(request):
    """
    POST /registration/uiuc-promo-code/
    Body: {"ticket_type": "variety_show" | "workshop" | "bundle"}

    Issues (or re-fetches) a single-use, tier-scoped discount code for a
    verified UIUC delegate. Idempotent per (delegate, ticket_type).
    """
    delegate = _get_authenticated_delegate(request)
    if delegate is None:
        return JsonResponse({"message": "Authentication required"}, status=401)

    if not delegate.is_uiuc_verified:
        return JsonResponse({"message": "UIUC verification required"}, status=403)

    data = json.loads(request.body)
    ticket_type = data.get("ticket_type")

    if ticket_type not in Delegate.TicketType.values:
        return JsonResponse({"message": "Invalid ticket_type"}, status=400)

    existing = UIUCPromoCode.objects.filter(delegate=delegate, ticket_type=ticket_type).first()
    if existing is not None:
        return JsonResponse({"code": existing.code, "ticket_type": existing.ticket_type})

    try:
        result = eventbrite_client.create_discount(delegate.uiuc_netid, ticket_type)
    except EventbriteError:
        return JsonResponse({"message": "Could not generate promo code"}, status=502)

    promo = UIUCPromoCode.objects.create(
        delegate=delegate,
        ticket_type=ticket_type,
        code=result["code"],
        eventbrite_discount_id=result["eventbrite_discount_id"],
    )

    return JsonResponse({"code": promo.code, "ticket_type": promo.ticket_type})


def _resolve_ticket_type(ticket_class_id):
    for ticket_type, class_id in settings.EVENTBRITE_TICKET_CLASS_IDS.items():
        if class_id == ticket_class_id:
            return ticket_type
    return None


@require_POST
@ratelimit(key="user_or_ip", rate="20/h", block=True)
def verify_payment(request):
    """
    POST /registration/verify-payment/
    Body: {"order_id": "..."}

    Verifies an Eventbrite order server-side and marks the delegate paid.
    ticket_type is never trusted from the client — it is always derived
    from the order itself.
    """
    delegate = _get_authenticated_delegate(request)
    if delegate is None:
        return JsonResponse({"message": "Authentication required"}, status=401)

    data = json.loads(request.body)
    order_id = data.get("order_id")
    if not order_id:
        return JsonResponse({"message": "order_id is required"}, status=400)

    if delegate.payment_status == Delegate.PaymentStatus.PAID:
        if delegate.eventbrite_order_id == order_id:
            return JsonResponse(
                {"payment_status": delegate.payment_status, "ticket_type": delegate.ticket_type}
            )
        return JsonResponse(
            {"message": "Delegate is already paid for a different order"}, status=409
        )

    try:
        order = eventbrite_client.get_order(order_id)
    except EventbriteError:
        return JsonResponse({"message": "Could not verify order with Eventbrite"}, status=503)

    if order["event_id"] != settings.EVENTBRITE_EVENT_ID:
        return JsonResponse({"message": "Order does not belong to this event"}, status=400)

    if order["status"] != "placed":
        return JsonResponse({"message": "Order is not complete"}, status=400)

    ticket_type = _resolve_ticket_type(order["ticket_class_id"])
    if ticket_type is None:
        return JsonResponse({"message": "Unrecognized ticket class"}, status=400)

    matched_promo = None
    if order["discount_code"]:
        matched_promo = UIUCPromoCode.objects.filter(
            delegate=delegate, ticket_type=ticket_type, code=order["discount_code"]
        ).first()
        if matched_promo is None:
            return JsonResponse(
                {"message": "Discount code on this order does not belong to you"}, status=403
            )

    try:
        with transaction.atomic():
            delegate.payment_status = Delegate.PaymentStatus.PAID
            delegate.eventbrite_order_id = order_id
            delegate.ticket_type = ticket_type
            delegate.payment_verified_at = timezone.now()
            delegate.save()

            if matched_promo is not None:
                matched_promo.redeemed_at = timezone.now()
                matched_promo.save()
    except IntegrityError:
        return JsonResponse({"message": "This order has already been used"}, status=409)

    return JsonResponse({"payment_status": delegate.payment_status, "ticket_type": delegate.ticket_type})
