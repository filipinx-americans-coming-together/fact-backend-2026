from django.db import migrations
from django.db.models import Q
from django.utils import timezone


def mark_existing_setups(apps, schema_editor):
    # Facilitators who finished account setup before this deploy are marked so
    # the sheet never sends them a fresh setup link (which would reset password).
    # This covers: (1) facilitators who logged in (last_login set), and
    # (2) facilitators who set up an account but never logged in (email set by setup view).
    Facilitator = apps.get_model("registration", "Facilitator")
    FacilitatorContact = apps.get_model("registration", "FacilitatorContact")
    for facilitator in Facilitator.objects.select_related("user").filter(
        Q(user__last_login__isnull=False) | ~Q(user__email="")
    ):
        FacilitatorContact.objects.update_or_create(
            facilitator=facilitator,
            defaults={"setup_completed_at": facilitator.user.last_login or timezone.now()},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0024_facilitator_photo_fields_facilitatorcontact"),
    ]

    operations = [
        migrations.RunPython(mark_existing_setups, migrations.RunPython.noop),
    ]
