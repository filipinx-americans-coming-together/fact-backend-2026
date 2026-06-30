import datetime
import json
import pytz

from django.http import HttpResponse, JsonResponse
import pandas as pd
from fact_admin.models import AgendaItem
from django.core import serializers as django_serializers
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt


def agenda_items(request):
    """
    GET: List all agenda items
    POST: Create new agenda item (admin only)
    Required fields: title, start_time, end_time, building
    Returns 400 for invalid times, 403 for non-admin
    """
    if request.method == "GET":
        data = django_serializers.serialize(
            "json", AgendaItem.objects.all().order_by("start_time")
        )
        return HttpResponse(data, content_type="application/json")
    elif request.method == "POST":
        # make sure user is allowed
        if not request.user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        data = json.loads(request.body)
        title = data.get("title")
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        building = data.get("building")
        room_num = data.get("room_num")
        session_num = data.get("session_num")
        address = data.get("address")

        if not title or not start_time or not end_time:
            return JsonResponse(
                {"message": "Must provide title, start time, end time, and building"},
                status=400,
            )

        if title == "" or start_time == "" or end_time == "":
            return JsonResponse(
                {"message": "Must provide title, start time, end time, and building"},
                status=400,
            )

        start_time = parse_datetime(start_time)
        end_time = parse_datetime(end_time)

        if start_time > end_time:
            return JsonResponse(
                {"message": "End time can not be before start time"},
                status=400,
            )

        new_agenda_item = AgendaItem(
            title=title,
            building=building,
            room_num=room_num,
            start_time=start_time,
            end_time=end_time,
            address=address,
        )

        # note this just ignores (no error) malformed session data
        if int(session_num) in [1, 2, 3]:
            new_agenda_item.session_num = int(session_num)

        new_agenda_item.save()

        data = django_serializers.serialize("json", [new_agenda_item])
        return HttpResponse(data, content_type="application/json")

    else:
        return JsonResponse({"message": "method not allowed"}, status=405)


def agenda_items_id(request, id):
    """
    DELETE: Remove agenda item (admin only)
    Returns 404 if item not found, 403 for non-admin
    """
    if request.method == "DELETE":
        # make sure user is allowed
        if not request.user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        agenda_item = AgendaItem.objects.filter(pk=id)

        if not agenda_item.exists():
            return JsonResponse({"message": "Agenda item not found"}, status=404)

        agenda_item.delete()

        return JsonResponse({"message": "Delete success"})

    else:
        return JsonResponse({"message": "method not allowed"}, status=405)

def agenda_items_bulk(request):
    """
    POST: Bulk upload agenda items from Excel (admin only)
    Required columns: title, date, start_time, end_time, building, room_num, session_num, address
    Returns 400 for invalid data, 409 if items exist, 403 for non-admin
    Note: Existing items must be deleted first
    """
    if request.method == "POST":
        # make sure user is allowed
        if not request.user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        # must have no agenda items
        if AgendaItem.objects.all().count() > 0:
            return JsonResponse(
                {"message": "Delete existing agenda items before attempting to upload"},
                status=409,
            )

        if "agenda" not in request.FILES:
            return JsonResponse({"message": "Must include file"}, status=400)

        file = request.FILES["agenda"]
        agenda_df = None

        try:
            agenda_df = pd.read_excel(file)
        except:
            return JsonResponse({"message": "Error reading file"}, status=400)

        agenda_df = agenda_df.drop_duplicates()
        # when loading in df, pandas will add ".#" to duplicate columns
        agenda_df.columns = [x.lower().split(".")[0] for x in agenda_df.columns]

        # validate data
        columns_set = set(agenda_df.columns)

        if len(columns_set) != len(agenda_df.columns):
            return JsonResponse({"message": "Duplicate column names"}, status=400)

        expected_columns = [
            "title",
            "date",
            "start_time",
            "end_time",
            "building",
            "room_num",
            "session_num",
            "address",
        ]

        for i in range(len(expected_columns)):
            if expected_columns[i] not in columns_set:
                return JsonResponse(
                    {"message": f"Missing column '{expected_columns[i]}'"}, status=400
                )

        # check data
        for idx, row in agenda_df.iterrows():
            if row["start_time"] > row["end_time"]:
                return JsonResponse(
                    {"message": "Start times can not be after end times"}, status=400
                )

            if (
                pd.isna(agenda_df.at[idx, "title"])
                or pd.isna(agenda_df.at[idx, "date"])
                or pd.isna(agenda_df.at[idx, "start_time"])
                or pd.isnull(agenda_df.at[idx, "title"])
                or pd.isnull(agenda_df.at[idx, "date"])
                or pd.isnull(agenda_df.at[idx, "start_time"])
            ):
                return JsonResponse(
                    {"message": "Title, date, and start time can not be empty"},
                    status=400,
                )

        timezone = pytz.timezone("America/Chicago")

        for idx, row in agenda_df.iterrows():
            start_time = row["start_time"]
            if isinstance(row["start_time"], pd.Timestamp):
                start_time = row["start_time"].time()

            end_time = row["end_time"]
            if isinstance(row["end_time"], pd.Timestamp):
                end_time = row["end_time"].time()

            start_datetime = timezone.localize(
                datetime.datetime.combine(row["date"], start_time)
            )

            end_datetime = timezone.localize(
                datetime.datetime.combine(row["date"], end_time)
            )

            new_agenda_item = AgendaItem(
                title=row["title"],
                building=row["building"],
                room_num=row["room_num"],
                start_time=start_datetime,
                end_time=end_datetime,
                address=row["address"],
            )

            # note this just ignores malformed session data
            if row["session_num"] and row["session_num"] in [1, 2, 3]:
                new_agenda_item.session_num = int(row["session_num"])

            new_agenda_item.save()

        data = django_serializers.serialize(
            "json", AgendaItem.objects.all().order_by("start_time")
        )
        return HttpResponse(data, content_type="application/json")
    else:
        return JsonResponse({"message": "method not allowed"}, status=405)
