"""Parse the Formativo's injury sheet (tab `E`) and match it to the roster.

The club keeps one Google Sheet for the youth medical area; its tab `E` is the
injury register: one row per injury since January 2022, across every category.
Step one of the import is this module — read the sheet and resolve each row to
a `Player` — because on this sheet the player is the hard part:

* `NOMBRE COMPLETO` is free text, in two casings, sometimes with one surname.
* `Rut`, `Edad` and `Posición` are a VLOOKUP against the club's own personal
  data tab and come back `#N/A` whenever the name is spelled differently there.
  So a missing RUT is not "no RUT": it is a name the club's lookup could not
  resolve either.
* The injured player may no longer be in the club — the register goes back to
  2022, the roster we hold does not.

Matching, strongest first, each row stamped with the method that resolved it
so a report can say how much rests on names alone:

    rut       the row's own RUT        → Player.national_id
    rut_dp    the name → `Datos Personales` → its RUT → Player.national_id
    dob       `Datos Personales` birth date + ≥2 shared name tokens
    nombre    exact normalised name (full, or first name + first surname)
    alias     a confirmed spelling stored as a `PlayerAlias` nickname
    parcial   one player whose name contains the row's, or is contained in
              it (roster with one surname fewer, or surnames written first)

Anything that resolves to two players is `ambiguo` and never guessed: filing
one player's injury under a namesake is an error nobody finds afterwards.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from core.models import Club, Player

SHEET_ID = "1ZagD0XPBO2IXwyLBCue6CaeGBh_MdAveIP9jtGjwc4k"
HOJA = "E"
HOJA_PERSONALES = "Datos Personales"

# Header → key. Looked up by name so a reordered column cannot shift values.
# `Columna 1` holds the season phase and `Columna 2` the status — the club
# never titled them.
COLUMNAS = {
    "NOMBRE COMPLETO": "nombre",
    "RUT": "rut",
    "EDAD": "edad",
    "CATEGORIA": "categoria",
    "POSICION": "posicion",
    "PARTE DE CUERPO LESIONADA": "region",
    "LATERALIDAD": "lado",
    "TIPO DE LESION": "tipo",
    "DIAGNOSTICO": "diagnostico",
    "MUSCULO": "musculo",
    "CAUSA": "causa",
    "RECURRENCIA": "recurrencia",
    "EXPOSICION": "exposicion",
    "CONTACTO COLISION": "contacto",
    "FECHA DE LESION": "fecha_lesion",
    "FECHA DE ALTA": "fecha_alta",
    "DIAS PERDIDOS POR LESION": "dias_perdidos",
    "N PARTIDOS": "partidos",
    "TRATAMIENTO": "tratamiento",
    "COLUMNA 1": "fase_temporada",
    "KINE RESPONSABLE": "kine",
    "COLUMNA 2": "estado",
}


def norm(value: object) -> str:
    """Upper-case, accent-free, letters and spaces only."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", text).split())


