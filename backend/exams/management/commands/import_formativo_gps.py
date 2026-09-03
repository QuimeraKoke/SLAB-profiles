"""Import `GPS CATEGORÍAS.xlsx` into `gps_partido` / `gps_sesion`.

Thin CLI over `exams.formativo_gps_ingest`; see that module for the
match-vs-session rule, the column map and the provenance keys.

Additive: dedup on `result_data["origen_id"]`, existing results are never
overwritten. Dry-run by default.

    cp "GPS CATEGORÍAS.xlsx" backend/_formativo_gps.xlsx
    docker compose exec backend python manage.py import_formativo_gps \\
        --file /app/_formativo_gps.xlsx              # dry-run
    docker compose exec backend python manage.py import_formativo_gps \\
        --file /app/_formativo_gps.xlsx --commit     # write

Alerts stay OFF unless `--alerts` is passed: this is a 2024–2026 backfill.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams import formativo_gps_ingest as ing


class Command(BaseCommand):
    help = "Importa el GPS del formativo (aditivo, dedup por origen_id)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True,
                            help="Ruta al .xlsx dentro del contenedor.")
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--alerts", action="store_true")
        parser.add_argument("--sheet", action="append", dest="sheets",
                            help="Limitar a una hoja (repetible).")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")

        rep = ing.run(opts["file"], club, commit=opts["commit"],
                      fire_alerts=opts["alerts"],
                      solo_hojas=set(opts["sheets"]) if opts.get("sheets") else None)

        modo = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{modo}\n"))
        self.stdout.write(self.style.SUCCESS(
            f"  resultados a crear  : {rep.creados}"))
        self.stdout.write(f"    · gps_partido     : {rep.partidos}"
                          f"  ({rep.con_evento} vinculados a un evento)")
        self.stdout.write(f"    · gps_sesion      : {rep.sesiones}")
        if rep.md_sin_marca:
            self.stdout.write(self.style.WARNING(
                f"      de ellas {rep.md_sin_marca} son día de partido SIN "
                f"localía/resultado → van a sesión"))
        self.stdout.write(f"  ya estaban en base  : {rep.ya_existian}")
        self.stdout.write(f"  repetidas en el xlsx: {rep.duplicados_en_archivo}")
        self.stdout.write(f"  filas sin métricas  : {rep.sin_datos}")
        if rep.sin_fecha:
            self.stdout.write(self.style.WARNING(
                f"  filas SIN FECHA     : {rep.sin_fecha}"))
        if rep.columnas_sin_mapear:
            self.stdout.write(self.style.ERROR(
                "\n  ⚠️ MÉTRICAS QUE NO MAPEARON (la hoja cambió de forma):"))
            for hoja, faltan in sorted(rep.columnas_sin_mapear.items()):
                self.stdout.write(f"    {hoja:<14} {', '.join(faltan)}")
        if rep.columnas_desconocidas:
            self.stdout.write(self.style.WARNING(
                "\n  Columnas que el importador no reconoce (¿se agregaron?):"))
            for hoja, cols in sorted(rep.columnas_desconocidas.items()):
                self.stdout.write(f"    {hoja:<14} {', '.join(cols)}")
        if rep.por_hoja:
            self.stdout.write("\n  por hoja:")
            for hoja, n in sorted(rep.por_hoja.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"    {hoja:<14} {n}")

        for titulo, items, estilo in (
            ("Sin plantilla en el club", rep.sin_plantilla, self.style.ERROR),
            ("Valores descartados por rango (la fila sí se carga)",
             rep.fuera_de_rango, self.style.ERROR),
            ("Sin jugador en SLAB", rep.sin_jugador, self.style.WARNING),
        ):
            if not items:
                continue
            self.stdout.write(estilo(f"\n  {titulo}: {len(items)}"))
            for item in items[:12]:
                self.stdout.write(f"    {item}")
            if len(items) > 12:
                self.stdout.write(f"    … y {len(items) - 12} más")
