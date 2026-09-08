import json
from django.core import mail
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import Group, User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone

from fact_admin.models import AdminPasswordReset, AdminPromotion, RegistrationFlag
from registration.models import Delegate, Location, Registration, School, Workshop


class RegistrationFlagsGET(TestCase):
    def setUp(self):
        self.client = Client()

        self.expected_data = [
            {"label": "flag-1", "value": True},
            {"label": "flag-2", "value": True},
            {"label": "flag-3", "value": False},
            {"label": "flag-4", "value": True},
            {"label": "flag-5", "value": False},
        ]

        for flag in self.expected_data:
            RegistrationFlag.objects.create(label=flag["label"], value=flag["value"])

        self.url = reverse("fact_admin:flags")

    def test_gets_all_flags(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        data = response.json()

        actual = []
        for item in data:
            actual.append(
                {"label": item["fields"]["label"], "value": item["fields"]["value"]}
            )

        self.assertEqual(actual, self.expected_data)


class RegistrationFlagLabelGET(TestCase):
    def setUp(self):
        self.client = Client()

        RegistrationFlag.objects.create(label="first-flag", value=False)

        self.expected_label = "second-flag"
        self.expected_value = True

        self.flag = RegistrationFlag.objects.create(
            label=self.expected_label, value=self.expected_value
        )

        self.url_name = "fact_admin:flags_label"

    def test_flag_not_found(self):
        url = reverse(self.url_name, kwargs={"label": "not a label"})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_gets_flag(self):
        url = reverse(self.url_name, kwargs={"label": self.flag.label})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data[0]["fields"]["label"], self.flag.label)
        self.assertEqual(data[0]["fields"]["value"], self.flag.value)


