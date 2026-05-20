"""Phase 0 — reference data import.

Imports legacy `categoria` → SLAB Category and legacy `posicion` →
SLAB Position. These are tiny tables (16 + 18 rows) but every later
phase depends on the lookup maps this phase populates.

Strategy:
  - Match by name (with CATEGORY_NAME_MAP applied — e.g. PEM →
    "Primer Equipo"). If a matching SLAB row exists, link to it.
  - Otherwise, CREATE the SLAB row and link.
  - Populate `legacy_raw` on every touched row so a re-run knows where
    it came from.
  - The cache (`ctx.category_by_legacy_id` / `ctx.position_by_legacy_id`)
    is populated for use by later phases.
"""
from __future__ import annotations

from django.db import transaction

from core.models import Category, Position

from ..mapping import CATEGORY_NAME_MAP, fix_mojibake
from .context import MigrationContext, dry_uuid


def run(ctx: MigrationContext) -> None:
    """Run reference-data phase. Idempotent — re-runs link to existing
    rows rather than duplicate them."""
    ctx.audit.info("phase0_reference: start")
    _import_categories(ctx)
    _import_positions(ctx)
    ctx.audit.info(
        "phase0_reference: done",
        category_count=len(ctx.category_by_legacy_id),
        position_count=len(ctx.position_by_legacy_id),
    )


# --- Category --------------------------------------------------------


def _import_categories(ctx: MigrationContext) -> None:
    rows = ctx.legacy_db.fetch_all(
        "SELECT id_categoria, genero, nombre FROM categoria ORDER BY id_categoria"
    )
    for row in rows:
        try:
            legacy_id = row["id_categoria"]
            legacy_name = fix_mojibake(row.get("nombre") or "") or ""
            genero = row.get("genero") or ""

            slab_name = CATEGORY_NAME_MAP.get(legacy_name, legacy_name)
            # For female categories with no explicit rename, append the
            # gender suffix so SLAB names are unambiguous (e.g.
            # "U18 - Femenino").
            if genero.lower() == "femenino" and "femenino" not in slab_name.lower():
                slab_name = f"{slab_name} - Femenino"

            existing = Category.objects.filter(
                club=ctx.club, name=slab_name,
            ).first()

            if existing:
                # Category model has no `legacy_raw` field (small reference
                # table; provenance lives in the audit log). We just link
                # the legacy id and move on.
                ctx.category_by_legacy_id[legacy_id] = str(existing.id)
                ctx.audit.record(
                    phase="phase0",
                    action="skipped",
                    source_table="categoria",
                    source_pk=legacy_id,
                    target_model="core.Category",
                    target_pk=str(existing.id),
                    reason=f"matched existing SLAB Category by name='{slab_name}'",
                    extra={"legacy_row": row},
                )
                continue

            if ctx.dry_run:
                ctx.audit.record(
                    phase="phase0",
                    action="created",
                    source_table="categoria",
                    source_pk=legacy_id,
                    target_model="core.Category",
                    target_pk=None,
                    reason=f"would create Category '{slab_name}' (dry-run)",
                )
                # Use a sentinel so later phases linking via this legacy
                # id don't crash. They'll resolve the real UUID on a
                # real (non-dry) run.
                # Deterministic placeholder UUID so cascading phases
                # can still resolve FK lookups in dry-run mode.
                ctx.category_by_legacy_id[legacy_id] = dry_uuid("category", legacy_id)
                continue

            with transaction.atomic():
                cat = Category.objects.create(club=ctx.club, name=slab_name)
            ctx.category_by_legacy_id[legacy_id] = str(cat.id)
            ctx.audit.record(
                phase="phase0",
                action="created",
                source_table="categoria",
                source_pk=legacy_id,
                target_model="core.Category",
                target_pk=str(cat.id),
                extra={"legacy_row": row},
            )

        except Exception as exc:   # noqa: BLE001 — log and continue
            ctx.audit.record(
                phase="phase0",
                action="failed",
                source_table="categoria",
                source_pk=row.get("id_categoria"),
                reason=f"{type(exc).__name__}: {exc}",
            )


