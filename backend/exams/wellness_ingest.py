"""Shared wellness Check-IN ingest — used by both the manual `.xlsx` importer
(`load_checkin_fisico`) and the scheduled Google-Sheet sync
(`exams.tasks.sync_wellness_responses`).

Input is a list of header→value dicts (cells may be Python types from openpyxl
*or* plain strings from the Sheets API — coercion is defensive about both).
Output is created `ExamResult` rows on the `checkin_fisico` template, plus
molestia/estado-mismatch alerts, with a JSON-friendly report.

Molestia rules (the form's "Glosario Cuerpo" → the template's option_labels):
the free-text cell holds comma-separated zone codes (e.g. "V1, X1"); we
normalize ("1.0"→"1", trim, upper), validate against the template's known
codes, and store the clean comma-joined string. Decoding to labels / body-map
regions is the template's job (option_labels / option_regions).
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Optional

from django.utils import timezone

from core.models import Player
from exams.models import ExamResult, ExamTemplate


WELLNESS_SLUG = "checkin_fisico"

# Header keyword (normalized, substring) → result_data field key.
KEYWORD_COLS: dict[str, str] = {
    "marca temporal": "ts",
    "jugador": "jugador",
    "estado de entren": "estado",
    "recuperaci": "recuperacion",
    "cuerpo": "cuerpo",
    "energ": "energia",
    "nimo": "animo",     # ¿cómo estás de ánimo?
    "dorm": "sueno",     # ¿cómo dormiste hoy?
    "molestia": "molestia",
}
_NUM_FIELDS = ("recuperacion", "cuerpo", "energia", "animo", "sueno")


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


# ---------- coercion helpers ----------

_TS_FORMATS = (
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d",
)


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Form timestamp → aware datetime. Accepts datetime (xlsx) or a
    day-first string (Sheets API, e.g. '16/4/2026 8:28:48')."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, 12, 0)
    else:
        s = str(value).strip()
        # Pad single-digit day/month so %d/%m parse ('16/4/2026' → '16/04/2026').
        dt = None
        for fmt in _TS_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            # last resort: split date/time and parse numerically
            try:
                datepart = s.split()[0]
                d, m, y = (int(x) for x in datepart.replace("-", "/").split("/")[:3])
                if y < 100:
                    y += 2000
                dt = datetime(y, m, d, 12, 0)
            except (ValueError, IndexError):
                return None
    # Drop microseconds: the Sheets API returns second precision while
    # openpyxl preserves microseconds — truncating keeps the idempotency key
    # stable across both sources (same submission ⇒ same recorded_at).
    dt = dt.replace(microsecond=0)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _coerce_num(raw: Any) -> Optional[float]:
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


def map_estado(raw: Any) -> str:
    e = _norm(str(raw or ""))
    if e.startswith("lesi"):
        return "lesion"
    if e.startswith("parcial"):
        return "parcial"
    return "disponible"


def normalize_molestia(raw: Any, valid_codes: set[str]) -> tuple[list[str], list[str]]:
    """Parse the molestia cell into (clean_codes, unknown_codes).

    Rules: split on comma/semicolon, trim, upper-case, coerce float-like
    "1.0"→"1", drop blanks/"NO"/"NINGUNA", validate against `valid_codes`.
    """
    if raw is None:
        return [], []
    text = str(raw).strip()
    if not text or _norm(text) in {"no", "ninguna", "ninguno", "n/a", "na", "-"}:
        return [], []
    codes: list[str] = []
    unknown: list[str] = []
    for tok in text.replace(";", ",").split(","):
        t = tok.strip()
        if not t:
            continue
        try:  # "1.0" → "1"
            f = float(t)
            if f.is_integer():
                t = str(int(f))
        except ValueError:
            pass
        t = t.upper()
        if valid_codes and t not in valid_codes:
            unknown.append(t)
            continue
        if t not in codes:
            codes.append(t)
    return codes, unknown


# ---------- player matching ----------

def _build_matcher(category):
    roster = list(Player.objects.filter(category=category, is_active=True))
    idx = []
    for p in roster:
        t = _norm(f"{p.first_name} {p.last_name}").split()
        if t:
            idx.append({"p": p, "fi": t[0][:1], "last": t[-1], "first": t[0],
                        "full": " ".join(t)})

    def match(name: str):
        t = _norm(name).split()
        if not t:
            return None
        first, fi, last, full = t[0], t[0][:1], t[-1], " ".join(t)
        for e in idx:                                   # exact full name
            if e["full"] == full:
                return e["p"]
        for e in idx:                                   # first-initial + ~surname
            if e["fi"] == fi and _lev(e["last"], last) <= 1:
                return e["p"]
        for e in idx:                                   # exact first + close surname
            if e["first"] == first and _lev(e["last"], last) <= 2:
                return e["p"]
        return None  # NO surname-only fallback (avoids attaching youth to seniors)

    return match


# ---------- main ingest ----------

def _template_valid_codes(template: ExamTemplate) -> set[str]:
    for f in (template.config_schema or {}).get("fields", []):
        if f.get("key") == "molestia":
            return set((f.get("option_labels") or {}).keys())
    return set()


def _column_index(headers: list[str]) -> dict[str, str]:
    """Map each present header → field key via KEYWORD_COLS substring match."""
    out: dict[str, str] = {}
    for h in headers:
        hn = _norm(h)
        for kw, key in KEYWORD_COLS.items():
            if kw in hn:
                out[h] = key
                break
    return out


def ingest_wellness(
    rows: list[dict[str, Any]],
    *,
    template: ExamTemplate,
    category,
    mode: str = "all",          # "all" | "today" | "reconcile"
    since_days: int = 3,
    today: date | None = None,
    dry_run: bool = False,
) -> dict:
    """Create ExamResults from wellness rows; evaluate molestia alerts.

    `mode` bounds which rows by timestamp date:
      * "today"     → only rows from `today` (local)
      * "reconcile" → rows within the last `since_days`
      * "all"       → every row (full backfill)
    Idempotent on (player, recorded_at). Returns a JSON-friendly report.
    """
    if not rows:
        return {"rows": 0, "created": 0, "skipped": 0, "unmatched": {},
                "molestias": 0, "mismatches": 0, "unknown_codes": {}, "alerts": 0}

    valid_codes = _template_valid_codes(template)
    headers = list({h for r in rows for h in r.keys()})
    colmap = _column_index(headers)              # header → field key
    # invert: field key → the header string actually present
    field_header = {v: k for k, v in colmap.items()}
    match = _build_matcher(category)
    today = today or timezone.localdate()
    lo_date = today - timedelta(days=since_days)

    # Truncate stored timestamps to seconds so rows imported earlier from the
    # .xlsx (microsecond precision) match the same submissions arriving via the
    # Sheets API (second precision) — otherwise a backfill duplicates them.
    existing = {
        (pid, rec.replace(microsecond=0))
        for pid, rec in ExamResult.objects.filter(template=template)
        .values_list("player_id", "recorded_at")
    }

    created = skipped = molestias = mismatches = 0
    unmatched: dict[str, int] = {}
    unknown_codes: dict[str, int] = {}
    to_create: list[ExamResult] = []
    # latest processed check-in per player → drives the molestia alert
    latest: dict[Any, dict] = {}

    def cell(row, field):
        h = field_header.get(field)
        return row.get(h) if h is not None else None

    for row in rows:
        name = cell(row, "jugador")
        if not name or not str(name).strip():
            continue
        rec = parse_timestamp(cell(row, "ts"))
        if rec is None:
            continue
        rec_day = timezone.localtime(rec).date()
        if mode == "today" and rec_day != today:
            continue
        if mode == "reconcile" and rec_day < lo_date:
            continue

        player = match(str(name))
        if player is None:
            key = str(name).strip()
            unmatched[key] = unmatched.get(key, 0) + 1
            continue

        estado = map_estado(cell(row, "estado"))
        codes, unknown = normalize_molestia(cell(row, "molestia"), valid_codes)
        for u in unknown:
            unknown_codes[u] = unknown_codes.get(u, 0) + 1

        data: dict[str, Any] = {"estado": estado}
        total = 0.0
        for key in _NUM_FIELDS:
            v = _coerce_num(cell(row, key))
            if v is not None:
                data[key] = v
                total += v
        data["total_bienestar"] = round(total, 1)
        if codes:
            data["molestia"] = ",".join(codes)
            molestias += 1
        mismatch = bool(codes) and estado == "disponible"
        if mismatch:
            data["molestia_revisar"] = True
            mismatches += 1

        # track the player's most-recent check-in for alerting
        prev = latest.get(player.id)
        if prev is None or rec > prev["rec"]:
            latest[player.id] = {"player": player, "rec": rec, "estado": estado,
                                 "codes": codes, "mismatch": mismatch}

        if (player.id, rec) in existing:
            skipped += 1
            continue
        existing.add((player.id, rec))
        created += 1
        if not dry_run:
            to_create.append(ExamResult(
                player=player, template=template, recorded_at=rec,
                result_data=data, inputs_snapshot={},
            ))

    alerts = 0
    if not dry_run:
        ExamResult.objects.bulk_create(to_create, batch_size=400)
        # Molestia / estado-mismatch alerts, based on each player's latest check-in.
        try:
            from goals.evaluator import evaluate_molestia_alert
            for info in latest.values():
                if evaluate_molestia_alert(
                    player=info["player"], template=template,
                    estado=info["estado"], codes=info["codes"],
                    mismatch=info["mismatch"], recorded_at=info["rec"],
                ):
                    alerts += 1
        except Exception:  # pragma: no cover — alerts are best-effort
            pass
        # Check-in alerts (molestia + bands) expire when the check-ins stop:
        # a player who reported a molestia and then went silent (usually
        # because he's now injured and the Episode tracks him) shouldn't
        # keep a months-old warning alive on the Daily.
        try:
            from goals.evaluator import resolve_stale_checkin_alerts
            resolve_stale_checkin_alerts(template)
        except Exception:  # pragma: no cover — best-effort
            pass
        # Band/threshold rules (e.g. «cuerpo cae en banda Bajo»). These
        # normally run in the ExamResult post_save signal, but bulk_create
        # SKIPS signals — so without this pass, synced check-ins would never
        # fire (nor auto-resolve) wellness band alerts. Evaluate each
        # player's latest check-in: fires when it's in an alert band,
        # resolves standing alerts when it's back in range.
        try:
            from goals.evaluator import evaluate_threshold_rules_for_result
            for info in latest.values():
                latest_result = (
                    ExamResult.objects
                    .filter(player=info["player"], template=template,
                            recorded_at=info["rec"])
                    .first()
                )
                if latest_result is not None:
                    alerts += len(evaluate_threshold_rules_for_result(latest_result))
        except Exception:  # pragma: no cover — alerts are best-effort
            pass

    return {
        "rows": len(rows), "created": created, "skipped": skipped,
        "unmatched": unmatched, "molestias": molestias, "mismatches": mismatches,
        "unknown_codes": unknown_codes, "alerts": alerts,
    }