def norm_cab(value: object) -> str:
    """Like `norm` but keeps digits: `Columna 1` and `Columna 2` are two columns."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text).split())


def norm_rut(value: object) -> str:
    """`17.241.956-9` and `17241956-9` are the same RUT; `#N/A…` is none."""
    text = str(value or "").upper()
    if text.startswith("#"):
        return ""
    limpio = re.sub(r"[^0-9K]", "", text).lstrip("0")
    return limpio if len(limpio) >= 7 else ""


def _vacio(v) -> bool:
    return v is None or (isinstance(v, str) and (not v.strip() or v.startswith("#")))


def _fecha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _num(v) -> float | None:
    if isinstance(v, bool) or _vacio(v):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


@dataclass
class Lesion:
    fila: int                     # 1-based row in the sheet, for the report
    datos: dict[str, Any]

    @property
    def nombre(self) -> str:
        return str(self.datos.get("nombre") or "").strip()

    @property
    def fecha(self) -> date | None:
        return self.datos.get("fecha_lesion")


@dataclass
class Personal:
    rut: str
    dob: date | None
    tokens: set[str]


# ── parsing ─────────────────────────────────────────────────────────────
def _cabecera(cab: list) -> dict[str, int]:
    ix = {}
    for i, c in enumerate(cab):
        clave = norm_cab(c)
        if clave in COLUMNAS and COLUMNAS[clave] not in ix:
            ix[COLUMNAS[clave]] = i
    faltan = {"nombre", "fecha_lesion"} - set(ix)
    if faltan:
        raise ValueError(f"La hoja {HOJA!r} no trae {sorted(faltan)}")
    return ix


def parse_lesiones(grid) -> tuple[list[Lesion], int]:
    """Rows with a name. Returns (injuries, rows with a name but no date)."""
    filas = [list(f) for f in grid]
    ix = _cabecera(filas[0])
    lesiones, sin_fecha = [], 0
    for n, r in enumerate(filas[1:], start=2):
        get = lambda k: r[ix[k]] if k in ix and ix[k] < len(r) else None
        if _vacio(get("nombre")):
            continue
        datos: dict[str, Any] = {}
        for k in ix:
            v = get(k)
            if k in ("fecha_lesion", "fecha_alta"):
                datos[k] = _fecha(v)
            elif k in ("edad", "dias_perdidos", "partidos"):
                datos[k] = _num(v)
            elif not _vacio(v):
                datos[k] = str(v).strip()
        if datos.get("fecha_lesion") is None:
            sin_fecha += 1
            continue
        lesiones.append(Lesion(fila=n, datos=datos))
    return lesiones, sin_fecha


def parse_personales(grid) -> dict[str, Personal]:
    """`Datos Personales`: name → RUT + birth date, the bridge to the roster.

    Column 0 is the full name under a stray date serial instead of a title.
    """
    filas = [list(f) for f in grid]
    cab = [norm_cab(c) for c in filas[0]]
    i_rut, i_dob = cab.index("ID"), cab.index("FECHA DE NACIMIENTO")
    i_n1, i_n2 = cab.index("NOMBRE 1"), cab.index("NOMBRE 2")
    i_a1, i_a2 = cab.index("APELLIDO 1"), cab.index("APELLIDO 2")

    indice: dict[str, Personal] = {}
    repetidos: set[str] = set()
    for r in filas[1:]:
        get = lambda i: r[i] if i < len(r) else None
        n1, n2, a1, a2 = (norm(get(i)) for i in (i_n1, i_n2, i_a1, i_a2))
        completo = norm(get(0))
        if not (completo or (n1 and a1)):
            continue
        p = Personal(rut=norm_rut(get(i_rut)), dob=_fecha(get(i_dob)),
                     tokens=set(f"{n1} {n2} {a1} {a2} {completo}".split()))
        for clave in {completo, f"{n1} {a1} {a2}".strip(), f"{n1} {a1}".strip(),
                      f"{n1} {n2} {a1} {a2}".strip()}:
            if not clave:
                continue
            previo = indice.get(clave)
            if previo and (previo.rut, previo.dob) != (p.rut, p.dob):
                repetidos.add(clave)       # two people share this spelling
            indice[clave] = p
    for clave in repetidos:
        indice.pop(clave, None)
    return indice


# ── matching ────────────────────────────────────────────────────────────
@dataclass
class Match:
    player: Player | None
    metodo: str   # rut | rut_dp | alias | dob | nombre | parcial
    #               | ambiguo | conflicto_rut | conflicto_edad | sin_jugador
    candidatos: list[Player] = field(default_factory=list)


def _edad(p: Player, dia: date) -> int | None:
    b = p.date_of_birth
    if not b:
        return None
    return dia.year - b.year - ((dia.month, dia.day) < (b.month, b.day))


def _verificar(m: Match, lesion: Lesion) -> Match:
    """Reject a match the row's own data contradicts.

    * A RUT match must share at least one name token. The sheet's RUT is a
      VLOOKUP and our `national_id` was typed by hand; one row resolved a
      19-year-old's RUT to an 11-year-old.
    * A match by name must agree with the row's age within a year, which is
      how two namesakes two years apart are told apart. Ages of 60 and up are
      the sheet's `YEARFRAC` over an empty birth date and are ignored.
    """
    toks = set(norm(lesion.nombre).split())
    if m.metodo in ("rut", "rut_dp"):
        if not toks & _tokens(m.player):
            return Match(None, "conflicto_rut", [m.player])
        return m
    edad_fila = lesion.datos.get("edad")
    edad = _edad(m.player, lesion.fecha)
    if (edad_fila is not None and edad_fila < 60 and edad is not None
            and abs(edad_fila - edad) > 1):
        return Match(None, "conflicto_edad", [m.player])
    return m


def _completo(p: Player) -> str:
    return norm(f"{p.first_name} {p.last_name} {p.second_last_name}")


def _tokens(p: Player) -> set[str]:
    return set(_completo(p).split())


class Matcher:
    def __init__(self, club: Club, personales: dict[str, Personal]):
        self.personales = personales
        self.por_rut: dict[str, list[Player]] = defaultdict(list)
        self.por_dob: dict[date, list[tuple[set, Player]]] = defaultdict(list)
        self.por_nombre: dict[str, list[Player]] = defaultdict(list)
        self.tokens: list[tuple[set, Player]] = []
        for p in Player.objects.filter(category__club=club).select_related("category"):
            if (rut := norm_rut(p.national_id)):
                self.por_rut[rut].append(p)
            completo = norm(f"{p.first_name} {p.last_name} {p.second_last_name}")
            toks = set(completo.split())
            if p.date_of_birth:
                self.por_dob[p.date_of_birth].append((toks, p))
            primer = norm(p.first_name).split()[:1]
            claves = {completo, norm(f"{p.first_name} {p.last_name}")}
            if primer:
                claves.add(norm(f"{primer[0]} {p.last_name} {p.second_last_name}"))
                claves.add(norm(f"{primer[0]} {p.last_name}"))
            for clave in claves:
                if p not in self.por_nombre[clave]:
                    self.por_nombre[clave].append(p)
            self.tokens.append((toks, p))
        # A confirmed spelling (`BYRON RIOS GERRERO` → Bayron Ríos Guerrero)
        # is stored once as a nickname alias and resolves forever after —
        # the same table `import_lesiones` and the wellness importer read.
        from core.models import PlayerAlias

        self.por_alias: dict[str, list[Player]] = defaultdict(list)
        for a in (PlayerAlias.objects
                  .filter(player__category__club=club, kind=PlayerAlias.KIND_NICKNAME)
                  .select_related("player__category")):
            self.por_alias[norm(a.value)].append(a.player)

    @staticmethod
    def _uno(candidatos: list[Player], metodo: str, toks: set[str]) -> Match:
        """One candidate, or the only one the row's own name agrees with.

        The name breaks ties even under a RUT match, because two roster rows
        CAN share a RUT: ours has two pairs whose RUT and birth date were
        copied from one player to the other. The tie is broken only by a
        clear winner (≥2 shared tokens, strictly more than anyone else).
        """
        unicos = list({p.pk: p for p in candidatos}.values())
        if len(unicos) == 1:
            return Match(unicos[0], metodo)
        puntos = sorted(((len(toks & _tokens(p)), p) for p in unicos),
                        key=lambda t: -t[0])
        if puntos[0][0] >= 2 and puntos[0][0] > puntos[1][0]:
            return Match(puntos[0][1], metodo, unicos)
        return Match(None, "ambiguo", unicos)

    def match(self, lesion: Lesion) -> Match:
        m = self._match(lesion)
        return _verificar(m, lesion) if m.player else m

    def _match(self, lesion: Lesion) -> Match:
        clave = norm(lesion.nombre)
        toks = set(clave.split())
        personal = self.personales.get(clave)

        for rut, metodo in ((norm_rut(lesion.datos.get("rut")), "rut"),
                            (personal.rut if personal else "", "rut_dp")):
            if rut and self.por_rut.get(rut):
                return self._uno(self.por_rut[rut], metodo, toks)

        if self.por_alias.get(clave):
            return self._uno(self.por_alias[clave], "alias", toks)

        if personal and personal.dob and self.por_dob.get(personal.dob):
            buenos = [p for t, p in self.por_dob[personal.dob]
                      if len(t & (toks | personal.tokens)) >= 2]
            if buenos:
                return self._uno(buenos, "dob", toks | personal.tokens)

        if self.por_nombre.get(clave):
            return self._uno(self.por_nombre[clave], "nombre", toks)

        if len(toks) >= 2:
            contienen = [p for t, p in self.tokens if toks <= t]
            if contienen:
                return self._uno(contienen, "parcial", toks)
            # The other direction: the ROSTER carries one surname fewer
            # (`Nazih Avendano` for `NAZIH AVENDAÑO CORONA`), or the sheet
            # writes surnames first. Every roster token must be in the row.
            contenidos = [p for t, p in self.tokens if len(t) >= 2 and t <= toks]
            if contenidos:
                return self._uno(contenidos, "parcial", toks)
        return Match(None, "sin_jugador")

    def sugerencia(self, nombre: str) -> tuple[Player, float] | None:
        """Closest roster name, for a human to confirm — never auto-assigned.

        Compared both whole and against first name + first surname, since the
        sheet often carries one surname fewer than the roster.
        """
        from difflib import SequenceMatcher

        clave = norm(nombre)
        mejor, puntaje = None, 0.0
        for _, p in self.tokens:
            corto = norm(f"{norm(p.first_name).split()[0] if p.first_name.strip() else ''} "
                         f"{p.last_name}")
            r = max(SequenceMatcher(None, clave, _completo(p)).ratio(),
                    SequenceMatcher(None, clave, corto).ratio())
            if r > puntaje:
                mejor, puntaje = p, r
        return (mejor, puntaje) if mejor and puntaje >= 0.8 else None

    def ruts_compartidos(self) -> list[list[Player]]:
        return [ps for ps in self.por_rut.values() if len(ps) > 1]


# ── report ──────────────────────────────────────────────────────────────
@dataclass
class Reporte:
    filas: int = 0
    sin_fecha: int = 0
    por_metodo: Counter = field(default_factory=Counter)
    por_anio: dict = field(default_factory=lambda: defaultdict(Counter))
    activas: Counter = field(default_factory=Counter)
    jugadores: set = field(default_factory=set)
    sin_jugador: dict = field(default_factory=lambda: defaultdict(list))
    ambiguos: dict = field(default_factory=dict)
    fuera_formativo: Counter = field(default_factory=Counter)
    en_personales: set = field(default_factory=set)
    sugerencias: dict = field(default_factory=dict)
    ruts_compartidos: list = field(default_factory=list)
    conflictos: list = field(default_factory=list)
    desempatados: int = 0


def leer(origen: str = SHEET_ID, *, creds_file: str = "", creds_json: str = ""):
    from exams.formativo_sources import abrir, match_sheet

    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    hojas = fuente.hojas()
    lesiones, sin_fecha = parse_lesiones(fuente.filas(match_sheet(hojas, HOJA)))
    real = match_sheet(hojas, HOJA_PERSONALES)
    personales = parse_personales(fuente.filas(real)) if real else {}
    fuente.cerrar()
    return lesiones, sin_fecha, personales


def diagnosticar(club: Club, lesiones: list[Lesion], personales: dict,
                 sin_fecha: int = 0) -> tuple[Reporte, list[tuple[Lesion, Match]]]:
    matcher = Matcher(club, personales)
    rep = Reporte(filas=len(lesiones), sin_fecha=sin_fecha)
    pares = []
    for les in lesiones:
        m = matcher.match(les)
        pares.append((les, m))
        ok = m.player is not None
        rep.por_metodo[m.metodo] += 1
        rep.por_anio[les.fecha.year]["ok" if ok else "no"] += 1
        if norm(les.datos.get("estado")) == "LESIONADO":
            rep.activas["ok" if ok else "no"] += 1
        if ok:
            rep.jugadores.add(m.player.pk)
            rep.desempatados += bool(m.candidatos)
            if m.player.category.is_senior:
                rep.fuera_formativo[m.player.category.name] += 1
        elif m.metodo.startswith("conflicto"):
            p = m.candidatos[0]
            rep.conflictos.append(
                f"{m.metodo[10:]:<5} fila {les.fila}: {les.nombre} ({les.fecha}, "
                f"edad {les.datos.get('edad')}, rut {les.datos.get('rut', '—')}) "
                f"≠ {p.first_name} {p.last_name} {p.second_last_name} "
                f"({p.category.name}, {p.date_of_birth}, rut {p.national_id or '—'})")
        elif m.metodo == "ambiguo":
            rep.ambiguos[les.nombre] = [
                f"{p.first_name} {p.last_name} {p.second_last_name} "
                f"({p.category.name}, {p.date_of_birth})" for p in m.candidatos]
        else:
            rep.sin_jugador[les.nombre].append(les.fecha)
    for nombre in rep.sin_jugador:
        if norm(nombre) in personales:
            rep.en_personales.add(nombre)
        if (s := matcher.sugerencia(nombre)):
            rep.sugerencias[nombre] = s
    rep.ruts_compartidos = matcher.ruts_compartidos()
    return rep, pares


# ── mapping onto the `lesiones` template ────────────────────────────────
# The sheet's vocabulary → the template's option VALUES (accent-free, as
# `seed_lesiones` declares them). Keyed by `norm()` so casing, accents and the
# club's typos (`Rodill`) collapse onto one entry.
REGION = {
    "MUSLO": "Muslo", "RODILLA": "Rodilla", "RODILL": "Rodilla",
    "TOBILLO": "Tobillo", "C LUMBAR SACRO PELVIS": "Columna lumbar/Pelvis",
    "PIE DEDOS DEL PIE": "Pie/Dedos pie", "PIE": "Pie/Dedos pie",
    "PIERNA TENDON DE AQUILES": "Pierna/Aquiles", "CADERA": "Cadera/Ingle",
    "MANO DEDO PULGAR": "Mano/Dedos", "HOMBRO CLAVICULA": "Hombro/Clavicula",
    "CABEZA CARA": "Cabeza/Cara", "MUNECA": "Muneca",
    "CUELLO C CERVICAL": "Cuello/C. cervical",
    "ESTERNON COSTILLAS C TORACICA": "Torax/Costillas", "ANTEBRAZO": "Antebrazo",
    "CODO": "Codo", "ABDOMEN": "Abdomen", "BRAZO": "Brazo",
}
# `Otra lesión ósea` is NOT a fracture — it is where the club files Osgood,
# Sever, Iselin, periostitis: growth-plate and stress conditions of a youth
# squad. Mapping it to `Fractura/Estres oseo` would triple the fracture count
# in any Fuller statistic, so it goes to `Otro` and the club's own label is
# kept in `tipo_club`.
TIPO = {
    "ROTURA MUSCULAR DESGARRO CONTRACTURA CALAMBRE": "Lesion muscular (desgarro/rotura)",
    "ESGUINCE LESION DE LIGAMENTO": "Esguince/Lesion ligamentosa",
    "FRACTURA": "Fractura/Estres oseo",
    "LESION TENDON ROTURA TENDINOSIS BURSITIS": "Lesion tendinosa/Tendinopatia",
    "HEMATOMA CONTUSION EQUIMOSIS": "Contusion/Hematoma",
    "LESION MENISCO CARTILAGO": "Lesion meniscal/cartilago",
    "DISLOCACION SUBLUXACION": "Luxacion/Subluxacion",
    "CONCUSION": "Conmocion", "LACERACION": "Laceracion/Abrasion",
    "OTRA LESION OSEA": "Otro", "OTRA LESION": "Otro",
}
LADO = {"DERECHO": "Derecho", "IZQUIERDO": "Izquierdo", "NO APLICA": "NA"}
MODO = {"SOBRECARGA": "Sobreuso/Gradual", "TRAUMATICA": "Agudo/Traumatico"}
RECURRENCIA = {"NO": "Nueva", "SI": "Recurrente"}
TRATAMIENTO = {
    "KINESICO": "Kinésico", "KINESICO QUIRURGICO": "Kinésico + quirúrgico",
    "QUIRURGICO": "Kinésico + quirúrgico", "REPOSO DEPORTIVO": "Reposo deportivo",
}
ORIGEN = "planilla_club_lesiones_formativo"
DEDUP_DIAS = 7          # an existing episode this close is the same injury
REVISAR_DIAS = 180      # open this long → ask the club whether it is still open


def severidad(dias: int | None) -> str | None:
    """Fuller et al. (2006) time-loss bands."""
    if dias is None:
        return None
    if dias == 0:
        return "Sin tiempo perdido"
    return ("Minima" if dias <= 3 else "Leve" if dias <= 7
            else "Moderada" if dias <= 28 else "Severa")


@dataclass
class Plan:
    lesion: Lesion
    player: Player
    origen_id: str
    datos: dict[str, Any]
    inicio: date
    alta: date | None             # None → the episode stays open
    accion: str = "crear"         # crear | cerrar | ya_existe | duplicado | omitir_senior
    nota: str = ""
    episodio: Any = None          # the episode a re-run found for this row


def _origen_id(player: Player, les: Lesion) -> str:
    """Player + date + region: survives the club fixing a name's spelling."""
    return f"{player.pk}|{les.fecha.isoformat()}|{norm(les.datos.get('region'))}"


