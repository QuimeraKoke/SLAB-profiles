"""Phase 1 — Player import.

Filters legacy `jugador` (805 rows) down to ACTIVE players for the
scope window: any jugador that has at least one row in 2025+ across
the in-scope tables (antropometria / lesion / hoja_diaria / wellness /
medicamentos / examenes / fase_densidad / gps_partido / citaciones).
That gives ~338 active players vs. 805 historical.

Each imported jugador becomes a SLAB Player whose:
  - first_name / last_name / middle_name / second_last_name come from
    legacy columns
  - national_id <- jugador.rut
  - date_of_birth <- jugador.fecha_nacimiento
  - position <- jugador.posicion_primaria_id (resolved via ctx.position_by_legacy_id)
  - secondary_position <- jugador.posicion_secundaria_id (same)
  - photo_url <- copied from Google Drive into SLAB storage (with
    fallback to the raw URL on fetch failure)
  - sex <- inferred from the dominant categoría's `genero` (Femenino →
    Female, else Male). Legacy `jugador` has no sex column directly.
  - legacy_raw stashes the full source row + categorisation provenance

Categoría assignment uses a 3-tier fallback:

  Tier 1 — most-cited categoría from `citaciones` in scope (best signal:
           the player was actually called to a match).
  Tier 2 — most-recent row in `jugador_inscripcion`, traversed via
           competicion_temporada → competicion.categoria_id. This is
           the signal that picks up the women's team and the U8-U10
           youth squads, which legacy doesn't track via citaciones.
  Tier 3 — "Primer Equipo" default. Players with no citaciones AND no
           inscriptions land here; flagged in `legacy_raw._category_source`
           so they can be re-assigned from the dashboard.
"""
from __future__ import annotations

from django.db import transaction

from core.models import Category, Player, PlayerAlias, Position

from ..mapping import PREFERRED_FOOT_MAP, fix_mojibake, jsonable
from ..photos import copy_player_photo_to_storage
from .context import MigrationContext, dry_uuid


# Tier 2 fallback — most-recent inscription row per jugador. Uses NO
# scope filter (the inscription is the "current squad assignment",
# regardless of whether the player has been called up in 2025+).
_INSCRIPCION_CATEGORIA_QUERY = """
    WITH ranked AS (
        SELECT ji.jugador_id,
               cat.id_categoria,
               cat.genero,
               ROW_NUMBER() OVER (
                 PARTITION BY ji.jugador_id
                 ORDER BY ji.fecha DESC NULLS LAST, ji.id_inscripcion DESC
               ) AS rn
          FROM jugador_inscripcion ji
          JOIN competicion_temporada ct
            ON ct.id_competicion_temporada = ji.competicion_temporada_id
          JOIN competicion comp ON comp.id_competicion = ct.competicion_id
          JOIN categoria   cat  ON cat.id_categoria   = comp.categoria_id
    )
    SELECT jugador_id, id_categoria, genero
      FROM ranked WHERE rn = 1
"""


# Tier 1 — most-cited categoría within scope. `categoria.genero` is
# also returned so we can set Player.sex from a real signal rather than
# a name heuristic.
_DOMINANT_CATEGORIA_QUERY = """
    WITH cit_in_scope AS (
        SELECT c.jugador_id, cat.id_categoria, cat.genero
          FROM citaciones c
          JOIN partido p ON p.id_partido = c.partido_id
          JOIN competicion_temporada ct
            ON ct.id_competicion_temporada = p.competicion_temporada_id
          JOIN competicion comp ON comp.id_competicion = ct.competicion_id
          JOIN categoria   cat  ON cat.id_categoria   = comp.categoria_id
         WHERE p.fecha_partido BETWEEN %s AND %s
           AND c.jugador_id IS NOT NULL
    ),
    ranked AS (
        SELECT jugador_id, id_categoria, genero,
               COUNT(*) AS n,
               ROW_NUMBER() OVER (
                 PARTITION BY jugador_id
                 ORDER BY COUNT(*) DESC, id_categoria ASC
               ) AS rn
          FROM cit_in_scope
         GROUP BY jugador_id, id_categoria, genero
    )
    SELECT jugador_id, id_categoria, genero
      FROM ranked WHERE rn = 1
"""


