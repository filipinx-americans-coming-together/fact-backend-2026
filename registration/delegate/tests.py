from django.forms import model_to_dict
from django.test import Client, TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from registration.models import (
    Delegate,
    Location,
    NewSchool,
    Registration,
    School,
    Workshop,
)


class CreateDelegatePOST(TestCase):
    def setUp(self):
        self.client = Client()

        self.school = School.objects.create(name="School")

        self.good_data = {
            "f_name": "First",
            "l_name": "Second",
            "email": "email@email.com",
            "password": "pass-1243__?",
            "pronouns": "she/her",
            "year": "Junior",
            "school_id": self.school.pk,
        }

        self.url = reverse("registration:delegates_create")

    def test_create_delegate_success(self):
        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.all().count(), 1)

        user = User.objects.get(
            first_name=self.good_data["f_name"],
            last_name=self.good_data["l_name"],
            username=self.good_data["email"],
            email=self.good_data["email"],
        )

        delegate = Delegate.objects.get(
            user=user,
            pronouns=self.good_data["pronouns"],
            year=self.good_data["year"],
            school_id=self.school.pk,
        )

    def test_email_already_exists(self):
        User.objects.create(username=self.good_data["email"], email=self.good_data["email"])

        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(User.objects.all().count(), 1)

    def test_bad_password(self):
        data = self.good_data.copy()
        data["password"] = "pass"

        response = self.client.post(self.url, data, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.all().count(), 0)

    def test_invalid_email(self):
        data = self.good_data.copy()
        data["email"] = "email"

        response = self.client.post(self.url, data, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.all().count(), 0)

    def test_create_new_school(self):
        data = self.good_data.copy()
        del data["school_id"]
        data["other_school_name"] = "some other school"

        response = self.client.post(self.url, data, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.all().count(), 1)
        self.assertTrue(NewSchool.objects.filter(name="some other school").exists())


