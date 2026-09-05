"""Ingest of the Formativo's eight wellness documents (Check-IN + Check-OUT).

One Google Form per category, each writing into its own spreadsheet: eight
documents, two response tabs apiece, ~65.000 check-ins and ~53.000 check-outs
going back to February 2024 and still being filled today.

Why the column map is by NAME and never positional
--------------------------------------------------
The eight forms were built separately and drifted. Same question, different
column index in every document — `SUB 13` puts weight and hydration in columns
2 and 3 where everyone else has them in 8 and 10, and `SUB 16` keeps muscle
damage in column 10 instead of 4. A positional reader would load hydration into
sleep quality for one whole category and report success.

They also drifted in wording, so the map carries the variants the club actually
typed:

    CALIDAD SUEÑO           / CALIDAD DEL SUEÑO
    Peso (kg) solo número   / Peso (kg)
    DAÑO MUSCULAR           / PERCEPCIÓN MOLESTIAS/DOLORES   (check-out)
    UA                      / AU

⚠️ The scale is NOT inverted
---------------------------
In this form **5 is the best answer for all five check-in items**, fatigue,
stress and muscle damage included: `NIVEL DE FATIGA` 5 means "no fatigue".
That was verified against the club's own `SUMA` column, which is the RAW sum of
the five — 25.146 rows across three documents match the raw sum exactly and
none match a mirrored version. The check-out's damage item points the same way:
players scoring 1–2 name a sore muscle in 50–70% of rows, players scoring 5 in
1%. Getting this backwards is invisible — every number stays in range and the
squad simply looks fine when it is wrecked.

`SUMA` and `UA` are not imported
--------------------------------
Both are derived, and their headers are inconsistent across the eight files —
`SUMA` in five, absent in three, a bare empty header in one; `UA` in six and
`AU` in one. A column whose own name is a typo is how a metric goes half-empty
in silence, so the templates compute them.

Which player, not which category
--------------------------------
The document title carries a category (`SUB 11 - 2026 - CAT 15`), but it is a
stale copy of a fact SLAB already holds: one title still says 2025, and the top
two span several cohorts (`CAT 08-07`, `CAT 07-05`). So rows match on the
player NAME across the club, and the player's own category — set by the master
import from the club's roster — decides where the result lands. The title is
used only to disambiguate a homonym, and to report a row whose player is not in
that document's categories.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

CHECKIN_SLUG = "checkin_formativo"
CHECKOUT_SLUG = "checkout_formativo"

HOJA_CHECKIN = "CHECK IN"
HOJA_CHECKOUT = "CHECK OUT"


def norm(value: object) -> str:
    """Upper-case, accent-free, punctuation-free, single-spaced."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text).split())


# ─── Column maps ──────────────────────────────────────────────────────
#
# Keyed by the NORMALIZED header. Every variant the eight documents use has to
# be listed: an unmapped column is reported loudly rather than dropped, because
# a silently dropped column is exactly how a metric goes missing.

COL_CHECKIN: dict[str, str] = {
    "MARCA TEMPORAL": "_ts",
    "JUGADOR": "_jugador",
    "CALIDAD SUENO": "calidad_sueno",
    "CALIDAD DEL SUENO": "calidad_sueno",
    "NIVEL DE FATIGA": "nivel_fatiga",
    "NIVEL DE ESTRES": "nivel_estres",
    "ESTADO DE ANIMO": "estado_animo",
    "DANO MUSCULAR": "dano_muscular",
    "CUAL ES TU NIVEL DE RECUPERACION CON RESPECTO A LA SESION ANTERIOR":
        "nivel_recuperacion",
    "SINTOMAS": "sintomas",
    "PESO KG SOLO NUMERO": "peso",
    "PESO KG": "peso",
    "SENALA TU DOLOR MUSCULAR": "dolor_muscular",
    "SENALA TU NIVEL DE HIDRATACION": "hidratacion",
    "ESTAN SIENDO ARMONICAS TUS RELACIONES AFECTIVAS Y O FAMILIARES":
        "relaciones_afectivas",
    "ASISTIO A CLASES ESCOLARES": "asistio_clases",
    "SENALA TU ULTIMA COMIDA ANTES DE ENTRENAR": "ultima_comida",
    # Derivada: la calcula la plantilla.
    "SUMA": None,
}