def _partido_oficial(player: Player, dia: date) -> bool:
    from datetime import timedelta
    from exams.models import ExamResult

    return ExamResult.objects.filter(
        player=player, template__slug="ficha_partido",
        recorded_at__date__gte=dia - timedelta(days=1),
        recorded_at__date__lte=dia + timedelta(days=1)).exists()


def planificar(pares: list[tuple[Lesion, Match]], hoy: date) -> list[Plan]:
    from exams.models import Episode

    existentes = {}
    for ep in (Episode.objects.filter(template__slug="lesiones",
                                      player__in={m.player for _, m in pares if m.player})
               .only("id", "player_id", "started_at", "status", "legacy_raw", "title")):
        existentes.setdefault(ep.player_id, []).append(ep)

    planes, vistos = [], set()
    for les, m in pares:
        p = m.player
        if p is None:
            continue
        d = les.datos
        alta = d.get("fecha_alta")
        nota = ""
        if alta and alta < les.fecha:
            nota = f"alta {alta} anterior a la lesión — duración desconocida"
            alta_real, dias = les.fecha, None
        elif alta and alta > hoy:
            alta_real, dias = None, None           # scheduled discharge: still out
        elif alta:
            alta_real, dias = alta, (alta - les.fecha).days
        elif norm(d.get("estado")) == "LESIONADO":
            alta_real, dias = None, None
        else:
            # "Alta" with no discharge date: closed, but on an unknown day.
            # Closed at the injury date so it does not read as ongoing, with
            # no duration rather than the sheet's TODAY()-based count.
            nota = "alta sin fecha — duración desconocida"
            alta_real, dias = les.fecha, None

        exposicion = None
        if norm(d.get("exposicion")) == "ENTRENAMIENTO":
            exposicion = "Entrenamiento"
        elif norm(d.get("exposicion")) == "PARTIDO" and _partido_oficial(p, les.fecha):
            exposicion = "Partido oficial"
        partidos = d.get("partidos")
        datos = {
            "diagnosed_at": les.fecha.isoformat(),
            "type": TIPO.get(norm(d.get("tipo"))),
            "tipo_club": d.get("tipo"),
            "exposicion_club": d.get("exposicion"),
            "body_part": REGION.get(norm(d.get("region"))),
            "lado": LADO.get(norm(d.get("lado"))),
            "body_part_detail": " ".join(str(d.get("diagnostico") or "").split()) or None,
            "musculo": d.get("musculo"),
            "severity": severidad(dias),
            "exposicion": exposicion,
            "modo": MODO.get(norm(d.get("causa"))),
            "mecanismo": "Contacto con jugador" if norm(d.get("contacto")) == "PATADA" else None,
            "recurrencia": RECURRENCIA.get(norm(d.get("recurrencia"))),
            "tratamiento": TRATAMIENTO.get(norm(d.get("tratamiento"))),
            "dias_perdidos": dias,
            # A negative value is a date serial typed into the column.
            "partidos_perdidos": int(partidos) if partidos is not None and 0 <= partidos <= 100 else None,
            "fase_temporada": d.get("fase_temporada"),
            "kine_responsable": d.get("kine"),
        }
        if alta and alta > hoy:
            datos["expected_return_date"] = alta.isoformat()
        datos = {k: v for k, v in datos.items() if v is not None}

        plan = Plan(les, p, _origen_id(p, les), datos, les.fecha, alta_real, nota=nota)
        if plan.origen_id in vistos:
            plan.accion = "duplicado"
        else:
            vistos.add(plan.origen_id)
            propio = next((e for e in existentes.get(p.pk, [])
                           if (e.legacy_raw or {}).get("origen_id") == plan.origen_id), None)
            ajeno = next((e for e in existentes.get(p.pk, [])
                          if (e.legacy_raw or {}).get("origen") != ORIGEN and e.started_at
                          and abs((e.started_at.date() - les.fecha).days) <= DEDUP_DIAS), None)
            if propio is not None:
                # Re-run: the only change applied is the one that matters
                # clinically — an injury the club has since discharged.
                plan.accion = ("cerrar" if propio.status == Episode.STATUS_OPEN and alta_real
                               else "ya_existe")
                plan.episodio = propio
            elif ajeno is not None:
                plan.accion = "ya_existe"
                plan.nota = f"ya registrada: {ajeno.started_at.date()} «{ajeno.title}»"
            elif p.category.is_senior and alta_real is None:
                # An OPEN injury on a first-team player would flip his status
                # from a sheet the first team's medical staff do not keep.
                plan.accion = "omitir_senior"
        planes.append(plan)
    return planes


