"""Import `EVALUACIONES FÍSICAS CATEGORÍAS.xlsx` into the five physical templates.

Thin CLI over `exams.formativo_ingest`; see that module for the pivot of the
long-format sheets, the matching rules, and the provenance keys.

Additive: dedup on `result_data["origen_id"]`, existing results are never
overwritten. Dry-run by default.

    # copy the workbook into the backend mount so the container can read it:
    cp "EVALUACIONES FÍSICAS CATEGORÍAS.xlsx" backend/_formativo_eval.xlsx
    docker compose exec backend python manage.py import_formativo_evaluaciones \\
        --file /app/_formativo_eval.xlsx              # dry-run
    docker compose exec backend python manage.py import_formativo_evaluaciones \\
        --file /app/_formativo_eval.xlsx --commit     # write

Alerts stay OFF unless `--alerts` is passed. This is a 2024–2026 backfill and
an alert anchored on a two-year-old reading is expired again by the next
staleness sweep, so firing it would only churn the alert list.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams import formativo_ingest


class Command(BaseCommand):
    help = ("Importa las evaluaciones físicas del formativo "
            "(aditivo, dedup por origen_id).")

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, dest="origen",
                            help=("Ruta al .xlsx dentro del contenedor, O el id "
                                  "de la Google Sheet viva del club."))
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--commit", action="store_true",
                            help="Escribe (por defecto: simulación).")
        parser.add_argument("--alerts", action="store_true",
                            help="Evalúa alertas de banda para lo cargado.")
        parser.add_argument("--sheet", action="append", dest="sheets",
                            help="Limitar a una hoja (repetible).")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")

        from django.conf import settings

        rep = formativo_ingest.run(
            opts["origen"], club, commit=opts["commit"],
            fire_alerts=opts["alerts"],
            creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
            creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON,
            solo_hojas=set(opts["sheets"]) if opts.get("sheets") else None)

        modo = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{modo}\n"))
        self.stdout.write(self.style.SUCCESS(f"  resultados a crear : {rep.creados}"))
        self.stdout.write(f"  ya estaban en base : {rep.ya_existian}")
        self.stdout.write(f"  repetidas en el xlsx: {rep.duplicados_en_archivo}")
        self.stdout.write(f"  filas sin datos    : {rep.sin_datos}")
        if rep.sin_fecha:
            total = sum(rep.sin_fecha.values())
            self.stdout.write(self.style.WARNING(
                f"  filas SIN FECHA    : {total} (no se pueden cargar)"))
            for hoja, n in sorted(rep.sin_fecha.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"    {hoja:<26} {n}")
        if rep.por_hoja:
            self.stdout.write("\n  por hoja:")
            for hoja, n in sorted(rep.por_hoja.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"    {hoja:<26} {n}")
        if rep.alertas:
            self.stdout.write(f"\n  alertas evaluadas  : {rep.alertas}")

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
