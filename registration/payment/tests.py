import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from registration.models import Delegate, UIUCPromoCode


class DelegateStatusGETTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("registration:delegate_status")

    def test_unauthenticated(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_authenticated"])

    def test_authenticated_no_promo_codes(self):
        user = User.objects.create_user(username="a@a.com", email="a@a.com", password="password123")
        Delegate.objects.create(user=user, is_uiuc_verified=True, uiuc_targeted_id="jsmith2")
        self.client.login(username="a@a.com", password="password123")

        response = self.client.get(self.url)
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertTrue(data["is_uiuc_verified"])
        self.assertEqual(data["payment_status"], Delegate.PaymentStatus.UNPAID)
        self.assertEqual(data["has_unredeemed_promo"], {})

    def test_authenticated_with_unredeemed_promo(self):
        user = User.objects.create_user(username="a@a.com", email="a@a.com", password="password123")
        delegate = Delegate.objects.create(user=user, is_uiuc_verified=True, uiuc_targeted_id="jsmith2")
        UIUCPromoCode.objects.create(
            delegate=delegate,
            ticket_type=Delegate.TicketType.WORKSHOP,
            code="UIUC_jsmith2_AAAA",
            eventbrite_discount_id="disc_1",
        )
        self.client.login(username="a@a.com", password="password123")

        response = self.client.get(self.url)
        data = response.json()
        self.assertEqual(data["has_unredeemed_promo"], {"workshop": "UIUC_jsmith2_AAAA"})


@override_settings(EVENTBRITE_MOCK_MODE=True)
class UIUCPromoCodePOSTTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("registration:uiuc_promo_code")

    def test_requires_authentication(self):
        response = self.client.post(self.url, {"ticket_type": "workshop"}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_requires_uiuc_verification(self):
        user = User.objects.create_user(username="a@a.com", email="a@a.com", password="password123")
        Delegate.objects.create(user=user, is_uiuc_verified=False)
        self.client.login(username="a@a.com", password="password123")

        response = self.client.post(self.url, {"ticket_type": "workshop"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_rejects_invalid_ticket_type(self):
        user = User.objects.create_user(username="a@a.com", email="a@a.com", password="password123")
        Delegate.objects.create(user=user, is_uiuc_verified=True, uiuc_targeted_id="jsmith2")
        self.client.login(username="a@a.com", password="password123")

        response = self.client.post(self.url, {"ticket_type": "not_a_tier"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_creates_code_first_time(self):
        user = User.objects.create_user(username="a@a.com", email="a@a.com", password="password123")
        Delegate.objects.create(user=user, is_uiuc_verified=True, uiuc_targeted_id="jsmith2")
        self.client.login(username="a@a.com", password="password123")

        response = self.client.post(self.url, {"ticket_type": "workshop"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["code"].startswith("UIUC_"))
        self.assertEqual(UIUCPromoCode.objects.count(), 1)

    def test_second_call_returns_same_code(self):
        user = User.objects.create_user(username="a@a.com", email="a@a.com", password="password123")
        Delegate.objects.create(user=user, is_uiuc_verified=True, uiuc_targeted_id="jsmith2")
        self.client.login(username="a@a.com", password="password123")

        first = self.client.post(self.url, {"ticket_type": "workshop"}, content_type="application/json").json()
        second = self.client.post(self.url, {"ticket_type": "workshop"}, content_type="application/json").json()

        self.assertEqual(first["code"], second["code"])
        self.assertEqual(UIUCPromoCode.objects.count(), 1)


@override_settings(EVENTBRITE_MOCK_MODE=True)
class VerifyPaymentPOSTTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("registration:verify_payment")
        self.user = User.objects.create_user(username="a@a.com", email="a@a.com", password="password123")
        self.delegate = Delegate.objects.create(user=self.user, is_uiuc_verified=True, uiuc_targeted_id="jsmith2")
        self.client.login(username="a@a.com", password="password123")

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(self.url, {"order_id": "MOCK_ORDER_workshop_none"}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_general_paid_order_succeeds(self):
        response = self.client.post(self.url, {"order_id": "MOCK_ORDER_workshop_none"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)

        self.delegate.refresh_from_db()
        self.assertEqual(self.delegate.payment_status, Delegate.PaymentStatus.PAID)
        self.assertEqual(self.delegate.ticket_type, Delegate.TicketType.WORKSHOP)
        self.assertEqual(self.delegate.eventbrite_order_id, "MOCK_ORDER_workshop_none")

    def test_self_reported_netid_is_saved(self):
        # Real Eventbrite order carrying an answer to the "NetID"
        # custom question — mock mode's fixed order encoding can't express
        # this, so get_order itself is patched instead.
        with patch(
            "registration.payment.views.eventbrite_client.get_order",
            return_value={
                "id": "real-order-1",
                "status": "placed",
                "event_id": "mock-event-id-workshop",
                "ticket_class_id": "mock-workshop-uiuc",
                "discount_code": None,
                "netid": "jsmith2",
            },
        ):
            response = self.client.post(
                self.url, {"order_id": "real-order-1"}, content_type="application/json"
            )
        self.assertEqual(response.status_code, 200)

        self.delegate.refresh_from_db()
        self.assertEqual(self.delegate.uiuc_netid_self_reported, "jsmith2")

    def test_uiuc_order_with_matching_promo_redeems_it(self):
        promo = UIUCPromoCode.objects.create(
            delegate=self.delegate,
            ticket_type=Delegate.TicketType.BUNDLE,
            code="UIUC_jsmith2_AAAA",
            eventbrite_discount_id="disc_1",
        )
        response = self.client.post(
            self.url, {"order_id": "MOCK_ORDER_bundle_UIUC_jsmith2_AAAA"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        promo.refresh_from_db()
        self.assertIsNotNone(promo.redeemed_at)
        self.assertEqual(promo.redeemed_order_id, "MOCK_ORDER_bundle_UIUC_jsmith2_AAAA")
        self.delegate.refresh_from_db()
        self.assertEqual(self.delegate.payment_status, Delegate.PaymentStatus.PAID)

    def test_order_with_someone_elses_promo_code_rejected(self):
        other_user = User.objects.create_user(username="b@b.com", email="b@b.com", password="password123")
        other_delegate = Delegate.objects.create(user=other_user, is_uiuc_verified=True, uiuc_targeted_id="bwilson")
        UIUCPromoCode.objects.create(
            delegate=other_delegate,
            ticket_type=Delegate.TicketType.BUNDLE,
            code="UIUC_bwilson_ZZZZ",
            eventbrite_discount_id="disc_2",
        )

        response = self.client.post(
            self.url, {"order_id": "MOCK_ORDER_bundle_UIUC_bwilson_ZZZZ"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

        self.delegate.refresh_from_db()
        self.assertEqual(self.delegate.payment_status, Delegate.PaymentStatus.UNPAID)

    @override_settings(EVENTBRITE_EVENT_IDS={"workshop": "a-different-event", "variety_show": "a-different-event", "bundle": "a-different-event"})
    def test_order_for_different_event_rejected(self):
        response = self.client.post(
            self.url, {"order_id": "MOCK_ORDER_workshop_none"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_unrecognized_order_rejected(self):
        response = self.client.post(
            self.url, {"order_id": "totally-bogus"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 503)

    def test_resubmitting_same_order_is_idempotent(self):
        self.client.post(self.url, {"order_id": "MOCK_ORDER_workshop_none"}, content_type="application/json")
        response = self.client.post(self.url, {"order_id": "MOCK_ORDER_workshop_none"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_submitting_different_order_while_already_paid_rejected(self):
        self.client.post(self.url, {"order_id": "MOCK_ORDER_workshop_none"}, content_type="application/json")
        response = self.client.post(self.url, {"order_id": "MOCK_ORDER_bundle_none"}, content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_order_id_already_used_by_another_delegate_rejected(self):
        other_user = User.objects.create_user(username="b@b.com", email="b@b.com", password="password123")
        Delegate.objects.create(
            user=other_user,
            eventbrite_order_id="MOCK_ORDER_workshop_none",
            payment_status=Delegate.PaymentStatus.PAID,
            ticket_type=Delegate.TicketType.WORKSHOP,
        )

        response = self.client.post(
            self.url, {"order_id": "MOCK_ORDER_workshop_none"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 409)

    def test_pending_order_rejected(self):
        response = self.client.post(
            self.url, {"order_id": "MOCK_ORDER_PENDING_workshop_none"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

        self.delegate.refresh_from_db()
        self.assertEqual(self.delegate.payment_status, Delegate.PaymentStatus.UNPAID)


@override_settings(EVENTBRITE_MOCK_MODE=True)
class FindMyOrderGETTest(TestCase):
    FIND = "registration.payment.views.eventbrite_client.find_orders_by_email"

    def setUp(self):
        self.client = Client()
        self.url = reverse("registration:find_my_order")
        self.user = User.objects.create_user(
            username="jane@example.com", email="jane@example.com", password="password123"
        )
        self.delegate = Delegate.objects.create(user=self.user)
        self.client.login(username="jane@example.com", password="password123")

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_already_paid_skips_eventbrite(self):
        self.delegate.payment_status = Delegate.PaymentStatus.PAID
        self.delegate.eventbrite_order_id = "1111111111"
        self.delegate.save()

        with patch(self.FIND) as find:
            response = self.client.get(self.url)

        find.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"already_paid": True, "orders": []})

    def test_no_orders(self):
        with patch(self.FIND, return_value=[]) as find:
            response = self.client.get(self.url)

        find.assert_called_once_with("jane@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"already_paid": False, "orders": []})

    def test_one_order_is_masked(self):
        with patch(self.FIND, return_value=[{"id": "12345679203", "ticket_type": "bundle"}]):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"already_paid": False, "orders": [{"order_hint": "…9203", "ticket_type": "bundle"}]},
        )
        # The full order number is the only proof of ownership (account
        # emails aren't verified) — it must never leave the server here.
        self.assertNotIn(b"12345679203", response.content)
        self.assertNotIn("12345679203", response.content.decode("utf-8"))

    def test_two_orders_give_two_hints(self):
        with patch(
            self.FIND,
            return_value=[
                {"id": "11110001234", "ticket_type": "workshop"},
                {"id": "22220005678", "ticket_type": "bundle"},
            ],
        ):
            response = self.client.get(self.url)

        self.assertEqual(
            response.json()["orders"],
            [
                {"order_hint": "…1234", "ticket_type": "workshop"},
                {"order_hint": "…5678", "ticket_type": "bundle"},
            ],
        )

    def test_order_linked_to_another_delegate_excluded(self):
        other = User.objects.create_user(username="b@b.com", email="b@b.com", password="password123")
        Delegate.objects.create(
            user=other,
            payment_status=Delegate.PaymentStatus.PAID,
            eventbrite_order_id="11110001234",
            ticket_type=Delegate.TicketType.WORKSHOP,
        )

        with patch(
            self.FIND,
            return_value=[
                {"id": "11110001234", "ticket_type": "workshop"},
                {"id": "22220005678", "ticket_type": "bundle"},
            ],
        ):
            response = self.client.get(self.url)

        self.assertEqual(
            response.json()["orders"], [{"order_hint": "…5678", "ticket_type": "bundle"}]
        )

    def test_eventbrite_error_returns_503(self):
        from registration.payment.eventbrite_client import EventbriteError

        with patch(self.FIND, side_effect=EventbriteError("down")):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"message": "Could not check Eventbrite"})

    def test_mock_mode_end_to_end(self):
        # No patching: exercises the real mock branch of the client.
        user = User.objects.create_user(
            username="j+hasorder@example.com", email="j+hasorder@example.com", password="password123"
        )
        Delegate.objects.create(user=user)
        self.client.login(username="j+hasorder@example.com", password="password123")

        response = self.client.get(self.url)

        self.assertEqual(
            response.json(),
            {"already_paid": False, "orders": [{"order_hint": "…none", "ticket_type": "workshop"}]},
        )
        self.assertNotIn("MOCK_ORDER_workshop_none", response.content.decode("utf-8"))

    def test_post_not_allowed(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 405)
