import importlib
from datetime import timedelta

import django.apps
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from .models import Facilitator, FacilitatorContact, FacilitatorWorkshop, Workshop


class FacilitatorContactPrivacyTest(TestCase):
    def setUp(self):
        user = User.objects.create_user("mafa1234", password="pw")
        self.facilitator = Facilitator.objects.create(
            user=user, department_name="MAFA", image_url="https://x.test/a.png", bio="b"
        )
        FacilitatorContact.objects.create(
            facilitator=self.facilitator, email="secret-contact@example.com"
        )
        workshop = Workshop.objects.create(title="PSA 101", description="d", session=1)
        FacilitatorWorkshop.objects.create(facilitator=self.facilitator, workshop=workshop)
        self.workshop = workshop

    def test_photo_fields_default(self):
        self.assertIsNone(self.facilitator.photo_width)
        self.assertIsNone(self.facilitator.photo_height)
        self.assertEqual(self.facilitator.photo_blur, "")
        self.assertTrue(self.facilitator.photo_opaque)

    def test_contact_email_never_public(self):
        client = Client()
        for url in (
            "/registration/workshops/all/",
            f"/registration/workshops/{self.workshop.pk}/",
            "/registration/facilitators/",
        ):
            response = client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertNotIn("secret-contact@example.com", response.content.decode(), url)


class FacilitatorContactMigrationBackfillTest(TestCase):
    def _run_migration(self):
        """Run the mark_existing_setups migration function directly."""
        migration_module = importlib.import_module(
            "registration.migrations.0025_mark_existing_setups"
        )
        migration_module.mark_existing_setups(django.apps.apps, None)

    def test_facilitator_with_last_login_gets_marked(self):
        """Facilitator who logged in before migration gets contact with last_login."""
        user = User.objects.create_user("login1234", password="pw")
        login_time = timezone.now() - timedelta(days=5)
        user.last_login = login_time
        user.save()

        facilitator = Facilitator.objects.create(
            user=user, department_name="Dept A", image_url="https://x.test/a.png", bio="b"
        )

        self._run_migration()

        contact = FacilitatorContact.objects.get(facilitator=facilitator)
        self.assertEqual(contact.setup_completed_at, login_time)

    def test_facilitator_with_email_no_login_gets_marked(self):
        """Facilitator with email (setup) but no login gets contact with now()."""
        user = User.objects.create_user("email1234", password="pw")
        user.email = "facilitator@example.com"
        user.last_login = None
        user.save()

        facilitator = Facilitator.objects.create(
            user=user, department_name="Dept B", image_url="https://x.test/a.png", bio="b"
        )

        before = timezone.now()
        self._run_migration()
        after = timezone.now()

        contact = FacilitatorContact.objects.get(facilitator=facilitator)
        self.assertIsNotNone(contact.setup_completed_at)
        self.assertGreaterEqual(contact.setup_completed_at, before)
        self.assertLessEqual(contact.setup_completed_at, after)

    def test_facilitator_with_neither_no_contact(self):
        """Facilitator with no email and no login gets no contact row."""
        user = User.objects.create_user("neither1234", password="pw")
        user.email = ""
        user.last_login = None
        user.save()

        facilitator = Facilitator.objects.create(
            user=user, department_name="Dept C", image_url="https://x.test/a.png", bio="b"
        )

        self._run_migration()

        self.assertEqual(FacilitatorContact.objects.filter(facilitator=facilitator).count(), 0)
