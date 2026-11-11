"""Import the club's jump-control sheets (`U{11…20}_Plantilla_control_carga_CMJ`).

One Google Sheet per team, ONE TAB PER MATCH (`M40 CLOA`, `M40 UE` when a week
had two), each with the players' jump the day BEFORE the match (PRE, MD-1) and
the day AFTER (POST, MD+1), two attempts each. It feeds "Fatiga post-partido"
(PLAN_CONTROL_CARGA.md, «Fuente de saltos»). Read tab by tab, it is ~48 tabs
per document — so the whole document comes in ONE batched request.

What makes it hard, and how each is handled:

* **Three layouts.** OptoJump R-CMJ since ~M12 (altura de caída, tiempo de
  contacto, altura del rebote — early weeks have tiempo de vuelo instead),
  and in Jan–Mar CMJ from VALD or OptoJump (altura, RSI mod, ecc velocity).
  Weight columns are sometimes prepended and a blank column sometimes sits
  inside a group, so columns are located by the HEADERS (row 1 group labels,
  row 2 PRE 1 / PRE 2 / BEST PRE / POST 1 / POST 2 / BEST POST), never by
  position. The sheet's own "BEST" is ignored: in R-CMJ it is an AVERAGE.
* **No dates.** A tab is "un microciclo = el período entre dos partidos": one
  per match measured, in order — NOT the GPS's calendar-week MICRO. Dated by
  the title if it carries a date, else the club's reviewed table, else an
  alignment to the team's matches (see `align_between_matches`). Each result
  records which (`fecha_fuente`: titulo / club / propuesta).
* **Names.** "KORN", "K. GUZMAN", "S.GARCES", "CORTES B", "DIEGO COFRE",
  "FUENTES M S14" (a Serie 2014 playing up). Surname words + initials, matched
  in the team's players first, then the club's; a name two players fit
  (GARCES: Benjamín, Simón) is settled by who played that match, else
  reported unresolved. Never guessed.

RSI per attempt: rebote ÷ contacto (R-CMJ; vuelo ÷ contacto in the early
weeks), the sheet's RSI mod for CMJ. Stored per attempt, plus best and mean;
the panel reads the one `attempt_value` says (best, as the club's dashboard).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from exams.formativo_gps_ingest import norm

ORIGEN = "planilla_club_saltos"
SLUG = "control_salto"
MEASURES = (  # (normalised group label prefix, key, unit) — longest first
    ("ALTURA DEL SALTO REBOUND", "rebote", "m"),
    ("ALTURA DE CAIDA", "caida", "m"),
    ("TIEMPO DE CONTACTO", "contacto", "s"),
    ("TIEMPO DE VUELO", "vuelo", "s"),
    ("ALTURA DE SALTO", "altura", "cm"),
    ("RSI MOD", "rsi_mod", ""),
    ("RSI M S", "rsi_mod", ""),
    ("ECC VELOCITY", "ecc_vel", "m/s"),
)
SLOTS = ("pre_1", "pre_2", "post_1", "post_2")
INSTRUMENTS = (("OPTO", "OptoJump"), ("VALD", "VALD"))
SKIP_TABS = {"TOTALES", "CONTROL DE PESO"}


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


@dataclass
class Tab:
    title: str
    number: int | None
    suffix: str
    label: str                          # cell A1: instrument or microcycle type
    test: str                           # "rcmj" | "cmj"
    rows: list[tuple[str, dict]] = field(default_factory=list)   # (sheet name, values)


def parse_tab(title: str, grid: list[list[Any]]) -> Tab | None:
    """A tab's players and attempts, or None when it is not a jump tab."""
    if norm(title) in SKIP_TABS or len(grid) < 3:
        return None
    head = [norm(c) for c in grid[0]]
    sub = [norm(c) for c in grid[1]]
    if "DEPORTISTA" not in sub:
        return None
    starts = []
    for i, h in enumerate(head):
        for prefix, key, _unit in MEASURES:
            if h.startswith(prefix):
                starts.append((i, key))
                break
    if not starts:
        return None
    bounds = [s for s, _ in starts] + [len(sub) + 1]
    cols: dict[str, dict[str, int]] = {}
    for n, (start, key) in enumerate(starts):
        span = range(start, min(bounds[n + 1], start + 9))
        lab = {sub[j]: j for j in span if j < len(sub) and sub[j]}
        if "PRE 1" not in lab or "BEST PRE" not in lab:
            continue
        bp = lab["BEST PRE"]
        cols[key] = {"pre_1": lab["PRE 1"], "pre_2": lab.get("PRE 2", lab["PRE 1"] + 1),
                     "post_1": lab.get("POST 1", bp + 1), "post_2": lab.get("POST 2", bp + 2)}
    if not cols:
        return None
    test = "rcmj" if "contacto" in cols else "cmj"
    m = re.search(r"\bM\s*(\d{1,2})\b", title.upper())
    number = int(m.group(1)) if m else None
    suffix = re.sub(r"\bM\s*\d{1,2}\b", "", norm(title)).replace("SEMANA SANTA", "").strip()
    i_name = sub.index("DEPORTISTA")
    tab = Tab(title=title, number=number, suffix=suffix,
              label=str(grid[0][0] or "").strip() if grid[0] else "", test=test)
    for r in grid[2:]:
        name = str(r[i_name] if i_name < len(r) else "").strip()
        if not name or norm(name) in {"PROMEDIO", "Q1PQ"}:
            continue
        values = {}
        for key, c in cols.items():
            for slot, j in c.items():
                v = _num(r[j]) if j < len(r) else None
                if v is not None:
                    values[f"{key}_{slot}"] = v
        if values:
            tab.rows.append((name, values))
    return tab if tab.rows else None


