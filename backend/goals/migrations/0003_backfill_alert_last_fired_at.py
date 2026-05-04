"""Backfill `last_fired_at = fired_at` for pre-existing alerts."""

from django.db import migrations


def forwards(apps, schema_editor):
    Alert = apps.get_model("goals", "Alert")
    Alert.objects.filter(last_fired_at__isnull=True).update(
        last_fired_at=models.F("fired_at"),  # noqa
    )


def reverse(apps, schema_editor):
    pass  # New rows since this migration won't have last_fired_at=NULL anyway.


class Migration(migrations.Migration):
    dependencies = [
        ("goals", "0002_alert_last_fired_at_alert_trigger_count"),
    ]

    # Use a SQL-style update because django.db.models.F can't be used inside
    # update() at migration time without importing it; do it via raw SQL to
    # avoid the import dance.
    operations = [
        migrations.RunSQL(
            sql="UPDATE goals_alert SET last_fired_at = fired_at WHERE last_fired_at IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
