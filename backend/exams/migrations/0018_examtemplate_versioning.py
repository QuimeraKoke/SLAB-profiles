"""Add family_id / is_active_version to ExamTemplate.

Sequence:
  1. AddField for both columns (nullable / no constraint so we can backfill).
  2. RunPython: every existing row gets `family_id = uuid4()` (each one
     becomes its own one-row family) and `is_active_version = True`.
  3. AlterField to enforce NOT NULL on `family_id`.
  4. Add the two new constraints + the slug+active index.

Backfill rationale: pre-existing templates have a one-to-one relationship
with their data; treating each as version 1 of its own family preserves
exactly the current behavior — no template is silently "demoted" or
joined with another. Future forks build new versions on top.
"""

from __future__ import annotations

import uuid

from django.db import migrations, models


def backfill_family_id(apps, schema_editor):
    ExamTemplate = apps.get_model("exams", "ExamTemplate")
    for tpl in ExamTemplate.objects.all().only("pk"):
        ExamTemplate.objects.filter(pk=tpl.pk).update(
            family_id=uuid.uuid4(),
            is_active_version=True,
        )


def reverse_backfill(apps, schema_editor):
    # No-op: we don't try to coalesce families when rolling back. The
    # subsequent RemoveField step handles cleanup.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("exams", "0017_templatefield_option_regions"),
    ]

    operations = [
        migrations.AddField(
            model_name="examtemplate",
            name="family_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="examtemplate",
            name="is_active_version",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Exactly one version per family is active. New ExamResults are "
                    "written against the active version (resolved by slug); inactive "
                    "versions stay for history but are hidden from the registrar's "
                    "template picker."
                ),
            ),
        ),
        migrations.RunPython(backfill_family_id, reverse_backfill),
        migrations.AlterField(
            model_name="examtemplate",
            name="family_id",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                help_text=(
                    "Shared by every version of the same template. Set by "
                    "`fork_new_version`."
                ),
            ),
        ),
        migrations.AddIndex(
            model_name="examtemplate",
            index=models.Index(
                fields=["slug", "is_active_version"],
                name="exam_tpl_slug_active_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="examtemplate",
            constraint=models.UniqueConstraint(
                fields=["family_id", "version"],
                name="exam_tpl_family_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="examtemplate",
            constraint=models.UniqueConstraint(
                fields=["family_id"],
                condition=models.Q(is_active_version=True),
                name="exam_tpl_one_active_per_family",
            ),
        ),
    ]
