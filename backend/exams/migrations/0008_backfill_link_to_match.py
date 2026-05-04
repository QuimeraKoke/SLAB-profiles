"""Backfill `link_to_match` so current picker behavior is preserved.

Today the match picker shows up in two places:
  1. Single-mode forms when input_config.allow_event_link == true
     (only "Rendimiento de partido" today).
  2. The BulkIngestForm — unconditionally — for any template with
     input_modes including "bulk_ingest" (only the GPS template today).

After this migration the picker is gated by ExamTemplate.link_to_match in
both flows, so we set it True for any template currently showing the picker.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    ExamTemplate = apps.get_model("exams", "ExamTemplate")
    for tpl in ExamTemplate.objects.all():
        cfg = tpl.input_config or {}
        modes = cfg.get("input_modes") or []
        already_linked = bool(cfg.get("allow_event_link"))
        bulk_with_match = "bulk_ingest" in modes
        if already_linked or bulk_with_match:
            tpl.link_to_match = True
            # Keep JSON in sync (the model's save() does this; we use update_fields
            # to avoid retriggering input_config validation surprises in older rows).
            new_cfg = dict(cfg)
            new_cfg["allow_event_link"] = True
            tpl.input_config = new_cfg
            tpl.save(update_fields=["link_to_match", "input_config"])


def reverse(apps, schema_editor):
    ExamTemplate = apps.get_model("exams", "ExamTemplate")
    ExamTemplate.objects.update(link_to_match=False)


class Migration(migrations.Migration):
    dependencies = [
        ("exams", "0007_examtemplate_link_to_match"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
