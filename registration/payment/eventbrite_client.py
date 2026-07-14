"""
Thin wrapper around the Eventbrite API for order verification and UIUC
discount-code generation. Supports EVENTBRITE_MOCK_MODE for local
development without real Eventbrite credentials, mirroring
shibboleth_auth's SAML_MOCK_MODE pattern.

NOTE: field/parameter names used in the real-mode functions below
(percent_off, quantity_available, order status values, the exact
Discounts/Orders endpoint shapes) are our best guess at the real
Eventbrite API and should be verified against Eventbrite's live docs
before this is used against a real event.
"""

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


# ---------------------------------------------------------------------------
# get_order
# ---------------------------------------------------------------------------

def _mock_get_order(order_id):
    """
    Mock orders are encoded as MOCK_ORDER_<ticket_type>_<discount_code_or_none>.
    Matched against known ticket type keys (not a blind split) because
    ticket type names like "variety_show" contain underscores themselves.

    Always returns event_id="mock-event-id" — a fixed sentinel, not the
    live EVENTBRITE_EVENT_ID setting. A real order's event_id is fixed at
    creation time regardless of what's currently configured; echoing the
    live setting here would make the wrong-event rejection path in
    verify_payment untestable (the comparison could never fail).

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
            discount_code = rest if rest != "none" else None
            return {
                "id": order_id,
                "status": status,
                "event_id": "mock-event-id",
                "ticket_class_id": settings.EVENTBRITE_TICKET_CLASS_IDS[ticket_type],
                "discount_code": discount_code,
            }

    raise EventbriteError(f"Unknown mock ticket type in order_id '{order_id}'")


def _real_get_order(order_id):
    if not order_id.isdigit():
        raise EventbriteError(f"Invalid order_id format: '{order_id}'")

    url = f"https://www.eventbriteapi.com/v3/orders/{order_id}/"
    headers = {"Authorization": f"Bearer {settings.EVENTBRITE_API_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, params={"expand": "attendees"}, timeout=10)
    except requests.RequestException as e:
        raise EventbriteError(f"Eventbrite request failed: {e}")

    if response.status_code == 404:
        raise EventbriteError(f"Order {order_id} not found")
    if not response.ok:
        raise EventbriteError(f"Eventbrite API error (status {response.status_code})")

    raw = response.json()
    attendees = raw.get("attendees", [])
    ticket_class_id = attendees[0]["ticket_class_id"] if attendees else None
    return {
        "id": raw["id"],
        "status": raw.get("status"),
        "event_id": raw.get("event_id"),
        "ticket_class_id": ticket_class_id,
        "discount_code": raw.get("promo_code") or None,
    }


def get_order(order_id):
    """
    Fetch and normalize an Eventbrite order.

    Returns a dict: {id, status, event_id, ticket_class_id, discount_code}.
    Raises EventbriteError if the order can't be found or the API fails.
    """
    if settings.EVENTBRITE_MOCK_MODE:
        return _mock_get_order(order_id)
    return _real_get_order(order_id)


# ---------------------------------------------------------------------------
# create_discount
# ---------------------------------------------------------------------------

def _real_create_discount(ticket_class_id, code):
    url = f"https://www.eventbriteapi.com/v3/events/{settings.EVENTBRITE_EVENT_ID}/discounts/"
    headers = {"Authorization": f"Bearer {settings.EVENTBRITE_API_TOKEN}"}
    payload = {
        "discount.code": code,
        "discount.type": "coded",
        "discount.percent_off": "100",
        "discount.quantity_available": "1",
        "discount.ticket_class_ids": [ticket_class_id],
    }
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=10)
    except requests.RequestException as e:
        raise EventbriteError(f"Eventbrite request failed: {e}")

    if not response.ok:
        raise EventbriteError(f"Eventbrite API error (status {response.status_code})")
    return response.json()


def create_discount(netid, ticket_type):
    """
    Create a single-use, 100%-off discount code for the given ticket type.

    Returns a dict: {code, eventbrite_discount_id}.
    Raises EventbriteError if the ticket type is unrecognized or the API fails.
    """
    ticket_class_id = settings.EVENTBRITE_TICKET_CLASS_IDS.get(ticket_type)
    if ticket_class_id is None:
        raise EventbriteError(f"Unknown ticket type '{ticket_type}'")

    code = f"UIUC_{netid}_{_random_suffix()}"

    if settings.EVENTBRITE_MOCK_MODE:
        return {"code": code, "eventbrite_discount_id": f"MOCK_DISCOUNT_{code}"}

    raw = _real_create_discount(ticket_class_id, code)
    return {"code": code, "eventbrite_discount_id": raw["id"]}
