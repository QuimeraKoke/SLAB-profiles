"""Re-derive max_vel_p1 / max_vel_p2 / max_vel_total from each GPS row's
legacy source snapshot.

Background
----------
The legacy ``gps_partido`` table stores three rows per (player, match):
  - ``Primer Tiempo`` — first-half max in km/h (realistic ≈ 30 km/h)
  - ``Segundo Tiempo`` — second-half max (realistic ≈ 30 km/h)
  - ``Partido Completo`` — labelled "full match max" but actually contains
    the SUM of the two halves (~60 km/h — physically impossible).

The original phase6 migration mapped ``Partido Completo`` → ``_p1`` slot,
so the bogus sum overwrote the real first-half value. Across 654 GPS
results, 358 (54.9%) ended up with implausible max-speed numbers like
67 km/h.

Fix
---
For each affected result we still have the legacy source rows in
``legacy_raw._source_rows``. This command iterates every GPS result,
re-derives the three ``max_vel_*`` fields from the half-period source
rows (ignoring the bogus Partido Completo value), and writes back.

Idempotent — running twice does nothing on the second pass. Save uses
``update_fields=['result_data']`` so calculated-field recompute signals
don't fire (no other field changes).

Usage
-----
::

    python manage.py repair_gps_max_vel           # dry-run, prints counts
    python manage.py repair_gps_max_vel --apply   # actually write
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from exams.models import ExamResult


GPS_TEMPLATE_SLUG = "gps_rendimiento_fisico_de_partido"


def _half_max_vels(source_rows: list[dict]) -> tuple[float | None, float | None]:
    """Pluck max_vel_kmh from the half-period source rows. Returns
    (p1_value, p2_value). Either may be None if that half wasn't recorded.
    Partido Completo rows are intentionally ignored — they hold a bogus
    sum in the legacy data."""
    p1 = p2 = None
    for sr in source_rows:
        if not isinstance(sr, dict):
            continue
        mv = sr.get("max_vel_kmh")
        if mv is None:
            continue
        try:
            mv = float(mv)
        except (TypeError, ValueError):
            continue
        tipo = sr.get("tipo_evaluacion")
        if tipo == "Primer Tiempo":
            p1 = mv
        elif tipo == "Segundo Tiempo":
            p2 = mv
    return p1, p2


def _total_from_halves(p1: float | None, p2: float | None) -> float | None:
    """The honest 'full-match max' is the max across halves we have data
    for. Don't fall back to a single half label as the 'total' if both
    are present — that hides the half it came from."""
    if p1 is not None and p2 is not None:
        return max(p1, p2)
    return p1 if p1 is not None else p2


class Command(BaseCommand):
    help = "Repair GPS max_vel_* fields polluted by the legacy Partido Completo pivot."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually write the corrected values. Without this flag the "
                 "command just prints what would change.",
        )

    def handle(self, *args, **opts):
        apply_changes = opts["apply"]
        qs = ExamResult.objects.filter(template__slug=GPS_TEMPLATE_SLUG)
        total = qs.count()
        self.stdout.write(f"Scanning {total} GPS results …")

        no_sources = 0       # legacy_raw._source_rows absent — can't repair
        already_clean = 0    # values already match the half-source rows
        repaired = 0         # values changed
        sample_diffs: list[tuple[str, dict]] = []

        for r in qs.iterator():
            sources = (r.legacy_raw or {}).get("_source_rows")
            if not sources:
                no_sources += 1
                continue

            p1, p2 = _half_max_vels(sources)
            if p1 is None and p2 is None:
                # No half-period data at all — leave whatever's there
                # untouched (could be a legitimate non-match GPS row).
                no_sources += 1
                continue

            rd = dict(r.result_data or {})
            new_total = _total_from_halves(p1, p2)

            updates = {}
            if p1 is not None and rd.get("max_vel_p1") != p1:
                updates["max_vel_p1"] = p1
            if p2 is not None and rd.get("max_vel_p2") != p2:
                updates["max_vel_p2"] = p2
            if new_total is not None and rd.get("max_vel_total") != new_total:
                updates["max_vel_total"] = new_total

            if not updates:
                already_clean += 1
                continue

            repaired += 1
            if len(sample_diffs) < 5:
                sample_diffs.append((str(r.id), {
                    "before": {
                        k: rd.get(k) for k in ("max_vel_p1", "max_vel_p2", "max_vel_total")
                    },
                    "after": {
                        "max_vel_p1": p1 if p1 is not None else rd.get("max_vel_p1"),
                        "max_vel_p2": p2 if p2 is not None else rd.get("max_vel_p2"),
                        "max_vel_total": new_total,
                    },
                }))

            if apply_changes:
                rd.update(updates)
                r.result_data = rd
                r.save(update_fields=["result_data"])

        self.stdout.write("")
        self.stdout.write(f"  scanned:      {total}")
        self.stdout.write(f"  no sources:   {no_sources}")
        self.stdout.write(f"  already OK:   {already_clean}")
        self.stdout.write(self.style.WARNING(f"  to repair:    {repaired}"))

        if sample_diffs:
            self.stdout.write("")
            self.stdout.write("Sample diffs (first 5):")
            for rid, diff in sample_diffs:
                self.stdout.write(f"  {rid}")
                self.stdout.write(f"    before: {diff['before']}")
                self.stdout.write(f"    after:  {diff['after']}")

        self.stdout.write("")
        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Applied {repaired} repairs."))
        else:
            self.stdout.write(self.style.NOTICE(
                "DRY RUN — re-run with --apply to write the changes."
            ))
