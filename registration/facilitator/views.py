import json
import re
import secrets
import string
import unicodedata
from django.http import HttpResponse, JsonResponse
from django.core import serializers as django_serializers
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth import login, authenticate
from django.utils import timezone
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth.password_validation import validate_password

from registration import serializers
from registration.models import (
    AccountSetUp,
    Facilitator,
    FacilitatorRegistration,
    FacilitatorWorkshop,
    Workshop,
    Registration
)


def facilitators(request):
    """
    GET: List all facilitators
    POST: Create new facilitator account
    PUT: Update current facilitator profile
    DELETE: Delete current facilitator account
    Required fields for POST:
        - f_name, l_name: First and last name
        - email: Email (used as username)
        - password: Account password
        - workshops: List of workshop IDs
    Required fields for PUT:
        - f_name, l_name, email, password (for auth)
        - workshops: List of workshop IDs
    Returns 403 if not authenticated, 400 for invalid data, 409 for conflicts
    """
    user = request.user
    if request.method == "GET":
        data = django_serializers.serialize("json", Facilitator.objects.all())
        return HttpResponse(data, content_type="application/json")

    elif request.method == "PUT":
        if not user.is_authenticated or not hasattr(user, "facilitator"):
            return JsonResponse({"message": "No facilitator logged in"}, status=403)

        data = json.loads(request.body)

        f_name = data.get("f_name")
        l_name = data.get("l_name")
        email = data.get("email")
        password = data.get("password")
        new_password = data.get("new_password")
        workshops = data.get("workshops", [])

        # update user data
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

        # update facilitator data
        facilitator = user.facilitator

        facilitator.save()

        # update facilitator workshops (different from delegate workshops)
        if workshops:
            FacilitatorWorkshop.objects.filter(facilitator=facilitator).delete()
            for workshop_id in workshops:
                workshop = Workshop.objects.get(pk=workshop_id)
                FacilitatorWorkshop.objects.create(
                    facilitator=facilitator, workshop=workshop
                )

        user.save()

        return HttpResponse(
            serializers.serialize_facilitator(facilitator),
            content_type="application/json",
        )

    elif request.method == "POST":
        data = json.loads(request.body)

        f_name = data.get("f_name")
        l_name = data.get("l_name")
        email = data.get("email")
        password = data.get("password")
        workshops = data.get("workshops", [])

        # validate data
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
        except ValidationError:
            return JsonResponse({"message": "Invalid email"}, status=400)

        if User.objects.filter(email=email).exists():
            return JsonResponse({"message": "Email already in use"}, status=400)

        try:
            validate_password(password)
        except ValidationError:
            return JsonResponse(
                {"message": "Password is not strong enough"}, status=400
            )

        # set user data
        user = User(username=email, email=email, first_name=f_name, last_name=l_name)
        user.set_password(password)
        user.save()

        # set facilitator data
        facilitator = Facilitator(user=user)
        facilitator.save()

        # set facilitator workshops
        for workshop_id in workshops:
            workshop = Workshop.objects.get(pk=workshop_id)
            FacilitatorWorkshop.objects.create(
                facilitator=facilitator, workshop=workshop
            )

        # login
        login(request, user)

        return HttpResponse(
            serializers.serialize_facilitator(facilitator),
            content_type="application/json",
        )

    elif request.method == "DELETE":
        if not user.is_authenticated or not hasattr(user, "facilitator"):
            return JsonResponse({"message": "No facilitator logged in"}, status=403)

        user.delete()

        return JsonResponse({"message": "success"})

    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def me(request):
    """
    GET: Get current facilitator profile
    Returns 403 if not authenticated
    """
    user = request.user

    if request.method == "GET":
        if not user.is_authenticated or not hasattr(user, "facilitator"):
            return JsonResponse({"message": "No facilitator logged in"}, status=403)

        return HttpResponse(
            serializers.serialize_facilitator(user.facilitator),
            content_type="application/json",
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, 405)


