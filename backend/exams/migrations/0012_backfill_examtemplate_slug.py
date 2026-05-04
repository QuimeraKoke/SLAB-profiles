"""Backfill `ExamTemplate.slug` from `name` for existing rows.

Slug rules: lowercase, ASCII, dashes turned into underscores, must match
`^[a-z][a-z0-9_]*$`. Conflicts within the same club get a numeric suffix
(`pentacompartimental`, `pentacompartimental_2`, …).
"""

import re
from django.db import migrations
from django.utils.text import slugify


def _to_identifier(name: str) -> str:
    s = slugify(name).replace("-", "_")[:80]
    if not s or not s[0].isalpha():
        s = f"t_{s}" if s else "template"
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s or "template"


def forwards(apps, schema_editor):
    ExamTemplate = apps.get_model("exams", "ExamTemplate")
    Department = apps.get_model("core", "Department")

    # Group by club so uniqueness check happens per club.
    by_club: dict = {}
    for tpl in ExamTemplate.objects.select_related("department").all():
        if tpl.slug:
            continue
        club_id = tpl.department.club_id
        used = by_club.setdefault(club_id, set())
        # Bring in any already-set slugs in this club.
        if not used:
            used.update(
                ExamTemplate.objects
                .filter(department__club_id=club_id)
                .exclude(slug="")
                .values_list("slug", flat=True)
            )

        base = _to_identifier(tpl.name)
        candidate = base
        n = 1
        while candidate in used or candidate == "player":
            n += 1
            candidate = f"{base}_{n}"
        used.add(candidate)
        tpl.slug = candidate
        tpl.save(update_fields=["slug"])


def reverse(apps, schema_editor):
    ExamTemplate = apps.get_model("exams", "ExamTemplate")
    ExamTemplate.objects.update(slug="")


class Migration(migrations.Migration):
    dependencies = [
        ("exams", "0011_examtemplate_slug_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