# --- Position --------------------------------------------------------


def _import_positions(ctx: MigrationContext) -> None:
    rows = ctx.legacy_db.fetch_all(
        "SELECT id_posicion, nombre, tipo FROM posicion ORDER BY id_posicion"
    )
    for row in rows:
        try:
            legacy_id = row["id_posicion"]
            name = fix_mojibake(row.get("nombre") or "") or ""
            if not name:
                ctx.audit.record(
                    phase="phase0",
                    action="skipped",
                    source_table="posicion",
                    source_pk=legacy_id,
                    reason="legacy row had no nombre",
                )
                continue

            # SLAB requires an abbreviation; derive from the name when
            # absent in legacy (legacy posicion has no abbrev column).
            # Deduplicate against existing club abbreviations to avoid
            # the (club, abbreviation) unique-constraint clash — SLAB
            # already seeds e.g. "DC" / "VI", but with different
            # full names than legacy uses.
            abbreviation = _unique_abbreviation(
                ctx.club, _derive_abbreviation(name),
            )

            existing = Position.objects.filter(club=ctx.club, name=name).first()
            if existing:
                # Position model has no `legacy_raw`; provenance lives
                # in the audit log only.
                ctx.position_by_legacy_id[legacy_id] = str(existing.id)
                ctx.audit.record(
                    phase="phase0",
                    action="skipped",
                    source_table="posicion",
                    source_pk=legacy_id,
                    target_model="core.Position",
                    target_pk=str(existing.id),
                    reason=f"matched existing Position by name='{name}'",
                    extra={"legacy_row": row},
                )
                continue

            if ctx.dry_run:
                ctx.audit.record(
                    phase="phase0",
                    action="created",
                    source_table="posicion",
                    source_pk=legacy_id,
                    target_model="core.Position",
                    target_pk=None,
                    reason=f"would create Position '{name}' (dry-run)",
                )
                ctx.position_by_legacy_id[legacy_id] = dry_uuid("position", legacy_id)
                continue

            with transaction.atomic():
                pos = Position.objects.create(
                    club=ctx.club,
                    name=name,
                    abbreviation=abbreviation,
                    role=row.get("tipo") or "",
                )
            ctx.position_by_legacy_id[legacy_id] = str(pos.id)
            ctx.audit.record(
                phase="phase0",
                action="created",
                source_table="posicion",
                source_pk=legacy_id,
                target_model="core.Position",
                target_pk=str(pos.id),
            )

        except Exception as exc:   # noqa: BLE001
            ctx.audit.record(
                phase="phase0",
                action="failed",
                source_table="posicion",
                source_pk=row.get("id_posicion"),
                reason=f"{type(exc).__name__}: {exc}",
            )


def _derive_abbreviation(name: str) -> str:
    """Derive a short abbreviation from a position name. Uses the first
    letter of each significant word, capped at 4 chars. 'Lateral derecho'
    → 'LD', 'Defensa central' → 'DC', 'Volante mixto' → 'VM'."""
    words = [w for w in name.split() if len(w) > 2]
    if not words:
        return name[:4].upper()
    abbrev = "".join(w[0] for w in words[:4]).upper()
    return abbrev[:8]


def _unique_abbreviation(club, base: str) -> str:
    """Return `base` if it's not already used on this club, else `base2`,
    `base3`, …. SLAB enforces unique (club, abbreviation), so legacy
    positions whose derived abbreviation collides with an existing SLAB
    seed (e.g. DC, VI) get a numeric suffix to keep both rows alive."""
    if not Position.objects.filter(club=club, abbreviation=base).exists():
        return base
    for n in range(2, 100):
        candidate = f"{base}{n}"
        # Keep the column length below the model's max (typically 8) —
        # `base` is already capped at 8 by _derive_abbreviation, but
        # the numeric suffix can push it over; trim from the base side.
        if len(candidate) > 8:
            candidate = f"{base[: 8 - len(str(n))]}{n}"
        if not Position.objects.filter(club=club, abbreviation=candidate).exists():
            return candidate
    raise RuntimeError(f"Could not find unique abbreviation for base '{base}'")
