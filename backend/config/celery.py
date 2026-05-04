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


# Beat schedule: a single daily tick that evaluates due goals.
# 05:00 server-time gives the doctor a fresh batch of overnight checks
# before a typical morning briefing.
app.conf.beat_schedule = {
    "evaluate-due-goals-daily": {
        "task": "goals.tasks.evaluate_due_goals",
        "schedule": crontab(hour=5, minute=0),
    },
}
