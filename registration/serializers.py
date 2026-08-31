import json
from registration.models import (
    Delegate,
    Facilitator,
    FacilitatorAssistant,
    FacilitatorRegistration,
    FacilitatorWorkshop,
    Registration,
    Workshop,
)
from django.contrib.auth.models import User
from django.core import serializers


def serialize_workshop(workshop, include_fas=False):
    """
    Serializes workshop data including location, facilitators, and registration count.
    Optional: Include facilitator assistants.
    """
    workshop_data = serializers.serialize("json", [workshop])
    # location is nullable (Workshop.location, null=True/blank=True) — Django's
    # serializer crashes on serialize("json", [None]), so a workshop with no
    # location assigned yet must serialize to an empty list, not attempt this.
    location_data = serializers.serialize("json", [workshop.location] if workshop.location else [])
    registrations = Registration.objects.filter(workshop_id=workshop.pk)
    facilitator_registrations = FacilitatorRegistration.objects.filter(
        workshop_id=workshop.pk
    )
    facilitators = FacilitatorWorkshop.objects.filter(workshop_id=workshop.pk).values(
        "facilitator"
    )
    facilitator_data = serializers.serialize(
        "json", Facilitator.objects.filter(pk__in=facilitators)
    )

    data = {
        "workshop": json.JSONDecoder().decode(workshop_data),
        "location": json.JSONDecoder().decode(location_data),
        "facilitators": json.JSONDecoder().decode(facilitator_data),
        "registrations": registrations.count() + facilitator_registrations.count(),
    }

    if include_fas:
        fa_data = serializers.serialize(
            "json", FacilitatorAssistant.objects.filter(workshop_id=workshop.pk)
        )
        data["facilitator_assistants"] = json.JSONDecoder().decode(fa_data)

    return data


def serialize_user(user):
    """
    Serializes user data including delegate profile and workshop registrations.
    """
    delegate_data = serializers.serialize("json", [user.delegate])
    user_data = serializers.serialize("json", [user])
    registration_data = serializers.serialize(
        "json", Registration.objects.filter(delegate=user.delegate)
    )

    data = {
        "delegate": json.JSONDecoder().decode(delegate_data),
        "user": json.JSONDecoder().decode(user_data),
        "registration": json.JSONDecoder().decode(registration_data),
    }

    return json.dumps(data)


def serialize_facilitator(facilitator):
    """
    Serializes facilitator data including profile, user account, and workshop assignments.
    """
    facilitator_data = serializers.serialize("json", [facilitator])
    user_data = serializers.serialize("json", [facilitator.user])
    workshops = serializers.serialize(
        "json", FacilitatorWorkshop.objects.filter(facilitator=facilitator)
    )

    registrations = FacilitatorRegistration.objects.none()
    for name in facilitator.facilitators:
        registrations = registrations | FacilitatorRegistration.objects.filter(
            facilitator_name=name.strip()
        )

    registrations = serializers.serialize("json", registrations)

    # get a list of workshops that the facilitator is facilitating
    data = {
        "facilitator": json.loads(facilitator_data),
        "user": json.loads(user_data),
        "registrations": json.loads(registrations),
        "workshops": json.loads(workshops),
    }

    return json.dumps(data)
