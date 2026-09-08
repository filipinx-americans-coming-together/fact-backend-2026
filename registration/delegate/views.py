import json
import environ

from django.http import HttpResponse, JsonResponse
from django.core import serializers as django_serializers
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from registration import serializers
from registration.models import (
    Delegate,
    FacilitatorRegistration,
    Location,
    NewSchool,
    PasswordReset,
    Registration,
    School,
    Workshop,
)


env = environ.Env()
environ.Env.read_env()


def _lock_and_register_workshops(delegate, requested_ids, replace_existing):
    """
    Capacity-checks and writes `delegate`'s registrations for `requested_ids`
    under row locks (sorted by pk, consistent lock order across concurrent
    callers to avoid deadlocks) so two requests racing for the last seat
    can't both pass the check before either writes — see IT Bugs FACT 2024
    #6 ("why are we over capacity"). Shared by delegate_me, delegates, and
    fact_admin's day-of registration endpoint so there's exactly one place
    this logic can go wrong.

    replace_existing=True excludes the delegate's own current registrations
    from the capacity count (re-picking a session you already hold isn't
    "taking someone else's seat") and replaces them with `requested_ids`
    atomically — used when an existing delegate is changing their picks.
    replace_existing=False just creates registrations for `requested_ids`
    with no exclusion or cleanup — used for a delegate with no existing
    registrations yet (fresh signup, or a day-of account).

    Returns None on success, or a JsonResponse describing the first
    failure (unknown workshop, duplicate session, or a full workshop).
    Caller must not write to Registration for this delegate outside this
    function while relying on its capacity guarantee.
    """
    with transaction.atomic():
        workshops_by_id = {
            w.pk: w
            for w in Workshop.objects.select_for_update().filter(
                pk__in=sorted(requested_ids)
            )
        }

        if len(workshops_by_id) != len(set(requested_ids)):
            return JsonResponse(
                {"message": "Requested workshop not found"}, status=404
            )

        sessions = []
        for workshop_id in requested_ids:
            workshop = workshops_by_id[workshop_id]

            if workshop.session in sessions:
                return JsonResponse(
                    {
                        "message": "Can not register for multiple workshops in a single session"
                    },
                    status=400,
                )
            sessions.append(workshop.session)

            registrations = Registration.objects.filter(workshop_id=workshop_id)
            if replace_existing:
                registrations = registrations.exclude(delegate=delegate)
            registrations_count = (
                registrations.count()
                + FacilitatorRegistration.objects.filter(workshop_id=workshop_id).count()
            )

            if registrations_count >= workshop.location.capacity:
                return JsonResponse(
                    {"message": f"{workshop.title} is full"}, status=409
                )

        if replace_existing:
            Registration.objects.filter(delegate=delegate).delete()

        for workshop_id in requested_ids:
            Registration.objects.create(
                delegate=delegate, workshop=workshops_by_id[workshop_id]
            )

    return None


