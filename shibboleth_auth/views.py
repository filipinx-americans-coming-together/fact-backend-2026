"""
Shibboleth SAML SSO views for UIUC authentication.

Provides four endpoints:
  - /saml/login/    — Initiates SAML login (redirects to UIUC IDP)
  - /saml/acs/      — Assertion Consumer Service (receives SAML response)
  - /saml/metadata/ — Serves SP metadata XML for iTrust registration
  - /saml/status/   — Returns current user's UIUC verification status

Supports a mock mode (SAML_MOCK_MODE=True) for local development
that simulates a successful Shibboleth login without the real IDP.

UIUC releases exactly two attributes to this SP, both privacy-preserving —
no name, email, or NetID is ever available here:
  - eduPersonTargetedID: an opaque, persistent, SP-scoped identifier.
    Stable across logins for the same person, not derivable to a real
    identity. This is what makes a delegate's UIUC verification (and
    their one free-ticket promo code) a one-time thing.
  - eduPersonAffiliation: e.g. "student;member". Used only to decide
    whether to grant the free-ticket eligibility.
Because there's no real name/email, Shibboleth login only proves "this
is a currently-affiliated UIUC student" and creates a session — the
delegate still fills in their own name/email afterward via the normal
PUT /registration/delegate/me/ flow.
"""

import hashlib
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


def _is_student_affiliation(affiliation):
    """
    eduPersonAffiliation is multi-valued in SAML (semicolon-joined once
    flattened to a single string by python3-saml, or a list from
    auth.get_attributes()). True if any value is "student".
    """
    if not affiliation:
        return False
    if isinstance(affiliation, (list, tuple)):
        values = affiliation
    else:
        values = affiliation.replace(",", ";").split(";")
    return "student" in (v.strip().lower() for v in values)


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

def _get_or_create_shibboleth_user(request, targeted_id, affiliation):
    """
    Attach the opaque eduPersonTargetedID/eduPersonAffiliation to a
    delegate account.

    UIUC sign-in is now a verification step reached from partway through
    the register flow (pick workshops, then optionally verify UIUC status
    for a discount code) — not a way to log in or create an account, so
    the expected caller already has an authenticated session with a
    Delegate. In that case the targeted_id is attached directly to that
    delegate; it is never used to switch the session to a different
    account.

    Falls back to the old find-or-create-placeholder behavior only when
    there's no already-authenticated delegate (e.g. someone hits
    /saml/login/ directly with no FACT account yet) — this keeps a cold
    NetID click from erroring out, though the normal path is create an
    account first, then verify.

    is_uiuc_verified is only set True when the affiliation actually
    includes "student"; a successful Shibboleth login alone is not enough.

    Returns (user, error): error is None on success, or a short machine
    code string ("already_linked") when this targeted_id already belongs
    to a different delegate — the caller redirects with that as a query
    param rather than switching accounts out from under the delegate.
    """
    is_student = _is_student_affiliation(affiliation)

    current_delegate = None
    if request.user.is_authenticated:
        try:
            current_delegate = request.user.delegate
        except Delegate.DoesNotExist:
            current_delegate = None

    if current_delegate is not None:
        already_used_elsewhere = (
            Delegate.objects.filter(uiuc_targeted_id=targeted_id)
            .exclude(pk=current_delegate.pk)
            .exists()
        )
        if already_used_elsewhere:
            return request.user, "already_linked"

        current_delegate.is_uiuc_verified = is_student
        current_delegate.uiuc_targeted_id = targeted_id
        current_delegate.uiuc_affiliation = affiliation
        current_delegate.shibboleth_verified_at = timezone.now()
        current_delegate.save()
        return request.user, None

    try:
        delegate = Delegate.objects.get(uiuc_targeted_id=targeted_id)
        user = delegate.user
        delegate.is_uiuc_verified = is_student
        delegate.uiuc_affiliation = affiliation
        delegate.shibboleth_verified_at = timezone.now()
        delegate.save()
        return user, None
    except Delegate.DoesNotExist:
        pass

    # Placeholder username — no real identity attribute to key off of.
    # Uniqueness/collision-resistance comes from hashing the (already
    # unique) targeted_id, not from any UIUC-provided username.
    username = "shib_" + hashlib.sha256(targeted_id.encode()).hexdigest()[:24]
    user = User(username=username)
    user.set_unusable_password()
    user.save()

    Delegate.objects.create(
        user=user,
        is_uiuc_verified=is_student,
        uiuc_targeted_id=targeted_id,
        uiuc_affiliation=affiliation,
        shibboleth_verified_at=timezone.now(),
    )

    return user, None