# Tables that, when they have a 2025+ row for a player, qualify the
# player as ACTIVE. List grows with the scope; keep aligned with the
# migration spec.
_ACTIVE_PLAYER_QUERY = """
    SELECT DISTINCT jugador_id FROM (
        SELECT jugador_id FROM antropometria
         WHERE fecha_evaluacion >= %s AND fecha_evaluacion <= %s AND jugador_id IS NOT NULL
        UNION SELECT jugador_id FROM lesion
         WHERE fecha_lesion >= %s AND fecha_lesion <= %s AND jugador_id IS NOT NULL
        UNION SELECT jugador_id FROM hoja_diaria
         WHERE fecha >= %s AND fecha <= %s AND jugador_id IS NOT NULL
        UNION SELECT jugador_id FROM wellness
         WHERE marca_temporal >= %s AND marca_temporal <= %s AND jugador_id IS NOT NULL
        UNION SELECT jugador_id FROM medicamentos
         WHERE fecha >= %s AND fecha <= %s AND jugador_id IS NOT NULL
        UNION SELECT jugador_id FROM examenes
         WHERE fecha_examen >= %s AND fecha_examen <= %s AND jugador_id IS NOT NULL
        UNION SELECT jugador_id FROM fase_densidad
         WHERE fecha_evaluacion >= %s AND fecha_evaluacion <= %s AND jugador_id IS NOT NULL
        UNION SELECT jugador_id FROM gps_partido
         WHERE fecha >= %s AND fecha <= %s AND jugador_id IS NOT NULL
        UNION SELECT c.jugador_id
          FROM citaciones c
          JOIN partido p ON p.id_partido = c.partido_id
         WHERE p.fecha_partido >= %s AND p.fecha_partido <= %s
    ) t
"""


