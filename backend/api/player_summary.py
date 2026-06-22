"""Per-player season-summary cards for the Resumen S-LAB block.

Three deterministic cards that sit alongside the agent narrative on the
player Resumen tab:

  * estadisticas       — season match stats (EventParticipant + rendimiento)
  * rendimiento_fisico — match-GPS averages
  * reporte_medico     — current availability status + recent episodes

All-time over the player's matches (no date window) — the Resumen is a
career-in-the-system overview, matching the old season-recap cards. Each
builder degrades gracefully (zeros / nulls / empty) when a data source
isn't seeded, so the block always renders.
"""
from __future__ import annotations

from typing import Any

from core.models import Player, PlayerAlias
from events.models import Event, EventParticipant
from exams.models import Episode, ExamResult, ExamTemplate


def build_player_season_summary(player: Player) -> dict[str, Any]:
    """Assemble the three Resumen cards for `player`. Never raises."""
    return {
        "estadisticas": _season_match_stats(player),
        "rendimiento_fisico": _gps_averages(player),
        "reporte_medico": _medical(player),
    }


def _avg(values: list[Any]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    return (sum(nums) / len(nums)) if nums else None


def _active_template(slug: str, player: Player) -> ExamTemplate | None:
    """Resolve the active version of a template by slug, scoped to the
    player's club. Returns the active version (or any version) so the caller
    can fan out across the version family via `family_id`."""
    club = player.category.club if player.category_id else None
    qs = ExamTemplate.objects.filter(slug=slug)
    if club is not None:
        qs = qs.filter(department__club=club)
    return qs.order_by("-is_active_version", "-version").first()


def _season_match_stats(player: Player) -> dict[str, Any]:
    """Partidos jugados / minutos / goles / asistencias / amarillas / rojas.

    Primary source is `EventParticipant` (the authoritative box score). When a
    club records per-match performance on the `rendimiento_de_partido` exam
    instead — and EventParticipant carries no minutes — we fall back to those
    results. Totals are rounded to integers (some sources store synthetic
    fractional values; partial goals/minutes make no sense in a season tally)."""
    parts = list(
        EventParticipant.objects
        .filter(player=player, event__event_type=Event.TYPE_MATCH)
        .values_list("match_role", "minutes_played", "goals", "yellow_cards", "red_cards")
    )
    if any((p[1] or 0) > 0 for p in parts):
        return {
            "partidos_jugados": sum(1 for p in parts if (p[1] or 0) > 0),
            "minutos_totales": round(sum((p[1] or 0) for p in parts)),
            "goles": round(sum((p[2] or 0) for p in parts)),
            "asistencias": _sum_field(player, "assists"),
            "amarillas": round(sum((p[3] or 0) for p in parts)),
            "rojas": round(sum((p[4] or 0) for p in parts)),
        }
    return _season_stats_from_rendimiento(player)


def _season_stats_from_rendimiento(player: Player) -> dict[str, Any]:
    """Fallback box score from `rendimiento_de_partido` results (used when the
    club records performance on the exam rather than EventParticipant, e.g. the
    demo). All sums rounded to integers."""
    tpl = _active_template("rendimiento_de_partido", player)
    if tpl is None:
        return {
            "partidos_jugados": 0, "minutos_totales": 0, "goles": 0,
            "asistencias": None, "amarillas": 0, "rojas": 0,
        }
    rows = list(
        ExamResult.objects
        .filter(player=player, template__family_id=tpl.family_id)
        .values_list("result_data", flat=True)
    )

    def s(key: str) -> float:
        return sum(
            (rd or {}).get(key) or 0
            for rd in rows
            if isinstance((rd or {}).get(key), (int, float))
        )

    return {
        "partidos_jugados": sum(1 for rd in rows if ((rd or {}).get("minutes_played") or 0) > 0),
        "minutos_totales": round(s("minutes_played")),
        "goles": round(s("goals")),
        "asistencias": round(s("assists")),
        "amarillas": round(s("yellow_cards")),
        "rojas": round(s("red_card")),
    }


def _sum_field(player: Player, key: str) -> int | None:
    """Rounded sum of a numeric field across the player's match-performance
    results. Returns None when the template/field isn't present so the UI can
    show '—' rather than a misleading 0."""
    tpl = _active_template("rendimiento_de_partido", player)
    if tpl is None:
        return None
    total = 0.0
    found = False
    for rd in ExamResult.objects.filter(
        player=player, template__family_id=tpl.family_id,
    ).values_list("result_data", flat=True):
        v = (rd or {}).get(key)
        if isinstance(v, (int, float)):
            total += v
            found = True
    return round(total) if found else None


def _gps_averages(player: Player) -> dict[str, Any]:
    """Per-match GPS averages over `gps_rendimiento_fisico_de_partido`."""
    tpl = _active_template("gps_rendimiento_fisico_de_partido", player)
    if tpl is None:
        return {"partidos_con_gps": 0}
    rows = list(
        ExamResult.objects
        .filter(player=player, template__family_id=tpl.family_id)
        .values_list("result_data", flat=True)
    )

    def col(key: str) -> float | None:
        return _avg([(r or {}).get(key) for r in rows])

    return {
        "partidos_con_gps": len(rows),
        "distancia_promedio": col("tot_dist_total"),
        "v_max_promedio": col("max_vel_total"),
        "hiaa_promedio": col("hiaa_total"),
        "hmld_promedio": col("hmld_total"),
        "aceleraciones_promedio": col("acc_dec_total") if col("acc_dec_total") is not None else col("acc_total"),
    }


def _medical(player: Player, limit: int = 3) -> dict[str, Any]:
    """Current availability status + the most recent episodes (open or closed,
    newest first) with their stage/status for the badge."""
    episodes = list(
        Episode.objects
        .filter(player=player)
        .select_related("template")
        .order_by("-started_at")[:limit]
    )
    return {
        "player_status": player.status,
        "player_status_label": player.get_status_display(),
        "episodes": [
            {
                "id": str(e.id),
                "title": e.title or e.template.name,
                "stage": e.stage,
                "status": e.status,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "ended_at": e.ended_at.isoformat() if e.ended_at else None,
            }
            for e in episodes
        ],
    }


def player_squad_number(player: Player) -> str | None:
    """The player's jersey number, stored as a `squad_number` alias (may be
    absent). Returns the most recent alias value or None."""
    alias = (
        PlayerAlias.objects
        .filter(player=player, kind=PlayerAlias.KIND_SQUAD_NUMBER)
        .order_by("-created_at")
        .first()
    )
    return alias.value if alias else None
