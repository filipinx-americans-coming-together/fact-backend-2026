from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TestCase, override_settings

from registration.payment import eventbrite_client
from registration.payment.eventbrite_client import EventbriteError


@override_settings(EVENTBRITE_MOCK_MODE=True, EVENTBRITE_EVENT_ID="mock-event-id")
class GetOrderMockTest(TestCase):
    def test_valid_mock_order_no_discount(self):
        order = eventbrite_client.get_order("MOCK_ORDER_workshop_none")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(order["event_id"], "mock-event-id")
        self.assertIsNone(order["discount_code"])

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
            order["ticket_class_id"], settings.EVENTBRITE_TICKET_CLASS_IDS["variety_show"]
        )
        self.assertIsNone(order["discount_code"])

    def test_valid_mock_order_variety_show_with_discount(self):
        order = eventbrite_client.get_order("MOCK_ORDER_variety_show_UIUC_jsmith2_ZZZZ")
        self.assertEqual(order["discount_code"], "UIUC_jsmith2_ZZZZ")

    def test_valid_mock_order_pending_status(self):
        order = eventbrite_client.get_order("MOCK_ORDER_PENDING_workshop_none")
        self.assertEqual(order["status"], "pending")
        self.assertEqual(
            order["ticket_class_id"], settings.EVENTBRITE_TICKET_CLASS_IDS["workshop"]
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
    EVENTBRITE_EVENT_ID="event-456",
)
class RealCreateDiscountRequestShapeTest(TestCase):
    """
    Locks in the Discounts request shape against the real Eventbrite API v3
    spec: organization-scoped URL, JSON body (not form-encoded) nested
    under "discount", with event_id inside the body since the URL itself
    no longer carries it.
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
        self.assertEqual(discount["event_id"], "event-456")
        self.assertEqual(discount["ticket_class_ids"], [settings.EVENTBRITE_TICKET_CLASS_IDS["workshop"]])
        self.assertEqual(result["eventbrite_discount_id"], "discount-789")

    @patch("registration.payment.eventbrite_client.requests.post")
    def test_raises_on_error_response(self, mock_post):
        mock_post.return_value = Mock(ok=False, status_code=400)

        with self.assertRaises(EventbriteError):
            eventbrite_client.create_discount("opaque-targeted-id-1", "workshop")


@override_settings(EVENTBRITE_MOCK_MODE=False)
class RealGetOrderRequestShapeTest(TestCase):
    @patch("registration.payment.eventbrite_client.requests.get")
    def test_gets_order_by_id_url_with_attendees_expansion(self, mock_get):
        mock_get.return_value = Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "id": "12345",
                "status": "placed",
                "event_id": "event-456",
                "promo_code": "UIUC_ABC_XYZ",
                "attendees": [{"ticket_class_id": "ticket-1"}],
            },
        )

        order = eventbrite_client.get_order("12345")

        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://www.eventbriteapi.com/v3/orders/12345/")
        self.assertEqual(kwargs["params"], {"expand": "attendees"})
        self.assertEqual(order["ticket_class_id"], "ticket-1")
        self.assertEqual(order["discount_code"], "UIUC_ABC_XYZ")
