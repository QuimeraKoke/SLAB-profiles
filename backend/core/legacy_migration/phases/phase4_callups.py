"""Phase 4 — `citaciones` + `estadistica_interna` → EventParticipant.

For every 2025+ partido we imported in phase 3, walk its citaciones
rows and create one EventParticipant per (event, player). The match
role comes from `citaciones.estado`; basic stats (minutos, goles,
yellow_cards, red_cards) come from `estadistica_interna` looked up by
`citaciones_id`.

`absence_reason` is also derived here when possible:
  - `lesionado` → JOIN against the legacy `lesion` table to find the
    injury active on the match date; copy its `diagnostico` (falling
    back to `tipo_lesion @ parte_lesionada` if `diagnostico` is null).
  - `suspendido` / `seleccion` / `citado_no_vestir` → fixed default
    Spanish labels so the convocatoria UI shows context-aware text.

Also populates `ctx.citacion_lookup` so phase 6 can resolve the 3,241
legacy `evaluacion_partido` rows that lost their FKs in 2025+ but
still carry `citacion_id`.
"""
from __future__ import annotations

from datetime import date as _date

from django.db import transaction

from events.models import EventParticipant

from ..mapping import fix_mojibake, jsonable, map_citation_status
from .context import MigrationContext


# Default human-readable absence reasons when the legacy data doesn't
# carry a richer text. Lesionado is handled separately by joining the
# `lesion` table — see _build_injury_lookup().
_DEFAULT_REASON_BY_ROLE = {
    "suspendido":       "Suspendido (importado del sistema legacy)",
    "seleccion":        "Convocado a Selección (importado del sistema legacy)",
    "citado_no_vestir": "Citado sin vestir (importado del sistema legacy)",
    "promovido":        "Promovido desde categoría inferior (importado del sistema legacy)",
}


def _bootstrap_lookups_from_db(ctx: MigrationContext) -> None:
    """Rebuild player_by_legacy_id + event_by_legacy_id from existing
    `legacy_raw._source_pk` columns when those maps are empty. Mirrors
    the helper in phase6_results — enables `--entities=phase4` to run
    in isolation for backfills."""
    from core.models import Player
    from events.models import Event

    if not ctx.player_by_legacy_id:
        rebuilt = 0
        for p in Player.objects.filter(legacy_raw__has_key="_source_pk"):
            pk = (p.legacy_raw or {}).get("_source_pk")
            if pk is not None:
                ctx.player_by_legacy_id[int(pk)] = str(p.id)
                rebuilt += 1
        ctx.audit.info(f"phase4_callups: bootstrapped player lookup ({rebuilt} entries)")

    if not ctx.event_by_legacy_id:
        rebuilt = 0
        for ev in Event.objects.filter(
            event_type=Event.TYPE_MATCH, legacy_raw__has_key="_source_pk",
        ):
            pk = (ev.legacy_raw or {}).get("_source_pk")
            if pk is not None:
                ctx.event_by_legacy_id[int(pk)] = str(ev.id)
                rebuilt += 1
        ctx.audit.info(f"phase4_callups: bootstrapped event lookup ({rebuilt} entries)")