COL_CHECKOUT: dict[str, str] = {
    "MARCA TEMPORAL": "_ts",
    "JUGADOR": "_jugador",
    "DURACION SESION MIN": "duracion_min",
    "NIVEL DE ESFUERZO PERCIBIDO": "rpe",
    "DANO MUSCULAR": "dano_muscular",
    "PERCEPCION MOLESTIAS DOLORES": "dano_muscular",
    "LA MOLESTIA DOLOR ES EN ALGUNO DE ESTOS MUSCULOS ISQUIOTIBIALES":
        "molestia_isquiotibiales",
    "LA MOLESTIA DOLOR ES EN ALGUNO DE ESTOS MUSCULOS ADUCTORES":
        "molestia_aductores",
    "LA MOLESTIA DOLOR ES EN ALGUNO DE ESTOS MUSCULOS CUADRICEPS":
        "molestia_cuadriceps",
    "LA MOLESTIA DOLOR ES EN ALGUNO DE ESTOS MUSCULOS GEMELOS":
        "molestia_gemelos",
    "SENALA SI TUVISTE ALGUNA MOLESTIA MUSCULAR DESPUES DEL ENTRENAMIENTO":
        "molestia_post",
    "OTRAS MOLESTIAS U OBSERVACIONES": "observaciones",
    "PARTIDO CAPACIDAD DE RECUPERACION ENTRE ESFUERZOS": "partido_recuperacion",
    "PARTIDO RENDIMIENTO EN ACCIONES EXPLOSIVAS SPRINTS SALTOS ACCIONES 1VS1":
        "partido_explosivas",
    "PARTIDO RENDIMIENTO FISICO GENERAL DURANTE EL PARTIDO": "partido_fisico",
    "SENALA TU TIPO DE ENTRENAMIENTO": "tipo_entrenamiento",
    "CONSUMISTE TU PROTEINA POST ENTRENAMIENTO": "proteina_post",
    "CUANTOS PUNTOS SUMASTE DE RECUPERACION POSTERIOR A LA SESION":
        "puntos_recuperacion",
    # Derivada: RPE × duración, la calcula la plantilla. `AU` es el typo de uno
    # de los ocho documentos.
    "UA": None,
    "AU": None,
}

# Campos numéricos por hoja: todo lo demás se guarda como texto limpio.
NUM_CHECKIN = frozenset({
    "calidad_sueno", "nivel_fatiga", "nivel_estres", "estado_animo",
    "dano_muscular", "nivel_recuperacion", "hidratacion", "peso",
})
NUM_CHECKOUT = frozenset({
    "duracion_min", "rpe", "dano_muscular", "partido_recuperacion",
    "partido_explosivas", "partido_fisico", "puntos_recuperacion",
})

# Una respuesta tiene que traer al menos uno de estos, o es una fila vacía que
# el formulario dejó por arrastre.
CLAVES_CHECKIN = frozenset({"calidad_sueno", "nivel_fatiga", "nivel_estres",
                            "estado_animo", "dano_muscular", "peso"})
CLAVES_CHECKOUT = frozenset({"duracion_min", "rpe", "dano_muscular",
                             "molestia_post"})

# Texto que significa "nada" en las columnas libres de molestia. Guardarlo tal
# cual llenaría la bitácora de "Ninguno" y haría imposible contar molestias.
VACIOS = frozenset({"", "NO", "NINGUNO", "NINGUNA", "NADA", "SIN MOLESTIAS",
                    "NINGUN DOLOR", "SIN DOLOR", "NINGUNA MOLESTIA", "N A"})

