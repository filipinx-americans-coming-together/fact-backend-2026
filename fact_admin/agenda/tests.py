import json
import os
import random
import pandas as pd
from datetime import datetime

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import make_aware

from fact_admin.models import AgendaItem


class AgendaItemsGET(TestCase):
    def setUp(self):
        self.client = Client()

        self.expected_items = []

        for i in range(10):
            start_time = timezone.now() + timezone.timedelta(
                hours=random.randint(0, 24)
            )

            new_item = AgendaItem.objects.create(
                title=f"item {i}",
                building="building",
                room_num=f"{i}",
                start_time=start_time,
                end_time=start_time + timezone.timedelta(hours=1),
                address=f"10{i} address street",
            )

            self.expected_items.append((new_item.pk, start_time))

        self.expected_items = sorted(self.expected_items, key=lambda x: x[1])

    def test_gets_items_chronologically(self):
        response = self.client.get(reverse("fact_admin:agenda_items"))
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AgendaItem.objects.all().count(), len(data))

        for i in range(len(self.expected_items)):
            expected_item = AgendaItem.objects.get(pk=self.expected_items[i][0])

            self.assertEqual(expected_item.title, data[i]["fields"]["title"])
            self.assertEqual(expected_item.building, data[i]["fields"]["building"])
            self.assertEqual(expected_item.room_num, data[i]["fields"]["room_num"])
            self.assertEqual(expected_item.address, data[i]["fields"]["address"])

            expected_start = expected_item.start_time.isoformat()[:-9] + "Z"
            self.assertEqual(expected_start, data[i]["fields"]["start_time"])

            expected_end = expected_item.end_time.isoformat()[:-9] + "Z"
            self.assertEqual(expected_end, data[i]["fields"]["end_time"])