def with_rsi(test: str, values: dict) -> dict:
    """Add rsi per attempt, best and mean per phase, and the best-vs-best Δ%."""
    out = dict(values)
    for slot in SLOTS:
        if test == "rcmj":
            c = values.get(f"contacto_{slot}")
            top = values.get(f"rebote_{slot}", values.get(f"vuelo_{slot}"))
            rsi = round(top / c, 3) if top is not None and c else None
        else:
            rsi = values.get(f"rsi_mod_{slot}")
        if rsi is not None:
            out[f"rsi_{slot}"] = rsi
    for phase in ("pre", "post"):
        tries = [out[k] for k in (f"rsi_{phase}_1", f"rsi_{phase}_2") if k in out]
        if tries:
            out[f"rsi_{phase}_best"] = max(tries)
            out[f"rsi_{phase}_mean"] = round(sum(tries) / len(tries), 3)
    if out.get("rsi_pre_best") and out.get("rsi_post_best") is not None:
        out["rsi_delta_pct"] = round((out["rsi_post_best"] - out["rsi_pre_best"]) / out["rsi_pre_best"] * 100, 1)
    out["rsi_metodo"] = ("rebote / contacto" if any(k.startswith("rebote") for k in values)
                         else "vuelo / contacto" if test == "rcmj" else "RSI mod")
    return out


# ── names ────────────────────────────────────────────────────────────────────

def name_parts(raw: str) -> tuple[list[str], list[str]]:
    """("K. GUZMAN") → (["GUZMAN"], ["K"]); "FUENTES M S14" drops the S14 tag."""
    text = re.sub(r"\bS\s?\d{2}\b", " ", raw.upper())
    text = re.sub(r"([A-ZÑ])\.", r"\1 ", text)
    words, initials = [], []
    for t in norm(text).split():
        (initials if len(t) == 1 else words).append(t)
    return words, initials


