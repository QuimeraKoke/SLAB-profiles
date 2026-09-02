#!/usr/bin/env python3
"""Build the canonical Formativo player master from the club's two workbooks.

This is the phase-1 quality gate of PLAN_FORMATIVO.md. It reads
`GPS CATEGORÍAS.xlsx` and `EVALUACIONES FÍSICAS CATEGORÍAS.xlsx` and emits a
canonical `nombre → cohorte → fecha nac. → categoría → posición` CSV, plus the
list of rows that still need the club, plus the aliases SLAB needs to match.

Why this script exists instead of reading the workbooks directly
----------------------------------------------------------------
Neither workbook has an authoritative roster. The `JUGADORES` sheet looks like
one, but its `CATEGORÍA` column is a formula:

    =IFS(C>18.9,"U21", C>16.9,"U18", … , C>10.9,"U11")
    where C = YEARFRAC(FECHA_NACIMIENTO, TODAY())

Two failure modes fall out of that, and both are silent:

1. **Empty birth date → "U21"/"U20".** `YEARFRAC(blank, TODAY())` counts from
   1900 and yields ~126 years, which trips the first rung. Every dateless row
   is filed in the oldest bracket. 16 rows are affected, and 7 of them are
   duplicate rows for youth players who *do* have a date elsewhere — reading
   `CATEGORÍA` at face value invents seven Sub 20 players who don't exist.
2. **No rung below 10.9 → `#N/A`.** Players born Oct–Dec of the Sub 11 cohort
   are younger than 10.9 and fall off the end of the chain. Worse than staying
   broken: `TODAY()` makes them repair themselves a few weeks later, so the
   column is a function of when you opened the file.

So the category is *derived*, and we don't import derived values — the same
reason `CometCompetitionLink` stores `bracket` and computes the team. What we
import is the birth date (the fact); SLAB computes the Sub N label per season
via `Category.season_label_parts()`.

Where the category actually comes from
--------------------------------------
The per-category sheets (`U11`…`U20` in the GPS book, and the test sheets in
the evaluations book) are session/test records, one row per player per event,
each carrying an explicit `CATEGORÍA` written by whoever ran the session. That
is a real assignment rather than an age computation, so we take the category by
majority vote over those rows.

Sheets deliberately excluded, and why:

- `U17WC`, `U20 WC`, `WC CLUBES` — these are World Cup scouting logs holding
  *other teams'* players (Panamá, Guatemala, Al Ahly, Inter Miami). Importing
  them would put opponents in the club's roster.
- `Pasing Gral.`, `GPS PARTIDOS`, `VAM`, `Control de Carga` — aggregates by
  category with no player column.
- `SPARRING` — real club players, but `CATEGORÍA` reads "SPARRING", which is a
  role in a session, not a bracket. Kept as evidence for dates only.

Name truncation
---------------
The session sheets truncate names at 22 characters (`BASTIAN MORALES RAMIRE`,
`CARLOS ANAIS ESTUPIÑAN`). Matching is therefore prefix-aware, never exact-only.

Usage:
    python3 build_formativo_master.py "/path/to/U de Chile - Formativo" \\
        [--season 2026] [--outdir .]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover
    sys.exit("pip install openpyxl")

GPS_BOOK = "GPS CATEGORÍAS.xlsx"
EVAL_BOOK = "EVALUACIONES FÍSICAS CATEGORÍAS.xlsx"

# Sheets that hold players from OTHER teams, or no player column at all.
# Excluding these is a correctness requirement, not an optimisation.
SHEETS_EXCLUDED = {
    "U17WC", "U20 WC", "WC CLUBES",          # other teams' players
    "Pasing Gral.", "GPS PARTIDOS", "VAM",   # aggregates, no player
    "Control de Carga", "Perfiles Físicos",  # no category / no date
    "Hoja 9",                                # duplicate of RESISTENCIA
    "FORMATO CONDICIONAL 15-16 y 18-",       # the band definitions
    "FORMATO CONDICIONAL 13 -14 y 11",
}
# Sheet whose CATEGORÍA is a session role, not a bracket. Dates still count.
SHEETS_NO_CATEGORY = {"SPARRING", "Pasing Indi."}
TRIALIST_SHEET = "REGISTRO JUGADORES A PRUEBA"

# Dates the club confirmed by email (2026-07-30). These win over the files:
# both workbooks disagreed on them, so neither file is authoritative.
CLUB_CONFIRMED: dict[str, date] = {
    "ALONSO MUNOZ": date(2014, 2, 8),
    "VICENTE NILO": date(2015, 12, 2),
    "IVO IBARRA": date(2012, 1, 16),
    "BRANKO GEZAN GARCIA": date(2006, 8, 3),
    "DAVID GUZMAN VIVANCO": date(2008, 6, 9),
}
# The GPS book files the Sub 15 David as VIVANCO; he is BASCUR. Same name for
# two people is the one true collision in the master, so we split by date.
NAME_FIX_BY_DOB: dict[tuple[str, date], str] = {
    ("DAVID GUZMAN VIVANCO", date(2011, 2, 10)): "DAVID GUZMAN BASCUR",
}


def norm(value: object) -> str:
    """Uppercase, unaccented, punctuation-stripped, single-spaced."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", text).split())


