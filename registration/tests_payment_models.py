from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from registration.models import Delegate, UIUCPromoCode


class DelegatePaymentFieldsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a@a.com", email="a@a.com")

    def test_defaults(self):
        delegate = Delegate.objects.create(user=self.user)
        self.assertEqual(delegate.payment_status, Delegate.PaymentStatus.UNPAID)
        self.assertIsNone(delegate.ticket_type)
        self.assertIsNone(delegate.eventbrite_order_id)
        self.assertIsNone(delegate.payment_verified_at)

    def test_eventbrite_order_id_unique(self):
        other_user = User.objects.create_user(username="b@b.com", email="b@b.com")
        Delegate.objects.create(
            user=self.user,
            eventbrite_order_id="ORDER123",
            payment_status=Delegate.PaymentStatus.PAID,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Delegate.objects.create(
                    user=other_user,
                    eventbrite_order_id="ORDER123",
                    payment_status=Delegate.PaymentStatus.PAID,
                )

    def test_two_delegates_can_both_be_unpaid(self):
        # null eventbrite_order_id must NOT collide under the unique constraint
        other_user = User.objects.create_user(username="c@c.com", email="c@c.com")
        Delegate.objects.create(user=self.user)
        Delegate.objects.create(user=other_user)  # must not raise


class UIUCPromoCodeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a@a.com", email="a@a.com")
        self.delegate = Delegate.objects.create(user=self.user, is_uiuc_verified=True, uiuc_netid="jsmith2")

    def test_create(self):
        promo = UIUCPromoCode.objects.create(
            delegate=self.delegate,
            ticket_type=Delegate.TicketType.WORKSHOP,
            code="UIUC_jsmith2_X9B4",
            eventbrite_discount_id="disc_1",
        )
        self.assertIsNone(promo.redeemed_at)

    def test_one_code_per_delegate_per_ticket_type(self):
        UIUCPromoCode.objects.create(
            delegate=self.delegate,
            ticket_type=Delegate.TicketType.WORKSHOP,
            code="UIUC_jsmith2_X9B4",
            eventbrite_discount_id="disc_1",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UIUCPromoCode.objects.create(
                    delegate=self.delegate,
                    ticket_type=Delegate.TicketType.WORKSHOP,
                    code="UIUC_jsmith2_ZZZZ",
                    eventbrite_discount_id="disc_2",
                )

    def test_same_delegate_can_have_codes_for_different_tiers(self):
        UIUCPromoCode.objects.create(
            delegate=self.delegate,
            ticket_type=Delegate.TicketType.WORKSHOP,
            code="UIUC_jsmith2_AAAA",
            eventbrite_discount_id="disc_1",
        )
        UIUCPromoCode.objects.create(
            delegate=self.delegate,
            ticket_type=Delegate.TicketType.VARIETY_SHOW,
            code="UIUC_jsmith2_BBBB",
            eventbrite_discount_id="disc_2",
        )  # must not raise