# ⚠️ Y SÓLO en esas columnas. `NO` está en la lista porque es como el jugador
# dice "no me duele nada", pero también es la respuesta legítima de
# `¿Consumiste tu proteína post-entrenamiento?` y de `¿ASISTIÓ A CLASES
# ESCOLARES?`. Aplicar el filtro a todo el texto convertía cada "No" de esas
# dos preguntas en un campo ausente, que es indistinguible de no haber
# contestado.
CAMPOS_MOLESTIA = frozenset({
    "sintomas", "dolor_muscular", "molestia_post", "observaciones",
    "molestia_isquiotibiales", "molestia_aductores", "molestia_cuadriceps",
    "molestia_gemelos",
})


def es_vacio(valor: object) -> bool:
    return norm(valor) in VACIOS


def _num(raw: object) -> float | int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
    else:
        t = str(raw).strip().replace(",", ".")
        if not t:
            return None
        try:
            v = float(t)
        except ValueError:
            return None
    return int(v) if v == int(v) else round(v, 2)


def _texto(raw: object) -> str:
    return " ".join(str(raw or "").split())


@dataclass
class Reporte:
    documento: str = ""
    hoja: str = ""
    filas: int = 0
    creados: int = 0
    repetidos: int = 0
    vacias: int = 0
    sin_fecha: int = 0
    sin_jugador: int = 0
    fuera_de_categoria: int = 0
    alertas: int = 0
    no_encontrados: dict = field(default_factory=dict)
    ambiguos: dict = field(default_factory=dict)
    columnas_sin_mapear: list = field(default_factory=list)

    def dict(self) -> dict:
        d = self.__dict__.copy()
        d["no_encontrados"] = dict(sorted(
            self.no_encontrados.items(), key=lambda kv: -kv[1])[:25])
        d["ambiguos"] = dict(sorted(
            self.ambiguos.items(), key=lambda kv: -kv[1])[:25])
        return d


def cohortes_del_titulo(titulo: str) -> list[int]:
    """Cohort years a document covers, from `… - CAT 08-07` / `… - CAT 15`.

    Two-digit years, and a document can list several: `CAT 07-05` is the 2007,
    2006 and 2005 cohorts. Returns [] when the title says nothing — the caller
    then falls back to the whole club, which is the safe direction.
    """
    # ⚠️ Contra el título YA NORMALIZADO, donde `CAT 08-07` es `CAT 08 07`:
    # `norm` reemplaza la puntuación por espacios. Una regex que todavía
    # buscara el guion falla justo en los dos documentos multi-cohorte, que son
    # los que tienen los homónimos.
    m = re.search(r"\bCAT((?:\s+[0-9]{2})+)\s*$", norm(titulo))
    if not m:
        return []
    partes = [int(p) for p in re.findall(r"[0-9]{2}", m.group(1))]
    años = [2000 + p for p in partes]
    if len(años) == 2 and años[0] > años[1]:
        # `CAT 07-05` es un RANGO: 2007, 2006 y 2005.
        return list(range(años[1], años[0] + 1))
    return sorted(set(años))


class Indice:
    """Los cuatro índices que hacen falta para resolver un nombre escrito a mano.

    Dos ejes que se cruzan:

    * **nivel** — primarias (nombre + paterno, en los dos órdenes, con y sin
      materno) y secundarias (nombre + materno). Las secundarias existen porque
      `Mathias Restrepo Rojas` firma `MATHIAS ROJAS`, y se consultan sólo si
      las primarias no encontraron a nadie.
    * **alcance** — todo el club, o acotado a las cohortes del documento, que
      es lo único que desempata a los dos `David Guzmán`.
    """

    def __init__(self):
        self.club: dict[str, list] = {}
        self.club_sec: dict[str, list] = {}
        self.cohorte: dict[int, dict[str, list]] = {}
        self.cohorte_sec: dict[int, dict[str, list]] = {}

    def _add(self, destino, clave, player):
        destino.setdefault(clave, []).append(player)

    def agregar(self, player, primarias, secundarias, años):
        for clave in primarias:
            self._add(self.club, clave, player)
            for a in años:
                self._add(self.cohorte.setdefault(a, {}), clave, player)
        for clave in secundarias:
            self._add(self.club_sec, clave, player)
            for a in años:
                self._add(self.cohorte_sec.setdefault(a, {}), clave, player)