# The ANFP ladder, mirroring `core.Bracket` (order 0..7). It has NO Sub 17 and
# NO Sub 19, so a bracket is never `season - cohort` — that expression invents
# rungs that no competition has. Cohorts younger than Sub 11 have no ANFP
# bracket at all; they are a "Serie <year>" and nothing more, which is exactly
# what `Category.season_label_parts()` returns for them.
ANFP_LADDER = (11, 12, 13, 14, 15, 16, 18, 20)

# Birth years outside this window are data errors, not players.
DOB_YEAR_MIN = 1995


def bracket_norm(value: object) -> int | None:
    """Parse a `U13`-style label into its rung number. `U21` → Sub 20."""
    text = str(value or "").strip().upper()
    if not re.fullmatch(r"U\d{1,2}", text):
        return None
    rung = int(text[1:])
    return 20 if rung == 21 else rung


BELOW_LADDER = "below"      # Sub 8/9/10 — the ANFP runs no competition
ABOVE_LADDER = "senior"     # aged out of the youth system


def bracket_for_age(age: int) -> int | str:
    """First youth rung that admits this age — brackets are a CEILING.

    Mirrors `core.Bracket.for_age`, including its two edges, because a second
    implementation that disagrees is how a ladder with gaps gets read
    inconsistently. Age 17 has no rung so it plays Sub 18 (the club's Sub 18 is
    cohorts 2008+2009); age 19 plays Sub 20.

    Above every youth rung it returns `ABOVE_LADDER` rather than clamping to
    Sub 20. Clamping looked right against the club's file — their U20 sheet
    spans 2004–2007 — but those rows are sessions from 2024/2025 when that
    cohort really was Sub 20. In the target season they have aged out, and
    saying "Sub 20" would assert a squad membership the data does not support.
    """
    if age < ANFP_LADDER[0]:
        return BELOW_LADDER
    for rung in ANFP_LADDER:
        if age <= rung:
            return rung
    return ABOVE_LADDER


def implied_cohort(rung: int, row_year: int) -> int:
    """A session labelled `U13` in 2025 was played by the 2012 cohort.

    Inverting the label against the season it was written in makes session
    evidence season-invariant. Voting on the raw label instead would file a
    player under whatever bracket he happened to play two years ago.
    """
    return row_year - rung


class Observation:
    """One sighting of a player in a data row, with where it came from.

    `row_year` is the year of the row's own `FECHA`, needed to interpret
    `bracket` — a `U13` written in 2024 and one written in 2026 describe two
    different cohorts.
    """

    __slots__ = ("dob", "bracket", "age_int", "row_year", "source")

    def __init__(self, dob, bracket, age_int, row_year, source):
        self.dob, self.bracket, self.age_int = dob, bracket, age_int
        self.row_year, self.source = row_year, source