class DelegatesPOST(TestCase):
    def setUp(self):
        self.client = Client()

        self.school = School.objects.create(name="School")

        location_1 = Location.objects.create(
            building="Building", room_num="ABC", session=1, capacity=10
        )
        location_2 = Location.objects.create(
            building="Building", room_num="12", session=2, capacity=10
        )
        location_3 = Location.objects.create(
            building="Another building", room_num="ABC", session=3, capacity=10
        )

        self.workshop_1 = Workshop.objects.create(
            title="title 1", description="description 1", location=location_1, session=1
        )
        self.workshop_2 = Workshop.objects.create(
            title="title 2", description="description 2", location=location_2, session=2
        )
        self.workshop_3 = Workshop.objects.create(
            title="title 3", description="description 3", location=location_3, session=3
        )

        # Create user and delegate profile to register
        self.user = User.objects.create_user(
            username="email@email.com", email="email@email.com", password="password123"
        )
        self.delegate = Delegate.objects.create(
            user=self.user,
            pronouns="she/her",
            year="Junior",
            school=self.school,
            payment_status=Delegate.PaymentStatus.PAID,
            ticket_type=Delegate.TicketType.BUNDLE,
        )

        self.good_data = {
            "email": "email@email.com",
            "workshop_1_id": self.workshop_1.pk,
            "workshop_2_id": self.workshop_2.pk,
            "workshop_3_id": self.workshop_3.pk,
        }

        self.url = reverse("registration:delegates")

    def test_register_workshops_success(self):
        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_1.pk, delegate_id=self.delegate.pk
            ).exists()
        )
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_2.pk, delegate_id=self.delegate.pk
            ).exists()
        )
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_3.pk, delegate_id=self.delegate.pk
            ).exists()
        )

    def test_register_workshops_user_not_found(self):
        data = self.good_data.copy()
        data["email"] = "nonexistent@email.com"

        response = self.client.post(self.url, data, content_type="application/json")
        self.assertEqual(response.status_code, 404)

    def test_full_workshops(self):
        # set capacity of location to 1, and register someone else first
        location = Location.objects.create(
            building="new building", room_num="123", capacity=1, session=1
        )
        workshop = Workshop.objects.create(
            title="new workshop title",
            description="description",
            location=location,
            session=1,
        )
        other_user = User.objects.create(username="user123", email="email123@email.com")
        other_delegate = Delegate.objects.create(
            user=other_user, year="Senior", school=self.school
        )
        Registration.objects.create(workshop=workshop, delegate=other_delegate)

        data = self.good_data.copy()
        data["workshop_1_id"] = workshop.pk

        response = self.client.post(self.url, data, content_type="application/json")
        self.assertEqual(response.status_code, 409)

    def test_same_session_workshops(self):
        data = self.good_data.copy()
        data["workshop_2_id"] = self.workshop_1.pk  # Both workshop 1 and 2 in session 1

        response = self.client.post(self.url, data, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_unpaid_delegate_rejected(self):
        self.delegate.payment_status = Delegate.PaymentStatus.UNPAID
        self.delegate.save()

        response = self.client.post(self.url, self.good_data, content_type="application/json")
        self.assertEqual(response.status_code, 402)
        self.assertFalse(
            Registration.objects.filter(delegate_id=self.delegate.pk).exists()
        )

    def test_variety_show_only_ticket_rejected(self):
        self.delegate.ticket_type = Delegate.TicketType.VARIETY_SHOW
        self.delegate.save()

        response = self.client.post(self.url, self.good_data, content_type="application/json")
        self.assertEqual(response.status_code, 402)
        self.assertFalse(
            Registration.objects.filter(delegate_id=self.delegate.pk).exists()
        )


class DelegateMePUT(TestCase):
    def setUp(self):
        self.client = Client()

        self.school = School.objects.create(name="School")

        location_1 = Location.objects.create(
            building="Building", room_num="ABC", session=1, capacity=10
        )
        location_2 = Location.objects.create(
            building="Building", room_num="12", session=2, capacity=10
        )
        location_3 = Location.objects.create(
            building="Another building", room_num="ABC", session=3, capacity=10
        )

        self.workshop_1 = Workshop.objects.create(
            title="title 1", description="description 1", location=location_1, session=1
        )
        self.workshop_2 = Workshop.objects.create(
            title="title 2", description="description 2", location=location_2, session=2
        )
        self.workshop_3 = Workshop.objects.create(
            title="title 3", description="description 3", location=location_3, session=3
        )

        # Create unpaid delegate
        self.unpaid_user = User.objects.create_user(
            username="unpaid@email.com", email="unpaid@email.com", password="password123"
        )
        self.unpaid_delegate = Delegate.objects.create(
            user=self.unpaid_user,
            pronouns="she/her",
            year="Junior",
            school=self.school,
            payment_status=Delegate.PaymentStatus.UNPAID,
            ticket_type=Delegate.TicketType.WORKSHOP,
        )

        # Create paid delegate with BUNDLE ticket
        self.paid_bundle_user = User.objects.create_user(
            username="paid_bundle@email.com", email="paid_bundle@email.com", password="password123"
        )
        self.paid_bundle_delegate = Delegate.objects.create(
            user=self.paid_bundle_user,
            pronouns="she/her",
            year="Junior",
            school=self.school,
            payment_status=Delegate.PaymentStatus.PAID,
            ticket_type=Delegate.TicketType.BUNDLE,
        )

        # Create paid delegate with VARIETY_SHOW ticket
        self.paid_variety_user = User.objects.create_user(
            username="paid_variety@email.com", email="paid_variety@email.com", password="password123"
        )
        self.paid_variety_delegate = Delegate.objects.create(
            user=self.paid_variety_user,
            pronouns="she/her",
            year="Junior",
            school=self.school,
            payment_status=Delegate.PaymentStatus.PAID,
            ticket_type=Delegate.TicketType.VARIETY_SHOW,
        )

        self.url = reverse("registration:delegates_me")

    def test_unpaid_delegate_rejected_when_submitting_workshops(self):
        """Unpaid delegate submitting workshop IDs should get 402 and no registrations created"""
        self.client.login(username="unpaid@email.com", password="password123")

        data = {
            "f_name": "First",
            "l_name": "Last",
            "email": "unpaid@email.com",
            "password": "password123",
            "pronouns": "she/her",
            "year": "Junior",
            "workshop_1_id": self.workshop_1.pk,
            "workshop_2_id": self.workshop_2.pk,
            "workshop_3_id": self.workshop_3.pk,
        }

        response = self.client.put(
            self.url, data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 402)
        self.assertFalse(
            Registration.objects.filter(delegate_id=self.unpaid_delegate.pk).exists()
        )

    def test_paid_variety_show_ticket_rejected_when_submitting_workshops(self):
        """Paid delegate with VARIETY_SHOW ticket submitting workshop IDs should get 402"""
        self.client.login(username="paid_variety@email.com", password="password123")

        data = {
            "f_name": "First",
            "l_name": "Last",
            "email": "paid_variety@email.com",
            "password": "password123",
            "pronouns": "she/her",
            "year": "Junior",
            "workshop_1_id": self.workshop_1.pk,
            "workshop_2_id": self.workshop_2.pk,
            "workshop_3_id": self.workshop_3.pk,
        }

        response = self.client.put(
            self.url, data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 402)
        self.assertFalse(
            Registration.objects.filter(delegate_id=self.paid_variety_delegate.pk).exists()
        )

    def test_paid_workshop_ticket_succeeds_when_submitting_workshops(self):
        """Paid delegate with WORKSHOP ticket submitting workshop IDs should succeed (regression)"""
        # Change the paid_bundle delegate to WORKSHOP type for this test
        paid_workshop_user = User.objects.create_user(
            username="paid_workshop@email.com", email="paid_workshop@email.com", password="password123"
        )
        paid_workshop_delegate = Delegate.objects.create(
            user=paid_workshop_user,
            pronouns="she/her",
            year="Junior",
            school=self.school,
            payment_status=Delegate.PaymentStatus.PAID,
            ticket_type=Delegate.TicketType.WORKSHOP,
        )

        self.client.login(username="paid_workshop@email.com", password="password123")

        data = {
            "f_name": "First",
            "l_name": "Last",
            "email": "paid_workshop@email.com",
            "password": "password123",
            "pronouns": "she/her",
            "year": "Junior",
            "workshop_1_id": self.workshop_1.pk,
            "workshop_2_id": self.workshop_2.pk,
            "workshop_3_id": self.workshop_3.pk,
        }

        response = self.client.put(
            self.url, data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_1.pk, delegate_id=paid_workshop_delegate.pk
            ).exists()
        )
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_2.pk, delegate_id=paid_workshop_delegate.pk
            ).exists()
        )
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_3.pk, delegate_id=paid_workshop_delegate.pk
            ).exists()
        )

    def test_paid_bundle_ticket_succeeds_when_submitting_workshops(self):
        """Paid delegate with BUNDLE ticket submitting workshop IDs should succeed (regression)"""
        self.client.login(username="paid_bundle@email.com", password="password123")

        data = {
            "f_name": "First",
            "l_name": "Last",
            "email": "paid_bundle@email.com",
            "password": "password123",
            "pronouns": "she/her",
            "year": "Junior",
            "workshop_1_id": self.workshop_1.pk,
            "workshop_2_id": self.workshop_2.pk,
            "workshop_3_id": self.workshop_3.pk,
        }

        response = self.client.put(
            self.url, data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_1.pk, delegate_id=self.paid_bundle_delegate.pk
            ).exists()
        )
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_2.pk, delegate_id=self.paid_bundle_delegate.pk
            ).exists()
        )
        self.assertTrue(
            Registration.objects.filter(
                workshop_id=self.workshop_3.pk, delegate_id=self.paid_bundle_delegate.pk
            ).exists()
        )

    def test_unpaid_delegate_succeeds_when_updating_only_non_workshop_fields(self):
        """Unpaid delegate updating only pronouns/school (no workshop IDs) should succeed"""
        self.client.login(username="unpaid@email.com", password="password123")

        data = {
            "f_name": "FirstUpdated",
            "l_name": "LastUpdated",
            "email": "unpaid@email.com",
            "password": "password123",
            "pronouns": "they/them",
            "year": "Senior",
        }

        response = self.client.put(
            self.url, data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        # Verify the update happened
        self.unpaid_user.refresh_from_db()
        self.unpaid_delegate.refresh_from_db()
        self.assertEqual(self.unpaid_user.first_name, "FirstUpdated")
        self.assertEqual(self.unpaid_user.last_name, "LastUpdated")
        self.assertEqual(self.unpaid_delegate.pronouns, "they/them")
        self.assertEqual(self.unpaid_delegate.year, "Senior")
        # Ensure no workshops were registered
        self.assertFalse(
            Registration.objects.filter(delegate_id=self.unpaid_delegate.pk).exists()
        )


class DelegatesGET(TestCase):
    def setUp(self):
        pass

    def test_rejects_no_user(self):
        pass

    def test_rejects_non_delegate(self):
        pass

    def test_returns_delegate(self):
        pass


class DelegateLoginPOST(TestCase):
    def setUp(self):
        pass

    def test_rejects_invalid_creds(self):
        pass

    def test_rejects_non_delegate(self):
        pass

    def test_logs_in(self):
        pass


class UsersRequestPasswordResetPOST(TestCase):
    def setUp(self):
        pass

    def test_no_obj_created_if_no_user(self):
        pass

    def test_reject_no_email(self):
        pass

    def test_creates_reset_obj(self):
        pass


class UsersResetPasswordPOST(TestCase):
    def setUp(self):
        pass

    def test_reject_missing_email(self):
        pass

    def test_reject_missing_token(self):
        pass

    def test_reject_invalid_toke(self):
        pass

    def test_resets_password(self):
        pass


class UsersLogoutPOST(TestCase):
    def setUp(self):
        pass

    def test_logout(self):
        pass
