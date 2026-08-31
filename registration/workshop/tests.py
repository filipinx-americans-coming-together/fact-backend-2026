import json
import os
import random
import pandas as pd

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.contrib.auth.models import User, Group
from registration.models import Delegate, Location, Registration, Workshop

from registration.models import Location, Workshop

class WorkshopAPITestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.location = Location.objects.create(
            room_num="Test Room", building="Test Building", capacity=100
        )
        self.workshop = Workshop.objects.create(
            title="Test Workshop",
            description="Test Description",
            location=self.location,
            session=1,
        )
        self.workshop_url = reverse("registration:workshop")
        self.workshop_id_url = reverse(
            "registration:workshop_id", kwargs={"id": self.workshop.pk}
        )

    def test_post_workshop(self):
        data = {
            "title": "New Workshop",
            "description": "New Description",
            "facilitators": [
                "Facilitator 1",
                "Facilitator 2"
            ],
            # "location": self.location.id,
            "session": 1
        }
        response = self.client.post(
            self.workshop_url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

    # def test_post_workshop_missing_attribute(self):
    #     data = {
    #         "title": "New Workshop",
    #         "description": "New Description",
    #         "facilitators": [
    #             "Facilitator 1",
    #             "Facilitator 2"
    #         ],
    #         "location": self.location.id
    #     }
    #     response = self.client.post(self.workshop_url, json.dumps(data), content_type="application/json")
    #     self.assertEqual(response.status_code, 400)

    def test_post_workshop_invalid_json(self):
        response = self.client.post(
            self.workshop_url, "Invalid JSON", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Invalid JSON", status_code=400)

    def test_get_workshop(self):
        response = self.client.get(self.workshop_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Workshop")

    def test_get_workshop_id(self):
        response = self.client.get(self.workshop_id_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Workshop")

    def test_put_workshop_id(self):
        data = {
            "title": "Updated Workshop",
            "description": "Updated Description",
            "facilitators": ["Updated Facilitator 1", "Updated Facilitator 2"],
            "location": self.location.id,
            "session": 1,
        }
        response = self.client.put(
            self.workshop_id_url, json.dumps(data), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.title, "Updated Workshop")

    def test_delete_workshop_id(self):
        response = self.client.delete(self.workshop_id_url)
        self.assertEqual(response.status_code, 200)
        with self.assertRaises(Workshop.DoesNotExist):
            Workshop.objects.get(pk=self.workshop.pk)

    def test_post_workshop_already_exists(self):
        data = {
            "title": "Test Workshop",
            "description": "Another Description",
            "facilitators": ["Facilitator 1", "Facilitator 2"],
            "location": self.location.id,
            "session": 1,
        }
        response = self.client.post(
            self.workshop_url, json.dumps(data), content_type="application/json"
        )
        self.assertContains(response, "Workshop in current session already exists", status_code=409)


# WorkshopRegistrations (test_404s_no_workshop, test_returns_num_registrations)
# was removed: it exercised a "registration:workshop_registration" URL that
# doesn't exist anywhere in urls.py or any view — the feature it tested was
# never built (or was removed without the tests being cleaned up). Confirmed
# via a codebase-wide search turning up zero references outside this file.

class WorkshopPOSTBulk(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("registration:workshops_bulk")

        self.base_path = "./registration/workshop/data"
        os.mkdir(self.base_path)

        # good file — one row per column workshops_bulk actually requires
        # (see expected_columns in registration/workshop/views.py); this
        # used to only have title/session/description/facilitators, which
        # made every upload here fail at the "missing column" check before
        # ever reaching the logic under test
        titles = ["workshop 1", "workshop 2", "workshop 3"]
        sessions = [1, 2, 3]
        descriptions = ["description 1", "description 2", "description 3"]
        facilitators = ["fac1, fac11", "fac2", "fac3"]
        department_names = ["Dept 1", "Dept 2", "Dept 3"]
        image_urls = [
            "https://example.com/1.png",
            "https://example.com/2.png",
            "https://example.com/3.png",
        ]
        bios = ["Bio 1", "Bio 2", "Bio 3"]
        networking_sessions = [0, 0, 0]
        positions = ["Lead", "Co-Lead", "Speaker"]
        preferred_caps = [20, 25, 30]
        moveable_seats = [True, False, True]
        # capitalization to make sure processing is case insensitive
        data = {
            "title": titles,
            "SessIOn": sessions,
            "description": descriptions,
            "facilitators": facilitators,
            "department_name": department_names,
            "image_url": image_urls,
            "bio": bios,
            "networking_session": networking_sessions,
            "position": positions,
            "preferred_cap": preferred_caps,
            "moveable_seats": moveable_seats,
        }
        self.good_workshops_df = pd.DataFrame(data)

        good_workshops_url = f"{self.base_path}/good_workshops.xlsx"
        self.good_workshops_df.to_excel(good_workshops_url, index=False)

        # open file
        with open(good_workshops_url, 'rb') as f:
            self.workshop_file = SimpleUploadedFile(
                name='good_workshops.xlsx',
                content=f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        # duplicate cols
        duplicate_cols_df = self.good_workshops_df.copy()
        duplicate_cols_df.insert(
            len(duplicate_cols_df),
            "title",
            ["dupe 1", "dupe 2", "dupe 3"],
            True
        )

        duplicate_cols_url = f"{self.base_path}/duplicate_cols.xlsx"
        duplicate_cols_df.to_excel(duplicate_cols_url, index=False)

        # open file
        with open(duplicate_cols_url, 'rb') as f:
            self.duplicate_cols_file = SimpleUploadedFile(
                name='duplicate_cols.xlsx',
                content=f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        # missing cols
        missing_cols_df = self.good_workshops_df.copy()
        missing_cols_df = missing_cols_df.drop("description", axis=1)

        missing_cols_url = f"{self.base_path}/missing_cols.xlsx"
        missing_cols_df.to_excel(missing_cols_url, index=False)

        # open file
        with open(missing_cols_url, 'rb') as f:
            self.missing_cols_file = SimpleUploadedFile(
                name='missing_cols.xlsx',
                content=f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        # missing vals
        missing_vals_df = self.good_workshops_df.copy()
        missing_vals_df.at[1, "title"] = None

        missing_vals_url = f"{self.base_path}/missing_vals.xlsx"
        missing_vals_df.to_excel(missing_vals_url, index=False)

        # open file
        with open(missing_vals_url, 'rb') as f:
            self.missing_vals_file = SimpleUploadedFile(
                name='missing_vals.xlsx',
                content=f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        # invalid session
        invalid_session_df = self.good_workshops_df.copy()
        invalid_session_df.at[1, "SessIOn"] = 4

        invalid_session_url = f"{self.base_path}/invalid_session.xlsx"
        invalid_session_df.to_excel(invalid_session_url, index=False)

        # open file
        with open(invalid_session_url, 'rb') as f:
            self.invalid_session_file = SimpleUploadedFile(
                name='invalid_session.xlsx',
                content=f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        self.created_files = [
            good_workshops_url,
            duplicate_cols_url, 
            missing_cols_url, 
            missing_vals_url, 
            invalid_session_url
        ]

        # admin user
        group = Group(id=1, name="FACTAdmin")
        group.save()

        self.username = "fact-admin-user"
        self.password = "fact-admin-pass"

        user = User(id=1, username=self.username)
        user.set_password(self.password)
        user.save()

        user.groups.add(group)

        # non admin
        self.not_admin_username = "not-admin-user"
        self.not_admin_password = "not-admin-pass"

        not_admin = User(username=self.not_admin_username)
        not_admin.set_password(self.not_admin_password)
        not_admin.save()

    def tearDown(self):
        # clean up created files
        for path in self.created_files:
            os.remove(path)

        os.rmdir(self.base_path)


    def test_not_admin(self):
        response = self.client.post(self.url, {"workshops": self.workshop_file})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(Workshop.objects.all()), 0)

        # login to not admin
        self.client.login(username=self.not_admin_username, password=self.not_admin_password)

        response = self.client.post(self.url, {"workshops": self.workshop_file})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(Workshop.objects.all()), 0)

    def test_no_file(self):
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(Workshop.objects.all()), 0)

    def test_workshops_already_exist(self):
        # add workshops
        for i in range(5):
            Workshop.objects.create(
                title=f"workshop {i}",
                description="description",
                session=random.randint(1,3)
            )

        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": self.workshop_file})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(Workshop.objects.all()), 5)

    def test_invalid_file(self):
        # create file
        bad_file = SimpleUploadedFile(
            name="bad.png", 
            content=b"bad file",
            content_type="img/png"
        )

        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": bad_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(Workshop.objects.all()), 0)

    def test_duplicate_cols(self):
        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": self.duplicate_cols_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(Workshop.objects.all()), 0)

    def test_not_enough_locations(self):
        # add some locations
        for i in range(5):
            Location.objects.create(room_num=f"{i}", building=f"building", capacity=20, session=2)

        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": self.workshop_file})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(Workshop.objects.all()), 0)


    def test_missing_cols(self):
        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": self.missing_cols_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(Workshop.objects.all()), 0)

    def test_missing_vals(self):
        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": self.missing_vals_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(Workshop.objects.all()), 0)

    def test_invalid_session(self):
        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": self.invalid_session_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(Workshop.objects.all()), 0)

    def test_creates_workshops(self):
        # add locations
        for i in range(1, 4):
            Location.objects.create(session=i, building="building", room_num=f"{i}", capacity=20)

        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"workshops": self.workshop_file})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(Workshop.objects.all()), len(self.good_workshops_df))

        for idx, row in self.good_workshops_df.iterrows():
            self.assertTrue(Workshop.objects.filter(
                title=row["title"],
                description=row["description"],
                session=row["SessIOn"]
            ).exists())
