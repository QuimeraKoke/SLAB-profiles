"""One-shot split of a club's combined GPS data into the live template pair.

Before: matches + trainings mixed in `gps_sesion`; a legacy per-half match
template (2025 season) and an empty legacy `gps_entrenamiento` template on the
side — three "GPS" definitions in the UI.

After: `gps_partido` (event-linked match sessions, flat keys) + `gps_sesion`
renamed "GPS Entrenamiento" (trainings only). The per-half template keeps its
results as an archive (its totals are copied into `gps_partido` so match
history is continuous) and disappears from the registrar panel because it is
bulk-ingest-only. The empty legacy training template is deleted when nothing
references it, else renamed "(legado)" and detached.

Idempotent — safe to re-run; every step skips what already happened.

    docker compose exec backend python manage.py split_gps_partido --dry-run
    docker compose exec backend python manage.py split_gps_partido
"""
from __future__ import annotations

import json
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from core.models import Department
from dashboards.models import WidgetDataSource
from exams.models import ExamResult, ExamTemplate
from exams.management.commands.seed_gps_partido import (
    INPUT_CONFIG as PARTIDO_INPUT_CONFIG,
    build_config_schema,
)

# Legacy per-half match keys → flat per-session keys. Only totals with an
# exact semantic counterpart are converted; per-half detail (`*_p1`/`*_p2`),
# the relative rates and the 70-85% band stay only on the archived per-half
# results.
PER_HALF_TO_PARTIDO: dict[str, str] = {
    "tot_dur_total": "tot_dur",
    "tot_dist_total": "tot_dist",
    "mpm_total": "mpm",
    "hsr_total": "hsr",
    "sprint_total": "sprint_dist",
    "dist_85_95_total": "zone_85_95",
    "acc_dec_total": "acc_dec",
    "acc_total": "acc",
    "dec_total": "dec",
    "max_vel_total": "max_vel",
    "hmld_total": "hmld",
    "player_load_total": "player_load",
    "hiaa_total": "hiaa",
}

# The same map for team-report widgets, where per-half keys collapse onto the
# flat key (a "primer tiempo" chart becomes a whole-match chart; duplicates
# are pruned afterwards).
PER_HALF_TEAM_MAP: dict[str, str] = {
    **PER_HALF_TO_PARTIDO,
    **{k.replace("_total", f"_{half}"): v
       for k, v in PER_HALF_TO_PARTIDO.items() for half in ("p1", "p2")},
}

# Legacy manual-training keys → per-session keys (identity except sprint;
# hsr_rel has no per-session counterpart).
LEGACY_TRAIN_TO_SESSION: dict[str, str] = {
    "tot_dur": "tot_dur", "tot_dist": "tot_dist", "mpm": "mpm", "hsr": "hsr",
    "sprint": "sprint_dist", "acc": "acc", "dec": "dec", "hmld": "hmld",
    "max_vel": "max_vel", "player_load": "player_load", "hiaa": "hiaa",
    "rpe": "rpe",
}


