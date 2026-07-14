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
    def test_creates_code_with_netid(self):
        result = eventbrite_client.create_discount("jsmith2", "workshop")
        self.assertIn("jsmith2", result["code"])
        self.assertTrue(result["code"].startswith("UIUC_"))
        self.assertTrue(result["eventbrite_discount_id"])

    def test_unknown_ticket_type_raises(self):
        with self.assertRaises(EventbriteError):
            eventbrite_client.create_discount("jsmith2", "not_a_real_tier")