def run(ctx: MigrationContext) -> None:
    ctx.audit.info("phase4_callups: start")
    _bootstrap_lookups_from_db(ctx)

    if not ctx.event_by_legacy_id:
        ctx.audit.warn(
            "phase4_callups: no events were imported in phase 3 — skipping",
        )
        return

    # Load estadistica_interna keyed by citaciones_id. The 2025 chunk
    # has 5,083 rows (legacy stores minutos/goles/cards per call-up
    # rather than per evaluacion_partido).
    stats_by_citacion: dict[int, dict] = {}
    for r in ctx.legacy_db.iter_rows(
        "SELECT * FROM estadistica_interna WHERE citaciones_id IS NOT NULL"
    ):
        stats_by_citacion[r["citaciones_id"]] = r

    # Pre-load every injury (lesion) row keyed by jugador_id. We'll
    # search per-citation for an injury active on the match date.
    # See _build_injury_lookup() for the in-memory data shape.
    injuries_by_player = _build_injury_lookup(ctx)

    # Pre-load partido dates so we can resolve injury overlap without
    # a second query per citation. Keyed by legacy partido_id.
    partido_dates: dict[int, _date] = {}
    for r in ctx.legacy_db.iter_rows(
        "SELECT id_partido, fecha_partido FROM partido"
    ):
        partido_dates[r["id_partido"]] = r["fecha_partido"]

    # Pull citaciones for the partidos we imported in scope.
    partido_ids = list(ctx.event_by_legacy_id.keys())

    if not partido_ids:
        ctx.audit.warn("phase4_callups: no partido ids to query — aborting")
        return

    placeholders = ",".join(["%s"] * len(partido_ids))
    rows = ctx.legacy_db.fetch_all(
        f"SELECT * FROM citaciones WHERE partido_id IN ({placeholders})",
        tuple(partido_ids),
    )

    for row in rows:
        try:
            _import_one_citacion(
                ctx, row, stats_by_citacion,
                injuries_by_player, partido_dates,
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(
                phase="phase4",
                action="failed",
                source_table="citaciones",
                source_pk=row.get("id_citaciones"),
                reason=f"{type(exc).__name__}: {exc}",
            )

    ctx.audit.info("phase4_callups: done", citaciones=len(rows))


def _build_injury_lookup(ctx: MigrationContext) -> dict[int, list[dict]]:
    """Pre-load every injury row into a per-player list, sorted newest
    first. Tiny table (~hundreds of rows) so we keep it all in memory
    and let `_describe_injury()` linearly scan the (small) per-player
    list to find the one active on a given match date."""
    out: dict[int, list[dict]] = {}
    for r in ctx.legacy_db.iter_rows(
        "SELECT id_lesion, jugador_id, fecha_lesion, fecha_alta, "
        "       tipo_lesion, parte_lesionada, lateralidad, diagnostico "
        "  FROM lesion"
    ):
        pid = r.get("jugador_id")
        if pid is None or r.get("fecha_lesion") is None:
            continue
        out.setdefault(pid, []).append(r)
    # Sort per-player lists newest first so the first matching injury
    # is the most recent one (in case of overlapping ranges).
    for lst in out.values():
        lst.sort(key=lambda r: r["fecha_lesion"], reverse=True)
    return out


def _describe_injury(
    injuries: list[dict],
    on_date: _date | None,
) -> str:
    """Return a compact human label of the injury active on `on_date`,
    or `""` if none. Falls back to `tipo_lesion @ parte_lesionada` when
    `diagnostico` is empty."""
    if on_date is None or not injuries:
        return ""
    for inj in injuries:
        start = inj["fecha_lesion"]
        end = inj.get("fecha_alta")  # nullable — open injury
        if start <= on_date and (end is None or on_date <= end):
            diag = fix_mojibake(inj.get("diagnostico") or "")
            if diag:
                return diag[:200]
            tipo = fix_mojibake(inj.get("tipo_lesion") or "")
            parte = fix_mojibake(inj.get("parte_lesionada") or "")
            lat = fix_mojibake(inj.get("lateralidad") or "")
            parts = [p for p in [tipo, parte, lat] if p]
            return " · ".join(parts)[:200] if parts else "Lesión activa"
    return ""


def _import_one_citacion(
    ctx: MigrationContext,
    row: dict,
    stats_by_citacion: dict[int, dict],
    injuries_by_player: dict[int, list[dict]] | None = None,
    partido_dates: dict[int, _date] | None = None,
) -> None:
    legacy_id = row["id_citaciones"]
    partido_id = row["partido_id"]
    jugador_id = row["jugador_id"]

    # Always populate the lookup map (used by phase 6).
    ctx.citacion_lookup[legacy_id] = (partido_id, jugador_id)

    event_uuid = ctx.event_by_legacy_id.get(partido_id)
    player_uuid = ctx.player_by_legacy_id.get(jugador_id)

    if not event_uuid:
        ctx.audit.record(
            phase="phase4",
            action="skipped",
            source_table="citaciones",
            source_pk=legacy_id,
            reason=f"event for partido_id={partido_id} not imported",
        )
        return

    if not player_uuid:
        ctx.audit.record(
            phase="phase4",
            action="skipped",
            source_table="citaciones",
            source_pk=legacy_id,
            reason=f"player jugador_id={jugador_id} not in active set",
        )
        return

    match_role = map_citation_status(row.get("estado"))
    if match_role is None:
        # Unknown estado — keep the row but mark as no_citado + log so
        # the medical/coaching staff can fix the source row.
        ctx.audit.warn(
            "phase4_callups: unmapped estado, defaulting to no_citado",
            estado=row.get("estado"),
            id_citaciones=legacy_id,
        )
        match_role = "no_citado"

    position_played_id = ctx.position_by_legacy_id.get(row.get("posicion_id"))
    if ctx.dry_run:
        # Don't pass placeholder FKs to the (skipped) ORM call.
        position_played_id = None

    stats = stats_by_citacion.get(legacy_id, {})

    legacy_raw = jsonable({
        "_source_table": "citaciones",
        "_source_pk": legacy_id,
        "_source_row": row,
        "_estadistica_interna": stats or None,
    })

    # Build the absence reason. For Lesionado, query the legacy
    # injury table for an overlapping row and copy the diagnosis.
    # For the other absence states use the generic default.
    absence_reason = ""
    if match_role == "lesionado" and injuries_by_player and partido_dates:
        match_date = partido_dates.get(partido_id)
        absence_reason = _describe_injury(
            injuries_by_player.get(jugador_id, []),
            match_date,
        )
        if not absence_reason:
            absence_reason = _DEFAULT_REASON_BY_ROLE.get(match_role, "")
    elif match_role in _DEFAULT_REASON_BY_ROLE:
        absence_reason = _DEFAULT_REASON_BY_ROLE[match_role]

    fields = {
        "event_id": event_uuid,
        "player_id": player_uuid,
        "attendance": EventParticipant.Attendance.ATTENDED
            if match_role in ("titular", "suplente_ingresa")
            else EventParticipant.Attendance.SCHEDULED,
        "match_role": match_role,
        "absence_reason": absence_reason,
        "position_played_id": position_played_id,
        "external_id": legacy_id,
        "legacy_raw": legacy_raw,
    }
    # Merge per-match basic stats only for rows that actually played.
    if match_role in ("titular", "suplente_ingresa") and stats:
        fields.update({
            "minutes_played": _as_int(stats.get("minutos")),
            "goals": _as_int(stats.get("goles")),
            "yellow_cards": _as_int(stats.get("amarillas")),
            "red_cards": _as_int(stats.get("rojas")),
        })

    if ctx.dry_run:
        ctx.audit.record(
            phase="phase4",
            action="created",   # dry-run can't distinguish — mark as created
            source_table="citaciones",
            source_pk=legacy_id,
            target_model="events.EventParticipant",
            reason="dry-run",
        )
        return

    # Idempotent upsert keyed on (event, player) — that's the
    # `unique_together` on EventParticipant.
    existing = EventParticipant.objects.filter(
        event_id=event_uuid, player_id=player_uuid,
    ).first()

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        with transaction.atomic():
            existing.save()
        target_pk = str(existing.id)
        action = "updated"
    else:
        with transaction.atomic():
            ep = EventParticipant.objects.create(**fields)
        target_pk = str(ep.id)
        action = "created"

    ctx.audit.record(
        phase="phase4",
        action=action,
        source_table="citaciones",
        source_pk=legacy_id,
        target_model="events.EventParticipant",
        target_pk=target_pk,
    )


def _as_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
