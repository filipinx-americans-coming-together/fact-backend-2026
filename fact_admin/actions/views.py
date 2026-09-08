import json
from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.core import serializers as django_serializers
from django.contrib.auth.models import Group, User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
import os

import pandas as pd

from fact_admin.models import AdminPasswordReset, AdminPromotion, RegistrationFlag
from registration import serializers
from registration.delegate.views import _create_delegate_account, _lock_and_register_workshops
from registration.models import Delegate, Location, Registration, School, Workshop, Facilitator, AccountSetUp

# set workshop locations
# get summary (sheet)
# get locations (sheet)
# reset database
# send email updates?


def registration_flags(request):
    """
    GET: List all registration flags
    """
    if request.method == "GET":
        data = django_serializers.serialize("json", RegistrationFlag.objects.all())
        return HttpResponse(data, content_type="application/json")
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def registration_flag_id(request, label):
    """
    GET: Get flag by label
    PUT: Update flag value (admin only)
    """
    if request.method == "GET":
        flag = RegistrationFlag.objects.filter(label=label)

        if not flag.exists():
            return JsonResponse({"message": "Permission not found"}, status=404)

        return HttpResponse(
            django_serializers.serialize("json", flag),
            content_type="application/json",
        )
    if request.method == "PUT":
        # must be admin
        if not request.user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        flag = RegistrationFlag.objects.filter(label=label)

        if not flag.exists():
            return JsonResponse({"message": "Flag not found"}, status=404)

        data = json.loads(request.body)
        value = data.get("value")

        if value == None or (value != True and value != False):
            return JsonResponse(
                {"message": "Must provide true/false value"}, status=400
            )

        flag_obj = flag.first()
        flag_obj.value = value
        flag_obj.save()

        return HttpResponse(django_serializers.serialize("json", flag))
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def summary(request):
    """
    GET: Event stats (admin only)
    Returns: delegate count, school count, recent registrations (past 5 days)
    """
    if not request.user.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "Must be admin to make this request"}, status=403
        )

    if request.method == "GET":
        # delegates = Delegate.objects.all().count()
        delegates = Registration.objects.values("delegate").distinct().count()
        schools = (
            Delegate.objects.values("school")
            .distinct()
            .count()
            # + Delegate.objects.values("other_school").distinct().count()
        )

        registrations = Delegate.objects.filter(
            date_created__gt=timezone.now() - timezone.timedelta(days=5)
        ).values_list("date_created", flat=True)

        return JsonResponse(
            {
                "delegates": delegates,
                "schools": schools,
                "registrations": list(registrations),
            },
            safe=False,
        )
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def delegate_sheet(request):
    """
    GET: Export delegate info to Excel (admin only)
    Includes: personal info, school, workshop selections
    """
    if not request.user.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "Must be admin to make this request"}, status=403
        )

    if request.method == "GET":
        delegates = Delegate.objects.all().select_related("user", "school").prefetch_related("registration_set__workshop")
        
        records = []
        for d in delegates:
            record = {
                "pronouns": d.pronouns,
                "year": d.year,
                "first_name": d.user.first_name if d.user else None,
                "last_name": d.user.last_name if d.user else None,
                "email": d.user.email if d.user else None,
                "school": d.school.name if d.school else (d.other_school if d.other_school else None),
                "session_1": None,
                "session_2": None,
                "session_3": None,
            }
            
            for reg in d.registration_set.all():
                if reg.workshop:
                    session = reg.workshop.session
                    if session in [1, 2, 3]:
                        record[f"session_{session}"] = reg.workshop.title
            
            records.append(record)
            
        df = pd.DataFrame(records)

        # Save the Excel file
        file_path = "delegates.xlsx"
        df.to_excel(file_path, index=False)

        # Return the file as a response
        response = FileResponse(open(file_path, "rb"))
        response["Content-Disposition"] = f'attachment; filename="{file_path}"'
        return response

    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def location_sheet(request):
    """
    GET: Export workshop locations to Excel (admin only)
    Includes: workshop details, location, capacity info
    """
    if not request.user.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "Must be admin to make this request"}, status=403
        )

    if request.method == "GET":
        # Fetch workshops with required fields
        workshops = Workshop.objects.all().values(
            "id", "title", "session", "location_id", "preferred_cap", "moveable_seats"
        )
        df = pd.DataFrame.from_records(workshops)

        # Convert fields to string for Excel compatibility
        df["preferred_cap"] = df["preferred_cap"].astype(str)
        df["moveable_seats"] = df["moveable_seats"].astype(str)

        for idx, row in df.iterrows():
            # Handle location_id and resolve location details
            location_id = row.get("location_id")
            if location_id is not None:
                try:
                    location = Location.objects.get(pk=location_id)
                    df.at[idx, "location"] = f"{location.building} {location.room_num}"
                except Location.DoesNotExist:
                    print(f"Location with ID {location_id} does not exist.")
                    df.at[idx, "location"] = "Unknown Location"
            else:
                print(f"Missing location_id for workshop at index {idx}.")
                df.at[idx, "location"] = "No Location Assigned"

            # Handle preferred_cap
            preferred_cap = row.get("preferred_cap")
            if preferred_cap is not None and not pd.isna(preferred_cap):
                df.at[idx, "preferred_cap"] = str(preferred_cap)
            else:
                df.at[idx, "preferred_cap"] = "No Preference"

            # Handle moveable_seats
            moveable_seats = row.get("moveable_seats")
            if moveable_seats is not None:
                df.at[idx, "moveable_seats"] = "Yes" if moveable_seats else "No"
            else:
                df.at[idx, "moveable_seats"] = "Unknown"

        # Drop unwanted columns
        df.drop(["id", "location_id"], axis=1, inplace=True, errors="ignore")

        # Save the Excel file
        file_path = "locations.xlsx"
        df.to_excel(file_path, index=False)

        # Return the file as a response
        response = FileResponse(open(file_path, "rb"))
        response["Content-Disposition"] = f'attachment; filename="{file_path}"'
        return response
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)