class RegistrationFlagLabelPUT(TestCase):
    def setUp(self):
        self.client = Client()

        # users
        group = Group.objects.create(name="FACTAdmin")

        self.username = "admin-user"
        self.password = "admin-pass"

        user = User(username=self.username)
        user.set_password(self.password)
        user.save()

        user.groups.add(group)

        self.non_admin_username = "non-admin-user"
        self.non_admin_password = "non-admin-pass"

        user = User(username=self.non_admin_username)
        user.set_password(self.non_admin_password)
        user.save()

        self.flag = RegistrationFlag.objects.create(label="some-label", value=False)

        self.good_data = {"value": True}

        self.url_name = "fact_admin:flags_label"

    def test_rejects_non_admin(self):
        response = self.client.put(
            reverse(self.url_name, kwargs={"label": self.flag.label}),
            json.dumps(self.good_data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(RegistrationFlag.objects.get(pk=self.flag.pk).value, False)

        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.put(
            reverse(self.url_name, kwargs={"label": self.flag.label}),
            json.dumps(self.good_data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(RegistrationFlag.objects.get(pk=self.flag.pk).value, False)

    def test_flag_not_found(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.put(
            reverse(self.url_name, kwargs={"label": "not a label"}),
            json.dumps(self.good_data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_invalid_value(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.put(
            reverse(self.url_name, kwargs={"label": self.flag.label}),
            json.dumps({"value": "example data"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(RegistrationFlag.objects.get(pk=self.flag.pk).value, False)

    def test_updates_flag(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.put(
            reverse(self.url_name, kwargs={"label": self.flag.label}),
            json.dumps(self.good_data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            RegistrationFlag.objects.get(pk=self.flag.pk).value, self.good_data["value"]
        )


class SummaryGET(TestCase):
    def setUp(self):
        self.client = Client()

        # users
        group = Group.objects.create(name="FACTAdmin")

        self.username = "admin-user"
        self.password = "admin-pass"

        user = User(username=self.username)
        user.set_password(self.password)
        user.save()

        user.groups.add(group)

        self.non_admin_username = "non-admin-user"
        self.non_admin_password = "non-admin-pass"

        user = User(username=self.non_admin_username)
        user.set_password(self.non_admin_password)
        user.save()

        self.url = reverse("fact_admin:summary")

    def test_rejects_non_admin(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_gets_summary(self):
        self.client.login(username=self.username, password=self.password)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        # TODO test actual data getting


class DelegateSheetGET(TestCase):
    def setUp(self):
        self.client = Client()

        # users
        group = Group.objects.create(name="FACTAdmin")

        self.username = "admin-user"
        self.password = "admin-pass"

        user = User(username=self.username)
        user.set_password(self.password)
        user.save()

        user.groups.add(group)

        self.non_admin_username = "non-admin-user"
        self.non_admin_password = "non-admin-pass"

        user = User(username=self.non_admin_username)
        user.set_password(self.non_admin_password)
        user.save()

        self.url = reverse("fact_admin:delegate_sheet")

    def test_rejects_non_admin(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    # TODO write test
    def test_gets_sheet(self):
        pass


class LocationSheetGET(TestCase):
    def setUp(self):
        self.client = Client()

        # users
        group = Group.objects.create(name="FACTAdmin")

        self.username = "admin-user"
        self.password = "admin-pass"

        user = User(username=self.username)
        user.set_password(self.password)
        user.save()

        user.groups.add(group)

        self.non_admin_username = "non-admin-user"
        self.non_admin_password = "non-admin-pass"

        user = User(username=self.non_admin_username)
        user.set_password(self.non_admin_password)
        user.save()

        self.url = reverse("fact_admin:location_sheet")

    def test_rejects_non_admin(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    # TODO write test
    def test_gets_sheet_location(self):
        pass


class PromoteAdminPOST(TestCase):
    def setUp(self):
        self.client = Client()

        group = Group.objects.create(name="FACTAdmin")

        self.admin_username = "admin-user"
        self.admin_password = "admin-pass"
        admin = User(username=self.admin_username, first_name="Admin")
        admin.set_password(self.admin_password)
        admin.save()
        admin.groups.add(group)

        self.non_admin_username = "non-admin-user"
        self.non_admin_password = "non-admin-pass"
        non_admin = User(username=self.non_admin_username)
        non_admin.set_password(self.non_admin_password)
        non_admin.save()

        self.target_email = "target@email.com"
        self.target = User.objects.create(
            username=self.target_email, email=self.target_email, first_name="Target"
        )

        self.url = reverse("fact_admin:promote_admin")
        self.good_data = {"email": self.target_email}

    def test_rejects_non_admin(self):
        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_promote_sends_email_and_creates_pending_promotion(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AdminPromotion.objects.filter(email=self.target_email).exists()
        )
        self.assertFalse(self.target.groups.filter(name="FACTAdmin").exists())

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.target_email, mail.outbox[0].to)

    def test_email_not_found(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        response = self.client.post(
            self.url,
            {"email": "nobody@email.com"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_already_admin_rejected(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        group = Group.objects.get(name="FACTAdmin")
        self.target.groups.add(group)

        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)


class PromoteAdminConfirmPOST(TestCase):
    def setUp(self):
        self.client = Client()

        self.target_email = "target@email.com"
        self.target = User.objects.create(
            username=self.target_email, email=self.target_email
        )

        self.token = PasswordResetTokenGenerator().make_token(self.target)
        self.promotion = AdminPromotion.objects.create(
            email=self.target_email,
            token=self.token,
            expiration=timezone.now() + timezone.timedelta(hours=24),
        )

        self.url = reverse("fact_admin:promote_admin_confirm")

    def test_confirm_grants_admin_group(self):
        response = self.client.post(
            self.url, {"token": self.token}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.target.groups.filter(name="FACTAdmin").exists())
        self.assertFalse(AdminPromotion.objects.filter(pk=self.promotion.pk).exists())

    def test_invalid_token_rejected(self):
        response = self.client.post(
            self.url, {"token": "not-a-real-token"}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.target.groups.filter(name="FACTAdmin").exists())

    def test_expired_token_rejected(self):
        self.promotion.expiration = timezone.now() - timezone.timedelta(minutes=1)
        self.promotion.save()

        response = self.client.post(
            self.url, {"token": self.token}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.target.groups.filter(name="FACTAdmin").exists())


class ResetAdminPasswordPOST(TestCase):
    def setUp(self):
        self.client = Client()

        group = Group.objects.create(name="FACTAdmin")

        self.admin_username = "admin-user"
        self.admin_password = "admin-pass"
        admin = User(username=self.admin_username, first_name="Admin")
        admin.set_password(self.admin_password)
        admin.save()
        admin.groups.add(group)

        self.non_admin_username = "non-admin-user"
        self.non_admin_password = "non-admin-pass"
        self.non_admin_email = "non-admin@email.com"
        non_admin = User(username=self.non_admin_username, email=self.non_admin_email)
        non_admin.set_password(self.non_admin_password)
        non_admin.save()

        self.target_email = "target-admin@email.com"
        self.target = User.objects.create(
            username=self.target_email, email=self.target_email, first_name="Target"
        )
        self.target.groups.add(group)

        self.url = reverse("fact_admin:reset_admin_password")
        self.good_data = {"email": self.target_email}

    def test_rejects_non_admin(self):
        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_reset_sends_email_and_creates_pending_reset(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AdminPasswordReset.objects.filter(email=self.target_email).exists()
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.target_email, mail.outbox[0].to)

    def test_email_not_found(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        response = self.client.post(
            self.url,
            {"email": "nobody@email.com"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_non_admin_target_rejected(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        response = self.client.post(
            self.url,
            {"email": self.non_admin_email},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)


class ResetAdminPasswordConfirmPOST(TestCase):
    def setUp(self):
        self.client = Client()

        self.target_email = "target-admin@email.com"
        self.target = User.objects.create(
            username=self.target_email, email=self.target_email
        )
        self.target.set_password("old-password")
        self.target.save()

        self.token = PasswordResetTokenGenerator().make_token(self.target)
        self.reset = AdminPasswordReset.objects.create(
            email=self.target_email,
            token=self.token,
            expiration=timezone.now() + timezone.timedelta(hours=24),
        )

        self.url = reverse("fact_admin:reset_admin_password_confirm")

    def test_confirm_sets_new_password(self):
        response = self.client.post(
            self.url,
            {"token": self.token, "password": "new-password-123"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("new-password-123"))
        self.assertFalse(AdminPasswordReset.objects.filter(pk=self.reset.pk).exists())

    def test_missing_password_rejected(self):
        response = self.client.post(
            self.url, {"token": self.token}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("old-password"))

    def test_invalid_token_rejected(self):
        response = self.client.post(
            self.url,
            {"token": "not-a-real-token", "password": "new-password-123"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("old-password"))

    def test_expired_token_rejected(self):
        self.reset.expiration = timezone.now() - timezone.timedelta(minutes=1)
        self.reset.save()

        response = self.client.post(
            self.url,
            {"token": self.token, "password": "new-password-123"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("old-password"))


class DayOfRegistrationPOST(TestCase):
    def setUp(self):
        self.client = Client()

        group = Group.objects.create(name="FACTAdmin")
        self.admin_username = "admin-user"
        self.admin_password = "admin-pass"
        admin = User(username=self.admin_username)
        admin.set_password(self.admin_password)
        admin.save()
        admin.groups.add(group)

        self.non_admin_username = "non-admin-user"
        self.non_admin_password = "non-admin-pass"
        non_admin = User(username=self.non_admin_username)
        non_admin.set_password(self.non_admin_password)
        non_admin.save()

        self.school = School.objects.create(name="School")

        location_1 = Location.objects.create(
            building="Building", room_num="ABC", session=1, capacity=10
        )
        self.workshop_1 = Workshop.objects.create(
            title="title 1", description="description 1", location=location_1, session=1
        )

        self.url = reverse("fact_admin:day_of_registration")
        self.good_data = {
            "f_name": "First",
            "l_name": "Last",
            "email": "dayof@email.com",
            "password": "pass-1243__?",
            "pronouns": "she/her",
            "year": "Junior",
            "school_id": self.school.pk,
            "ticket_type": Delegate.TicketType.WORKSHOP,
        }

    def test_rejects_non_admin(self):
        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email=self.good_data["email"]).exists())

    def test_creates_paid_delegate_without_logging_admin_out(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        response = self.client.post(
            self.url, self.good_data, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        delegate = Delegate.objects.get(user__email=self.good_data["email"])
        self.assertEqual(delegate.payment_status, Delegate.PaymentStatus.PAID)
        self.assertEqual(delegate.ticket_type, Delegate.TicketType.WORKSHOP)
        self.assertTrue(delegate.eventbrite_order_id.startswith("DAY_OF_"))

        # admin's own session should still be the admin, not the new delegate
        me_response = self.client.get(reverse("fact_admin:admin_user"))
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(
            json.loads(me_response.content)[0]["fields"]["username"],
            self.admin_username,
        )

    def test_registers_requested_workshop(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        data = self.good_data.copy()
        data["workshop_1_id"] = self.workshop_1.pk

        response = self.client.post(self.url, data, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        delegate = Delegate.objects.get(user__email=self.good_data["email"])
        self.assertTrue(
            Registration.objects.filter(
                delegate=delegate, workshop=self.workshop_1
            ).exists()
        )

    def test_full_workshop_rolls_back_entire_delegate(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        # fill the only seat with someone else first
        other_school = School.objects.create(name="Other School")
        other_user = User.objects.create(username="other@email.com", email="other@email.com")
        other_delegate = Delegate.objects.create(user=other_user, school=other_school)
        Location.objects.filter(pk=self.workshop_1.location.pk).update(capacity=1)
        Registration.objects.create(delegate=other_delegate, workshop=self.workshop_1)

        data = self.good_data.copy()
        data["workshop_1_id"] = self.workshop_1.pk

        response = self.client.post(self.url, data, content_type="application/json")

        self.assertEqual(response.status_code, 409)
        # the whole delegate account must be rolled back, not left half-created
        self.assertFalse(User.objects.filter(email=self.good_data["email"]).exists())

    def test_ticket_type_without_workshop_access_rejects_workshop_pick(self):
        self.client.login(username=self.admin_username, password=self.admin_password)

        data = self.good_data.copy()
        data["ticket_type"] = Delegate.TicketType.VARIETY_SHOW
        data["workshop_1_id"] = self.workshop_1.pk

        response = self.client.post(self.url, data, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email=self.good_data["email"]).exists())
    def test_gets_sheet(self):
        pass
