"""Seed the club's anthropometry bands per category (formativo, masculino).

Source: the PF's table "Masculino" pinned in the club (photo of 2026-11-04):
Σ 6 pliegues, % masa adiposa, índice músculo-óseo and % masa muscular, for
Sub 13, Sub 14, Sub 15-16 and Sub 18-Proy. (Sub 18-Proy is applied to Sub 18
and Sub 20; "Proyección" has no category of its own.) Until now every formativo
player was judged with the field's single scale, which is the Primer Equipo's.

One BAND `AlertRule` per (category, field) of `pentacompartimental` with the
club's numbers in `config["ranges"]`. That is what the charts draw for the
category (`dashboards.category_bands`) and what fires alerts. The category rule
replaces the club-wide rule on the same field (`goals.evaluator`).

The table reads "< 45 mm" for the best band and "> 60 mm" for the worst. Bands
are listed worst-first so that a value exactly on a boundary lands in the worse
band (bounds are inclusive and the first match wins), which is what the strict
"<" / ">" of the table mean.

⚠️ The table leaves a gap in IMO Sub 18-Proy: Élite "> 4,3" but Profesional
"4,2 - 4". Here Profesional runs 4,0 – 4,3 so no value is left without a band.

    python manage.py seed_antropometria_bands            # plan
    python manage.py seed_antropometria_bands --commit
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Bracket, Club
from exams.models import ExamTemplate
from goals.models import AlertRule, AlertRuleKind, AlertSeverity

SLUG = "pentacompartimental"
GROUPS = {"Sub 13": (13,), "Sub 14": (14,), "Sub 15-16": (15, 16), "Sub 18-Proy": (18, 20)}
COLORS = {"best": "#16a34a", "good": "#86efac", "ok": "#f59e0b", "bad": "#dc2626"}

# field → (direction, labels best → worst, {group: (cut best|good, good|ok, ok|bad)}).
TABLE: dict[str, tuple[str, tuple[str, str, str, str], dict[str, tuple[float, float, float]]]] = {
    "suma_pliegues": ("down", ("Elite/Excelente", "Profesional/Bueno", "Aceptable", "Elevado"), {
        "Sub 13": (45, 55, 60), "Sub 14": (45, 55, 60), "Sub 15-16": (40, 50, 55), "Sub 18-Proy": (40, 50, 55)}),
    "masa_adiposa_pct": ("down", ("Elite/Excelente", "Profesional/Bueno", "Aceptable", "Elevado"), {
        "Sub 13": (20, 23, 26), "Sub 14": (20, 23, 26), "Sub 15-16": (18, 21, 25), "Sub 18-Proy": (16, 19, 23)}),
    "imo": ("up", ("Elite/Excelente", "Profesional/Bueno", "Aceptable", "Bajo"), {
        "Sub 13": (3.7, 3.5, 3.0), "Sub 14": (3.8, 3.6, 3.2), "Sub 15-16": (4.0, 3.8, 3.6), "Sub 18-Proy": (4.3, 4.0, 3.7)}),
    "masa_muscular_pct": ("up", ("Elite/Excelente", "Profesional/Bueno", "Aceptable", "Bajo"), {
        "Sub 13": (45, 43, 40), "Sub 14": (48, 45, 43), "Sub 15-16": (50, 48, 45), "Sub 18-Proy": (52, 50, 47)}),
}


def build_ranges(direction: str, labels: tuple[str, ...], cuts: tuple[float, float, float]) -> list[dict]:
    """Four bands, worst first (a boundary value belongs to the worse band)."""
    best, good, ok, bad = labels
    c1, c2, c3 = (float(c) for c in cuts)
    if direction == "down":       # less is better: < c1 best … > c3 bad
        return [{"label": bad, "min": c3, "color": COLORS["bad"]},
                {"label": ok, "min": c2, "max": c3, "color": COLORS["ok"]},
                {"label": good, "min": c1, "max": c2, "color": COLORS["good"]},
                {"label": best, "max": c1, "color": COLORS["best"]}]
    return [{"label": bad, "max": c3, "color": COLORS["bad"]},
            {"label": ok, "min": c3, "max": c2, "color": COLORS["ok"]},
            {"label": good, "min": c2, "max": c1, "color": COLORS["good"]},
            {"label": best, "min": c1, "color": COLORS["best"]}]


class Command(BaseCommand):
    help = "Bandas de antropometría por categoría (tabla del PF: Sub 13, 14, 15-16, 18-Proy)."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--season", type=int, default=None)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        from goals.evaluator import finalize_threshold_alerts_for_template
        from goals.management.commands.seed_formativo_bands import Command as FormativoBands

        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        template = (ExamTemplate.objects.filter(department__club=club, slug=SLUG)
                    .order_by("-is_active_version").first())
        if template is None:
            raise CommandError(f"El club no tiene la plantilla {SLUG}.")
        season = opts["season"] or timezone.localdate().year
        ladder = Bracket.ladder()
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("APLICADO" if opts["commit"] else "PLAN (sin cambios; usar --commit)"))
        created = updated = 0
        with transaction.atomic():
            for group, ages in GROUPS.items():
                cats = FormativoBands()._categorias(club, season, set(ages), ladder)
                cats = [c for c in cats if template.applicable_categories.filter(pk=c.pk).exists()]
                w(f"  {group}: {', '.join(c.name for c in cats) or '(ninguna categoría)'}")
                for field_key, (direction, labels, by_group) in TABLE.items():
                    ranges = build_ranges(direction, labels, by_group[group])
                    for cat in cats:
                        rule = AlertRule.objects.filter(template__family_id=template.family_id or template.id,
                                                        field_key=field_key, category=cat,
                                                        kind=AlertRuleKind.BAND).first()
                        if rule is None:
                            glob = AlertRule.objects.filter(template=template, field_key=field_key,
                                                            category=None, kind=AlertRuleKind.BAND).first()
                            rule = AlertRule(template=template, field_key=field_key, category=cat,
                                             kind=AlertRuleKind.BAND, scope={},
                                             severity=glob.severity if glob else AlertSeverity.WARNING)
                            created += 1
                        else:
                            updated += 1
                        # The staff's choice of which bands alert survives a re-seed.
                        trigger = (rule.config or {}).get("trigger_labels") or [labels[3]]
                        rule.config = {**(rule.config or {}), "ranges": ranges, "trigger_labels": trigger}
                        rule.full_clean(exclude=["template", "category"])
                        rule.save()
            w(f"  reglas creadas {created} · actualizadas {updated}")
            if opts["commit"]:
                stats = finalize_threshold_alerts_for_template(template)
                w(f"  alertas re-evaluadas: {stats}")
            else:
                transaction.set_rollback(True)
