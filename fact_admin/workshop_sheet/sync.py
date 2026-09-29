"""
Row logic for the workshops Google Sheet sync. Spec:
docs/superpowers/specs/2026-09-29-workshop-sheet-sync-design.md

sync_row() saves one sheet row. Every problem a coordinator can fix is
raised as RowError with a message written for them; the view shows it in
the row's Status cell.
"""
import logging
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from registration.facilitator.emails import send_setup_email
from registration.facilitator.views import create_facilitator_account
from registration.models import (
    Facilitator,
    FacilitatorContact,
    FacilitatorRegistration,
    FacilitatorWorkshop,
    Location,
    Registration,
    Workshop,
)

logger = logging.getLogger(__name__)

VALID_SESSIONS = {1, 2, 3}
PLACEHOLDER_PHOTO = "placehold.co"


class RowError(Exception):
    pass


@dataclass
class RowOutcome:
    workshop: Workshop
    created: bool
    facilitator: Facilitator | None
    notes: list = field(default_factory=list)


def text(row, key):
    value = row.get(key)
    return "" if value is None else str(value).strip()


def int_or_none(row, key, label):
    value = text(row, key)
    if not value:
        return None
    try:
        return int(float(value))
    except (ValueError, OverflowError):
        raise RowError(f"{label} must be a number")


def _check_length(value, label, limit):
    if len(value) > limit:
        raise RowError(f"{label} is too long (max {limit} characters)")


def norm(value):
    return " ".join(str(value).lower().split())


def room_label(location):
    return f"{location.building} {location.room_num}".strip()


def seats_taken(workshop):
    return (
        Registration.objects.filter(workshop=workshop).count()
        + FacilitatorRegistration.objects.filter(workshop=workshop).count()
    )


# --- workshop -----------------------------------------------------------------

def _resolve_workshop(row, session):
    workshop_id = int_or_none(row, "workshop_id", "Workshop ID")
    if workshop_id is not None:
        workshop = Workshop.objects.select_for_update().filter(pk=workshop_id).first()
        if workshop is None:
            raise RowError(f"No workshop with ID {workshop_id} on the website")
        return workshop, False

    title = text(row, "title")
    if not title:
        raise RowError("Title is required")
    # Same title in the same session is the same workshop: panel rows, or a
    # row whose Workshop ID wasn't written back yet.
    workshop = Workshop.objects.select_for_update().filter(title=title, session=session).first()
    if workshop is not None:
        return workshop, False
    if not text(row, "description"):
        raise RowError("Description is required for a new workshop")
    if not text(row, "facilitator"):
        raise RowError("Facilitator is required for a new workshop")
    return Workshop(title=title, session=session), True


def _apply_session(workshop, created, session):
    if created or workshop.session == session:
        return
    # Registrants would end up with two workshops in one session.
    if Registration.objects.filter(workshop=workshop).exists():
        raise RowError(f"Can't move to Session {session}: delegates are registered for this workshop")
    workshop.session = session
    if workshop.location and workshop.location.session != session:
        workshop.location = None  # a room belongs to one session


# --- room ---------------------------------------------------------------------

def _find_or_create_room(building, room, session, capacity, notes):
    for location in Location.objects.filter(session=session):
        if norm(location.building) == norm(building) and norm(location.room_num) == norm(room):
            return location
    if capacity is None:
        notes.append("room created with capacity 0")
    return Location.objects.create(
        building=building, room_num=room, session=session, capacity=capacity or 0
    )


def _apply_room(row, workshop, session, notes):
    building, room = text(row, "building"), text(row, "room")
    _check_length(building, "Building", 50)
    _check_length(room, "Room", 50)
    capacity = int_or_none(row, "capacity", "Capacity")
    if capacity is not None and capacity < 0:
        raise RowError("Capacity can't be negative")

    if building or room:
        if not (building and room):
            raise RowError("Fill in both Building and Room")
        location = _find_or_create_room(building, room, session, capacity, notes)
        taken = Workshop.objects.filter(location=location).exclude(pk=workshop.pk).first()
        if taken:
            raise RowError(
                f'Room "{room_label(location)}" is already used by "{taken.title}" in Session {session}'
            )
        workshop.location = location

    if capacity is not None:
        if workshop.location is None:
            raise RowError("Set a Building and Room before Capacity")
        workshop.location.capacity = capacity
        workshop.location.save()


# --- facilitator ----------------------------------------------------------------

def _clean_email(row):
    email = text(row, "email").lower()
    if email:
        try:
            validate_email(email)
        except ValidationError:
            raise RowError(f"{email} isn't a valid email")
    return email


def _resolve_facilitator(row, name, email):
    facilitator_id = int_or_none(row, "facilitator_id", "Facilitator ID")
    if facilitator_id is not None:
        facilitator = Facilitator.objects.filter(pk=facilitator_id).first()
        if facilitator is None:
            raise RowError(f"No facilitator with ID {facilitator_id} on the website")
        return facilitator

    if email:
        contact = (
            FacilitatorContact.objects.select_related("facilitator")
            .filter(email__iexact=email).first()
        )
        if contact:
            return contact.facilitator

    # A copied row or a typo would otherwise create a second account.
    if Facilitator.objects.filter(department_name__iexact=name).exists():
        raise RowError(
            f'A facilitator named "{name}" already exists. Copy its Facilitator ID or email into this row.'
        )
    user, _token, _expiration = create_facilitator_account(name)
    return Facilitator(user=user, department_name=name, image_url="", bio="")


