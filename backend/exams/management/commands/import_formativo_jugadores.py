"""Birth date, foot and photo from the formativo's player register (tab
JUGADORES). Thin CLI over `exams.formativo_jugadores`; dry-run by default.

    docker compose exec backend python manage.py import_formativo_jugadores           # plan
    docker compose exec backend python manage.py import_formativo_jugadores --commit
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams import formativo_jugadores as ing


class Command(BaseCommand):
    help = "Nacimiento, pie hábil y foto desde la hoja JUGADORES del formativo."

    def add_arguments(self, parser):
        parser.add_argument("--file", dest="origen", default=settings.FORMATIVO_EVAL_SHEET_ID,
                            help="Id de la Google Sheet (por defecto FORMATIVO_EVAL_SHEET_ID) o .xlsx")
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--sin-fotos", action="store_true")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        if not opts["origen"]:
            raise CommandError("Falta --file (o FORMATIVO_EVAL_SHEET_ID).")
        rep = ing.run(opts["origen"], club, commit=opts["commit"], fotos=not opts["sin_fotos"],
                      creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
                      creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("APLICADO" if opts["commit"] else "SIMULACIÓN"))
        w(f"  filas en la hoja        : {rep.filas}")
        w(f"  nacimiento completado   : {rep.nacimiento}")
        w(f"  pie hábil nuevo         : {rep.pie_nuevo}")
        w(f"  pie hábil corregido     : {rep.pie_corregido}")
        w(f"  fotos {'copiadas' if opts['commit'] else 'a copiar'}       : {rep.fotos}")
        for titulo, lista in (("Sin jugador en SLAB", rep.sin_jugador),
                              ("Fotos que no se pudieron bajar", rep.fotos_fallidas),
                              ("Nacimiento distinto (no se toca)", rep.nacimiento_distinto)):
            if lista:
                w(self.style.WARNING(f"  {titulo}: {len(lista)}"))
                for x in lista[:10]:
                    w(f"    {x}")
