"""Import the Pentacompartimental (5-component anthropometry) xlsx export into
the `pentacompartimental` template.

Thin CLI over `exams.penta_ingest` — the same engine behind the self-service
upload (`POST /pentacompartimental/upload`), so a file imported here and one
uploaded through the UI are treated identically. See that module for the parsing
rules, name matching and dedup policy.

Additive: dedup on (player, assessment date), existing results are never
overwritten. Dry-run by default.

    # copy the workbook into the backend mount so the container can read it:
    cp report.xlsx backend/_penta_import.xlsx
    docker compose exec backend python manage.py import_pentacompartimental \\
        --file /app/_penta_import.xlsx            # dry-run
    docker compose exec backend python manage.py import_pentacompartimental \\
        --file /app/_penta_import.xlsx --commit   # write

A historical backfill should pass --no-alerts: band alerts are otherwise
evaluated for assessments inside the 30-day staleness window.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import Club
from exams import penta_ingest
from exams.models import ExamTemplate


class Command(BaseCommand):
    help = "Import the Pentacompartimental anthropometry xlsx (additive, dedup on player+date)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the .xlsx (inside the container).")
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--sheet", default=penta_ingest.SHEET)
        parser.add_argument("--slug", default="pentacompartimental")
        parser.add_argument("--commit", action="store_true", help="Write (default: dry-run).")
        parser.add_argument(
            "--no-alerts", action="store_true",
            help="Skip band-alert evaluation. Use for historical backfills.",
        )

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"Club '{opts['club']}' not found.")
        tpl = ExamTemplate.objects.filter(
            slug=opts["slug"], department__club=club,
        ).first()
        if tpl is None:
            raise CommandError(f"Template '{opts['slug']}' not found in {club.name}.")

        try:
            with open(opts["file"], "rb") as fh:
                file_bytes = fh.read()
        except OSError as exc:
            raise CommandError(f"No se pudo abrir {opts['file']}: {exc}")

        try:
            rep = penta_ingest.run(
                file_bytes, club=club, template=tpl,
                dry_run=not opts["commit"], sheet=opts["sheet"],
                fire_alerts=not opts["no_alerts"],
            )
        except penta_ingest.PentaParseError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            f"Template: {rep['template']} ({rep['club']}) | filas leídas: {rep['rows_read']}"
        )
        self.stdout.write(
            f"Nuevos a crear: {rep['created']} | ya existían (omitidos): "
            f"{rep['skipped_existing']} | dup en archivo: "
            f"{rep['skipped_duplicate_in_file']} | incompletos: "
            f"{rep['skipped_incomplete']} | sin fecha: {rep['skipped_undated']} "
            f"| jugadores: {len(rep['players'])}"
        )
        for s in rep["players"]:
            self.stdout.write(
                f"  +{s['new']:>2}  {s['player']} [{s['category'] or '?'}]  "
                f"(excel: {s['excel_name']})"
            )
        if rep["unmatched"]:
            self.stdout.write(self.style.WARNING(
                f"\nSIN MATCH ({len(rep['unmatched'])}): "
                + ", ".join(f"{u['name']} ({u['rows']})" for u in rep["unmatched"])
            ))

        if rep["dry_run"]:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN — nada escrito. Pasá --commit para importar."
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            f"\nImportado (aditivo, sin señales): +{rep['created']} resultados"
            + (f", {rep['alerts_fired']} alerta(s) evaluada(s)." if rep["alerts_fired"] else ".")
        ))
