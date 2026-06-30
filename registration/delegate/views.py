import json
import environ

from django.http import HttpResponse, JsonResponse
from django.core import serializers as django_serializers
from django.contrib.auth.models import User
from django.core.validators import validate_email
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
        print(workshop_ids)

        # update data

        if f_name and len(f_name) > 0:
            user.first_name = f_name

        if l_name and len(l_name) > 0:
            user.last_name = l_name

        if email and len(email) > 0:
            try:
                validate_email(email)
            except:
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
            except:
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

        # workshops
        sessions = []
        for workshop_id in workshop_ids:
            if workshop_id:
                workshop = Workshop.objects.get(pk=int(workshop_id))
                session = Workshop.objects.get(pk=workshop_id).session

                if session in sessions:
                    return JsonResponse(
                        {
                            "message": "Can not register for multiple workshops in a single session"
                        },
                        status=400,
                    )

                sessions.append(session)

                # workshop cap
                registrations = (
                    Registration.objects.filter(workshop_id=workshop_id)
                    .exclude(delegate=user.delegate)
                    .count()
                    + FacilitatorRegistration.objects.filter(
                        workshop_id=workshop_id
                    ).count()
                )

                if registrations >= workshop.location.capacity:
                    return JsonResponse(
                        {"message": f"{workshop.title} is full"}, status=409
                    )

        if len(sessions) == 3:
            # clear registered workshops
            Registration.objects.filter(delegate=user.delegate).delete()

            # re register
            for workshop_id in workshop_ids:
                workshop = Workshop.objects.get(pk=workshop_id)

                registration = Registration(delegate=user.delegate, workshop=workshop)

                registration.save()

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

        sessions = []
        for workshop_id in workshop_ids:
            try:
                workshop = Workshop.objects.get(pk=int(workshop_id))
                session = workshop.session
            except:
                return JsonResponse(
                    {"message": "Requested workshop not found"}, status=404
                )

            # session
            if session in sessions:
                return JsonResponse(
                    {
                        "message": "Can not register for multiple workshops in a single session"
                    },
                    status=400,
                )

            sessions.append(session)

            # workshop cap
            registrations = (
                Registration.objects.filter(workshop_id=workshop_id).count()
                + FacilitatorRegistration.objects.filter(
                    workshop_id=workshop_id
                ).count()
            )

            if registrations >= workshop.location.capacity:
                return JsonResponse(
                    {"message": f"{workshop.title} is full"}, status=409
                )

        # check user exists
        try:
            user = User.objects.get(email=email)
        except:
            return JsonResponse({"message": "User not found"}, status=404)

        delegate = user.delegate

        workshop_details = {}

        # set registration data
        try:
            with transaction.atomic():
                for workshop_id in workshop_ids:
                    workshop = Workshop.objects.get(pk=workshop_id)

                    registration = Registration(delegate=delegate, workshop=workshop)
                    registration.save()

                    # save workshop names for email
                    workshop_details[workshop.session] = workshop.title
        except Exception as e:
            return JsonResponse({"message": "Server error during registration"}, status=500)

        # login
        login(request, user)

        # send email
        subject = f"FACT 2025 Registration Confirmation - {user.first_name} {user.last_name}"

        registration_details = ""
        for session in workshop_details:
            registration_details += f"Session {session}: {workshop_details[session]}\n"

        body = f"Thank you for registering for FACT 2025!\n\nYou have registered for the following workshops\n\n{registration_details}\nTo update your personal information, change workshops, and view up to date conference information, visit fact.psauiuc.org/my-fact/dashboard.\nWant to connect with other delegates? Follow @factcommitments2025 on Instagram to see who's committed to FACT!\nFill out https://forms.gle/rwvAhU2JsuGYnLnd7 to be posted!"
        from_email = env("EMAIL_HOST_USER")
        to_email = [email]

        send_mail(subject, body, from_email, to_email)

        return HttpResponse(
            serializers.serialize_user(user), content_type="application/json"
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)

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

        f_name = data.get("f_name")
        l_name = data.get("l_name")
        email = data.get("email")
        password = data.get("password")
        pronouns = data.get("pronouns")
        year = data.get("year")
        school_id = data.get("school_id")
        other_school_name = data.get("other_school_name")

        if not f_name or len(f_name) < 1:
            return JsonResponse(
                {"message": "First name must be at least one character"}, status=400
            )

        if not l_name or len(l_name) < 1:
            return JsonResponse(
                {"message": "Last name must be at least one character"}, status=400
            )

        try:
            validate_email(email)
        except:
            return JsonResponse({"message": "Invalid email"}, status=400)

        if User.objects.filter(email=email).exists():
            return JsonResponse({"message": "Email already in use"}, status=409)

        try:
            validate_password(password)
        except:
            return JsonResponse({"message": "Password is too weak"}, status=400)

        # set user data
        try:
            with transaction.atomic():
                user = User(username=email, email=email, first_name=f_name, last_name=l_name)
                user.set_password(password)
                user.save()

                # set delegate data
                delegate = Delegate(user=user, pronouns=pronouns, year=year)

                if school_id:
                    if (
                        str(school_id).isdigit()
                        and School.objects.filter(pk=school_id).exists()
                    ):
                        delegate.school_id = school_id
                elif other_school_name and len(other_school_name) > 0:
                    delegate.other_school = other_school_name
                    NewSchool.objects.create(name=other_school_name)

                delegate.save()
        except Exception as e:
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
        except:
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
        except:
            return JsonResponse({"message": "Invalid reset token"}, status=409)

        return JsonResponse({"message": "success"})
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)
