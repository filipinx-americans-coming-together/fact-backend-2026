import json
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.core import serializers

from fact_admin.models import Notification


def notification_id(request, id):
    """
    DELETE: Remove notification (admin only)
    Returns 404 if not found, 403 for non-admin
    """
    if request.method == "DELETE":
        user = request.user

        # make sure user is allowed
        if not user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        notification = Notification.objects.filter(pk=id)

        if not notification.exists():
            return JsonResponse({"message": "Notification not found"}, status=404)

        notification.delete()

        return JsonResponse({"message": "success"})
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def notifications(request):
    """
    GET: List active notifications
    POST: Create notification (admin only)
    Required fields: message (min 10 chars), expiration
    Returns 400 for invalid data, 409 for duplicate, 403 for non-admin
    """
    if request.method == "GET":
        # get objects that are not expired
        notifications = Notification.objects.filter(expiration__gt=timezone.now())

        return HttpResponse(
            serializers.serialize("json", notifications),
            content_type="application/json",
        )
    elif request.method == "POST":
        user = request.user

        # make sure user is allowed
        if not user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        # remove expired notifications
        Notification.objects.filter(expiration__lte=timezone.now()).delete()

        # get data
        data = json.loads(request.body)

        message = data.get("message")
        expiration = data.get("expiration")

        # check data
        if not message or len(message) < 10:
            return JsonResponse({"message": "Enter a valid message"}, status=400)

        if Notification.objects.filter(message=message, expiration__gte=timezone.now()):
            return JsonResponse(
                {"message": "Notification with this message already exists"}, status=409
            )

        if not expiration:
            return JsonResponse(
                {"message": "Please provide expiration date/time"}, status=400
            )

        try:
            expiration = timezone.datetime.fromisoformat(expiration)
        except ValueError:
            return JsonResponse(
                {"message": "Expiration could not be converted to valid date/time"},
                status=400,
            )

        # create object
        notification = Notification(message=message, expiration=expiration)
        notification.save()

        return HttpResponse(
            serializers.serialize("json", [notification]),
            content_type="application/json",
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)
