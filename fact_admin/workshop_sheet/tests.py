import json

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from registration.models import (
    Location,
    Delegate,
    Facilitator,
    FacilitatorWorkshop,
    Registration,
    Workshop,
)

TEST_KEY = "test-workshop-sheet-key"


def _row(**overrides):
    row = {
        "row": 2,
        "id": "",
        "title": "Kapwa 101",
        "session": 1,
        "description": "Intro to kapwa",
        "facilitator": "Counseling Center",
        "facilitator_names": "Ana Cruz, Ben Reyes",
        "photo": "https://example.com/cc.png",
        "bio": "UIUC Counseling Center",
        "position": "",
        "room": "",
        "capacity": "",
    }
    row.update(overrides)
    return row


@override_settings(SHEETS_API_KEY=TEST_KEY)
class WorkshopSheetTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("fact_admin:workshop_sheet")

    def _post(self, rows, key=TEST_KEY):
        return self.client.post(
            self.url,
            json.dumps({"rows": rows}),
            content_type="application/json",
            HTTP_X_SHEETS_KEY=key,
        )

    def _existing_workshop(self, title="Kapwa 101", session=1, facilitator="Counseling Center"):
        user = User.objects.create_user(username=facilitator.replace(" ", "")[:9].lower())
        f = Facilitator.objects.create(
            user=user, department_name=facilitator, image_url="https://example.com/x.png", bio="old bio"
        )
        w = Workshop.objects.create(title=title, description="old", session=session)
        FacilitatorWorkshop.objects.create(facilitator=f, workshop=w)
        return w

    @override_settings(SHEETS_API_KEY="")
    def test_disabled_when_key_unset(self):
        response = self._post([_row()])
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Workshop.objects.exists())

    def test_wrong_key_rejected(self):
        response = self._post([_row()], key="nope")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Workshop.objects.exists())

    def test_creates_workshop_facilitator_and_emails_setup_link(self):
        response = self._post([_row()])

        self.assertEqual(response.status_code, 200)
        workshop = Workshop.objects.get(title="Kapwa 101")
        self.assertEqual(
            response.json()["results"], [{"row": 2, "id": workshop.pk, "status": "added"}]
        )
        self.assertEqual(workshop.session, 1)
        self.assertIsNone(workshop.location)
        facilitator = Facilitator.objects.get(department_name="Counseling Center")
        self.assertEqual(facilitator.facilitators, ["Ana Cruz", "Ben Reyes"])
        self.assertTrue(
            FacilitatorWorkshop.objects.filter(facilitator=facilitator, workshop=workshop).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Counseling Center", mail.outbox[0].body)

    def test_rerun_is_idempotent(self):
        self._post([_row()])
        response = self._post([_row()])

        self.assertEqual(response.json()["results"][0]["status"], "updated")
        self.assertEqual(Workshop.objects.count(), 1)
        self.assertEqual(Facilitator.objects.count(), 1)
        self.assertEqual(FacilitatorWorkshop.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_rename_by_id_updates_same_workshop(self):
        workshop = self._existing_workshop(title="Ethan's Workshop")

        response = self._post([_row(id=workshop.pk, title="Ethan's New Title", description="new")])

        self.assertEqual(response.json()["results"][0]["status"], "updated")
        workshop.refresh_from_db()
        self.assertEqual(workshop.title, "Ethan's New Title")
        self.assertEqual(workshop.description, "new")
        self.assertEqual(Workshop.objects.count(), 1)

    def test_blank_cells_do_not_erase_facilitator_details(self):
        workshop = self._existing_workshop()

        self._post([_row(id=workshop.pk, bio="", photo="", facilitator_names="")])

        facilitator = Facilitator.objects.get(department_name="Counseling Center")
        self.assertEqual(facilitator.bio, "old bio")
        self.assertEqual(facilitator.image_url, "https://example.com/x.png")

    def test_panel_rows_share_one_workshop(self):
        response = self._post([
            _row(row=2, title="Career Panel", session=3, facilitator="Awareness"),
            _row(row=3, title="Career Panel", session=3, facilitator="Cindy Martin"),
        ])

        ids = {r["id"] for r in response.json()["results"]}
        self.assertEqual(len(ids), 1)
        workshop = Workshop.objects.get(title="Career Panel")
        self.assertEqual(FacilitatorWorkshop.objects.filter(workshop=workshop).count(), 2)

    def test_bad_row_does_not_block_others(self):
        response = self._post([
            _row(row=2, session=4),
            _row(row=3, title=""),
            _row(row=4, title="Harana", session=3, facilitator="Harana"),
            _row(row=5, id=99999),
        ])

        statuses = [r["status"] for r in response.json()["results"]]
        self.assertEqual(statuses[0], "error: session must be 1, 2, or 3")
        self.assertEqual(statuses[1], "error: title is required")
        self.assertEqual(statuses[2], "added")
        self.assertEqual(statuses[3], "error: No workshop with id 99999 on the website")
        self.assertEqual(list(Workshop.objects.values_list("title", flat=True)), ["Harana"])

    def test_new_workshop_requires_facilitator(self):
        response = self._post([_row(facilitator="")])

        self.assertEqual(
            response.json()["results"][0]["status"],
            "error: facilitator is required for a new workshop",
        )
        self.assertFalse(Workshop.objects.exists())
        self.assertFalse(User.objects.exists())

    def test_session_change_blocked_when_delegates_registered(self):
        workshop = self._existing_workshop()
        user = User.objects.create_user(username="d", email="d@example.com")
        Registration.objects.create(delegate=Delegate.objects.create(user=user), workshop=workshop)

        response = self._post([_row(id=workshop.pk, session=2)])

        self.assertTrue(response.json()["results"][0]["status"].startswith("error: Can't change session"))
        workshop.refresh_from_db()
        self.assertEqual(workshop.session, 1)

    def test_rows_missing_from_sheet_are_not_deleted(self):
        self._existing_workshop(title="Keep Me")

        self._post([_row(title="Something Else", facilitator="Library")])

        self.assertTrue(Workshop.objects.filter(title="Keep Me").exists())

    def test_get_returns_existing_workshops_as_rows(self):
        workshop = self._existing_workshop()

        response = self.client.get(self.url, HTTP_X_SHEETS_KEY=TEST_KEY)

        self.assertEqual(response.status_code, 200)
        [row] = response.json()["rows"]
        self.assertEqual(row["id"], workshop.pk)
        self.assertEqual(row["title"], "Kapwa 101")
        self.assertEqual(row["facilitator"], "Counseling Center")

    def test_get_lists_each_panel_facilitator(self):
        self._post([
            _row(row=2, title="Career Panel", session=3, facilitator="Awareness"),
            _row(row=3, title="Career Panel", session=3, facilitator="Cindy Martin"),
        ])

        rows = self.client.get(self.url, HTTP_X_SHEETS_KEY=TEST_KEY).json()["rows"]

        self.assertEqual(sorted(r["facilitator"] for r in rows), ["Awareness", "Cindy Martin"])

    def test_invalid_body_rejected(self):
        response = self.client.post(
            self.url, "not json", content_type="application/json", HTTP_X_SHEETS_KEY=TEST_KEY
        )
        self.assertEqual(response.status_code, 400)

    def test_drive_share_link_becomes_image_link(self):
        self._post([_row(photo="https://drive.google.com/file/d/1AbC-d_9/view?usp=sharing")])

        facilitator = Facilitator.objects.get(department_name="Counseling Center")
        self.assertEqual(
            facilitator.image_url, "https://drive.google.com/uc?export=view&id=1AbC-d_9"
        )

    def test_non_https_photo_rejected(self):
        response = self._post([_row(photo="javascript:alert(1)")])

        self.assertEqual(
            response.json()["results"][0]["status"], "error: photo must be an https:// link"
        )
        self.assertFalse(Workshop.objects.exists())

    def test_room_and_capacity(self):
        room = Location.objects.create(building="Lincoln Hall", room_num="1000", capacity=40, session=1)

        self._post([_row(room="lincoln hall  1000", capacity=25)])

        workshop = Workshop.objects.get(title="Kapwa 101")
        self.assertEqual(workshop.location, room)
        room.refresh_from_db()
        self.assertEqual(room.capacity, 25)

    def test_room_must_exist_in_that_session(self):
        Location.objects.create(building="Lincoln Hall", room_num="1000", session=2)

        response = self._post([_row(room="Lincoln Hall 1000")])

        self.assertTrue(response.json()["results"][0]["status"].startswith('error: No room "Lincoln Hall 1000" in session 1'))
        self.assertFalse(Workshop.objects.exists())

    def test_room_already_taken(self):
        room = Location.objects.create(building="Siebel", room_num="1404", session=1)
        other = self._existing_workshop(title="Other", facilitator="Library")
        other.location = room
        other.save()

        response = self._post([_row(room="Siebel 1404")])

        self.assertEqual(
            response.json()["results"][0]["status"],
            'error: Room "Siebel 1404" is already used by "Other"',
        )
        self.assertEqual(Workshop.objects.count(), 1)

    def test_capacity_without_room_rejected(self):
        response = self._post([_row(capacity=30)])

        self.assertTrue(response.json()["results"][0]["status"].startswith("error: Set a room"))
        self.assertFalse(Workshop.objects.exists())

    def test_blank_room_keeps_existing_room(self):
        room = Location.objects.create(building="Siebel", room_num="1404", capacity=40, session=1)
        workshop = self._existing_workshop()
        workshop.location = room
        workshop.save()

        self._post([_row(id=workshop.pk, room="", capacity="")])

        workshop.refresh_from_db()
        self.assertEqual(workshop.location, room)
        room.refresh_from_db()
        self.assertEqual(room.capacity, 40)
