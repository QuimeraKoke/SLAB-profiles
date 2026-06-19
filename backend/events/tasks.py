"""Celery tasks for the events app."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def sync_all_bound_category_fixtures(
    with_stats: bool = True, stats_limit: int = 20,
) -> list[dict]:
    """Scheduled fixture + results sync for every category bound to
    API-Football. Wired into the beat schedule (every 6h). Safe no-op when
    no API_FOOTBALL_KEY / no bound categories.

    `stats_limit` defaults to 20 so a scheduled run stays well under the
    free tier's 100 req/day (20 matches × 4 calls) while the backlog of
    completed-match tactical data fills in over successive runs."""
    from django.conf import settings

    if not (getattr(settings, "API_FOOTBALL_KEY", "") or "").strip():
        logger.info("sync_all_bound_category_fixtures: no API_FOOTBALL_KEY; skipping.")
        return []
    from events.services.fixtures_sync import sync_all_bound_categories

    return sync_all_bound_categories(with_stats=with_stats, stats_limit=stats_limit)
