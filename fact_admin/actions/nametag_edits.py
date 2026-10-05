"""
Officer edits from the Nametag Review tab of the FACT 2026 Google Sheet
(C:\\Users\\light\\fact\\google-sheets\\fact-2026-sheet), applied to a
delegate's profile. Called by nametag_sheet's POST in views.py.
"""
import logging

from django.contrib.auth.models import User

from registration.models import Delegate, School

logger = logging.getLogger(__name__)

FIELDS = ("first_name", "last_name", "pronouns", "school", "year")
USER_FIELDS = ("first_name", "last_name")


class EditError(Exception):
    """An edit that wasn't saved; the message goes into the sheet's Notes."""


def _max_length(field):
    if field in USER_FIELDS:
        return User._meta.get_field(field).max_length
    if field == "school":
        return Delegate._meta.get_field("other_school").max_length
    return Delegate._meta.get_field(field).max_length


def _current(delegate, field):
    """The field as GET /fact-admin/sheets/nametags/ sends it, stripped."""
    if field in USER_FIELDS:
        value = getattr(delegate.user, field)
    elif field == "school":
        value = delegate.school.name if delegate.school else delegate.other_school
    else:
        value = getattr(delegate, field)
    return (value or "").strip()


def apply_edit(edit):
    """
    Saves one {"order_id", "email", "field", "old", "new"} edit and returns
    "saved" or "already saved"; raises EditError if it isn't saved. "old" is
    the value the sheet last saw, or None when the sheet showed "(hidden)"
    and so has nothing to compare. Call inside a transaction.
    """
    field = edit.get("field")
    if field not in FIELDS:
        raise EditError("This column can't be edited from the sheet")
    old, new = edit.get("old"), edit.get("new")
    if not isinstance(new, str) or not (old is None or isinstance(old, str)):
        raise EditError("Invalid value")
    new = new.strip()
    if "\n" in new or "\r" in new:
        raise EditError("Line breaks aren't allowed")

    order_id = str(edit.get("order_id") or "").strip()
    email = str(edit.get("email") or "").strip()
    delegate = None
    if order_id and email:
        # No select_related on the nullable school: Postgres rejects
        # FOR UPDATE on the nullable side of an outer join.
        delegate = (
            Delegate.objects.select_related("user").select_for_update()
            .filter(
                payment_status=Delegate.PaymentStatus.PAID,
                ticket_type__in=[Delegate.TicketType.WORKSHOP, Delegate.TicketType.BUNDLE],
                eventbrite_order_id=order_id,
                user__email__iexact=email,
            )
            .first()
        )
    if delegate is None:
        raise EditError("No paid delegate with this order and email")

    current = _current(delegate, field)
    # Already equal: a re-push after a sync that saved but then failed.
    if current == new:
        return "already saved"
    # Never echo `current`: it can be a password typed into the wrong box.
    if old is not None and old.strip() != current:
        raise EditError("Changed on the site since the last sync; not saved")
    if field in USER_FIELDS and not new:
        raise EditError("Name can't be blank")
    limit = _max_length(field)
    if len(new) > limit:
        raise EditError(f"Too long (max {limit} characters)")

    if field in USER_FIELDS:
        setattr(delegate.user, field, new)
        delegate.user.save(update_fields=[field])
    elif field == "school":
        school = School.objects.filter(name__iexact=new).first() if new else None
        delegate.school = school
        delegate.other_school = new if new and not school else None
        delegate.save(update_fields=["school", "other_school"])
    else:
        setattr(delegate, field, new)
        delegate.save(update_fields=[field])
    # Log the sheet's old (None when hidden) and new, never `current`: it can
    # be a password typed into the wrong box.
    logger.info("Nametag sheet edit: delegate %s %s %r -> %r", delegate.pk, field, old, new)
    return "saved"
