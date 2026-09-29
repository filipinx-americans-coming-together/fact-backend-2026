import json
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .sync import RowError, deliver_login, facilitator_values, login_due, sheet_rows, sync_row

logger = logging.getLogger(__name__)

# Each send is a synchronous SMTP call; cap them so one big POST stays well
# inside gunicorn's worker timeout. The rest are picked up by the next sync.
MAX_LOGIN_EMAILS_PER_SYNC = 8


@csrf_exempt  # key-authenticated server-to-server call, no cookies involved
def workshop_sheet(request):
    """
    Sync endpoint for the workshops Google Sheet's Apps Script
    (C:\\Users\\light\\fact\\google-sheets\\workshop-sheet). Authenticated by
    X-Sheets-Key against SHEETS_API_KEY; disabled when the key is unset.

    GET: every workshop as sheet rows (one per facilitator).
    POST {"rows": [...]}: saves each row in its own transaction, then sends
    due setup emails (once per facilitator). Never deletes anything.
    """
    if not settings.SHEETS_API_KEY:
        return JsonResponse({"message": "Workshop sheet sync is disabled"}, status=503)
    provided = request.headers.get("X-Sheets-Key", "")
    if not secrets.compare_digest(provided.encode(), settings.SHEETS_API_KEY.encode()):
        return JsonResponse({"message": "Invalid key"}, status=403)

    if request.method == "GET":
        return JsonResponse({"rows": sheet_rows()})
    if request.method != "POST":
        return JsonResponse({"message": "method not allowed"}, status=405)

    try:
        rows = json.loads(request.body).get("rows")
    except (ValueError, AttributeError):
        return JsonResponse({"message": "Invalid JSON"}, status=400)
    if not isinstance(rows, list):
        return JsonResponse({"message": "rows must be a list"}, status=400)

    results = []
    logins = {}  # facilitator pk -> {"facilitator", "results", "resend"}
    for row in rows:
        if not isinstance(row, dict):
            results.append({"tab": None, "row": None, "level": "error", "status": "not a row",
                            "retry": False, "resend_done": False})
            continue
        base = {"tab": row.get("tab"), "row": row.get("row"), "retry": False, "resend_done": False}
        try:
            with transaction.atomic():
                outcome = sync_row(row)
        except RowError as e:
            results.append({**base, "level": "error", "status": str(e)})
            continue
        except Exception:
            logger.exception("Workshop sheet row %s failed", row.get("row"))
            results.append({**base, "level": "error",
                            "status": "Couldn't save this row (server error). Tell FACT IT."})
            continue

        result = {
            **base,
            "level": "warn" if outcome.notes else "ok",
            "status": " · ".join(["added" if outcome.created else "updated", *outcome.notes]),
            "workshop_id": outcome.workshop.pk,
            "facilitator_id": outcome.facilitator.pk if outcome.facilitator else None,
            "facilitator": facilitator_values(outcome.facilitator),
        }
        results.append(result)
        if outcome.facilitator:
            entry = logins.setdefault(
                outcome.facilitator.pk,
                {"facilitator": outcome.facilitator, "results": [], "resend": False},
            )
            entry["results"].append(result)
            entry["resend"] = entry["resend"] or row.get("resend_login") is True

    # After the row transactions commit: one email per facilitator, even
    # when several of their rows (sessions, workshops) were ticked.
    attempts = 0
    for entry in logins.values():
        due = login_due(entry["facilitator"], entry["resend"])
        if due and attempts >= MAX_LOGIN_EMAILS_PER_SYNC:
            for result in entry["results"]:
                result["status"] += " · login email queued, will send next sync"
                if result["level"] == "ok":
                    result["level"] = "warn"
                result["retry"] = True
                result["resend_done"] = False
            continue
        if due:
            attempts += 1
        delivered = deliver_login(entry["facilitator"], entry["resend"])
        if not delivered:
            continue
        note, level, retry, resend_done = delivered
        for result in entry["results"]:
            result["status"] += f" · {note}"
            if level == "warn" and result["level"] == "ok":
                result["level"] = "warn"
            result["retry"] = retry
            result["resend_done"] = resend_done

    return JsonResponse({"results": results})