def escribir(planes: list[Plan], fuente: str) -> dict[str, int]:
    """Create the episodes. Caller wraps it in a transaction."""
    from datetime import time

    from django.utils import timezone

    from exams.models import Episode, ExamResult, ExamTemplate

    def aware(d: date, hora: int = 12):
        return timezone.make_aware(datetime.combine(d, time(hora, 0)))

    # The episode's state is its LATEST result by `recorded_at`, and a tie is
    # resolved arbitrarily: an injury discharged the day it happened (or whose
    # discharge date is unknown) came out open six times in 584. The closing
    # result is therefore stamped at the end of the day.
    CIERRE = 18

    plantillas: dict[int, ExamTemplate] = {}

    def plantilla(player):
        club_id = player.category.club_id
        if club_id not in plantillas:
            plantillas[club_id] = (
                ExamTemplate.objects.filter(slug="lesiones", department__club_id=club_id,
                                            is_active_version=True).first()
                or ExamTemplate.objects.get(slug="lesiones", department__club_id=club_id))
        return plantillas[club_id]

    n = Counter()
    for pl in planes:
        if pl.accion == "cerrar":
            ep = pl.episodio
            ExamResult.objects.create(
                player=pl.player, template=ep.template, episode=ep,
                recorded_at=aware(pl.alta, CIERRE), result_data=dict(pl.datos, stage="closed"),
                inputs_snapshot={})
            Episode.objects.filter(pk=ep.pk, available_at__isnull=True).update(
                available_at=aware(pl.alta, CIERRE))
            n["cerradas"] += 1
            continue
        if pl.accion != "crear":
            continue
        template = plantilla(pl.player)
        ep = Episode.objects.create(
            player=pl.player, template=template, started_at=aware(pl.inicio),
            legacy_raw={"origen": ORIGEN, "origen_id": pl.origen_id, "fuente": fuente,
                        "fila": pl.lesion.fila,
                        "data": {k: (v.isoformat() if isinstance(v, date) else v)
                                 for k, v in pl.lesion.datos.items()}})
        ExamResult.objects.create(
            player=pl.player, template=template, episode=ep,
            recorded_at=aware(pl.inicio), result_data=dict(pl.datos, stage="aguda"),
            inputs_snapshot={})
        if pl.alta is not None:
            ExamResult.objects.create(
                player=pl.player, template=template, episode=ep,
                recorded_at=aware(pl.alta, CIERRE), result_data=dict(pl.datos, stage="closed"),
                inputs_snapshot={})
            Episode.objects.filter(pk=ep.pk).update(available_at=aware(pl.alta, CIERRE))
            n["cerradas"] += 1
        else:
            n["abiertas"] += 1
        n["creadas"] += 1
    return dict(n)
