"""
Shibboleth SAML SSO views for UIUC authentication.

Provides four endpoints:
  - /saml/login/    — Initiates SAML login (redirects to UIUC IDP)
  - /saml/acs/      — Assertion Consumer Service (receives SAML response)
  - /saml/metadata/ — Serves SP metadata XML for iTrust registration
  - /saml/status/   — Returns current user's UIUC verification status

Supports a mock mode (SAML_MOCK_MODE=True) for local development
that simulates a successful Shibboleth login without the real IDP.
"""

import json
import logging

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from registration.models import Delegate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: prepare the python3-saml request dict from Django's HttpRequest
# ---------------------------------------------------------------------------

def _prepare_saml_request(request):
    """
    Translate a Django HttpRequest into the dict format that python3-saml
    expects for its Auth object.
    """
    return {
        "https": "on" if request.is_secure() else "off",
        "http_host": request.META.get("HTTP_HOST", "localhost:8000"),
        "script_name": request.META.get("PATH_INFO", "/"),
        "get_data": request.GET.copy(),
        "post_data": request.POST.copy(),
        "server_port": request.META.get("SERVER_PORT", "443"),
    }


# ---------------------------------------------------------------------------
# Helper: find or create a User + Delegate from SAML attributes
# ---------------------------------------------------------------------------

