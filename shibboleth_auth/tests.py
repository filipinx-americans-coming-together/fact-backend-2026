"""
Tests for the shibboleth_auth app.

These tests run in mock mode by default (SAML_MOCK_MODE=True is the
default when DEVELOPMENT_MODE=True, which Django's test runner uses
via the local .env file).
"""

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from registration.models import Delegate


@override_settings(
    SAML_MOCK_MODE=True,
    SAML_MOCK_EPPN="testuser@illinois.edu",
    SAML_MOCK_EMAIL="testuser@illinois.edu",
    SAML_MOCK_FIRST_NAME="Test",
    SAML_MOCK_LAST_NAME="Illini",
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

    def test_login_creates_user(self):
        """Mock login should create a Django User."""
        self.client.get("/saml/login/")
        self.assertTrue(
            User.objects.filter(email="testuser@illinois.edu").exists()
        )

    def test_login_creates_delegate(self):
        """Mock login should create a Delegate with UIUC verification."""
        self.client.get("/saml/login/")
        user = User.objects.get(email="testuser@illinois.edu")
        delegate = Delegate.objects.get(user=user)
        self.assertTrue(delegate.is_uiuc_verified)
        self.assertEqual(delegate.uiuc_netid, "testuser")
        self.assertEqual(delegate.uiuc_eppn, "testuser@illinois.edu")
        self.assertIsNotNone(delegate.shibboleth_verified_at)

    def test_login_sets_user_name(self):
        """Mock login should set first and last name from SAML attributes."""
        self.client.get("/saml/login/")
        user = User.objects.get(email="testuser@illinois.edu")
        self.assertEqual(user.first_name, "Test")
        self.assertEqual(user.last_name, "Illini")

    def test_login_reuses_existing_user(self):
        """If a user with that email already exists, link to them."""
        existing = User.objects.create_user(
            username="testuser@illinois.edu",
            email="testuser@illinois.edu",
            password="oldpassword123!",
            first_name="Existing",
            last_name="User",
        )
        Delegate.objects.create(user=existing, pronouns="they/them")

        self.client.get("/saml/login/")

        # Should still be only one user
        self.assertEqual(
            User.objects.filter(email="testuser@illinois.edu").count(), 1
        )
        # Delegate should now be verified
        delegate = Delegate.objects.get(user=existing)
        self.assertTrue(delegate.is_uiuc_verified)
        self.assertEqual(delegate.uiuc_netid, "testuser")

    def test_login_creates_session(self):
        """After mock login, the user should be authenticated."""
        self.client.get("/saml/login/")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertTrue(data["is_uiuc_verified"])


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
            username="verified@illinois.edu",
            email="verified@illinois.edu",
            password="testpass123!",
            first_name="Verified",
            last_name="Student",
        )
        from django.utils import timezone
        Delegate.objects.create(
            user=user,
            is_uiuc_verified=True,
            uiuc_netid="verified",
            uiuc_eppn="verified@illinois.edu",
            shibboleth_verified_at=timezone.now(),
        )
        self.client.login(username="verified@illinois.edu", password="testpass123!")
        response = self.client.get("/saml/status/")
        data = response.json()
        self.assertTrue(data["is_authenticated"])
        self.assertTrue(data["is_uiuc_verified"])
        self.assertEqual(data["netid"], "verified")
        self.assertEqual(data["eppn"], "verified@illinois.edu")

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
