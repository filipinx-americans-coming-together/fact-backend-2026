import json

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from registration.models import Delegate

VALID_ACCOUNT_FIELDS = {
    "f_name": "Jamie",
    "l_name": "Smith",
    "email": "jamie@example.com",
    "password": "correct horse battery staple",
    "pronouns": "they/them",
    "year": "Sophomore",
}


# RATELIMIT_ENABLE=False: this endpoint is IP-keyed (there's no user yet
# to key on), so every request in this test class would otherwise share
# one bucket and trip the real 10/h limit partway through the suite.
# The limiter itself isn't under test here — the endpoint's logic is.
@override_settings(EVENTBRITE_MOCK_MODE=True, RATELIMIT_ENABLE=False)
class ClaimOrderPOSTTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("registration:claim_order")

    def _post(self, order_id, **overrides):
        body = {"order_id": order_id, **VALID_ACCOUNT_FIELDS, **overrides}
        return self.client.post(self.url, body, content_type="application/json")

    def test_missing_order_id_rejected(self):
        response = self.client.post(self.url, {**VALID_ACCOUNT_FIELDS}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_unrecognized_order_rejected(self):
        response = self._post("totally-bogus")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(User.objects.exists())

    @override_settings(EVENTBRITE_EVENT_ID="a-different-event")
    def test_order_for_different_event_rejected(self):
        response = self._post("MOCK_ORDER_workshop_none")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_incomplete_order_rejected(self):
        response = self._post("MOCK_ORDER_PENDING_workshop_none")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_discount_coded_order_rejected(self):
        """
        The whole point of this endpoint is orders nobody had to be
        verified to buy — a discount code only exists via the
        Shibboleth-verified UIUC promo path, so an anonymous caller
        presenting one here must never be allowed to claim it.
        """
        response = self._post("MOCK_ORDER_workshop_UIUC_ABCD1234")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.exists())

    def test_successful_claim_creates_paid_account_and_logs_in(self):
        response = self._post("MOCK_ORDER_workshop_none")
        self.assertEqual(response.status_code, 200)

        user = User.objects.get(email="jamie@example.com")
        delegate = user.delegate
        self.assertEqual(delegate.payment_status, Delegate.PaymentStatus.PAID)
        self.assertEqual(delegate.ticket_type, Delegate.TicketType.WORKSHOP)
        self.assertEqual(delegate.eventbrite_order_id, "MOCK_ORDER_workshop_none")
        self.assertIsNotNone(delegate.payment_verified_at)

        # session should be authenticated as this user now
        status_response = self.client.get(reverse("registration:delegate_status"))
        self.assertTrue(status_response.json()["is_authenticated"])

    def test_duplicate_order_id_rejected(self):
        first = self._post("MOCK_ORDER_workshop_none")
        self.assertEqual(first.status_code, 200)
        self.client.logout()

        second = self._post("MOCK_ORDER_workshop_none", email="someone-else@example.com")
        self.assertEqual(second.status_code, 409)
        self.assertFalse(User.objects.filter(email="someone-else@example.com").exists())

    def test_invalid_email_rejected_and_order_not_consumed(self):
        response = self._post("MOCK_ORDER_workshop_none", email="not-an-email")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

        # the order must still be claimable after a failed attempt —
        # nothing should have been partially committed
        retry = self._post("MOCK_ORDER_workshop_none")
        self.assertEqual(retry.status_code, 200)

    def test_weak_password_rejected_and_order_not_consumed(self):
        response = self._post("MOCK_ORDER_workshop_none", password="123")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())

        retry = self._post("MOCK_ORDER_workshop_none")
        self.assertEqual(retry.status_code, 200)

    def test_duplicate_existing_email_rejected(self):
        User.objects.create_user(
            username="jamie@example.com", email="jamie@example.com", password="whatever123!"
        )
        response = self._post("MOCK_ORDER_workshop_none")
        self.assertEqual(response.status_code, 409)
        # the pre-existing account must not have gained a Delegate/payment
        # from this attempt — the order should still be claimable elsewhere
        refetched = User.objects.get(email="jamie@example.com")
        self.assertFalse(hasattr(refetched, "delegate"))
        retry = self._post("MOCK_ORDER_workshop_none", email="jamie2@example.com")
        self.assertEqual(retry.status_code, 200)

    def test_rejects_get(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)


@override_settings(EVENTBRITE_MOCK_MODE=True)
class ClaimOrderRateLimitTest(TestCase):
    """
    Rate limiting is under test here (unlike the class above, which
    disables it to isolate business-logic assertions).
    """

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.url = reverse("registration:claim_order")

    def _post(self, order_id, **overrides):
        body = {"order_id": order_id, **VALID_ACCOUNT_FIELDS, **overrides}
        return self.client.post(self.url, body, content_type="application/json")

    def test_repeated_attempts_on_one_order_id_get_blocked(self):
        """5/h per order_id — guessing/enumerating one specific order must
        get cut off quickly, even though each attempt uses a different
        email (so it isn't the email-uniqueness check causing the 4xx)."""
        for i in range(5):
            response = self._post("MOCK_ORDER_workshop_none", email=f"attempt{i}@example.com")
            # each of these fails validation-wise (see below) or succeeds
            # once — what matters is none of them is blocked by the limiter
            self.assertNotEqual(response.status_code, 403)

        blocked = self._post("MOCK_ORDER_workshop_none", email="attempt5@example.com")
        self.assertEqual(blocked.status_code, 403)

    def test_different_order_ids_are_not_cross_limited(self):
        """A different order_id must not inherit another order_id's
        exhausted budget — the limiter is scoped per order, not global."""
        for i in range(5):
            self._post("MOCK_ORDER_workshop_none", email=f"attempt{i}@example.com")

        response = self._post("MOCK_ORDER_bundle_none", email="different-order@example.com")
        self.assertNotEqual(response.status_code, 403)
