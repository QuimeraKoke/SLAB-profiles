"""Scheduled wellness Check-IN sync (Google Sheet → ExamResults).

Beat fires `sync_wellness_responses` frequently during the morning check-in
window and less often off-peak (see config/celery.py). Each run pulls the form
responses, feeds them through the shared `wellness_ingest` pipeline, and
upserts molestia alerts. A Redis lock prevents overlapping runs from stacking.

No-ops cleanly (logs + returns) when the sheet/credentials aren't configured,
so the schedule is safe to ship before the club wires its own Google key.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

_LOCK_KEY = "lock:sync_wellness_responses"
_LOCK_TTL = 240  # seconds — longer than a normal run, shorter than the 5-min tick


@shared_task(name="exams.tasks.sync_wellness_responses")
def sync_wellness_responses(mode: str = "today", since_days: int = 3) -> dict:
    """Pull wellness form responses and ingest them.

    mode: "today" (frequent ticks) | "reconcile" (daily catch-up of the last
    `since_days`) | "all" (full backfill).
    """
    from core.models import Category
    from exams.models import ExamTemplate
    from exams.wellness_ingest import WELLNESS_SLUG, ingest_wellness
    from integrations.google_sheets import GoogleSheetsError, fetch_rows

    sheet_id = settings.WELLNESS_SHEET_ID
    creds_file = settings.GOOGLE_SHEETS_CREDENTIALS_FILE
    creds_json = settings.GOOGLE_SHEETS_CREDENTIALS_JSON
    if not sheet_id or not (creds_file or creds_json):
        logger.info("wellness sync skipped: WELLNESS_SHEET_ID / credentials not set")
        return {"status": "skipped", "reason": "not configured"}

    # Best-effort cross-run lock (skip if a previous run is still going).
    lock = None
    try:
        from django.core.cache import cache
        lock = cache
        if not cache.add(_LOCK_KEY, "1", _LOCK_TTL):
            logger.info("wellness sync skipped: another run holds the lock")
            return {"status": "skipped", "reason": "locked"}
    except Exception:  # pragma: no cover — cache backend unavailable
        lock = None

    try:
        category = (
            Category.objects.filter(
                name=settings.WELLNESS_CATEGORY, club__name=settings.WELLNESS_CLUB,
            ).select_related("club").first()
        )
        if category is None:
            logger.warning("wellness sync: category %r / club %r not found",
                           settings.WELLNESS_CATEGORY, settings.WELLNESS_CLUB)
            return {"status": "error", "reason": "category not found"}
        template = ExamTemplate.objects.filter(
            slug=WELLNESS_SLUG, department__club=category.club,
        ).first()
        if template is None:
            logger.warning("wellness sync: template %r not found", WELLNESS_SLUG)
            return {"status": "error", "reason": "template not found"}

        try:
            rows = fetch_rows(
                sheet_id, settings.WELLNESS_SHEET_WORKSHEET,
                creds_file=creds_file, creds_json=creds_json,
            )
        except GoogleSheetsError as exc:
            logger.error("wellness sync: %s", exc)
            return {"status": "error", "reason": str(exc)}

        report = ingest_wellness(
            rows, template=template, category=category,
            mode=mode, since_days=since_days,
        )
        logger.info("wellness sync (%s): %s", mode, report)
        return {"status": "ok", "mode": mode, **report}
    finally:
        if lock is not None:
            try:
                lock.delete(_LOCK_KEY)
            except Exception:  # pragma: no cover
                pass


@shared_task(name="exams.tasks.sync_all_vald_clubs")
def sync_all_vald_clubs(full: bool = False) -> list[dict]:
    """Scheduled VALD Hub sync for every club with an enabled integration.

    No-ops cleanly when nothing is bound / no credentials are configured, so
    the beat schedule is safe to ship before a club wires its VALD keys.
    """
    from exams.models import ValdIntegration

    if not ValdIntegration.objects.filter(enabled=True).exists():
        logger.info("VALD sync skipped: no enabled integrations.")
        return []
    from exams.services.vald_sync import sync_all_bound_clubs

    reports = sync_all_bound_clubs(full=full)
    logger.info("VALD sync: %s", reports)
    return reports
