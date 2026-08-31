import json

from django.test import Client, TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from registration.models import Facilitator
from registration.models import FacilitatorRegistration
from registration.models import FacilitatorWorkshop
from registration.models import Location
from registration.models import Workshop


class FacilitatorAPITestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(username='facilitator1', email='facilitator1@example.com', password='password')
        self.facilitator1 = Facilitator.objects.create(user=self.user1, fa_name="Facilitator One", fa_contact="123-456-7890", department_name="Dept1", position="Prof", facilitators=[], image_url="http://example.com/img1.png", bio="Bio1", attending_networking_session=False)
        self.user2 = User.objects.create_user(username='facilitator2', email='facilitator2@example.com', password='password')
        self.facilitator2 = Facilitator.objects.create(user=self.user2, fa_name="Facilitator Two", fa_contact="222-333-4444", department_name="Dept2", position="Prof2", facilitators=[], image_url="http://example.com/img2.png", bio="Bio2", attending_networking_session=False)
        self.user3 = User.objects.create_user(username='facilitator3', email='facilitator3@example.com', password='password')
        self.facilitator3 = Facilitator.objects.create(user=self.user3, fa_name="Facilitator Three", fa_contact="333-444-5555", department_name="Dept3", position="Prof3", facilitators=[], image_url="http://example.com/img3.png", bio="Bio3", attending_networking_session=False)
        self.other_user = User.objects.create_user(username='other', email='other@example.com', password='password')
        self.other_facilitator = Facilitator.objects.create(user=self.other_user, fa_name="Other", fa_contact="000-000-0000", department_name="OtherDept", position="OtherProf", facilitators=[], image_url="http://example.com/img4.png", bio="OtherBio", attending_networking_session=False)
        self.workshop = Workshop.objects.create(title="Workshop1", description="desc", session=1)
        self.facilitator_url = reverse('registration:facilitators')
        self.me_url = reverse('registration:facilitators_me')
        self.login_url = reverse('registration:facilitators_login')
        self.setup_url = reverse('registration:facilitators_set_up')
        self.register_url = reverse('registration:register_facilitator')

    def test_get_facilitator(self):
        self.client.login(username='facilitator1', password='password')
        
        response = self.client.get(self.facilitator_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Facilitator One")

    def test_post_facilitator(self):
        data = {
            "f_name": "New",
            "l_name": "Facilitator",
            "email": "newfacilitator@example.com",
            "password": "Xk9$mVq2pL7zW",  # "password123" fails CommonPasswordValidator
            "fa_name": "New Facilitator",
            "fa_contact": "987-654-3210",
            "workshops": []
        }
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Facilitator.objects.count(), 5)  # 4 from setUp + 1 new facilitator

    def test_put_facilitator(self):
        self.client.login(username='facilitator1', password='password')
        
        data = {
            "f_name": "Updated",
            "l_name": "Facilitator",
            "email": "updatedfacilitator@example.com",
            "password": "newpassword123",
            "fa_name": "Updated Facilitator",
            "fa_contact": "111-222-3333",
            "workshops": []
        }
        response = self.client.put(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.facilitator1.refresh_from_db()
        self.assertEqual(self.facilitator1.fa_name, "Updated Facilitator")
        self.assertEqual(self.facilitator1.fa_contact, "111-222-3333")

    def test_delete_facilitator(self):
        self.client.login(username='facilitator1', password='password')
        
        response = self.client.delete(self.facilitator_url)
        self.assertEqual(response.status_code, 200)
        with self.assertRaises(Facilitator.DoesNotExist):
            Facilitator.objects.get(pk=self.facilitator1.pk)

    def test_post_facilitator_already_exists(self):
        data = {
            "f_name": "Facilitator",
            "l_name": "One",
            "email": "facilitator1@example.com",
            "password": "password",
            "fa_name": "Facilitator One",
            "fa_contact": "123-456-7890",
            "workshops": []
        }
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Email already in use", status_code=400)

    def test_put_invalid_email(self):
        self.client.force_login(self.user3)
        data = {"f_name": "Fac", "l_name": "Three", "email": "bademail", "password": "password", "workshops": []}
        response = self.client.put(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid email", response.json().get("message", ""))

    def test_put_email_already_in_use(self):
        self.client.force_login(self.user3)
        data = {"f_name": "Fac", "l_name": "Three", "email": "other@example.com", "password": "password", "workshops": []}
        response = self.client.put(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Email already in use", response.json().get("message", ""))

    def test_put_password_change_success(self):
        self.client.force_login(self.user3)
        data = {"f_name": "Fac", "l_name": "Three", "email": "facilitator3@example.com", "password": "password", "new_password": "newpassword123", "workshops": []}
        response = self.client.put(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.user3.refresh_from_db()
        self.assertTrue(self.user3.check_password("newpassword123"))

    def test_put_password_change_wrong_old(self):
        self.client.force_login(self.user3)
        data = {"f_name": "Fac", "l_name": "Three", "email": "facilitator3@example.com", "password": "wrong", "new_password": "newpassword123", "workshops": []}
        response = self.client.put(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Old password does not match", response.json().get("message", ""))

    def test_put_password_change_weak(self):
        self.client.force_login(self.user3)
        data = {"f_name": "Fac", "l_name": "Three", "email": "facilitator3@example.com", "password": "password", "new_password": "123", "workshops": []}
        response = self.client.put(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Password is not strong enough", response.json().get("message", ""))

    def test_put_update_workshops(self):
        self.client.force_login(self.user3)
        data = {"f_name": "Fac", "l_name": "Three", "email": "facilitator3@example.com", "password": "password", "workshops": [self.workshop.pk]}
        response = self.client.put(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(FacilitatorWorkshop.objects.filter(facilitator=self.facilitator3, workshop=self.workshop).exists())

    def test_post_missing_first_name(self):
        data = {"l_name": "Three", "email": "new@example.com", "password": "password123", "workshops": []}
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("First name must be at least one character", response.json().get("message", ""))

    def test_post_missing_last_name(self):
        data = {"f_name": "Fac", "email": "new@example.com", "password": "password123", "workshops": []}
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Last name must be at least one character", response.json().get("message", ""))

    def test_post_invalid_email(self):
        data = {"f_name": "Fac", "l_name": "Three", "email": "bademail", "password": "password123", "workshops": []}
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid email", response.json().get("message", ""))

    def test_post_email_already_in_use(self):
        data = {"f_name": "Fac", "l_name": "Three", "email": "facilitator3@example.com", "password": "password123", "workshops": []}
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Email already in use", response.json().get("message", ""))

    def test_post_weak_password(self):
        data = {"f_name": "Fac", "l_name": "Three", "email": "new@example.com", "password": "123", "workshops": []}
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Password is not strong enough", response.json().get("message", ""))

    def test_post_valid_with_workshops(self):
        data = {"f_name": "Fac", "l_name": "Three", "email": "new2@example.com", "password": "Xk9$mVq2pL7zW", "workshops": [self.workshop.pk]}
        response = self.client.post(self.facilitator_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        new_user = User.objects.get(email="new2@example.com")
        new_fac = Facilitator.objects.get(user=new_user)
        self.assertTrue(FacilitatorWorkshop.objects.filter(facilitator=new_fac, workshop=self.workshop).exists())

    def test_delete_no_auth(self):
        response = self.client.delete(self.facilitator_url)
        self.assertEqual(response.status_code, 403)
        self.assertIn("No facilitator logged in", response.json().get("message", ""))

    def test_delete_success(self):
        self.client.force_login(self.user3)
        response = self.client.delete(self.facilitator_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("success", response.json().get("message", ""))
        self.assertFalse(User.objects.filter(pk=self.user3.pk).exists())

    # --- /facilitators/me/ endpoint ---
    def test_me_requires_authentication(self):
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, 403)
        self.assertIn("No facilitator logged in", response.json().get("message", ""))

    def test_me_success(self):
        self.client.force_login(self.user2)
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Facilitator Two", response.content.decode())

    def test_login_facilitator_success(self):
        data = {"username": "facilitator2", "password": "password"}
        response = self.client.post(self.login_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Facilitator Two", response.content.decode())

    def test_login_facilitator_invalid_creds(self):
        data = {"username": "facilitator2", "password": "wrongpass"}
        response = self.client.post(self.login_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid credentials", response.json().get("message", ""))

    def test_login_facilitator_missing_fields(self):
        response = self.client.post(self.login_url, json.dumps({}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Must provide username", response.json().get("message", ""))

    def test_facilitator_account_set_up_missing_fields(self):
        response = self.client.post(self.setup_url, json.dumps({}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Must provide password", response.json().get("message", ""))

    def test_facilitator_account_set_up_invalid_email(self):
        data = {"email": "bademail", "password": "password123", "token": "sometoken"}
        response = self.client.post(self.setup_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid email", response.json().get("message", ""))

    def test_facilitator_account_set_up_invalid_token(self):
        # a strong, non-common password — this test targets the invalid-token
        # branch specifically, which only runs after password-strength
        # validation passes; "password123" is common enough to be rejected
        # by CommonPasswordValidator first, masking the intended failure mode
        data = {"email": "facilitator2@example.com", "password": "Xk9$mVq2pL7zW", "token": "badtoken"}
        response = self.client.post(self.setup_url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertIn("Invalid set up token", response.json().get("message", ""))

    def test_register_facilitator_missing_fields(self):
        # register_facilitator only handles PUT (see its docstring/method
        # check) — GET is separately covered by
        # test_register_facilitator_method_not_allowed below
        response = self.client.put(self.register_url, json.dumps({}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Must provide facilitator name", response.json().get("message", ""))

    def test_register_facilitator_method_not_allowed(self):
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 405)
        self.assertIn("method not allowed", response.json().get("message", ""))

    def test_register_facilitator_success(self):
        location = Location.objects.create(building="B", room_num="1", capacity=5, session=1)
        workshop = Workshop.objects.create(title="Capped Workshop", description="d", session=1, location=location)

        data = {"facilitator_name": "New Name", "workshops": [workshop.pk]}
        response = self.client.put(self.register_url, json.dumps(data), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            FacilitatorRegistration.objects.filter(
                facilitator_name="New Name", workshop_id=workshop.pk
            ).exists()
        )

    def test_register_facilitator_rejects_duplicate_session(self):
        location_a = Location.objects.create(building="B", room_num="1", capacity=5, session=1)
        location_b = Location.objects.create(building="B", room_num="2", capacity=5, session=1)
        workshop_a = Workshop.objects.create(title="A", description="d", session=1, location=location_a)
        workshop_b = Workshop.objects.create(title="B", description="d", session=1, location=location_b)

        data = {"facilitator_name": "New Name", "workshops": [workshop_a.pk, workshop_b.pk]}
        response = self.client.put(self.register_url, json.dumps(data), content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("single session", response.json().get("message", ""))

    def test_register_facilitator_rejects_full_workshop(self):
        location = Location.objects.create(building="B", room_num="1", capacity=1, session=1)
        workshop = Workshop.objects.create(title="Full Workshop", description="d", session=1, location=location)
        FacilitatorRegistration.objects.create(facilitator_name="Existing", workshop_id=workshop.pk)

        data = {"facilitator_name": "New Name", "workshops": [workshop.pk]}
        response = self.client.put(self.register_url, json.dumps(data), content_type="application/json")

        self.assertEqual(response.status_code, 409)
        self.assertIn("is full", response.json().get("message", ""))

    def test_register_facilitator_unknown_workshop(self):
        data = {"facilitator_name": "New Name", "workshops": [999999]}
        response = self.client.put(self.register_url, json.dumps(data), content_type="application/json")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Workshop not found", response.json().get("message", ""))
