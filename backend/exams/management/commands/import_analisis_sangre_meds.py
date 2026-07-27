"""Import a MEDS blood-panel CSV into `analisis_sangre` (+ CK into `ck`).

Source: `parse_meds_bloodwork.py` turns the per-player Clínica MEDS PDFs into
one CSV row per player (see backend/scripts/). This command loads that CSV:

  * The panel fields the `analisis_sangre` template actually has AND the MEDS
    report actually carries → one ExamResult per (player, sample date).
  * `ck_total` → the dedicated `ck` template (separate cadence + alerting),
    exactly like `import_ck`.

Values are stored VERBATIM — no unit conversion. The template's displayed
units for testosterona (ng/dL) and cortisol (µg/dL) are cosmetic mislabels;
every existing DB value for those fields is on the ng/mL scale the MEDS report
uses, so converting would corrupt each player's trend. Fixing the labels is a
separate template edit, not this import's job.

Player matching is alias-first, then exact accent-insensitive full name, then
a first+last containment fallback (covers "Juan Martin Lucero" → "Juan
Lucero", "Jose Tomas Alburquenque" → "Jose Alburquenque"). Matching spans ALL
active club players, not just Primer Equipo, because youth players (SUB-20 /
SUB-18) evaluated with the first team appear in the same draw.

Additive + idempotent: a (player, sample-date) that already exists for the
target template is skipped, so re-running only adds new rows.

    docker compose exec backend python manage.py import_analisis_sangre_meds \\
        --file /tmp/analisis_sangre.csv             # dry-run plan
    docker compose exec backend python manage.py import_analisis_sangre_meds \\
        --file /tmp/analisis_sangre.csv --commit    # write
"""
from __future__ import annotations

import csv
import json
import unicodedata
from datetime import date, datetime, time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Category, Club, Player, PlayerAlias
from exams.models import ExamResult, ExamTemplate