def run(ctx: MigrationContext) -> None:
    ctx.audit.info("phase1_players: start", date_from=str(ctx.date_from), date_to=str(ctx.date_to))

    # Window params are repeated 9× for the 9 sub-queries in the UNION.
    df, dt = ctx.date_from, ctx.date_to
    window = (df, dt) * 9
    active_ids = {
        row["jugador_id"] for row in ctx.legacy_db.iter_rows(_ACTIVE_PLAYER_QUERY, window)
    }
    ctx.audit.info("phase1_players: active set computed", count=len(active_ids))

    if not active_ids:
        ctx.audit.warn("phase1_players: no active players found in scope — aborting phase")
        return

    # Pick the default category for players with NO citaciones in scope.
    default_category = Category.objects.filter(
        club=ctx.club, name="Primer Equipo",
    ).first()
    if default_category is None and not ctx.dry_run:
        ctx.audit.warn(
            "phase1_players: no default Category found — aborting phase",
            club=str(ctx.club),
        )
        return

    # Categorisation per active player — 3-tier resolution.
    # cat_by_jugador[jugador_id] = (categoria_id, source_tag)
    cat_by_jugador: dict[int, tuple[int, str]] = {}
    genero_by_cat: dict[int, str] = {}

    # Tier 1: citaciones in scope (most reliable — actual match calls).
    for r in ctx.legacy_db.iter_rows(
        _DOMINANT_CATEGORIA_QUERY, (ctx.date_from, ctx.date_to)
    ):
        cat_by_jugador[r["jugador_id"]] = (r["id_categoria"], "citaciones")
        genero_by_cat[r["id_categoria"]] = (r["genero"] or "").strip().lower()
    n_citaciones = len(cat_by_jugador)

    # Tier 2: most-recent jugador_inscripcion (women's team + youth +
    # players without 2025 citaciones). Restricted to the active set
    # so the dict + counters reflect only players we'll actually import.
    for r in ctx.legacy_db.iter_rows(_INSCRIPCION_CATEGORIA_QUERY):
        jid = r["jugador_id"]
        if jid not in active_ids:
            continue
        # Tier-1 wins when it has a value; otherwise inscription fills in.
        if jid not in cat_by_jugador:
            cat_by_jugador[jid] = (r["id_categoria"], "inscripcion")
        # Populate genero map for the inscription-only categorias too.
        genero_by_cat.setdefault(
            r["id_categoria"], (r["genero"] or "").strip().lower(),
        )
    n_inscripcion = len(cat_by_jugador) - n_citaciones
    n_fallback = len(active_ids) - len(cat_by_jugador)
    ctx.audit.info(
        "phase1_players: categoria signals computed",
        from_citaciones=n_citaciones,
        from_inscripcion=n_inscripcion,
        from_fallback=n_fallback,
    )

    # Preload Category objects keyed by legacy categoria id — one query
    # at phase start, then dict lookups inside the per-player loop.
    category_by_legacy_id_obj: dict[int, Category] = {}
    if not ctx.dry_run:
        for legacy_cat_id, cat_uuid in ctx.category_by_legacy_id.items():
            cat = Category.objects.filter(id=cat_uuid).first()
            if cat:
                category_by_legacy_id_obj[legacy_cat_id] = cat

    # Nationality lookup. Column names auto-detected because legacy
    # tables don't follow a single convention. Empty dict on failure —
    # nationality is non-critical and falls back to blank.
    nacionalidad_by_id = _load_nacionalidad_lookup(ctx)

    # Pull every active jugador in a single query (optionally capped).
    placeholders = ",".join(["%s"] * len(active_ids))
    limit_clause = f" LIMIT {int(ctx.limit)}" if ctx.limit else ""
    rows = ctx.legacy_db.fetch_all(
        f"SELECT * FROM jugador WHERE id_jugador IN ({placeholders}){limit_clause}",
        tuple(active_ids),
    )

    for row in rows:
        try:
            _import_one_player(
                ctx, row, default_category,
                cat_by_jugador, genero_by_cat, category_by_legacy_id_obj,
                nacionalidad_by_id,
            )
        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(
                phase="phase1",
                action="failed",
                source_table="jugador",
                source_pk=row.get("id_jugador"),
                reason=f"{type(exc).__name__}: {exc}",
            )

    ctx.audit.info(
        "phase1_players: done",
        player_count=len(ctx.player_by_legacy_id),
    )


