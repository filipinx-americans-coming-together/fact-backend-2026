"""
Tests for the shibboleth_auth app.

These tests run in mock mode by default (SAML_MOCK_MODE=True is the
default when DEVELOPMENT_MODE=True, which Django's test runner uses
via the local .env file).
"""

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from registration.models import Delegate
from shibboleth_auth.views import _is_student_affiliation


class AffiliationCheckTests(TestCase):
    """Unit tests for _is_student_affiliation, independent of the login flow."""

    def test_semicolon_joined_string_with_student(self):
        self.assertTrue(_is_student_affiliation("student;member"))

    def test_semicolon_joined_string_without_student(self):
        self.assertFalse(_is_student_affiliation("staff;member"))

    def test_list_of_values_with_student(self):
        self.assertTrue(_is_student_affiliation(["member", "student"]))

    def test_list_of_values_without_student(self):
        self.assertFalse(_is_student_affiliation(["staff", "employee"]))

    def test_case_insensitive(self):
        self.assertTrue(_is_student_affiliation("Student"))

    def test_empty_or_none(self):
        self.assertFalse(_is_student_affiliation(""))
        self.assertFalse(_is_student_affiliation(None))
        self.assertFalse(_is_student_affiliation([]))


@override_settings(
    SAML_MOCK_MODE=True,
    SAML_MOCK_TARGETED_ID="mock-targeted-id-abc123",
    SAML_MOCK_AFFILIATION="student;member",
    SAML_FRONTEND_REDIRECT_URL="http://localhost:3000/registration-step-2",
)
class ShibbolethMockLoginTests(TestCase):
    """Test the mock Shibboleth login flow."""

    def setUp(self):
        self.client = Client()

    def test_login_redirects_to_frontend(self):
        """GET /saml/login/ should redirect to the frontend success URL."""
        response = self.client.get("/saml/login/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "http://localhost:3000/registration-step-2",
        )

    def test_login_creates_user_and_delegate(self):
        """Mock login should create a Django User + verified Delegate keyed by targeted_id."""
        self.client.get("/saml/login/")
        delegate = Delegate.objects.get(uiuc_targeted_id="mock-targeted-id-abc123")
        self.assertTrue(delegate.is_uiuc_verified)
        self.assertEqual(delegate.uiuc_affiliation, "student;member")
        self.assertIsNotNone(delegate.shibboleth_verified_at)

    def test_login_does_not_set_real_name_or_email(self):
        """No identity attributes are available from Shibboleth — the User
        record must be a placeholder the delegate fills in themselves later."""
        self.client.get("/saml/login/")
        delegate = Delegate.objects.get(uiuc_targeted_id="mock-targeted-id-abc123")
        self.assertEqual(delegate.user.email, "")
        self.assertEqual(delegate.user.first_name, "")
        self.assertEqual(delegate.user.last_name, "")

    def test_login_reuses_existing_delegate_by_targeted_id(self):
        """A second login with the same targeted_id must reuse the same
        Delegate/User row, not create a new one — this is what makes the
        one-time-use promo code guarantee hold."""
        self.client.get("/saml/login/")
        first_count = User.objects.count()

        self.client.get("/saml/login/")
        second_count = User.objects.count()

        self.assertEqual(first_count, second_count)
        self.assertEqual(
            Delegate.objects.filter(uiuc_targeted_id="mock-targeted-id-abc123").count(), 1
        )

    def test_login_creates_session(self):
        """After mock login, the user should be authenticated."""
        self.client.get("/saml/login/")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertTrue(data["is_uiuc_verified"])


@override_settings(
    SAML_MOCK_MODE=True,
    SAML_MOCK_TARGETED_ID="mock-targeted-id-staff",
    SAML_MOCK_AFFILIATION="staff;member",
)
class ShibbolethNonStudentAffiliationTests(TestCase):
    """A successful Shibboleth login alone must not grant verification —
    the affiliation has to actually include 'student'."""

    def setUp(self):
        self.client = Client()

    def test_non_student_affiliation_is_not_verified(self):
        self.client.get("/saml/login/")
        delegate = Delegate.objects.get(uiuc_targeted_id="mock-targeted-id-staff")
        self.assertFalse(delegate.is_uiuc_verified)

    def test_status_reflects_non_verification(self):
        self.client.get("/saml/login/")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertFalse(data["is_uiuc_verified"])


