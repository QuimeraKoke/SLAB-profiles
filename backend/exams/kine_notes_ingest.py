"""The formativo physios' log (Google Sheet, tab "f") → Kinesiología's "Notas diarias".

One row per intervention: Jugador, Rut, Fecha, Tratante, Categoria, Tipo de
intervencion, Observaciones. Each becomes one note of the department's
`notas_diarias_kinesiologico` template: fecha, tratante and
`tipo_intervencion` (both selectors), the observations as the note, and their
opening words as its subject — the department list shows the subject, never
the body, and the type already has its own column.

The sheet is the source of truth (it is live — the staff keep logging there),
so a sync MIRRORS it: new rows become notes, a row the club edits replaces its
note, a row the club deletes takes its note with it. Only notes this module
created are touched (`result_data["origen"] == ORIGEN`); a note typed in SLAB
is never deleted. A row's identity is its content, hashed: editing any cell is
"this row changed", which is what the club means by it.

Player matching, in order:
* by RUT (dots, dash and case ignored);
* by name (`formativo_gps_ingest.build_matcher`), and then ONLY if the player
  has a birth date and is within three years of the sheet's "Sub N" — a name
  alone matched a Sub 13 kid to a SUB-20 player with no birth date. The name
  fallback also rescues RUTs the sheet has wrong (a different check digit, or
  someone else's number entirely).
Rows that match no one are skipped and reported, never invented: "Prueba"
(trial players), the youngest categories not loaded in SLAB.

Dates are the club's to fix: a year before 2020 (the sheet has "0202-10-20")
is skipped and reported with its row number; a 2025 date among the 2026 ones
is imported as written and also reported. Once the club corrects the cell the
next sync picks it up — a corrected row is a changed row.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Club, Player
from exams.formativo_gps_ingest import build_matcher, norm
from exams.models import ExamResult, ExamTemplate

ORIGEN = "planilla_kine_formativo"
HOJA = "f"
SLUG = "notas_diarias_kinesiologico"
# Below this a date is a typo, not a session (the sheet starts in 2026).
ANIO_MINIMO = 2020
# Where the log really starts: the first month with at least this many rows.
# A date before it (11 rows dated 2025-01-30 among January 2026) is suspicious.
FILAS_MES_INICIO = 20
# Never delete more than this share of the existing notes in one run: a sheet
# read that comes back half empty (a tab renamed, a filter left on) must not
# wipe the history.
MAX_BORRADO = 0.5

# The two selectors. Values are the labels themselves — the department card
# and the history show the stored value as-is. New values in the sheet (a new
# physio) are ADDED as options by the sync; nothing is ever removed.
CAMPO_TRATANTE = {"key": "tratante", "label": "Tratante", "type": "categorical",
                  "group": "Encabezado"}
CAMPO_TIPO = {"key": "tipo_intervencion", "label": "Tipo de intervención",
              "type": "categorical", "group": "Encabezado"}
TRATANTES = ["M. Vera", "L. Caputto", "S. Valenzuela", "M. Reyes", "D. Nuñez", "M. Quiñones"]
TIPOS = ["Tratamiento", "Readaptación", "Kine complementaria", "Evaluación", "Podología",
         "Pauta preventiva", "Curación", "Masoterapia", "Recovery"]

# The sheet writes some types without the accent ("Podologia", "Curacion"):
# one option per type, the accented one.
_TIPO_CANON = {norm(t): t for t in TIPOS}


@dataclass
class Fila:
    n: int                 # row number as the club sees it (1-based, header incl.)
    nombre: str
    rut: str
    fecha: date | None
    fecha_cruda: Any
    tratante: str
    categoria: str
    tipo: str
    obs: str

    def identidad(self) -> str:
        partes = [norm(self.nombre), _rut(self.rut), self.fecha.isoformat() if self.fecha else "",
                  norm(self.tratante), norm(self.tipo), self.obs.strip()]
        return hashlib.sha1("|".join(partes).encode()).hexdigest()[:20]


@dataclass
class Reporte:
    filas: int = 0
    creadas: int = 0
    actualizadas: int = 0
    borradas: int = 0
    sin_cambio: int = 0
    borrado_bloqueado: bool = False
    sin_jugador: list[Fila] = dc_field(default_factory=list)
    fecha_invalida: list[Fila] = dc_field(default_factory=list)
    fecha_dudosa: list[Fila] = dc_field(default_factory=list)
    opciones_nuevas: dict = dc_field(default_factory=dict)
    categorias_nuevas: list[str] = dc_field(default_factory=list)
    via: Counter = dc_field(default_factory=Counter)


def _rut(s: str) -> str:
    return re.sub(r"[^0-9K]", "", (s or "").upper())


def _fecha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date(1899, 12, 30) + timedelta(days=int(float(v)))
    except (TypeError, ValueError, OverflowError):
        pass
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _edad_de_categoria(cat: str) -> int | None:
    m = re.search(r"(\d{1,2})", cat or "")
    return int(m.group(1)) if m else None


def leer(origen: str, *, creds_file: str = "", creds_json: str = "") -> list[Fila]:
    from exams.formativo_sources import abrir

    fuente = abrir(origen, creds_file=creds_file, creds_json=creds_json)
    try:
        grid = fuente.filas(HOJA)
    finally:
        fuente.cerrar()
    return parsear(grid)


def parsear(grid: list) -> list[Fila]:
    # The header is the first row that names "Jugador" (the sheet has an
    # empty row above it).
    i_cab = next((i for i, r in enumerate(grid)
                  if any(norm(str(c or "")) == "JUGADOR" for c in r)), None)
    if i_cab is None:
        raise ValueError(f"La hoja «{HOJA}» no tiene la columna Jugador.")
    cab = [norm(str(c or "")) for c in grid[i_cab]]
    ix = {c: i for i, c in enumerate(cab) if c}
    falta = {"JUGADOR", "FECHA", "TRATANTE", "TIPO DE INTERVENCION", "OBSERVACIONES"} - ix.keys()
    if falta:
        raise ValueError(f"Faltan columnas en «{HOJA}»: {', '.join(sorted(falta))}.")
    filas = []
    for k, r in enumerate(grid[i_cab + 1:], start=i_cab + 2):
        get = lambda col: (r[ix[col]] if col in ix and ix[col] < len(r) else None)
        nombre = str(get("JUGADOR") or "").strip()
        if not nombre:
            continue
        cruda = get("FECHA")
        rut = str(get("RUT") or "").strip()
        filas.append(Fila(
            n=k, nombre=nombre, rut="" if rut.startswith("#") else rut,
            fecha=_fecha(cruda), fecha_cruda=cruda,
            tratante=str(get("TRATANTE") or "").strip(),
            categoria=str(get("CATEGORIA") or "").strip(),
            tipo=_TIPO_CANON.get(norm(str(get("TIPO DE INTERVENCION") or "")),
                                 str(get("TIPO DE INTERVENCION") or "").strip()),
            obs=str(get("OBSERVACIONES") or "").strip(),
        ))
    return filas


def _matcher(club: Club):
    por_rut = {_rut(p.national_id): p
               for p in Player.objects.filter(category__club=club).exclude(national_id="")
               if p.national_id}
    por_nombre = build_matcher(club)

    def match(f: Fila) -> tuple[Player | None, str]:
        if f.rut and (p := por_rut.get(_rut(f.rut))):
            return p, "rut"
        p = por_nombre(f.nombre, None)
        if p is None or p.date_of_birth is None:
            return None, ""
        edad_cat = _edad_de_categoria(f.categoria)
        if f.fecha and edad_cat is not None:
            edad = (f.fecha - p.date_of_birth).days / 365.25
            if abs(edad - edad_cat) > 3:
                return None, ""
        return p, "nombre"
    return match


def asegurar_campos(template: ExamTemplate, filas: list[Fila]) -> dict[str, list[str]]:
    """Make sure the two selectors exist, with every value the sheet uses.
    Returns {field key: options added}. Mutates `template.config_schema`; the
    caller saves."""
    from exams.management.commands.seed_daily_notes import con_campos_kine

    antes = {f["key"]: list(f.get("options") or [])
             for f in (template.config_schema or {}).get("fields", [])}
    usados = {"tratante": [f.tratante for f in filas], "tipo_intervencion": [f.tipo for f in filas]}
    template.config_schema = con_campos_kine(template.config_schema, extra=usados)
    despues = {f["key"]: f.get("options") or [] for f in template.config_schema["fields"]}
    return {k: [o for o in despues[k] if o not in antes.get(k, [])]
            for k in ("tratante", "tipo_intervencion")
            if [o for o in despues[k] if o not in antes.get(k, [])]}


def run(origen: str | list, club: Club, *, commit: bool = False,
        creds_file: str = "", creds_json: str = "") -> Reporte:
    """`origen`: a sheet id, or an already-read grid (tests)."""
    filas = (parsear(origen) if isinstance(origen, list)
             else leer(origen, creds_file=creds_file, creds_json=creds_json))
    rep = Reporte(filas=len(filas))
    template = (ExamTemplate.objects.filter(department__club=club, slug=SLUG,
                                            is_active_version=True).first()
                or ExamTemplate.objects.filter(department__club=club, slug=SLUG).first())
    if template is None:
        raise ValueError(f"El club no tiene la plantilla {SLUG} (seed_daily_notes).")

    match = _matcher(club)
    por_mes = Counter(f.fecha.replace(day=1) for f in filas
                      if f.fecha and f.fecha.year >= ANIO_MINIMO)
    inicio = min((m for m, n in por_mes.items() if n >= FILAS_MES_INICIO), default=None)
    manana = timezone.localdate() + timedelta(days=1)
    deseadas: dict[str, tuple[Fila, Player]] = {}
    repetidas: Counter = Counter()
    for f in filas:
        if f.fecha is None or f.fecha.year < ANIO_MINIMO:
            rep.fecha_invalida.append(f)
            continue
        p, via = match(f)
        if p is None:
            rep.sin_jugador.append(f)
            continue
        if (inicio and f.fecha < inicio) or f.fecha > manana:
            rep.fecha_dudosa.append(f)
        rep.via[via] += 1
        base = f.identidad()
        repetidas[base] += 1
        # Two identical rows are two interventions the club logged twice;
        # keep both, each with its own identity.
        ident = base if repetidas[base] == 1 else f"{base}#{repetidas[base]}"
        deseadas[ident] = (f, p)

    filas_db = {r.result_data.get("origen_id"): r for r in
                ExamResult.objects.filter(template__family_id=template.family_id,
                                          result_data__origen=ORIGEN).only("pk", "result_data")}
    existentes = {k: r.pk for k, r in filas_db.items()}
    nuevas = [k for k in deseadas if k not in existentes]
    sobran = [pk for k, pk in existentes.items() if k not in deseadas]
    # Same row, but how a note is built changed (its subject, say): bring the
    # stored note in line. The row's identity is the sheet's content, so this
    # is never a different intervention.
    a_actualizar = []
    for k, r in filas_db.items():
        if k in deseadas:
            f, _ = deseadas[k]
            nuevo = _datos(f, k)
            if any(r.result_data.get(c) != v for c, v in nuevo.items()):
                r.result_data = {**r.result_data, **nuevo}
                a_actualizar.append(r)
    rep.actualizadas = len(a_actualizar)
    rep.sin_cambio = len(deseadas) - len(nuevas) - len(a_actualizar)
    if existentes and len(sobran) > MAX_BORRADO * len(existentes):
        rep.borrado_bloqueado = True
        sobran = []
    rep.borradas = len(sobran)
    rep.creadas = len(nuevas)

    rep.opciones_nuevas = asegurar_campos(template, [f for f, _ in deseadas.values()])
    if not commit:
        return rep
    a_crear = set(nuevas)
    with transaction.atomic():
        if rep.opciones_nuevas:
            template.save(update_fields=["config_schema", "updated_at"])
            template.rebuild_template_fields()
        rep.categorias_nuevas = _asegurar_pestana(
            template, {p.category for _, p in deseadas.values()})
        ExamResult.objects.filter(pk__in=sobran).delete()
        ExamResult.objects.bulk_update(a_actualizar, ["result_data"], batch_size=500)
        ExamResult.objects.bulk_create([
            ExamResult(
                player=p, template=template,
                recorded_at=timezone.make_aware(datetime.combine(f.fecha, datetime.min.time()))
                + timedelta(hours=12),
                result_data=_datos(f, k),
            )
            for k, (f, p) in deseadas.items() if k in a_crear
        ], batch_size=500)
    return rep


ASUNTO_MAX = 80


def _datos(f: Fila, ident: str) -> dict:
    return {
        "fecha": f.fecha.isoformat(),
        "asunto": _asunto(f),
        "nota": f.obs or "—",
        "tratante": f.tratante or None,
        "tipo_intervencion": f.tipo or None,
        "origen": ORIGEN, "origen_id": ident, "origen_fila": f.n,
        "categoria_planilla": f.categoria,
    }


def _asunto(f: Fila) -> str:
    """The note's opening words: the department list shows the subject, never
    the note body, and the type already has its own column."""
    texto = " ".join(f.obs.split())
    if not texto:
        return f.tipo or "Kinesiología"
    if len(texto) <= ASUNTO_MAX:
        return texto
    corte = texto.rfind(" ", 0, ASUNTO_MAX)
    return texto[:corte if corte > 40 else ASUNTO_MAX].rstrip(" ,.;:") + "…"


def _asegurar_pestana(template: ExamTemplate, categorias) -> list[str]:
    """The Kinesiología tab, where the notes are. A department shows on a
    player's profile only if his category has it, and the template is listed
    only where it applies — Kinesiológico had neither anywhere, so 2.300 notes
    lived only in the timeline. Add-only, and youth categories only: the sheet
    is the formativo's; a player since promoted keeps his notes in the
    timeline and history."""
    nuevas = []
    for cat in categorias:
        if cat is None or cat.is_senior:
            continue
        if not cat.departments.filter(pk=template.department_id).exists():
            cat.departments.add(template.department)
            nuevas.append(cat.name)
        template.applicable_categories.add(cat)
    return sorted(nuevas)


def escribir_reporte(rep: Reporte, ruta: str) -> None:
    """The club's to-do list, as an Excel: who to create, which dates to fix."""
    import openpyxl

    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Jugadores no encontrados"
    hoja.append(["Jugador", "Rut", "Categoría", "Filas", "Números de fila"])
    por_jugador: dict = defaultdict(list)
    for f in rep.sin_jugador:
        por_jugador[(f.nombre, f.rut, f.categoria)].append(f.n)
    for (nombre, rut, cat), ns in sorted(por_jugador.items(), key=lambda x: -len(x[1])):
        hoja.append([nombre, rut or "—", cat or "—", len(ns), ", ".join(map(str, ns))])
    for titulo, lista, nota in (
        ("Fechas inválidas", rep.fecha_invalida, "No se importó: el año es imposible o falta la fecha."),
        ("Fechas para revisar", rep.fecha_dudosa,
         "Se importó, pero la fecha es anterior al inicio de la planilla o futura."),
    ):
        h = libro.create_sheet(titulo)
        h.append([nota])
        h.append(["Fila", "Fecha en la planilla", "Jugador", "Tratante", "Tipo", "Observaciones"])
        for f in lista:
            h.append([f.n, f.fecha.isoformat() if f.fecha else str(f.fecha_cruda or "(vacía)"),
                      f.nombre, f.tratante, f.tipo, f.obs[:120]])
    for h in libro.worksheets:
        for col in h.columns:
            h.column_dimensions[col[0].column_letter].width = min(
                60, max(10, max(len(str(c.value or "")) for c in col) + 2))
    libro.save(ruta)
