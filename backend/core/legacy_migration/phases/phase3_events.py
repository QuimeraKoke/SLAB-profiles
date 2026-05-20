"""Phase 3 — Event import (matches from `partido`).

Legacy `partido` → `events.Event(event_type='match')`. Future-dated
rows (scheduled matches up to Dec 2026) are imported verbatim — the
client uses the schedule as a planning tool.

Department assignment is `Táctico` (the dept that owns
rendimiento_de_partido). Pre-built lookups for equipo (opponent name)
and competicion_temporada (label) come from the legacy reference
tables and live on `Event.metadata`."""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction

from events.models import Event

from ..mapping import fix_mojibake, jsonable
from .context import MigrationContext, dry_uuid


_TZ_LOCAL = ZoneInfo("America/Santiago")


def run(ctx: MigrationContext) -> None:
    ctx.audit.info("phase3_events: start")

    equipo_lookup = _load_equipo_lookup(ctx)
    competicion_lookup = _load_competicion_lookup(ctx)

    department = ctx.get_department("tactico")

    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM partido "
        " WHERE fecha_partido >= %s AND fecha_partido <= %s "
        " ORDER BY fecha_partido, id_partido",
        (ctx.date_from, ctx.date_to),
    )

    for row in rows:
        try:
            _import_one_partido(ctx, row, equipo_lookup, competicion_lookup, department)
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(
                phase="phase3",
                action="failed",
                source_table="partido",
                source_pk=row.get("id_partido"),
                reason=f"{type(exc).__name__}: {exc}",
            )

    ctx.audit.info("phase3_events: done", count=len(rows))


def _import_one_partido(
    ctx: MigrationContext,
    row: dict,
    equipo_lookup: dict[int, str],
    competicion_lookup: dict[int, str],
    department,
) -> None:
    legacy_id = row["id_partido"]
    fecha = row.get("fecha_partido")
    if not fecha:
        ctx.audit.record(
            phase="phase3", action="skipped",
            source_table="partido", source_pk=legacy_id,
            reason="row missing fecha_partido",
        )
        return

    # Convert legacy date → SLAB datetime (Chile local 15:00 default
    # kickoff when no specific time is recorded).
    starts_at = datetime.combine(fecha, time(15, 0), tzinfo=_TZ_LOCAL)

    local = fix_mojibake(equipo_lookup.get(row.get("equipo_local_id"), "")) or ""
    visita = fix_mojibake(equipo_lookup.get(row.get("equipo_visita_id"), "")) or ""
    competition = fix_mojibake(competicion_lookup.get(row.get("competicion_temporada_id"), "")) or ""

    title_parts: list[str] = []
    if local and visita:
        title_parts.append(f"{local} vs {visita}")
    elif row.get("nombre_evento"):
        title_parts.append(fix_mojibake(row["nombre_evento"]))
    if row.get("jornada"):
        title_parts.append(f"({row['jornada']})")
    title = " ".join(title_parts) or f"Partido #{legacy_id}"

    metadata: dict[str, Any] = {
        "external_id": legacy_id,
        "equipo_local": local,
        "equipo_visita": visita,
        "competition_label": competition,
        "jornada": row.get("jornada") or "",
        "abbreviation": row.get("nombre_evento_abreviado") or "",
        "is_home": row.get("is_local"),
        "is_won": row.get("is_won"),
        "score": {
            "local": row.get("goles_local"),
            "visita": row.get("goles_visita"),
        },
    }

    legacy_raw = jsonable({
        "_source_table": "partido",
        "_source_pk": legacy_id,
        "_source_row": row,
    })

    existing = Event.objects.filter(
        legacy_raw__contains={"_source_table": "partido", "_source_pk": legacy_id},
    ).first()

    if ctx.dry_run:
        ctx.audit.record(
            phase="phase3",
            action="updated" if existing else "created",
            source_table="partido", source_pk=legacy_id,
            target_model="events.Event",
            target_pk=str(existing.id) if existing else None,
            reason="dry-run",
        )
        ctx.event_by_legacy_id[legacy_id] = (
            str(existing.id) if existing else dry_uuid("event", legacy_id)
        )
        return

    if existing:
        existing.title = title[:140]
        existing.starts_at = starts_at
        existing.metadata = metadata
        existing.legacy_raw = legacy_raw
        with transaction.atomic():
            existing.save()
        ev = existing
        action = "updated"
    else:
        with transaction.atomic():
            ev = Event.objects.create(
                club=ctx.club,
                department=department,
                event_type=Event.TYPE_MATCH,
                scope=Event.SCOPE_CATEGORY,
                title=title[:140],
                starts_at=starts_at,
                metadata=metadata,
                legacy_raw=legacy_raw,
            )
        action = "created"

    ctx.event_by_legacy_id[legacy_id] = str(ev.id)
    ctx.audit.record(
        phase="phase3",
        action=action,
        source_table="partido", source_pk=legacy_id,
        target_model="events.Event", target_pk=str(ev.id),
    )


# --- Reference lookups: equipo + competicion_temporada ----------------


def _load_equipo_lookup(ctx: MigrationContext) -> dict[int, str]:
    """Build {id_equipo: nombre}. Rival clubs; used only for match metadata."""
    return {
        r["id_equipo"]: r["nombre"]
        for r in ctx.legacy_db.iter_rows("SELECT id_equipo, nombre FROM equipo")
    }


def _load_competicion_lookup(ctx: MigrationContext) -> dict[int, str]:
    """Resolve competicion_temporada_id → 'Competición · Temporada'. Joins
    the competicion + temporada tables since legacy stores them as
    separate references."""
    sql = """
        SELECT ct.id_competicion_temporada AS id,
               COALESCE(c.nombre, '') AS comp,
               COALESCE(t.nombre, '') AS temp
          FROM competicion_temporada ct
          LEFT JOIN competicion c ON c.id_competicion = ct.competicion_id
          LEFT JOIN temporada   t ON t.id_temporada   = ct.temporada_id
    """
    out: dict[int, str] = {}
    for r in ctx.legacy_db.iter_rows(sql):
        label = " · ".join(p for p in [r["comp"], r["temp"]] if p)
        out[r["id"]] = label or f"#{r['id']}"
    return out