def send_facilitator_links(request):
    """
    POST: Print (instead of send) individual login links to facilitators (admin only)
    Requires uploaded Excel file with:
        - 'Facilitator Name' (matches Facilitator.department_name)
        - 'Facilitator Email'
    Prints each facilitator's personalized email to console for verification.
    """
    if not request.user.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "Must be admin to make this request"}, status=403
        )

    if request.method == "POST":
        if "emails" not in request.FILES:
            return JsonResponse({"message": "Must include Excel file as 'emails'"}, status=400)
        
        file = request.FILES["emails"]

        try:
            df = pd.read_excel(file)
        except Exception as e:
            return JsonResponse({"message": f"Error reading Excel file: {str(e)}"}, status=400)
        
        # validate required columns
        # NOTE: EXCEL SHEET SHOULD BE FORMATTED WITH COLUMNS AS ROW 1 AND ALL SESSION IN SAME SHEET
        df.columns = [col.strip() for col in df.columns]
        expected_columns = {"Facilitator Name", "Facilitator Email"}
        if not expected_columns.issubset(df.columns):
            return JsonResponse(
                {"message": f"Excel file must contain the following columns: {', '.join(expected_columns)}"},
                status=400
            )

        df["Facilitator Email"] = df["Facilitator Email"].str.strip().str.lower()
        df["Facilitator Name"] = df["Facilitator Name"].str.strip()

        facilitators = Facilitator.objects.all()
        if facilitators.count() == 0:
            return JsonResponse(
                {"message": "No facilitators found"}, status=404
            )

        sent_count = 0
        failed = []

        # Collect facilitator info with their account setup tokens
        for facilitator in facilitators:
            name_key = str(facilitator.department_name).strip()
            match = df.loc[df["Facilitator Name"] == name_key]

            if match.empty:
                failed.append(f"No matching email for facilitator: {facilitator.department_name}")
                continue

            account_setup = AccountSetUp.objects.filter(username=facilitator.user.username).first()
            if not account_setup:
                failed.append(f"No account setup found for facilitator: {facilitator.department_name}")
                continue

            facilitator_email = match.iloc[0]["Facilitator Email"]
    
            # Login link using the stored token
            login_url = f"{os.getenv('ACCOUNT_SET_UP_URL')}/{account_setup.token}"

            from_email = os.getenv("EMAIL_HOST_USER")
            to_email = [email.strip() for email in facilitator_email.split(",")]
            
            subject = (f"FACT 2025 Facilitator Account - {facilitator.department_name}")
            body = (
                f"Dear {facilitator.department_name},\n\n"
                "As a part of the FACT registration system, each facilitator can access a dashboard showing up to date information on your workshop location and number of delegates registered for your workshop(s). These accounts are meant to supplement your experience as a facilitator and will be deactivated once FACT 2025 has concluded.\n\n"
                "You will also be able to register for workshops through this account. In your facilitator dashboard, there is an area to register each individual facilitator (one for each individual facilitator name that you provided on the confirmation form) for workshops. Registration is not required for facilitators, but if you have time, we highly recommend checking out the other workshops! We ask that you use the facilitator portal, not the standard/delegate registration page to register for workshops in order to help keep our registration numbers as accurate as possible.\n\n"
                f"To access your account visit: {login_url}\n\n"
                f"Your username is: {account_setup.username}\n\nWe do not support username changes at this time. Upon visiting the provided link, you will be prompted to provide an email and password to finish setting up your account. The provided link will expire on Friday, November 14th at 11:59pm.\n\n"
                "We recommend that only one member of your organization/department handles and has access to this account to reduce the risk of compromising passwords.\n\n"
                "After you have set up your account, you can visit https://fact.psauiuc.org/my-fact/login to login (make sure to select “Facilitator” before attempting to login!) to view your workshop information.\n\n"
                "If you encounter any issues with accessing your account, please contact FACT IT at fact.it@psauiuc.org."
            )

            # Print email details to console instead of sending for testing
            # print("=========================================")
            # print(f"To: {facilitator_email}")
            # print(f"Subject: {subject}")
            # print(f"Body:\n{body}")
            # print("=========================================\n")
            
            try:
                send_mail(subject, body, from_email, to_email)
                sent_count += 1
            except Exception as e:
                failed.append(f"Failed to send email to {facilitator_email}: {str(e)}")

        return JsonResponse(
            {
                "message": f"Successfully sent {sent_count} facilitator emails.",
                "failed": failed,
            },
            status=200
        )
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def promote_admin(request):
    """
    POST: Request that an existing registered user be promoted to FACTAdmin
    (admin only). Sends a confirmation link to the target's email instead of
    granting the group immediately — the promotion only takes effect once
    they click it (see promote_admin_confirm below). Requires the target to
    already have an account; there is no self-service admin signup.
    """
    if not request.user.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "Must be admin to make this request"}, status=403
        )

    if request.method != "POST":
        return JsonResponse({"message": "method not allowed"}, status=405)

    data = json.loads(request.body)
    email = data.get("email")

    if not email or len(email) == 0:
        return JsonResponse({"message": "Must provide email"}, status=400)

    try:
        target = User.objects.get(email=email)
    except User.DoesNotExist:
        return JsonResponse(
            {"message": "No account found with that email — they must create an account first"},
            status=404,
        )

    if target.groups.filter(name="FACTAdmin").exists():
        return JsonResponse({"message": "This user is already an admin"}, status=400)

    token_generator = PasswordResetTokenGenerator()
    token = token_generator.make_token(target)

    promotion = AdminPromotion(
        email=email,
        token=token,
        expiration=timezone.now() + timezone.timedelta(hours=24),
        requested_by=request.user,
    )
    promotion.save()

    confirm_url = f"{os.getenv('ADMIN_PROMOTION_URL')}/{token}"

    subject = "FACT Admin Access Request"
    body = (
        f"Hi {target.first_name}. {request.user.first_name} {request.user.last_name} "
        f"has requested that your FACT account be given admin access.\n\n"
        f"If you'd like to accept, click the link below:\n\n{confirm_url}\n\n"
        f"If you weren't expecting this, you can ignore this email — nothing happens "
        f"until this link is clicked. This link will expire in 24 hours."
    )
    from_email = os.getenv("EMAIL_HOST_USER")
    send_mail(subject, body, from_email, [email])

    return JsonResponse({"message": f"Promotion request sent to {email}"})


