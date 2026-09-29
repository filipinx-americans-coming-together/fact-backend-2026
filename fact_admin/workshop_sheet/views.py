import json
import os
import re
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from registration.facilitator.views import create_facilitator_account
from registration.models import (
    Facilitator,
    FacilitatorWorkshop,
    Location,
    Registration,
    Workshop,
)

# Sheet columns, in order. "done" and "status" are sheet-only: the script
# sends a row once done is ticked, and writes status back.
COLUMNS = [
    "id",
    "done",
    "session",
    "title",
    "description",
    "room",
    "capacity",
    "facilitator",
    "facilitator_names",
    "photo",
    "bio",
    "position",
    "status",
]

VALID_SESSIONS = {1, 2, 3}

# Drive share links (".../file/d/<id>/view", "...open?id=<id>") aren't image
# URLs. The uc form is, and it's already allowed in the frontend's
# next.config.mjs remotePatterns.
DRIVE_ID = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:[^#]*&)?id=)([\w-]+)")


class RowError(Exception):
    pass


def _text(row, key):
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _int_or_none(row, key):
    value = _text(row, key)
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        raise RowError(f"{key} must be a number")


def _photo_url(value):
    match = DRIVE_ID.search(value)
    if match:
        return f"https://drive.google.com/uc?export=view&id={match.group(1)}"
    if not value.startswith("https://"):
        raise RowError("photo must be an https:// link")
    return value


def _room_label(location):
    return f"{location.building} {location.room_num}".strip()


def _norm(s):
    return " ".join(s.lower().split())


def _find_room(label, session):
    wanted = _norm(label)
    for location in Location.objects.filter(session=session):
        if _norm(_room_label(location)) == wanted:
            return location
    raise RowError(
        f'No room "{label}" in session {session}. Add it under Locations in Django admin first.'
    )


def _find_workshop(row, title, session):
    """
    id column wins (that's what lets a title be renamed). Without an id, a
    workshop with the same title + session is the same workshop — covers
    several facilitator rows for one panel, and a row whose id didn't get
    written back yet.
    """
    workshop_id = _int_or_none(row, "id")
    if workshop_id is not None:
        workshop = Workshop.objects.filter(pk=workshop_id).first()
        if workshop is None:
            raise RowError(f"No workshop with id {workshop_id} on the website")
        return workshop, False

    workshop = Workshop.objects.filter(title=title, session=session).first()
    if workshop is not None:
        return workshop, False

    return Workshop(), True


def _sync_room(row, workshop, session):
    """Blank room/capacity leave the current values alone."""
    label = _text(row, "room")
    if label:
        location = _find_room(label, session)
        taken = Workshop.objects.filter(location=location).exclude(pk=workshop.pk).first()
        if taken:
            raise RowError(f'Room "{label}" is already used by "{taken.title}"')
        workshop.location = location
    elif workshop.location and workshop.location.session != session:
        # Moved to another session; the old room belongs to the old session.
        workshop.location = None

    capacity = _int_or_none(row, "capacity")
    if capacity is not None:
        if workshop.location is None:
            raise RowError("Set a room before setting capacity (capacity belongs to the room)")
        workshop.location.capacity = capacity
        workshop.location.save()


def _sync_facilitator(row, workshop, new_accounts):
    name = _text(row, "facilitator")
    if not name:
        return

    photo = _text(row, "photo")
    photo = _photo_url(photo) if photo else ""

    facilitator = Facilitator.objects.filter(department_name=name).first()
    if facilitator is None:
        user, token, _ = create_facilitator_account(name)
        facilitator = Facilitator(user=user, department_name=name)
        new_accounts.append((name, user.username, f"{os.getenv('ACCOUNT_SET_UP_URL')}/{token}"))

    # Blank cells never erase what's already on the website.
    names = _text(row, "facilitator_names")
    if names:
        facilitator.facilitators = [n.strip() for n in names.split(",") if n.strip()]
    if photo:
        facilitator.image_url = photo
    for field in ("bio", "position"):
        value = _text(row, field)
        if value:
            setattr(facilitator, field, value)
    facilitator.save()

    FacilitatorWorkshop.objects.get_or_create(facilitator=facilitator, workshop=workshop)


def _sync_row(row, new_accounts):
    title = _text(row, "title")
    description = _text(row, "description")
    session = _int_or_none(row, "session")

    if not title:
        raise RowError("title is required")
    if not description:
        raise RowError("description is required")
    if session not in VALID_SESSIONS:
        raise RowError("session must be 1, 2, or 3")

    workshop, created = _find_workshop(row, title, session)

    # Room assignment (matchworkshoplocations) assumes every session 1/2
    # workshop has a facilitator, same as the Excel bulk upload requires.
    if created and not _text(row, "facilitator"):
        raise RowError("facilitator is required for a new workshop")

    # Moving a workshop to another session would leave its registrants with
    # two workshops in one session (or none in another) — do that by hand.
    if (
        not created
        and workshop.session != session
        and Registration.objects.filter(workshop=workshop).exists()
    ):
        raise RowError(
            "Can't change session: delegates are already registered for this workshop"
        )

    workshop.title = title
    workshop.description = description
    workshop.session = session
    _sync_room(row, workshop, session)
    workshop.save()

    _sync_facilitator(row, workshop, new_accounts)
    return workshop, created


def _sheet_rows(workshop):
    """One row per facilitator, matching how the sheet lists panels."""
    links = FacilitatorWorkshop.objects.filter(workshop=workshop).select_related("facilitator")
    facilitators = [link.facilitator for link in links] or [None]
    location = workshop.location
    return [
        {
            "id": workshop.pk,
            "done": False,
            "session": workshop.session,
            "title": workshop.title,
            "description": workshop.description,
            "room": _room_label(location) if location else "",
            "capacity": location.capacity if location else "",
            "facilitator": f.department_name if f else "",
            "facilitator_names": ", ".join(f.facilitators) if f else "",
            "photo": f.image_url if f else "",
            "bio": f.bio if f else "",
            "position": (f.position or "") if f else "",
            "status": "",
        }
        for f in facilitators
    ]


@csrf_exempt  # key-authenticated server-to-server call, no cookies involved
def workshop_sheet(request):
    """
    Sync endpoint for the workshops Google Sheet's Apps Script
    (docs/workshop_sheet/). Authenticated by the X-Sheets-Key header against
    SHEETS_API_KEY, the same key as the nametag export — whoever can read
    the script's properties (every editor, if it's bound to the sheet) can
    use it for both. Disabled unless SHEETS_API_KEY is set.

    GET: every workshop as sheet rows, one per facilitator.
    POST {"rows": [{<column>: value, "row": <sheet row number>}, ...]}:
        creates or updates each workshop (and its facilitator and room),
        returning {"results": [{"row", "id", "status"}]}. Each row is saved
        on its own, so one bad row doesn't block the rest. Never deletes
        workshops, facilitators, facilitator links, or rooms.
    """
    if not settings.SHEETS_API_KEY:
        return JsonResponse({"message": "Workshop sheet sync is disabled"}, status=503)

    provided = request.headers.get("X-Sheets-Key", "")
    if not secrets.compare_digest(provided, settings.SHEETS_API_KEY):
        return JsonResponse({"message": "Invalid key"}, status=403)

    if request.method == "GET":
        workshops = Workshop.objects.select_related("location").order_by("session", "title")
        return JsonResponse(
            {"columns": COLUMNS, "rows": [r for w in workshops for r in _sheet_rows(w)]}
        )

    if request.method != "POST":
        return JsonResponse({"message": "method not allowed"}, status=405)

    try:
        rows = json.loads(request.body).get("rows")
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"message": "Invalid JSON"}, status=400)
    if not isinstance(rows, list):
        return JsonResponse({"message": "rows must be a list"}, status=400)

    results = []
    new_accounts = []
    for row in rows:
        if not isinstance(row, dict):
            results.append({"row": None, "id": None, "status": "error: not a row"})
            continue
        row_accounts = []
        try:
            with transaction.atomic():
                workshop, created = _sync_row(row, row_accounts)
        except RowError as e:
            results.append({"row": row.get("row"), "id": row.get("id") or None, "status": f"error: {e}"})
            continue
        new_accounts.extend(row_accounts)
        results.append({
            "row": row.get("row"),
            "id": workshop.pk,
            "status": "added" if created else "updated",
        })

    if new_accounts:
        body = "Facilitator accounts created from the workshop sheet"
        for name, username, url in new_accounts:
            body += f"\nFacilitator: {name}, Username: {username}, Account Link: {url}"
        try:
            send_mail(
                "FACT Facilitator Accounts",
                body,
                os.getenv("EMAIL_HOST_USER"),
                ["fact.it@psauiuc.org"],
            )
        except Exception:
            # The workshops are already saved; a mail outage shouldn't make
            # the script think the whole sync failed and retry it.
            pass

    return JsonResponse({"results": results})