def _apply_photo(row, facilitator):
    url = text(row, "photo_url")
    if not url:
        return
    if not url.startswith("https://"):
        raise RowError("Photo upload returned a bad link")
    facilitator.image_url = url
    facilitator.photo_width = int_or_none(row, "photo_width", "Photo width")
    facilitator.photo_height = int_or_none(row, "photo_height", "Photo height")
    facilitator.photo_blur = text(row, "photo_blur")
    facilitator.photo_opaque = row.get("photo_opaque") is not False


def _apply_facilitator(row):
    name = text(row, "facilitator")
    if not name:
        return None
    _check_length(name, "Facilitator", 150)
    _check_length(text(row, "position"), "Position", 200)
    email = _clean_email(row)
    facilitator = _resolve_facilitator(row, name, email)

    if email:
        owner = (
            FacilitatorContact.objects.select_related("facilitator")
            .filter(email__iexact=email).exclude(facilitator_id=facilitator.pk).first()
        )
        if owner:
            raise RowError(f'{email} belongs to "{owner.facilitator.department_name}"')

    # Blank cells never erase what's already on the website.
    facilitator.department_name = name
    people = text(row, "people")
    if people:
        facilitator.facilitators = [p.strip() for p in people.split(",") if p.strip()]
    for key in ("position", "bio"):
        value = text(row, key)
        if value:
            setattr(facilitator, key, value)
    _apply_photo(row, facilitator)
    facilitator.save()

    contact, _ = FacilitatorContact.objects.get_or_create(facilitator=facilitator)
    if email and contact.email != email:
        contact.email = email
        contact.save(update_fields=["email"])
    return facilitator


# --- row ------------------------------------------------------------------------

def sync_row(row):
    """Save one sheet row. Call inside transaction.atomic()."""
    session = int_or_none(row, "session", "Session")
    if session not in VALID_SESSIONS:
        raise RowError("This tab isn't a session tab")

    _check_length(text(row, "title"), "Title", 150)
    notes = []
    workshop, created = _resolve_workshop(row, session)
    _apply_session(workshop, created, session)
    for key in ("title", "description"):
        value = text(row, key)
        if value:
            setattr(workshop, key, value)
    _apply_room(row, workshop, session, notes)
    workshop.save()

    facilitator = _apply_facilitator(row)
    if facilitator:
        FacilitatorWorkshop.objects.get_or_create(facilitator=facilitator, workshop=workshop)

    if workshop.location:
        taken = seats_taken(workshop)
        if taken > workshop.location.capacity:
            notes.append(f"{taken} registered > {workshop.location.capacity} capacity")
    return RowOutcome(workshop, created, facilitator, notes)


# --- login email ------------------------------------------------------------------

def login_due(facilitator, resend):
    """True when deliver_login would actually attempt a send (mirrors its conditions)."""
    contact = FacilitatorContact.objects.filter(facilitator=facilitator).first()
    if contact is None or not contact.email or contact.setup_completed_at:
        return False
    return bool(resend or not contact.login_sent_at)


def deliver_login(facilitator, resend):
    """
    Send the setup email when it's due. Returns None when nothing applies,
    else (note, level, retry, resend_done): retry keeps Ready ticked so the
    next sync tries again; resend_done unticks Resend login.
    """
    contact = FacilitatorContact.objects.filter(facilitator=facilitator).first()
    if contact is None or not contact.email:
        return ("Resend login needs a Facilitator Email", "warn", False, True) if resend else None
    if contact.setup_completed_at:
        # A setup link resets the password; never send one after setup.
        return ("already set up, use Forgot password", "warn", False, True) if resend else None
    if contact.login_sent_at and not resend:
        return None
    try:
        send_setup_email(facilitator, [contact.email])
    except Exception:
        logger.exception("Setup email to facilitator %s failed", facilitator.pk)
        return ("login email failed, will retry", "warn", True, False)
    contact.login_sent_at = timezone.now()
    contact.save(update_fields=["login_sent_at"])
    sent = timezone.localtime(contact.login_sent_at)
    return (f"login sent {sent:%b} {sent.day}", "ok", False, True)


# --- GET ------------------------------------------------------------------------

def _photo_cell(url):
    return "" if not url or PLACEHOLDER_PHOTO in url else url


def _position_cell(value):
    return "" if value in (None, "nan") else value


def facilitator_values(facilitator):
    if facilitator is None:
        return None
    contact = getattr(facilitator, "contact", None)
    return {
        "name": facilitator.department_name,
        "people": ", ".join(facilitator.facilitators or []),
        "position": _position_cell(facilitator.position),
        "bio": facilitator.bio,
        "email": contact.email if contact else "",
    }


def sheet_rows():
    """Every (workshop, facilitator) pair as a sheet row, one row for a workshop with none."""
    links = {}
    for link in FacilitatorWorkshop.objects.select_related("facilitator__contact").order_by("pk"):
        links.setdefault(link.workshop_id, []).append(link.facilitator)

    rows = []
    for workshop in Workshop.objects.select_related("location").order_by("session", "title", "pk"):
        location = workshop.location
        for facilitator in links.get(workshop.pk) or [None]:
            values = facilitator_values(facilitator) or {}
            rows.append({
                "session": workshop.session,
                "workshop_id": workshop.pk,
                "title": workshop.title,
                "description": workshop.description,
                "building": location.building if location else "",
                "room": location.room_num if location else "",
                "capacity": location.capacity if location else "",
                "facilitator_id": facilitator.pk if facilitator else "",
                "facilitator": values.get("name", ""),
                "people": values.get("people", ""),
                "position": values.get("position", ""),
                "bio": values.get("bio", ""),
                "photo": _photo_cell(facilitator.image_url) if facilitator else "",
                "email": values.get("email", ""),
            })
    return rows