def _import_one_player(
    ctx: MigrationContext,
    row: dict,
    default_category: Category | None,
    cat_by_jugador: dict[int, tuple[int, str]],
    genero_by_cat: dict[int, str],
    category_by_legacy_id_obj: dict[int, Category],
    nacionalidad_by_id: dict[int, str],
) -> None:
    legacy_id = row["id_jugador"]

    # Idempotency: if a Player already exists with this legacy id stashed,
    # update-in-place; else create.
    existing = Player.objects.filter(
        legacy_raw__contains={"_source_table": "jugador", "_source_pk": legacy_id},
    ).first()

    # Resolve names (handling mojibake on the way).
    first_name = fix_mojibake(row.get("primer_nombre") or "") or ""
    middle_name = fix_mojibake(row.get("segundo_nombre") or "") or ""
    last_name = fix_mojibake(row.get("primer_apellido") or "") or ""
    second_last_name = fix_mojibake(row.get("segundo_apellido") or "") or ""

    # Fallback: legacy `nombre` is the full name; split if components empty.
    if not first_name and row.get("nombre"):
        parts = fix_mojibake(row["nombre"]).split()
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

    # Resolve categoría via the 3-tier signal (citaciones → inscripcion
    # → PEM fallback). Sources land in legacy_raw for audit.
    cat_entry = cat_by_jugador.get(legacy_id)
    if cat_entry and cat_entry[0] in category_by_legacy_id_obj:
        legacy_cat_id, category_source = cat_entry
        category = category_by_legacy_id_obj[legacy_cat_id]
    else:
        legacy_cat_id = None
        category = default_category
        category_source = "fallback-pem"

    # Sex from `categoria.genero` (preferred). Legacy `jugador` itself
    # has no sex column. Fallback to Male.
    inferred_sex = Player.SEX_MALE
    if legacy_cat_id and genero_by_cat.get(legacy_cat_id) == "femenino":
        inferred_sex = Player.SEX_FEMALE
    elif category and "femenino" in (category.name or "").lower():
        inferred_sex = Player.SEX_FEMALE

    # Resolve position FKs through the phase0 cache. Skip the FK when
    # the lookup is a DRY: sentinel (dry-run mode).
    position_id = _resolve_position(ctx, row.get("posicion_primaria_id"))
    secondary_position_id = _resolve_position(ctx, row.get("posicion_secundaria_id"))

    preferred_foot = PREFERRED_FOOT_MAP.get(row.get("pie") or "", "")

    # Nationality: legacy stores up to two nationalities via FK. Primary
    # lands in Player.nationality; the secondary (when present) is
    # captured in legacy_raw only — SLAB has no field for it yet.
    primary_nat_id = row.get("primera_nacionalidad_id")
    secondary_nat_id = row.get("segunda_nacionalidad_id")
    nationality = nacionalidad_by_id.get(primary_nat_id, "") if primary_nat_id else ""
    secondary_nationality = (
        nacionalidad_by_id.get(secondary_nat_id, "") if secondary_nat_id else ""
    )

    # Build the legacy_raw payload. Photo copy is deferred to after the
    # save so we have the player's UUID to use as a key fallback.
    legacy_raw = jsonable({
        "_source_table": "jugador",
        "_source_pk": legacy_id,
        "_source_row": row,
        "_category_source": category_source,
        "_dominant_categoria_id": legacy_cat_id,
        "_secondary_nationality": secondary_nationality or None,
    })

    if ctx.dry_run:
        action = "updated" if existing else "created"
        ctx.audit.record(
            phase="phase1",
            action=action,
            source_table="jugador",
            source_pk=legacy_id,
            target_model="core.Player",
            target_pk=str(existing.id) if existing else None,
            reason=f"would {action} '{first_name} {last_name}' (dry-run)",
        )
        ctx.player_by_legacy_id[legacy_id] = (
            str(existing.id) if existing else dry_uuid("player", legacy_id)
        )
        return

    if existing:
        existing.category = category
        existing.first_name = first_name
        existing.middle_name = middle_name
        existing.last_name = last_name
        existing.second_last_name = second_last_name
        existing.date_of_birth = row.get("fecha_nacimiento") or existing.date_of_birth
        existing.national_id = row.get("rut") or ""
        existing.nationality = nationality
        existing.preferred_foot = preferred_foot
        existing.sex = inferred_sex
        if position_id:
            existing.position_id = position_id
        if secondary_position_id:
            existing.secondary_position_id = secondary_position_id
        existing.legacy_raw = legacy_raw
        with transaction.atomic():
            existing.save()
        player = existing
        action = "updated"
    else:
        with transaction.atomic():
            player = Player.objects.create(
                category=category,
                first_name=first_name,
                middle_name=middle_name,
                last_name=last_name,
                second_last_name=second_last_name,
                date_of_birth=row.get("fecha_nacimiento"),
                sex=inferred_sex,
                national_id=row.get("rut") or "",
                nationality=nationality,
                preferred_foot=preferred_foot,
                position_id=position_id,
                secondary_position_id=secondary_position_id,
                legacy_raw=legacy_raw,
            )
        action = "created"

    # Wyscout alias: create/update a PlayerAlias for nombre_wyscout when
    # it differs from the player's canonical name. Idempotent — the
    # unique constraint on (player, kind, source, value) is the key.
    wyscout_name = fix_mojibake(row.get("nombre_wyscout") or "").strip()
    canonical = f"{first_name} {last_name}".strip()
    if wyscout_name and wyscout_name.lower() != canonical.lower():
        PlayerAlias.objects.get_or_create(
            player=player,
            kind=PlayerAlias.KIND_NICKNAME,
            source=PlayerAlias.SOURCE_WYSCOUT,
            value=wyscout_name[:120],
        )

    # Photo copy: try after the player record is committed so we have
    # the legacy_id stable. Failures are logged but never block the
    # main migration — the URL fallback handles outages gracefully.
    # Honour --skip-photos for fast local re-runs; the slowest step in
    # phase 1 is the Drive fetch.
    if ctx.skip_photos:
        ctx.audit.info(
            f"phase1_players: photo copy skipped (--skip-photos) for jugador {legacy_id}"
        )
    else:
        photo_url = _photo_for(row)
        if photo_url:
            try:
                final_url = copy_player_photo_to_storage(photo_url, legacy_id)
                if final_url and final_url != player.photo_url:
                    player.photo_url = final_url
                    player.save(update_fields=["photo_url"])
            except Exception as exc:   # noqa: BLE001
                ctx.audit.warn(
                    f"phase1_players: photo copy failed for jugador {legacy_id}: "
                    f"{type(exc).__name__}: {exc}",
                )

    ctx.player_by_legacy_id[legacy_id] = str(player.id)
    ctx.audit.record(
        phase="phase1",
        action=action,
        source_table="jugador",
        source_pk=legacy_id,
        target_model="core.Player",
        target_pk=str(player.id),
    )