def facilitator_account_set_up(request):
    """
    POST: Complete facilitator account setup
    Required fields:
        - email: User email
        - password: Account password
        - token: Setup token
    Returns 400 for invalid data, 409 for invalid token
    """
    if request.method == "POST":
        data = json.loads(request.body)

        email = data.get("email")
        password = data.get("password")
        token = data.get("token")

        if not password or password == "":
            return JsonResponse({"message": "Must provide password"}, status=400)

        if not token or token == "":
            return JsonResponse({"message": "Must provide token"}, status=400)

        if not email or email == "":
            return JsonResponse({"message": "Must provide email"}, status=400)

        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse({"message": "Invalid email"}, status=400)

        try:
            validate_password(password)
        except ValidationError:
            return JsonResponse(
                {"message": "Password is not strong enough"}, status=400
            )

        AccountSetUp.objects.filter(expiration__lt=timezone.now()).delete()

        try:
            setup = AccountSetUp.objects.get(token=token)
            username = setup.username
            setup.delete()

            user = User.objects.get(username=username)
            user.set_password(password)
            user.email = email
            user.save()
        except (AccountSetUp.DoesNotExist, User.DoesNotExist):
            return JsonResponse({"message": "Invalid set up token"}, status=409)

        return JsonResponse({"message": "success"})
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def login_facilitator(request):
    """
    POST: Authenticate facilitator
    Required fields:
        - email: User email
        - password: Account password
    Returns 400 for invalid credentials, 403 for non-facilitator accounts
    """
    user = request.user

    if request.method == "POST":
        data = json.loads(request.body)

        username = data.get("username")
        password = data.get("password")

        if username is None or len(username) == 0:
            return JsonResponse({"message": "Must provide username"}, status=400)

        if password is None or len(password) == 0:
            return JsonResponse({"message": "Must provide password"}, status=400)

        user = authenticate(username=username, password=password)

        if user is None:
            return JsonResponse({"message": "Invalid credentials"}, status=400)

        if not hasattr(user, "facilitator"):
            return JsonResponse(
                {"message": "No associated facilitator account"}, status=403
            )

        login(request, user)

        return HttpResponse(
            serializers.serialize_facilitator(user.facilitator),
            content_type="application/json",
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def create_facilitator_account(department_name):
    """
    Create a new facilitator account for a department.
    Args:
        department_name: Name of the department
    Returns:
        tuple: (username, token) for account setup
    """
    # create username (first 9 letters of provided name + 4 random numbers)
    normalized_string = unicodedata.normalize("NFKD", department_name)
    ascii_string = normalized_string.encode("ascii", "ignore").decode("ascii")
    cleaned_string = re.sub(r"[^a-zA-Z]", "", ascii_string)

    digits = string.digits

    username = cleaned_string[:9].lower()

    for i in range(4):
        username += secrets.choice(digits)

    user = User(username=username, first_name=department_name)
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for i in range(8))
    user.set_password(password)
    user.save()

    token_generator = PasswordResetTokenGenerator()
    token = token_generator.make_token(user)
    expiration = timezone.now() + timezone.timedelta(days=7)

    reset = AccountSetUp(
        username=username,
        token=token,
        expiration=expiration,
    )
    reset.save()

    return (user, token, expiration)


def register_facilitator(request):
    """
    PUT: Register new facilitator account
    Required fields:
        - department_name: Department name
    Returns 400 for invalid data
    """
    if request.method == "PUT":
        data = json.loads(request.body)

        workshops = data.get("workshops")
        facilitator_name = data.get("facilitator_name")

        if not facilitator_name or facilitator_name == "":
            return JsonResponse(
                {"message": "Must provide facilitator name and workshop"}, status=400
            )

        # if facilitator_name not in [
        #     name.strip() for name in facilitator.facilitators.split(",")
        # ]:
        #     return JsonResponse(
        #         {
        #             "message": f"Could not find facilitator with the name '{facilitator_name}'"
        #         },
        #         status=404,
        #     )

        sessions = set()
        for workshop in workshops:
            if workshop:
                workshop_obj = Workshop.objects.filter(pk=workshop).first()

                if not workshop_obj:
                    return JsonResponse(
                        {"message": "Workshop not found"},
                        status=404,
                    )

                if workshop_obj.pk in sessions:
                    return JsonResponse(
                        {
                            "message": "Can not register for more than one workshop in a single session"
                        },
                        status=400,
                    )

                sessions.add(workshop_obj.session)

        # clear workshops
        FacilitatorRegistration.objects.filter(
            facilitator_name=facilitator_name
        ).delete()

        registrations = []

        for workshop in workshops:
            if workshop:
                workshop_obj = Workshop.objects.get(pk=int(workshop))

                # workshop cap
                capacity = (
                    Registration.objects.filter(workshop_id=workshop)
                    .count()
                    + FacilitatorRegistration.objects.filter(
                        workshop_id=workshop
                    )
                    .exclude(facilitator_name=facilitator_name)
                    .count()
                )

                if capacity >= workshop_obj.location.capacity:
                    return JsonResponse(
                        {"message": f"{workshop_obj.title} is full"}, status=409
                    )
                
                registration = FacilitatorRegistration(
                    facilitator_name=facilitator_name, workshop_id=workshop
                )
                registration.save()

                registrations.append(registration)

        data = django_serializers.serialize("json", registrations)
        return HttpResponse(data, content_type="application/json")
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)