def _get_or_create_shibboleth_user(eppn, email, first_name, last_name):
    """
    Given SAML attributes, find an existing user by email or create a new one.
    Sets Shibboleth verification fields on the Delegate.

    Returns the User instance.
    """
    # Extract netid from eppn (e.g. "jsmith2@illinois.edu" → "jsmith2")
    netid = eppn.split("@")[0] if "@" in eppn else eppn

    # Try to find an existing user by email first
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        # Create a new user — use email as username (matches existing pattern)
        user = User(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        # Shibboleth users don't need a Django password — set unusable
        user.set_unusable_password()
        user.save()

    # Ensure a Delegate profile exists
    delegate, created = Delegate.objects.get_or_create(
        user=user,
        defaults={
            "is_uiuc_verified": True,
            "uiuc_netid": netid,
            "uiuc_eppn": eppn,
            "shibboleth_verified_at": timezone.now(),
        },
    )

    if not created:
        # Update existing delegate with Shibboleth info
        delegate.is_uiuc_verified = True
        delegate.uiuc_netid = netid
        delegate.uiuc_eppn = eppn
        delegate.shibboleth_verified_at = timezone.now()
        delegate.save()

    # Update user name if it was blank
    if not user.first_name and first_name:
        user.first_name = first_name
    if not user.last_name and last_name:
        user.last_name = last_name
    user.save()

    return user


# ===========================================================================
# MOCK MODE views (for local development without a real IDP)
# ===========================================================================

def _mock_login(request):
    """
    Mock SAML login: immediately creates/finds a test UIUC user and
    redirects to the frontend success URL. No real IDP interaction.
    """
    mock_eppn = getattr(settings, "SAML_MOCK_EPPN", "testuser@illinois.edu")
    mock_email = getattr(settings, "SAML_MOCK_EMAIL", "testuser@illinois.edu")
    mock_first = getattr(settings, "SAML_MOCK_FIRST_NAME", "Test")
    mock_last = getattr(settings, "SAML_MOCK_LAST_NAME", "Illini")

    user = _get_or_create_shibboleth_user(mock_eppn, mock_email, mock_first, mock_last)
    login(request, user)

    redirect_url = getattr(
        settings,
        "SAML_FRONTEND_REDIRECT_URL",
        "http://localhost:3000/registration-step-2",
    )

    logger.info("MOCK Shibboleth login for user: %s", mock_eppn)

    from django.shortcuts import redirect
    return redirect(redirect_url)


def _mock_acs(request):
    """
    Mock ACS endpoint — in mock mode, login is handled directly by
    _mock_login, so ACS just redirects to the frontend.
    """
    from django.shortcuts import redirect
    redirect_url = getattr(
        settings,
        "SAML_FRONTEND_REDIRECT_URL",
        "http://localhost:3000/registration-step-2",
    )
    return redirect(redirect_url)


# ===========================================================================
# PRODUCTION views (real SAML flow with python3-saml)
# ===========================================================================

@require_GET
def saml_login(request):
    """
    GET /saml/login/

    In mock mode: immediately logs in a test user and redirects.
    In production: generates a SAML AuthnRequest and redirects the
    browser to the UIUC IDP login page.
    """
    if getattr(settings, "SAML_MOCK_MODE", False):
        return _mock_login(request)

    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from shibboleth_auth.saml_config import get_saml_settings
    except ImportError:
        return JsonResponse(
            {"error": "python3-saml is not installed. Cannot perform SAML login."},
            status=500,
        )

    req = _prepare_saml_request(request)
    saml_settings = get_saml_settings()
    auth = OneLogin_Saml2_Auth(req, saml_settings)

    # redirect_url is where UIUC sends the user after login
    sso_url = auth.login()

    logger.info("Redirecting to UIUC IDP for SAML login")

    from django.shortcuts import redirect
    return redirect(sso_url)


@csrf_exempt  # SAML responses are POST-ed by the IDP, no CSRF token available
@require_POST
def saml_acs(request):
    """
    POST /saml/acs/

    Assertion Consumer Service — receives the signed SAML response from
    the UIUC IDP, validates it, extracts user attributes, and logs the
    user into Django.

    The @csrf_exempt is required because the IDP POST does not include
    a Django CSRF token.
    """
    if getattr(settings, "SAML_MOCK_MODE", False):
        return _mock_acs(request)

    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from shibboleth_auth.saml_config import get_saml_settings
    except ImportError:
        return JsonResponse(
            {"error": "python3-saml is not installed."},
            status=500,
        )

    req = _prepare_saml_request(request)
    saml_settings = get_saml_settings()
    auth = OneLogin_Saml2_Auth(req, saml_settings)
    auth.process_response()

    errors = auth.get_errors()
    if errors:
        error_reason = auth.get_last_error_reason()
        logger.error("SAML ACS errors: %s — Reason: %s", errors, error_reason)
        return JsonResponse(
            {
                "error": "SAML authentication failed",
                "details": errors,
                "reason": error_reason,
            },
            status=400,
        )

    if not auth.is_authenticated():
        logger.warning("SAML ACS: user not authenticated after processing response")
        return JsonResponse(
            {"error": "SAML authentication was not successful"},
            status=401,
        )

    # Extract attributes from the SAML assertion
    attributes = auth.get_attributes()
    name_id = auth.get_nameid()

    # UIUC Shibboleth attribute names
    eppn = (
        attributes.get("urn:oid:1.3.6.1.4.1.5923.1.1.1.6", [None])[0]  # eduPersonPrincipalName
        or attributes.get("eppn", [None])[0]
        or name_id
        or ""
    )
    email = (
        attributes.get("urn:oid:0.9.2342.19200300.100.1.3", [None])[0]  # mail
        or attributes.get("mail", [None])[0]
        or eppn  # fall back to eppn as email
    )
    first_name = (
        attributes.get("urn:oid:2.5.4.42", [None])[0]  # givenName
        or attributes.get("givenName", [None])[0]
        or ""
    )
    last_name = (
        attributes.get("urn:oid:2.5.4.4", [None])[0]  # sn (surname)
        or attributes.get("sn", [None])[0]
        or ""
    )

    logger.info("SAML ACS: authenticated user eppn=%s email=%s", eppn, email)

    user = _get_or_create_shibboleth_user(eppn, email, first_name, last_name)
    login(request, user)

    redirect_url = getattr(
        settings,
        "SAML_FRONTEND_REDIRECT_URL",
        "http://localhost:3000/registration-step-2",
    )

    from django.shortcuts import redirect
    return redirect(redirect_url)


@require_GET
def saml_metadata(request):
    """
    GET /saml/metadata/

    Serves the Service Provider metadata XML. This is what you submit
    to the UIUC iTrust Federation Registry to register the app as an SP.

    Works in both mock and production mode.
    """
    if getattr(settings, "SAML_MOCK_MODE", False):
        # In mock mode, return a minimal placeholder metadata XML
        base_url = getattr(settings, "SAML_SP_BASE_URL", "http://localhost:8000")
        entity_id = getattr(settings, "SAML_SP_ENTITY_ID", f"{base_url}/shibboleth")
        xml = f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
                     entityID="{entity_id}">
  <md:SPSSODescriptor
      AuthnRequestsSigned="true"
      WantAssertionsSigned="true"
      protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:AssertionConsumerService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        Location="{base_url}/saml/acs/"
        index="1" />
  </md:SPSSODescriptor>
</md:EntityDescriptor>"""
        return HttpResponse(xml, content_type="application/xml")

    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from shibboleth_auth.saml_config import get_saml_settings
    except ImportError:
        return JsonResponse(
            {"error": "python3-saml is not installed."},
            status=500,
        )

    req = _prepare_saml_request(request)
    saml_settings = get_saml_settings()
    auth = OneLogin_Saml2_Auth(req, saml_settings)
    metadata = auth.get_settings().get_sp_metadata()
    errors = auth.get_settings().validate_metadata(metadata)

    if errors:
        return JsonResponse(
            {"error": "Invalid SP metadata", "details": list(errors)},
            status=500,
        )

    return HttpResponse(metadata, content_type="application/xml")


@require_GET
def saml_status(request):
    """
    GET /saml/status/

    Returns the current user's UIUC Shibboleth verification status.
    Used by the frontend to determine if the user has been verified.
    """
    user = request.user

    if not user.is_authenticated:
        return JsonResponse(
            {
                "is_authenticated": False,
                "is_uiuc_verified": False,
            }
        )

    try:
        delegate = user.delegate
        return JsonResponse(
            {
                "is_authenticated": True,
                "is_uiuc_verified": delegate.is_uiuc_verified,
                "netid": delegate.uiuc_netid or None,
                "eppn": delegate.uiuc_eppn or None,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
            }
        )
    except Delegate.DoesNotExist:
        return JsonResponse(
            {
                "is_authenticated": True,
                "is_uiuc_verified": False,
            }
        )
