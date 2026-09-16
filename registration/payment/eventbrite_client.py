"""
Thin wrapper around the Eventbrite API for order verification and UIUC
discount-code generation. Supports EVENTBRITE_MOCK_MODE for local
development without real Eventbrite credentials, mirroring
shibboleth_auth's SAML_MOCK_MODE pattern.

Endpoint shapes verified against Eventbrite's public API v3 spec
(eventbrite-api-v3-public.apib): Order retrieval at GET /orders/{id}/,
Discount creation at POST /organizations/{organization_id}/discounts/
with a JSON body nested under "discount".
"""

import hashlib
import secrets
import string

import requests
from django.conf import settings


class EventbriteError(Exception):
    """Raised when the Eventbrite API returns an error or unexpected data."""


def _random_suffix(length=16):
    # secrets, not random: this suffix is a bearer credential for a free
    # ticket, not a cosmetic ID — it must not be predictable.
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _short_id(targeted_id, length=10):
    # eduPersonTargetedID is opaque and can be long/URI-shaped — not
    # something to paste directly into an Eventbrite discount code. This
    # is a stable, short, non-reversible tag derived from it, purely for
    # the code to look scoped-per-person in the Eventbrite dashboard; the
    # actual one-time-use guarantee comes from Delegate.uiuc_targeted_id's
    # DB uniqueness + UIUCPromoCode's one-per-(delegate, ticket_type), not
    # from this tag.
    return hashlib.sha256(targeted_id.encode()).hexdigest()[:length].upper()


# ---------------------------------------------------------------------------
# get_order
# ---------------------------------------------------------------------------

# Fixed sentinels, deliberately NOT derived from settings.EVENTBRITE_EVENT_IDS
# — a real order's event_id is fixed at creation time regardless of what's
# currently configured; echoing the live setting here would make the
# wrong-event rejection path in verify_payment untestable (the comparison
# could never fail). variety_show and bundle share one sentinel because
# they share one real event (see settings.py).
_MOCK_EVENT_IDS = {
    "workshop": "mock-event-id-workshop",
    "variety_show": "mock-event-id-vshow",
    "bundle": "mock-event-id-vshow",
}


def _mock_get_order(order_id):
    """
    Mock orders are encoded as
    MOCK_ORDER_<ticket_type>_[FREE_]<discount_code_or_none>. Matched against
    known ticket type keys (not a blind split) because ticket type names
    like "variety_show" contain underscores themselves.

    An optional "FREE_" marker right after the ticket type selects the
    hidden, $0 UIUC ticket class instead of the paid one — mirrors the real
    two-ticket-classes-per-type setup (see EVENTBRITE_UIUC_TICKET_CLASS_IDS).

    A "PENDING_" prefix right after MOCK_ORDER_ makes the mock report
    status="pending" instead of "placed", so verify_payment's rejection
    of incomplete orders can actually be tested.
    """
    if not order_id.startswith("MOCK_ORDER_"):
        raise EventbriteError(f"Order {order_id} not found")

    remainder = order_id[len("MOCK_ORDER_"):]

    status = "placed"
    if remainder.startswith("PENDING_"):
        status = "pending"
        remainder = remainder[len("PENDING_"):]

    for ticket_type in settings.EVENTBRITE_TICKET_CLASS_IDS:
        prefix = f"{ticket_type}_"
        if remainder.startswith(prefix):
            rest = remainder[len(prefix):]

            if rest.startswith("FREE_"):
                ticket_class_id = settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS[ticket_type]
                rest = rest[len("FREE_"):]
            else:
                ticket_class_id = settings.EVENTBRITE_TICKET_CLASS_IDS[ticket_type]

            discount_code = rest if rest != "none" else None
            return {
                "id": order_id,
                "status": status,
                "event_id": _MOCK_EVENT_IDS[ticket_type],
                "ticket_class_id": ticket_class_id,
                "discount_code": discount_code,
                "netid": None,
            }

    raise EventbriteError(f"Unknown mock ticket type in order_id '{order_id}'")


# Custom Question text (event-scoped, type "text", respondent "attendee")
# attached to the UIUC ticket classes on the real events — not a
# Shibboleth attribute, purely self-reported at checkout as an interim
# stand-in until Shib/iTrust is live. Matched by exact question text since
# the Attendee Answers expansion keys answers by question_id, which
# differs per event/question, not by any stable name. Confirmed against
# the real questions (event 2001126216382 q323798359, event 2001120979719
# q323798414): text is exactly "NetID", not "UIUC NetID".
NETID_QUESTION_TEXT = "NetID"


