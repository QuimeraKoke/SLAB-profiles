"""Import the club's jump-control sheets into `control_salto`.

    python manage.py import_formativo_saltos                       # plan, every sheet in settings
    python manage.py import_formativo_saltos --sheet <id> --commit
    python manage.py import_formativo_saltos --file U20.xlsx       # an export

Each document is read in ONE request (Sheets quota is shared with the prod
syncs). Dates: title > club's reviewed table (`import_jump_tab_dates`) >
alignment — see `exams.formativo_saltos_ingest`.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams import formativo_saltos_ingest as ing


class Command(BaseCommand):
    help = "Importa las planillas de control de salto (PRE / POST partido) del formativo."

    def add_arguments(self, parser):
        parser.add_argument("--sheet", action="append", dest="sheets", default=[])
        parser.add_argument("--file", action="append", dest="files", default=[])
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--season", type=int)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError("Club no encontrado.")
        origins = opts["files"] + opts["sheets"] or list(settings.FORMATIVO_SALTOS_SHEET_IDS)
        if not origins:
            raise CommandError("Sin planillas: --sheet, --file o FORMATIVO_SALTOS_SHEET_IDS.")
        mode = "APLICADO" if opts["commit"] else "PLAN (sin cambios; usar --commit)"
        self.stdout.write(self.style.MIGRATE_HEADING(mode))
        for origin in origins:
            try:
                rep = ing.run(origin, club, season=opts["season"], commit=opts["commit"],
                              creds_file=getattr(settings, "GOOGLE_SHEETS_CREDENTIALS_FILE", ""),
                              creds_json=getattr(settings, "GOOGLE_SHEETS_CREDENTIALS_JSON", ""))
            except ValueError as exc:
                self.stdout.write(self.style.WARNING(f"  {origin}: {exc}"))
                continue
            self.stdout.write(
                f"  {rep.documento} ({rep.equipo}): {rep.pestanas} pestañas con datos · fechas "
                f"{dict(rep.por_fuente)} · sin partido {len(rep.pestanas_sin_partido)} · "
                f"nuevas {rep.creados} · actualizadas {rep.actualizados} · iguales {rep.sin_cambios} · "
                f"sin jugador {len(rep.sin_jugador)}")
            for line in rep.sin_jugador[:40]:
                self.stdout.write(f"      ? {line}")
