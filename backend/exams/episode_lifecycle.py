"""Episode lifecycle helpers for episodic exam templates.

The result-create endpoint calls `resolve_episode()` BEFORE persisting the
ExamResult to either continue an existing open episode or start a fresh
one. The `refresh_episode_from_results()` helper runs from the post-save
signal: it reads the latest linked result and recomputes the Episode's
`stage`, `status`, `title`, and `ended_at`. After updating the Episode,
`recompute_player_status()` walks the player's open episodes and caches
the worst stage on Player.status.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.utils import timezone

from .models import Episode, ExamResult, ExamTemplate


def resolve_episode(
    *,
    template: ExamTemplate,
    player,
    episode_id: Optional[str | "UUID"],  # noqa: F821
    recorded_at: datetime,
    user,
) -> Episode | None:
    """Returns the Episode this new result should link to.

    - Non-episodic template → returns None (caller stores result without an episode).
    - Episodic + episode_id provided → loads & validates that episode.
    - Episodic + no episode_id → creates a new open Episode.
    """
    if not template.is_episodic:
        return None

    if episode_id:
        ep = Episode.objects.filter(pk=episode_id).first()
        if ep is None:
            from ninja.errors import HttpError
            raise HttpError(404, "Episode not found.")
        if ep.player_id != player.id or ep.template_id != template.id:
            from ninja.errors import HttpError
            raise HttpError(400, "Episode does not match the result's player + template.")
        if ep.status == Episode.STATUS_CLOSED:
            from ninja.errors import HttpError
            raise HttpError(400, "Episode is closed; open a new episode instead.")
        return ep

    return Episode.objects.create(
        player=player,
        template=template,
        status=Episode.STATUS_OPEN,
        started_at=recorded_at,
        created_by=user if (user is not None and user.is_authenticated) else None,
    )


def _format_title(template: ExamTemplate, result_data: dict) -> str:
    """Render `episode_config.title_template` with values from result_data.

    Missing keys degrade to empty strings; the result is stripped to remove
    leading/trailing dashes and double-spaces. If no template is set or the
    render is empty, returns "".
    """
    cfg = template.episode_config or {}
    tpl = cfg.get("title_template") or ""
    if not tpl:
        return ""
    try:
        rendered = tpl.format(**{k: result_data.get(k, "") for k in _placeholders(tpl)})
    except (KeyError, IndexError, ValueError):
        return ""
    # Tidy: collapse double spaces and trim spurious " — " when fields are missing.
    rendered = " ".join(rendered.split())
    while rendered.startswith("—") or rendered.startswith("-"):
        rendered = rendered[1:].strip()
    while rendered.endswith("—") or rendered.endswith("-"):
        rendered = rendered[:-1].strip()
    return rendered


def _placeholders(template_str: str) -> list[str]:
    import re
    return re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template_str)


def refresh_episode_from_results(episode: Episode) -> None:
    """Recompute the Episode's derived fields from its latest linked result.

    No-op when the episode has no linked results (e.g. immediately after
    creation, before the first result is saved).
    """
    cfg = episode.template.episode_config or {}
    stage_field = cfg.get("stage_field")
    closed_stage = cfg.get("closed_stage")

    latest = (
        ExamResult.objects
        .filter(episode=episode)
        .order_by("-recorded_at")
        .first()
    )
    if latest is None:
        return

    new_stage = ""
    if stage_field:
        raw = (latest.result_data or {}).get(stage_field) or ""
        new_stage = str(raw).strip()

    is_closed = bool(new_stage and closed_stage and new_stage == closed_stage)

    new_title = _format_title(episode.template, latest.result_data or {})
    new_status = Episode.STATUS_CLOSED if is_closed else Episode.STATUS_OPEN
    new_ended_at = latest.recorded_at if is_closed else None

    update_fields: list[str] = []
    if episode.stage != new_stage:
        episode.stage = new_stage
        update_fields.append("stage")
    if new_title and episode.title != new_title:
        episode.title = new_title
        update_fields.append("title")
    if episode.status != new_status:
        episode.status = new_status
        update_fields.append("status")
    if episode.ended_at != new_ended_at:
        episode.ended_at = new_ended_at
        update_fields.append("ended_at")
    if update_fields:
        update_fields.append("updated_at")
        episode.save(update_fields=update_fields)


def recompute_player_status(player) -> None:
    """Walk the player's open episodes; cache the worst stage on Player.status."""
    from core.models import Player

    open_eps = (
        Episode.objects
        .filter(player=player, status=Episode.STATUS_OPEN)
        .select_related("template")
    )

    # Default = available (no open episodes).
    worst_status = Player.STATUS_AVAILABLE
    worst_rank = Player.STATUS_RANK[Player.STATUS_AVAILABLE]

    for ep in open_eps:
        cfg = ep.template.episode_config or {}
        open_stages = cfg.get("open_stages") or []
        if ep.stage not in open_stages:
            continue
        # Map the episode's stage to a canonical Player.STATUS_* value.
        mapped = _map_stage_to_player_status(ep.stage)
        rank = Player.STATUS_RANK.get(mapped)
        if rank is None:
            continue
        if rank < worst_rank:
            worst_rank = rank
            worst_status = mapped

    if player.status != worst_status:
        player.status = worst_status
        player.save(update_fields=["status"])


def _map_stage_to_player_status(stage: str) -> str:
    """Map an episode's stage onto the canonical Player.STATUS_* vocabulary.

    For v1 we expect episodic templates to use the shared vocabulary
    (`injured / recovery / reintegration / closed`). If a different stage
    name shows up, we treat it as the worst case ('injured') so the player
    isn't silently marked available while something is genuinely open.
    """
    from core.models import Player

    canon = {
        "injured": Player.STATUS_INJURED,
        "recovery": Player.STATUS_RECOVERY,
        "reintegration": Player.STATUS_REINTEGRATION,
    }
    return canon.get(stage, Player.STATUS_INJURED)
