import json
from django.test import Client, TestCase
from django.urls import reverse

from registration.models import Location


class LocationAPITestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.location = Location.objects.create(
            room_num="101",
            building="Main Building",
            capacity=30
        )
        self.location_url = reverse('registration:location')
        self.location_id_url = reverse('registration:location_id', kwargs={'id': self.location.id})

    def test_post_location(self):
        data = {
            "room_num": "102",
            "building": "Annex Building",
            "capacity": 25,
            "session": 1
        }
        response = self.client.post(self.location_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201)

    def test_post_location_invalid_json(self):
        response = self.client.post(self.location_url, "Invalid JSON", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Invalid JSON", status_code=400)

    def test_post_location_already_exists(self):
        data = {
            "room_num": "101",
            "building": "Main Building",
            "capacity": 30,
            "session": 0
        }
        response = self.client.post(self.location_url, json.dumps(data), content_type="application/json")
        self.assertContains(response, "Location already exists", status_code=409)

    def test_get_location(self):
        response = self.client.get(self.location_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "101")

    def test_get_location_id(self):
        response = self.client.get(self.location_id_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "101")

    def test_put_location_id(self):
        data = {
            "room_num": "103",
            "building": "Main Building",
            "capacity": 40
        }
        response = self.client.put(self.location_id_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.location.refresh_from_db()
        self.assertEqual(self.location.room_num, "103")

    def test_put_location_id_not_found(self):
        data = {
            "room_num": "104",
            "building": "Main Building",
            "capacity": 50
        }
        invalid_url = reverse('registration:location_id', kwargs={'id': 999})
        response = self.client.put(invalid_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Location not found", status_code=404)

    def test_delete_location_id(self):
        response = self.client.delete(self.location_id_url)
        self.assertEqual(response.status_code, 200)
        with self.assertRaises(Location.DoesNotExist):
            Location.objects.get(id=self.location.id)

    def test_delete_location_id_not_found(self):
        invalid_url = reverse('registration:location_id', kwargs={'id': 999})
        response = self.client.delete(invalid_url)
        self.assertEqual(response.status_code, 200)