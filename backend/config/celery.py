"""Celery app for the SLAB backend.

Started by the `worker` and `beat` services in docker-compose.yml.
Tasks live in each Django app's `tasks.py` (auto-discovered).
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("slab")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# Beat schedule. 05:00 server-time gives the doctor a fresh batch of
# overnight goal checks before a typical morning briefing.
app.conf.beat_schedule = {
    "evaluate-due-goals-daily": {
        "task": "goals.tasks.evaluate_due_goals",
        "schedule": crontab(hour=5, minute=0),
    },
    # Weekly player-state history capture (Mondays 04:00) → evolution charts.
    "snapshot-player-states-weekly": {
        "task": "dashboards.tasks.snapshot_player_states",
        "schedule": crontab(hour=4, minute=0, day_of_week=1),
    },
    # Match calendar + results sync from API-Football (every 6h). No-op
    # unless API_FOOTBALL_KEY is set and categories are bound.
    "sync-api-football-fixtures": {
        "task": "events.tasks.sync_all_bound_category_fixtures",
        "schedule": crontab(minute=0, hour="*/6"),
    },
}
