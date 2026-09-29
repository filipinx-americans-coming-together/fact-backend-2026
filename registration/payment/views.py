import json

from django.conf import settings
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from registration.delegate.views import _create_delegate_account
from registration.models import Delegate, UIUCPromoCode
from registration.payment import eventbrite_client
from registration.payment.eventbrite_client import EventbriteError, OrderNotFoundError
# Shared with find_orders_by_email; kept under its old name here.
from registration.payment.eventbrite_client import resolve_ticket_type as _resolve_ticket_type


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
        result = eventbrite_client.create_discount(delegate.uiuc_targeted_id, ticket_type)
    except EventbriteError:
        return JsonResponse({"message": "Could not generate promo code"}, status=502)

    promo = UIUCPromoCode.objects.create(
        delegate=delegate,
        ticket_type=ticket_type,
        code=result["code"],
        eventbrite_discount_id=result["eventbrite_discount_id"],
    )

    return JsonResponse({"code": promo.code, "ticket_type": promo.ticket_type})


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
    except OrderNotFoundError:
        # The delegate's typo, not an outage: a 400 with a message they can
        # act on (the host replaces 5xx bodies with its own error page).
        return JsonResponse(
            {
                "message": "We couldn't find that order number. Check the number in your "
                "Eventbrite confirmation email and try again."
            },
            status=400,
        )
    except EventbriteError:
        return JsonResponse({"message": "Could not verify order with Eventbrite"}, status=503)

    if order["status"] != "placed":
        return JsonResponse({"message": "Order is not complete"}, status=400)

    # ticket_type must be resolved before the event check below — workshop
    # and variety_show/bundle are two different real events, so which
    # event_id is "correct" depends on which ticket class this order used.
    ticket_type = _resolve_ticket_type(order["ticket_class_id"])
    if ticket_type is None:
        return JsonResponse({"message": "Unrecognized ticket class"}, status=400)

    if order["event_id"] != settings.EVENTBRITE_EVENT_IDS[ticket_type]:
        return JsonResponse({"message": "Order does not belong to this event"}, status=400)

    matched_promo = None
    # Per-delegate discount-code ownership check temporarily disabled — not
    # a removal. Real Shibboleth/iTrust verification isn't live yet, so
    # UIUC students currently get one fixed, shared Eventbrite discount
    # code with no per-delegate UIUCPromoCode row ever issued for it; this
    # check rejected every legitimate use of that code. Re-enable once
    # Shibboleth-verified per-delegate promo codes (uiuc_promo_code below)
    # are the only way discount codes are issued again.
    # if order["discount_code"]:
    #     matched_promo = UIUCPromoCode.objects.filter(
    #         delegate=delegate, ticket_type=ticket_type, code=order["discount_code"]
    #     ).first()
    #     if matched_promo is None:
    #         return JsonResponse(
    #             {"message": "Discount code on this order does not belong to you"}, status=403
    #         )

    try:
        with transaction.atomic():
            delegate.payment_status = Delegate.PaymentStatus.PAID
            delegate.eventbrite_order_id = order_id
            delegate.ticket_type = ticket_type
            delegate.payment_verified_at = timezone.now()
            if order["netid"]:
                delegate.uiuc_netid_self_reported = order["netid"]
            delegate.save()

            if matched_promo is not None:
                matched_promo.redeemed_at = timezone.now()
                matched_promo.redeemed_order_id = order_id
                matched_promo.save()
    except IntegrityError:
        return JsonResponse({"message": "This order has already been used"}, status=409)

    return JsonResponse({"payment_status": delegate.payment_status, "ticket_type": delegate.ticket_type})


def _order_hint(order_id):
    # Only ever the last 4 characters — the full order number is what the
    # buyer proves ownership with when linking via verify_payment.
    return "…" + str(order_id)[-4:]


