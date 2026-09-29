import json
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from registration.models import (
    AccountSetUp, Delegate, Facilitator, FacilitatorContact, FacilitatorWorkshop, Location,
    Registration, Workshop,
)

KEY = "test-sheet-key"
URL = "/fact-admin/sheets/workshops/"


def row(**fields):
    base = {"tab": "Session 1", "row": 3, "session": 1}
    base.update(fields)
    return base


@override_settings(SHEETS_API_KEY=KEY)
class SheetTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def post(self, *rows):
        response = self.client.post(
            URL, json.dumps({"rows": list(rows)}), content_type="application/json",
            HTTP_X_SHEETS_KEY=KEY,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def get_rows(self):
        response = self.client.get(URL, HTTP_X_SHEETS_KEY=KEY)
        self.assertEqual(response.status_code, 200)
        return response.json()["rows"]

    def facilitator(self, name="MAFA", email=None):
        user = User.objects.create_user(name.lower().replace(" ", "")[:9] + "0001", password="pw")
        f = Facilitator.objects.create(user=user, department_name=name, image_url="", bio="")
        if email:
            FacilitatorContact.objects.create(facilitator=f, email=email)
        return f

    def room(self, building="Lincoln", number="1000", session=1, capacity=30):
        return Location.objects.create(building=building, room_num=number, session=session, capacity=capacity)


class AuthTest(SheetTestCase):
    @override_settings(SHEETS_API_KEY="")
    def test_disabled_without_key(self):
        self.assertEqual(self.client.get(URL, HTTP_X_SHEETS_KEY="x").status_code, 503)

    def test_wrong_or_missing_key(self):
        self.assertEqual(self.client.get(URL, HTTP_X_SHEETS_KEY="nope").status_code, 403)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_method_and_json(self):
        self.assertEqual(self.client.put(URL, HTTP_X_SHEETS_KEY=KEY).status_code, 405)
        bad = self.client.post(URL, "{", content_type="application/json", HTTP_X_SHEETS_KEY=KEY)
        self.assertEqual(bad.status_code, 400)
        not_list = self.client.post(URL, json.dumps({"rows": 1}), content_type="application/json", HTTP_X_SHEETS_KEY=KEY)
        self.assertEqual(not_list.status_code, 400)


class WorkshopRowTest(SheetTestCase):
    def test_new_workshop_requires_fields(self):
        [result] = self.post(row(title="New", description="", facilitator="MAFA"))
        self.assertEqual(result["level"], "error")
        self.assertIn("Description is required", result["status"])
        [result] = self.post(row(title="New", description="d"))
        self.assertIn("Facilitator is required", result["status"])
        self.assertFalse(Workshop.objects.filter(title="New").exists())

    def test_create_then_rename_by_id(self):
        [created] = self.post(row(title="Kapwa", description="d", facilitator="New Org"))
        self.assertEqual(created["level"], "ok")
        self.assertTrue(created["status"].startswith("added"))
        workshop_id = created["workshop_id"]
        [renamed] = self.post(row(workshop_id=workshop_id, title="Kapwa 101"))
        self.assertTrue(renamed["status"].startswith("updated"))
        self.assertEqual(Workshop.objects.get(pk=workshop_id).title, "Kapwa 101")

    def test_title_match_within_session_only(self):
        existing = Workshop.objects.create(title="AZA", description="d", session=2)
        [result] = self.post(row(title="AZA", description="d2", facilitator="AZA Essentials"))
        self.assertNotEqual(result["workshop_id"], existing.pk)
        self.assertEqual(Workshop.objects.filter(title="AZA").count(), 2)

    def test_blank_cells_keep_values(self):
        workshop = Workshop.objects.create(title="T", description="keep me", session=1)
        self.post(row(workshop_id=workshop.pk, title="T", description=""))
        workshop.refresh_from_db()
        self.assertEqual(workshop.description, "keep me")

    def test_unknown_workshop_id(self):
        [result] = self.post(row(workshop_id=99999, title="T"))
        self.assertIn("No workshop with ID 99999", result["status"])

    def test_session_move_blocked_with_registrations(self):
        workshop = Workshop.objects.create(title="T", description="d", session=1)
        delegate_user = User.objects.create_user("del", password="pw")
        Registration.objects.create(delegate=Delegate.objects.create(user=delegate_user), workshop=workshop)
        [result] = self.post(row(tab="Session 2", session=2, workshop_id=workshop.pk, title="T"))
        self.assertIn("Can't move to Session 2", result["status"])
        workshop.refresh_from_db()
        self.assertEqual(workshop.session, 1)

    def test_session_move_allowed_and_room_dropped(self):
        workshop = Workshop.objects.create(title="T", description="d", session=1, location=self.room())
        [result] = self.post(row(tab="Session 2", session=2, workshop_id=workshop.pk, title="T"))
        self.assertEqual(result["level"], "ok")
        workshop.refresh_from_db()
        self.assertEqual(workshop.session, 2)
        self.assertIsNone(workshop.location)

    def test_bad_session(self):
        [result] = self.post(row(session=7, title="T"))
        self.assertIn("isn't a session tab", result["status"])

    def test_one_bad_row_does_not_block_others(self):
        results = self.post(
            row(row=3, workshop_id=99999, title="x"),
            row(row=4, title="Good", description="d", facilitator="Org"),
        )
        self.assertEqual([r["level"] for r in results], ["error", "ok"])


class RoomRowTest(SheetTestCase):
    def setUp(self):
        super().setUp()
        self.workshop = Workshop.objects.create(title="T", description="d", session=1)

    def test_room_created_and_reused(self):
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", building="Lincoln Hall", room="1000", capacity="40"))
        self.assertEqual(result["level"], "ok")
        self.workshop.refresh_from_db()
        self.assertEqual((self.workshop.location.building, self.workshop.location.capacity), ("Lincoln Hall", 40))
        self.post(row(workshop_id=self.workshop.pk, title="T", building=" lincoln  hall ", room="1000"))
        self.assertEqual(Location.objects.filter(session=1).count(), 1)

    def test_room_without_capacity_warns(self):
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", building="TBD", room="9"))
        self.assertEqual(result["level"], "warn")
        self.assertIn("room created with capacity 0", result["status"])

    def test_room_conflict(self):
        other = Workshop.objects.create(title="Other", description="d", session=1, location=self.room())
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", building="Lincoln", room="1000"))
        self.assertIn('already used by "Other" in Session 1', result["status"])

    def test_half_room_rejected(self):
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", building="Lincoln"))
        self.assertIn("Fill in both Building and Room", result["status"])

    def test_capacity_text_rejected(self):
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", building="L", room="1", capacity="30 seats"))
        self.assertEqual(result["level"], "error")
        self.assertIn("Capacity must be a number", result["status"])
        self.assertFalse(Location.objects.exists())

    def test_capacity_needs_room(self):
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", capacity="20"))
        self.assertIn("Set a Building and Room before Capacity", result["status"])

    def test_over_capacity_warns_but_saves(self):
        location = self.room(capacity=5)
        self.workshop.location = location
        self.workshop.save()
        for i in range(3):
            user = User.objects.create_user(f"d{i}", password="pw")
            Registration.objects.create(delegate=Delegate.objects.create(user=user), workshop=self.workshop)
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", capacity="2"))
        self.assertEqual(result["level"], "warn")
        self.assertIn("3 registered > 2 capacity", result["status"])
        location.refresh_from_db()
        self.assertEqual(location.capacity, 2)


class GetRowsTest(SheetTestCase):
    def test_rows_per_facilitator_with_private_email(self):
        workshop = Workshop.objects.create(title="Panel", description="d", session=2, location=self.room(session=2))
        a = self.facilitator("A Org", email="a@example.com")
        b = self.facilitator("B Org")
        FacilitatorWorkshop.objects.create(facilitator=a, workshop=workshop)
        FacilitatorWorkshop.objects.create(facilitator=b, workshop=workshop)
        Workshop.objects.create(title="Lonely", description="d", session=1)
        rows = self.get_rows()
        self.assertEqual([(r["title"], r["facilitator"]) for r in rows],
                         [("Lonely", ""), ("Panel", "A Org"), ("Panel", "B Org")])
        panel_a = rows[1]
        self.assertEqual((panel_a["building"], panel_a["room"], panel_a["capacity"]), ("Lincoln", "1000", 30))
        self.assertEqual(panel_a["email"], "a@example.com")
        self.assertEqual(rows[2]["email"], "")

    def test_get_blanks_placeholder_photo_and_nan_position(self):
        workshop = Workshop.objects.create(title="T", description="d", session=1)
        f = self.facilitator("Org")
        f.image_url = "https://placehold.co/400x400?text=TBD"
        f.position = "nan"
        f.save()
        FacilitatorWorkshop.objects.create(facilitator=f, workshop=workshop)
        [only] = self.get_rows()
        self.assertEqual((only["photo"], only["position"]), ("", ""))


class RobustnessTest(SheetTestCase):
    def test_long_title_errors_but_others_saved(self):
        results = self.post(
            row(row=3, title="x" * 151, description="d", facilitator="Org"),
            row(row=4, title="Fine", description="d", facilitator="Org2"),
        )
        self.assertEqual([r["level"] for r in results], ["error", "ok"])
        self.assertIn("Title is too long", results[0]["status"])
        self.assertFalse(Workshop.objects.filter(title__startswith="xxx").exists())

    def test_capacity_inf_rejected(self):
        workshop = Workshop.objects.create(title="T", description="d", session=1)
        for value in ("inf", "1e400"):
            [result] = self.post(row(workshop_id=workshop.pk, title="T", building="L", room="1", capacity=value))
            self.assertIn("Capacity must be a number", result["status"])

    def test_unexpected_exception_is_contained(self):
        from unittest.mock import patch
        from fact_admin.workshop_sheet import views
        real = views.sync_row
        calls = {"n": 0}

        def flaky(r):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return real(r)

        with patch("fact_admin.workshop_sheet.views.sync_row", side_effect=flaky):
            results = self.post(
                row(row=3, title="A", description="d", facilitator="Org"),
                row(row=4, title="B", description="d", facilitator="Org2"),
            )
        self.assertEqual([r["level"] for r in results], ["error", "ok"])
        self.assertIn("server error", results[0]["status"])

    def test_non_utf8_body(self):
        response = self.client.post(URL, b"\xff", content_type="application/json", HTTP_X_SHEETS_KEY=KEY)
        self.assertEqual(response.status_code, 400)

    def test_non_ascii_key(self):
        self.assertEqual(self.client.get(URL, HTTP_X_SHEETS_KEY="ключ").status_code, 403)


class FacilitatorRowTest(SheetTestCase):
    def setUp(self):
        super().setUp()
        self.workshop = Workshop.objects.create(title="T", description="d", session=1)

    def test_new_facilitator_gets_account_and_private_contact(self):
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", facilitator="New Org",
                                 email="New@Example.com", people="Ana, Ben", bio="Hi"))
        f = Facilitator.objects.get(pk=result["facilitator_id"])
        self.assertEqual((f.department_name, f.facilitators, f.bio), ("New Org", ["Ana", "Ben"], "Hi"))
        self.assertEqual(f.contact.email, "new@example.com")
        self.assertTrue(FacilitatorWorkshop.objects.filter(facilitator=f, workshop=self.workshop).exists())
        self.assertEqual(result["facilitator"]["email"], "new@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])
        self.assertIn("login sent", result["status"])

    def test_match_by_id_renames(self):
        f = self.facilitator("Donny Rojo")
        self.post(row(workshop_id=self.workshop.pk, title="T", facilitator_id=f.pk, facilitator="Donny Rojo, FYLPRO"))
        f.refresh_from_db()
        self.assertEqual(f.department_name, "Donny Rojo, FYLPRO")
        self.assertEqual(Facilitator.objects.count(), 1)

    def test_match_by_email_across_sessions(self):
        f = self.facilitator("Sierra Sikora", email="sierra@example.com")
        other = Workshop.objects.create(title="Songs", description="d", session=3)
        [result] = self.post(row(tab="Session 3", session=3, workshop_id=other.pk, title="Songs",
                                 facilitator="Sierra Sikora", email="SIERRA@example.com"))
        self.assertEqual(result["facilitator_id"], f.pk)
        self.assertEqual(Facilitator.objects.count(), 1)

    def test_duplicate_name_blocked(self):
        self.facilitator("MAFA")
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", facilitator="mafa"))
        self.assertEqual(result["level"], "error")
        self.assertIn('A facilitator named "mafa" already exists', result["status"])
        self.assertEqual(User.objects.filter(username__startswith="mafa").count(), 1)

    def test_email_owned_by_other_facilitator(self):
        self.facilitator("MAFA", email="shared@example.com")
        mine = self.facilitator("Kasamahan")
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", facilitator_id=mine.pk,
                                 facilitator="Kasamahan", email="shared@example.com"))
        self.assertIn('shared@example.com belongs to "MAFA"', result["status"])

    def test_invalid_email(self):
        [result] = self.post(row(workshop_id=self.workshop.pk, title="T", facilitator="Org", email="not-an-email"))
        self.assertIn("isn't a valid email", result["status"])

    def test_blank_cells_keep_facilitator_values(self):
        f = self.facilitator("Org")
        f.bio, f.facilitators, f.image_url = "keep", ["Keep"], "https://x.test/keep.png"
        f.save()
        self.post(row(workshop_id=self.workshop.pk, title="T", facilitator_id=f.pk, facilitator="Org"))
        f.refresh_from_db()
        self.assertEqual((f.bio, f.facilitators, f.image_url), ("keep", ["Keep"], "https://x.test/keep.png"))

    def test_photo_fields_saved(self):
        f = self.facilitator("Org")
        self.post(row(workshop_id=self.workshop.pk, title="T", facilitator_id=f.pk, facilitator="Org",
                      photo_url="https://blob.test/facilitators/org-abc.png", photo_width=220,
                      photo_height=180, photo_opaque=False, photo_blur=""))
        f.refresh_from_db()
        self.assertEqual((f.image_url, f.photo_width, f.photo_height, f.photo_opaque),
                         ("https://blob.test/facilitators/org-abc.png", 220, 180, False))

    def test_new_facilitator_rolled_back_on_row_error(self):
        with patch("fact_admin.workshop_sheet.sync.FacilitatorWorkshop.objects.get_or_create",
                   side_effect=RuntimeError("boom")):
            [result] = self.post(row(workshop_id=self.workshop.pk, title="T", facilitator="Brand New"))
        self.assertEqual(result["level"], "error")
        self.assertFalse(Facilitator.objects.filter(department_name="Brand New").exists())
        self.assertFalse(User.objects.filter(username__startswith="brandnew").exists())


