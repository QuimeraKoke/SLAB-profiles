"""Celery tasks for dashboards — player metric-state recompute."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="dashboards.tasks.recompute_player_state")
def recompute_player_state(player_id: str) -> None:
    """Rebuild one player's materialized `PlayerMetricState` from raw data.
    Enqueued by the `post_save(ExamResult)` trigger (on commit) and runnable
    in bulk via `manage.py rebuild_player_state`."""
    from core.models import Player
    from .player_state import upsert_player_state

    player = Player.objects.filter(pk=player_id).select_related("category", "position").first()
    if player is None:
        logger.info("recompute_player_state: player %s not found (deleted?).", player_id)
        return
    upsert_player_state(player)


@shared_task(name="dashboards.tasks.snapshot_player_states")
def snapshot_player_states() -> dict:
    """Weekly history capture: recompute each active player's state fresh,
    then write today's `PlayerStateSnapshot` (one per player per day —
    idempotent). Scheduled in config/celery.py; the evolution charts read
    these snapshots."""
    from django.utils import timezone

    from core.models import Player
    from .models import PlayerStateSnapshot
    from .player_state import upsert_player_state

    today = timezone.now().date()
    n = 0
    for player in (
        Player.objects.filter(is_active=True).select_related("category", "position").iterator()
    ):
        st = upsert_player_state(player)
        PlayerStateSnapshot.objects.update_or_create(
            player=player, captured_on=today,
            defaults={"state": st.state, "version": st.version},
        )
        n += 1
    logger.info("snapshot_player_states: captured %s snapshots for %s", n, today)
    return {"snapshotted": n, "date": str(today)}


@shared_task(name="dashboards.tasks.recompute_readiness")
def recompute_readiness(player_id: str) -> dict | None:
    """Recompute + cache a player's agent-refined readiness (signature-gated,
    so an unchanged save is a cheap no-op). Triggered on ExamResult save and
    runnable in bulk via `manage.py rebuild_readiness`."""
    from core.models import Player
    from .readiness import compute_readiness

    player = (
        Player.objects.filter(pk=player_id, is_active=True)
        .select_related("category", "position").first()
    )
    if player is None:
        return None
    r = compute_readiness(player)
    return {"player": str(player_id), "score": r.score, "source": r.source}
