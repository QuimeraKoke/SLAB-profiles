"""Load the club's wellness Check-IN responses (Google-Forms .xlsx) into the
`checkin_fisico` template as ExamResults.

    docker compose exec backend python manage.py load_checkin_fisico \\
        --file /tmp/checkin.xlsx --club "Universidad de Chile" --category "Primer Equipo"

Idempotent: a (player, recorded_at) already present is skipped, so re-running
only adds new responses. Players in the sheet not found in the (active)
roster are reported and skipped.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

_SHEET = "Respuestas de formulario 1"
# Header keyword → field key.
_COLS = {
    "marca temporal": "ts",
    "jugador": "jugador",
    "estado de entren": "estado",
    "recuperaci": "recuperacion",
    "cuerpo": "cuerpo",
    "energ": "energia",
    "nimo": "animo",       # ¿cómo estás de ánimo?
    "dorm": "sueno",       # ¿cómo dormiste hoy?
    "molestia": "molestia",
}
_NUMS = ("recuperacion", "cuerpo", "energia", "animo", "sueno")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def _lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 1:
        return 2
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class Command(BaseCommand):
    help = "Load wellness Check-IN responses from an .xlsx into checkin_fisico."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--club", default=None)
        parser.add_argument("--category", default="Primer Equipo")
        parser.add_argument("--sheet", default=_SHEET)

    def handle(self, *args, **opts):
        import openpyxl
        from core.models import Category, Player
        from exams.models import ExamResult, ExamTemplate

        cat = Category.objects.filter(name=opts["category"])
        if opts["club"]:
            cat = cat.filter(club__name=opts["club"])
        cat = cat.first()
        if cat is None:
            raise CommandError("Category not found.")
        template = ExamTemplate.objects.filter(
            slug="checkin_fisico", department__club=cat.club,
        ).first()
        if template is None:
            raise CommandError("Template 'checkin_fisico' not found — run seed_checkin_fisico first.")

        # Active roster index for name matching.
        roster = list(Player.objects.filter(category=cat, is_active=True))
        idx = []
        for p in roster:
            t = _norm(f"{p.first_name} {p.last_name}").split()
            if t:
                idx.append({"p": p, "fi": t[0][:1], "last": t[-1], "full": " ".join(t)})

        def match(name: str):
            t = _norm(name).split()
            if not t:
                return None
            first, fi, last, full = t[0], t[0][:1], t[-1], " ".join(t)
            for e in idx:
                if e["full"] == full:
                    return e["p"]
            # First-initial + near-identical surname (Vásquez/Vazquez).
            for e in idx:
                if e["fi"] == fi and _lev(e["last"], last) <= 1:
                    return e["p"]
            # Exact first name + close surname (Toselli/Tosseli). NOTE: no
            # surname-only fallback — that wrongly attached youth (Diego
            # Vargas, Vicente Ramírez) to seniors sharing a surname.
            for e in idx:
                if e["full"].split()[0] == first and _lev(e["last"], last) <= 2:
                    return e["p"]
            return None

        wb = openpyxl.load_workbook(opts["file"], data_only=True, read_only=True)
        ws = wb[opts["sheet"]]
        it = ws.iter_rows(values_only=True)
        header = next(it)
        colmap = {}
        for i, h in enumerate(header):
            hn = _norm(str(h))
            for kw, key in _COLS.items():
                if kw in hn:
                    colmap[key] = i
                    break

        existing = set(
            ExamResult.objects.filter(template=template)
            .values_list("player_id", "recorded_at")
        )

        created, skipped_dup, unmatched = 0, 0, {}
        to_create = []
        for row in it:
            def g(key):  # bounds-safe cell access (rows truncate trailing blanks)
                i = colmap.get(key)
                return row[i] if (i is not None and i < len(row)) else None

            name_cell = g("jugador")
            if not row or not name_cell:
                continue
            player = match(str(name_cell))
            if player is None:
                key = str(name_cell).strip()
                unmatched[key] = unmatched.get(key, 0) + 1
                continue
            ts = g("ts")
            if isinstance(ts, datetime):
                rec = ts if timezone.is_aware(ts) else timezone.make_aware(ts)
            else:
                continue
            if (player.id, rec) in existing:
                skipped_dup += 1
                continue

            data: dict = {}
            est = _norm(str(g("estado") or ""))
            data["estado"] = ("lesion" if est.startswith("lesi")
                              else "parcial" if est.startswith("parcial")
                              else "disponible")
            total = 0.0
            for key in _NUMS:
                try:
                    fv = float(g(key))
                except (TypeError, ValueError):
                    fv = None
                if fv is not None:
                    data[key] = fv
                    total += fv
            data["total_bienestar"] = round(total, 1)
            mol = g("molestia")
            if mol not in (None, ""):
                data["molestia"] = str(mol)

            to_create.append(ExamResult(player=player, template=template,
                                        recorded_at=rec, result_data=data))
            existing.add((player.id, rec))
            created += 1

        ExamResult.objects.bulk_create(to_create, batch_size=400)

        self.stdout.write(self.style.SUCCESS(
            f"Loaded {created} responses · skipped {skipped_dup} duplicates."))
        if unmatched:
            self.stdout.write(self.style.WARNING(
                "Unmatched players (not in active roster):"))
            for n, c in sorted(unmatched.items(), key=lambda x: -x[1]):
                self.stdout.write(f"  {n} ({c} rows)")
