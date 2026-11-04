"""The formativo's player register (tab JUGADORES of "Evaluaciones físicas")
as the rule for each player's Serie and birth date.

The club's sheet is the guide (the staff, 2026-11-04: "lo importante es
seguir las reglas del profe en el excel"):

* Serie = what the sheet's CATEGORÍA says, for the 2026 season: U20 →
  SUB-20; U18 → Serie 2008 or 2009 by birth year (Sub 18 holds both); any
  other U<n> → Serie <2026 − n>. The club places December births one
  category down — that is the club's rule, and it is followed as written.
* Birth date = the sheet's.

What it never does: create or deactivate players, touch the Primer Equipo or
inactive players, or act on a row it cannot pin to ONE player. Every skipped
row is reported with why:

* `contradiccion` — the sheet's category is more than `MAX_AGE_GAP` years
  from the player's age (three 2013-born kids listed as U20): a sheet error,
  not a rule.
* `ambiguo` / `sin_jugador` — no single player matches.
* `conflicto` — two rows of the sheet say different things about one player.
* `fecha_repetida` — the sheet gives the same birth date to `REPEATED_DOB`+
  players and it disagrees with SLAB: a copy error, the date is not changed.

Matching is stricter than the importers' (which fall back to the name
alone): birth date + ≥2 name words, or else the FULL name — or every
word of a shortened one — unique in the club. A correction must never land on a homonym.

Dry-run unless `commit=True` (`sync_formativo_roster --commit`).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from django.db import transaction

from core.models import Category, Club, Player

HOJA = "JUGADORES"
MAX_AGE_GAP = 2
REPEATED_DOB = 3
FORMATIVO = re.compile(r"^(Serie \d{4}|SUB-20)$")


def parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    t = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def target_category(u: str, birth_year: int | None, season: int) -> str | None:
    """The platform category the sheet's CATEGORÍA means this season."""
    m = re.fullmatch(r"U(\d{1,2})", (u or "").strip().upper())
    if not m:
        return None
    n = int(m.group(1))
    if n == 20:
        return "SUB-20"
    if n == 18:
        return f"Serie {birth_year}" if birth_year in (season - 18, season - 17) else None
    return f"Serie {season - n}"


def is_contradiction(u: str, birth_year: int | None, season: int) -> bool:
    m = re.fullmatch(r"U(\d{1,2})", (u or "").strip().upper())
    if not m or birth_year is None:
        return False
    return abs((season - birth_year) - int(m.group(1))) > MAX_AGE_GAP


@dataclass
class Cambio:
    player_id: str
    nombre: str
    serie_antes: str
    serie_despues: str | None = None
    nac_antes: date | None = None
    nac_despues: date | None = None


@dataclass
class Reporte:
    filas: int = 0
    sin_cambios: int = 0
    cambios: list[Cambio] = field(default_factory=list)
    saltados: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


class Matcher:
    def __init__(self, club: Club):
        from exams.formativo_gps_ingest import norm

        self.norm = norm
        self.by_dob: dict[date, list[tuple[set, Player]]] = defaultdict(list)
        self.by_full: dict[str, list[Player]] = defaultdict(list)
        for p in Player.objects.filter(category__club=club).select_related("category"):
            full = norm(" ".join(x for x in (p.first_name, p.last_name, p.second_last_name) if x and x != "-"))
            if p.date_of_birth:
                self.by_dob[p.date_of_birth].append((set(full.split()), p))
            self.by_full[full].append(p)

    def match(self, nombre: str, dob: date | None) -> tuple[Player | None, str]:
        key = self.norm(nombre)
        words = set(key.split())
        if dob and self.by_dob.get(dob):
            hits = [p for toks, p in self.by_dob[dob] if len(toks & words) >= 2]
            if len(hits) == 1:
                return hits[0], "fecha+nombre"
            if len(hits) > 1:
                return None, "ambiguo"
        same = self.by_full.get(key, [])
        if len(same) == 1:
            return same[0], "nombre completo"
        if same:
            return None, "ambiguo"
        # The sheet often shortens the name ("IGNACIO ALVIZU" for Ignacio
        # Alvizu Gómez): every word of it in ONE player's full name.
        if len(words) >= 2:
            hits = [p for full, ps in self.by_full.items() if words <= set(full.split()) for p in ps]
            if len(hits) == 1:
                return hits[0], "nombre abreviado"
            if hits:
                return None, "ambiguo"
        return None, "sin_jugador"


