import os
from datetime import timedelta

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.utils import timezone

from registration.models import AccountSetUp

SETUP_LINK_DAYS = 7


def issue_setup_token(user):
    """
    Replace any setup tokens for this user with one fresh 7-day token, so a
    re-sent email never carries an expired (already deleted) link.
    """
    AccountSetUp.objects.filter(username=user.username).delete()
    return AccountSetUp.objects.create(
        username=user.username,
        token=PasswordResetTokenGenerator().make_token(user),
        expiration=timezone.now() + timedelta(days=SETUP_LINK_DAYS),
    )


def setup_email_text(facilitator, setup):
    login_url = f"{os.getenv('ACCOUNT_SET_UP_URL')}/{setup.token}"
    expiration = timezone.localtime(setup.expiration).strftime("%A, %B %d at %I:%M%p")
    subject = f"FACT 2026 Facilitator Account - {facilitator.department_name}"
    body = (
        f"Dear {facilitator.department_name},\n\n"
        "As a part of the FACT registration system, each facilitator can access a dashboard showing up to date information on your workshop location and number of delegates registered for your workshop(s). These accounts are meant to supplement your experience as a facilitator and will be deactivated once FACT 2026 has concluded.\n\n"
        "You will also be able to register for workshops through this account. In your facilitator dashboard, there is an area to register each individual facilitator (one for each individual facilitator name that you provided on the confirmation form) for workshops. Registration is not required for facilitators, but if you have time, we highly recommend checking out the other workshops! We ask that you use the facilitator portal, not the standard/delegate registration page to register for workshops in order to help keep our registration numbers as accurate as possible.\n\n"
        f"To access your account visit: {login_url}\n\n"
        f"Your username is: {setup.username}\n\nWe do not support username changes at this time. Upon visiting the provided link, you will be prompted to provide an email and password to finish setting up your account. The provided link will expire on {expiration}.\n\n"
        "We recommend that only one member of your organization/department handles and has access to this account to reduce the risk of compromising passwords.\n\n"
        "After you have set up your account, you can visit https://fact.psauiuc.org/my-fact/login to login (make sure to select “Facilitator” before attempting to login!) to view your workshop information.\n\n"
        "If you encounter any issues with accessing your account, please contact FACT IT at fact.it@psauiuc.org."
    )
    return subject, body


def send_setup_email(facilitator, to_emails):
    """Issue a fresh setup link and email it. Raises if sending fails."""
    setup = issue_setup_token(facilitator.user)
    subject, body = setup_email_text(facilitator, setup)
    send_mail(subject, body, os.getenv("EMAIL_HOST_USER"), to_emails)
