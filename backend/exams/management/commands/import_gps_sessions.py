"""One-time backfill of a season's per-session GPS export into ExamResults.

NOT the recurring upload path — that's the self-service UI (training) backed by
`POST /api/results/gps-sessions`. This command is the deliberate one-shot
loader for whole-season files (matches → linked Events; training → flat). Core
logic lives in `exams.gps_session_ingest`.

    docker compose exec backend python manage.py import_gps_sessions \\
        --file /tmp/1782416220434.xls --dry-run        # read the plan
    docker compose exec backend python manage.py import_gps_sessions \\
        --file /tmp/1782416220434.xls                  # commit
"""
from __future__ import annotations

import json
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Category, Department
from exams.models import ExamTemplate
from exams import gps_session as G
from exams import gps_session_ingest


class Command(BaseCommand):
    help = "One-time backfill of a per-session GPS export into ExamResults (+ match Events)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the GPS export (.xls/.xlsx).")
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--category", default="Primer Equipo")
        parser.add_argument("--template-slug", default="gps_sesion",
                            help="Template for training files.")
        parser.add_argument("--match-template-slug", default="gps_partido",
                            help="Template for match files (event-linked).")
        parser.add_argument("--department-slug", default="fisico",
                            help="Department the match Events live on.")
        parser.add_argument("--mode", choices=["auto", "match", "training"], default="auto")
        parser.add_argument("--default-year", type=int, default=G.DEFAULT_YEAR)
        parser.add_argument("--dry-run", action="store_true", help="Parse + plan, write nothing.")
        parser.add_argument("--update", action="store_true",
                            help="Overwrite result_data on records that already exist.")
        parser.add_argument("--no-log", action="store_true",
                            help="Skip writing the run log under migration_runs/.")

    def handle(self, *args, **opts):
        cat = (
            Category.objects.filter(name=opts["category"], club__name=opts["club"])
            .select_related("club").first()
        )
        if cat is None:
            raise CommandError(f"Category '{opts['category']}' not found in club '{opts['club']}'.")
        department = Department.objects.filter(club=cat.club, slug=opts["department_slug"]).first()
        if department is None:
            raise CommandError(f"Department '{opts['department_slug']}' not found in {cat.club.name}.")

        try:
            with open(opts["file"], "rb") as fh:
                file_bytes = fh.read()
        except OSError as exc:
            raise CommandError(str(exc))

        # Match files write to the match template, training files to the
        # training one. `auto` sniffs the file the same way `run()` does (a
        # `Days` column ⇒ match export).
        try:
            mode = opts["mode"]
            if mode == "auto":
                mode = "match" if G.parse_workbook(file_bytes)[0] else "training"
        except G.GpsParseError as exc:
            raise CommandError(str(exc))
        slug = opts["match_template_slug"] if mode == "match" else opts["template_slug"]
        template = ExamTemplate.objects.filter(
            slug=slug, department__club=cat.club,
        ).first()
        if template is None:
            seed_hint = "seed_gps_partido" if mode == "match" else "seed_gps_session"
            raise CommandError(
                f"Template '{slug}' not found for {cat.club.name} — "
                f"run `{seed_hint} --create-if-missing` first."
            )

        try:
            report = gps_session_ingest.run(
                file_bytes, template=template, category=cat,
                dry_run=opts["dry_run"], create_events=True, department=department,
                default_year=opts["default_year"], mode=mode, update=opts["update"],
            )
        except G.GpsParseError as exc:
            raise CommandError(str(exc))

        self._report(opts["file"], report)
        if not opts["no_log"] and not opts["dry_run"]:
            self._write_log(opts["file"], report)

    def _report(self, path, r):
        tag = "DRY-RUN — " if r["dry_run"] else ""
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{tag}{path}  [mode={r['mode']}]"))
        self.stdout.write(
            f"  rows={r['total_rows']}  planned={r['planned']}  "
            f"results: +{r['created']} created, {r['skipped']} skipped, {r['updated']} updated"
        )
        if r["mode"] == "match":
            verb = (f"would create ~{r['events_created']}, reuse {r['events_reused']}"
                    if r["dry_run"] else
                    f"+{r['events_created']} created, {r['events_reused']} reused")
            self.stdout.write(f"  match events: {verb}")
        if r["unmatched"]:
            total = sum(u["rows"] for u in r["unmatched"])
            self.stdout.write(self.style.WARNING(f"  unmatched player codes ({total} rows):"))
            for u in r["unmatched"]:
                self.stdout.write(f"      {u['code']} ({u['rows']} rows) — add a PlayerAlias")
        if r["undated"]:
            total = sum(u["rows"] for u in r["undated"])
            self.stdout.write(self.style.WARNING(
                f"  skipped undated sessions ({total} rows, {len(r['undated'])} sessions):"))
            for u in r["undated"]:
                self.stdout.write(f"      {u['session']!r} ({u['rows']} rows)")
        self.stdout.write(self.style.SUCCESS("  done." if not r["dry_run"] else "  (nothing written)"))

    def _write_log(self, path, report):
        import os
        stem = os.path.splitext(os.path.basename(path))[0]
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        out_dir = os.path.join(settings.BASE_DIR, "migration_runs")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"gps-import-{stem}-{ts}.json")
        with open(out, "w") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        self.stdout.write(f"  run log: {out}")
