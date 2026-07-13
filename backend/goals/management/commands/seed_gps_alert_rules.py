"""Starter alert rules for the per-session GPS template (`gps_sesion`) — §1.2.

An **intra-individual** default set the club can tune/extend in the in-app
editor (1.g). These compare each player to *himself*, so they need no
club-specific configuration:

  * `zscore` vs. a 28-day rolling basal (spike detection) on the *per-minute*
    intensity rates (hsr_min / sprint_dist_min / acc_dec_min) — duration-
    normalized so a short session isn't judged on raw volume — scoped to
    training sessions (entrenamiento / tareas).
  * `pct_match` on HSR *volume* — training HSR ≥ 85 % of the player's own
    match demand.

Absolute per-línea (`by_role`) thresholds are intentionally NOT seeded here —
those are club-specific and belong in the editor. Idempotent: keyed on
(template, field_key, kind, category). Re-runs create only what's missing and
leave admin-tuned rules alone.

    docker compose exec backend python manage.py seed_gps_alert_rules \\
        [--club "Universidad de Chile"] [--category "Primer Equipo"] [--no-backfill]
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from goals.models import AlertRule, AlertRuleKind, AlertSeverity

_TRAINING = ["entrenamiento", "tareas"]

_ZSCORE_CFG = {"window": {"kind": "timedelta", "days": 28}, "threshold_z": 2,
               "direction": "increase", "method": "moving_avg"}

RULES = [
    {"field_key": "hsr_min", "kind": AlertRuleKind.ZSCORE, "severity": AlertSeverity.WARNING,
     "config": _ZSCORE_CFG, "scope": {"session_types": _TRAINING}},
    {"field_key": "sprint_dist_min", "kind": AlertRuleKind.ZSCORE, "severity": AlertSeverity.WARNING,
     "config": _ZSCORE_CFG, "scope": {"session_types": _TRAINING}},
    {"field_key": "acc_dec_min", "kind": AlertRuleKind.ZSCORE, "severity": AlertSeverity.WARNING,
     "config": _ZSCORE_CFG, "scope": {"session_types": _TRAINING}},
    {"field_key": "hsr", "kind": AlertRuleKind.PCT_MATCH, "severity": AlertSeverity.WARNING,
     "config": {"ratio_upper": 0.85}, "scope": {"session_types": _TRAINING}},
]


class Command(BaseCommand):
    help = "Seed the intra-individual GPS (gps_sesion) alert rules + backfill latest results."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None, help="Restrict to one club (name).")
        parser.add_argument("--category", default=None, help="Restrict rules to one category (name).")
        parser.add_argument("--no-backfill", action="store_true",
                            help="Create rules only; don't evaluate the latest results.")

    @transaction.atomic
    def handle(self, *args, **opts):
        from core.models import Category, Player
        from exams.models import ExamResult, ExamTemplate
        from goals.evaluator import evaluate_threshold_rules_for_result

        templates = ExamTemplate.objects.filter(slug="gps_sesion", is_active_version=True)
        if opts["club"]:
            templates = templates.filter(department__club__name=opts["club"])
        if not templates.exists():
            self.stdout.write(self.style.WARNING("No gps_sesion template found — nothing to do."))
            return

        for template in templates:
            club = template.department.club
            cats = template.applicable_categories.all()
            if opts["category"]:
                cats = cats.filter(name=opts["category"])
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{club.name} — {template.name}"))

            # category=None means "all categories on this template" — but the
            # doctor asked per-category tuning, so we scope each rule to a
            # category (create one rule per applicable category unless --category).
            targets = list(cats) if opts["category"] else [None]
            created = 0
            for spec in RULES:
                for cat in targets:
                    _, was_created = AlertRule.objects.get_or_create(
                        template=template, field_key=spec["field_key"],
                        kind=spec["kind"], category=cat,
                        defaults={
                            "config": spec["config"], "scope": spec["scope"],
                            "severity": spec["severity"], "is_active": True,
                        },
                    )
                    created += int(was_created)
                    label = cat.name if cat else "todas las categorías"
                    flag = "creada" if was_created else "ya existía"
                    self.stdout.write(f"  {spec['kind']} · {spec['field_key']} · {label} — {flag}")

            if opts["no_backfill"]:
                continue

            # Backfill: evaluate each player's latest gps_sesion result so
            # alerts appear immediately (visible in the navbar / Alertas tab).
            player_qs = Player.objects.filter(is_active=True)
            if opts["category"]:
                player_qs = player_qs.filter(category__name=opts["category"], category__club=club)
            else:
                player_qs = player_qs.filter(category__club=club)
            fired = 0
            for player in player_qs.select_related("category", "position"):
                latest = (
                    ExamResult.objects.filter(player=player, template=template)
                    .order_by("-recorded_at").first()
                )
                if latest is not None:
                    fired += len(evaluate_threshold_rules_for_result(latest))
            self.stdout.write(self.style.SUCCESS(f"  backfill: {fired} alert(s) fired/refreshed"))

        self.stdout.write(self.style.SUCCESS("\nDone."))