class ShibbolethStatusTests(TestCase):
    """Test the /saml/status/ endpoint."""

    def setUp(self):
        self.client = Client()

    def test_status_unauthenticated(self):
        """Unauthenticated users should get is_authenticated=False."""
        response = self.client.get("/saml/status/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["is_authenticated"])
        self.assertFalse(data["is_uiuc_verified"])

    def test_status_authenticated_no_delegate(self):
        """Authenticated user without a Delegate should not be verified."""
        user = User.objects.create_user(
            username="plain@example.com",
            email="plain@example.com",
            password="testpass123!",
        )
        self.client.login(username="plain@example.com", password="testpass123!")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertFalse(data["is_uiuc_verified"])

    def test_status_verified_delegate(self):
        """Verified UIUC delegate should return full verification info."""
        user = User.objects.create_user(
            username="verified_delegate",
            password="testpass123!",
        )
        from django.utils import timezone
        Delegate.objects.create(
            user=user,
            is_uiuc_verified=True,
            uiuc_targeted_id="mock-targeted-id-xyz",
            uiuc_affiliation="student;member",
            shibboleth_verified_at=timezone.now(),
        )
        self.client.login(username="verified_delegate", password="testpass123!")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertTrue(data["is_uiuc_verified"])
        self.assertEqual(data["targeted_id"], "mock-targeted-id-xyz")
        self.assertEqual(data["affiliation"], "student;member")

    def test_status_non_verified_delegate(self):
        """Non-UIUC delegate should return is_uiuc_verified=False."""
        user = User.objects.create_user(
            username="normal@other.edu",
            email="normal@other.edu",
            password="testpass123!",
        )
        Delegate.objects.create(user=user)
        self.client.login(username="normal@other.edu", password="testpass123!")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertFalse(data["is_uiuc_verified"])


@override_settings(
    SAML_MOCK_MODE=True,
    SAML_MOCK_TARGETED_ID="mock-targeted-id-attach",
    SAML_MOCK_AFFILIATION="student;member",
    SAML_FRONTEND_REDIRECT_URL="http://localhost:3000/my-fact/register",
)
class ShibbolethAttachToCurrentDelegateTests(TestCase):
    """
    UIUC sign-in is reached from partway through /my-fact/register on an
    already-authenticated delegate now, not a way to log in or create an
    account — verification must attach to that delegate, never spawn or
    switch to a separate placeholder account.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="real_delegate@example.com",
            email="real_delegate@example.com",
            password="testpass123!",
        )
        Delegate.objects.create(user=self.user)
        self.client.login(username="real_delegate@example.com", password="testpass123!")

    def test_verification_attaches_to_current_delegate(self):
        """No new User/Delegate is created — the existing one is verified in place."""
        user_count_before = User.objects.count()

        response = self.client.get("/saml/login/")

        self.assertEqual(User.objects.count(), user_count_before)
        delegate = Delegate.objects.get(user=self.user)
        self.assertTrue(delegate.is_uiuc_verified)
        self.assertEqual(delegate.uiuc_targeted_id, "mock-targeted-id-attach")
        self.assertEqual(response["Location"], "http://localhost:3000/my-fact/register")

    def test_session_stays_the_same_account(self):
        """Verifying must not switch the logged-in session to a different user."""
        self.client.get("/saml/login/")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertEqual(data["email"], "real_delegate@example.com")

    def test_targeted_id_already_claimed_by_another_delegate_is_rejected(self):
        """A targeted_id already linked to a different delegate must not be
        reattached — the current delegate's verification state is untouched
        and the redirect carries an error the frontend can show."""
        other_user = User.objects.create_user(username="other@example.com")
        Delegate.objects.create(
            user=other_user,
            is_uiuc_verified=True,
            uiuc_targeted_id="mock-targeted-id-attach",
        )

        response = self.client.get("/saml/login/")

        self.assertEqual(
            response["Location"],
            "http://localhost:3000/my-fact/register?uiuc_error=already_linked",
        )
        delegate = Delegate.objects.get(user=self.user)
        self.assertFalse(delegate.is_uiuc_verified)
        self.assertIsNone(delegate.uiuc_targeted_id)


@override_settings(SAML_MOCK_MODE=True)
class ShibbolethMetadataTests(TestCase):
    """Test the /saml/metadata/ endpoint."""

    def setUp(self):
        self.client = Client()

    def test_metadata_returns_xml(self):
        """Metadata endpoint should return XML content."""
        response = self.client.get("/saml/metadata/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")

    def test_metadata_contains_entity_id(self):
        """Metadata XML should contain the SP entity ID."""
        response = self.client.get("/saml/metadata/")
        content = response.content.decode("utf-8")
        self.assertIn("entityID=", content)
        self.assertIn("/shibboleth", content)

    def test_metadata_contains_acs_url(self):
        """Metadata XML should contain the ACS endpoint URL."""
        response = self.client.get("/saml/metadata/")
        content = response.content.decode("utf-8")
        self.assertIn("/saml/acs/", content)


class ShibbolethEndpointMethodTests(TestCase):
    """Test that endpoints enforce correct HTTP methods."""

    def setUp(self):
        self.client = Client()

    def test_login_rejects_post(self):
        """Login endpoint should reject POST requests."""
        response = self.client.post("/saml/login/")
        self.assertEqual(response.status_code, 405)

    def test_metadata_rejects_post(self):
        """Metadata endpoint should reject POST requests."""
        response = self.client.post("/saml/metadata/")
        self.assertEqual(response.status_code, 405)

    def test_status_rejects_post(self):
        """Status endpoint should reject POST requests."""
        response = self.client.post("/saml/status/")
        self.assertEqual(response.status_code, 405)


class ShibbolethSPSettingsTests(TestCase):
    """Test the python3-saml settings dict built by get_saml_settings()."""

    def test_sp_has_no_single_logout_service(self):
        """SP metadata must not advertise an SLO endpoint that has no route."""
        from shibboleth_auth.saml_config import get_saml_settings

        settings_dict = get_saml_settings()
        self.assertNotIn("singleLogoutService", settings_dict["sp"])

    def test_sp_still_has_acs(self):
        """Removing SLO must not disturb the ACS entry."""
        from shibboleth_auth.saml_config import get_saml_settings

        settings_dict = get_saml_settings()
        self.assertIn("assertionConsumerService", settings_dict["sp"])
        self.assertEqual(
            settings_dict["sp"]["assertionConsumerService"]["binding"],
            "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        )

    @override_settings(
        SAML_SP_CERT="env-supplied-cert-content",
        SAML_SP_KEY="env-supplied-key-content",
        SAML_SP_CERT_FILE="/nonexistent/cert.pem",
        SAML_SP_KEY_FILE="/nonexistent/key.pem",
    )
    def test_sp_credential_prefers_env_content_over_file(self):
        """
        A PaaS deploy has no writable cert files (gitignored, never in the
        build) -- SAML_SP_CERT/SAML_SP_KEY env content must be used even
        when the *_FILE paths are set to something that doesn't exist.
        """
        from shibboleth_auth.saml_config import get_saml_settings

        settings_dict = get_saml_settings()
        self.assertEqual(settings_dict["sp"]["x509cert"], "env-supplied-cert-content")
        self.assertEqual(settings_dict["sp"]["privateKey"], "env-supplied-key-content")

    @override_settings(SAML_SP_CERT="", SAML_SP_KEY="")
    def test_sp_credential_falls_back_to_file_when_env_content_empty(self):
        """Local dev: no env content set, falls back to the generated .pem files."""
        from shibboleth_auth.saml_config import get_saml_settings

        settings_dict = get_saml_settings()
        self.assertIn("BEGIN CERTIFICATE", settings_dict["sp"]["x509cert"])
        self.assertIn("BEGIN", settings_dict["sp"]["privateKey"])

    @override_settings(
        SAML_SP_CERT="",
        SAML_SP_KEY="",
        SAML_SP_CERT_FILE="/nonexistent/cert.pem",
        SAML_SP_KEY_FILE="/nonexistent/key.pem",
    )
    def test_sp_credential_empty_when_neither_source_available(self):
        """No env content and no real file -- resolves to empty, not a crash."""
        from shibboleth_auth.saml_config import get_saml_settings

        settings_dict = get_saml_settings()
        self.assertEqual(settings_dict["sp"]["x509cert"], "")
        self.assertEqual(settings_dict["sp"]["privateKey"], "")