def plan(grid: list[list], club: Club, season: int) -> Reporte:
    from exams.formativo_gps_ingest import norm

    rep = Reporte()
    if not grid:
        return rep
    head = [norm(c) for c in grid[0]]
    ix = {c: i for i, c in enumerate(head) if c}
    i_nom = ix.get("JUGADOR")
    i_dob = next((i for c, i in ix.items() if "NACIMIENTO" in c), None)
    i_cat = ix.get("CATEGORIA")
    if i_nom is None or i_cat is None:
        raise ValueError("La hoja JUGADORES no tiene las columnas JUGADOR / CATEGORÍA.")

    matcher = Matcher(club)
    # A date the sheet repeats for several players reads as a copy error
    # (2006-05-26 three times in U20), not as their birth date.
    dob_count: dict = defaultdict(int)
    for r in grid[1:]:
        d = parse_date(r[i_dob]) if i_dob is not None and i_dob < len(r) and str(r[i_nom] if i_nom < len(r) else "").strip() else None
        if d:
            dob_count[d] += 1
    wanted: dict = {}                    # player_id → (player, serie, dob, row name)
    for r in grid[1:]:
        cell = lambda i: (r[i] if i is not None and i < len(r) else "")  # noqa: E731
        nombre = str(cell(i_nom) or "").strip()
        if not nombre:
            continue
        rep.filas += 1
        dob, u = parse_date(cell(i_dob)), str(cell(i_cat) or "").strip()
        p, how = matcher.match(nombre, dob)
        if p is None:
            rep.saltados[how].append(nombre)
            continue
        cat = p.category.name if p.category_id else ""
        if not p.is_active or not FORMATIVO.match(cat):
            continue                     # Primer Equipo / femenino / inactive: not this rule's
        year = (dob or p.date_of_birth).year if (dob or p.date_of_birth) else None
        if is_contradiction(u, year, season):
            rep.saltados["contradiccion"].append(f"{nombre} ({u}, nacido en {year})")
            continue
        serie = target_category(u, year, season)
        if serie is None:
            rep.saltados["sin_categoria"].append(f"{nombre} ({u or 'vacía'})")
        prev = wanted.get(p.id)
        if prev and (prev[1], prev[2]) != (serie, dob):
            rep.saltados["conflicto"].append(f"{nombre}: la hoja lo trae dos veces con datos distintos")
            wanted[p.id] = (p, None, None, nombre)
            continue
        wanted[p.id] = (p, serie, dob, nombre)

    for p, serie, dob, nombre in wanted.values():
        cat = p.category.name
        c = Cambio(player_id=str(p.id), nombre=" ".join(x for x in (p.first_name, p.last_name) if x), serie_antes=cat)
        if serie and serie != cat:
            c.serie_despues = serie
        if dob and dob != p.date_of_birth:
            if dob_count.get(dob, 0) >= REPEATED_DOB:
                rep.saltados["fecha_repetida"].append(f"{nombre}: la hoja dice {dob}, igual que otros {dob_count[dob] - 1}")
            else:
                c.nac_antes, c.nac_despues = p.date_of_birth, dob
        if c.serie_despues or c.nac_despues:
            rep.cambios.append(c)
        else:
            rep.sin_cambios += 1
    rep.cambios.sort(key=lambda c: (c.serie_despues or c.serie_antes, c.nombre))
    return rep


@transaction.atomic
def apply(rep: Reporte, club: Club) -> int:
    cats = {c.name: c for c in Category.objects.filter(club=club)}
    missing = {c.serie_despues for c in rep.cambios if c.serie_despues and c.serie_despues not in cats}
    if missing:
        raise ValueError(f"No existen las categorías: {', '.join(sorted(missing))}.")
    n = 0
    for c in rep.cambios:
        p = Player.objects.select_for_update().get(pk=c.player_id)
        fields = []
        if c.serie_despues:
            p.category = cats[c.serie_despues]
            fields.append("category")
        if c.nac_despues:
            p.date_of_birth = c.nac_despues
            fields.append("date_of_birth")
        p.save(update_fields=fields)
        n += 1
    return n


def run(origen: str, club: Club, *, season: int, commit: bool = False,
        creds_file: str = "", creds_json: str = "") -> Reporte:
    from exams.formativo_sources import abrir, match_sheet

    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    try:
        hoja = match_sheet(fuente.hojas(), HOJA)
        grid = fuente.filas(hoja) if hoja else []
    finally:
        fuente.cerrar()
    if not grid:
        raise ValueError("No se encontró la hoja JUGADORES.")
    rep = plan(grid, club, season)
    if commit:
        apply(rep, club)
    return rep