def promote_admin_confirm(request):
    """
    POST: Confirm a pending admin promotion using the token emailed by
    promote_admin above. Not admin-gated — the token itself, known only to
    whoever received the email, is the credential.
    """
    if request.method != "POST":
        return JsonResponse({"message": "method not allowed"}, status=405)

    data = json.loads(request.body)
    token = data.get("token")

    if not token or len(token) == 0:
        return JsonResponse({"message": "Must provide token"}, status=400)

    AdminPromotion.objects.filter(expiration__lt=timezone.now()).delete()

    try:
        promotion = AdminPromotion.objects.get(token=token)
    except AdminPromotion.DoesNotExist:
        return JsonResponse({"message": "Invalid or expired promotion link"}, status=409)

    try:
        target = User.objects.get(email=promotion.email)
    except User.DoesNotExist:
        promotion.delete()
        return JsonResponse({"message": "That account no longer exists"}, status=404)

    admin_group, _ = Group.objects.get_or_create(name="FACTAdmin")
    target.groups.add(admin_group)
    promotion.delete()

    return JsonResponse({"message": "success"})


def reset_admin_password(request):
    """
    POST: Request that another FACTAdmin's password be reset (admin only).
    Sends a confirmation link to the target's email instead of resetting
    the password immediately — the new password is only set once they
    click it and choose one themselves (see reset_admin_password_confirm
    below). There is deliberately no self-service path: an admin login
    has no account context to key a "forgot password" email off of before
    they've authenticated, so resets go through a peer admin instead.
    """
    if not request.user.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "Must be admin to make this request"}, status=403
        )

    if request.method != "POST":
        return JsonResponse({"message": "method not allowed"}, status=405)

    data = json.loads(request.body)
    email = data.get("email")

    if not email or len(email) == 0:
        return JsonResponse({"message": "Must provide email"}, status=400)

    try:
        target = User.objects.get(email=email)
    except User.DoesNotExist:
        return JsonResponse({"message": "No account found with that email"}, status=404)

    if not target.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "That account is not an admin"}, status=400
        )

    token_generator = PasswordResetTokenGenerator()
    token = token_generator.make_token(target)

    reset = AdminPasswordReset(
        email=email,
        token=token,
        expiration=timezone.now() + timezone.timedelta(hours=24),
        requested_by=request.user,
    )
    reset.save()

    confirm_url = f"{os.getenv('ADMIN_PASSWORD_RESET_URL')}/{token}"

    subject = "FACT Admin Password Reset"
    body = (
        f"Hi {target.first_name}. {request.user.first_name} {request.user.last_name} "
        f"has requested a password reset for your FACT admin account.\n\n"
        f"If you'd like to set a new password, click the link below:\n\n{confirm_url}\n\n"
        f"If you weren't expecting this, you can ignore this email — nothing changes "
        f"until this link is clicked and a new password is submitted. This link will "
        f"expire in 24 hours."
    )
    from_email = os.getenv("EMAIL_HOST_USER")
    send_mail(subject, body, from_email, [email])

    return JsonResponse({"message": f"Password reset request sent to {email}"})


