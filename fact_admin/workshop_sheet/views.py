import json
import os
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from registration.facilitator.views import create_facilitator_account
from registration.models import Facilitator, FacilitatorWorkshop, Registration, Workshop

# Sheet columns, in order. "publish" and "status" are sheet-only: rows are
# sent only once publish is ticked, and status is written back by the script.
COLUMNS = [
    "id",
    "publish",
    "title",
    "session",
    "description",
    "facilitator",
    "facilitator_names",
    "image_url",
    "bio",
    "position",
    "preferred_cap",
    "moveable_seats",
    "status",
]

VALID_SESSIONS = {1, 2, 3}


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


def _bool(row, key):
    return _text(row, key).lower() in {"true", "yes", "y", "1", "x"}


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


def _sync_facilitator(row, workshop, new_accounts):
    name = _text(row, "facilitator")
    if not name:
        return

    facilitator = Facilitator.objects.filter(department_name=name).first()
    if facilitator is None:
        user, token, _ = create_facilitator_account(name)
        facilitator = Facilitator(user=user, department_name=name)
        new_accounts.append((name, user.username, f"{os.getenv('ACCOUNT_SET_UP_URL')}/{token}"))

    # Blank cells never erase what's already on the website.
    names = _text(row, "facilitator_names")
    if names:
        facilitator.facilitators = [n.strip() for n in names.split(",") if n.strip()]
    for field in ("image_url", "bio", "position"):
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
    workshop.preferred_cap = _int_or_none(row, "preferred_cap")
    workshop.moveable_seats = _bool(row, "moveable_seats")
    workshop.save()

    _sync_facilitator(row, workshop, new_accounts)
    return workshop, created


def _sheet_rows(workshop):
    """One row per facilitator, matching how the sheet lists panels."""
    links = FacilitatorWorkshop.objects.filter(workshop=workshop).select_related("facilitator")
    facilitators = [link.facilitator for link in links] or [None]
    return [
        {
            "id": workshop.pk,
            "publish": True,
            "title": workshop.title,
            "session": workshop.session,
            "description": workshop.description,
            "facilitator": f.department_name if f else "",
            "facilitator_names": ", ".join(f.facilitators) if f else "",
            "image_url": f.image_url if f else "",
            "bio": f.bio if f else "",
            "position": (f.position or "") if f else "",
            "preferred_cap": workshop.preferred_cap if workshop.preferred_cap is not None else "",
            "moveable_seats": workshop.moveable_seats,
            "status": "on website",
        }
        for f in facilitators
    ]


@csrf_exempt  # key-authenticated server-to-server call, no cookies involved
def workshop_sheet(request):
    """
    Sync endpoint for the workshops Google Sheet's Apps Script. Authenticated
    by the X-Sheets-Key header, checked against WORKSHOP_SHEET_API_KEY — a
    separate key from SHEETS_API_KEY, because anyone who can edit the
    workshops sheet can read its script's key, and that key must not also
    unlock delegate data. Disabled unless WORKSHOP_SHEET_API_KEY is set.

    GET: every workshop as sheet rows (to fill the sheet the first time).
    POST {"rows": [{<column>: value, "row": <sheet row number>}, ...]}:
        creates or updates each workshop (and its facilitator), returning
        {"results": [{"row", "id", "status"}]}. Each row is saved on its own,
        so one bad row doesn't block the rest. Never deletes workshops,
        facilitators, or facilitator links, and never assigns rooms — do
        those in Django admin.
    """
    if not settings.WORKSHOP_SHEET_API_KEY:
        return JsonResponse({"message": "Workshop sheet sync is disabled"}, status=503)

    provided = request.headers.get("X-Sheets-Key", "")
    if not secrets.compare_digest(provided, settings.WORKSHOP_SHEET_API_KEY):
        return JsonResponse({"message": "Invalid key"}, status=403)

    if request.method == "GET":
        workshops = Workshop.objects.order_by("session", "title")
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
