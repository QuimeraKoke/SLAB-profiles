"""Seed the club's per-category alert bands from the `FORMATO CONDICIONAL` sheets.

Phase 5 of PLAN_FORMATIVO.md — the half that was missing. The *mechanism* has
been in place since the evaluator learned to read `AlertRule.config["ranges"]`,
but no rule used it: the club's real thresholds only existed in two sheets of
`EVALUACIONES FÍSICAS CATEGORÍAS.xlsx`, so every band rule fell back to the
field's shared `reference_ranges` and a Sub 11 was judged with a Sub 20's
numbers.

    cp "EVALUACIONES FÍSICAS CATEGORÍAS.xlsx" backend/_formativo_eval.xlsx
    docker compose exec backend python manage.py seed_formativo_bands \\
        --file /app/_formativo_eval.xlsx --club "Universidad de Chile"
    # ... read the report, then add --commit

How the sheets are laid out
---------------------------
Each sheet holds two category groups, and each group is a grid of blocks three
columns wide — band label, threshold, and a human range text — repeated at
C/D/E, G/H/I and K/L/M. Every block is a test: seven bands from
"Muy Deficiente" to "Elite", with the test's name in the row above.

The group label sits in column A *inside the first block of its group*
(`A7 = "18-20"`, `A41 = "15-16"`), which is why a group cannot be delimited by
the merged range of that cell — `A7–A23` stops before the Resistencia block at
rows 27–34 that belongs to it. Blocks are found by their seven band labels, and
each is assigned to the last group whose own first block starts at or before it.

⚠️ The direction is inferred from the NUMBERS, not from the range text
------------------------------------------------------------------------
The range text is decorative and sometimes wrong. In the `18-20` group T10
reads `<1,8` for "Muy Deficiente", and in `15-16` the same test reads `>1,8` —
one of the two is written backwards, and taking either at face value would
invert a whole scale: the fastest players would be flagged as the worst.

The thresholds themselves are consistent (T10 runs 1,8 → 1,53, descending;
RM Back Squat runs 125 → 219, ascending), and they agree with the physics:
a time gets better as it drops, a load as it rises. So the direction comes from
whether the sequence rises or falls, and the club's typo is corrected on the
way in. Discrepancies are reported.

What it writes
--------------
One `AlertRule` per (category, field), of kind BAND, with:

* `config["ranges"]` — the club's seven bands, as real min/max numbers.
* `config["trigger_labels"] = ["Muy Deficiente"]` — a starting point. The
  evaluator lets `trigger_labels` win over the reddest-band heuristic, and this
  is already editable from `/configuraciones/alertas`, so the staff decide which
  bands raise an alert without touching the numbers.

Additive: an existing rule for the same (category, template, field) is left
alone unless `--overwrite`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Bracket, Category, Club
from exams.models import ExamTemplate
from goals.models import AlertRule, AlertRuleKind, AlertSeverity

SHEETS = ("FORMATO CONDICIONAL 15-16 y 18-", "FORMATO CONDICIONAL 13 -14 y 11")

# The seven bands, worst to best, exactly as the club writes them.
BANDAS = ("Muy Deficiente", "Deficiente", "Regular", "Bueno", "muy bueno",
          "Excelente", "Elite")
# Red → teal ramp. Seven steps, so the middle is amber rather than green.
COLORES = ("#dc2626", "#f97316", "#f59e0b", "#84cc16", "#16a34a", "#059669",
           "#0d9488")

# Group label in column A → the bracket ages it covers.
GRUPOS = {
    "18 20": (18, 20),
    "15 16": (15, 16),
    "SUB 13 SUB 14": (13, 14),
    "SUB 11 SUB 12": (11, 12),
}

# (test name, unit) → (template slug, field key). The unit disambiguates
# `RM BACK SQUAT` (kg) from `BACK SQUAT` (RM/kg) and the two YOYO columns,
# which otherwise collide.
TESTS = {
    ("RM BACK SQUAT", "KG"): ("fuerza", "rm_estimado"),
    ("BACK SQUAT", "RM KG"): ("fuerza", "fr"),
    ("TIRO", "KM HR"): ("neuromuscular", "tiro_best"),
    ("CMJ T V", "CM"): ("neuromuscular", "cmj_best"),
    ("T10", "TIEMPO SEG"): ("carreras", "t10_best"),
    ("T30", "TIEMPO SEG"): ("carreras", "t30_best"),
    ("COD 505 DER", "TIEMPO SEG"): ("carreras", "cod_der_best"),
    ("COD 505 IZQ", "TIEMPO SEG"): ("carreras", "cod_izq_best"),
    ("YOYO IR1", "PALIER"): ("resistencia", "palier"),
    ("YOYO IR1", "VO2"): ("resistencia", "vo2_max"),
}


def norm(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text).split())


def _num(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None      # ">219" and the like: a boundary already covered by b6


@dataclass
class Bloque:
    hoja: str
    fila: int
    grupo: str
    test: str
    unidad: str
    umbrales: list[float]
    texto_primero: str = ""


@dataclass
class Reporte:
    creadas: int = 0
    actualizadas: int = 0
    ya_existian: int = 0
    bloques: int = 0
    sin_mapeo: list[str] = dc_field(default_factory=list)
    sin_categoria: list[str] = dc_field(default_factory=list)
    texto_invertido: list[str] = dc_field(default_factory=list)
    incompletos: list[str] = dc_field(default_factory=list)
    no_aplicable: list[str] = dc_field(default_factory=list)


def parse_sheets(path: str) -> tuple[list[Bloque], list[str]]:
    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True)
    bloques: list[Bloque] = []
    faltantes = [h for h in SHEETS if h not in book.sheetnames]
    for hoja in SHEETS:
        if hoja in book.sheetnames:
            bloques.extend(_parse_sheet(book[hoja], hoja))
    book.close()
    return bloques, faltantes


def _parse_sheet(ws, hoja: str) -> list[Bloque]:
    filas = {}
    for r in range(1, ws.max_row + 1):
        filas[r] = [ws.cell(row=r, column=c).value
                    for c in range(1, ws.max_column + 1)]

    # A block is seven consecutive rows whose label column reads the seven
    # band names in order. Anchoring on the sequence rather than on a header
    # keeps it working when the club adds or moves a section.
    crudos = []
    for base in (3, 7, 11):        # C/D/E, G/H/I, K/L/M as 0-indexed columns
        for r in range(2, ws.max_row - len(BANDAS) + 2):
            etiquetas = [norm(filas.get(r + i, [None])[base - 1]
                              if base - 1 < len(filas.get(r + i, [])) else None)
                         for i in range(len(BANDAS))]
            if etiquetas != [norm(b) for b in BANDAS]:
                continue
            cab = filas.get(r - 1, [])
            get = lambda fila, col: (fila[col] if col < len(fila) else None)
            test = norm(get(cab, base - 1))
            unidad = norm(get(cab, base))
            umbrales = [_num(get(filas.get(r + i, []), base))
                        for i in range(len(BANDAS))]
            crudos.append((r, test, unidad,
                           [u for u in umbrales if u is not None],
                           str(get(filas.get(r, []), base + 1) or "")))

    # The group label lives inside the first block of its group, so each group
    # starts at that block's first band row.
    etiquetados = [r for r in range(1, ws.max_row + 1)
                   if norm(filas.get(r, [None])[0] if filas.get(r) else None)]
    inicios = []
    for L in etiquetados:
        contenedor = next((r for r, *_ in crudos if r - 1 <= L <= r + len(BANDAS) - 1),
                          None)
        if contenedor is not None:
            inicios.append((contenedor, norm(filas[L][0])))
    inicios.sort()

    def grupo_de(r: int) -> str:
        elegido = ""
        for inicio, nombre in inicios:
            if inicio <= r:
                elegido = nombre
        return elegido

    return [Bloque(hoja=hoja, fila=r, grupo=grupo_de(r), test=test,
                   unidad=unidad, umbrales=umbrales, texto_primero=texto)
            for r, test, unidad, umbrales, texto in sorted(crudos)]


def build_ranges(umbrales: list[float]) -> tuple[list[dict], bool]:
    """Seven bands out of six boundaries, oriented by the sequence itself.

    Returns `(ranges, mas_es_mejor)`. Ascending thresholds mean a higher value
    is better (a load), descending means lower is better (a time).
    """
    cortes = umbrales[:len(BANDAS) - 1]
    mas_es_mejor = cortes[-1] > cortes[0]
    ordenados = sorted(cortes) if mas_es_mejor else sorted(cortes, reverse=True)

    ranges: list[dict] = []
    for i, (label, color) in enumerate(zip(BANDAS, COLORES)):
        banda: dict = {"label": label, "color": color}
        if mas_es_mejor:
            if i > 0:
                banda["min"] = ordenados[i - 1]
            if i < len(ordenados):
                banda["max"] = ordenados[i]
        else:
            if i > 0:
                banda["max"] = ordenados[i - 1]
            if i < len(ordenados):
                banda["min"] = ordenados[i]
        ranges.append(banda)
    return ranges, mas_es_mejor


class Command(BaseCommand):
    help = "Siembra las bandas por categoría desde las hojas FORMATO CONDICIONAL."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True,
                            help="Ruta al .xlsx dentro del contenedor.")
        parser.add_argument("--club", default="Universidad de Chile")
        parser.add_argument("--season", type=int, default=None)
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--overwrite", action="store_true",
                            help="Reemplaza los umbrales de una regla existente.")

    def handle(self, *args, **opts):
        from datetime import date

        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        if not Path(opts["file"]).exists():
            raise CommandError(f"No existe {opts['file']}.")
        season = opts["season"] or date.today().year

        bloques, faltantes = parse_sheets(opts["file"])
        if faltantes:
            raise CommandError(
                f"El archivo no trae {faltantes}. ¿Es el libro de evaluaciones?")
        if not bloques:
            raise CommandError("No se reconoció ningún bloque de bandas.")

        rep = Reporte(bloques=len(bloques))
        with transaction.atomic():
            self._sembrar(club, season, bloques, opts, rep)
            if not opts["commit"]:
                transaction.set_rollback(True)
        self._imprimir(rep, opts)

    def _categorias(self, club, season, ages, ladder):
        """Categorías cuyo bracket de la temporada cae en `ages`."""
        youngest = min((b.age for b in ladder if b.age is not None), default=None)
        elegidas = []
        for cat in Category.objects.filter(club=club).prefetch_related(
                "team_seasons__bracket"):
            if cat.is_senior:
                continue
            if cat.cohort_year is None:
                # El plantel único del club (SUB-20): su bracket sale de la
                # TeamSeason, no de una cohorte que no tiene.
                ts = next((t for t in cat.team_seasons.all()
                           if t.season == season and t.bracket), None)
                if ts and ts.bracket.age in ages:
                    elegidas.append(cat)
                continue
            edad = season - cat.cohort_year
            if youngest is not None and edad < youngest:
                continue          # el techo de for_age mandaría un Sub 8 a Sub 11
            bracket = Bracket.for_age(edad, ladder)
            if bracket and not bracket.is_senior and bracket.age in ages:
                elegidas.append(cat)
        return elegidas

    def _sembrar(self, club, season, bloques, opts, rep):
        ladder = Bracket.ladder()
        plantillas = {
            t.slug: t for t in ExamTemplate.objects.filter(department__club=club)
            if t.slug in {s for s, _ in TESTS.values()}
        }
        for b in bloques:
            destino = TESTS.get((b.test, b.unidad))
            if destino is None:
                rep.sin_mapeo.append(
                    f"{b.hoja} f{b.fila}: {b.test!r} / {b.unidad!r}")
                continue
            if len(b.umbrales) < len(BANDAS) - 1:
                rep.incompletos.append(
                    f"{b.hoja} f{b.fila} {b.test}: {len(b.umbrales)} umbrales")
                continue
            ages = GRUPOS.get(b.grupo)
            if ages is None:
                rep.sin_categoria.append(f"{b.hoja} f{b.fila}: grupo {b.grupo!r}")
                continue
            slug, field_key = destino
            template = plantillas.get(slug)
            if template is None:
                rep.sin_mapeo.append(f"{b.hoja} f{b.fila}: falta la plantilla {slug}")
                continue

            ranges, mas_es_mejor = build_ranges(b.umbrales)
            # El texto del rango del club, cuando contradice a los números.
            texto = b.texto_primero.strip()
            if texto.startswith("<") and not mas_es_mejor:
                rep.texto_invertido.append(
                    f"{b.hoja} f{b.fila} {b.test} ({b.grupo}): dice {texto!r} "
                    f"pero los umbrales bajan → se usó 'peor es mayor'")
            elif texto.startswith(">") and mas_es_mejor:
                rep.texto_invertido.append(
                    f"{b.hoja} f{b.fila} {b.test} ({b.grupo}): dice {texto!r} "
                    f"pero los umbrales suben → se usó 'peor es menor'")

            cats = self._categorias(club, season, ages, ladder)
            if not cats:
                rep.sin_categoria.append(
                    f"{b.hoja} f{b.fila}: ninguna categoría en Sub {ages} para {season}")
                continue
            for cat in cats:
                self._regla(template, field_key, cat, ranges, opts, rep)

    def _regla(self, template, field_key, category, ranges, opts, rep):
        # La regla se valida contra `applicable_categories`, y el club define
        # bandas para combinaciones que hoy no mide: hay un bloque de YOYO para
        # Sub 11–12 mientras `resistencia` arranca en Sub 13, que es donde
        # tienen filas. No se amplía la aplicabilidad por cuenta propia —
        # ampliarla es decidir que esa categoría corre el test— así que se
        # salta y se reporta como pregunta para el club.
        if not template.applicable_categories.filter(pk=category.pk).exists():
            rep.no_aplicable.append(
                f"{template.slug}.{field_key} → {category.name}")
            return
        regla = AlertRule.objects.filter(
            template=template, field_key=field_key, category=category,
            kind=AlertRuleKind.BAND).first()
        if regla is not None and not opts["overwrite"]:
            rep.ya_existian += 1
            return
        config = {"ranges": ranges, "trigger_labels": [BANDAS[0]]}
        if regla is None:
            regla = AlertRule(template=template, field_key=field_key,
                              category=category, kind=AlertRuleKind.BAND,
                              severity=AlertSeverity.WARNING, scope={})
            rep.creadas += 1
        else:
            # Conserva las bandas que el cuerpo técnico ya eligió como
            # disparadoras: se re-siembran los NÚMEROS, no la decisión.
            previos = (regla.config or {}).get("trigger_labels")
            if isinstance(previos, list) and previos:
                config["trigger_labels"] = previos
            rep.actualizadas += 1
        regla.config = config
        regla.full_clean(exclude=["template", "category"])
        regla.save()

    def _imprimir(self, rep, opts):
        modo = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{modo} · {rep.bloques} bloques de bandas leídos\n"))
        self.stdout.write(self.style.SUCCESS(f"  reglas creadas    : {rep.creadas}"))
        if rep.actualizadas:
            self.stdout.write(f"  reglas actualizadas: {rep.actualizadas}")
        self.stdout.write(f"  ya existían        : {rep.ya_existian}"
                          f"{'  (usar --overwrite)' if rep.ya_existian else ''}")
        for titulo, items, estilo in (
            ("Bloques sin mapeo a un campo", rep.sin_mapeo, self.style.ERROR),
            ("Bloques incompletos", rep.incompletos, self.style.ERROR),
            ("Sin categoría destino", rep.sin_categoria, self.style.WARNING),
            ("La plantilla no aplica a esa categoría (¿ampliar o descartar?)",
             rep.no_aplicable, self.style.WARNING),
            ("⚠️ Texto del rango contradice los umbrales",
             rep.texto_invertido, self.style.WARNING),
        ):
            if not items:
                continue
            self.stdout.write(estilo(f"\n  {titulo}: {len(items)}"))
            for item in items[:12]:
                self.stdout.write(f"    {item}")
            if len(items) > 12:
                self.stdout.write(f"    … y {len(items) - 12} más")
