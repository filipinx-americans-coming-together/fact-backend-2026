from django.urls import path

from .delegate import views as delegate_views
from .facilitator import views as facilitator_views
from .location import views as location_views
from .payment import views as payment_views
from .school import views as school_views
from .workshop import views as workshop_views

app_name = "registration"
urlpatterns = [
    path("workshops/", workshop_views.workshops, name="workshop"),
    path("workshops/<int:id>/", workshop_views.workshop_id, name="workshop_id"),
    path("workshops/all/", workshop_views.workshops_all, name="workshops_all"),
    path("workshops/bulk/", workshop_views.workshops_bulk, name="workshops_bulk"),
    path("locations/bulk/", location_views.locations_bulk, name="locations_bulk"),
    path("locations/", location_views.locations, name="location"),
    path("locations/<int:id>/", location_views.location_id, name="location_id"),
    path("facilitators/", facilitator_views.facilitators, name="facilitators"),
    path("facilitators/me/", facilitator_views.me, name="facilitators_me"),
    path(
        "facilitators/login/",
        facilitator_views.login_facilitator,
        name="facilitators_login",
    ),
    path(
        "facilitators/set-up/",
        facilitator_views.facilitator_account_set_up,
        name="facilitators_set_up",
    ),
    path(
        "facilitators/register/",
        facilitator_views.register_facilitator,
        name="register_facilitator",
    ),
    path("delegates/me/", delegate_views.delegate_me, name="delegates_me"),
    path("delegates/", delegate_views.delegates, name="delegates"),
    path("delegates/create-account", delegate_views.create_delegate, name="delegates_create"),
    path("delegates/login/", delegate_views.login_delegate, name="delegates_login"),
    path("delegate-status/", payment_views.delegate_status, name="delegate_status"),
    path("uiuc-promo-code/", payment_views.uiuc_promo_code, name="uiuc_promo_code"),
    path("verify-payment/", payment_views.verify_payment, name="verify_payment"),
    path("schools/", school_views.schools, name="schools"),
    path("schools/bulk/", school_views.schools_bulk, name="schools_bulk"),
    path("schools/new/", school_views.new_schools, name="schools_new"),
    path("users/logout/", delegate_views.logout_user, name="logout"),
    path(
        "users/request-reset-password/",
        delegate_views.request_password_reset,
        name="request_password_reset",
    ),
    path("users/reset-password/", delegate_views.reset_password, name="reset_password"),
]
