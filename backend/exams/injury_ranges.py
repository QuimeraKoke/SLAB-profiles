"""A player's injuries as date ranges, for drawing on time-axis charts.

Charts need less than the Lesiones tab does — when it started, when it ended,
and a one-line summary — but they need it for several players at once
(`/comparar`) and on every chart of a profile, so it is one query for the
episodes and one for their results, never one per episode like
`_serialize_episode`.

The summary is MERGED across the episode's results, oldest first with each
later non-empty value winning. Reading only the latest result would lose the
diagnosis on episodes updated by hand: a stage change carries the definition
forward, but an older manual follow-up may not.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from exams.models import Episode, ExamResult

SLUG = "lesiones"

# result_data key → summary key
CAMPOS = {
    "body_part": "body_part",
    "lado": "lado",
    "type": "type",
    "body_part_detail": "diagnosis",
    "severity": "severity",
    "dias_perdidos": "dias_perdidos",
    "recurrencia": "recurrencia",
}


def _label(template, field_key: str, value: Any) -> Any:
    """Display label of a categorical option (`Muneca` → `Muñeca`)."""
    for f in (template.config_schema or {}).get("fields") or []:
        if f.get("key") == field_key:
            return (f.get("option_labels") or {}).get(value, value)
    return value


def injury_ranges(episodes: Iterable[Episode]) -> list[dict[str, Any]]:
    from exams.episode_lifecycle import stage_label

    episodios = list(episodes)
    por_ep: dict = defaultdict(list)
    for r in (ExamResult.objects.filter(episode__in=episodios)
              .only("episode_id", "recorded_at", "result_data")
              .order_by("recorded_at")):
        por_ep[r.episode_id].append(r.result_data or {})

    salida = []
    for ep in episodios:
        resumen: dict[str, Any] = {}
        for datos in por_ep.get(ep.pk, []):
            for origen, destino in CAMPOS.items():
                v = datos.get(origen)
                if v not in (None, ""):
                    resumen[destino] = v
        for clave in ("body_part", "type", "severity", "lado"):
            if clave in resumen:
                resumen[clave] = _label(ep.template, clave, resumen[clave])
        abierta = ep.status == Episode.STATUS_OPEN
        fin: datetime | None = None if abierta else (ep.ended_at or ep.available_at)
        salida.append({
            "id": ep.pk,
            "player_id": ep.player_id,
            "player_name": f"{ep.player.first_name} {ep.player.last_name}".strip(),
            "status": ep.status,
            "stage_label": stage_label(ep.template, ep.stage) if abierta else "",
            "title": ep.title,
            "started_at": ep.started_at,
            "ended_at": fin,
            "summary": resumen,
        })
    return salida


def for_players(player_ids, templates_qs) -> list[dict[str, Any]]:
    qs = (Episode.objects
          .filter(player_id__in=list(player_ids), template__slug=SLUG,
                  template__in=templates_qs)
          .select_related("template", "player")
          .order_by("started_at"))
    return injury_ranges(qs)
