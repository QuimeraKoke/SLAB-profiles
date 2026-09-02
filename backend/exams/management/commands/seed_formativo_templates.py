"""Create the five Formativo physical-testing templates, plus GPS heart rate.

Phase 4 of PLAN_FORMATIVO.md.

    docker compose exec backend python manage.py seed_formativo_templates \\
        --club "Universidad de Chile" --season 2026

Five templates, not one per category
------------------------------------
The club's smaller categories run a **nested subset** of the bigger ones, never
something different: no category measures a field the older ones lack. With two
nested variants per family, duplicating templates per category would mean ten
copies of the same exam to edit ten times over. Fields a category does not
measure stay optional and empty, and `applicable_categories` decides who is
offered the form at all.

The trigger to revisit that would be *divergence* rather than subsetting — one
category needing a field the others do not have. None of the five families does
that today.

Derived columns are computed, not imported
------------------------------------------
Each formula below was checked against the club's own numbers before being
encoded, because a formula that is nearly right is worse than an imported value:

* `METROS = PALIER × 40` — exact in all 862 rows of `RESISTENCIA`.
* `VO2 MAX = 0.336 × PALIER + 36.4` — exact in all 862.
* `%RM = ÚLTIMA CARGA ÷ 1RM × 100` — exact in all 729 rows of `FUERZA` and
  `PRESS DE BANCO`.
* `FR = 1RM ÷ PESO CORPORAL` — off in 2 of 682 rows, both single-cell typos.
* 1000 m `VAM = METROS ÷ TIEMPO(s)` — exact.

Two columns are deliberately **imported instead of computed**:

* **`vam` in the shuttle test.** It is a 91-row lookup table (the workbook's
  `VAM` sheet, palier → km/h), not an expression, and the formula engine has no
  lookup. Note that this means a stored `vam` is historical: if the club revises
  its table, old rows keep the old value.
* **`vo2_max` in the 1000 m test.** It is not a function of time alone — 240 s
  yields 48.3 and 251 s yields 51.1 — so it depends on something else (age,
  most likely). Guessing a formula here would silently rewrite the club's
  numbers.

⚠️ `applicable_categories` is season-dependent
----------------------------------------------
Who runs a test is expressed as a rung ("Sub 13 and up"), but the M2M stores
categories. A Serie 2015 that is Sub 11 today will be Sub 13 in 2028 and should
be offered Resistencia then. So this command resolves rungs to categories **for
the season given** and must be re-run at the start of each one. Re-running is
idempotent.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Bracket, Category, Club, Department

# ── shared field builders ───────────────────────────────────────────────
def _rep(key: str, label: str, unit: str, group: str, lo: float, hi: float) -> dict:
    return {"key": key, "label": label, "type": "number", "unit": unit,
            "group": group, "min": lo, "max": hi}


def _best(key: str, label: str, unit: str, group: str, reps: list[str],
          lowest_is_best: bool) -> dict:
    """`BEST` is min for a time and max for a height or a speed.

    It is derived from the attempts, so SLAB computes it rather than importing
    it — storing the club's value too would be the same conclusion twice, free
    to drift.

    ⚠️ The formula has to survive a MISSING attempt, which is the common case:
    2978 of 4341 rows in `CARRERAS` and 1012 of 1565 in `NEUROMUSCULAR` record
    only two. A plain `min([a], [b], [c])` returns None as soon as one is
    absent, so the import would have loaded 15.000 rows and left every chart
    and every alert empty without a single error.

    A missing key is not null in this engine — it raises `Unknown variable` —
    and `coalesce` is the only lazy function, so each argument coalesces to the
    first attempt that IS present. With `a` and `b` recorded, `min` receives
    `(a, b, a)`, which is `min(a, b)`. With none recorded, `coalesce` raises
    and the field is left empty, which is the right answer.
    """
    func = "min" if lowest_is_best else "max"
    args = []
    for i in range(len(reps)):
        rot = reps[i:] + reps[:i]
        args.append(f"coalesce({', '.join(f'[{r}]' for r in rot)})")
    return {"key": key, "label": label, "type": "calculated", "unit": unit,
            "group": group, "chart_type": "line",
            "direction_of_good": "down" if lowest_is_best else "up",
            "formula": f"{func}({', '.join(args)})"}


def _prom(key: str, label: str, unit: str, group: str, reps: list[str],
          lowest_is_best: bool) -> dict:
    """Imported, not computed — the engine cannot count present values.

    A mean needs sum ÷ how-many-were-recorded, and there is no way to count:
    `1 if [c] else 0` raises `Unknown variable` when `c` is absent, and
    `coalesce` can only substitute a value, not report that it had to. Summing
    coalesced attempts and dividing by three would silently divide a two-attempt
    mean by three.

    So this carries the club's own average, the same call already made for
    `vam` and the 1000 m `vo2_max`. Consequence worth knowing: on a
    hand-entered form `best` fills itself and this stays blank, because there
    is nothing to derive it from.
    """
    return {"key": key, "label": label, "type": "number", "unit": unit,
            "group": group, "chart_type": "line",
            "direction_of_good": "down" if lowest_is_best else "up"}


def _serie(key: str, label: str, unit: str, group: str, reps: list[str],
           lo: float, hi: float, lowest_is_best: bool) -> list[dict]:
    fields = [_rep(r, f"{label} — intento {i}", unit, group, lo, hi)
              for i, r in enumerate(reps, 1)]
    fields.append(_best(key + "_best", f"{label} — mejor", unit, group, reps,
                        lowest_is_best))
    fields.append(_prom(key + "_prom", f"{label} — promedio", unit, group, reps,
                        lowest_is_best))
    return fields


# ── 1. Carreras ─────────────────────────────────────────────────────────
G_VEL, G_COD = "Velocidad", "Cambio de dirección (COD 505)"
CARRERAS = {"fields": [
    *_serie("t10", "T10", "s", G_VEL, ["t10_1", "t10_2", "t10_3"], 1.0, 4.0, True),
    *_serie("t30", "T30", "s", G_VEL, ["t30_1", "t30_2", "t30_3"], 3.0, 9.0, True),
    *_serie("cod_der", "COD 505 derecha", "s", G_COD,
            ["cod_der_1", "cod_der_2", "cod_der_3"], 1.5, 5.0, True),
    *_serie("cod_izq", "COD 505 izquierda", "s", G_COD,
            ["cod_izq_1", "cod_izq_2", "cod_izq_3"], 1.5, 5.0, True),
    {
        "key": "cod_asimetria", "label": "Asimetría COD (der vs izq)",
        "type": "calculated", "unit": "%", "group": G_COD, "chart_type": "line",
        # Signed on purpose: positive means the RIGHT side is slower. An
        # absolute value hides which side to work on, and the sign convention
        # differing between templates is exactly what bit the médico ones.
        "direction_of_good": "down",
        "formula": ("round(([cod_der_best] - [cod_izq_best]) "
                    "/ [cod_izq_best] * 10000) / 100"),
        "reference_ranges": [
            {"max": -10, "label": "Asimetría izquierda", "color": "#dc2626", "alert": True},
            {"min": -10, "max": 10, "label": "Simétrico", "color": "#16a34a"},
            {"min": 10, "label": "Asimetría derecha", "color": "#dc2626", "alert": True},
        ],
    },
]}

# ── 2. Neuromuscular ────────────────────────────────────────────────────
G_SALTO, G_TIRO = "Salto", "Potencia de tiro"
NEUROMUSCULAR = {"fields": [
    *_serie("cmj", "CMJ", "cm", G_SALTO, ["cmj_1", "cmj_2", "cmj_3"], 5, 80, False),
    *_serie("tiro", "Tiro", "km/h", G_TIRO, ["tiro_1", "tiro_2", "tiro_3"],
            20, 140, False),
]}

# ── 3. Resistencia (Course Navette, por palier) ─────────────────────────
G_RES = "Test de palier"
RESISTENCIA = {"fields": [
    {"key": "palier", "label": "Palier alcanzado", "type": "number", "unit": "",
     "group": G_RES, "min": 1, "max": 91, "chart_type": "line",
     "direction_of_good": "up"},
    {"key": "metros", "label": "Metros recorridos", "type": "calculated",
     "unit": "m", "group": G_RES, "chart_type": "line",
     "direction_of_good": "up", "formula": "[palier] * 40"},
    {"key": "vo2_max", "label": "VO₂ máx estimado", "type": "calculated",
     "unit": "ml/kg/min", "group": G_RES, "chart_type": "line",
     "direction_of_good": "up",
     "formula": "round((0.336 * [palier] + 36.4) * 100) / 100"},
    {"key": "vam", "label": "VAM", "type": "number", "unit": "km/h",
     "group": G_RES, "min": 8, "max": 25, "chart_type": "line",
     "direction_of_good": "up"},
]}

# ── 4. Resistencia 1000 metros ──────────────────────────────────────────
G_MIL = "1000 metros"
RESISTENCIA_1000 = {"fields": [
    {"key": "tiempo_s", "label": "Tiempo", "type": "number", "unit": "s",
     "group": G_MIL, "min": 120, "max": 600, "chart_type": "line",
     "direction_of_good": "down"},
    {"key": "metros", "label": "Distancia", "type": "number", "unit": "m",
     "group": G_MIL, "min": 100, "max": 5000},
    {"key": "vam", "label": "Velocidad media", "type": "calculated",
     "unit": "m/s", "group": G_MIL, "chart_type": "line",
     "direction_of_good": "up",
     "formula": "round([metros] / [tiempo_s] * 1000) / 1000"},
    # Imported, not computed: not a function of time alone (see module docstring).
    {"key": "vo2_max", "label": "VO₂ máx estimado", "type": "number",
     "unit": "ml/kg/min", "group": G_MIL, "min": 20, "max": 90,
     "chart_type": "line", "direction_of_good": "up"},
]}

# ── 5. Fuerza (perfil carga-velocidad) ──────────────────────────────────
G_FZA, G_PERFIL = "Resumen", "Perfil carga-velocidad (mejor por carga)"
# The workbook runs 20→160 kg for the squat and 20→80 for the bench press. One
# template with every load optional beats two near-identical templates: the
# protocol is the same and only the lift changes, which is what `ejercicio` is.
CARGAS = list(range(20, 170, 10))
FUERZA = {"fields": [
    {"key": "ejercicio", "label": "Ejercicio", "type": "categorical",
     "group": G_FZA, "options": ["Sentadilla", "Press de banco"]},
    {"key": "peso_corporal", "label": "Peso corporal", "type": "number",
     "unit": "kg", "group": G_FZA, "min": 25, "max": 130},
    {"key": "ultima_carga_kg", "label": "Última carga", "type": "number",
     "unit": "kg", "group": G_FZA, "min": 10, "max": 220},
    {"key": "ultima_carga_ms", "label": "Velocidad en la última carga",
     "type": "number", "unit": "m/s", "group": G_FZA, "min": 0.1, "max": 2.5,
     "chart_type": "line", "direction_of_good": "up"},
    {"key": "rm_estimado", "label": "1RM estimado", "type": "number",
     "unit": "kg", "group": G_FZA, "min": 10, "max": 260,
     "chart_type": "line", "direction_of_good": "up"},
    {"key": "pct_rm", "label": "% del 1RM en la última carga",
     "type": "calculated", "unit": "%", "group": G_FZA,
     "formula": "round([ultima_carga_kg] / [rm_estimado] * 10000) / 100"},
    {"key": "fr", "label": "Fuerza relativa (1RM / peso corporal)",
     "type": "calculated", "unit": "", "group": G_FZA, "chart_type": "line",
     "direction_of_good": "up",
     "formula": "round([rm_estimado] / [peso_corporal] * 1000) / 1000"},
    *[{"key": f"v_{c}kg", "label": f"{c} kg", "type": "number", "unit": "m/s",
       "group": G_PERFIL, "min": 0.1, "max": 2.5} for c in CARGAS],
]}

# The two heart-rate columns the Formativo GPS export has and `gps_sesion` lacks.
# Adding them keeps the deliberate rule of exactly TWO GPS exams system-wide.
GPS_HR_FIELDS = [
    {"key": "avg_hr_pct", "label": "FC media (% de la máxima)", "type": "number",
     "unit": "%", "group": "Frecuencia cardíaca", "min": 30, "max": 100,
     "chart_type": "line"},
    {"key": "max_hr_bpm", "label": "FC máxima", "type": "number", "unit": "bpm",
     "group": "Frecuencia cardíaca", "min": 100, "max": 230,
     "chart_type": "line"},
]

INPUT_CONFIG = {
    "input_modes": ["team_table", "single", "bulk_ingest"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": []},
}

# slug, name, schema, lowest rung that runs the test (None = every category)
TEMPLATES = [
    ("carreras", "Carreras (velocidad y COD)", CARRERAS, None),
    ("neuromuscular", "Neuromuscular (CMJ y tiro)", NEUROMUSCULAR, None),
    ("resistencia", "Resistencia (test de palier)", RESISTENCIA, 13),
    ("resistencia_1000m", "Resistencia 1000 metros", RESISTENCIA_1000, 13),
    ("fuerza", "Fuerza (perfil carga-velocidad)", FUERZA, 13),
]


class Command(BaseCommand):
    help = "Create the five Formativo physical templates and the GPS HR fields."

    def add_arguments(self, parser):
        parser.add_argument("--club", required=True)
        parser.add_argument("--department-slug", default="fisico")
        parser.add_argument("--season", type=int, default=date.today().year)
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        from exams.models import ExamTemplate

        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        dept = Department.objects.filter(club=club, slug=opts["department_slug"]).first()
        if dept is None:
            disponibles = ", ".join(
                Department.objects.filter(club=club).values_list("slug", flat=True))
            raise CommandError(
                f"No existe el departamento '{opts['department_slug']}' en "
                f"{club.name}. Hay: {disponibles}")

        season, ladder = opts["season"], Bracket.ladder()
        for slug, name, schema, min_rung in TEMPLATES:
            template = ExamTemplate.objects.filter(department=dept, slug=slug).first()
            if template is None:
                template = ExamTemplate(department=dept, slug=slug, name=name,
                                        config_schema=schema,
                                        input_config=INPUT_CONFIG)
                accion = "creada"
            elif template.is_locked and not opts["unlock"]:
                self.stdout.write(self.style.WARNING(
                    f"  {name}: bloqueada, pasá --unlock"))
                continue
            else:
                template.name = name
                template.config_schema = schema
                template.input_config = INPUT_CONFIG
                if opts["unlock"]:
                    template.is_locked = False
                accion = "actualizada"
            template.save()
            template.rebuild_template_fields()

            cats = self._categories(club, dept, season, ladder, min_rung)
            template.applicable_categories.set(cats)
            corte = f"Sub {min_rung}+" if min_rung else "todas"
            self.stdout.write(self.style.SUCCESS(
                f"  {name}: {accion} · {len(schema['fields'])} campos · "
                f"{len(cats)} categorías ({corte})"))

        self._gps_heart_rate(dept, opts["unlock"])
        self._gps_applicability(club, dept, season, ladder)

    def _formativo(self, club, season):
        """The club's youth categories, identified by data rather than by name.

        NOT `Category.objects.filter(departments=dept)`, which is what the
        first version did and what `seed_fatiga_central` still does: at this
        club only `Primer Equipo` has departments linked, so that filter
        resolved to one category and the five templates would have been
        offered to nobody. `applicable_categories` is the gate the API
        actually reads (`ExamTemplate.objects.filter(applicable_categories=…)`);
        `Category.departments` feeds the daily report's department list, which
        is a different question.

        A category is Formativo if it has a birth cohort, or if it fields a
        youth bracket in some season — that second clause is what picks up the
        club's `SUB-20`, which is a squad of four cohorts and has none of its
        own. Senior and women's categories are left out: the Formativo
        workbooks cover neither.
        """
        cats = []
        for cat in Category.objects.filter(club=club).prefetch_related(
                "team_seasons__bracket"):
            if cat.is_senior:
                continue
            if cat.cohort_year is not None:
                cats.append(cat)
                continue
            youth = any(ts.bracket and not ts.bracket.is_senior
                        for ts in cat.team_seasons.all())
            if youth:
                cats.append(cat)
        return cats

    def _categories(self, club, dept, season, ladder, min_rung):
        """Categories that run this test in `season`.

        Resolved from the rung, not stored as one: `applicable_categories` is a
        set of categories, so the answer changes every season. Re-run the
        command at each season start — see the module docstring.
        """
        cats = self._formativo(club, season)
        if min_rung is None:
            return cats
        youngest = min((b.age for b in ladder if b.age is not None), default=None)
        keep = []
        for cat in cats:
            if cat.cohort_year is None:
                # The top-bucket squad spans several cohorts and is the oldest
                # youth group, so any youth-rung cut includes it.
                keep.append(cat)
                continue
            age = season - cat.cohort_year
            # `Bracket.for_age` is a CEILING, so an 8-year-old comes back as
            # Sub 11 and would clear a "Sub 11 and up" cut. Series 2016–2018
            # ran no GPS at all, and this is the third place in this work where
            # the ceiling had to be guarded — see core/test_formativo_ladder.py.
            if youngest is not None and age < youngest:
                continue
            bracket = Bracket.for_age(age, ladder)
            if bracket is not None and (bracket.is_senior or bracket.age >= min_rung):
                keep.append(cat)
        return keep

    def _gps_applicability(self, club, dept, season, ladder):
        """Widen the two GPS exams to the youth categories that have GPS data.

        Both were applicable to `Primer Equipo` only, which would have made the
        ~13.000 youth GPS rows unimportable — there would be no template
        offering them a home. The GPS workbook has sheets `U11`…`U20` and none
        below, so the cut is Sub 11 and up; Series 2016–2018 run no GPS.

        Adding categories here does not change what anyone sees: a template
        with no results renders as an empty form.
        """
        from exams.models import ExamTemplate

        con_gps = self._categories(club, dept, season, ladder, min_rung=11)
        # Only the youth categories are ours to decide; `Primer Equipo` and the
        # women's categories keep whatever they already have. `add()` alone is
        # not enough — a previous run with a wrong cut left Series 2016–2018
        # attached, and additive-only would never take them back off.
        sin_gps = [c for c in self._formativo(club, season) if c not in con_gps]
        for slug in ("gps_sesion", "gps_partido"):
            template = ExamTemplate.objects.filter(
                department__club=club, slug=slug).first()
            if template is None:
                self.stdout.write(self.style.WARNING(f"  {slug}: no existe"))
                continue
            antes = set(template.applicable_categories.values_list("id", flat=True))
            template.applicable_categories.add(*con_gps)
            quitadas = [c for c in sin_gps if c.id in antes]
            if quitadas:
                template.applicable_categories.remove(*quitadas)
            total = template.applicable_categories.count()
            agregadas = len({c.id for c in con_gps} - antes)
            detalle = f"+{agregadas}" + (f" −{len(quitadas)}" if quitadas else "")
            self.stdout.write(self.style.SUCCESS(
                f"  {slug}: {detalle} categorías juveniles (Sub 11+), {total} en total"))

    def _gps_heart_rate(self, dept, unlock):
        from exams.models import ExamTemplate

        template = ExamTemplate.objects.filter(department=dept,
                                               slug="gps_sesion").first()
        if template is None:
            self.stdout.write(self.style.WARNING(
                "  gps_sesion no existe en este departamento: no se agregó FC"))
            return
        if template.is_locked and not unlock:
            self.stdout.write(self.style.WARNING(
                "  gps_sesion: bloqueada, pasá --unlock para agregar FC"))
            return
        schema = dict(template.config_schema or {})
        fields = list(schema.get("fields") or [])
        existentes = {f.get("key") for f in fields}
        nuevos = [f for f in GPS_HR_FIELDS if f["key"] not in existentes]
        if not nuevos:
            self.stdout.write("  gps_sesion: ya tenía los campos de FC")
            return
        schema["fields"] = fields + nuevos
        template.config_schema = schema
        if unlock:
            template.is_locked = False
        template.save(update_fields=["config_schema", "is_locked"])
        template.rebuild_template_fields()
        self.stdout.write(self.style.SUCCESS(
            f"  gps_sesion: + {', '.join(f['key'] for f in nuevos)}"))