class NameMatcher:
    """Sheet name → player. The sheet writes the PATERNAL surname (Chilean
    usage): "GONZALEZ T" is Tomás González, not Vicente Ramírez González — so
    paternal surnames are tried first, the maternal only if nobody fits.
    Ties are broken by who played that match, then by who is really in the
    team (team GPS rows this season: Benjamín Salas 153 in U20 vs Clemente
    Salas 2 — he plays U18). Otherwise unresolved, never guessed."""

    DOMINANCE = 3      # the busiest candidate needs ×3 the next one's rows…
    MIN_ROWS = 10      # …and at least this many

    def __init__(self, team_players, club_players, activity: dict | None = None):
        self.team = list(team_players)
        self.club = list(club_players)
        self.activity = activity or {}

    @staticmethod
    def _tokens(p) -> tuple[set, set, set]:
        names = set(norm(" ".join(x for x in (p.first_name, getattr(p, "middle_name", "") or "") if x)).split())
        paternal = set(norm(p.last_name or "").split())
        maternal = set(norm(getattr(p, "second_last_name", "") or "").split())
        return names, paternal, maternal

    def candidates(self, raw: str, pool, *, paternal_only: bool = False) -> list:
        words, initials = name_parts(raw)
        if not words:
            return []
        out = []
        for p in pool:
            names, paternal, maternal = self._tokens(p)
            surnames = paternal if paternal_only else paternal | maternal
            if not all(w in names | surnames for w in words):
                continue
            if not any(w in surnames for w in words):
                continue  # a first name alone ("DIEGO") is not enough
            if initials and not all(any(n.startswith(i) for n in names) for i in initials):
                continue
            out.append(p)
        return out

    def _break_tie(self, found, played):
        if played:
            narrowed = [p for p in found if p.id in played]
            if len(narrowed) == 1:
                return narrowed[0], "ok (jugó ese partido)"
        ranked = sorted(found, key=lambda p: -self.activity.get(p.id, 0))
        top, nxt = (self.activity.get(ranked[0].id, 0), self.activity.get(ranked[1].id, 0))
        if top >= self.MIN_ROWS and top >= self.DOMINANCE * max(nxt, 1):
            return ranked[0], "ok (el del equipo)"
        return None, f"ambiguo ({len(found)})"

    def match(self, raw: str, played: set | None = None):
        """(player | None, reason)."""
        for pool in (self.team, self.club):
            for paternal_only in (True, False):
                found = self.candidates(raw, pool, paternal_only=paternal_only)
                if len(found) == 1:
                    return found[0], "ok"
                if len(found) > 1:
                    return self._break_tie(found, played)
        return None, "sin coincidencia"


# ── tab → match ──────────────────────────────────────────────────────────────
#
# A tab is "un microciclo = el período entre dos partidos" (the club,
# 2026-11-03): one tab per match measured, in order. Which matches were
# measured varies per team (U20 fits officials only; U18/U16 also friendlies —
# U16's "Viaje a mendoza" lands on Independiente Rivadavia in Mendoza), so both
# sets are tried, with and without the latest match (its POST may not exist
# yet), and the alignment that honours the tabs' rival suffixes and best
# overlaps who played wins. A date in the tab's title, or the club's reviewed
# table (`load_control.JumpTabMatch`), always beats the alignment.

_DATE_IN_TITLE = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?(?!\d)")


def _subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return bool(short) and all(ch in it for ch in short)


def date_in_title(title: str, season: int) -> date | None:
    m = _DATE_IN_TITLE.search(title)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    year = int(y) + (2000 if y and len(y) == 2 else 0) if y else season
    try:
        return date(year, mo, d)
    except ValueError:
        return None


def played_by_day(club, season: int, bracket, days) -> dict[date, set]:
    """{match day: players with ≥ 60 GPS minutes that day} — who a POST
    (taken after > 75′) should mostly be."""
    from dashboards.team_scope import season_rows
    from exams.models import ExamResult

    out: dict[date, set] = defaultdict(set)
    for pid, rec, data in ExamResult.objects.filter(
        season_rows(club.id, season, bracket), template__slug__in=("gps_partido", "gps_sesion"),
        recorded_at__date__in=list(days),
    ).values_list("player_id", "recorded_at", "result_data"):
        d = timezone.localtime(rec).date()
        if ((data or {}).get("tot_dur") or 0) >= 60:
            out[d].add(pid)
    return out


def align_between_matches(tabs: list[Tab], kinds: dict[date, str], opponents: dict[date, str],
                          played: dict[date, set], matcher: NameMatcher, today: date) -> dict[str, date]:
    """{tab title: match day} by order, choosing the variant that best fits."""
    post = {}
    for t in tabs:
        ids = set()
        for name, values in t.rows:
            if any(k.endswith(("post_1", "post_2")) for k in values):
                p, _ = matcher.match(name)
                if p is not None:
                    ids.add(p.id)
        post[t.title] = ids

    def anchor(t: Tab, d: date) -> int:
        if not t.suffix:
            return 0
        ok = _subsequence(t.suffix.replace(" ", ""), norm(opponents.get(d, "")).replace(" ", ""))
        return 1 if ok else -1

    best = None
    for allowed in (("official", "friendly"), ("official",)):
        for cutoff in (today, today - timedelta(days=1), today - timedelta(days=2)):
            days = sorted(d for d, k in kinds.items() if k in allowed and d < cutoff)
            n = min(len(tabs), len(days))
            pairs = list(zip(tabs[len(tabs) - n:], days[len(days) - n:]))
            key = (sum(anchor(t, d) for t, d in pairs), sum(len(post[t.title] & played.get(d, set())) for t, d in pairs))
            if best is None or key > best[0]:
                best = (key, pairs)
    return {t.title: d for t, d in best[1]} if best else {}


