import json
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse


class LoginPOST(TestCase):
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

        self.url = reverse("fact_admin:login_admin")

    def test_rejects_invalid_credentials(self):
        response = self.client.post(
            self.url,
            json.dumps({"username": "some_username", "password": "mypassword"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_rejects_non_admin(self):
        response = self.client.post(
            self.url,
            json.dumps(
                {
                    "username": self.non_admin_username,
                    "password": self.non_admin_password,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_logs_in(self):
        response = self.client.post(
            self.url,
            json.dumps(
                {
                    "username": self.username,
                    "password": self.password,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)


class BootstrapAdminLoginPOST(TestCase):
    """
    The one-time bootstrap path in login_admin: BOOTSTRAP_ADMIN_EMAIL logging
    in successfully while zero FACTAdmins exist gets auto-granted the group,
    and the path permanently disables itself the moment any FACTAdmin exists.
    """

    def setUp(self):
        self.client = Client()
        self.url = reverse("fact_admin:login_admin")

        self.bootstrap_password = "bootstrap-pass"
        self.bootstrap_user = User(
            username="fact.it@psauiuc.org", email="fact.it@psauiuc.org"
        )
        self.bootstrap_user.set_password(self.bootstrap_password)
        self.bootstrap_user.save()

    def test_bootstrap_grants_admin_when_none_exist(self):
        self.assertFalse(User.objects.filter(groups__name="FACTAdmin").exists())

        response = self.client.post(
            self.url,
            json.dumps(
                {
                    "username": "fact.it@psauiuc.org",
                    "password": self.bootstrap_password,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.bootstrap_user.refresh_from_db()
        self.assertTrue(self.bootstrap_user.groups.filter(name="FACTAdmin").exists())

    def test_bootstrap_does_not_fire_once_an_admin_exists(self):
        other_admin = User(username="already-admin", email="other@example.com")
        other_admin.set_password("password123")
        other_admin.save()
        group = Group.objects.create(name="FACTAdmin")
        other_admin.groups.add(group)

        response = self.client.post(
            self.url,
            json.dumps(
                {
                    "username": "fact.it@psauiuc.org",
                    "password": self.bootstrap_password,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.bootstrap_user.refresh_from_db()
        self.assertFalse(self.bootstrap_user.groups.filter(name="FACTAdmin").exists())

    def test_other_emails_do_not_trigger_bootstrap(self):
        other_user = User(username="someone-else", email="someone-else@example.com")
        other_user.set_password("password123")
        other_user.save()

        response = self.client.post(
            self.url,
            json.dumps({"username": "someone-else", "password": "password123"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        other_user.refresh_from_db()
        self.assertFalse(other_user.groups.filter(name="FACTAdmin").exists())


class MeGET(TestCase):
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

        self.url = reverse("fact_admin:admin_user")

    def test_rejects_no_user(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_rejects_non_admin(self):
        self.client.login(username=self.non_admin_username, password=self.non_admin_password)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_returns_admin(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)