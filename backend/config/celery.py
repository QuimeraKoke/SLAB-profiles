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
    # AI recap of the day that just ended (00:00 local). Pre-warms the saved
    # DailySummary so the morning Daily shows it instantly; lazy on-demand
    # generation covers any other day when first viewed. Uses DAILY_SUMMARY_MODEL
    # (Haiku); no-op if ANTHROPIC_API_KEY is unset.
    "generate-daily-summaries": {
        "task": "dashboards.tasks.generate_daily_summaries",
        "schedule": crontab(hour=0, minute=0),
    },
    # Alert hygiene: resolve alerts whose anchoring reading is >30 days old
    # (04:45, before the goal evaluator and the morning Daily).
    "expire-stale-alerts-daily": {
        "task": "goals.tasks.expire_stale_alerts",
        "schedule": crontab(hour=4, minute=45),
    },
    # Weekly player-state history capture (Mondays 04:00) → evolution charts.
    "snapshot-player-states-weekly": {
        "task": "dashboards.tasks.snapshot_player_states",
        "schedule": crontab(hour=4, minute=0, day_of_week=1),
    },
    # Daily player-state refresh (04:30) so the weekly chronic-load window ends
    # *today* even with no new ExamResult — fixes the stale "over-ceiling"
    # (sobreentrenamiento) flag lingering after rest days. Recompute only.
    "rebuild-player-states-daily": {
        "task": "dashboards.tasks.rebuild_player_states",
        "schedule": crontab(hour=4, minute=30),
    },
    # Match calendar + results sync from API-Football (every 6h). No-op
    # unless API_FOOTBALL_KEY is set and categories are bound.
    "sync-api-football-fixtures": {
        "task": "events.tasks.sync_all_bound_category_fixtures",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    # VALD Hub strength/dynamometry sync (ForceDecks/ForceFrame/NordBord →
    # ExamResults). Hourly at :30; each run is incremental — it only pulls data
    # modified since the last successful sync (per-product `sync_cursors` on the
    # ValdIntegration). No-op unless a club has an enabled integration + creds.
    "sync-vald-hub": {
        "task": "exams.tasks.sync_all_vald_clubs",
        "schedule": crontab(minute=30),
    },
    # Wellness Check-IN sync (Google Sheet → ExamResults). Hours are LOCAL
    # (CELERY_TIMEZONE). Frequent during the morning check-in window, relaxed
    # off-peak, plus a daily reconcile for late/edited responses. No-op unless
    # WELLNESS_SHEET_ID + credentials are configured.
    "wellness-sync-morning": {
        "task": "exams.tasks.sync_wellness_responses",
        "schedule": crontab(minute="*/5", hour="8-11"),     # 08:00–11:55, every 5 min
        "kwargs": {"mode": "today"},
    },
    "wellness-sync-offpeak": {
        "task": "exams.tasks.sync_wellness_responses",
        "schedule": crontab(minute="0,30", hour="0-7,12-23"),  # every 30 min otherwise
        "kwargs": {"mode": "today"},
    },
    "wellness-reconcile-daily": {
        "task": "exams.tasks.sync_wellness_responses",
        "schedule": crontab(minute=10, hour=13),            # 13:10 catch-up
        "kwargs": {"mode": "reconcile", "since_days": 3},
    },
}
