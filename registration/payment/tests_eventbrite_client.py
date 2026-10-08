from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from registration.payment import eventbrite_client
from registration.payment.eventbrite_client import EventbriteError

class ResolveEventbriteIds(TestCase):
    def test_variety_show(self):
        self.assertEqual(["vs-floor", "vs-balcony"], settings.EVENTBRITE_TICKET_CLASS_IDS["variety_show"])
    def test_workshop(self):
        self.assertEqual(["workshop"], settings.EVENTBRITE_TICKET_CLASS_IDS["workshop"])
    def test_bundle(self):
        self.assertEqual(["bundle-floor", "bundle-balcony"], settings.EVENTBRITE_TICKET_CLASS_IDS["bundle"])
    def test_uiuc_variety_show(self):
        self.assertEqual(["vs-floor-uiuc", "vs-balcony-uiuc"], settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS["variety_show"])
    def test_uiuc_workshop(self):
        self.assertEqual(["workshop-uiuc"], settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS["workshop"])
    def test_uiuc_bundle(self):
        self.assertEqual(["bundle-floor-uiuc", "bundle-balcony-uiuc"], settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS["bundle"])

    def test_resolve_variety_show(self):
        ticket_class_ids = ["vs-floor", "vs-balcony", "vs-floor-uiuc", "vs-balcony-uiuc"]
        for id in ticket_class_ids:
            res = eventbrite_client.resolve_ticket_type(id)
            self.assertEqual(res, "variety_show")
    def test_resolve_workshop(self):
        ticket_class_ids = ["workshop", "workshop-uiuc"]
        for id in ticket_class_ids:
            res = eventbrite_client.resolve_ticket_type(id)
            self.assertEqual(res, "workshop")
    def test_resolve_bundle(self):
        ticket_class_ids = ["bundle-floor", "bundle-balcony", "bundle-floor-uiuc", "bundle-balcony-uiuc"]
        for id in ticket_class_ids:
            res = eventbrite_client.resolve_ticket_type(id)
            self.assertEqual(res, "bundle")

@override_settings(EVENTBRITE_MOCK_MODE=True)
class GetOrderMockTest(TestCase):
    def test_valid_mock_order_no_discount(self):
        order = eventbrite_client.get_order("MOCK_ORDER_workshop_none")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(order["event_id"], "mock-event-id-workshop")
        self.assertIsNone(order["discount_code"])

    def test_valid_mock_order_uses_hidden_uiuc_ticket_class(self):
        # FREE_ marker selects the hidden $0 UIUC class instead of the
        # paid one — mirrors the real two-classes-per-type setup.
        order = eventbrite_client.get_order("MOCK_ORDER_bundle_FREE_none")
        self.assertEqual(
            order["ticket_class_id"], settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS["bundle"][0]
        )

    def test_valid_mock_order_with_discount(self):
        order = eventbrite_client.get_order("MOCK_ORDER_bundle_UIUC_jsmith2_X9B4")
        self.assertEqual(order["discount_code"], "UIUC_jsmith2_X9B4")

    def test_unrecognized_mock_order_raises(self):
        with self.assertRaises(EventbriteError):
            eventbrite_client.get_order("not-a-mock-order")

    def test_unknown_ticket_type_in_mock_order_raises(self):
        with self.assertRaises(EventbriteError):
            eventbrite_client.get_order("MOCK_ORDER_not_a_real_tier_none")

    def test_valid_mock_order_variety_show_ticket_type(self):
        order = eventbrite_client.get_order("MOCK_ORDER_variety_show_none")
        self.assertEqual(
            order["ticket_class_id"], settings.EVENTBRITE_TICKET_CLASS_IDS["variety_show"][0]
        )
        self.assertIsNone(order["discount_code"])

    def test_valid_mock_order_variety_show_with_discount(self):
        order = eventbrite_client.get_order("MOCK_ORDER_variety_show_UIUC_jsmith2_ZZZZ")
        self.assertEqual(order["discount_code"], "UIUC_jsmith2_ZZZZ")

    def test_valid_mock_order_pending_status(self):
        order = eventbrite_client.get_order("MOCK_ORDER_PENDING_workshop_none")
        self.assertEqual(order["status"], "pending")
        self.assertEqual(
            order["ticket_class_id"], settings.EVENTBRITE_TICKET_CLASS_IDS["workshop"][0]
        )

    @override_settings(EVENTBRITE_MOCK_MODE=False)
    def test_real_get_order_rejects_non_numeric_order_id(self):
        with self.assertRaises(EventbriteError):
            eventbrite_client.get_order("not-numeric-id")


