from django.contrib.auth.models import User
from django.test import Client, TestCase

from .models import Delegate, Registration, Workshop


class DelegateWorkshopAdminTest(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser("admin", "admin@example.com", "pw")
        user = User.objects.create_user(
            "ana", "ana@example.com", "pw", first_name="Ana", last_name="Cruz"
        )
        self.delegate = Delegate.objects.create(user=user)
        self.workshop = Workshop.objects.create(title="Kapwa 101", description="x", session=2)
        Registration.objects.create(delegate=self.delegate, workshop=self.workshop)

        other = User.objects.create_user(
            "ben", "ben@example.com", "pw", first_name="Ben", last_name="Reyes"
        )
        other_delegate = Delegate.objects.create(user=other)
        other_workshop = Workshop.objects.create(title="Bayanihan", description="x", session=1)
        Registration.objects.create(delegate=other_delegate, workshop=other_workshop)

        self.client = Client()
        self.client.force_login(self.admin_user)

    def _results(self, params):
        response = self.client.get("/admin/registration/registration/", params)
        self.assertEqual(response.status_code, 200)
        return list(response.context["cl"].result_list)

    def test_delegate_page_lists_their_workshops(self):
        response = self.client.get(
            f"/admin/registration/delegate/{self.delegate.id}/change/"
        )
        self.assertEqual(response.status_code, 200)
        inline_formset = response.context["inline_admin_formsets"][0].formset
        self.assertEqual(
            [form.instance.workshop for form in inline_formset.forms],
            [self.workshop],
        )
        self.assertContains(response, "Kapwa 101")

    def test_registration_search_by_delegate_name_and_email(self):
        for q in ("Cruz", "Ana", "ana@example.com"):
            results = self._results({"q": q})
            self.assertEqual([r.workshop for r in results], [self.workshop])

    def test_registration_filter_by_session_and_workshop(self):
        results = self._results({"workshop__session__exact": 2})
        self.assertEqual([r.delegate for r in results], [self.delegate])

        results = self._results({"workshop__id__exact": self.workshop.id})
        self.assertEqual([r.delegate for r in results], [self.delegate])

    def test_registration_list_shows_session_column(self):
        response = self.client.get("/admin/registration/registration/")
        self.assertContains(response, "column-workshop_session")
