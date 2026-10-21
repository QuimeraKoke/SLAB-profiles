"""Thin CLI over `exams.kine_notes_ingest` — the formativo physios' log sheet.

    docker compose exec backend python manage.py import_kine_formativo                 # plan
    docker compose exec backend python manage.py import_kine_formativo --reporte /tmp/kine.xlsx
    docker compose exec backend python manage.py import_kine_formativo --commit

Same run the hourly sync does (`exams.tasks.sync_kine_formativo`).
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams import kine_notes_ingest as ing


class Command(BaseCommand):
    help = "Planilla de kinesiología del formativo → Notas diarias de Kinesiología."

    def add_arguments(self, parser):
        parser.add_argument("--sheet", default=settings.KINE_FORMATIVO_SHEET_ID)
        parser.add_argument("--club", default=settings.FORMATIVO_CLUB)
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--reporte", default="",
                            help="Ruta de un .xlsx con lo que el club tiene que corregir.")

    def handle(self, *args, **opts):
        from exams.tasks import _formativo_creds

        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        cf, cj = _formativo_creds()
        rep = ing.run(opts["sheet"], club, commit=opts["commit"], creds_file=cf, creds_json=cj)

        w = self.stdout.write
        w(self.style.MIGRATE_HEADING("\nAPLICADO\n" if opts["commit"]
                                     else "\nSIMULACIÓN (sin --commit no escribe)\n"))
        w(f"  filas en la planilla      : {rep.filas}")
        w(f"  notas a crear             : {rep.creadas}")
        w(f"  notas a actualizar        : {rep.actualizadas}")
        w(f"  notas sin cambio          : {rep.sin_cambio}")
        w(f"  notas a borrar            : {rep.borradas}"
          + ("  (BLOQUEADO: borraría más de la mitad — ¿la hoja se leyó entera?)"
             if rep.borrado_bloqueado else ""))
        w(f"  jugador por RUT / nombre  : {rep.via['rut']} / {rep.via['nombre']}")
        personas = {(f.nombre, f.categoria) for f in rep.sin_jugador}
        w(f"  sin jugador en SLAB       : {len(rep.sin_jugador)} filas, {len(personas)} personas")
        w(f"  fechas inválidas (omitidas): {len(rep.fecha_invalida)}"
          + (f" — filas {', '.join(str(f.n) for f in rep.fecha_invalida)}" if rep.fecha_invalida else ""))
        w(f"  fechas para revisar       : {len(rep.fecha_dudosa)}"
          + (f" — filas {', '.join(str(f.n) for f in rep.fecha_dudosa)}" if rep.fecha_dudosa else ""))
        for k, v in rep.opciones_nuevas.items():
            w(f"  opciones nuevas en {k}: {', '.join(v)}")
        if rep.categorias_nuevas:
            w(f"  pestaña Kinesiología agregada en: {', '.join(rep.categorias_nuevas)}")
        if opts["reporte"]:
            ing.escribir_reporte(rep, opts["reporte"])
            w(self.style.SUCCESS(f"  reporte: {opts['reporte']}"))