class LoginEmailTest(SheetTestCase):
    def setUp(self):
        super().setUp()
        self.s2 = Workshop.objects.create(title="Music", description="d", session=2)
        self.s3 = Workshop.objects.create(title="Songs", description="d", session=3)
        self.sierra = self.facilitator("Sierra Sikora", email="sierra@example.com")

    def rows_for_sierra(self, **extra):
        return (
            row(tab="Session 2", session=2, row=3, workshop_id=self.s2.pk, title="Music",
                facilitator_id=self.sierra.pk, facilitator="Sierra Sikora", **extra),
            row(tab="Session 3", session=3, row=4, workshop_id=self.s3.pk, title="Songs",
                facilitator_id=self.sierra.pk, facilitator="Sierra Sikora", **extra),
        )

    def test_one_email_for_two_rows(self):
        results = self.post(*self.rows_for_sierra())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["sierra@example.com"])
        for result in results:
            self.assertIn("login sent", result["status"])
            self.assertTrue(result["resend_done"])
        self.assertIsNotNone(FacilitatorContact.objects.get(facilitator=self.sierra).login_sent_at)

    def test_not_resent_on_retick(self):
        self.post(*self.rows_for_sierra())
        sent_at = FacilitatorContact.objects.get(facilitator=self.sierra).login_sent_at
        results = self.post(*self.rows_for_sierra())
        self.assertEqual(FacilitatorContact.objects.get(facilitator=self.sierra).login_sent_at, sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("login sent", results[0]["status"])

    def test_no_email_without_contact_email(self):
        f = self.facilitator("No Email Org")
        self.post(row(workshop_id=Workshop.objects.create(title="X", description="d", session=1).pk,
                      title="X", facilitator_id=f.pk, facilitator="No Email Org"))
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_without_contact_email_warns(self):
        f = self.facilitator("No Email Org")
        w = Workshop.objects.create(title="X", description="d", session=1)
        [result] = self.post(row(workshop_id=w.pk, title="X", facilitator_id=f.pk,
                                 facilitator="No Email Org", resend_login=True))
        self.assertIn("Resend login needs a Facilitator Email", result["status"])
        self.assertEqual(result["level"], "warn")
        self.assertTrue(result["resend_done"])
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_before_setup_sends_fresh_link(self):
        self.post(*self.rows_for_sierra())
        first_body = mail.outbox[0].body
        later = datetime.now() + timedelta(minutes=5)
        with patch.object(PasswordResetTokenGenerator, "_now", return_value=later):
            [result] = self.post(self.rows_for_sierra(resend_login=True)[0])
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotEqual(mail.outbox[1].body, first_body)
        self.assertTrue(result["resend_done"])
        self.assertEqual(AccountSetUp.objects.filter(username=self.sierra.user.username).count(), 1)

    def test_never_sent_after_setup(self):
        FacilitatorContact.objects.filter(facilitator=self.sierra).update(setup_completed_at=timezone.now())
        self.post(*self.rows_for_sierra())
        self.assertEqual(len(mail.outbox), 0)
        [result] = self.post(self.rows_for_sierra(resend_login=True)[0])
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("already set up, use Forgot password", result["status"])
        self.assertEqual(result["level"], "warn")

    def test_failure_keeps_retrying(self):
        with patch("fact_admin.workshop_sheet.sync.send_setup_email", side_effect=OSError("smtp down")):
            [result] = self.post(self.rows_for_sierra()[0])
        self.assertEqual(result["level"], "warn")
        self.assertIn("login email failed, will retry", result["status"])
        self.assertTrue(result["retry"])
        self.assertFalse(result["resend_done"])
        self.assertIsNone(FacilitatorContact.objects.get(facilitator=self.sierra).login_sent_at)
        self.post(self.rows_for_sierra()[0])
        self.assertEqual(len(mail.outbox), 1)


class LoginEmailCapTest(SheetTestCase):
    def test_cap_queues_extra_facilitators_until_next_sync(self):
        w = Workshop.objects.create(title="X", description="d", session=1)
        a = self.facilitator("Alpha Org", email="a@example.com")
        b = self.facilitator("Beta Org", email="b@example.com")
        rows = [
            row(row=3, workshop_id=w.pk, title="X", facilitator_id=a.pk, facilitator="Alpha Org"),
            row(row=4, workshop_id=w.pk, title="X", facilitator_id=b.pk, facilitator="Beta Org"),
        ]
        with patch("fact_admin.workshop_sheet.views.MAX_LOGIN_EMAILS_PER_SYNC", 1):
            first, second = self.post(*rows)
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("login sent", first["status"])
            self.assertIn("login email queued, will send next sync", second["status"])
            self.assertEqual(second["level"], "warn")
            self.assertTrue(second["retry"])
            self.assertFalse(second["resend_done"])
            self.assertIsNone(FacilitatorContact.objects.get(facilitator=b).login_sent_at)
            self.post(*rows)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["b@example.com"])