def delegate_me(request):
    """
    GET: Get current delegate profile
    PUT: Update delegate profile and workshop registrations
    DELETE: Delete delegate account
    Required fields for PUT:
        - f_name, l_name, email, password (for auth)
        - pronouns, year, school_id/other_school_name
        - workshop_1_id, workshop_2_id, workshop_3_id (all required)
    Returns 403 if not authenticated, 400 for invalid data, 409 for conflicts
    """
    user = request.user

    if request.method == "GET":
        if not user.is_authenticated or not hasattr(user, "delegate"):
            return JsonResponse({"message": "No delegate logged in"}, status=403)

        return HttpResponse(
            serializers.serialize_user(user), content_type="application/json"
        )
    elif request.method == "PUT":
        if not user.is_authenticated or not hasattr(user, "delegate"):
            return JsonResponse({"message": "No delegate logged in"}, status=403)

        data = json.loads(request.body)

        f_name = data.get("f_name")
        l_name = data.get("l_name")
        email = data.get("email")
        password = data.get("password")
        new_password = data.get("new_password")
        pronouns = data.get("pronouns")
        year = data.get("year")
        school_id = data.get("school_id")
        other_school_name = data.get("other_school_name")

        workshop_1_id = data.get("workshop_1_id")
        workshop_2_id = data.get("workshop_2_id")
        workshop_3_id = data.get("workshop_3_id")

        workshop_ids = [workshop_1_id, workshop_2_id, workshop_3_id]

        # payment gate: only block if workshop IDs are actually being submitted
        if any(workshop_ids) and (
            user.delegate.payment_status != Delegate.PaymentStatus.PAID
            or user.delegate.ticket_type not in (
                Delegate.TicketType.WORKSHOP,
                Delegate.TicketType.BUNDLE,
            )
        ):
            return JsonResponse(
                {"message": "Payment required before workshop registration"}, status=402
            )

        # update data

        if f_name and len(f_name) > 0:
            user.first_name = f_name

        if l_name and len(l_name) > 0:
            user.last_name = l_name

        if email and len(email) > 0:
            try:
                validate_email(email)
            except ValidationError:
                return JsonResponse({"message": "Invalid email"}, status=400)

            if email != user.email and User.objects.filter(email=email).exists():
                return JsonResponse({"message": "Email already in use"}, status=400)

            user.email = email

        if new_password:
            if not authenticate(username=user.username, password=password):
                return JsonResponse(
                    {"message": "Old password does not match"}, status=409
                )

            try:
                validate_password(new_password)
                user.set_password(new_password)
            except ValidationError:
                return JsonResponse(
                    {"message": "Password is not strong enough"}, status=400
                )

        if pronouns and len(pronouns) > 0:
            user.delegate.pronouns = pronouns

        if year and len(year) > 0:
            user.delegate.year = year

        if school_id:
            # check if school id exists, if not check for other school
            # if there is an "other" school, create a new school object

            if school_id.isdigit() and School.objects.filter(pk=school_id).exists():
                user.delegate.school_id = school_id
            elif other_school_name and len(other_school_name) > 0:
                user.delegate.other_school = other_school_name

                NewSchool.objects.create(name=other_school_name)

        # workshops: only commit a change if all three sessions were
        # submitted (matches this endpoint's documented "all required").
        requested_ids = [int(w) for w in workshop_ids if w]
        if len(requested_ids) == 3:
            error = _lock_and_register_workshops(
                user.delegate, requested_ids, replace_existing=True
            )
            if error:
                return error

        user.save()
        user.delegate.save()

        return HttpResponse(
            serializers.serialize_user(user), content_type="application/json"
        )
    elif request.method == "DELETE":
        if not user.is_authenticated:
            return JsonResponse({"message": "No user logged in"}, status=403)

        data = serializers.serialize_user(user)

        user.delete()
        user.save()

        return HttpResponse(data, content_type="application/json")
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def delegates(request):
    """
    POST: Register an existing delegate for workshops
    Required fields:
        - email: Email (used as username)
        - workshop_1_id, workshop_2_id, workshop_3_id: Workshop selections
    Returns 400 for invalid data, 409 for full workshop, 404 if user is not found
    """
    if request.method == "POST":
        data = json.loads(request.body)

        email = data.get("email")
        workshop_1_id = data.get("workshop_1_id")
        workshop_2_id = data.get("workshop_2_id")
        workshop_3_id = data.get("workshop_3_id")

        workshop_ids = [int(workshop_1_id), int(workshop_2_id), int(workshop_3_id)]

        # validate data
        if None in workshop_ids:
            return JsonResponse(
                {"message": "Must register for all three sessions"}, status=400
            )

        # check user exists
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse({"message": "User not found"}, status=404)

        delegate = user.delegate

        if delegate.payment_status != Delegate.PaymentStatus.PAID or delegate.ticket_type not in (
            Delegate.TicketType.WORKSHOP,
            Delegate.TicketType.BUNDLE,
        ):
            return JsonResponse(
                {"message": "Payment required before workshop registration"}, status=402
            )

        try:
            error = _lock_and_register_workshops(
                delegate, workshop_ids, replace_existing=False
            )
            if error:
                return error
        except Exception:
            return JsonResponse({"message": "Server error during registration"}, status=500)

        workshop_details = {}
        for workshop_id in workshop_ids:
            workshop = Workshop.objects.get(pk=workshop_id)
            workshop_details[workshop.session] = workshop.title

        # login
        login(request, user)

        # send email
        subject = f"FACT 2026 Registration Confirmation - {user.first_name} {user.last_name}"

        registration_details = ""
        for session in workshop_details:
            registration_details += f"Session {session}: {workshop_details[session]}\n"

        body = f"Thank you for registering for FACT 2026!\n\nYou have registered for the following workshops\n\n{registration_details}\nTo update your personal information, change workshops, and view up to date conference information, visit fact.psauiuc.org/my-fact/dashboard.\nWant to connect with other delegates? Follow @factcommitments on Instagram to see who's committed to FACT!\nFill out https://forms.gle/rwvAhU2JsuGYnLnd7 to be posted!"
        from_email = env("EMAIL_HOST_USER")
        to_email = [email]

        send_mail(subject, body, from_email, to_email)

        return HttpResponse(
            serializers.serialize_user(user), content_type="application/json"
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)

def _create_delegate_account(f_name, l_name, email, password, pronouns, year, school_id, other_school_name):
    """
    Validates delegate account fields and creates the User + Delegate.

    Returns (user, None) on success, or (None, JsonResponse) on the first
    validation failure — no DB writes happen before all validation passes.
    Shared by create_delegate (account-first signup) and
    registration.payment.views.claim_order (purchase-first signup), so the
    two entry points can never validate an account differently.

    Caller is responsible for wrapping in transaction.atomic() if this needs
    to succeed/fail together with other writes (e.g. marking payment).
    """
    if not f_name or len(f_name) < 1:
        return None, JsonResponse(
            {"message": "First name must be at least one character"}, status=400
        )

    if not l_name or len(l_name) < 1:
        return None, JsonResponse(
            {"message": "Last name must be at least one character"}, status=400
        )

    try:
        validate_email(email)
    except ValidationError:
        return None, JsonResponse({"message": "Invalid email"}, status=400)

    if User.objects.filter(email=email).exists():
        return None, JsonResponse({"message": "Email already in use"}, status=409)

    try:
        validate_password(password)
    except ValidationError:
        return None, JsonResponse({"message": "Password is too weak"}, status=400)

    user = User(username=email, email=email, first_name=f_name, last_name=l_name)
    user.set_password(password)
    user.save()

    delegate = Delegate(user=user, pronouns=pronouns, year=year)

    if school_id:
        if str(school_id).isdigit() and School.objects.filter(pk=school_id).exists():
            delegate.school_id = school_id
    elif other_school_name and len(other_school_name) > 0:
        delegate.other_school = other_school_name
        NewSchool.objects.create(name=other_school_name)

    delegate.save()

    return user, None


