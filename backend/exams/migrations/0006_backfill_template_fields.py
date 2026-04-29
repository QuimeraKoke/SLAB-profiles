"""One-time backfill: populate `TemplateField` rows from each
ExamTemplate's existing `config_schema["fields"]` JSON.

After this runs, every existing template can be edited via the admin's
inline form. New JSON written by seed commands still needs a follow-up
`python manage.py sync_template_fields` to rebuild the rows.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    ExamTemplate = apps.get_model("exams", "ExamTemplate")
    TemplateField = apps.get_model("exams", "TemplateField")

    for template in ExamTemplate.objects.all():
        fields = (template.config_schema or {}).get("fields") or []
        if not fields:
            continue
        # Idempotent: clear any rows first (the schema migration just created
        # the table so this should always be empty, but be defensive).
        TemplateField.objects.filter(template=template).delete()

        for idx, raw in enumerate(fields):
            if not isinstance(raw, dict):
                continue
            ftype = raw.get("type") or "number"
            TemplateField.objects.create(
                template=template,
                sort_order=idx,
                key=raw.get("key", f"field_{idx}"),
                label=raw.get("label", raw.get("key", f"Campo {idx + 1}")),
                type=ftype,
                unit=raw.get("unit", "") or "",
                group=raw.get("group", "") or "",
                options=raw.get("options") or [],
                formula=raw.get("formula", "") or "",
                chart_type=raw.get("chart_type", "") or "",
                required=bool(raw.get("required")),
                multiline=bool(raw.get("multiline")),
                rows=raw.get("rows"),
                placeholder=raw.get("placeholder", "") or "",
            )


def reverse(apps, schema_editor):
    TemplateField = apps.get_model("exams", "TemplateField")
    TemplateField.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("exams", "0005_templatefield"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