def _resolve_position(ctx: MigrationContext, legacy_id) -> str | None:
    """Resolve a legacy posicion_id to a SLAB Position UUID. In dry-run
    we return None so the FK doesn't error out — `position_id` is
    nullable and the audit log still captures intent."""
    if legacy_id is None or ctx.dry_run:
        return None
    return ctx.position_by_legacy_id.get(legacy_id)


def _load_nacionalidad_lookup(ctx: MigrationContext) -> dict[int, str]:
    """Return {id: nombre} for the legacy nationality lookup. The table
    is called `area` in this database (shared with competicion.area_id).
    Schema is still auto-detected so a rename in the source DB doesn't
    silently break the import. Empty dict + warning on failure —
    nationality is non-critical."""
    cols = {
        r["column_name"]
        for r in ctx.legacy_db.iter_rows(
            "SELECT column_name FROM information_schema.columns "
            " WHERE table_schema='public' AND table_name='area'"
        )
    }
    if not cols:
        ctx.audit.warn("phase1_players: 'area' table not found in legacy DB")
        return {}

    id_col = next(
        (c for c in ("id_area", "id_nacionalidad", "id_pais", "id") if c in cols),
        None,
    )
    name_col = next(
        (c for c in ("nombre", "nombre_pais", "nombre_es", "pais", "label") if c in cols),
        None,
    )
    if not id_col or not name_col:
        ctx.audit.warn(
            "phase1_players: area PK/name column unrecognized — "
            "nationalities will be empty",
            cols=sorted(cols),
        )
        return {}

    out: dict[int, str] = {}
    for r in ctx.legacy_db.iter_rows(
        f"SELECT {id_col} AS id, {name_col} AS nombre FROM area"
    ):
        if r["id"] is not None:
            out[r["id"]] = fix_mojibake((r["nombre"] or "")).strip()
    ctx.audit.info("phase1_players: area (nationality) loaded", count=len(out))
    return out


def _photo_for(row: dict) -> str | None:
    """Prefer `foto` (the Drive-hosted full-res URL) over `imagen`. Both
    can be present; legacy stores them redundantly in different formats."""
    for key in ("foto", "imagen"):
        url = row.get(key)
        if url and url.strip():
            return url.strip()
    return None
