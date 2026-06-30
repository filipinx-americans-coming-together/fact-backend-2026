import json
import os
import pandas as pd

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from registration import serializers
from registration.facilitator.views import create_facilitator_account
from registration.models import (
    Facilitator,
    FacilitatorWorkshop,
    Location,
    Workshop,
)
from ..management.commands.matchworkshoplocations import set_locations

from django.core import serializers as django_serializers
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt

import environ

env = environ.Env()
environ.Env.read_env()


def workshops(request):
    """
    GET: List all workshops
    POST: Create new workshop
    Required fields:
        - title: Workshop name
        - description: Workshop description
        - session: Workshop session number (1-3)
        - location: Location ID (optional)
    Returns 400 for invalid data, 409 for duplicate workshop
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            location = None
            if "location" in data:
                location = get_object_or_404(Location, id=data.get("location"))

            w = Workshop.objects.filter(title=data.get("title"))

            if w.exists():
                if w[0].session == data.get("session"):
                    return JsonResponse(
                        {"message": "Workshop in current session already exists"},
                        status=409,
                    )

            workshop = Workshop(
                title=data.get("title"),
                description=data.get("description"),
                location=location,
                session=data.get("session"),
            )

            workshop.save()
            data = json.dumps(serializers.serialize_workshop(workshop))

            return HttpResponse(data, content_type="application/json")
        except json.JSONDecodeError:
            return JsonResponse({"message": "Invalid JSON"}, status=400)
    elif request.method == "GET":
        from django.db.models import Count
        workshops = Workshop.objects.annotate(registration_count=Count('registration'))
        serialized = django_serializers.serialize("json", workshops)
        data = json.loads(serialized)
        for d, w in zip(data, workshops):
            d["fields"]["registration_count"] = w.registration_count
        return HttpResponse(json.dumps(data), content_type="application/json")
    else:
        return JsonResponse({"message": "Method not allowed"}, status=400)


def workshops_bulk(request):
    """
    POST: Bulk upload workshops from Excel file (admin only)
    Required file format:
        - Excel file with columns: title, session, description, department_name,
          facilitators, image_url, bio, networking_session, position (optional),
          preferred_cap (optional), moveable_seats
        - No empty cells (except optional fields)
        - Sessions must be 1, 2, or 3
    Returns 403 for non-admin, 409 if workshops exist, 400 for invalid data
    """
    if request.method == "POST":
        # must be admin
        if not request.user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        # must have no workshops
        if Workshop.objects.all().count() > 0 or Facilitator.objects.all().count() > 0:
            return JsonResponse(
                {
                    "message": "Delete existing workshops and facilitators before attempting to upload"
                },
                status=409,
            )

        if "workshops" not in request.FILES:
            return JsonResponse({"message": "Must include file"}, status=400)

        file = request.FILES["workshops"]
        workshop_df = None

        try:
            workshop_df = pd.read_excel(file)
        except Exception:
            return JsonResponse({"message": "Error reading file"}, status=400)

        workshop_df = workshop_df.drop_duplicates()
        # when loading in df, pandas will add ".#" to duplicate columns
        workshop_df.columns = [x.lower().split(".")[0] for x in workshop_df.columns]

        # validate data
        columns_set = set(workshop_df.columns)

        if len(columns_set) != len(workshop_df.columns):
            return JsonResponse({"message": "Duplicate column names"}, status=400)

        expected_columns = [
            "title",
            "session",
            "description",
            "department_name",
            "facilitators",
            "image_url",
            "bio",
            "networking_session",
            "position",
            "preferred_cap",
            "moveable_seats",
        ]

        for i in range(len(expected_columns)):
            if expected_columns[i] not in columns_set:
                return JsonResponse(
                    {"message": f"Missing column {expected_columns[i]}"}, status=400
                )

        if (
            workshop_df.drop(["position", "preferred_cap"], axis=1)
            .isnull()
            .values.any()
        ):
            return JsonResponse(
                {"message": "Missing values - make sure there are no empty cells"},
                status=400,
            )

        # check sessions and locations
        workshop_count = {1: [], 2: [], 3: []}

        valid_sessions = set([1, 2, 3])

        for idx, rows in workshop_df.iterrows():
            if rows["session"] not in valid_sessions:
                return JsonResponse(
                    {"message": f"{rows['session']} is not a valid session number"},
                    status=400,
                )

            # need to account for duplicate workshop names because of career panels
            if rows["title"] not in workshop_count[rows["session"]]:
                workshop_count[rows["session"]].append(rows["title"])

        for i in range(1, 4):
            if len(workshop_count[i]) > Location.objects.filter(session=i).count():
                return JsonResponse(
                    {
                        "message": f"Not enough locations for given workshops in session {i}"
                    },
                    status=409,
                )

        # save workshops, create facilitator accounts, session 1 and 2
        facilitator_account_urls = []
        for index, row in workshop_df[workshop_df["session"].isin([1, 2])].iterrows():
            # facilitator (if does not exist)
            # department names for workshop 3 (career panels) may appear in the individual facilitator names of another workshop
            facilitator = Facilitator.objects.filter(
                department_name=row["department_name"]
            ).first()

            if not facilitator:
                user, token, expiration = create_facilitator_account(
                    row["department_name"]
                )
                reset_url = f"{os.getenv('ACCOUNT_SET_UP_URL')}/{token}"

                facilitator_account_urls.append(
                    (row["department_name"], user.username, reset_url)
                )

                facilitator = Facilitator(
                    user=user,
                    department_name=row["department_name"],
                    facilitators=row["facilitators"],
                    image_url=row["image_url"],
                    bio=row["bio"],
                    attending_networking_session=row["networking_session"] == 1,
                )

                if row["position"]:
                    facilitator.position = row["position"]

                facilitator.save()

            elif row["networking_session"] == 1:
                # if facilitator is already created and this row is marked as attending networking session
                facilitator.attending_networking_session = True
                facilitator.save()

            # workshop
            workshop = Workshop(
                title=row["title"],
                description=row["description"],
                session=row["session"],
                moveable_seats=row["moveable_seats"],
            )

            try:
                cap = int(row["preferred_cap"])
                workshop.preferred_cap = cap
            except (ValueError, TypeError):
                pass

            workshop.save()

            FacilitatorWorkshop.objects.create(
                facilitator=facilitator, workshop=workshop
            )

        # session 3 (career panels)
        for index, row in workshop_df[workshop_df["session"] == 3].iterrows():
            # if facilitator is a facilitator already, do not create account
            facilitator = Facilitator.objects.filter(
                department_name=row["department_name"]
            ).first()

            if not facilitator:
                user, token, expiration = create_facilitator_account(
                    row["department_name"]
                )

                reset_url = f"{env('ACCOUNT_SET_UP_URL')}/{token}"

                facilitator_account_urls.append(
                    (row["department_name"], user.username, reset_url)
                )

                facilitator = Facilitator(
                    user=user,
                    department_name=row["department_name"],
                    facilitators=row["facilitators"],
                    image_url=row["image_url"],
                    bio=row["bio"],
                    attending_networking_session=row["networking_session"] == 1,
                )

                if row["position"]:
                    facilitator.position = row["position"]

                facilitator.save()

            elif row["networking_session"] == 1:
                # if facilitator is already created and this row is marked as attending networking session
                facilitator.attending_networking_session = True
                facilitator.save()

            # if title already created ignore
            workshop = Workshop.objects.filter(title=row["title"]).first()
            if not workshop:
                # workshop
                workshop = Workshop(
                    title=row["title"],
                    description=row["description"],
                    session=row["session"],
                    moveable_seats=row["moveable_seats"],
                )

                try:
                    cap = int(row["preferred_cap"])
                    workshop.preferred_cap = cap
                except (ValueError, TypeError):
                    pass

                workshop.save()

            FacilitatorWorkshop.objects.create(
                facilitator=facilitator, workshop=workshop
            )

        # set locations
        set_locations(1)
        set_locations(2)
        set_locations(3)

        # email facilitator password links
        subject = "FACT Facilitator Accounts"
        body = "Facilitator accounts created"

        for facilitator in facilitator_account_urls:
            body += f"\nFacilitator: {facilitator[0]}, Username: {facilitator[1]}, Account Link: {facilitator[2]}"

        from_email = env("EMAIL_HOST_USER")
        to_email = ["fact.it@psauiuc.org"]

        send_mail(subject, body, from_email, to_email)

        data = django_serializers.serialize("json", Workshop.objects.all())

        return HttpResponse(data, content_type="application/json")
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def workshop_id(request, id):
    """
    GET: Get workshop by ID
    PUT: Update workshop
    DELETE: Delete workshop
    Required fields for PUT:
        - title: Workshop name
        - description: Workshop description
        - session: Workshop session number
        - location: Location ID (optional)
    Returns 404 if not found, 400 for invalid data
    """
    workshop = get_object_or_404(Workshop, pk=id)

    if request.method == "GET":
        include_fas = False
        if hasattr(request.user, "facilitator"):
            include_fas = True
        return HttpResponse(
            json.dumps(serializers.serialize_workshop(workshop, include_fas=include_fas)),
            content_type="application/json",
        )
    elif request.method == "PUT":
        try:
            # TODO integrity checks
            data = json.loads(request.body)
            location = get_object_or_404(Location, id=data.get("location"))

            workshop.title = data.get("title", workshop.title)
            workshop.description = data.get("description", workshop.description)
            workshop.location = location
            workshop.session = data.get("session", workshop.session)

            workshop.save()
            data = json.dumps(serializers.serialize_workshop(workshop))
            return HttpResponse(data, content_type="application/json")
        except json.JSONDecodeError:
            return JsonResponse({"message": "Invalid JSON"}, status=400)
    elif request.method == "DELETE":
        workshop.delete()
        return JsonResponse({"message": "success"}, status=200)
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def workshops_all(request):
    """
    GET: List all workshops with facilitator details
    Returns 405 for non-GET methods
    """
    if request.method == "GET":
        data = {}
        for workshop in Workshop.objects.all():
            data.update({workshop.pk: serializers.serialize_workshop(workshop, include_fas=False)})
        return HttpResponse(json.dumps(data), content_type="application/json")
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)