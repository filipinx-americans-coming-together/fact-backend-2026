import json
import tempfile
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from .models import Facilitator, FacilitatorWorkshop, Workshop

ENTRIES = [
    {"title": "PSA 101", "name": "MAFA", "photo": "https://blob.test/facilitators/mafa.png",
     "width": 180, "height": 180, "blurDataURL": "data:image/jpeg;base64,AAA",
     "bio": "A long and complete MAFA bio.", "flatPhoto": True},
    {"title": "Missing Workshop", "name": "Nobody", "photo": "https://blob.test/n.png",
     "width": 1, "height": 1, "blurDataURL": "", "bio": "x"},
]


class ImportHardcodedTest(TestCase):
    def setUp(self):
        user = User.objects.create_user("mafa0001", password="pw")
        self.mafa = Facilitator.objects.create(
            user=user, department_name="MAFA", position="nan", bio="short",
            image_url="https://drive.google.com/file/d/abc/view",
        )
        workshop = Workshop.objects.create(title="PSA 101", description="d", session=1)
        FacilitatorWorkshop.objects.create(facilitator=self.mafa, workshop=workshop)
        self.file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(ENTRIES, self.file)
        self.file.close()

    def run_command(self, *args):
        out = StringIO()
        call_command("import_hardcoded_facilitators", "--file", self.file.name, *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        output = self.run_command("--dry-run")
        self.mafa.refresh_from_db()
        self.assertEqual(self.mafa.image_url, "https://drive.google.com/file/d/abc/view")
        self.assertEqual(self.mafa.position, "nan")
        self.assertIn("Dry run", output)
        self.assertIn("MAFA", output)

    def test_real_run_copies_photo_bio_and_clears_nan(self):
        output = self.run_command()
        self.mafa.refresh_from_db()
        self.assertEqual(self.mafa.image_url, "https://blob.test/facilitators/mafa.png")
        self.assertEqual((self.mafa.photo_width, self.mafa.photo_height), (180, 180))
        self.assertEqual(self.mafa.photo_blur, "data:image/jpeg;base64,AAA")
        self.assertFalse(self.mafa.photo_opaque)
        self.assertEqual(self.mafa.bio, "A long and complete MAFA bio.")
        self.assertEqual(self.mafa.position, "")
        self.assertIn("Missing Workshop: no matching facilitator", output)

    def test_longer_backend_bio_kept(self):
        self.mafa.bio = "x" * 500
        self.mafa.save()
        self.run_command()
        self.mafa.refresh_from_db()
        self.assertEqual(self.mafa.bio, "x" * 500)