def _real_get_order(order_id):
    if not order_id.isdigit():
        raise EventbriteError(f"Invalid order_id format: '{order_id}'")

    url = f"https://www.eventbriteapi.com/v3/orders/{order_id}/"
    headers = {"Authorization": f"Bearer {settings.EVENTBRITE_API_TOKEN}"}
    try:
        # The Order object's own documented `promo_code` field is never
        # actually populated by the real API (verified against a live
        # 100%-off order — comes back null even though a code was used).
        # The real discount data only shows up via the nested
        # attendees.promotional_code expansion, as {code, percent_off, ...}
        # on each attendee. attendees.answers is the same pattern for
        # custom-question answers (e.g. self-reported NetID).
        response = requests.get(
            url,
            headers=headers,
            params={"expand": "attendees,attendees.promotional_code,attendees.answers"},
            timeout=10,
        )
    except requests.RequestException as e:
        raise EventbriteError(f"Eventbrite request failed: {e}")

    if response.status_code == 404:
        raise EventbriteError(f"Order {order_id} not found")
    if not response.ok:
        raise EventbriteError(f"Eventbrite API error (status {response.status_code})")

    raw = response.json()
    attendees = raw.get("attendees", [])
    ticket_class_id = attendees[0]["ticket_class_id"] if attendees else None
    promotional_code = attendees[0].get("promotional_code") if attendees else None
    answers = attendees[0].get("answers", []) if attendees else []
    netid = next(
        (a["answer"] for a in answers if a.get("question") == NETID_QUESTION_TEXT and a.get("answer")),
        None,
    )
    return {
        "id": raw["id"],
        "status": raw.get("status"),
        "event_id": raw.get("event_id"),
        "ticket_class_id": ticket_class_id,
        "discount_code": promotional_code["code"] if promotional_code else None,
        "netid": netid,
    }


def get_order(order_id):
    """
    Fetch and normalize an Eventbrite order.

    Returns a dict: {id, status, event_id, ticket_class_id, discount_code, netid}.
    netid is the self-reported answer to the "NetID" custom question,
    or None if that question wasn't answered/attached to this order's ticket.
    Raises EventbriteError if the order can't be found or the API fails.
    """
    if settings.EVENTBRITE_MOCK_MODE:
        return _mock_get_order(order_id)
    return _real_get_order(order_id)


# ---------------------------------------------------------------------------
# create_discount
# ---------------------------------------------------------------------------

def _real_create_discount(event_id, uiuc_ticket_class_id, code):
    url = f"https://www.eventbriteapi.com/v3/organizations/{settings.EVENTBRITE_ORGANIZATION_ID}/discounts/"
    headers = {"Authorization": f"Bearer {settings.EVENTBRITE_API_TOKEN}"}
    payload = {
        "discount": {
            "code": code,
            # "access" reveals a hidden ticket class rather than discounting
            # a visible one — the UIUC ticket class is already $0, so no
            # percent_off/amount_off is needed at all.
            "type": "access",
            "quantity_available": 1,
            "event_id": event_id,
            "ticket_class_ids": [uiuc_ticket_class_id],
        }
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
    except requests.RequestException as e:
        raise EventbriteError(f"Eventbrite request failed: {e}")

    if not response.ok:
        raise EventbriteError(f"Eventbrite API error (status {response.status_code})")
    return response.json()


def create_discount(targeted_id, ticket_type):
    """
    Create a single-use access code that reveals the hidden, $0 UIUC ticket
    class for the given ticket type, tagged with a short hash of the
    delegate's opaque eduPersonTargetedID (there's no netid/email to scope
    it to via Shibboleth — see shibboleth_auth; the Eventbrite ticket itself
    asks for NetID directly via its own custom question instead).

    Returns a dict: {code, eventbrite_discount_id}.
    Raises EventbriteError if the ticket type is unrecognized or the API fails.
    """
    uiuc_ticket_class_id = settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS.get(ticket_type)
    event_id = settings.EVENTBRITE_EVENT_IDS.get(ticket_type)
    if uiuc_ticket_class_id is None or event_id is None:
        raise EventbriteError(f"Unknown ticket type '{ticket_type}'")

    code = f"UIUC_{_short_id(targeted_id)}_{_random_suffix()}"

    if settings.EVENTBRITE_MOCK_MODE:
        return {"code": code, "eventbrite_discount_id": f"MOCK_DISCOUNT_{code}"}

    raw = _real_create_discount(event_id, uiuc_ticket_class_id, code)
    return {"code": code, "eventbrite_discount_id": raw["id"]}