def indice_jugadores(club) -> Indice:
    """Build the four name indices for a club's roster."""
    from core.models import Player

    indice = Indice()
    qs = (Player.objects.filter(category__club=club)
          .select_related("category").only(
              "id", "first_name", "last_name", "second_last_name",
              "date_of_birth", "category__id", "category__cohort_year"))
    for p in qs:
        # Dos vías al mismo jugador. La categoría no siempre lleva cohorte: el
        # bucket de arriba (`SUB-20`) junta 2007, 2006 y 2005 y su
        # `cohort_year` es NULL, así que sus jugadores sólo aparecen por su
        # año de nacimiento — y ahí es justamente donde viven los homónimos
        # que hay que desempatar.
        años = {a for a in (p.category.cohort_year,
                            p.date_of_birth.year if p.date_of_birth else None) if a}
        primarias, secundarias = _claves_nombre(p)
        indice.agregar(p, primarias, secundarias, años)
    return indice


def _claves_nombre(player) -> tuple[set[str], set[str]]:
    """(primarias, secundarias) — every written form of one player's name.

    `JUGADOR` is a free-text field the player types, so the same person arrives
    as `NOMBRE APELLIDO` in one document and `APELLIDO NOMBRE` in another, with
    or without the second surname.

    The second surname is not optional here. Chilean compound surnames are
    split across `last_name` and `second_last_name`, so `Tomás De Araya` is
    stored as last=`De` second=`Araya` and matching on first+last alone looks
    for `TOMAS DE` — which is why 37 of his check-ins came back "sin jugador"
    while his record was sitting right there.
    """
    nombre = norm(player.first_name)
    ap1 = norm(player.last_name)
    ap2 = norm(getattr(player, "second_last_name", "") or "")
    if not (nombre or ap1):
        return set(), set()
    primarias = {f"{nombre} {ap1}".strip(), f"{ap1} {nombre}".strip()}
    secundarias = set()
    if ap2:
        primarias |= {f"{nombre} {ap1} {ap2}".strip(),
                      f"{ap1} {ap2} {nombre}".strip()}
        # `nombre + materno`: `Mathias Restrepo Rojas` firma `MATHIAS ROJAS`,
        # y son 760 filas suyas. Pero va en SEGUNDO nivel, nunca al lado de las
        # primarias: si compitiera de igual a igual, `Lucas Pantoja Nuñez`
        # reclamaría la clave `LUCAS NUÑEZ` que es de `Lucas Nuñez Leon` y las
        # dos quedarían ambiguas. Medido con las claves mezcladas: recupera 760
        # filas y bloquea ~970.
        secundarias.add(f"{nombre} {ap2}".strip())
    primarias = {c for c in primarias if c}
    return primarias, {c for c in secundarias if c and c not in primarias}


