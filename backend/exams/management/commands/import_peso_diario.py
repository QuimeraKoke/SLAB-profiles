"""Import the first team's daily weigh-in ("Registro peso diario") into `peso_talla`.

The hourly Celery task runs the same code; this is for the first load and for
checking what a run would do.

    docker compose exec backend python manage.py import_peso_diario            # dry run
    docker compose exec backend python manage.py import_peso_diario --commit
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams import peso_diario_ingest as ing


class Command(BaseCommand):
    help = "Peso diario de Primer Equipo (Google Sheet) → Peso y Talla."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=settings.PESO_DIARIO_SHEET_ID, dest="origen",
                            help="Id de la Google Sheet o ruta a un .xlsx.")
        parser.add_argument("--club", default=settings.PESO_DIARIO_CLUB)
        parser.add_argument("--commit", action="store_true", help="Escribe (por defecto: simulación).")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        filas, dias = ing.leer(opts["origen"],
                               creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
                               creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
        try:
            rep = ing.run(club, filas, dias, commit=opts["commit"])
        except ValueError as e:
            raise CommandError(str(e)) from e

        w = self.stdout.write
        w(self.style.MIGRATE_HEADING(
            "\nAPLICADO\n" if opts["commit"] else "\nSIMULACIÓN (sin --commit no escribe)\n"))
        w(f"  días en la hoja     : {len(dias)} ({rep.desde} → {rep.hasta})")
        w(f"  jugadores en la hoja: {rep.jugadores} · emparejados {rep.emparejados} "
          f"{dict(rep.por_metodo)}")
        w(self.style.SUCCESS(f"  pesos a crear       : {rep.creados}"))
        w(f"  a corregir          : {rep.actualizados}")
        w(f"  sin cambios         : {rep.iguales}")
        w(f"  celdas con estado (no son peso, no se cargan): {dict(rep.estados)}")
        for titulo, items in (("Fuera de rango", rep.fuera_de_rango),
                              ("Ambiguos — no se asignan", rep.ambiguos),
                              ("Sin jugador en SLAB", rep.sin_jugador)):
            if items:
                w(self.style.WARNING(f"\n  {titulo}: {len(items)}"))
                for it in items:
                    w(f"    {it}")