def create_delegate(request):
    """
    POST: Create new delegate account
    Required fields:
        - f_name, l_name: First and last name
        - email: Email (used as username)
        - password: Account password
        - pronouns: Preferred pronouns
        - year: Academic year
        - school_id or other_school_name: School affiliation
    Returns 400 for invalid data, 409 for duplicate email
    """
    if request.method == "POST":
        data = json.loads(request.body)

        try:
            with transaction.atomic():
                user, error = _create_delegate_account(
                    f_name=data.get("f_name"),
                    l_name=data.get("l_name"),
                    email=data.get("email"),
                    password=data.get("password"),
                    pronouns=data.get("pronouns"),
                    year=data.get("year"),
                    school_id=data.get("school_id"),
                    other_school_name=data.get("other_school_name"),
                )
                if error:
                    return error
        except Exception:
            return JsonResponse({"message": "Server error during registration"}, status=500)

        # login
        login(request, user)

        return HttpResponse(
            serializers.serialize_user(user), content_type="application/json"
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)

def login_delegate(request):
    """
    POST: Authenticate delegate
    Required fields:
        - email: User email
        - password: Account password
    Returns 400 for invalid credentials, 403 for non-delegate accounts
    """
    if request.method == "POST":
        data = json.loads(request.body)

        email = data.get("email")
        password = data.get("password")

        if email is None or len(email) == 0:
            return JsonResponse({"message": "Must provide email"}, status=400)

        if password is None or len(password) == 0:
            return JsonResponse({"message": "Must provide password"}, status=400)

        user = authenticate(username=email, password=password)

        if user is None:
            return JsonResponse({"message": "Invalid credentials"}, status=400)

        login(request, user)

        return HttpResponse(
            serializers.serialize_user(user), content_type="application/json"
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def logout_user(request):
    """
    POST: Logout current user
    Returns 200 on success
    """
    if request.method == "POST":
        logout(request)

        return JsonResponse({"message": "Logout successful"})
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def request_password_reset(request):
    """
    POST: Request password reset token
    Required fields:
        - email: User email
    Returns 200 on success, 404 if email not found
    """
    if request.method == "POST":
        data = json.loads(request.body)

        email = data.get("email")

        if not email or email == "":
            return JsonResponse({"message": "Must provide email"}, status=400)

        # return "success" even if no connected user exists
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return JsonResponse(
                {
                    "message": "If email is connected to account, reset password link has been sent"
                }
            )

        token_generator = PasswordResetTokenGenerator()
        token = token_generator.make_token(user)

        reset = PasswordReset(
            email=email,
            token=token,
            expiration=timezone.now() + timezone.timedelta(minutes=15),
        )
        reset.save()

        reset_url = f"{env('RESET_PASSWORD_URL')}/{token}"

        # send email
        subject = "FACT Account Password Reset"
        body = f"Hi {user.first_name}. You are receiving this email because you requested a password reset. Click on the link to create a new password\n\n{reset_url}\n\n If you didn't request a password reset, you can ignore this email. Your password will not be changed. This link will expire in 15 minutes."
        from_email = env("EMAIL_HOST_USER")
        to_email = [email]

        send_mail(subject, body, from_email, to_email)

        return JsonResponse(
            {
                "message": "If email is connected to account, reset password link has been sent"
            }
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def reset_password(request):
    """
    POST: Reset password using token
    Required fields:
        - email: User email
        - token: Reset token
        - password: New password
    Returns 400 for invalid data, 404 for invalid token
    """
    if request.method == "POST":
        data = json.loads(request.body)

        password = data.get("password")
        token = data.get("token")

        if not password or password == "":
            return JsonResponse({"message": "Must provide password"}, status=400)

        if not token or token == "":
            return JsonResponse({"message": "Must provide token"}, status=400)

        PasswordReset.objects.filter(expiration__lt=timezone.now()).delete()

        try:
            reset = PasswordReset.objects.get(token=token)
            email = reset.email
            reset.delete()

            user = User.objects.get(email=email)
            user.set_password(password)
            user.save()
        except (PasswordReset.DoesNotExist, User.DoesNotExist):
            return JsonResponse({"message": "Invalid reset token"}, status=409)

        return JsonResponse({"message": "success"})
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)