# ── run ──────────────────────────────────────────────────────────────────────

@dataclass
class Reporte:
    documento: str = ""
    equipo: str = ""
    desfase: int | None = None
    pestanas: int = 0
    pestanas_sin_partido: list = field(default_factory=list)
    por_fuente: Counter = field(default_factory=Counter)
    creados: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    sin_jugador: list = field(default_factory=list)


def team_of_document(title: str) -> str | None:
    m = re.match(r"\s*U(\d{2})", title.upper())
    return f"Sub {m.group(1)}" if m else None


def ensure_template(club):
    from exams.models import ExamTemplate
    from core.models import Department

    tpl = ExamTemplate.objects.filter(slug=SLUG, department__club=club).first()
    if tpl:
        return tpl
    dept = (Department.objects.filter(club=club, slug="fisico").first()
            or Department.objects.filter(club=club).first())
    fields = [{"key": "test", "label": "Test", "type": "categorical", "options": ["rcmj", "cmj"]},
              {"key": "rsi_pre_best", "label": "RSI PRE (mejor)", "type": "number", "group": "RSI"},
              {"key": "rsi_post_best", "label": "RSI POST (mejor)", "type": "number", "group": "RSI"},
              {"key": "rsi_delta_pct", "label": "Δ% RSI POST vs PRE", "type": "number", "unit": "%", "group": "RSI"},
              {"key": "rsi_pre_mean", "label": "RSI PRE (promedio)", "type": "number", "group": "RSI"},
              {"key": "rsi_post_mean", "label": "RSI POST (promedio)", "type": "number", "group": "RSI"}]
    for _prefix, key, unit in MEASURES:
        if any(f["key"] == f"{key}_pre_1" for f in fields):
            continue
        for slot in SLOTS:
            fields.append({"key": f"{key}_{slot}", "label": f"{key} {slot.replace('_', ' ').upper()}",
                           "type": "number", "unit": unit, "group": "Intentos"})
    return ExamTemplate.objects.create(
        department=dept, name="Control de salto (PRE / POST partido)", slug=SLUG,
        config_schema={"fields": fields})


DATE_KEYS = ("fecha_partido", "fecha_fuente", "rival")


