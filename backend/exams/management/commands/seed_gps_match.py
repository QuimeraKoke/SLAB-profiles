"""Create / overwrite a GPS match-physical-performance template.

Models the metric set in the sample GPS export ('AguArc', 'FabHor', ...
two rows per starter: 'Primer Tiempo' / 'Segundo Tiempo'). Run with:

    docker compose exec backend python manage.py seed_gps_match \\
        --create-if-missing --department-slug fisico \\
        --all-applicable-categories

Most metrics aggregate as `sum` (distances, durations, counts). `Max Vel`
uses `max`. Rate fields (m/min) are intentionally `none`; their full-match
values are derived in `extra_fields` from the corresponding totals so we
get a duration-weighted rate instead of a naive average of segment rates.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate
from exams.template_builders import Metric, Segment, build_segmented_fields


SEGMENTS: list[Segment] = [
    Segment(suffix="p1", label="Primer tiempo"),
    Segment(suffix="p2", label="Segundo tiempo"),
]

METRICS: list[Metric] = [
    Metric(key="tot_dur",     label="Duración",            unit="min",   group="Carga",     aggregate="sum",  chart_type="line"),
    Metric(key="tot_dist",    label="Distancia total",     unit="m",     group="Distancia", aggregate="sum",  chart_type="line"),
    Metric(key="hsr",         label="HSR > 19,8 km/h",     unit="m",     group="Distancia", aggregate="sum",  chart_type="line"),
    Metric(key="sprint",      label="Sprint > 25 km/h",    unit="m",     group="Distancia", aggregate="sum",  chart_type="line"),
    Metric(key="dist_70_85",  label="Dist. 70-85% Vmax",   unit="m",     group="Distancia", aggregate="sum"),
    Metric(key="dist_85_95",  label="Dist. 85-95% Vmax",   unit="m",     group="Distancia", aggregate="sum"),
    Metric(key="acc_dec",     label="Acc + Dec ≥3",        unit="n",     group="Aceleración", aggregate="sum"),
    Metric(key="acc",         label="Acc ≥3",              unit="n",     group="Aceleración", aggregate="sum"),
    Metric(key="dec",         label="Dec ≥3",              unit="n",     group="Aceleración", aggregate="sum"),
    Metric(key="max_vel",     label="Vel. máxima",         unit="km/h",  group="Velocidad", aggregate="max",  chart_type="line"),
    Metric(key="hiaa",        label="HIAA",                unit="n",     group="Carga",     aggregate="sum"),
    Metric(key="hmld",        label="HMLD",                unit="m",     group="Distancia", aggregate="sum"),
    Metric(key="player_load", label="Player Load",         unit="a.u.",  group="Carga",     aggregate="sum",  chart_type="line"),
    # Rate metrics — keep per-segment values, skip naive aggregation.
    Metric(key="mpm",         label="Metros por minuto",   unit="m/min", group="Ritmo",     aggregate="none"),
    Metric(key="hsr_rel",     label="HSR relativo",        unit="m/min", group="Ritmo",     aggregate="none"),
    Metric(key="sprint_rel",  label="Sprint relativo",     unit="m/min", group="Ritmo",     aggregate="none"),
]

# Duration-weighted rate totals — cross-field formulas the helper can't express.
EXTRA_FIELDS: list[dict] = [
    {
        "key": "mpm_total", "label": "Metros por minuto (total)",
        "type": "calculated", "unit": "m/min", "group": "Ritmo",
        "formula": "[tot_dist_total] / [tot_dur_total]",
    },
    {
        "key": "hsr_rel_total", "label": "HSR relativo (total)",
        "type": "calculated", "unit": "m/min", "group": "Ritmo",
        "formula": "[hsr_total] / [tot_dur_total]",
    },
    {
        "key": "sprint_rel_total", "label": "Sprint relativo (total)",
        "type": "calculated", "unit": "m/min", "group": "Ritmo",
        "formula": "[sprint_total] / [tot_dur_total]",
    },
]

# Maps the actual columns in the GPS export onto the template. Header strings
# are matched after `.strip()` during ingest, so the leading-space quirk on
# " HSR rel (m/min)" is stored verbatim and the parser tolerates it either way.
COLUMN_MAPPING: dict = {
    "player_lookup": {"column": "Players", "kind": "alias"},
    "session_label": {"column": "Sessions"},
    "segment": {
        "column": "Tasks",
        "values": {
            "Primer Tiempo": "p1",
            "Segundo Tiempo": "p2",
        },
    },
    "field_map": {
        "Tot Dur (m)":                 {"template_key_pattern": "tot_dur_{segment}"},
        "Tot Dist (m)":                {"template_key_pattern": "tot_dist_{segment}"},
        "Meterage Per Minute":         {"template_key_pattern": "mpm_{segment}"},
        "Distancia HSR > 19,8 km/h":   {"template_key_pattern": "hsr_{segment}"},
        " HSR rel (m/min)":            {"template_key_pattern": "hsr_rel_{segment}"},
        "Distancia Sprint > 25 km/h":  {"template_key_pattern": "sprint_{segment}"},
        "Sprint rel (m/min)":          {"template_key_pattern": "sprint_rel_{segment}"},
        "70-85% V max (m)":            {"template_key_pattern": "dist_70_85_{segment}"},
        "85-95% V max (m)":            {"template_key_pattern": "dist_85_95_{segment}"},
        "Acc&Dec +3":                  {"template_key_pattern": "acc_dec_{segment}"},
        "Acc +3":                      {"template_key_pattern": "acc_{segment}"},
        "Dec +3":                      {"template_key_pattern": "dec_{segment}"},
        "Max Vel (km/h)":              {"template_key_pattern": "max_vel_{segment}"},
        "HIAA":                        {"template_key_pattern": "hiaa_{segment}"},
        "HMLD (m)":                    {"template_key_pattern": "hmld_{segment}"},
        "Player Load (a.u.)":          {"template_key_pattern": "player_load_{segment}"},
    },
}

INPUT_CONFIG: dict = {
    "input_modes": ["bulk_ingest"],
    "default_input_mode": "bulk_ingest",
    "modifiers": {"prefill_from_last": False},
    "column_mapping": COLUMN_MAPPING,
}


class Command(BaseCommand):
    help = "Seed / overwrite the GPS match-physical-performance template."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="GPS – Rendimiento físico de partido",
                            help="Template name to seed (default: GPS – Rendimiento físico de partido).")
        parser.add_argument("--club", default=None,
                            help="Restrict to a single club name.")
        parser.add_argument("--department-slug", default="fisico",
                            help="Department slug to attach the template to (default: fisico).")
        parser.add_argument("--create-if-missing", action="store_true",
                            help="Create the template if no match exists.")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="When creating, attach to every category that has the target department.")
        parser.add_argument("--unlock", action="store_true",
                            help="Clear is_locked before overwriting (only meaningful if results exist).")

    @transaction.atomic
    def handle(self, *args, **opts):
        name: str = opts["name"]
        club_name: str | None = opts["club"]
        dept_slug: str = opts["department_slug"]

        clubs = Club.objects.all()
        if club_name:
            clubs = clubs.filter(name=club_name)
        if not clubs.exists():
            raise CommandError("No clubs match the filter.")
        if club_name is None and clubs.count() > 1:
            raise CommandError("Multiple clubs exist; pass --club to disambiguate.")

        config_schema = {
            "fields": build_segmented_fields(
                METRICS, SEGMENTS, extra_fields=EXTRA_FIELDS,
            ),
        }

        for club in clubs:
            department = Department.objects.filter(club=club, slug=dept_slug).first()
            if not department:
                self.stdout.write(self.style.WARNING(
                    f"[{club.name}] no department with slug '{dept_slug}' — skipping."
                ))
                continue

            template = ExamTemplate.objects.filter(name=name, department=department).first()
            if not template:
                if not opts["create_if_missing"]:
                    self.stdout.write(self.style.WARNING(
                        f"[{club.name}] template '{name}' not found and --create-if-missing not set — skipping."
                    ))
                    continue
                template = ExamTemplate.objects.create(
                    name=name, department=department,
                    config_schema=config_schema, input_config=INPUT_CONFIG,
                    # GPS match results are intrinsically per-match —
                    # without an Event link the per-half / per-match
                    # reporting can't aggregate correctly.
                    link_to_match=True,
                )
                if opts["all_applicable_categories"]:
                    cats = Category.objects.filter(club=club, departments=department)
                    template.applicable_categories.set(cats)
                self.stdout.write(self.style.SUCCESS(
                    f"[{club.name}] created template '{name}' "
                    f"({len(config_schema['fields'])} fields, {template.applicable_categories.count()} categories, "
                    f"input_modes={INPUT_CONFIG['input_modes']})."
                ))
                continue

            if template.is_locked and not opts["unlock"]:
                self.stdout.write(self.style.WARNING(
                    f"[{club.name}] template '{name}' is locked — pass --unlock to overwrite."
                ))
                continue
            template.config_schema = config_schema
            template.input_config = INPUT_CONFIG
            template.link_to_match = True
            if opts["unlock"]:
                template.is_locked = False
            template.save(update_fields=[
                "config_schema", "input_config", "link_to_match",
                "is_locked", "updated_at",
            ])
            self.stdout.write(self.style.SUCCESS(
                f"[{club.name}] updated template '{name}' "
                f"({len(config_schema['fields'])} fields, input_modes={INPUT_CONFIG['input_modes']})."
            ))
