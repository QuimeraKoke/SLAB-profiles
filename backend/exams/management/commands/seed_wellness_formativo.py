"""Create the Formativo's own Check-IN and Check-OUT templates.

The club fills a **different** wellness form in the Formativo than in Primer
Equipo. They overlap on sleep and mood and diverge on everything else:

| Primer Equipo (`checkin_fisico`) | Formativo (`checkin_formativo`) |
|---|---|
| estado de entrenamiento | calidad de sueño |
| calidad de recuperación | nivel de fatiga |
| cómo sientes tu cuerpo | **daño muscular** |
| nivel de energía | **nivel de estrés** |
| estado de ánimo | estado de ánimo |
| cómo dormiste | síntomas |
| total bienestar | **peso**, **hidratación**, **última comida** |

So one template cannot serve both, and neither can one hardcoded item list —
which is why `api/wellness.py` now reads the score's items from the template's
own `wellness` block instead of a module constant.

And the Formativo has something Primer Equipo does not: a **Check-OUT**. RPE
and session duration per player, which multiply into internal load (the club's
own `UA` column), plus per-muscle soreness and three match-perception scales.
That is the first post-session exam in the system.

    docker compose exec backend python manage.py seed_wellness_formativo \\
        --club "Universidad de Chile" --season 2026

Derived columns are computed, not imported
------------------------------------------
The sheets carry `SUMA` (check-in total) and `UA` (RPE × duration). Both are
derived, and their headers are inconsistent across the eight documents —
`SUMA` in four, a bare `0` in one, `UA` in six and `AU` in one. Importing a
column whose own name is a typo is how a metric silently becomes half-empty,
so the templates compute them.
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Bracket, Category, Club, Department

# Bandas de la escala 1–5, compartidas por las doce categorías.
#
# Van en el CAMPO y no en `config["ranges"]` de cada regla a propósito: un 3 de
# sueño significa lo mismo en Serie 2018 que en SUB-20, así que replicarlas por
# categoría serían 12 copias del mismo número esperando a desincronizarse. Las
# pruebas físicas son el caso contrario — ahí el club mide el mismo test con
# umbrales distintos por edad y por eso `seed_formativo_bands` sí las escribe
# por categoría.
#
# Los límites son inclusivos y gana el primer match, así que el orden importa:
# un 3 cae en "Aviso" porque "Crítico" cierra en 2. El club puede sobreescribir
# los números por categoría desde el editor de bandas sin tocar esto.
BANDAS_1_5 = [
    {"min": 1, "max": 2, "label": "Crítico", "color": "#dc2626", "alert": True},
    {"min": 2, "max": 3, "label": "Aviso", "color": "#f59e0b"},
    {"min": 3, "max": 5, "label": "Normal", "color": "#16a34a"},
]


# 1–5 self-report scales. `direction_of_good` differs per item and that is the
# point: more sleep is better, more fatigue is worse. Getting one backwards
# inverts its band on every chart.
def _escala(key: str, label: str, grupo: str, *, mas_es_mejor: bool,
            bandas: bool = True) -> dict:
    campo = {
        "key": key, "label": label, "type": "number", "unit": "",
        "group": grupo, "min": 1, "max": 5, "chart_type": "line",
        "direction_of_good": "up" if mas_es_mejor else "down",
    }
    if bandas:
        campo["reference_ranges"] = [dict(b) for b in BANDAS_1_5]
    return campo


G_BIEN, G_CUERPO, G_HABITOS = "Bienestar", "Cuerpo", "Hábitos"

CHECKIN = {
    "fields": [
        # ⚠️ Los cinco apuntan en la MISMA dirección: 5 es lo mejor, también en
        # fatiga, estrés y daño. `NIVEL DE FATIGA` 5 es "sin fatiga", no
        # "fatiga máxima". Verificado contra la columna `SUMA` del propio club,
        # que es la suma CRUDA de los cinco: 25.146 filas de tres documentos
        # coinciden al 100% con la suma cruda y 0 con la versión invertida.
        _escala("calidad_sueno", "Calidad del sueño", G_BIEN, mas_es_mejor=True),
        _escala("nivel_fatiga", "Nivel de fatiga", G_BIEN, mas_es_mejor=True),
        _escala("nivel_estres", "Nivel de estrés", G_BIEN, mas_es_mejor=True),
        _escala("estado_animo", "Estado de ánimo", G_BIEN, mas_es_mejor=True),
        _escala("dano_muscular", "Daño muscular", G_CUERPO, mas_es_mejor=True),
        # Sólo la pregunta el documento de SUB 16, y hoy está entera vacía. Va
        # igual para que el importador no la reporte como columna desconocida.
        _escala("nivel_recuperacion", "Nivel de recuperación", G_BIEN,
                mas_es_mejor=True),
        {"key": "sintomas", "label": "Síntomas", "type": "text", "group": G_CUERPO},
        {"key": "dolor_muscular", "label": "Dolor muscular (zona)",
         "type": "text", "group": G_CUERPO},
        # Sin bandas: el peso "normal" es el del jugador, no un rango del
        # formulario. Una banda compartida le diría a un Serie 2018 y a un
        # SUB-20 lo mismo.
        {"key": "peso", "label": "Peso", "type": "number", "unit": "kg",
         "group": G_CUERPO, "min": 25, "max": 130, "chart_type": "line"},
        # ⚠️ NO es una escala 1–5, aunque el formulario la llame "nivel".
        # Medido sobre 46.512 respuestas: va de 1 a 9 y el 78% son 2 o 3 —
        # litros de agua al día, donde 2 es lo normal. Tratada como escala 1–5
        # con banda "1–2 = Crítico", marcaba el 55% de las respuestas del
        # plantel como críticas y enterraba a las alertas reales.
        #
        # Sin banda por defecto a propósito: cuántos litros son pocos es una
        # decisión del cuerpo médico, no algo que se pueda inferir de la
        # distribución. El editor de bandas está para eso.
        {"key": "hidratacion", "label": "Hidratación", "type": "number",
         "unit": "L", "group": G_HABITOS, "min": 0, "max": 10,
         "chart_type": "line", "direction_of_good": "up"},
        {"key": "ultima_comida", "label": "Última comida antes de entrenar",
         "type": "text", "group": G_HABITOS},
        {"key": "relaciones_afectivas",
         "label": "¿Relaciones afectivas y/o familiares armónicas?",
         "type": "text", "group": G_BIEN},
        # Only two of the eight documents ask it. Optional, like every field a
        # category does not measure.
        {"key": "asistio_clases", "label": "¿Asistió a clases escolares?",
         "type": "text", "group": G_HABITOS},
        {
            "key": "total_bienestar", "label": "Total bienestar",
            "type": "calculated", "unit": "", "group": G_BIEN,
            "chart_type": "line", "direction_of_good": "up",
            # The club's own `SUMA`, recomputed: the raw sum of the five, 5 to
            # 25. Raw because all five point the same way — see the note on the
            # scales above. Mirroring three of them (which is what this formula
            # used to do) produced a number the club would not recognise: 15
            # where their sheet says 19.
            "formula": ("[calidad_sueno] + [nivel_fatiga] + [nivel_estres] "
                        "+ [estado_animo] + [dano_muscular]"),
        },
    ],
    # What makes this template the category's Check-IN, and which of its fields
    # the 0–100 score averages. Read by api/wellness.py.
    "wellness": {
        "role": "checkin",
        "items": [
            ["calidad_sueno", "Sueño"],
            ["nivel_fatiga", "Fatiga"],
            ["nivel_estres", "Estrés"],
            ["estado_animo", "Ánimo"],
            ["dano_muscular", "Daño muscular"],
        ],
        # NINGUNO invertido: en este formulario 5 siempre es lo mejor.
        "inverted": [],
        "dimensions": [["calidad_sueno", "Sueño"], ["nivel_fatiga", "Fatiga"],
                       ["estado_animo", "Ánimo"]],
    },
}

G_CARGA, G_MOLESTIA, G_PARTIDO = "Carga", "Molestias", "Percepción de partido"
MUSCULOS = [("isquiotibiales", "Isquiotibiales"), ("aductores", "Aductores"),
            ("cuadriceps", "Cuádriceps"), ("gemelos", "Gemelos")]

CHECKOUT = {
    "fields": [
        {"key": "duracion_min", "label": "Duración de la sesión",
         "type": "number", "unit": "min", "group": G_CARGA,
         "min": 1, "max": 240, "chart_type": "line"},
        {"key": "rpe", "label": "Esfuerzo percibido (RPE)", "type": "number",
         "unit": "", "group": G_CARGA, "min": 0, "max": 10,
         "chart_type": "line", "direction_of_good": "neutral",
         # Zonas de intensidad para leer el gráfico, con `alert: False` en
         # todas. El RPE mide CARGA: una sesión de 9 es una sesión dura, no un
         # problema, y sin el flag explícito la heurística de
         # `exams.bands.alert_bands` elegiría la banda más roja y la haría
         # disparar sola.
         "reference_ranges": [
             {"min": 0, "max": 4, "label": "Baja", "color": "#93c5fd",
              "alert": False},
             {"min": 4, "max": 7, "label": "Moderada", "color": "#60a5fa",
              "alert": False},
             {"min": 7, "max": 9, "label": "Alta", "color": "#2563eb",
              "alert": False},
             {"min": 9, "max": 10, "label": "Máxima", "color": "#1e3a8a",
              "alert": False},
         ]},
        {
            "key": "carga_interna", "label": "Carga interna (UA)",
            "type": "calculated", "unit": "UA", "group": G_CARGA,
            "chart_type": "line", "direction_of_good": "neutral",
            # RPE × minutes — the club's `UA`. Computed rather than imported:
            # that column is headed `UA` in six documents and `AU` in one, and
            # a metric whose own header is a typo goes half-empty in silence.
            "formula": "[rpe] * [duracion_min]",
        },
        # Misma dirección que en el check-in: 5 = sin daño. Verificado contra
        # las cuatro columnas de músculo: quien puntúa 1–2 nombra un músculo
        # dolorido en el 50–70% de las filas, quien puntúa 5 en el 1%.
        _escala("dano_muscular", "Daño muscular", G_MOLESTIA, mas_es_mejor=True),
        {"key": "molestia_post", "label": "Molestia muscular post-sesión",
         "type": "text", "group": G_MOLESTIA},
        *[{"key": f"molestia_{k}", "label": f"Molestia — {etiqueta}",
           "type": "text", "group": G_MOLESTIA} for k, etiqueta in MUSCULOS],
        {"key": "observaciones", "label": "Otras molestias u observaciones",
         "type": "text", "group": G_MOLESTIA, "multiline": True, "rows": 2},
        _escala("partido_recuperacion",
                "Partido — capacidad de recuperación entre esfuerzos",
                G_PARTIDO, mas_es_mejor=True),
        _escala("partido_explosivas",
                "Partido — rendimiento en acciones explosivas",
                G_PARTIDO, mas_es_mejor=True),
        _escala("partido_fisico", "Partido — rendimiento físico general",
                G_PARTIDO, mas_es_mejor=True),
        {"key": "tipo_entrenamiento", "label": "Tipo de entrenamiento",
         "type": "text", "group": G_CARGA},
        {"key": "proteina_post", "label": "¿Consumiste proteína post-entrenamiento?",
         "type": "text", "group": G_CARGA},
        {"key": "puntos_recuperacion",
         "label": "Puntos de recuperación posteriores a la sesión",
         # El techo no es 20: los valores reales llegan a 105 y más.
         "type": "number", "unit": "", "group": G_CARGA, "min": 0, "max": 200},
    ],
    "wellness": {
        "role": "checkout",
        # Sólo el daño muscular. El RPE mide CARGA, no bienestar: meterlo en el
        # puntaje hace que una sesión exigente se pinte de rojo un martes
        # cualquiera, y su `direction_of_good` es neutral justamente por eso.
        # Dos documentos (SUB 12 y SUB 13) ni siquiera preguntan daño muscular
        # en el check-out; ahí el puntaje queda vacío, que es lo honesto.
        "items": [["dano_muscular", "Daño muscular"]],
        "inverted": [],
        # `carga_interna` NO va como chip: UA no tiene techo, así que como
        # porcentaje de algo no significa nada. El RPE sí, leído como
        # intensidad (6/10 → 60).
        "dimensions": [["dano_muscular", "Daño muscular"], ["rpe", "RPE"]],
    },
}

# Qué campos vigilan una alerta. Sólo las escalas 1–5 con bandas: el peso no
# tiene un rango compartido y el RPE mide carga, no bienestar.
CAMPOS_CON_ALERTA = {
    "checkin_formativo": ["calidad_sueno", "nivel_fatiga", "nivel_estres",
                          "estado_animo", "dano_muscular"],
    "checkout_formativo": ["dano_muscular", "partido_recuperacion",
                           "partido_explosivas", "partido_fisico"],
}

# `trigger_labels` decide qué banda dispara cada severidad. Sin ellos, el
# evaluador cae a la heurística de "la banda más roja" y las dos reglas del
# mismo campo dispararían por lo mismo.
SEVERIDADES = (("critical", ["Crítico"]), ("warning", ["Aviso"]))


INPUT_CONFIG = {
    "input_modes": ["team_table", "single", "bulk_ingest"],
    "default_input_mode": "team_table",
    "team_table": {"shared_fields": []},
}

PLANTILLAS = [
    ("checkin_formativo", "Check-IN formativo", CHECKIN),
    ("checkout_formativo", "Check-OUT formativo", CHECKOUT),
]


class Command(BaseCommand):
    help = "Crea las plantillas de Check-IN y Check-OUT del formativo."

    def add_arguments(self, parser):
        parser.add_argument("--club", required=True)
        parser.add_argument("--department-slug", default="fisico")
        parser.add_argument("--season", type=int, default=None)
        parser.add_argument("--unlock", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        from exams.models import ExamTemplate

        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")
        dept = Department.objects.filter(
            club=club, slug=opts["department_slug"]).first()
        if dept is None:
            raise CommandError(
                f"No existe el departamento '{opts['department_slug']}'.")
        season = opts["season"] or date.today().year

        cats = self._formativo(club, season)
        for slug, nombre, schema in PLANTILLAS:
            template = ExamTemplate.objects.filter(department=dept, slug=slug).first()
            if template is None:
                template = ExamTemplate(department=dept, slug=slug, name=nombre,
                                        config_schema=schema,
                                        input_config=INPUT_CONFIG)
                accion = "creada"
            elif template.is_locked and not opts["unlock"]:
                self.stdout.write(self.style.WARNING(
                    f"  {nombre}: bloqueada, pasá --unlock"))
                continue
            else:
                template.name = nombre
                template.config_schema = schema
                template.input_config = INPUT_CONFIG
                if opts["unlock"]:
                    template.is_locked = False
                accion = "actualizada"
            template.save()
            template.rebuild_template_fields()
            template.applicable_categories.set(cats)
            self.stdout.write(self.style.SUCCESS(
                f"  {nombre}: {accion} · {len(schema['fields'])} campos · "
                f"{len(cats)} categorías"))

        self._alertas()
        self.stdout.write(
            "\n  Categorías: " + ", ".join(sorted(c.name for c in cats)))

    def _alertas(self):
        """Una regla `band` por campo y severidad, sin categoría.

        `category=None` significa "todas", que es lo correcto acá: los umbrales
        de una escala 1–5 son los mismos en las doce. Es además el patrón que
        ya tiene `checkin_fisico`.

        Nunca toca una regla existente. El cuerpo médico va a ajustar estos
        números desde el editor de bandas, y una segunda corrida del seeder no
        puede borrar ese trabajo.
        """
        from exams.models import ExamTemplate
        from goals.models import AlertRule

        creadas = existentes = 0
        for slug, campos in CAMPOS_CON_ALERTA.items():
            template = ExamTemplate.objects.filter(slug=slug).first()
            if template is None:
                continue
            for campo in campos:
                for severidad, labels in SEVERIDADES:
                    _, nueva = AlertRule.objects.get_or_create(
                        template=template, field_key=campo, category=None,
                        severity=severidad, kind="band",
                        defaults={"config": {"trigger_labels": labels},
                                  "is_active": True},
                    )
                    creadas += nueva
                    existentes += not nueva
        self.stdout.write(self.style.SUCCESS(
            f"  Alertas: {creadas} creadas · {existentes} ya existían"))

    def _formativo(self, club, season):
        """Youth categories, by data rather than by name — same rule as the
        physical templates: a cohort, or a squad that fields a youth bracket."""
        cats = []
        for cat in Category.objects.filter(club=club).prefetch_related(
                "team_seasons__bracket"):
            if cat.is_senior or "Femenino" in cat.name:
                continue
            if cat.cohort_year is not None or any(
                    ts.bracket and not ts.bracket.is_senior
                    for ts in cat.team_seasons.all()):
                cats.append(cat)
        return cats
