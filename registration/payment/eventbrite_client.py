"""
Thin wrapper around the Eventbrite API for order verification and UIUC
discount-code generation. Supports EVENTBRITE_MOCK_MODE for local
development without real Eventbrite credentials, mirroring
shibboleth_auth's SAML_MOCK_MODE pattern.

Endpoint shapes verified against Eventbrite's public API v3 spec
(eventbrite-api-v3-public.apib): Order retrieval at GET /orders/{id}/,
Discount creation at POST /organizations/{organization_id}/discounts/
with a JSON body nested under "discount", Order listing at
GET /events/{event_id}/orders/ ("List Orders by Event ID") with
only_emails/status filters and continuation-token pagination.
"""

import hashlib
import logging
import secrets
import string

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


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
# q323798414). Matched as a case-insensitive prefix, not exact text: the
# question was later reworded to "NetID (the part before @illinois.edu,
# not your UIN)" to stop people entering UINs, and an exact match silently
# stopped capturing answers.
NETID_QUESTION_PREFIX = "netid"


def _is_netid_question(answer):
    return (answer.get("question") or "").strip().lower().startswith(NETID_QUESTION_PREFIX)


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
        logger.error("Eventbrite get_order(%s) request failed: %s", order_id, e)
        raise EventbriteError(f"Eventbrite request failed: {e}")

    if response.status_code == 404:
        logger.error("Eventbrite get_order(%s): order not found (404): %s", order_id, response.text)
        raise EventbriteError(f"Order {order_id} not found")
    if not response.ok:
        logger.error(
            "Eventbrite get_order(%s) failed with status %s: %s",
            order_id, response.status_code, response.text,
        )
        raise EventbriteError(f"Eventbrite API error (status {response.status_code})")

    raw = response.json()
    attendees = raw.get("attendees", [])
    ticket_class_id = attendees[0]["ticket_class_id"] if attendees else None
    promotional_code = attendees[0].get("promotional_code") if attendees else None
    answers = attendees[0].get("answers", []) if attendees else []
    netid = next(
        (a["answer"] for a in answers if _is_netid_question(a) and a.get("answer")),
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
        logger.error("Eventbrite create_discount(%s) request failed: %s", event_id, e)
        raise EventbriteError(f"Eventbrite request failed: {e}")

    if not response.ok:
        logger.error(
            "Eventbrite create_discount(%s) failed with status %s: %s",
            event_id, response.status_code, response.text,
        )
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


# ---------------------------------------------------------------------------
# resolve_ticket_type
# ---------------------------------------------------------------------------

def resolve_ticket_type(ticket_class_id):
    """
    Map an Eventbrite ticket_class_id to a Delegate.TicketType value, or
    None if it isn't one of ours. Shared by verify_payment/claim_order and
    find_orders_by_email so the mapping lives in one place.
    """
    # Checks both the paid, publicly-visible class and the hidden, $0 UIUC
    # class for each ticket type — an order can legitimately be either one.
    for ticket_type, class_id in settings.EVENTBRITE_TICKET_CLASS_IDS.items():
        if class_id == ticket_class_id:
            return ticket_type
    for ticket_type, class_id in settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS.items():
        if class_id == ticket_class_id:
            return ticket_type
    return None


# ---------------------------------------------------------------------------
# find_orders_by_email
# ---------------------------------------------------------------------------

# Ticket types that include workshops. A Variety-Show-only order must not
# stop someone from buying workshops, so it is never reported.
_WORKSHOP_TICKET_TYPES = ("workshop", "bundle")


def _mock_find_orders_by_email(email):
    """
    Deterministic mock: an email local-part containing "+hastwo" has two
    workshop-including orders, "+hasorder" has one, anything else none.
    The IDs are valid mock get_order IDs, so linking them through
    verify_payment works end to end in local dev.
    """
    local_part = email.split("@", 1)[0]
    if "+hastwo" in local_part:
        return [
            {"id": "MOCK_ORDER_workshop_none", "ticket_type": "workshop"},
            {"id": "MOCK_ORDER_bundle_none", "ticket_type": "bundle"},
        ]
    if "+hasorder" in local_part:
        return [{"id": "MOCK_ORDER_workshop_none", "ticket_type": "workshop"}]
    return []


def _real_list_event_orders(event_id, email):
    url = f"https://www.eventbriteapi.com/v3/events/{event_id}/orders/"
    headers = {"Authorization": f"Bearer {settings.EVENTBRITE_API_TOKEN}"}
    params = {"only_emails": email, "status": "active", "expand": "attendees"}
    orders = []
    while True:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
        except requests.RequestException as e:
            logger.error("Eventbrite list orders (event %s) request failed: %s", event_id, e)
            raise EventbriteError(f"Eventbrite request failed: {e}")

        if not response.ok:
            logger.error(
                "Eventbrite list orders (event %s) failed with status %s: %s",
                event_id, response.status_code, response.text,
            )
            raise EventbriteError(f"Eventbrite API error (status {response.status_code})")

        raw = response.json()
        orders.extend(raw.get("orders", []))
        pagination = raw.get("pagination") or {}
        if not pagination.get("has_more_items") or not pagination.get("continuation"):
            return orders
        params = {**params, "continuation": pagination["continuation"]}


def _order_workshop_ticket_type(raw_order):
    # An order can hold several attendees; report it if any of them holds a
    # workshop-including ticket.
    for attendee in raw_order.get("attendees", []):
        ticket_type = resolve_ticket_type(attendee.get("ticket_class_id"))
        if ticket_type in _WORKSHOP_TICKET_TYPES:
            return ticket_type
    return None


def find_orders_by_email(email):
    """
    Find active FACT orders placed with this email that include workshops
    (workshop or bundle ticket), across every configured event.

    Returns a list of {"id": str, "ticket_type": str}. The caller must never
    expose the full id to the client (see find_my_order).
    Raises EventbriteError if any API call fails.
    """
    # An empty only_emails filter could match every order on the event, so
    # an account without an email never queries Eventbrite at all.
    email = (email or "").strip()
    if not email:
        return []

    if settings.EVENTBRITE_MOCK_MODE:
        return _mock_find_orders_by_email(email)

    found = []
    # variety_show and bundle share one event; query each event once.
    for event_id in dict.fromkeys(settings.EVENTBRITE_EVENT_IDS.values()):
        for raw_order in _real_list_event_orders(event_id, email):
            ticket_type = _order_workshop_ticket_type(raw_order)
            if ticket_type is not None:
                found.append({"id": str(raw_order["id"]), "ticket_type": ticket_type})
    return found