def _lev1(a: str, b: str) -> bool:
    """True when `a` and `b` differ by at most ONE edit.

    Only one, and only as a last resort: the two real misses in the club's
    documents are `BRAYAN` for `BRYAN` and `CHIARI` for `CHARI`, both a single
    character. Anything looser starts attributing one player's wellness to
    another, which is worse than a reported miss.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1,
                              previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1] <= 1


def _por_typo(clave: str, indice: dict):
    """Unique player whose name is one edit away, or None."""
    hits = {}
    for candidata, players in indice.items():
        if abs(len(candidata) - len(clave)) <= 1 and _lev1(candidata, clave):
            for p in players:
                hits[p.id] = p
            if len(hits) > 1:
                return None
    return next(iter(hits.values())) if len(hits) == 1 else None


def resolver_jugador(bruto: str, indice: "Indice", cohortes: list[int]):
    """(player, motivo). `motivo` is None on success.

    The order is the whole design, from strongest evidence to weakest:

    1. primary name, restricted to the document's own cohorts;
    2. primary name, across the club;
    3. secondary name (first + mother's surname), same two scopes;
    4. a single-character typo, same two scopes.

    Cohort first is what separates the two `David Guzmán` — 2008 fills the
    SUB 18 form, 2011 the SUB 15 one — and a step is only taken when the one
    before it found NOBODY. An ambiguity is reported, never resolved in favour
    of one: attributing a player's wellness to his namesake is a silent error
    the club would have no way to see.
    """
    clave = norm(bruto)
    if not clave:
        return None, "sin_jugador"

    def unico(mapa):
        ps = {p.id: p for p in mapa.get(clave, [])}
        if len(ps) == 1:
            return next(iter(ps.values())), None
        return (None, "ambiguo") if ps else (None, None)

    def por_cohortes(mapas):
        acumulado = {}
        for año in cohortes:
            for p in mapas.get(año, {}).get(clave, []):
                acumulado[p.id] = p
        if len(acumulado) == 1:
            return next(iter(acumulado.values())), None
        return (None, "ambiguo") if acumulado else (None, None)

    fuera = "fuera_de_categoria" if cohortes else None

    for mapas, mapa, marca in ((indice.cohorte, indice.club, fuera),
                               (indice.cohorte_sec, indice.club_sec, fuera)):
        p, motivo = por_cohortes(mapas)
        if p is not None:
            return p, None
        if motivo == "ambiguo":
            return None, "ambiguo"
        p, motivo = unico(mapa)
        if p is not None:
            return p, marca
        if motivo == "ambiguo":
            return None, "ambiguo"

    # Último recurso: un typo de un carácter, primero dentro de las cohortes.
    for año in cohortes:
        p = _por_typo(clave, indice.cohorte.get(año, {}))
        if p is not None:
            return p, None
    p = _por_typo(clave, indice.club)
    if p is not None:
        return p, fuera
    return None, "no_encontrado"


def parsear(grid: list[list[Any]], *, rol: str) -> tuple[list[dict], list[str]]:
    """(filas, columnas_sin_mapear). Each row is `{"_ts", "_jugador", …}`."""
    from integrations.google_sheets import serial_to_datetime

    if not grid or len(grid) < 2:
        return [], []
    mapa = COL_CHECKIN if rol == "checkin" else COL_CHECKOUT
    numericos = NUM_CHECKIN if rol == "checkin" else NUM_CHECKOUT
    claves_min = CLAVES_CHECKIN if rol == "checkin" else CLAVES_CHECKOUT

    columnas: list[tuple[int, str]] = []
    sin_mapear: list[str] = []
    for i, cabecera in enumerate(grid[0]):
        crudo = _texto(cabecera)
        clave = norm(crudo)
        if not clave:
            continue                       # columna sin encabezado: ignorada
        if clave in mapa:
            destino = mapa[clave]
            if destino:
                columnas.append((i, destino))
        else:
            sin_mapear.append(crudo)

    filas = []
    for fila in grid[1:]:
        datos: dict[str, Any] = {}
        for i, destino in columnas:
            if i >= len(fila):
                continue
            bruto = fila[i]
            if destino == "_ts":
                datos["_ts"] = serial_to_datetime(bruto)
            elif destino == "_jugador":
                datos["_jugador"] = _texto(bruto)
            elif destino in numericos:
                v = _num(bruto)
                if v is not None:
                    datos[destino] = v
            else:
                v = _texto(bruto)
                if v and not (destino in CAMPOS_MOLESTIA and es_vacio(v)):
                    datos[destino] = v
        if not (claves_min & datos.keys()):
            continue                       # fila de arrastre, sin respuesta
        filas.append(datos)
    return filas, sin_mapear


def espera_reintento(exc, intento: int) -> float:
    """Segundos a esperar antes del próximo intento.

    Un 429 de Sheets no es un fallo transitorio de red: es la cuota de 60
    lecturas por minuto por usuario, y su ventana es de un minuto. Reintentar a
    los 3 y 6 segundos vuelve a chocar contra la misma pared — medido en prod,
    dos de los ocho documentos fallaron así cuando el sync corrió pegado a otra
    lectura. Ante cuota se espera de a medio minuto; ante cualquier otra cosa
    alcanza con unos segundos.
    """
    texto = str(exc)
    if "429" in texto or "Quota exceeded" in texto:
        return 30.0 * (intento + 1)
    return 3.0 * (intento + 1)


def _disparar_alertas(results: list) -> int:
    """`bulk_create` fires no signals, so the alert evaluation is explicit.

    Bounded by the same staleness cutoff the GPS ingest uses. These documents
    hold two and a half seasons of history, and an alert anchored on a 2024
    reading is expired again by the next sweep — firing them would only churn
    the list without telling anyone anything.
    """
    from goals.evaluator import (ALERT_STALE_DAYS,
                                 evaluate_threshold_rules_for_result)

    corte = timezone.now() - timedelta(days=ALERT_STALE_DAYS)
    n = 0
    for r in results:
        if r.recorded_at and r.recorded_at >= corte:
            n += len(evaluate_threshold_rules_for_result(r) or [])
    return n


def ingerir(doc, *, titulo: str, club, rol: str, commit: bool,
            desde: datetime | None = None, alertas: bool = False) -> Reporte:
    """Read one tab of one document and create the missing results.

    Idempotent on `(player, recorded_at)` truncated to the second — the same
    key `wellness_ingest` uses for Primer Equipo, so a row means the same thing
    whichever ingest produced it.
    """
    from exams.models import ExamResult, ExamTemplate

    slug = CHECKIN_SLUG if rol == "checkin" else CHECKOUT_SLUG
    hoja = HOJA_CHECKIN if rol == "checkin" else HOJA_CHECKOUT
    rep = Reporte(documento=titulo, hoja=hoja)

    real = next((h for h in doc.worksheets() if norm(h) == norm(hoja)), None)
    if real is None:
        return rep
    filas, sin_mapear = parsear(doc.values(real), rol=rol)
    rep.columnas_sin_mapear = sin_mapear
    rep.filas = len(filas)
    if not filas:
        return rep

    template = ExamTemplate.objects.filter(
        slug=slug, department__club=club).first()
    if template is None:
        raise ValueError(f"No existe la plantilla {slug!r} en {club.name!r}.")

    cohortes = cohortes_del_titulo(titulo)
    indice = indice_jugadores(club)

    # Existentes, para no reinsertar. Se acota por fecha cuando hay `desde`.
    qs = ExamResult.objects.filter(template=template)
    if desde is not None:
        qs = qs.filter(recorded_at__gte=desde)
    existentes = {(pid, rec.replace(microsecond=0))
                  for pid, rec in qs.values_list("player_id", "recorded_at")}

    nuevos = []
    for datos in filas:
        ts = datos.pop("_ts", None)
        bruto = datos.pop("_jugador", "")
        if ts is None:
            rep.sin_fecha += 1
            continue
        if desde is not None and ts < desde.replace(tzinfo=None):
            continue
        if not datos:
            rep.vacias += 1
            continue

        player, motivo = resolver_jugador(bruto, indice, cohortes)
        if player is None:
            if motivo == "no_encontrado":
                rep.no_encontrados[bruto] = rep.no_encontrados.get(bruto, 0) + 1
            elif motivo == "ambiguo":
                rep.ambiguos[bruto] = rep.ambiguos.get(bruto, 0) + 1
            else:
                rep.sin_jugador += 1
            continue
        if motivo == "fuera_de_categoria":
            rep.fuera_de_categoria += 1

        rec = timezone.make_aware(ts.replace(microsecond=0))
        if (player.id, rec) in existentes:
            rep.repetidos += 1
            continue
        existentes.add((player.id, rec))
        datos["origen"] = "google_sheets_formativo"
        datos["origen_hoja"] = f"{titulo} · {hoja}"
        nuevos.append(ExamResult(player=player, template=template,
                                 recorded_at=rec, result_data=datos))

    rep.creados = len(nuevos)
    if commit and nuevos:
        ExamResult.objects.bulk_create(nuevos, batch_size=1000)
        if alertas:
            rep.alertas = _disparar_alertas(nuevos)
    return rep


def ventana(dias: int | None) -> datetime | None:
    """`desde` for an incremental run, or None for the full history."""
    if not dias:
        return None
    return timezone.now() - timedelta(days=dias)
