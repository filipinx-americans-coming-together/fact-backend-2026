"""
SAML configuration builder for python3-saml.

Generates the settings dict that python3-saml expects, using values from
Django settings. Handles both production (real UIUC IDP) and mock mode.
"""

import os
from django.conf import settings


def get_saml_settings():
    """
    Build and return the python3-saml settings dictionary.

    Uses Django settings for SP entity ID, ACS URL, certificate paths,
    and IDP metadata. In mock mode, these values are still generated
    but the actual SAML flow is bypassed in the views.
    """
    base_url = getattr(settings, "SAML_SP_BASE_URL", "http://localhost:8000")

    sp_cert = ""
    sp_key = ""

    cert_file = getattr(settings, "SAML_SP_CERT_FILE", None)
    key_file = getattr(settings, "SAML_SP_KEY_FILE", None)

    if cert_file and os.path.exists(cert_file):
        with open(cert_file, "r") as f:
            sp_cert = f.read()

    if key_file and os.path.exists(key_file):
        with open(key_file, "r") as f:
            sp_key = f.read()

    saml_settings = {
        "strict": True,
        "debug": getattr(settings, "DEBUG", False),
        "sp": {
            "entityId": getattr(
                settings,
                "SAML_SP_ENTITY_ID",
                f"{base_url}/shibboleth",
            ),
            "assertionConsumerService": {
                "url": f"{base_url}/saml/acs/",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "singleLogoutService": {
                "url": f"{base_url}/saml/sls/",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
            "x509cert": sp_cert,
            "privateKey": sp_key,
        },
        "idp": {
            "entityId": getattr(
                settings,
                "SAML_IDP_ENTITY_ID",
                "urn:mace:incommon:uiuc.edu",
            ),
            "singleSignOnService": {
                "url": getattr(
                    settings,
                    "SAML_IDP_SSO_URL",
                    "https://shibboleth.illinois.edu/idp/profile/SAML2/Redirect/SSO",
                ),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "singleLogoutService": {
                "url": getattr(
                    settings,
                    "SAML_IDP_SLO_URL",
                    "https://shibboleth.illinois.edu/idp/profile/SAML2/Redirect/SLO",
                ),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": getattr(settings, "SAML_IDP_CERT", ""),
        },
        "security": {
            "nameIdEncrypted": False,
            "authnRequestsSigned": True,
            "logoutRequestSigned": True,
            "logoutResponseSigned": True,
            "signMetadata": True,
            "wantMessagesSigned": True,
            "wantAssertionsSigned": True,
            "wantNameIdEncrypted": False,
            "requestedAuthnContext": False,
            "wantAttributeStatement": True,
        },
    }

    return saml_settings