def read_book(path: Path, observations: dict[str, list[Observation]],
              nominal: dict[str, dict], trialists: set[str]) -> None:
    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    tag = "GPS" if path.name == GPS_BOOK else "EVAL"
    for sheet_name in book.sheetnames:
        if sheet_name in SHEETS_EXCLUDED:
            continue
        sheet = book[sheet_name]
        rows = sheet.iter_rows(values_only=True)
        try:
            header = [str(c or "").strip().upper() for c in next(rows)]
        except StopIteration:
            continue

        def col(*names, contains=None):
            for i, head in enumerate(header):
                if head in names or (contains and contains in head):
                    return i
            return None

        i_name = col("JUGADOR", "NOMBRE")
        if i_name is None:
            continue
        i_dob = col(contains="NACIMIENTO")
        i_cat = col("CATEGORÍA", "CATEGORIA")
        i_age = col("EDAD")
        i_pos = col("POSICIÓN", "POSICION")
        i_when = next((i for i, h in enumerate(header)
                       if h.startswith("FECHA") and "NACIMIENTO" not in h), None)
        allow_category = sheet_name not in SHEETS_NO_CATEGORY

        for row in rows:
            if i_name >= len(row) or not isinstance(row[i_name], str):
                continue
            key = norm(row[i_name])
            if len(key.split()) < 2:      # header echoes, totals, stray labels
                continue

            def cell(idx):
                return row[idx] if idx is not None and idx < len(row) else None

            raw_dob = cell(i_dob)
            dob = raw_dob.date() if hasattr(raw_dob, "date") else None
            if dob and not (DOB_YEAR_MIN <= dob.year <= date.today().year - 5):
                dob = None                      # a stray value, not a birth date
            bracket = bracket_norm(cell(i_cat)) if allow_category else None
            raw_when = cell(i_when)
            row_year = raw_when.year if hasattr(raw_when, "year") else None
            raw_age = cell(i_age)
            # The trialist sheet writes EDAD as a whole number of years; that
            # pins the cohort to ±1 even with no birth date at all.
            age_int = int(raw_age) if isinstance(raw_age, (int, float)) and \
                5 < float(raw_age) < 25 and float(raw_age) == int(raw_age) else None

            if sheet_name == TRIALIST_SHEET:
                trialists.add(key)

            if sheet_name == "JUGADORES":
                # The nominal master: keep name/position/date, DISCARD the
                # formula-derived CATEGORÍA (see module docstring).
                entry = nominal.setdefault(key, {"positions": Counter(), "rows": []})
                entry["rows"].append(f"{path.name}!{sheet_name}")
                if cell(i_pos):
                    entry["positions"][str(cell(i_pos)).strip()] += 1
                if dob:
                    observations[key].append(
                        Observation(dob, None, None, None, f"{tag}:JUGADORES"))
                continue

            if dob or bracket or age_int:
                observations[key].append(
                    Observation(dob, bracket, age_int, row_year, f"{tag}:{sheet_name}"))
    book.close()


def _majority_dob(obs: list[Observation]) -> date | None:
    votes = Counter(o.dob for o in obs if o.dob)
    return votes.most_common(1)[0][0] if votes else None


def _fold_short_names(observations: dict[str, list[Observation]],
                      nominal: dict[str, dict]) -> None:
    """Collapse `ALVARO BARRERA` into `ALVARO BARRERA CALDERON`.

    The club writes some players with the maternal surname and some without,
    in the same sheet, so the master ends up holding one person twice. 13 pairs
    do this. Left alone they become 13 duplicate players, and phase 2 matched
    both rows to the same existing record.

    **The shared birth date is what licenses the merge**, not the prefix. Two
    prefix pairs here are genuinely different people — `ALONSO MORALES` (2014)
    versus `ALONSO MORALES ESPINOZA` (2016), and `DIEGO DIAZ` (2015) versus
    `DIEGO DIAZ PENALVER` (2017) — most likely brothers. Merging on the name
    alone would have destroyed two players.
    """
    keys = sorted(set(observations) | set(nominal), key=len, reverse=True)
    dobs = {k: _majority_dob(observations.get(k, [])) for k in keys}
    for short in list(keys):
        if short not in dobs or dobs[short] is None:
            continue
        longer = [k for k in keys
                  if k != short and k.startswith(short + " ") and dobs.get(k) == dobs[short]]
        if len(longer) != 1:
            continue
        target = longer[0]
        observations[target].extend(observations.pop(short, []))
        if short in nominal:
            entry = nominal.setdefault(target, {"positions": Counter(), "rows": []})
            entry["positions"].update(nominal[short]["positions"])
            entry["rows"].extend(nominal[short]["rows"])
            del nominal[short]
        dobs.pop(short, None)


def resolve_dob(key: str, obs: list[Observation]) -> tuple[date | None, str]:
    if key in CLUB_CONFIRMED:
        return CLUB_CONFIRMED[key], "club (confirmada por correo)"
    votes = Counter(o.dob for o in obs if o.dob)
    if not votes:
        return None, ""
    if len(votes) == 1:
        (dob, count), = votes.most_common(1)
        return dob, f"{count} fila(s) coincidentes"
    top, second = votes.most_common(2)
    total = sum(votes.values())
    # A lone dissenting row among a hundred agreeing ones is a typo, not a
    # conflict — Iván Núñez has 150 rows on 2010-03-06 and one stray date
    # copy-pasted from the row above. Only escalate when the minority has
    # enough weight to be a real disagreement.
    if second[1] >= 3 and second[1] >= 0.2 * total:
        return top[0], (f"CONFLICTO {top[1]} vs {second[1]} "
                        f"({top[0]} / {second[0]}) — requiere al club")
    if top[1] > second[1]:
        return top[0], f"mayoría {top[1]}/{total} (descarta {second[0]}, {second[1]})"
    return top[0], f"EMPATE {top[1]}-{second[1]} — CONFLICTO, requiere al club"


