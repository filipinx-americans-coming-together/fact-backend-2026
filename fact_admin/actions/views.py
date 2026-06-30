import json
from django.http import FileResponse, HttpResponse, JsonResponse
from django.core import serializers as django_serializers
from django.contrib.auth.models import User
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
import os

import pandas as pd

from fact_admin.models import RegistrationFlag
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