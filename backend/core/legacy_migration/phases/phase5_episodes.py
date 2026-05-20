"""Phase 5 — lesiones → Episode + ExamResult.

Each legacy `lesion` row becomes ONE Episode + ONE ExamResult linked
to the SLAB `lesiones` template. The Episode is the lifecycle anchor
(player + status + started_at + ended_at), the ExamResult holds the
clinical details (body_part, type, severity, etc.) in `result_data`.

Field mapping is in `mapping.py` — `tipo_lesion`/`parte_lesionada`/
`lateralidad` all get accent + casing normalisation before lookup.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction

from exams.models import Episode, ExamTemplate, ExamResult

from ..mapping import (
    fix_mojibake,
    infer_lesion_severity,
    jsonable,
    map_lesion_body_part,
    map_lesion_causa,
    map_lesion_exposicion,
    map_lesion_stage,
    map_lesion_tratamiento,
    map_lesion_type,
    normalize_lateralidad,
)
from .context import MigrationContext


_TZ = ZoneInfo("America/Santiago")


def run(ctx: MigrationContext) -> None:
    ctx.audit.info("phase5_episodes: start")

    template = ExamTemplate.objects.filter(
        slug="lesiones", department__club=ctx.club, is_active_version=True,
    ).first()
    if template is None:
        ctx.audit.warn("phase5_episodes: 'lesiones' template not found — aborting")
        return

    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM lesion WHERE fecha_lesion >= %s AND fecha_lesion <= %s",
        (ctx.date_from, ctx.date_to),
    )
    for row in rows:
        try:
            _import_one_lesion(ctx, row, template)
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(
                phase="phase5",
                action="failed",
                source_table="lesion",
                source_pk=row.get("id_lesion"),
                reason=f"{type(exc).__name__}: {exc}",
            )

    ctx.audit.info("phase5_episodes: done", count=len(rows))


def _import_one_lesion(ctx: MigrationContext, row: dict, template: ExamTemplate) -> None:
    legacy_id = row["id_lesion"]
    player_uuid = ctx.player_by_legacy_id.get(row.get("jugador_id"))

    if not player_uuid:
        ctx.audit.record(
            phase="phase5",
            action="skipped",
            source_table="lesion",
            source_pk=legacy_id,
            reason=f"player jugador_id={row.get('jugador_id')} not in active set",
        )
        return

    started_at = datetime.combine(row["fecha_lesion"], time(10, 0), tzinfo=_TZ)
    ended_at = (
        datetime.combine(row["fecha_alta"], time(10, 0), tzinfo=_TZ)
        if row.get("fecha_alta") else None
    )

    stage = map_lesion_stage(row.get("estado"), row.get("fecha_alta"))

    # Build result_data with the SLAB lesiones template's field keys.
    result_data: dict[str, Any] = {
        "diagnosed_at": row["fecha_lesion"].isoformat(),
        "type": map_lesion_type(row.get("tipo_lesion")),
        "body_part": map_lesion_body_part(
            row.get("parte_lesionada"), row.get("lateralidad"),
        ),
        # body_part_detail keeps the muscle + free-form diagnostic so
        # nothing is lost when the categorical maps don't cover it.
        "body_part_detail": _build_body_part_detail(row),
        "severity": infer_lesion_severity(row.get("dias_perdidos_por_lesion")),
        "stage": stage,
        "expected_return_date": None,    # legacy has no separate forecast
        "actual_return_date": row["fecha_alta"].isoformat() if row.get("fecha_alta") else None,
        # Extended fields we added in the lesiones seed (phase 2).
        "causa": map_lesion_causa(row.get("causa")),
        "exposicion": map_lesion_exposicion(row.get("exposicion")),
        "tratamiento": map_lesion_tratamiento(row.get("tratamiento")),
        "is_recurrencia": bool(row.get("is_recurrencia")) if row.get("is_recurrencia") is not None else None,
        "dias_perdidos": row.get("dias_perdidos_por_lesion"),
        "partidos_perdidos": row.get("num_partidos"),
        "notes": fix_mojibake(row.get("diagnostico") or "") or "",
    }
    # Drop None values so they don't show as 'null' in the UI.
    result_data = {k: v for k, v in result_data.items() if v is not None}

    legacy_raw = jsonable({
        "_source_table": "lesion",
        "_source_pk": legacy_id,
        "_source_row": row,
    })

    if ctx.dry_run:
        ctx.audit.record(
            phase="phase5",
            action="created",
            source_table="lesion",
            source_pk=legacy_id,
            target_model="exams.Episode+ExamResult",
            reason="dry-run",
        )
        return

    # Idempotent: re-find the Episode + result via legacy_raw.
    existing_episode = Episode.objects.filter(
        legacy_raw__contains={"_source_table": "lesion", "_source_pk": legacy_id},
    ).first()

    if existing_episode:
        existing_episode.status = (
            Episode.STATUS_OPEN if stage == "injured" else Episode.STATUS_CLOSED
        )
        existing_episode.stage = stage
        existing_episode.started_at = started_at
        existing_episode.ended_at = ended_at
        existing_episode.legacy_raw = legacy_raw
        with transaction.atomic():
            existing_episode.save()
        episode = existing_episode
        action = "updated"
    else:
        with transaction.atomic():
            episode = Episode.objects.create(
                player_id=player_uuid,
                template=template,
                status=(
                    Episode.STATUS_OPEN if stage == "injured" else Episode.STATUS_CLOSED
                ),
                stage=stage,
                title=_build_title(result_data),
                started_at=started_at,
                ended_at=ended_at,
                legacy_raw=legacy_raw,
            )
        action = "created"

    # Now the linked ExamResult.
    existing_result = ExamResult.objects.filter(episode=episode).first()
    er_fields = dict(
        player_id=player_uuid,
        template=template,
        recorded_at=started_at,
        result_data=result_data,
        episode=episode,
        legacy_raw=legacy_raw,
    )
    if existing_result:
        for k, v in er_fields.items():
            setattr(existing_result, k, v)
        with transaction.atomic():
            existing_result.save()
    else:
        with transaction.atomic():
            ExamResult.objects.create(**er_fields)

    ctx.audit.record(
        phase="phase5",
        action=action,
        source_table="lesion",
        source_pk=legacy_id,
        target_model="exams.Episode",
        target_pk=str(episode.id),
    )


def _build_body_part_detail(row: dict) -> str:
    """Combine legacy `musculo` (specific muscle) + lateralidad + raw
    parte_lesionada as a free-text fallback so the SLAB UI keeps the
    full context even when the SLAB body_part option doesn't quite
    match."""
    parts: list[str] = []
    if row.get("musculo"):
        parts.append(fix_mojibake(row["musculo"]))
    lat = normalize_lateralidad(row.get("lateralidad"))
    if lat:
        parts.append(lat)
    raw_parte = fix_mojibake(row.get("parte_lesionada") or "")
    if raw_parte and raw_parte not in parts:
        parts.append(raw_parte)
    return " · ".join(p for p in parts if p)


def _build_title(result_data: dict) -> str:
    """Format the Episode title — used by the SLAB UI on cards and lists."""
    bp = result_data.get("body_part") or result_data.get("body_part_detail") or ""
    typ = result_data.get("type") or ""
    return " — ".join([typ, bp]).strip(" —") or "Lesión"
