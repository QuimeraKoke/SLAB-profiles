"""Populate `Category.is_senior` from the names the code used to hardcode.

This is the ONLY place the string "Primer Equipo" is allowed to decide anything,
and only because it runs once against the state that already exists. From here on
the flag is the answer and the name is just a label — which is the point: which
squad receives senior fixtures is a club decision, and it belongs in a field the
club can edit, not in a literal spread across three modules.

Deliberately conservative. A category is marked senior only when its name matches
exactly, so a club with a differently-named first team gets `False` everywhere and
a visible gap in the admin, rather than a wrong guess. `sync_comet` already
reports competitions it can't map, so an unset flag surfaces as "sin categoría"
instead of silently filing senior matches under a youth squad.
"""
from django.db import migrations

# Historical names this project's code checked for. Not a general rule — just
# what was already there on 2026-08-23.
SENIOR_NAMES = ("Primer Equipo",)


def mark_senior(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    Category.objects.filter(name__in=SENIOR_NAMES).update(is_senior=True)


def unmark(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    Category.objects.update(is_senior=False)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_category_is_senior"),
    ]

    operations = [
        migrations.RunPython(mark_senior, unmark),
    ]
