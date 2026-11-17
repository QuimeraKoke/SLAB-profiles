"""Demo data for Resumen / Disponibilidad on the DEMO club (tutorial videos).

"¿Cómo llega cada jugador a entrenar hoy?" needs, relative to today:
  - today's check-in (and Monday's): most answer, a few don't; two with pain,
    two with low items, one with a cold,
  - the jumps of the last matches (control_salto, PRE/POST), three players
    hit hard by the last one,
  - this week planned and published (Control de carga, the same % as the
    "Programar la carga semanal" video) and its training GPS following the
    plan, except three players who stray from it (two over, one under),
    plus the earlier weeks' training GPS,
  - the injured players' episodes moved to recent dates (the seed's were
    from June, "vencido hace 126 días").

Runs on top of `seed_demo_carga` (matches + match GPS + Sub 20 season), which
it calls first. Copies the check-in and jump templates from the club that has
them when the demo club does not. Idempotent: rows marked origen=demo_daily
are deleted and rebuilt.

    python manage.py seed_demo_daily            # dry run
    python manage.py seed_demo_daily --commit
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, time, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Category, Club, Player
from exams.models import Episode, ExamResult, ExamTemplate
from load_control import planning
from load_control.defaults import GroupResolver, merged
from load_control.management.commands.seed_demo_carga import _posicion
from load_control.models import MicrocycleDay
from load_control.planning import team_for
from load_control.reference import day_targets
from load_control.services import open_microcycle

CLUB = "Selección Chilena"
ORIGEN = "demo_daily"
HOJA = "U20"
ITEMS = ("calidad_sueno", "nivel_fatiga", "nivel_estres", "estado_animo", "dano_muscular")

# What today's check-in says, by player (last name). Everyone else: fine.
HOY = {
    "Arces": {"dolor_muscular": "Isquiotibiales Der.", "dano_muscular": 3},
    "Montes": {"dolor_muscular": "Tobillo Izq."},
    "Loyola": {"calidad_sueno": 2, "estado_animo": 3},
    "Reichmuth": {"nivel_fatiga": 2, "dano_muscular": 2},
    "Salinas": {"sintomas": "Resfriado"},
}
SIN_CHECKIN = ("Osorio", "Pérez", "Ulloa")         # answered Monday, not today
GOLPE = {"Echeverría": -9.0, "Tapia": -7.5, "Reichmuth": -11.0}  # last match jump drop %
# This week's training vs the plan: everyone else within ±5 %.
FUERA_DE_PLAN = {"Maripán": 1.25, "Faúndez": 1.10, "Millán": 0.78}
# Illustrative % per training day (DT, HSR, Sprint, ACC, DEC): a demo, not advice.
PLAN = {"MD+2": [40, 20, 10, 40, 40], "MD+3": [60, 50, 40, 70, 70], "MD-3": [70, 60, 50, 80, 80],
        "MD-2": [55, 70, 80, 50, 50], "MD-1": [35, 30, 30, 30, 30]}
METRICAS = ["tot_dist", "hsr", "sprint_dist", "acc", "dec"]
# The injured: (days since diagnosis, days to the expected return).
LESION = {"Sierralta": (12, 10), "Morales": (20, 4), "Cepeda": (25, 3),
          "Pizarro": (15, 6), "Méndez": (30, 2)}


def _clone(slug: str, club: Club, department, category) -> ExamTemplate:
    tpl = ExamTemplate.objects.filter(slug=slug, department__club=club, is_active_version=True).first()
    if tpl:
        return tpl
    src = (ExamTemplate.objects.filter(slug=slug, is_active_version=True).exclude(department__club=club)
           .order_by("created_at").first())
    if src is None:
        raise CommandError(f"Ningún club tiene la plantilla «{slug}» para copiarla.")
    tpl = ExamTemplate.objects.create(
        name=src.name, slug=slug, department=department, config_schema=src.config_schema,
        input_config=src.input_config, family_id=uuid.uuid4(), version=1, is_active_version=True,
        link_to_match=src.link_to_match)
    tpl.applicable_categories.set([category])
    return tpl


class Command(BaseCommand):
    help = "Seed Resumen/Disponibilidad demo data (check-in, jumps, training GPS) on the demo club."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, commit=False, **opts):
        club = Club.objects.filter(name=CLUB).first()
        if club is None:
            raise CommandError(f"No existe el club demo «{CLUB}».")
        category = Category.objects.filter(club=club).order_by("name").first()
        sesion = ExamTemplate.objects.filter(slug="gps_sesion", department__club=club, is_active_version=True).first()
        if category is None or sesion is None:
            raise CommandError("El club demo necesita una categoría y la plantilla gps_sesion.")
        if commit:
            call_command("seed_demo_carga", commit=True, stdout=self.stdout)

        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        saturdays = [monday - timedelta(days=2 + 7 * k) for k in range(4)][::-1]
        rng = random.Random(17)
        at = lambda d, h=8: timezone.make_aware(datetime.combine(d, time(h)))  # noqa: E731

        with transaction.atomic():
            checkin = _clone("checkin_formativo", club, sesion.department, category)
            salto = _clone("control_salto", club, sesion.department, category)
            ExamResult.objects.filter(template__in=[checkin, salto, sesion],
                                      result_data__origen=ORIGEN).delete()

            players = list(Player.objects.filter(category=category, is_active=True)
                           .select_related("position").order_by("last_name"))
            by_last = {p.last_name: p for p in players}
            for name in [*HOY, *SIN_CHECKIN, *GOLPE, *FUERA_DE_PLAN, *LESION]:
                if name not in by_last:
                    raise CommandError(f"No está el jugador «{name}» en el club demo.")
            out = {by_last[n].id for n in LESION}
            keepers = {p.id for p in players if p.position and p.position.name == "Arquero"}
            rows = []
            # Who played each match, and how long (seed_demo_carga's match GPS).
            played = {(pid, timezone.localtime(rec).date()): (data or {}).get("tot_dur") or 0
                      for pid, rec, data in ExamResult.objects.filter(
                          template__slug="gps_partido", player__in=players, result_data__origen="demo_carga",
                      ).values_list("player_id", "recorded_at", "result_data")}
            for name in GOLPE:
                if played.get((by_last[name].id, saturdays[-1]), 0) < 60:
                    raise CommandError(f"«{name}» no jugó el último partido: elige otro para el golpe.")

            # ── Check-in: Monday (everyone available) and today ─────────────
            for p in players:
                if p.id in out:
                    continue
                for d in (monday, today) if today != monday else (today,):
                    if d == today and p.last_name in SIN_CHECKIN:
                        continue
                    data = {k: rng.choice([4, 4, 5]) for k in ITEMS}
                    data.update({"peso": round(rng.uniform(64, 82), 1), "origen": ORIGEN})
                    if d == today:
                        data.update(HOY.get(p.last_name, {}))
                    rows.append(ExamResult(template=checkin, player=p, recorded_at=at(d, 8), result_data=data))

            # ── Jumps: PRE (MD-1) / POST (MD+1) of the last four matches ──
            for p in players:
                if p.id in out or p.id in keepers:
                    continue
                basal = rng.uniform(1.55, 2.05)
                for i, sat in enumerate(saturdays):
                    if not played.get((p.id, sat)):
                        continue  # jumps only around a match he played
                    pre = basal * rng.uniform(0.97, 1.03)
                    last = i == len(saturdays) - 1
                    drop = GOLPE.get(p.last_name) if last else None
                    post = pre * (1 + (drop if drop is not None else rng.uniform(-3.5, 4)) / 100)
                    rows.append(ExamResult(template=salto, player=p, recorded_at=at(sat, 0), result_data={
                        "origen": ORIGEN, "test": "rcmj", "rsi_metodo": "rebote / contacto",
                        "rsi_pre_best": round(pre, 3), "rsi_pre_mean": round(pre * 0.985, 3),
                        "rsi_post_best": round(post, 3), "rsi_post_mean": round(post * 0.985, 3),
                        "rival": ["ARGENTINA", "URUGUAY", "PARAGUAY", "BOLIVIA"][i],
                        "equipo_hoja": HOJA, "hoja": f"M{i + 1}", "fecha_fuente": "partido",
                        "fecha_partido": sat.isoformat(),
                    }))

            # ── Training GPS: Mon–Fri of the last four weeks ──────────────
            for p in players:
                usual = rng.uniform(4800, 5600)
                for k in range(1, 29):
                    d = today - timedelta(days=k)
                    if d.weekday() >= 5 or d >= monday:
                        continue  # this week follows the plan, below
                    if p.id in out and k <= 20:
                        continue  # out injured: no field work lately
                    dist = usual * rng.uniform(0.92, 1.08)
                    rows.append(ExamResult(template=sesion, player=p, recorded_at=at(d, 11), result_data={
                        "origen": ORIGEN, "origen_hoja": HOJA, "tipo_sesion": "entrenamiento",
                        "fecha": d.isoformat(), "tot_dur": round(rng.uniform(70, 90), 1),
                        "tot_dist": round(dist), "hsr": round(dist * 0.06), "sprint_dist": round(dist * 0.018),
                        "acc": round(dist / 130), "dec": round(dist / 125),
                    }))
                # Match day for whoever played little or nothing: the
                # compensatory session, as the staff does.
                for sat in saturdays:
                    mins = played.get((p.id, sat), 0)
                    if p.id in out or mins >= 60 or (today - sat).days > 28:
                        continue
                    dist = 9500 * (90 - mins) / 90 * rng.uniform(0.9, 1.05)
                    rows.append(ExamResult(template=sesion, player=p, recorded_at=at(sat, 12), result_data={
                        "origen": ORIGEN, "origen_hoja": HOJA, "tipo_sesion": "compensatorio",
                        "fecha": sat.isoformat(), "tot_dur": round(60 * (90 - mins) / 90, 1),
                        "tot_dist": round(dist), "hsr": round(dist * 0.07), "sprint_dist": round(dist * 0.02),
                        "acc": round(dist / 130), "dec": round(dist / 125),
                    }))
            ExamResult.objects.bulk_create(rows)

            # ── This week: planned, published, trained to the plan ────────
            team = team_for(category)
            sunday = monday + timedelta(days=6)
            mc = planning.create(team, start=monday, end=sunday, number=1, kind="")
            days = []
            for d in mc.days.order_by("date"):
                kind = MicrocycleDay.KIND_REST if d.date == sunday else d.kind
                pct = PLAN.get(d.md_label) if kind == MicrocycleDay.KIND_TRAINING else None
                days.append({"date": d.date, "kind": kind,
                             "targets_pct": dict(zip(METRICAS, pct)) if pct else {}})
            planning.update(mc, days=days)
            open_microcycle(mc)
            # Each player's group as the match GPS has it (seed_demo_carga's rule).
            everyone = list(Player.objects.filter(category=category).select_related("position")
                            .order_by("last_name", "first_name"))
            hoja = {p.id: _posicion(p.position.name if p.position else "", i) for i, p in enumerate(everyone)}
            resolver = GroupResolver(merged())
            week = []
            for day in mc.days.filter(date__gte=monday, date__lte=today, kind=MicrocycleDay.KIND_TRAINING):
                targets = day_targets(mc, day)
                for p in players:
                    group = resolver.group({"posicion_hoja": hoja[p.id]}, None)
                    tg = targets.get(group) or {}
                    if p.id in out or not tg:
                        continue
                    factor = FUERA_DE_PLAN.get(p.last_name) or rng.uniform(0.96, 1.04)
                    data = {m: round(tg[m] * factor * rng.uniform(0.98, 1.02))
                            for m in METRICAS if tg.get(m) is not None}
                    week.append(ExamResult(template=sesion, player=p, recorded_at=at(day.date, 11), result_data={
                        "origen": ORIGEN, "origen_hoja": HOJA, "tipo_sesion": "entrenamiento",
                        "posicion_hoja": hoja[p.id], "fecha": day.date.isoformat(),
                        "tot_dur": round(rng.uniform(70, 90), 1), **data}))
            ExamResult.objects.bulk_create(week)
            rows += week

            # ── Injuries to recent dates ──────────────────────────────────
            moved = 0
            for name, (since, back) in LESION.items():
                ep = (Episode.objects.filter(player=by_last[name], status=Episode.STATUS_OPEN,
                                             template__slug="lesiones").order_by("-started_at").first())
                if ep is None:
                    continue
                diagnosed = today - timedelta(days=since)
                Episode.objects.filter(pk=ep.pk).update(started_at=at(diagnosed, 10))
                for r in ExamResult.objects.filter(episode=ep):
                    r.result_data = {**(r.result_data or {}), "diagnosed_at": diagnosed.isoformat(),
                                     "expected_return_date": (today + timedelta(days=back)).isoformat()}
                    r.recorded_at = at(diagnosed, 10)
                    r.save(update_fields=["result_data", "recorded_at"])
                moved += 1

            self.stdout.write(f"{len(rows)} filas (check-in, saltos, GPS) · {moved} lesiones al día de hoy.")
            if not commit:
                transaction.set_rollback(True)
                self.stdout.write("Dry run: nada guardado (usa --commit).")
