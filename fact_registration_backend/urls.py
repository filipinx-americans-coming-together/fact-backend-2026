"""
URL configuration for fact_registration_backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.middleware.csrf import get_token


def get_csrf(request):
    response = JsonResponse({"message": "CSRF cookie set"})
    response["X-CSRFToken"] = get_token(request)
    return response

app_name = "registration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("registration/", include("registration.urls")),
    path("fact-admin/", include("fact_admin.urls")),
    path("verifications/", include("one_time_verification.urls")),
    path("saml/", include("shibboleth_auth.urls")),
    path("csrf/", get_csrf),
]