@override_settings(EVENTBRITE_MOCK_MODE=True)
class CreateDiscountMockTest(TestCase):
    def test_creates_code_from_targeted_id(self):
        result = eventbrite_client.create_discount("opaque-targeted-id-1", "workshop")
        self.assertTrue(result["code"].startswith("UIUC_"))
        self.assertTrue(result["eventbrite_discount_id"])
        # the raw opaque ID itself must never appear in the code
        self.assertNotIn("opaque-targeted-id-1", result["code"])

    def test_same_targeted_id_gives_same_code_tag(self):
        # the hash-derived middle segment is stable for the same targeted_id,
        # even though the random suffix differs each call
        result1 = eventbrite_client.create_discount("opaque-targeted-id-1", "workshop")
        result2 = eventbrite_client.create_discount("opaque-targeted-id-1", "workshop")
        tag1 = result1["code"].split("_")[1]
        tag2 = result2["code"].split("_")[1]
        self.assertEqual(tag1, tag2)

    def test_different_targeted_ids_give_different_code_tags(self):
        result1 = eventbrite_client.create_discount("opaque-targeted-id-1", "workshop")
        result2 = eventbrite_client.create_discount("opaque-targeted-id-2", "workshop")
        tag1 = result1["code"].split("_")[1]
        tag2 = result2["code"].split("_")[1]
        self.assertNotEqual(tag1, tag2)

    def test_unknown_ticket_type_raises(self):
        with self.assertRaises(EventbriteError):
            eventbrite_client.create_discount("opaque-targeted-id-1", "not_a_real_tier")


@override_settings(
    EVENTBRITE_MOCK_MODE=False,
    EVENTBRITE_ORGANIZATION_ID="org-123",
    EVENTBRITE_EVENT_IDS={"workshop": "event-456", "variety_show": "event-789", "bundle": "event-789"},
)
class RealCreateDiscountRequestShapeTest(TestCase):
    """
    Locks in the Discounts request shape against the real Eventbrite API v3
    spec: organization-scoped URL, JSON body (not form-encoded) nested
    under "discount", with event_id inside the body since the URL itself
    no longer carries it. It's an "access" discount revealing the hidden
    UIUC ticket class, not a percent-off on the paid one — see
    eventbrite_client.create_discount's docstring for why.
    """

    @patch("registration.payment.eventbrite_client.requests.post")
    def test_posts_to_organization_scoped_url_with_nested_json_body(self, mock_post):
        mock_post.return_value = Mock(ok=True, json=lambda: {"id": "discount-789"})

        result = eventbrite_client.create_discount("opaque-targeted-id-1", "workshop")

        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://www.eventbriteapi.com/v3/organizations/org-123/discounts/")
        self.assertNotIn("data", kwargs)
        self.assertIn("json", kwargs)
        discount = kwargs["json"]["discount"]
        self.assertEqual(discount["type"], "access")
        self.assertNotIn("percent_off", discount)
        self.assertEqual(discount["event_id"], "event-456")
        self.assertEqual(
            discount["ticket_class_ids"], [settings.EVENTBRITE_UIUC_TICKET_CLASS_IDS["workshop"]]
        )
        self.assertEqual(result["eventbrite_discount_id"], "discount-789")

    @patch("registration.payment.eventbrite_client.requests.post")
    def test_raises_on_error_response(self, mock_post):
        mock_post.return_value = Mock(ok=False, status_code=400)

        with self.assertRaises(EventbriteError):
            eventbrite_client.create_discount("opaque-targeted-id-1", "workshop")


@override_settings(EVENTBRITE_MOCK_MODE=False)
class RealGetOrderNotFoundTest(TestCase):
    # Verified against the live API: an unknown order ID returns 404
    # NOT_FOUND, and a real order belonging to another organizer returns
    # 403 NOT_AUTHORIZED. Both mean "not one of our orders", not an outage.
    @patch("registration.payment.eventbrite_client.requests.get")
    def test_404_raises_order_not_found(self, mock_get):
        mock_get.return_value = Mock(ok=False, status_code=404, text="NOT_FOUND")
        with self.assertRaises(eventbrite_client.OrderNotFoundError):
            eventbrite_client.get_order("12345")

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_403_raises_order_not_found(self, mock_get):
        mock_get.return_value = Mock(ok=False, status_code=403, text="NOT_AUTHORIZED")
        with self.assertRaises(eventbrite_client.OrderNotFoundError):
            eventbrite_client.get_order("12345")

    def test_non_numeric_id_raises_order_not_found(self):
        with self.assertRaises(eventbrite_client.OrderNotFoundError):
            eventbrite_client.get_order("abc")

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_server_error_is_not_order_not_found(self, mock_get):
        mock_get.return_value = Mock(ok=False, status_code=500, text="boom")
        with self.assertRaises(EventbriteError) as ctx:
            eventbrite_client.get_order("12345")
        self.assertNotIsInstance(ctx.exception, eventbrite_client.OrderNotFoundError)