def run(origen: str, club, *, season: int | None = None, commit: bool = False,
        creds_file: str = "", creds_json: str = "", keep_proposed_dates: bool = False) -> Reporte:
    """`keep_proposed_dates` (the hourly sync): a row already imported keeps
    the match it was put on while that date is only a PROPOSAL (aligned from
    the calendar, not in the tab's title nor confirmed by the club) — the
    alignment shifts as fixtures and match sheets arrive, and an unattended
    sync must not silently move a team's jump history. Its measured values
    still update; a date that becomes confirmed still moves it. The manual
    command keeps the old behaviour: re-align everything."""
    from core.models import Bracket, Player, TeamSeason
    from dashboards.team_scope import season_rows
    from exams.formativo_sources import abrir
    from exams.models import ExamResult
    from load_control.matches import match_links, team_match_days
    from load_control.models import JumpTabMatch

    season = season or timezone.localdate().year
    today = timezone.localdate()
    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    rep = Reporte(documento=fuente.titulo())
    bracket_name = team_of_document(rep.documento)
    bracket = Bracket.objects.filter(name=bracket_name).first() if bracket_name else None
    if bracket is None:
        raise ValueError(f"No se reconoce el equipo en el título «{rep.documento}».")
    rep.equipo = bracket.name
    team_label = "U" + bracket.name.split()[-1]
    fuente.precargar()
    tabs = [t for t in (parse_tab(h, fuente.filas(h)) for h in fuente.hojas()) if t]
    rep.pestanas = len(tabs)

    team_ids = list(TeamSeason.objects.filter(season=season, bracket=bracket, team__club=club)
                    .values_list("team_id", flat=True))
    gps_players = ExamResult.objects.filter(season_rows(club.id, season, bracket)).values_list("player_id", flat=True)
    team = Player.objects.filter(category__club=club).filter(
        models_q(category_id__in=team_ids, is_active=True) | models_q(pk__in=gps_players)).distinct()
    activity = Counter(ExamResult.objects.filter(season_rows(club.id, season, bracket))
                       .values_list("player_id", flat=True))
    matcher = NameMatcher(team, Player.objects.filter(category__club=club), activity)

    kinds = team_match_days(club, season, bracket, date(season, 1, 1), min(today, date(season, 12, 31)))
    links = match_links(club, season, bracket, kinds)
    opponents = {d: (links.get(d) or {}).get("opponent") or "" for d in kinds}
    played = played_by_day(club, season, bracket, kinds)
    auto = align_between_matches(tabs, kinds, opponents, played, matcher, today)
    reviewed = {r.tab.strip(): r.match_date for r in JumpTabMatch.objects.filter(
        club=club, team=team_label, season=season)}

    tpl = ensure_template(club) if commit else None
    existing = {r.result_data.get("origen_id"): r for r in ExamResult.objects.filter(
        result_data__origen=ORIGEN, result_data__origen_documento=rep.documento)}
    to_create, to_update = [], []
    for t in tabs:
        day, source = date_in_title(t.title, season), "titulo"
        if day is None and t.title.strip() in reviewed:
            day, source = reviewed[t.title.strip()], "club"
            if day is None:
                continue  # the staff said this tab is not a match
        if day is None:
            day, source = auto.get(t.title), "propuesta"
        if day is None:
            rep.pestanas_sin_partido.append(t.title)
            continue
        rep.por_fuente[source] += 1
        label_n = norm(t.label)
        instrument = next((v for k, v in INSTRUMENTS if k in label_n), None)
        link = links.get(day) or match_links(club, season, bracket, {day: "official"}).get(day) or {}
        for name, values in t.rows:
            p, why = matcher.match(name, played=played.get(day))
            if p is None:
                rep.sin_jugador.append(f"{name} ({t.title}: {why})")
                continue
            data = with_rsi(t.test, values)
            data.update({
                "test": t.test, "fecha_partido": day.isoformat(), "fecha_fuente": source,
                "rival": link.get("opponent"), "microciclo_hoja": t.number, "hoja": t.title.strip(),
                "nombre_hoja": name, "instrumento": instrument, "etiqueta_hoja": t.label or None,
                "origen": ORIGEN, "origen_documento": rep.documento, "equipo_hoja": team_label,
                "origen_id": f"{rep.documento}|{t.title.strip()}|{norm(name)}",
            })
            old = existing.get(data["origen_id"])
            event_id = link.get("event_id")
            row_day = day
            if (keep_proposed_dates and old is not None and source == "propuesta"
                    and (old.result_data or {}).get("fecha_partido")):
                # Stay where it was: same match, same date, same event.
                for k in DATE_KEYS:
                    data[k] = (old.result_data or {}).get(k)
                event_id = old.event_id
                row_day = timezone.localtime(old.recorded_at).date()
            if old is None:
                to_create.append(ExamResult(
                    template=tpl, player=p, event_id=event_id,
                    recorded_at=timezone.make_aware(datetime.combine(row_day, datetime.min.time())),
                    result_data=data))
            elif old.result_data != data or old.player_id != p.id or str(old.event_id or "") != str(event_id or ""):
                old.result_data, old.player, old.event_id = data, p, event_id
                old.recorded_at = timezone.make_aware(datetime.combine(row_day, datetime.min.time()))
                to_update.append(old)
            else:
                rep.sin_cambios += 1
    rep.creados, rep.actualizados = len(to_create), len(to_update)
    if commit:
        with transaction.atomic():
            ExamResult.objects.bulk_create(to_create, batch_size=500)
            ExamResult.objects.bulk_update(to_update, ["result_data", "player", "event", "recorded_at"],
                                           batch_size=500)
            if team_ids:
                tpl.applicable_categories.add(*team_ids)
    fuente.cerrar()
    return rep


def models_q(**kw):
    from django.db.models import Q
    return Q(**kw)
