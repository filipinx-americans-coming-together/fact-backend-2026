from django.urls import path

from .login import views as login_views
from .notification import views as notification_views
from .agenda import views as agenda_views
from .actions import views as action_views

app_name = "fact_admin"
urlpatterns = [
    path("login/", login_views.login_admin, name="login_admin"),
    path("me/", login_views.me, name="admin_user"),
    path(
        "notifications/<int:id>/",
        notification_views.notification_id,
        name="notifications_id",
    ),
    path("notifications/", notification_views.notifications, name="notifications"),
    path(
        "agenda-items/<int:id>/", agenda_views.agenda_items_id, name="agenda_items_id"
    ),
    path("agenda-items/", agenda_views.agenda_items, name="agenda_items"),
    path(
        "agenda-items/bulk/", agenda_views.agenda_items_bulk, name="agenda_items_bulk"
    ),
    path("flags/", action_views.registration_flags, name="flags"),
    path(
        "flags/<str:label>/",
        action_views.registration_flag_id,
        name="flags_label",
    ),
    path("sheets/delegates/", action_views.delegate_sheet, name="delegate_sheet"),
    path("sheets/locations/", action_views.location_sheet, name="location_sheet"),
    path("accounts/send-facilitator-links/", action_views.send_facilitator_links, name="send_facilitator_links"),
    path("accounts/promote/", action_views.promote_admin, name="promote_admin"),
    path("accounts/promote/confirm/", action_views.promote_admin_confirm, name="promote_admin_confirm"),
    path("accounts/reset-password/", action_views.reset_admin_password, name="reset_admin_password"),
    path("accounts/reset-password/confirm/", action_views.reset_admin_password_confirm, name="reset_admin_password_confirm"),
    path("delegates/day-of/", action_views.day_of_registration, name="day_of_registration"),
    path("summary/", action_views.summary, name="summary"),
]