class GetOrderMockNotFoundTest(TestCase):
    def test_non_mock_id_raises_order_not_found(self):
        with self.assertRaises(eventbrite_client.OrderNotFoundError):
            eventbrite_client.get_order("totally-bogus")


@override_settings(EVENTBRITE_MOCK_MODE=False)
class RealGetOrderRequestShapeTest(TestCase):
    @patch("registration.payment.eventbrite_client.requests.get")
    def test_gets_order_by_id_url_with_attendees_expansion(self, mock_get):
        # The Order object's own documented `promo_code` field is a red
        # herring: verified against a live 100%-off order, it comes back
        # null even when a code was used. The real value only appears via
        # the nested attendees.promotional_code expansion, as {code: ...}
        # on each attendee — that's what discount_code is read from below.
        mock_get.return_value = Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "id": "12345",
                "status": "placed",
                "event_id": "event-456",
                "promo_code": None,
                "attendees": [
                    {
                        "ticket_class_id": "ticket-1",
                        "promotional_code": {"code": "UIUC_ABC_XYZ"},
                        "answers": [
                            {"question_id": "999", "question": "NetID", "answer": "jsmith2"},
                            {"question_id": "998", "question": "T-shirt size", "answer": "M"},
                        ],
                    }
                ],
            },
        )

        order = eventbrite_client.get_order("12345")

        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://www.eventbriteapi.com/v3/orders/12345/")
        self.assertEqual(
            kwargs["params"], {"expand": "attendees,attendees.promotional_code,attendees.answers"}
        )
        self.assertEqual(order["ticket_class_id"], "ticket-1")
        self.assertEqual(order["discount_code"], "UIUC_ABC_XYZ")
        self.assertEqual(order["netid"], "jsmith2")

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_reworded_netid_question_still_matches(self, mock_get):
        # The live question was reworded to steer people away from typing
        # their UIN; the answer must still be picked up.
        mock_get.return_value = Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "id": "12345",
                "status": "placed",
                "event_id": "event-456",
                "attendees": [
                    {
                        "ticket_class_id": "ticket-1",
                        "answers": [
                            {
                                "question_id": "999",
                                "question": "NetID (the part before @illinois.edu, not your UIN)",
                                "answer": "jsmith2",
                            },
                        ],
                    }
                ],
            },
        )

        order = eventbrite_client.get_order("12345")
        self.assertEqual(order["netid"], "jsmith2")

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_missing_netid_answer_is_none(self, mock_get):
        mock_get.return_value = Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "id": "12345",
                "status": "placed",
                "event_id": "event-456",
                "attendees": [{"ticket_class_id": "ticket-1", "answers": []}],
            },
        )

        order = eventbrite_client.get_order("12345")
        self.assertIsNone(order["netid"])


@override_settings(EVENTBRITE_MOCK_MODE=True)
class FindOrdersByEmailMockTest(TestCase):
    def test_plain_email_has_no_orders(self):
        self.assertEqual(eventbrite_client.find_orders_by_email("a@a.com"), [])

    def test_hasorder_email_returns_one_workshop_order(self):
        orders = eventbrite_client.find_orders_by_email("jane+hasorder@example.com")
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["ticket_type"], "workshop")
        # The mock ID must be one mock get_order accepts, so linking it
        # through verify_payment works end to end in local dev.
        self.assertEqual(eventbrite_client.get_order(orders[0]["id"])["status"], "placed")

    def test_hastwo_email_returns_two_orders(self):
        orders = eventbrite_client.find_orders_by_email("jane+hastwo@example.com")
        self.assertEqual(len(orders), 2)
        self.assertEqual(len({o["id"] for o in orders}), 2)


_FIND_SETTINGS = dict(
    EVENTBRITE_MOCK_MODE=False,
    EVENTBRITE_API_TOKEN="token-abc",
    EVENTBRITE_EVENT_IDS={"workshop": "event-ws", "variety_show": "event-vs", "bundle": "event-vs"},
    EVENTBRITE_TICKET_CLASS_IDS={"variety_show": "tc-vs", "workshop": "tc-ws", "bundle": "tc-bundle"},
    EVENTBRITE_UIUC_TICKET_CLASS_IDS={
        "variety_show": "tc-vs-uiuc", "workshop": "tc-ws-uiuc", "bundle": "tc-bundle-uiuc",
    },
)


