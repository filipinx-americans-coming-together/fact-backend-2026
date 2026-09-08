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