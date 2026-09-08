from django.db import models

from registration.models import Location


class Notification(models.Model):
    """
    System notifications with expiration dates.
    Used for displaying time-sensitive messages to admins.
    """
    message = models.CharField(
        max_length=180,
        help_text="The notification message to be displayed (max 180 characters)"
    )
    expiration = models.DateTimeField(
        help_text="The date and time when this notification should expire"
    )


class AgendaItem(models.Model):
    """
    Event schedule items.
    Tracks location, timing, and session info for each event.
    """
    title = models.CharField(
        max_length=200,
        help_text="The title or name of the agenda item"
    )
    building = models.CharField(
        null=True,
        blank=True,
        max_length=100,
        help_text="Optional building where the event will take place"
    )
    room_num = models.CharField(
        null=True,
        blank=True,
        max_length=100,
        help_text="Optional room number where the event will take place"
    )
    start_time = models.DateTimeField(
        help_text="The scheduled start time of the event"
    )
    end_time = models.DateTimeField(
        help_text="The scheduled end time of the event"
    )
    session_num = models.IntegerField(
        null=True,
        blank=True,
        help_text="Optional session number for events with multiple sessions"
    )
    address = models.CharField(
        null=True,
        blank=True,
        max_length=200,
        help_text="Optional address for events"
    )


class RegistrationFlag(models.Model):
    """
    Feature flags for registration system.
    Controls access to registration features and functionality.
    """
    label = models.CharField(
        max_length=200,
        help_text="Unique identifier for the flag"
    )
    value = models.BooleanField(
        help_text="The current state of the flag (True/False)"
    )

    def __str__(self):
        return f"{self.label} - {self.value}"


class AdminPromotion(models.Model):
    """
    Pending FACTAdmin promotion, awaiting the target's email confirmation
    click before the group is actually granted. Same shape as
    registration.models.PasswordReset/AccountSetUp (token + expiration).
    """
    email = models.EmailField()
    token = models.CharField(max_length=150)
    expiration = models.DateTimeField()
    requested_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        help_text="The FACTAdmin who requested this promotion, for audit",
    )

    def __str__(self):
        return f"promote {self.email}"


class AdminPasswordReset(models.Model):
    """
    Pending FACTAdmin password reset, awaiting the target admin's email
    confirmation click before the new password is actually set. Requested
    by a *different* FACTAdmin on the target's behalf — there is no
    self-service admin password reset, since an admin login has no
    "forgot password" context to key a self-service email off of the way
    the delegate/facilitator flows do. Same token+expiration shape as
    AdminPromotion.
    """
    email = models.EmailField()
    token = models.CharField(max_length=150)
    expiration = models.DateTimeField()
    requested_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="requested_password_resets",
        help_text="The FACTAdmin who requested this reset, for audit",
    )

    def __str__(self):
        return f"reset password for {self.email}"
