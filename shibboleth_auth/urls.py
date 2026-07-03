from django.urls import path

from . import views

app_name = "shibboleth_auth"

urlpatterns = [
    path("login/", views.saml_login, name="saml_login"),
    path("acs/", views.saml_acs, name="saml_acs"),
    path("metadata/", views.saml_metadata, name="saml_metadata"),
    path("status/", views.saml_status, name="saml_status"),
]