def reset_admin_password_confirm(request):
    """
    POST: Confirm a pending admin password reset using the token emailed
    by reset_admin_password above, and set the new password. Not
    admin-gated — the token itself, known only to whoever received the
    email, is the credential.
    """
    if request.method != "POST":
        return JsonResponse({"message": "method not allowed"}, status=405)

    data = json.loads(request.body)
    token = data.get("token")
    password = data.get("password")

    if not token or len(token) == 0:
        return JsonResponse({"message": "Must provide token"}, status=400)

    if not password or len(password) == 0:
        return JsonResponse({"message": "Must provide a new password"}, status=400)

    AdminPasswordReset.objects.filter(expiration__lt=timezone.now()).delete()

    try:
        reset = AdminPasswordReset.objects.get(token=token)
    except AdminPasswordReset.DoesNotExist:
        return JsonResponse({"message": "Invalid or expired reset link"}, status=409)

    try:
        target = User.objects.get(email=reset.email)
    except User.DoesNotExist:
        reset.delete()
        return JsonResponse({"message": "That account no longer exists"}, status=404)

    target.set_password(password)
    target.save()
    reset.delete()

    return JsonResponse({"message": "success"})


def day_of_registration(request):
    """
    POST: Create a delegate account in person, at the door on the day of
    the conference (admin only).

    Trusts the admin's own visual confirmation of a purchased ticket
    (checked at the door) instead of looking up an Eventbrite order —
    day-of sales are the one path that deliberately does not verify
    against Eventbrite. Reuses _create_delegate_account and the same
    capacity-locked workshop registration every other signup path uses, so
    a day-of delegate is registered exactly as safely as an online one.
    Deliberately does not call login() — this is the admin's own session,
    not the new delegate's.
    """
    if not request.user.groups.filter(name="FACTAdmin").exists():
        return JsonResponse(
            {"message": "Must be admin to make this request"}, status=403
        )

    if request.method != "POST":
        return JsonResponse({"message": "method not allowed"}, status=405)

    data = json.loads(request.body)

    ticket_type = data.get("ticket_type")
    if ticket_type not in Delegate.TicketType.values:
        return JsonResponse({"message": "Invalid ticket_type"}, status=400)

    workshop_ids = [
        data.get("workshop_1_id"),
        data.get("workshop_2_id"),
        data.get("workshop_3_id"),
    ]
    requested_ids = [int(w) for w in workshop_ids if w]

    if requested_ids and ticket_type not in (
        Delegate.TicketType.WORKSHOP,
        Delegate.TicketType.BUNDLE,
    ):
        return JsonResponse(
            {"message": "This ticket type does not include workshop registration"},
            status=400,
        )

    if not data.get("password"):
        return JsonResponse({"message": "Must provide password"}, status=400)

    class _RollbackWithResponse(Exception):
        def __init__(self, response):
            self.response = response

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
                # nothing written yet, safe to return directly
                return error

            delegate = user.delegate
            delegate.payment_status = Delegate.PaymentStatus.PAID
            delegate.ticket_type = ticket_type
            delegate.eventbrite_order_id = (
                f"DAY_OF_{request.user.username}_{timezone.now().timestamp()}"
            )
            delegate.payment_verified_at = timezone.now()
            delegate.save()

            if requested_ids:
                # raise instead of returning here — a bare early return would
                # exit the `with` block without an exception, committing the
                # account + payment status already written above even though
                # workshop registration failed
                workshop_error = _lock_and_register_workshops(
                    delegate, requested_ids, replace_existing=False
                )
                if workshop_error:
                    raise _RollbackWithResponse(workshop_error)
    except _RollbackWithResponse as rollback:
        return rollback.response
    except IntegrityError:
        return JsonResponse(
            {"message": "Server error creating this delegate — please retry"}, status=409
        )

    return HttpResponse(
        serializers.serialize_user(user), content_type="application/json"
    )