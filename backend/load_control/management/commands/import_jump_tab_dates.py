"""Load the club's reviewed «pestaña → partido» table for the jump sheets.

    python manage.py import_jump_tab_dates --file Saltos_revisado.xlsx            # plan
    python manage.py import_jump_tab_dates --file Saltos_revisado.xlsx --commit

Reads sheet «Pestañas»: Equipo, Pestaña, Fecha propuesta, …, «Fecha correcta».
EVERY row is stored — the corrected date when given, "NO" as not-a-match, the
proposed one otherwise (the staff saw it and left it) — so a later alignment
never moves a date they reviewed. Then re-run `import_formativo_saltos`.
"""
from __future__ import annotations

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Club
from load_control.models import JumpTabMatch


def _parse(v) -> date | None | str:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = str(v).strip()
    if t.upper() == "NO":
        return "NO"
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"fecha ilegible: {t!r}")


class Command(BaseCommand):
    help = "Carga la tabla pestaña → partido revisada por el club (planillas de salto)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--season", type=int)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        import openpyxl

        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError("Club no encontrado.")
        season = opts["season"] or timezone.localdate().year
        ws = openpyxl.load_workbook(opts["file"], data_only=True)["Pestañas"]
        head = [str(c.value or "").strip().lower() for c in ws[1]]
        col = lambda prefix: next(i for i, h in enumerate(head) if h.startswith(prefix))
        i_team, i_tab, i_prop, i_fix = col("equipo"), col("pestaña"), col("fecha propuesta"), col("fecha correcta")
        rows, errors, corrected = [], [], 0
        for n, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            team, tab = str(r[i_team] or "").strip(), str(r[i_tab] or "").strip()
            if not team or not tab:
                continue
            try:
                fix, prop = _parse(r[i_fix]), _parse(r[i_prop])
            except ValueError as exc:
                errors.append(f"fila {n}: {exc}")
                continue
            if fix is not None:
                corrected += 1
            value = fix if fix is not None else prop
            if value is None:
                continue  # no proposal and no answer: nothing to store
            rows.append((team, tab, None if value == "NO" else value))
        self.stdout.write(f"{len(rows)} pestañas ({corrected} corregidas por el club) · errores {len(errors)}")
        for e in errors:
            self.stdout.write(self.style.WARNING(f"  {e}"))
        if opts["commit"] and not errors:
            with transaction.atomic():
                for team, tab, d in rows:
                    JumpTabMatch.objects.update_or_create(
                        club=club, team=team, season=season, tab=tab, defaults={"match_date": d})
            self.stdout.write(self.style.SUCCESS("Guardado. Re-correr import_formativo_saltos."))
        elif errors:
            self.stdout.write(self.style.ERROR("Hay errores: no se guardó nada."))