def resolve_cohort(obs: list[Observation], dob: date | None) -> tuple[int | None, str]:
    """The cohort is the fact we import. A birth date settles it outright.

    Without one, session labels still pin it down: each `U13` row carries the
    year it was written in, so it implies a cohort. Failing that, the trialist
    sheet's whole-number `EDAD` gets within a year.
    """
    if dob:
        return dob.year, "de la fecha de nacimiento"
    votes = Counter(implied_cohort(o.bracket, o.row_year)
                    for o in obs if o.bracket and o.row_year)
    if votes:
        cohort, count = votes.most_common(1)[0]
        spread = max(votes) - min(votes)
        detail = f"de {count}/{sum(votes.values())} filas de sesión"
        if spread:
            detail += f" (rango {min(votes)}–{max(votes)}, ±{spread})"
        return cohort, detail
    ages = [(o.age_int, o.row_year) for o in obs if o.age_int and o.row_year]
    if ages:
        cohort = Counter(y - a for a, y in ages).most_common(1)[0][0]
        return cohort, "de EDAD entera en hoja de pruebas (±1 año)"
    return None, ""


def promotion_note(obs: list[Observation], cohort: int | None, season: int) -> str:
    """Flag a player whose CURRENT-season sessions run above his own rung.

    Only same-season rows count: a Sub 15 label from 2024 is not a promotion,
    it is just what that cohort was called two years ago. This is the club's
    "cómo le va al que sube" signal, and 26% of youth appearances are call-ups.
    """
    if cohort is None:
        return ""
    age = season - cohort
    # Compare against his own rung, falling back to his age for the Sub 8/9/10
    # cohorts that have no ANFP rung — otherwise a Serie 2016 playing Sub 10
    # reads as a promotion when Sub 10 is exactly his level.
    rung = bracket_for_age(age)
    threshold = rung if isinstance(rung, int) else age
    above = sorted({o.bracket for o in obs
                    if o.bracket and o.row_year == season and o.bracket > threshold})
    return f"jugó en Sub {', Sub '.join(map(str, above))} esta temporada" if above else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--season", type=int, default=date.today().year)
    parser.add_argument("--outdir", type=Path, default=Path("."))
    args = parser.parse_args()

    observations: dict[str, list[Observation]] = defaultdict(list)
    nominal: dict[str, dict] = {}
    trialists: set[str] = set()
    for book in (GPS_BOOK, EVAL_BOOK):
        path = args.folder / book
        if not path.exists():
            return int(bool(sys.stderr.write(f"falta {path}\n"))) or 2
        read_book(path, observations, nominal, trialists)

    # Session sheets truncate at 22 chars: fold each truncated key into the
    # full name from the nominal master when it is an unambiguous prefix.
    full_names = [k for k in nominal if len(k) > 22]
    for key in [k for k in observations if k not in nominal]:
        matches = [f for f in full_names if f.startswith(key)]
        if len(matches) == 1:
            observations[matches[0]].extend(observations.pop(key))

    _fold_short_names(observations, nominal)

    canonical, pending, aliases = [], [], []
    for key in sorted(set(nominal) | set(observations)):
        obs = observations.get(key, [])
        dob, dob_source = resolve_dob(key, obs)
        name = NAME_FIX_BY_DOB.get((key, dob), key)
        cohort, cohort_source = resolve_cohort(obs, dob)
        rung = bracket_for_age(args.season - cohort) if cohort else None
        if rung == BELOW_LADDER:
            rung_label = "(sin bracket ANFP)"
        elif rung == ABOVE_LADDER:
            rung_label = "(sobre-edad formativo)"
        else:
            rung_label = f"Sub {rung}" if rung else ""
        positions = nominal.get(key, {}).get("positions") or Counter()
        position = positions.most_common(1)[0][0] if positions else ""
        is_trialist = key in trialists and key not in nominal
        estado = "prueba" if is_trialist else ("plantel" if cohort else "pendiente")

        row = {
            "nombre": name,
            # The two facts SLAB imports. `serie` is just how the club names a
            # cohort; the Sub N bracket below is computed, never stored.
            "cohorte": cohort or "",
            "fecha_nacimiento": dob.isoformat() if dob else "",
            "serie": f"Serie {cohort}" if cohort else "",
            "posicion": position,
            "estado": estado,
            # Informational: what SLAB will render for THIS season. Recomputed
            # every season, so it is a report column, not an import column.
            f"bracket_{args.season}": rung_label,
            "fuente_fecha": dob_source,
            "fuente_cohorte": cohort_source,
            "promocion": promotion_note(obs, cohort, args.season),
        }
        canonical.append(row)
        if name != key:
            aliases.append({"jugador": name, "alias": key,
                            "motivo": "el archivo GPS lo registra con otro apellido materno"})
        # Trialists are excluded on purpose: the club's own trialist sheet has
        # no birth-date column, so listing all 80 of them as "missing data"
        # would bury the handful of squad players that genuinely need chasing.
        if not dob and not is_trialist:
            pending.append({
                "nombre": name,
                "cohorte_estimada": cohort or "",
                "estado": estado,
                "evidencia": ", ".join(sorted({o.source for o in obs})) or "sólo JUGADORES",
                "pedir": "fecha de nacimiento" + (
                    " y confirmar si es plantel o prueba" if not cohort else ""),
            })
        if "CONFLICTO" in dob_source:
            pending.append({"nombre": name, "cohorte_estimada": cohort or "",
                            "estado": "conflicto", "evidencia": dob_source,
                            "pedir": "cuál fecha es la correcta"})

    args.outdir.mkdir(parents=True, exist_ok=True)
    def dump(filename, rows, fields):
        path = args.outdir / filename
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        return path

    p1 = dump("formativo_maestro.csv", canonical, list(canonical[0]))
    p2 = dump("formativo_pendientes.csv", pending,
              ["nombre", "cohorte_estimada", "estado", "evidencia", "pedir"])
    p3 = dump("formativo_alias.csv", aliases, ["jugador", "alias", "motivo"]) \
        if aliases else None

    plantel = [r for r in canonical if r["estado"] == "plantel"]
    con_fecha = sum(1 for r in canonical if r["fecha_nacimiento"])
    bracket_col = f"bracket_{args.season}"
    print(f"temporada {args.season} · {len(canonical)} nombres")
    print(f"  plantel (cohorte resuelta) : {len(plantel)}")
    print(f"  con fecha de nacimiento    : {con_fecha}")
    print(f"  cohorte sólo estimada      : "
          f"{sum(1 for r in plantel if not r['fecha_nacimiento'])}")
    print(f"  jugadores a prueba         : "
          f"{sum(1 for r in canonical if r['estado'] == 'prueba')}")
    print(f"  sin resolver               : "
          f"{sum(1 for r in canonical if r['estado'] == 'pendiente')}")

    print(f"\nseries del plantel (bracket calculado para {args.season}):")
    by_cohort = Counter((r["cohorte"], r[bracket_col]) for r in plantel)
    for (cohort, rung), count in sorted(by_cohort.items(), reverse=True):
        print(f"  Serie {cohort:<6} {rung or '—':<24} {count}")

    # A birth date shared by three or more players is usually a filled-down
    # cell, not a coincidence. It does not block the import — matching guards
    # against merging same-date players whose names differ — but the club
    # should see it.
    compartidas = Counter(r["fecha_nacimiento"] for r in plantel if r["fecha_nacimiento"])
    sospechosas = {f: n for f, n in compartidas.items() if n >= 3}
    if sospechosas:
        print(f"\nfechas compartidas por 3+ jugadores (revisar con el club): "
              f"{len(sospechosas)}")
        for fecha, n in sorted(sospechosas.items(), key=lambda kv: -kv[1]):
            quienes = [r["nombre"] for r in plantel if r["fecha_nacimiento"] == fecha]
            print(f"  {fecha} ×{n}  {', '.join(q[:24] for q in quienes)}")

    subieron = [r for r in canonical if r["promocion"]]
    print(f"\njugadores que jugaron sobre su serie en {args.season}: {len(subieron)}")
    for r in subieron[:6]:
        print(f"  {r['nombre'][:26]:<28} Serie {r['cohorte']} → {r['promocion']}")
    if len(subieron) > 6:
        print(f"  … y {len(subieron) - 6} más (columna `promocion` del CSV)")

    print(f"\n→ {p1}\n→ {p2} ({len(pending)} filas)" + (f"\n→ {p3}" if p3 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