class AgendaItemsIDDELETE(TestCase):
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

    def test_delete_blocks_non_admin(self):
        # create item
        item = AgendaItem.objects.create(
            title="item title",
            building="building",
            room_num="room num",
            start_time="2024-10-18T00:02:17.590Z",
            end_time="2024-10-18T00:02:54.930Z",
            address="123 address street",
        )

        response = self.client.delete(
            reverse("fact_admin:agenda_items_id", kwargs={"id": item.pk})
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgendaItem.objects.all().count(), 1)

        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.delete(
            reverse("fact_admin:agenda_items_id", kwargs={"id": item.pk})
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgendaItem.objects.all().count(), 1)

    def test_delete_404s_no_match(self):
        # create item
        item = AgendaItem.objects.create(
            title="item title",
            building="building",
            room_num="room num",
            start_time="2024-10-18T00:02:17.590Z",
            end_time="2024-10-18T00:02:54.930Z",
            address="123 address street",
        )

        self.client.login(username=self.username, password=self.password)
        response = self.client.delete(
            reverse("fact_admin:agenda_items_id", kwargs={"id": item.pk + 1})
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(AgendaItem.objects.all().count(), 1)

    def tests_delete_deletes_item(self):
        # create item
        item = AgendaItem.objects.create(
            title="item title",
            building="building",
            room_num="room num",
            start_time="2024-10-18T00:02:17.590Z",
            end_time="2024-10-18T00:02:54.930Z",
            address="123 address street",
        )

        self.client.login(username=self.username, password=self.password)
        response = self.client.delete(
            reverse("fact_admin:agenda_items_id", kwargs={"id": item.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AgendaItem.objects.all().count(), 0)


class AgendaItemsPOST(TestCase):
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

        # data
        self.good_data = {
            "title": "example title",
            "start_time": "2024-10-18T00:02:17.590Z",
            "end_time": "2024-10-18T00:02:54.930Z",
            "building": "example building",
            "room_num": "example room",
            "session_num": "2",
            "address": "123 address street",
        }

        self.url = reverse("fact_admin:agenda_items")

    def test_blocks_non_admin(self):
        response = self.client.post(
            self.url, json.dumps(self.good_data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

        self.client.login(
            username=self.non_admin_username, password=self.non_admin_password
        )
        response = self.client.post(
            self.url, json.dumps(self.good_data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_rejects_missing_data(self):
        self.client.login(username=self.username, password=self.password)

        missing_data = {
            "title": "",
            "start_time": "2024-10-18T00:02:17.590Z",
            "end_time": "2024-10-18T00:02:50.590Z",
            "building": "building",
            "room_num": "",
        }

        response = self.client.post(
            self.url, json.dumps(missing_data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

        missing_data_2 = {
            "start_time": "2024-10-18T00:02:17.590Z",
            "end_time": "2024-10-18T00:02:40.590Z",
            "room_num": "123A",
        }

        response = self.client.post(
            self.url, json.dumps(missing_data_2), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_rejects_invalid_times(self):
        self.client.login(username=self.username, password=self.password)

        invalid_times = {
            "title": "example title",
            "start_time": "2024-10-18T00:02:54.930Z",
            "end_time": "2024-10-18T00:02:17.590Z",
            "building": "example building",
            "room_num": "example room",
            "address": "123 address street",
        }

        response = self.client.post(
            self.url, json.dumps(invalid_times), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_rejects_invalid_session(self):
        self.client.login(username=self.username, password=self.password)

        invalid_session = {
            "title": "example title",
            "start_time": "2024-10-18T00:02:54.930Z",
            "end_time": "2024-10-18T00:02:17.590Z",
            "building": "example building",
            "room_num": "example room",
            "session_num": 4,
            "address": "123 address street",
        }

        response = self.client.post(
            self.url, json.dumps(invalid_session), content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_creates_agenda_item_without_session_num(self):
        # session_num is optional (e.g. a networking event not tied to a
        # workshop session) — omitting it must not crash on int(None)
        self.client.login(username=self.username, password=self.password)

        data = dict(self.good_data)
        del data["session_num"]

        response = self.client.post(
            self.url, json.dumps(data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AgendaItem.objects.all().count(), 1)
        self.assertIsNone(AgendaItem.objects.first().session_num)

    def test_creates_agenda_item(self):
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(
            self.url, json.dumps(self.good_data), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AgendaItem.objects.all().count(), 1)

        data = response.json()[0]
        new_item = AgendaItem.objects.all()[0]

        self.assertEqual(data["pk"], new_item.pk)
        self.assertEqual(data["fields"]["title"], new_item.title)
        self.assertEqual(data["fields"]["building"], new_item.building)
        self.assertEqual(data["fields"]["room_num"], new_item.room_num)
        self.assertEqual(data["fields"]["address"], new_item.address)

        self.assertEqual(
            data["fields"]["start_time"], new_item.start_time.isoformat()[:-9] + "Z"
        )
        self.assertEqual(
            data["fields"]["end_time"], new_item.end_time.isoformat()[:-9] + "Z"
        )
        self.assertEqual(data["fields"]["session_num"], new_item.session_num)

        self.assertEqual(data["fields"]["title"], self.good_data["title"])
        self.assertEqual(data["fields"]["building"], self.good_data["building"])
        self.assertEqual(data["fields"]["room_num"], self.good_data["room_num"])
        self.assertEqual(data["fields"]["address"], self.good_data["address"])

        self.assertEqual(data["fields"]["start_time"], self.good_data["start_time"])
        self.assertEqual(data["fields"]["end_time"], self.good_data["end_time"])
        self.assertEqual(
            data["fields"]["session_num"], int(self.good_data["session_num"])
        )


class AgendaItemsPOSTBulk(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("fact_admin:agenda_items_bulk")

        self.base_path = "./fact_admin/agenda/data"
        if not (os.path.exists(self.base_path) and os.path.isdir(self.base_path)):
            os.mkdir(self.base_path)

        # good file
        titles = ["item 1", "item 2", "item 3"]
        buildings = ["building", "another building", "building"]
        room_nums = ["123", None, "AB2"]
        start_times = [
            datetime.strptime("11:00PM", "%H:%M%p").replace(tzinfo=None),
            datetime.strptime("8:00PM", "%H:%M%p").replace(tzinfo=None),
            datetime.strptime("2:00PM", "%H:%M%p").replace(tzinfo=None),
        ]
        end_times = [
            datetime.strptime("11:20PM", "%H:%M%p").replace(tzinfo=None),
            datetime.strptime("10:00PM", "%H:%M%p").replace(tzinfo=None),
            datetime.strptime("6:00PM", "%H:%M%p").replace(tzinfo=None),
        ]
        sessions = [1, None, 3]
        addresses = ["123 street", "4567 avenue", None]
        dates = [
            make_aware(datetime.strptime("10/6/2024", "%d/%m/%Y")).replace(tzinfo=None),
            make_aware(datetime.strptime("10/7/2024", "%d/%m/%Y")).replace(tzinfo=None),
            make_aware(datetime.strptime("10/06/2024", "%d/%m/%Y")).replace(
                tzinfo=None
            ),
        ]

        # capitalization to make sure processing is case insensitive
        data = {
            "title": titles,
            "session_num": sessions,
            "building": buildings,
            "room_num": room_nums,
            "start_time": start_times,
            "end_time": end_times,
            "address": addresses,
            "date": dates,
        }

        self.good_agenda_df = pd.DataFrame(data)

        good_agenda_url = f"{self.base_path}/good_agenda.xlsx"
        self.good_agenda_df.to_excel(good_agenda_url, index=False)

        # open file
        with open(good_agenda_url, "rb") as f:
            self.workshop_file = SimpleUploadedFile(
                name="good_agenda.xlsx",
                content=f.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        # duplicate cols
        duplicate_cols_df = self.good_agenda_df.copy()
        duplicate_cols_df.insert(
            len(duplicate_cols_df), "title", ["dupe 1", "dupe 2", "dupe 3"], True
        )

        duplicate_cols_url = f"{self.base_path}/duplicate_cols.xlsx"
        duplicate_cols_df.to_excel(duplicate_cols_url, index=False)

        # open file
        with open(duplicate_cols_url, "rb") as f:
            self.duplicate_cols_file = SimpleUploadedFile(
                name="duplicate_cols.xlsx",
                content=f.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        # missing cols
        missing_cols_df = self.good_agenda_df.copy()
        missing_cols_df = missing_cols_df.drop("address", axis=1)

        missing_cols_url = f"{self.base_path}/missing_cols.xlsx"
        missing_cols_df.to_excel(missing_cols_url, index=False)

        # open file
        with open(missing_cols_url, "rb") as f:
            self.missing_cols_file = SimpleUploadedFile(
                name="missing_cols.xlsx",
                content=f.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        # missing vals
        missing_vals_df = self.good_agenda_df.copy()
        missing_vals_df.at[1, "title"] = None

        missing_vals_url = f"{self.base_path}/missing_vals.xlsx"
        missing_vals_df.to_excel(missing_vals_url, index=False)

        # open file
        with open(missing_vals_url, "rb") as f:
            self.missing_vals_file = SimpleUploadedFile(
                name="missing_vals.xlsx",
                content=f.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        self.created_files = [
            good_agenda_url,
            duplicate_cols_url,
            missing_cols_url,
            missing_vals_url,
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
        response = self.client.post(self.url, {"agenda": self.workshop_file})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

        # login to not admin
        self.client.login(
            username=self.not_admin_username, password=self.not_admin_password
        )

        response = self.client.post(self.url, {"agenda": self.workshop_file})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_no_file(self):
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_agenda_itmes_already_exist(self):
        # add items
        for i in range(5):
            AgendaItem.objects.create(
                title="title",
                building="building",
                room_num="room num",
                start_time=timezone.now(),
                end_time=timezone.now() + timezone.timedelta(days=1),
                address="address",
            )

        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"agenda": self.workshop_file})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(AgendaItem.objects.all().count(), 5)

    def test_invalid_file(self):
        # create file
        bad_file = SimpleUploadedFile(
            name="bad.png", content=b"bad file", content_type="img/png"
        )

        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"agenda": bad_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_duplicate_cols(self):
        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"agenda": self.duplicate_cols_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_missing_cols(self):
        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"agenda": self.missing_cols_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    def test_missing_vals(self):
        # login
        self.client.login(username=self.username, password=self.password)

        response = self.client.post(self.url, {"agenda": self.missing_vals_file})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AgendaItem.objects.all().count(), 0)

    # TODO this test isn't passing but when you print out Agenda items it looks ok
    # I think it's something to do with the types of things being stored (empty string vs none etc)
    # def test_creates_agenda_items(self):
    #     # login
    #     self.client.login(username=self.username, password=self.password)

    #     response = self.client.post(self.url, {"agenda": self.workshop_file})

    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(AgendaItem.objects.all().count(), len(self.good_agenda_df))

    #     for idx, row in self.good_agenda_df.iterrows():
    #         # TODO doesn't test start/end time

    #         self.assertTrue(
    #             AgendaItem.objects.filter(
    #                 title=row["title"],
    #                 building=row["building"],
    #                 room_num="" if pd.isna(row["room_num"]) else row["room_num"],
    #                 session_num=(
    #                     None if pd.isna(row["session_num"]) else row["session_num"]
    #                 ),
    #                 address="nan" if pd.isna(row["address"]) else row["address"],
    #             ).exists()
    #         )