@require_GET
@ratelimit(key="user_or_ip", rate="30/h", block=True)
def find_my_order(request):
    """
    GET /registration/find-my-order/

    Looks up workshop-including Eventbrite orders placed with the
    authenticated delegate's account email, so the register page can ask
    them to link an existing ticket instead of buying a second one.

    Never returns a full order ID, only a masked hint: account emails are
    not verified, so the full order number (from the buyer's Eventbrite
    confirmation email) stays the proof of ownership, and linking still
    goes through verify_payment.
    """
    delegate = _get_authenticated_delegate(request)
    if delegate is None:
        return JsonResponse({"message": "Authentication required"}, status=401)

    if delegate.payment_status == Delegate.PaymentStatus.PAID:
        return JsonResponse({"already_paid": True, "orders": []})

    try:
        found = eventbrite_client.find_orders_by_email(request.user.email)
    except EventbriteError:
        return JsonResponse({"message": "Could not check Eventbrite"}, status=503)

    linked = set(
        Delegate.objects.filter(
            eventbrite_order_id__in=[order["id"] for order in found]
        ).values_list("eventbrite_order_id", flat=True)
    )

    return JsonResponse(
        {
            "already_paid": False,
            "orders": [
                {"order_hint": _order_hint(order["id"]), "ticket_type": order["ticket_type"]}
                for order in found
                if order["id"] not in linked
            ],
        }
    )


def _claim_order_id_key(group, request):
    """
    Rate-limit key targeting the actual threat this limiter defends
    against — guessing/enumerating someone else's paid order_id — rather
    than the requester's IP. There's no user to key on yet (unauthenticated
    endpoint), and a pure IP key would let one dorm/campus NAT's registration
    rush lock out unrelated students sharing that address.
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return "unparseable"
    return str(data.get("order_id") or "missing")


@require_POST
@ratelimit(key=_claim_order_id_key, rate="5/h", block=True)
@ratelimit(key="ip", rate="30/h", block=True)
def claim_order(request):
    """
    POST /registration/delegates/claim-order/
    Body: {order_id, f_name, l_name, email, password, pronouns, year, school_id/other_school_name}

    Unauthenticated purchase-first signup for non-UIUC delegates: pay on
    Eventbrite, then claim the order and create the account in one step,
    instead of creating an account before ever paying.

    Two independent rate limits: 5/h per order_id (the real target — stops
    brute-forcing/guessing a specific order), 30/h per IP as a much looser
    backstop against outright spam, high enough not to trip on a shared
    campus/dorm NAT during a registration rush.

    Verifies the order server-side exactly like verify_payment (event_id
    match, status == "placed", ticket_type derived from the order — never
    trusted from the client) before any account is created. Orders that
    used a discount code are rejected here: those only exist through the
    Shibboleth-verified UIUC promo path (uiuc_promo_code below), where
    ownership is checkable against an already-authenticated delegate; this
    endpoint has no delegate yet to check ownership against, so a
    discount-coded order can only be claimed through that authenticated
    path, not this one.
    """
    data = json.loads(request.body)
    order_id = data.get("order_id")
    if not order_id:
        return JsonResponse({"message": "order_id is required"}, status=400)

    try:
        order = eventbrite_client.get_order(order_id)
    except EventbriteError:
        return JsonResponse({"message": "Could not verify order with Eventbrite"}, status=503)

    if order["status"] != "placed":
        return JsonResponse({"message": "Order is not complete"}, status=400)

    if order["discount_code"]:
        return JsonResponse(
            {"message": "Discounted orders must be claimed through UIUC login instead"},
            status=403,
        )

    # ticket_type must be resolved before the event check below — workshop
    # and variety_show/bundle are two different real events, so which
    # event_id is "correct" depends on which ticket class this order used.
    ticket_type = _resolve_ticket_type(order["ticket_class_id"])
    if ticket_type is None:
        return JsonResponse({"message": "Unrecognized ticket class"}, status=400)

    if order["event_id"] != settings.EVENTBRITE_EVENT_IDS[ticket_type]:
        return JsonResponse({"message": "Order does not belong to this event"}, status=400)

    try:
        with transaction.atomic():
            user, error = _create_delegate_account(
                f_name=data.get("f_name"),
                l_name=data.get("l_name"),
                email=data.get("email"),
                password=data.get("password"),
                pronouns=data.get("pronouns"),
                year=data.get("year"),
                school_id=data.get("school_id"),
                other_school_name=data.get("other_school_name"),
            )
            if error:
                return error

            delegate = user.delegate
            delegate.payment_status = Delegate.PaymentStatus.PAID
            delegate.eventbrite_order_id = order_id
            delegate.ticket_type = ticket_type
            delegate.payment_verified_at = timezone.now()
            delegate.save()
    except IntegrityError:
        return JsonResponse({"message": "This order has already been used"}, status=409)

    login(request, user)

    return JsonResponse(
        {"payment_status": delegate.payment_status, "ticket_type": delegate.ticket_type}
    )
