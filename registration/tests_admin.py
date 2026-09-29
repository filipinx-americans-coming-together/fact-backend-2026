from django.contrib.auth.models import User
from django.test import Client, TestCase

from .admin import registration_problems
from .models import Delegate, FacilitatorRegistration, Location, Registration, School, Workshop


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


class RegistrationAdminChecksTest(TestCase):
    """Admin edits follow the website's registration rules."""

    def setUp(self):
        admin_user = User.objects.create_superuser("admin", "admin@example.com", "pw")
        self.client = Client()
        self.client.force_login(admin_user)

        self.delegate = self._delegate("ana", payment_status="paid", ticket_type="workshop")
        self.s1_a = self._workshop("S1 A", 1, capacity=5)
        self.s1_b = self._workshop("S1 B", 1, capacity=5)
        self.s2 = self._workshop("S2", 2, capacity=1)
        self.s3_no_room = Workshop.objects.create(title="S3 No Room", description="x", session=3)
        Registration.objects.create(delegate=self.delegate, workshop=self.s1_a)

    def _delegate(self, username, **fields):
        user = User.objects.create_user(username, f"{username}@example.com", "pw")
        school = School.objects.get_or_create(name="UIUC")[0]
        return Delegate.objects.create(
            user=user, pronouns="they/them", year="Junior", school=school, **fields
        )

    def _workshop(self, title, session, capacity):
        location = Location.objects.create(
            building="Hall", room_num=title, capacity=capacity, session=session
        )
        return Workshop.objects.create(
            title=title, description="x", session=session, location=location
        )

    def _change_page_data(self, delegate):
        """The delegate change form's current values, as a browser would post them."""
        response = self.client.get(f"/admin/registration/delegate/{delegate.pk}/change/")
        data = {}
        form = response.context["adminform"].form
        for bound in form:
            value = bound.value()
            if value is None or value is False:
                continue
            data[bound.html_name] = "on" if value is True else value
        for inline in response.context["inline_admin_formsets"]:
            formset = inline.formset
            for bound in formset.management_form:
                data[bound.html_name] = bound.value()
            for f in formset.forms:
                for bound in f:
                    value = bound.value()
                    if value not in (None, False):
                        data[bound.html_name] = value
        return data

    def _save_workshops(self, delegate, workshops):
        """Replace the inline rows with `workshops` and save the delegate page."""
        data = self._change_page_data(delegate)
        prefix = "registration_set"
        existing = list(Registration.objects.filter(delegate=delegate).order_by("workshop__session"))
        for i, reg in enumerate(existing):
            data[f"{prefix}-{i}-DELETE"] = "on"
        for j, workshop in enumerate(workshops):
            i = len(existing) + j
            data[f"{prefix}-{i}-workshop"] = workshop.pk
            data[f"{prefix}-{i}-delegate"] = delegate.pk
        data[f"{prefix}-TOTAL_FORMS"] = len(existing) + len(workshops)
        return self.client.post(
            f"/admin/registration/delegate/{delegate.pk}/change/", data, follow=True
        )

    def _add_row(self, delegate, workshop):
        """Keep existing rows and add one."""
        data = self._change_page_data(delegate)
        prefix = "registration_set"
        i = int(data[f"{prefix}-TOTAL_FORMS"])
        data[f"{prefix}-{i}-workshop"] = workshop.pk
        data[f"{prefix}-{i}-delegate"] = delegate.pk
        data[f"{prefix}-TOTAL_FORMS"] = i + 1
        return self.client.post(
            f"/admin/registration/delegate/{delegate.pk}/change/", data, follow=True
        )

    def _held(self, delegate):
        return set(
            Registration.objects.filter(delegate=delegate).values_list("workshop__title", flat=True)
        )

    def test_valid_change_saves(self):
        response = self._add_row(self.delegate, self.s2)

        self.assertNotContains(response, "errornote")
        self.assertEqual(self._held(self.delegate), {"S1 A", "S2"})

    def test_same_session_blocked(self):
        response = self._add_row(self.delegate, self.s1_b)

        self.assertContains(response, "Only one workshop per session")
        self.assertEqual(self._held(self.delegate), {"S1 A"})

    def test_swap_within_session_allowed(self):
        response = self._save_workshops(self.delegate, [self.s1_b])

        self.assertNotContains(response, "errornote")
        self.assertEqual(self._held(self.delegate), {"S1 B"})

    def test_duplicate_workshop_blocked(self):
        response = self._add_row(self.delegate, self.s1_a)

        self.assertContains(response, "is listed more than once")
        self.assertEqual(Registration.objects.filter(delegate=self.delegate).count(), 1)

    def test_full_workshop_blocked(self):
        Registration.objects.create(delegate=self._delegate("ben"), workshop=self.s2)

        response = self._add_row(self.delegate, self.s2)

        self.assertContains(response, "is full (1/1)")
        self.assertEqual(self._held(self.delegate), {"S1 A"})

    def test_facilitator_seats_count_toward_capacity(self):
        FacilitatorRegistration.objects.create(facilitator_name="Fa", workshop=self.s2)

        response = self._add_row(self.delegate, self.s2)

        self.assertContains(response, "is full")
        self.assertEqual(self._held(self.delegate), {"S1 A"})

    def test_keeping_a_seat_in_an_overfull_workshop_is_allowed(self):
        Registration.objects.create(delegate=self.delegate, workshop=self.s2)
        Registration.objects.create(delegate=self._delegate("ben"), workshop=self.s2)

        response = self._add_row(self.delegate, self._workshop("S3", 3, capacity=5))

        self.assertNotContains(response, "errornote")
        self.assertEqual(self._held(self.delegate), {"S1 A", "S2", "S3"})

    def test_workshop_without_room_blocked(self):
        response = self._add_row(self.delegate, self.s3_no_room)

        self.assertContains(response, "has no room yet")
        self.assertEqual(self._held(self.delegate), {"S1 A"})

    def test_unpaid_delegate_saves_with_warning(self):
        unpaid = self._delegate("cam")

        response = self._add_row(unpaid, self.s2)

        self.assertContains(response, "isn&#x27;t a paid workshop or bundle ticket holder")
        self.assertEqual(self._held(unpaid), {"S2"})

    def test_paid_delegate_gets_no_warning(self):
        response = self._add_row(self.delegate, self.s2)

        self.assertNotContains(response, "ticket holder")

    def test_registration_page_add_same_session_blocked(self):
        response = self.client.post(
            "/admin/registration/registration/add/",
            {"delegate": self.delegate.pk, "workshop": self.s1_b.pk},
        )

        self.assertContains(response, "Only one workshop per session")
        self.assertEqual(self._held(self.delegate), {"S1 A"})

    def test_registration_page_add_full_blocked(self):
        Registration.objects.create(delegate=self._delegate("ben"), workshop=self.s2)

        response = self.client.post(
            "/admin/registration/registration/add/",
            {"delegate": self.delegate.pk, "workshop": self.s2.pk},
        )

        self.assertContains(response, "is full")
        self.assertEqual(self._held(self.delegate), {"S1 A"})

    def test_unsaved_delegate_checks_capacity(self):
        # "Add delegate" validates the workshop rows before the delegate is saved.
        new = Delegate(user=User.objects.create_user("dee", "dee@example.com", "pw"))
        Registration.objects.create(delegate=self._delegate("ben"), workshop=self.s2)

        self.assertEqual(registration_problems(new, [self.s1_b]), [])
        self.assertEqual(registration_problems(new, [self.s2]), ['"S2" is full (1/1).'])

    def test_registration_page_edit_to_other_session_allowed(self):
        reg = Registration.objects.get(delegate=self.delegate)

        response = self.client.post(
            f"/admin/registration/registration/{reg.pk}/change/",
            {"delegate": self.delegate.pk, "workshop": self.s2.pk},
            follow=True,
        )

        self.assertNotContains(response, "errornote")
        self.assertEqual(self._held(self.delegate), {"S2"})