def convert_legacy_training(result_data: dict, recorded_at) -> dict:
    """Numeric payload of a legacy manual-training result in gps_sesion keys."""
    out: dict = {}
    for old_key, new_key in LEGACY_TRAIN_TO_SESSION.items():
        v = (result_data or {}).get(old_key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[new_key] = v
    out.update({
        "fecha": recorded_at.date().isoformat(),
        "sesion": (result_data or {}).get("sesion") or "",
        "tipo_sesion": "entrenamiento",
    })
    return out


def convert_per_half(result_data: dict) -> dict:
    """Numeric payload of a per-half match result in gps_partido keys."""
    out: dict = {}
    for old_key, new_key in PER_HALF_TO_PARTIDO.items():
        v = (result_data or {}).get(old_key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[new_key] = v
    return out


def remap_field_keys(keys: list[str], keymap: dict[str, str]) -> list[str]:
    """Translate widget field keys, dropping the ones with no counterpart."""
    return [keymap[k] for k in (keys or []) if k in keymap]


def remap_display_config(config: dict, keymap: dict[str, str]) -> dict:
    """Rewrite field keys wherever they appear in a widget's display_config
    (plain strings and lists of strings, e.g. `right_axis_keys`)."""
    out: dict = {}
    for k, v in (config or {}).items():
        if isinstance(v, str) and v in keymap:
            out[k] = keymap[v]
        elif isinstance(v, list):
            out[k] = [keymap.get(x, x) if isinstance(x, str) else x for x in v
                      if not (isinstance(x, str) and x.endswith("_total") and x not in keymap)]
        else:
            out[k] = v
    return out


class Command(BaseCommand):
    help = "Split a club's combined per-session GPS into gps_partido (matches) + gps_sesion (trainings)."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--department-slug", default="fisico")
        parser.add_argument("--train-name", default="GPS Entrenamiento")
        parser.add_argument("--match-name", default="GPS Partido")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-log", action="store_true")

    def handle(self, *args, **opts):
        dept = Department.objects.filter(
            club__name=opts["club"], slug=opts["department_slug"],
        ).select_related("club").first()
        if dept is None:
            raise CommandError(f"Department '{opts['department_slug']}' not found in '{opts['club']}'.")

        session_tpl = ExamTemplate.objects.filter(department=dept, slug="gps_sesion").first()
        if session_tpl is None:
            raise CommandError("Template 'gps_sesion' not found — nothing to split.")
        per_half_tpl = ExamTemplate.objects.filter(
            department=dept, slug="gps_rendimiento_fisico_de_partido",
        ).first()
        legacy_train_tpl = ExamTemplate.objects.filter(
            department=dept, slug="gps_entrenamiento",
        ).first()

        report: dict = {"club": dept.club.name, "dry_run": opts["dry_run"], "widgets": []}
        try:
            with transaction.atomic():
                self._split(dept, session_tpl, per_half_tpl, legacy_train_tpl, opts, report)
                if opts["dry_run"]:
                    transaction.set_rollback(True)
        except ProtectedError as exc:
            raise CommandError(f"Unexpected protected reference: {exc}")

        self._print(report)
        if not opts["no_log"] and not opts["dry_run"]:
            self._write_log(report)

    # ---- steps ----------------------------------------------------------

    def _split(self, dept, session_tpl, per_half_tpl, legacy_train_tpl, opts, report):
        # 1. The match template.
        partido_tpl = ExamTemplate.objects.filter(department=dept, slug="gps_partido").first()
        if partido_tpl is None:
            partido_tpl = ExamTemplate.objects.create(
                name=opts["match_name"], slug="gps_partido", department=dept,
                config_schema=build_config_schema(), input_config=PARTIDO_INPUT_CONFIG,
                link_to_match=True,
            )
            partido_tpl.applicable_categories.set(session_tpl.applicable_categories.all())
            partido_tpl.rebuild_template_fields()
            report["partido_template"] = "created"
        else:
            report["partido_template"] = "already exists"

        # 2. Move the event-linked (match) rows out of gps_sesion.
        moved = ExamResult.objects.filter(
            template__family_id=session_tpl.family_id, event__isnull=False,
        ).update(template=partido_tpl)
        report["moved_match_rows"] = moved

        # 3. Copy the legacy per-half totals in (archive rows stay put).
        converted = skipped_existing = 0
        if per_half_tpl is not None:
            taken = set(ExamResult.objects.filter(
                template__family_id=partido_tpl.family_id,
            ).values_list("player_id", "recorded_at__date"))
            to_create = []
            src = ExamResult.objects.filter(
                template__family_id=per_half_tpl.family_id,
            ).select_related("event")
            for r in src.iterator():
                key = (r.player_id, r.recorded_at.date())
                if key in taken:
                    skipped_existing += 1
                    continue
                taken.add(key)
                data = convert_per_half(r.result_data)
                data.update({
                    "fecha": r.recorded_at.date().isoformat(),
                    "sesion": (r.event.title if r.event else "")[:140],
                    "tipo_sesion": "partido",
                })
                to_create.append(ExamResult(
                    player_id=r.player_id, template=partido_tpl, event=r.event,
                    recorded_at=r.recorded_at, result_data=data, inputs_snapshot={},
                ))
            ExamResult.objects.bulk_create(to_create, batch_size=400)
            converted = len(to_create)
        report["converted_per_half_rows"] = converted
        report["skipped_existing_rows"] = skipped_existing

        # 4. gps_sesion becomes the training-only template.
        from exams.management.commands.seed_gps_session import CONFIG_SCHEMA as TRAIN_SCHEMA
        session_tpl.name = opts["train_name"]
        session_tpl.config_schema = TRAIN_SCHEMA
        session_tpl.link_to_match = False
        session_tpl.save()
        session_tpl.rebuild_template_fields()
        report["session_template"] = f"renamed to '{opts['train_name']}'"

        # 5. Copy legacy manual-training results into gps_sesion (originals
        # stay as archive; nothing reads their slug after the split).
        train_converted = train_skipped = 0
        if legacy_train_tpl is not None:
            taken = set(ExamResult.objects.filter(
                template__family_id=session_tpl.family_id,
            ).values_list("player_id", "recorded_at"))
            to_create = []
            src = ExamResult.objects.filter(template__family_id=legacy_train_tpl.family_id)
            for r in src.iterator():
                if (r.player_id, r.recorded_at) in taken:
                    train_skipped += 1
                    continue
                taken.add((r.player_id, r.recorded_at))
                to_create.append(ExamResult(
                    player_id=r.player_id, template=session_tpl,
                    recorded_at=r.recorded_at,
                    result_data=convert_legacy_training(r.result_data, r.recorded_at),
                    inputs_snapshot={},
                ))
            ExamResult.objects.bulk_create(to_create, batch_size=400)
            train_converted = len(to_create)
        report["converted_legacy_train_rows"] = train_converted
        report["skipped_legacy_train_rows"] = train_skipped

        # 6. Repoint this club's profile + team-report widget sources.
        if per_half_tpl is not None:
            self._repoint_sources(per_half_tpl, partido_tpl, PER_HALF_TO_PARTIDO, report)
            self._repoint_team_sources(per_half_tpl, partido_tpl, PER_HALF_TEAM_MAP, report)
        if legacy_train_tpl is not None:
            self._repoint_sources(legacy_train_tpl, session_tpl, LEGACY_TRAIN_TO_SESSION, report)
            self._repoint_team_sources(legacy_train_tpl, session_tpl, LEGACY_TRAIN_TO_SESSION, report)

        # 7. Retire the legacy training template (delete only if empty AND
        # unreferenced; otherwise archive in place).
        if legacy_train_tpl is not None:
            n_results = ExamResult.objects.filter(
                template__family_id=legacy_train_tpl.family_id,
            ).count()
            legacy_train_tpl.applicable_categories.clear()
            if n_results:
                if "(legado)" not in legacy_train_tpl.name:
                    legacy_train_tpl.name = f"{legacy_train_tpl.name} (legado)"
                    legacy_train_tpl.save(update_fields=["name"])
                report["legacy_train_template"] = (
                    f"archived — keeps {n_results} original results; renamed '(legado)' and detached"
                )
            else:
                try:
                    with transaction.atomic():
                        legacy_train_tpl.delete()
                    report["legacy_train_template"] = "deleted (empty, unreferenced)"
                except ProtectedError:
                    if "(legado)" not in legacy_train_tpl.name:
                        legacy_train_tpl.name = f"{legacy_train_tpl.name} (legado)"
                        legacy_train_tpl.save(update_fields=["name"])
                    report["legacy_train_template"] = (
                        "kept — still referenced; renamed '(legado)' and detached"
                    )

    def _repoint_team_sources(self, old_tpl, new_tpl, keymap, report):
        """Rebind team-report sources, collapsing per-half keys onto the flat
        whole-match keys, then prune widgets that became exact duplicates
        (e.g. a "primer tiempo" chart turning into a second copy of the
        totals chart) and any section that empties out."""
        from dashboards.models import TeamReportWidget, TeamReportWidgetDataSource

        half_derived: set = set()
        for ds in TeamReportWidgetDataSource.objects.filter(
            template=old_tpl,
        ).select_related("widget"):
            new_keys: list[str] = []
            for k in (ds.field_keys or []):
                nk = keymap.get(k)
                if nk and nk not in new_keys:
                    new_keys.append(nk)
            if not new_keys:
                report["widgets"].append({
                    "widget": ds.widget.title,
                    "action": "team source skipped — no mappable field keys",
                    "keys": ds.field_keys,
                })
                continue
            if any(k.endswith(("_p1", "_p2")) for k in (ds.field_keys or [])):
                half_derived.add(ds.widget_id)
            ds.template = new_tpl
            ds.field_keys = new_keys
            ds.save(update_fields=["template", "field_keys"])
            report["widgets"].append({
                "widget": ds.widget.title,
                "action": f"team source repointed to {new_tpl.slug}",
                "keys": new_keys,
            })

        widgets = list(
            TeamReportWidget.objects
            .filter(data_sources__template=new_tpl).distinct()
            .select_related("section")
            .prefetch_related("data_sources")
        )
        # Totals-native widgets win over half-derived ones with the same shape.
        widgets.sort(key=lambda w: (w.id in half_derived, w.section.sort_order, w.sort_order))
        seen: dict = {}
        for w in widgets:
            sig = (
                w.section.layout_id, w.chart_type,
                tuple(sorted(
                    (str(ds.template_id), tuple(ds.field_keys or []),
                     ds.aggregation, ds.aggregation_param)
                    for ds in w.data_sources.all()
                )),
            )
            if sig in seen:
                section = w.section
                report["widgets"].append({
                    "widget": w.title,
                    "action": f"deleted — duplicate of {seen[sig]!r} after per-half collapse",
                })
                w.delete()
                if not section.widgets.exists():
                    report["widgets"].append({
                        "widget": f"[section] {section.title}",
                        "action": "deleted — emptied by duplicate pruning",
                    })
                    section.delete()
            else:
                seen[sig] = w.title
                if w.id in half_derived:
                    cleaned = (w.title.replace(" — primer tiempo", "")
                               .replace(" — segundo tiempo", ""))
                    if cleaned != w.title:
                        w.title = cleaned
                        w.save(update_fields=["title"])
                    # A surviving half-section now shows whole-match data —
                    # its "Primer/Segundo tiempo" title would lie.
                    if w.section.title in ("Primer tiempo", "Segundo tiempo"):
                        report["widgets"].append({
                            "widget": f"[section] {w.section.title}",
                            "action": "retitled 'Detalle por jugador' — now shows whole-match data",
                        })
                        w.section.title = "Detalle por jugador"
                        w.section.save(update_fields=["title"])

    def _repoint_sources(self, old_tpl, new_tpl, keymap, report):
        sources = WidgetDataSource.objects.filter(template=old_tpl).select_related("widget")
        for ds in sources:
            new_keys = remap_field_keys(ds.field_keys, keymap)
            if not new_keys:
                report["widgets"].append({
                    "widget": ds.widget.title, "action": "skipped — no mappable field keys",
                    "keys": ds.field_keys,
                })
                continue
            dropped = [k for k in (ds.field_keys or []) if k not in keymap]
            ds.template = new_tpl
            ds.field_keys = new_keys
            ds.save(update_fields=["template", "field_keys"])
            w = ds.widget
            new_config = remap_display_config(w.display_config, keymap)
            if new_config != (w.display_config or {}):
                w.display_config = new_config
                w.save(update_fields=["display_config"])
            report["widgets"].append({
                "widget": w.title, "action": f"repointed to {new_tpl.slug}",
                "keys": new_keys, "dropped": dropped,
            })

    # ---- output ----------------------------------------------------------

    def _print(self, r):
        tag = "DRY-RUN — " if r["dry_run"] else ""
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{tag}split_gps_partido [{r['club']}]"))
        for k in ("partido_template", "moved_match_rows", "converted_per_half_rows",
                  "skipped_existing_rows", "converted_legacy_train_rows",
                  "skipped_legacy_train_rows", "session_template", "legacy_train_template"):
            if k in r:
                self.stdout.write(f"  {k}: {r[k]}")
        for w in r["widgets"]:
            extra = f" (dropped {w['dropped']})" if w.get("dropped") else ""
            self.stdout.write(f"  widget {w['widget']!r}: {w['action']}{extra}")
        if not r["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                "  done. Consider `rebuild_player_state` to refresh materialized load."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("  (nothing written)"))

    def _write_log(self, report):
        import os
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        out_dir = os.path.join(settings.BASE_DIR, "migration_runs")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"split-gps-partido-{ts}.json")
        with open(out, "w") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
        self.stdout.write(f"  run log: {out}")
