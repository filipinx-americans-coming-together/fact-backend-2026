from django.apps import AppConfig


class ShibbolethAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shibboleth_auth"
    verbose_name = "Shibboleth SAML Authentication"
