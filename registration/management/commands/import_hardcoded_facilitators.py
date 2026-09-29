import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from registration.models import Facilitator

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "hardcoded_facilitators.json"


class Command(BaseCommand):
    help = (
        "One-time: copy the frontend's hardcoded facilitator photos and bios "
        "(src/util/facilitatorPhotos.ts, exported as JSON) into the database, "
        "and clear the 'nan' positions left by the spreadsheet import."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--file", default=str(DEFAULT_FILE))

    def handle(self, *args, dry_run=False, file=None, **options):
        entries = json.loads(Path(file).read_text(encoding="utf-8"))
        with transaction.atomic():
            cleared = Facilitator.objects.filter(position="nan").update(position="")
            self.stdout.write(f"Cleared 'nan' position on {cleared} facilitators")
            for entry in entries:
                self._apply(entry)
            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write("Dry run: nothing saved.")

    def _apply(self, entry):
        matches = list(
            Facilitator.objects.filter(facilitatorworkshop__workshop__title=entry["title"]).distinct()
        )
        named = [f for f in matches if f.department_name.lower() == entry["name"].lower()]
        if named:
            matches = named
        if len(matches) != 1:
            reason = "no matching facilitator" if not matches else f"{len(matches)} facilitators, skipped"
            self.stdout.write(f"{entry['title']}: {reason}")
            return

        facilitator = matches[0]
        before = (facilitator.image_url, len(facilitator.bio or ""))
        # The hardcoded photo is what the live page shows today.
        facilitator.image_url = entry["photo"]
        facilitator.photo_width = entry["width"]
        facilitator.photo_height = entry["height"]
        facilitator.photo_blur = entry.get("blurDataURL") or ""
        facilitator.photo_opaque = not entry.get("flatPhoto", False)
        if len((facilitator.bio or "").strip()) < len(entry["bio"].strip()):
            facilitator.bio = entry["bio"]
        facilitator.save()
        self.stdout.write(
            f"{facilitator.department_name}: photo {before[0] or '-'} -> {facilitator.image_url}; "
            f"bio {before[1]} -> {len(facilitator.bio)} chars"
        )