def _orders_page(orders, continuation=None):
    pagination = {"has_more_items": continuation is not None}
    if continuation is not None:
        pagination["continuation"] = continuation
    return Mock(ok=True, status_code=200, json=lambda: {"pagination": pagination, "orders": orders})


def _order(order_id, *ticket_class_ids):
    return {
        "id": order_id,
        "status": "placed",
        "attendees": [{"ticket_class_id": tc} for tc in ticket_class_ids],
    }


@override_settings(**_FIND_SETTINGS)
class RealFindOrdersByEmailTest(TestCase):
    """
    GET /events/{event_id}/orders/ ("List Orders by Event ID" in the v3
    spec): only_emails filters by the order owner's email, status=active
    is "Attending Order", and the list is paginated with a continuation
    token (pagination.has_more_items / pagination.continuation).
    """

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_queries_each_distinct_event_once_with_email_filter(self, mock_get):
        mock_get.return_value = _orders_page([])

        eventbrite_client.find_orders_by_email("jane@example.com")

        urls = [c.args[0] for c in mock_get.call_args_list]
        self.assertEqual(
            sorted(urls),
            [
                "https://www.eventbriteapi.com/v3/events/event-vs/orders/",
                "https://www.eventbriteapi.com/v3/events/event-ws/orders/",
            ],
        )
        for c in mock_get.call_args_list:
            self.assertEqual(c.kwargs["params"]["only_emails"], "jane@example.com")
            self.assertEqual(c.kwargs["params"]["status"], "active")
            self.assertEqual(c.kwargs["params"]["expand"], "attendees")
            self.assertNotIn("continuation", c.kwargs["params"])
            self.assertEqual(c.kwargs["headers"], {"Authorization": "Bearer token-abc"})

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_follows_pagination(self, mock_get):
        def fake_get(url, headers, params, timeout):
            if "event-ws" not in url:
                return _orders_page([])
            if params.get("continuation") == "page-2":
                return _orders_page([_order("222", "tc-ws")])
            return _orders_page([_order("111", "tc-ws")], continuation="page-2")

        mock_get.side_effect = fake_get

        orders = eventbrite_client.find_orders_by_email("jane@example.com")

        self.assertEqual(sorted(o["id"] for o in orders), ["111", "222"])

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_resolves_paid_and_uiuc_ticket_classes(self, mock_get):
        def fake_get(url, headers, params, timeout):
            if "event-ws" in url:
                return _orders_page([_order("111", "tc-ws-uiuc")])
            return _orders_page([_order("222", "tc-bundle")])

        mock_get.side_effect = fake_get

        orders = eventbrite_client.find_orders_by_email("jane@example.com")

        self.assertEqual(
            sorted(orders, key=lambda o: o["id"]),
            [{"id": "111", "ticket_type": "workshop"}, {"id": "222", "ticket_type": "bundle"}],
        )

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_variety_show_only_and_unknown_orders_excluded(self, mock_get):
        def fake_get(url, headers, params, timeout):
            if "event-vs" in url:
                return _orders_page([
                    _order("333", "tc-vs"),
                    _order("444", "tc-vs-uiuc"),
                    _order("555", "tc-something-else"),
                ])
            return _orders_page([])

        mock_get.side_effect = fake_get

        self.assertEqual(eventbrite_client.find_orders_by_email("jane@example.com"), [])

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_raises_on_error_response(self, mock_get):
        mock_get.return_value = Mock(ok=False, status_code=500, text="boom")

        with self.assertRaises(EventbriteError):
            eventbrite_client.find_orders_by_email("jane@example.com")

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_blank_email_never_queries_eventbrite(self, mock_get):
        # An empty only_emails filter could match every order on the event;
        # an account with no email must simply have no orders.
        self.assertEqual(eventbrite_client.find_orders_by_email(""), [])
        self.assertEqual(eventbrite_client.find_orders_by_email("   "), [])
        self.assertEqual(eventbrite_client.find_orders_by_email(None), [])
        mock_get.assert_not_called()

    @patch("registration.payment.eventbrite_client.requests.get")
    def test_raises_on_request_exception(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("down")

        with self.assertRaises(EventbriteError):
            eventbrite_client.find_orders_by_email("jane@example.com")
