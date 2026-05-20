"""Phase 6 — bulk ExamResult import.

One importer per legacy table → SLAB template. Each follows the same
pattern: scope-filter the legacy rows, resolve `jugador_id` to a
SLAB Player, build `result_data`, create the `ExamResult`.

Tables covered (in scope-rowcount order):
    hoja_diaria          → hoja_diaria_medico   (~5,651)
    antropometria        → pentacompartimental  (~1,937)
    gps_partido          → gps_rendimiento_fisico_de_partido (~1,692)
    wellness             → check_in             (~1,095)
    examenes (CK rows)   → ck                   (~191)
    examenes (others)    → analisis_sangre      (~384, grouped by date)
    fase_densidad        → fase_densidad        (~532, grouped by date)
    medicamentos         → medicacion           (~460)
    evaluacion_partido   → rendimiento_de_partido (~3,241, citation lookup)
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction

from exams.models import ExamResult, ExamTemplate

from ..mapping import GPS_PERIOD_MAP, MEDICACION_TIPO_NORMALIZE, fix_mojibake, jsonable
from .context import MigrationContext


_TZ = ZoneInfo("America/Santiago")


def run(ctx: MigrationContext) -> None:
    ctx.audit.info("phase6_results: start")

    # Pre-resolve every template once. Skip a sub-phase when its
    # template isn't seeded (e.g. someone forgot to run the seed cmd).
    templates = {
        slug: ExamTemplate.objects.filter(
            slug=slug, department__club=ctx.club, is_active_version=True,
        ).first()
        for slug in (
            "hoja_diaria_medico", "pentacompartimental",
            "gps_rendimiento_fisico_de_partido", "check_in",
            "ck", "analisis_sangre", "fase_densidad",
            "medicacion", "rendimiento_de_partido",
        )
    }
    for slug, t in templates.items():
        if t is None:
            ctx.audit.warn(f"phase6_results: template '{slug}' not seeded — that sub-phase will skip")

    _import_hoja_diaria(ctx, templates["hoja_diaria_medico"])
    _import_antropometria(ctx, templates["pentacompartimental"])
    _import_gps_partido(ctx, templates["gps_rendimiento_fisico_de_partido"])
    _import_wellness(ctx, templates["check_in"])
    _import_ck(ctx, templates["ck"])
    _import_analisis_sangre(ctx, templates["analisis_sangre"])
    _import_fase_densidad(ctx, templates["fase_densidad"])
    _import_medicamentos(ctx, templates["medicacion"])
    _import_evaluacion_partido(ctx, templates["rendimiento_de_partido"])

    ctx.audit.info("phase6_results: done")


# --- generic helpers --------------------------------------------------


def _upsert_result(
    ctx: MigrationContext,
    source_table: str, source_pk: Any,
    template: ExamTemplate,
    player_legacy_id: int,
    recorded_at: datetime,
    result_data: dict,
    event_legacy_id: int | None = None,
    extra_legacy: dict | None = None,
):
    player_uuid = ctx.player_by_legacy_id.get(player_legacy_id)
    if not player_uuid:
        ctx.audit.record(
            phase="phase6", action="skipped",
            source_table=source_table, source_pk=source_pk,
            reason=f"player {player_legacy_id} not in active set",
        )
        return

    event_uuid = ctx.event_by_legacy_id.get(event_legacy_id) if event_legacy_id else None

    legacy_raw = {
        "_source_table": source_table,
        "_source_pk": source_pk,
    }
    if extra_legacy:
        legacy_raw.update(extra_legacy)
    # psycopg row values include date/datetime/Decimal which Django's
    # default JSONField encoder doesn't handle — normalise here so
    # every sub-phase gets the conversion for free.
    legacy_raw = jsonable(legacy_raw)
    result_data = jsonable(result_data)

    if ctx.dry_run:
        ctx.audit.record(
            phase="phase6", action="created",
            source_table=source_table, source_pk=source_pk,
            target_model="exams.ExamResult",
            reason="dry-run",
        )
        return

    existing = ExamResult.objects.filter(
        legacy_raw__contains={"_source_table": source_table, "_source_pk": source_pk},
    ).first()

    fields = dict(
        player_id=player_uuid,
        template=template,
        recorded_at=recorded_at,
        result_data=result_data,
        event_id=event_uuid,
        legacy_raw=legacy_raw,
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        with transaction.atomic():
            existing.save()
        action, target_pk = "updated", str(existing.id)
    else:
        with transaction.atomic():
            er = ExamResult.objects.create(**fields)
        action, target_pk = "created", str(er.id)

    ctx.audit.record(
        phase="phase6", action=action,
        source_table=source_table, source_pk=source_pk,
        target_model="exams.ExamResult", target_pk=target_pk,
    )


def _ts(d, default_hour: int = 9) -> datetime:
    """date or datetime → tz-aware datetime in America/Santiago."""
    if isinstance(d, datetime):
        return d.replace(tzinfo=_TZ) if d.tzinfo is None else d
    return datetime.combine(d, time(default_hour, 0), tzinfo=_TZ)


# --- per-table importers ----------------------------------------------


def _import_hoja_diaria(ctx: MigrationContext, template: ExamTemplate | None):
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM hoja_diaria WHERE fecha >= %s AND fecha <= %s",
        (ctx.date_from, ctx.date_to),
    )
    for row in rows:
        try:
            data = {
                "causa": fix_mojibake(row.get("causaintervencion") or "") or None,
                "tipo": fix_mojibake(row.get("tipointervencion") or "") or None,
                "musculo_objetivo": fix_mojibake(row.get("tratamientomusculo") or "") or None,
                "lateralidad": fix_mojibake(row.get("tratamientolateralidad") or "") or None,
                "color": fix_mojibake(row.get("color") or "") or None,
                "comentarios": fix_mojibake(row.get("comentarios") or "") or "",
            }
            data = {k: v for k, v in data.items() if v is not None}
            _upsert_result(
                ctx, "hoja_diaria", row["idregistro"], template,
                row["jugador_id"], _ts(row["fecha"]), data,
                extra_legacy={"_source_row": row},
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="hoja_diaria", source_pk=row.get("idregistro"),
                             reason=f"{type(exc).__name__}: {exc}")


def _import_antropometria(ctx: MigrationContext, template: ExamTemplate | None):
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM antropometria WHERE fecha_evaluacion >= %s AND fecha_evaluacion <= %s",
        (ctx.date_from, ctx.date_to),
    )
    for row in rows:
        try:
            # Map legacy columns to SLAB template keys.
            data: dict[str, Any] = {
                "peso": row.get("peso_bruto_kg"),
                "talla": row.get("talla_corporal_cm"),
                "talla_sentado": row.get("talla_sentado_cm"),
                "sexo": 1,    # Player-level sex stored separately; assume M for PEM
                # diameters
                "humero": row.get("diametro_humeral_biepicondilar"),
                "femur": row.get("diametro_femoral_biepicondilar"),
                "biacromial": row.get("diametro_biacromial"),
                "bi_iliocrestideo": row.get("diametro_bi_iliocrestideo"),
                "diam_torax_transverso": row.get("diametro_torax_transverso"),
                "diam_torax_ap": row.get("diametro_torax_antero_posterior"),
                # perimeters
                "perim_cabeza": row.get("perimetro_cabeza"),
                "perim_brazo_relajado": row.get("perimetro_brazo_relajado"),
                "perim_brazo_contraido": row.get("perimetro_brazo_flexionado_en_tension"),
                "perim_antebrazo": row.get("perimetro_antebrazo_maximo"),
                "perim_torax": row.get("perimetro_torax_mesoesternal"),
                "cintura": row.get("perimetro_cintura_minima"),
                "caderas": row.get("perimetro_cadera_maximo"),
                "muslo_gluteo": row.get("perimetro_muslo_maximo"),
                "muslo_medio": row.get("perimetro_muslo_medial"),
                "pierna_perim": row.get("perimetro_pantorrilla_maxima"),
                # skinfolds
                "pliegue_triceps": row.get("pliegues_triceps"),
                "pliegue_subescapular": row.get("pliegues_subescapular"),
                "pliegue_supra": row.get("pliegues_supraespinal"),
                "pliegue_abdomen": row.get("pliegues_abdominal"),
                "pliegue_muslo": row.get("pliegues_muslo_medial"),
                "pliegue_pierna": row.get("pliegues_pantorrilla"),
                "pliegue_bicipital": row.get("bicipital"),
                "pliegue_supracrestideo": row.get("supracrestideo"),
                # notes
                "objetivo": fix_mojibake(row.get("objetivo_general") or "") or None,
                "notas": fix_mojibake(row.get("comentarios") or "") or None,
            }
            data = {k: v for k, v in data.items() if v is not None}
            _upsert_result(
                ctx, "antropometria", row["id_evaluacion"], template,
                row["jugador_id"], _ts(row["fecha_evaluacion"]), data,
                extra_legacy={
                    "_source_row": row,
                    # Stash legacy-computed masas so we can compare vs
                    # SLAB-recomputed (Kerr/De Rose) values for QC.
                    "_legacy_computed_masas": {
                        "masa_piel_kg":     row.get("masa_piel_kg"),
                        "masa_adiposa_kg":  row.get("masa_adiposa_kg"),
                        "masa_muscular_kg": row.get("masa_muscular_kg"),
                        "masa_osea_kg":     row.get("masa_osea_kg"),
                        "masa_residual_kg": row.get("masa_residual_kg"),
                    },
                },
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="antropometria", source_pk=row.get("id_evaluacion"),
                             reason=f"{type(exc).__name__}: {exc}")


def _import_gps_partido(ctx: MigrationContext, template: ExamTemplate | None):
    """Pivot: legacy gps_partido is one row per period; SLAB has p1/p2
    columns side-by-side. Group source rows by (jugador, partido) then
    populate _p1 / _p2 based on `tipo_evaluacion`. 'Partido Completo'
    rows land in _p1 (see migration spec Gap 1)."""
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM gps_partido WHERE fecha >= %s AND fecha <= %s",
        (ctx.date_from, ctx.date_to),
    )

    # Group by (jugador_id, partido_id) → list of rows (each row = one period)
    groups: dict[tuple[int, int], list[dict]] = {}
    for r in rows:
        key = (r.get("jugador_id"), r.get("partido_id"))
        groups.setdefault(key, []).append(r)

    for (jugador_id, partido_id), period_rows in groups.items():
        try:
            data: dict[str, Any] = {}
            for r in period_rows:
                suffix = GPS_PERIOD_MAP.get(r.get("tipo_evaluacion"), "p1")
                # Map each numeric column to the appropriate _p{suffix} field.
                data.update({
                    f"tot_dur_{suffix}":      r.get("tot_dur_m"),
                    f"tot_dist_{suffix}":     r.get("tot_dist_m"),
                    f"mpm_{suffix}":          r.get("meterage_per_minute"),
                    f"hsr_{suffix}":          r.get("distancia_hsr_gt_19_8_kmh"),
                    f"hsr_rel_{suffix}":      r.get("distancia_abs_hsr_m_min"),
                    f"sprint_{suffix}":       r.get("distancia_sprint_gt_25_kmh"),
                    f"sprint_rel_{suffix}":   r.get("sprints_m_min"),
                    f"dist_70_85_{suffix}":   r.get("vmax_70_85"),
                    f"dist_85_95_{suffix}":   r.get("vmax_85_95"),
                    f"acc_dec_{suffix}":      r.get("acc_dec_gt_3"),
                    f"max_vel_{suffix}":      r.get("max_vel_kmh"),
                    f"hiaa_{suffix}":         r.get("hiaa"),
                    f"hmld_{suffix}":         r.get("load_hmld_m"),
                    f"acc_{suffix}":          r.get("acc_mayor_3_ms2"),
                    f"dec_{suffix}":          r.get("dec_mayor_3_ms2"),
                    f"player_load_{suffix}":  r.get("player_load_au"),
                })
            data = {k: v for k, v in data.items() if v is not None}
            recorded_at = _ts(period_rows[0]["fecha"], default_hour=15)
            _upsert_result(
                ctx, "gps_partido",
                # Use the first row's id as the upsert anchor.
                period_rows[0]["id_gps_partido"], template,
                jugador_id, recorded_at, data,
                event_legacy_id=partido_id,
                extra_legacy={
                    "_source_rows": period_rows,
                    "_pivot_keys": [r.get("tipo_evaluacion") for r in period_rows],
                },
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="gps_partido",
                             source_pk=period_rows[0].get("id_gps_partido"),
                             reason=f"{type(exc).__name__}: {exc}")


def _import_wellness(ctx: MigrationContext, template: ExamTemplate | None):
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM wellness "
        " WHERE marca_temporal >= %s AND marca_temporal <= %s "
        "   AND jugador_id IS NOT NULL",
        (ctx.date_from, ctx.date_to),
    )
    for row in rows:
        try:
            data = {
                "doms": row.get("dolor_muscular"),
                "animo": row.get("estado_animo"),
                "estres": row.get("estres"),
                "fatiga": row.get("fatiga"),
                "sueno": row.get("sueno"),
                "zona_dolor": fix_mojibake(row.get("zona_dolor") or "") or None,
                "peso": row.get("peso"),
            }
            data = {k: v for k, v in data.items() if v is not None}
            _upsert_result(
                ctx, "wellness", row["id_wellness"], template,
                row["jugador_id"], _ts(row["marca_temporal"]), data,
                extra_legacy={"_source_row": row},
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="wellness", source_pk=row.get("id_wellness"),
                             reason=f"{type(exc).__name__}: {exc}")


def _import_ck(ctx: MigrationContext, template: ExamTemplate | None):
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM examenes "
        " WHERE nombre_examen = 'CK' AND fecha_examen >= %s AND fecha_examen <= %s",
        (ctx.date_from, ctx.date_to),
    )
    for row in rows:
        try:
            data = {
                "fecha": row["fecha_examen"].isoformat() if row.get("fecha_examen") else None,
                "valor": row.get("valor"),
                "nota": fix_mojibake(row.get("unidad") or "") or None,
            }
            data = {k: v for k, v in data.items() if v is not None}
            _upsert_result(
                ctx, "examenes-ck", row["id_examen"], template,
                row["jugador_id"], _ts(row["fecha_examen"]), data,
                extra_legacy={"_source_row": row},
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="examenes-ck", source_pk=row.get("id_examen"),
                             reason=f"{type(exc).__name__}: {exc}")


# Legacy nombre_examen → SLAB analisis_sangre field key.
_BLOOD_TEST_KEY_MAP: dict[str, str] = {
    "Hematocrito":                    "hematocrito",
    "Hemoglobina":                    "hemoglobina",
    "Ferritina":                      "ferritina",
    "Vitamina B12":                   "vitamina_b12",
    "Vitamina D":                     "vitamina_d",
    "Testosterona Total":             "testosterona_total",
    "Testosterona Libre":             "testosterona_libre",
    "Cortisol":                       "cortisol",
    "TSH":                            "tsh",
    "T3":                             "t3",
    "T4 LIBRE":                       "t4_libre",
    "Densidad Urinaria":              "densidad_urinaria",
    # Índice Testosterona/Cortisol is calculated by SLAB — skip importing.
}


def _import_analisis_sangre(ctx: MigrationContext, template: ExamTemplate | None):
    """Group EAV `examenes` rows by (jugador, fecha) → one panel result.
    CK is handled separately by `_import_ck`."""
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM examenes "
        " WHERE nombre_examen <> 'CK' AND fecha_examen >= %s AND fecha_examen <= %s",
        (ctx.date_from, ctx.date_to),
    )

    groups: dict[tuple[int, Any], list[dict]] = {}
    for r in rows:
        key = (r.get("jugador_id"), r.get("fecha_examen"))
        groups.setdefault(key, []).append(r)

    for (jugador_id, fecha), panel_rows in groups.items():
        try:
            data: dict[str, Any] = {}
            for r in panel_rows:
                field_key = _BLOOD_TEST_KEY_MAP.get(r.get("nombre_examen"))
                if field_key is None or r.get("valor") is None:
                    continue
                data[field_key] = r["valor"]
            if not data:
                continue
            _upsert_result(
                ctx, "examenes-panel",
                f"{jugador_id}-{fecha}",
                template, jugador_id, _ts(fecha), data,
                extra_legacy={
                    "_source_rows": panel_rows,
                    "_grouping_key": {"jugador_id": jugador_id, "fecha": str(fecha)},
                },
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="examenes-panel",
                             source_pk=f"{jugador_id}-{fecha}",
                             reason=f"{type(exc).__name__}: {exc}")


# Legacy `variable` → SLAB fase_densidad field key.
_FASE_DENSIDAD_KEY_MAP: dict[str, str] = {
    "Densidad Urinaria":   "densidad_urinaria",
    "Fase Ciclo Menstrual": "fase_ciclo_menstrual",
    "Índice MAD":           "indice_mad",
    "Edad PHV":             "edad_phv",
}


def _import_fase_densidad(ctx: MigrationContext, template: ExamTemplate | None):
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM fase_densidad WHERE fecha_evaluacion >= %s AND fecha_evaluacion <= %s",
        (ctx.date_from, ctx.date_to),
    )
    groups: dict[tuple[int, Any], list[dict]] = {}
    for r in rows:
        key = (r.get("jugador_id"), r.get("fecha_evaluacion"))
        groups.setdefault(key, []).append(r)

    for (jugador_id, fecha), panel_rows in groups.items():
        try:
            data: dict[str, Any] = {}
            for r in panel_rows:
                field_key = _FASE_DENSIDAD_KEY_MAP.get(r.get("variable"))
                if field_key is None or r.get("valor") is None:
                    continue
                data[field_key] = r["valor"]
            if not data:
                continue
            _upsert_result(
                ctx, "fase_densidad",
                f"{jugador_id}-{fecha}",
                template, jugador_id, _ts(fecha), data,
                extra_legacy={"_source_rows": panel_rows},
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="fase_densidad",
                             source_pk=f"{jugador_id}-{fecha}",
                             reason=f"{type(exc).__name__}: {exc}")


def _import_medicamentos(ctx: MigrationContext, template: ExamTemplate | None):
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM medicamentos WHERE fecha >= %s AND fecha <= %s",
        (ctx.date_from, ctx.date_to),
    )
    for row in rows:
        try:
            tipo = fix_mojibake(row.get("tipo_de_medicamento") or "") or None
            if tipo:
                tipo = MEDICACION_TIPO_NORMALIZE.get(tipo, tipo)
            data = {
                # Free-text medicamento — may not match the WADA dropdown
                # options. Stash as text; the option_risk signal will
                # ignore unmatched names (no false WADA alerts).
                "medicamento": fix_mojibake(row.get("medicamento") or "") or None,
                "tipo": tipo,
                "cantidad": row.get("numero_de_comprimidos"),
                "fecha_inicio": row["fecha"].isoformat() if row.get("fecha") else None,
                "stage": "completada",   # legacy doesn't track status; default to completed
                "notas": fix_mojibake(row.get("comentarios") or "") or None,
            }
            data = {k: v for k, v in data.items() if v is not None}
            _upsert_result(
                ctx, "medicamentos", row["id_registro"], template,
                row["jugador_id"], _ts(row["fecha"]), data,
                extra_legacy={"_source_row": row},
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="medicamentos", source_pk=row.get("id_registro"),
                             reason=f"{type(exc).__name__}: {exc}")


def _import_evaluacion_partido(ctx: MigrationContext, template: ExamTemplate | None):
    """For 2025+ rows, partido_id/jugador_id are NULL — resolve via
    citacion_lookup populated by phase 4."""
    if not template:
        return
    rows = ctx.legacy_db.fetch_all(
        "SELECT * FROM evaluacion_partido WHERE fecha_evaluacion >= %s AND fecha_evaluacion <= %s",
        (ctx.date_from, ctx.date_to),
    )
    for row in rows:
        try:
            partido_id = row.get("partido_id")
            jugador_id = row.get("jugador_id")
            citacion_id = row.get("citacion_id")

            if (partido_id is None or jugador_id is None) and citacion_id is not None:
                lookup = ctx.citacion_lookup.get(citacion_id)
                if lookup is None:
                    ctx.audit.record(
                        phase="phase6", action="skipped",
                        source_table="evaluacion_partido", source_pk=row.get("id_evaluacion"),
                        reason=f"citacion_id={citacion_id} not in lookup map",
                    )
                    continue
                partido_id, jugador_id = lookup

            if jugador_id is None or partido_id is None:
                ctx.audit.record(
                    phase="phase6", action="skipped",
                    source_table="evaluacion_partido", source_pk=row.get("id_evaluacion"),
                    reason="no jugador_id/partido_id resolvable",
                )
                continue

            position_uuid = ctx.position_by_legacy_id.get(row.get("posicion_id"))

            # rendimiento_de_partido.position_played is a categorical
            # with 4 options, but we don't know the exact option keys
            # without inspecting the SLAB schema. Skip position_played
            # for now; the EventParticipant.position_played already
            # carries this info from phase 4.
            data: dict[str, Any] = {
                "rating": row.get("nota"),
                "notes": fix_mojibake(row.get("comentario") or "") or None,
            }
            data = {k: v for k, v in data.items() if v is not None}
            _upsert_result(
                ctx, "evaluacion_partido", row["id_evaluacion"], template,
                jugador_id, _ts(row["fecha_evaluacion"]), data,
                event_legacy_id=partido_id,
                extra_legacy={
                    "_source_row": row,
                    "_resolved_via_citacion": citacion_id,
                },
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(phase="phase6", action="failed",
                             source_table="evaluacion_partido", source_pk=row.get("id_evaluacion"),
                             reason=f"{type(exc).__name__}: {exc}")