# CSV column (from parse_meds_bloodwork.py) → analisis_sangre field key.
# Only fields the template HAS and the report CARRIES. testosterona_libre /
# t3 / t4_libre are template fields the MEDS panel does not measure — omitted.
PANEL_MAP = {
    "hematocrito":        "hematocrito",
    "hemoglobina":        "hemoglobina",
    "ferritina":          "ferritina",
    "vitamina_b12":       "vitamina_b12",
    "vitamina_d":         "vitamina_d",
    "testosterona_total": "testosterona_total",
    "cortisol_am":        "cortisol",
    "tsh":                "tsh",
}


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def _to_float(raw) -> float | None:
    if raw in (None, ""):
        return None
    # Strip out-of-range / below-detection markers ("<", ">", arrows).
    s = str(raw).strip().lstrip("<>").strip()
    try:
        return float(s)
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Import a MEDS blood-panel CSV into analisis_sangre + ck."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--pdf-dir", default=None,
                            help="Folder of source PDFs (named <player>.pdf) to "
                                 "attach to each panel's 'informe' field.")
        parser.add_argument("--commit", action="store_true",
                            help="Write to the DB (default: dry-run plan).")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"Club '{opts['club']}' not found.")

        panel_t = ExamTemplate.objects.filter(
            slug="analisis_sangre", department__club=club).first()
        ck_t = ExamTemplate.objects.filter(
            slug="ck", department__club=club).first()
        if panel_t is None or ck_t is None:
            raise CommandError("Templates 'analisis_sangre' and/or 'ck' not found.")

        # Match across ALL club players (youth included), alias-first.
        players = list(Player.objects.filter(category__club=club))
        aliases = {
            _norm(a.value): a.player_id
            for a in PlayerAlias.objects.filter(player__category__club=club)
        }
        by_id = {p.id: p for p in players}

        def match(name: str) -> Player | None:
            n = _norm(name)
            pid = aliases.get(n)
            if pid and pid in by_id:
                return by_id[pid]
            exact = [p for p in players if _norm(f"{p.first_name} {p.last_name}") == n]
            if len(exact) == 1:
                return exact[0]
            toks = n.split()
            if len(toks) >= 2:
                cands = [
                    p for p in players
                    if _norm(p.last_name) in n and _norm(p.first_name).split()[0] == toks[0]
                ]
                if len(cands) == 1:
                    return cands[0]
            return None

        def existing_keys(template) -> set[tuple]:
            keys = set()
            for pid, rec, data in ExamResult.objects.filter(
                template=template, player__category__club=club,
            ).values_list("player_id", "recorded_at", "result_data"):
                day = (data or {}).get("fecha") or timezone.localtime(rec).date().isoformat()
                keys.add((pid, str(day)[:10]))
            return keys

        exist_panel = existing_keys(panel_t)
        exist_ck = existing_keys(ck_t)

        panel_plan, ck_plan, unmatched, bad_date = [], [], [], []
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("player") or "").strip()
                player = match(name)
                if player is None:
                    unmatched.append(name)
                    continue
                fecha = (row.get("fecha_muestra") or "").strip()
                try:
                    day = date.fromisoformat(fecha)
                except ValueError:
                    bad_date.append(name)
                    continue

                # Panel: keep only present, parseable numeric fields.
                data = {}
                for csv_key, field_key in PANEL_MAP.items():
                    val = _to_float(row.get(csv_key))
                    if val is not None:
                        data[field_key] = val
                if data:
                    key = (player.id, day.isoformat())
                    if key in exist_panel:
                        pass  # already there
                    else:
                        exist_panel.add(key)
                        data["fecha"] = day.isoformat()
                        panel_plan.append({"player": player, "day": day, "data": data,
                                           "name": name})

                # CK: separate template.
                ck_val = _to_float(row.get("ck_total"))
                if ck_val is not None:
                    key = (player.id, day.isoformat())
                    if key not in exist_ck:
                        exist_ck.add(key)
                        ck_plan.append({"player": player, "day": day, "valor": ck_val,
                                        "name": name})

        # ── Report ──────────────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Plan (club={club.name}, sample date from CSV):"))
        self.stdout.write(
            f"  analisis_sangre: crear {len(panel_plan)} paneles · "
            f"ck: crear {len(ck_plan)} resultados")
        if unmatched:
            self.stdout.write(self.style.ERROR(
                f"  SIN MATCH ({len(unmatched)}): {', '.join(unmatched)} — omitidos"))
        if bad_date:
            self.stdout.write(self.style.ERROR(
                f"  fecha inválida: {', '.join(bad_date)} — omitidos"))
        # Per-panel field coverage preview (first 3 players).
        for p in panel_plan[:3]:
            fields = {k: v for k, v in p["data"].items() if k != "fecha"}
            self.stdout.write(f"    {p['name']}: {fields}")
        if len(panel_plan) > 3:
            self.stdout.write(f"    … +{len(panel_plan) - 3} más")

        # Resolve source PDFs (attach to each panel's 'informe' field).
        pdf_dir = Path(opts["pdf_dir"]) if opts["pdf_dir"] else None
        pdf_for: dict = {}
        missing_pdf = []
        if pdf_dir:
            if not pdf_dir.is_dir():
                raise CommandError(f"--pdf-dir not a directory: {pdf_dir}")
            for p in panel_plan:
                cand = pdf_dir / f"{p['name']}.pdf"
                if cand.exists():
                    pdf_for[p["name"]] = cand
                else:
                    missing_pdf.append(p["name"])
            self.stdout.write(
                f"  informe PDFs: {len(pdf_for)} por adjuntar"
                + (f" · SIN PDF: {', '.join(missing_pdf)}" if missing_pdf else ""))

        if not opts["commit"]:
            self.stdout.write(self.style.NOTICE(
                "Dry-run — nada escrito. Repite con --commit."))
            return

        with transaction.atomic():
            panel_objs = [
                ExamResult(
                    player=p["player"], template=panel_t,
                    recorded_at=timezone.make_aware(
                        datetime.combine(p["day"], time(12, 0))),
                    result_data=p["data"], inputs_snapshot={},
                ) for p in panel_plan
            ]
            ExamResult.objects.bulk_create(panel_objs, batch_size=200)
            ExamResult.objects.bulk_create([
                ExamResult(
                    player=p["player"], template=ck_t,
                    recorded_at=timezone.make_aware(
                        datetime.combine(p["day"], time(12, 0))),
                    result_data={"fecha": p["day"].isoformat(), "valor": p["valor"]},
                    inputs_snapshot={},
                ) for p in ck_plan
            ], batch_size=200)

            # Attach source PDFs to each panel's 'informe' field. ExamResult.id
            # is a client-generated UUID, so panel_objs already carry ids.
            attached = 0
            if pdf_for:
                from django.core.files import File
                from attachments.models import Attachment, AttachmentSource
                for plan_row, er in zip(panel_plan, panel_objs):
                    src = pdf_for.get(plan_row["name"])
                    if not src:
                        continue
                    att = Attachment(
                        source_type=AttachmentSource.EXAM_FIELD,
                        source_id=er.id, field_key="informe",
                        filename=src.name, mime_type="application/pdf",
                        size_bytes=src.stat().st_size,
                        label=f"Informe Clínica MEDS {plan_row['day'].isoformat()}",
                    )
                    with src.open("rb") as fh:
                        att.file.save(src.name, File(fh), save=False)
                    att.save()
                    attached += 1

        # bulk_create skips signals — evaluate band rules off each affected
        # player's LATEST result only (same trap import_ck documents).
        from goals.evaluator import evaluate_threshold_rules_for_result
        fired = 0
        for template, plan in ((panel_t, panel_plan), (ck_t, ck_plan)):
            for pid in {p["player"].id for p in plan}:
                latest = ExamResult.objects.filter(
                    player_id=pid, template=template,
                ).order_by("-recorded_at").first()
                if latest:
                    fired += len(evaluate_threshold_rules_for_result(latest))

        log_dir = Path(__file__).resolve().parents[3] / "migration_runs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"sangre-meds-{timezone.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
        with log_path.open("w") as fh:
            fh.write(json.dumps({"kind": "header", "file": path.name,
                                 "panels": len(panel_plan), "ck": len(ck_plan),
                                 "unmatched": unmatched}) + "\n")
            for p in panel_plan:
                fh.write(json.dumps({"template": "analisis_sangre",
                                     "player": p["name"], "fecha": p["day"].isoformat(),
                                     "data": p["data"]}) + "\n")
            for p in ck_plan:
                fh.write(json.dumps({"template": "ck", "player": p["name"],
                                     "fecha": p["day"].isoformat(), "valor": p["valor"]}) + "\n")

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {len(panel_plan)} paneles + {len(ck_plan)} CK creados · "
            f"{attached} informes PDF adjuntos · "
            f"{fired} alertas evaluadas. Log: {log_path.name}"))
