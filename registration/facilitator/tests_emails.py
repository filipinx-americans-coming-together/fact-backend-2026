import io
import json
from datetime import timedelta

import pandas as pd
from django.contrib.auth.models import Group, User
from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone

from registration.facilitator.emails import issue_setup_token, send_setup_email
from registration.models import AccountSetUp, Facilitator, FacilitatorContact


def make_facilitator(name="Sierra Sikora", username="sierrasik1234"):
    user = User.objects.create_user(username, password="pw")
    return Facilitator.objects.create(
        user=user, department_name=name, image_url="https://x.test/a.png", bio="b"
    )


class SetupEmailTest(TestCase):
    def test_issue_replaces_old_tokens(self):
        facilitator = make_facilitator()
        AccountSetUp.objects.create(
            username=facilitator.user.username,
            token="old",
            expiration=timezone.now() - timedelta(days=1),
        )
        setup = issue_setup_token(facilitator.user)
        tokens = list(AccountSetUp.objects.filter(username=facilitator.user.username))
        self.assertEqual(tokens, [setup])
        self.assertGreater(setup.expiration, timezone.now() + timedelta(days=6))

    def test_send_includes_link_and_username(self):
        facilitator = make_facilitator()
        send_setup_email(facilitator, ["sierra@example.com"])
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        setup = AccountSetUp.objects.get(username=facilitator.user.username)
        self.assertEqual(message.to, ["sierra@example.com"])
        self.assertIn(setup.token, message.body)
        self.assertIn(facilitator.user.username, message.body)
        self.assertEqual(message.subject, "FACT 2026 Facilitator Account - Sierra Sikora")


class SetupCompletedTest(TestCase):
    def test_account_setup_marks_completed(self):
        facilitator = make_facilitator()
        setup = issue_setup_token(facilitator.user)
        response = Client().post(
            "/registration/facilitators/set-up/",
            json.dumps({"email": "s@example.com", "password": "A-strong-pass-123", "token": setup.token}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        contact = FacilitatorContact.objects.get(facilitator=facilitator)
        self.assertIsNotNone(contact.setup_completed_at)


class SendFacilitatorLinksTest(TestCase):
    def setUp(self):
        admin = User.objects.create_user("admin", password="pw")
        admin.groups.add(Group.objects.get_or_create(name="FACTAdmin")[0])
        self.client = Client()
        self.client.force_login(admin)

    def _upload(self, rows):
        buffer = io.BytesIO()
        pd.DataFrame(rows).to_excel(buffer, index=False)
        buffer.seek(0)
        buffer.name = "emails.xlsx"
        return self.client.post("/fact-admin/accounts/send-facilitator-links/", {"emails": buffer})

    def test_expired_token_gets_fresh_link(self):
        facilitator = make_facilitator()
        AccountSetUp.objects.create(
            username=facilitator.user.username, token="dead",
            expiration=timezone.now() - timedelta(days=3),
        )
        response = self._upload([{"Facilitator Name": "Sierra Sikora", "Facilitator Email": "s@example.com"}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("dead", mail.outbox[0].body)
        contact = FacilitatorContact.objects.get(facilitator=facilitator)
        self.assertIsNotNone(contact.login_sent_at)
        self.assertEqual(contact.email, "s@example.com")

    def test_set_up_facilitator_skipped(self):
        facilitator = make_facilitator()
        FacilitatorContact.objects.create(facilitator=facilitator, setup_completed_at=timezone.now())
        response = self._upload([{"Facilitator Name": "Sierra Sikora", "Facilitator Email": "s@example.com"}])
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("Already set up: Sierra Sikora", response.json()["failed"])

    def test_backfilled_contact_skipped(self):
        """Facilitator with email set and backfilled contact gets no email."""
        # Create facilitator with email (setup completed before migration)
        facilitator = make_facilitator()
        facilitator.user.email = "sierra@example.com"
        facilitator.user.save()
        # Simulate the migration backfill
        FacilitatorContact.objects.create(
            facilitator=facilitator, setup_completed_at=timezone.now()
        )
        response = self._upload([{"Facilitator Name": "Sierra Sikora", "Facilitator Email": "sierra@example.com"}])
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("Already set up: Sierra Sikora", response.json()["failed"])
