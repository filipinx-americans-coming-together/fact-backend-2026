"""
SAML configuration builder for python3-saml.

Generates the settings dict that python3-saml expects, using values from
Django settings. Handles both production (real UIUC IDP) and mock mode.
"""

import os
from django.conf import settings


def _sp_credential(content, file_path):
    """
    Resolve one SP credential (cert or key): prefer PEM content supplied
    directly via settings (e.g. SAML_SP_CERT/SAML_SP_KEY env vars -- the
    only option on a PaaS deploy with no writable, committed cert files),
    falling back to reading it from disk when a file path is given and
    exists (local dev, where saml/generate_certs.sh already wrote one).
    """
    if content:
        return content

    if file_path and os.path.exists(file_path):
        with open(file_path, "r") as f:
            return f.read()

    return ""


def get_saml_settings():
    """
    Build and return the python3-saml settings dictionary.

    Uses Django settings for SP entity ID, ACS URL, certificate paths,
    and IDP metadata. In mock mode, these values are still generated
    but the actual SAML flow is bypassed in the views.
    """
    base_url = getattr(settings, "SAML_SP_BASE_URL", "http://localhost:8000")

    sp_cert = _sp_credential(
        getattr(settings, "SAML_SP_CERT", ""),
        getattr(settings, "SAML_SP_CERT_FILE", None),
    )
    sp_key = _sp_credential(
        getattr(settings, "SAML_SP_KEY", ""),
        getattr(settings, "SAML_SP_KEY_FILE", None),
    )

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
