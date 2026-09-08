import json

from django.http import HttpResponse, JsonResponse
from django.core import serializers
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login


def login_admin(request):
    """
    POST: Admin login
    Required fields: username, password
    Returns 400 for invalid credentials, 403 for non-admin
    """
    if request.method == "POST":
        user = request.user

        # get data
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

        # make sure user is allowed
        if not user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse(
                {"message": "Must be admin to make this request"}, status=403
            )

        login(request, user)

        return HttpResponse(
            serializers.serialize("json", [user]),
            content_type="application/json",
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)


def me(request):
    """
    GET: Get current admin user info
    Returns 403 if not authenticated or not admin
    """
    if request.method == "GET":
        user = request.user

        if not user.is_authenticated:
            return JsonResponse({"message": "No admin logged in"}, status=403)

        if not user.groups.filter(name="FACTAdmin").exists():
            return JsonResponse({"message": "No admin logged in"}, status=403)

        return HttpResponse(
            serializers.serialize("json", [user]),
            content_type="application/json",
        )
    else:
        return JsonResponse({"message": "Method not allowed"}, status=405)