# ===========================================================================
# MOCK MODE views (for local development without a real IDP)
# ===========================================================================

def _mock_login(request):
    """
    Mock SAML login: immediately creates/finds a test UIUC user and
    redirects to the frontend success URL. No real IDP interaction.
    """
    mock_targeted_id = getattr(
        settings,
        "SAML_MOCK_TARGETED_ID",
        "https://shibboleth.illinois.edu/idp!https://fact.psauiuc.org/shibboleth!mocktargetedid0000000000",
    )
    mock_affiliation = getattr(settings, "SAML_MOCK_AFFILIATION", "student;member")

    user, error = _get_or_create_shibboleth_user(request, mock_targeted_id, mock_affiliation)

    redirect_url = getattr(
        settings,
        "SAML_FRONTEND_REDIRECT_URL",
        "http://localhost:3000/my-fact/register",
    )

    from django.shortcuts import redirect

    if error:
        logger.info("MOCK Shibboleth login rejected (%s) for targeted_id: %s", error, mock_targeted_id)
        return redirect(f"{redirect_url}?uiuc_error={error}")

    login(request, user)
    logger.info("MOCK Shibboleth login for targeted_id: %s", mock_targeted_id)
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
        "http://localhost:3000/my-fact/register",
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

    # Extract attributes from the SAML assertion. UIUC releases exactly two
    # attributes to this SP — eduPersonTargetedID and eduPersonAffiliation —
    # see the module docstring. name_id is the fallback for targeted_id in
    # case UIUC delivers it as a persistent NameID instead of/as well as an
    # attribute (both are seen in the wild for eduPersonTargetedID); this
    # hasn't been verified against the real UIUC IDP yet.
    attributes = auth.get_attributes()
    name_id = auth.get_nameid()

    targeted_id = (
        attributes.get("urn:oid:1.3.6.1.4.1.5923.1.1.1.10", [None])[0]  # eduPersonTargetedID
        or attributes.get("eduPersonTargetedID", [None])[0]
        or name_id
        or ""
    )
    affiliation = (
        attributes.get("urn:oid:1.3.6.1.4.1.5923.1.1.1.1", [])  # eduPersonAffiliation
        or attributes.get("eduPersonAffiliation", [])
    )

    if not targeted_id:
        logger.error("SAML ACS: no eduPersonTargetedID (or NameID) in assertion")
        return JsonResponse(
            {"error": "SAML assertion missing eduPersonTargetedID"},
            status=400,
        )

    logger.info("SAML ACS: authenticated targeted_id=%s affiliation=%s", targeted_id, affiliation)

    user, error = _get_or_create_shibboleth_user(request, targeted_id, affiliation)

    redirect_url = getattr(
        settings,
        "SAML_FRONTEND_REDIRECT_URL",
        "http://localhost:3000/my-fact/register",
    )

    from django.shortcuts import redirect

    if error:
        logger.info("SAML ACS: verification rejected (%s) for targeted_id=%s", error, targeted_id)
        return redirect(f"{redirect_url}?uiuc_error={error}")

    login(request, user)
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
                "targeted_id": delegate.uiuc_targeted_id or None,
                "affiliation": delegate.uiuc_affiliation or None,
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
