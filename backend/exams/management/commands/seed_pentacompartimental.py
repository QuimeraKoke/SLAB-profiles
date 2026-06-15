"""Overwrite the Pentacompartimental template's config_schema with the
Drinkwater **proportional** 5-mass fractionation method.

This is the implementation the U. de Chile medical team actually uses
(per `calculo_variables.py` shared by the client). Every mass is
computed as ``mass_i = peso × parte_i / Σ(parte_1..5)`` where each
``parte_i`` is a Phantom-Stratagem (Drinkwater / Kerr / De Rose)
estimate used only as a proportion. As a result, the 5 masses sum
exactly to body weight — unlike the prior Kerr direct-z-score variant
where they did not.

Key data semantics (verified against the client's reference values):
  - ``muslo_gluteo`` (legacy ``perimetro_muslo_maximo``) is the
    mid-thigh PERIMETER used in the muscle perimeter sum.
  - ``pliegue_muslo`` (legacy ``pliegues_muslo_medial``) is the
    mid-thigh SKINFOLD used in the π/10 perimeter correction.
  - ``muslo_medio`` (legacy ``perimetro_muslo_medial``) is NOT used by
    any formula — it's a misnamed legacy column kept only for
    backward-compatible storage.

Skin thickness is sex-dependent (M 0.65 mm / F 0.5 mm) via the
``player.sex`` namespace.

Run with:

    docker compose exec backend python manage.py seed_pentacompartimental \\
        --all-applicable-categories --unlock

Pass --unlock when results already exist (template is locked); use only
when the medical team accepts that historical computed values will
change to the new method.

Inputs required for the full 5-mass output:
  - peso, talla, sexo, talla_sentado
  - diámetros: humero, femur, biacromial, bi_iliocrestideo,
    diam_torax_ap, diam_torax_transverso
  - perímetros: cabeza, brazo_relajado, antebrazo, torax (meso),
    cintura, muslo_medio, pierna
  - 6 pliegues: triceps, subescapular, supra, abdomen, muslo, pierna
  - 2 pliegues extra para somatocarta (no usados por las 5 masas):
    bicipital, supracrestideo
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Department
from exams.models import ExamTemplate


# --- Phantom-Stratagem constants (Drinkwater proportional, per client) ----
# Embedded as literals in the formula strings below because SLAB's
# formula engine doesn't support named constants. Listed here so the
# formulas can be read against the canonical reference.
#
# Skin (Kerr/De Rose, sexo-dependiente):
#   skin_kg = CSA · W^0.425 · H^0.725 / 10000 · TSK · density
#   CSA: M 68.308 / F 73.704 ; TSK: M 2.07 mm / F 1.96 mm ; density 1.05 g/cm³
#
# Phantom height       = 170.18 cm   (standing reference)
# Phantom sit-height   = 89.92 cm    (sitting reference, residual)
#
# Adipose:   Σ6 mean 116.41 / SD 34.79 ; mass mean 25.6  / SD 5.85
# Muscle:    Σperim corr. mean 207.21 / SD 13.74 ; mass mean 24.5 / SD 5.4
# Residual:  Σ mean 109.35   / SD 7.08  ; mass mean 6.10 / SD 1.24
# Bone head: linear ((cabeza − 56) / 1.44) × 0.18 + 1.2  (no stature scale)
# Bone body: Σ4-diám mean 98.88 / SD 5.33 ; mass mean 6.7  / SD 1.34
# Perimeter correction factor: π/10 (≈ 0.31416) subtracted × pliegue.


PENTACOMPARTIMENTAL_SCHEMA: dict = {
    "fields": [
        # ─── Datos básicos ─────────────────────────────────────────────
        {"key": "peso",          "label": "Peso",                 "type": "number", "unit": "kg", "group": "Datos básicos", "required": True},
        {"key": "talla",         "label": "Talla",                "type": "number", "unit": "cm", "group": "Datos básicos", "required": True},
        {"key": "talla_sentado", "label": "Talla sentado",        "type": "number", "unit": "cm", "group": "Datos básicos",
         "help_text": "Necesario para masa residual (referencia Phantom 89.92 cm)."},
        {"key": "sexo",          "label": "Sexo (1=M, 2=F)",      "type": "number",               "group": "Datos básicos", "required": True},

        # ─── Diámetros óseos ──────────────────────────────────────────
        {"key": "humero",                "label": "Húmero (biepicondilar)",   "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "femur",                 "label": "Fémur (biepicondilar)",    "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "biacromial",            "label": "Biacromial",               "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "bi_iliocrestideo",      "label": "Bi-iliocrestídeo",         "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "diam_torax_transverso", "label": "Tórax transverso",         "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "diam_torax_ap",         "label": "Tórax antero-posterior",   "type": "number", "unit": "cm", "group": "Diámetros"},
        {"key": "biestiloideo",          "label": "Biestiloideo (muñeca)",    "type": "number", "unit": "cm", "group": "Diámetros",
         "help_text": "Sólo necesario para somatocarta. No usado por las 5 masas."},

        # ─── Perímetros ────────────────────────────────────────────────
        {"key": "perim_cabeza",          "label": "Cabeza",                   "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "perim_brazo_relajado",  "label": "Brazo relajado",           "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "perim_brazo_contraido", "label": "Brazo contraído",          "type": "number", "unit": "cm", "group": "Perímetros",
         "help_text": "Sólo necesario para somatocarta. No usado por las 5 masas."},
        {"key": "perim_antebrazo",       "label": "Antebrazo",                "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "perim_torax",           "label": "Tórax (mesoesternal)",     "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "cintura",               "label": "Cintura mínima",           "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "caderas",               "label": "Caderas máxima",           "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "muslo_gluteo",          "label": "Muslo 1 cm glúteo",        "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "muslo_medio",           "label": "Muslo medio",              "type": "number", "unit": "cm", "group": "Perímetros"},
        {"key": "pierna_perim",          "label": "Pierna",                   "type": "number", "unit": "cm", "group": "Perímetros"},

        # ─── Pliegues cutáneos ────────────────────────────────────────
        {"key": "pliegue_triceps",         "label": "Tríceps",         "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_subescapular",    "label": "Subescapular",    "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_supra",           "label": "Supraespinal",    "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_abdomen",         "label": "Abdominal",       "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_muslo",           "label": "Muslo medial",    "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_pierna",          "label": "Pantorrilla",     "type": "number", "unit": "mm", "group": "Pliegues"},
        {"key": "pliegue_bicipital",       "label": "Bicipital",       "type": "number", "unit": "mm", "group": "Pliegues",
         "help_text": "Pliegue extra para perfil completo y somatocarta."},
        {"key": "pliegue_supracrestideo",  "label": "Supracrestídeo",  "type": "number", "unit": "mm", "group": "Pliegues",
         "help_text": "Pliegue extra para perfil completo y somatocarta."},

        # ─── Otras medidas (opcionales) ───────────────────────────────
        {"key": "envergadura", "label": "Envergadura", "type": "number", "unit": "cm", "group": "Otras medidas"},
        {"key": "long_brazo",  "label": "Long. brazo", "type": "number", "unit": "cm", "group": "Otras medidas"},
        {"key": "long_pierna", "label": "Long. pierna","type": "number", "unit": "cm", "group": "Otras medidas"},

        # ─── Calculados — Sumatorias ──────────────────────────────────
        {
            "key": "imc", "label": "IMC", "type": "calculated", "unit": "kg/m²",
            "formula": "[peso] / (([talla] / 100) ** 2)",
            "chart_type": "line",
        },
        {
            "key": "suma_pliegues", "label": "Σ 6 pliegues", "type": "calculated", "unit": "mm",
            "formula": (
                "[pliegue_triceps] + [pliegue_subescapular] + [pliegue_supra] "
                "+ [pliegue_abdomen] + [pliegue_muslo] + [pliegue_pierna]"
            ),
            "chart_type": "line",
            "direction_of_good": "down",
            "reference_ranges": [
                {"label": "Élite",     "max": 30,             "color": "#16a34a"},
                {"label": "Bueno",     "min": 30, "max": 40,  "color": "#86efac"},
                {"label": "Aceptable", "min": 40, "max": 50,  "color": "#f59e0b"},
                {"label": "Elevado",   "min": 50,             "color": "#dc2626"},
            ],
        },
        {
            "key": "suma_8_pliegues", "label": "Σ 8 pliegues", "type": "calculated", "unit": "mm",
            "formula": (
                "[pliegue_triceps] + [pliegue_subescapular] + [pliegue_supra] "
                "+ [pliegue_abdomen] + [pliegue_muslo] + [pliegue_pierna] "
                "+ [pliegue_bicipital] + [pliegue_supracrestideo]"
            ),
            "chart_type": "line",
        },

        # ─── Calculados — Fraccionamiento 5 masas (Drinkwater proporcional) ──
        # Método proporcional Drinkwater: cada masa = peso * parte_i /
        # Σ(parte_1..5). Las 5 partes son estimaciones Phantom-Stratagem
        # que se usan SÓLO como proporciones — la suma de las 5 masas
        # resultantes coincide exactamente con el peso corporal (identidad
        # algebraica). Esta es la implementación que usa el equipo médico
        # de U. de Chile (archivo calculo_variables.py del cliente).
        #
        # Diferencias clave vs. Kerr directo (versión anterior):
        #   1. muslo_gluteo (perim_muslo_maximo legado) es el perímetro
        #      del muslo, NO muslo_medio. La columna muslo_medial del
        #      legado contiene en realidad un PLIEGUE (mm), no perímetro.
        #   2. Grosor de piel depende del sexo (M 0.65 / F 0.5) vía
        #      player.sex en lugar de un literal sexo=1.
        #   3. Las masas son proporciones del peso, no estimaciones
        #      Phantom directas con re-escalado talla³.

        # ─── Partes (estimaciones Phantom usadas como proporciones) ──
        {
            # Parte 1 — piel. Kerr/De Rose con constantes sexo-dependientes
            # (lo que efectivamente carga la tabla Constante del cliente):
            #   CSA: M 68.308 / F 73.704
            #   TSK: M 2.07 mm / F 1.96 mm
            #   densidad: 1.05 g/cm³
            #
            # piel_kg = CSA · W^0.425 · H^0.725 / 10000 · TSK · 1.05.
            "key": "parte_piel", "label": "Parte piel (proporción)",
            "type": "calculated", "unit": "kg",
            "formula": (
                '(73.704 if player.sex == "F" else 68.308) '
                "* [peso] ** 0.425 * [talla] ** 0.725 / 10000 "
                '* (1.96 if player.sex == "F" else 2.07) '
                "* 1.05"
            ),
        },
        {
            # Parte 2 — adiposa. Z-score Σ6 pliegues escalado a Phantom
            # (170.18 / talla), de-escalado / (170.18/talla)^3.
            "key": "parte_adiposa", "label": "Parte adiposa (proporción)",
            "type": "calculated", "unit": "kg",
            "formula": (
                "((([suma_pliegues] * (170.18 / [talla]) - 116.41) / 34.79) * 5.85 + 25.6) "
                "/ ((170.18 / [talla]) ** 3)"
            ),
        },
        {
            # Σ perímetros musculares corregidos por pliegue
            # (P − π · pliegue / 10). Usa muslo_gluteo como perímetro
            # (legado: perimetro_muslo_maximo) y pliegue_muslo como
            # corrección del muslo medial.
            "key": "sum_perim_muscle", "label": "Σ perímetros muscular (corr.)",
            "type": "calculated", "unit": "cm",
            "formula": (
                "[perim_brazo_relajado] - 3.14159 * [pliegue_triceps] / 10 "
                "+ [perim_antebrazo] "
                "+ [muslo_gluteo] - 3.14159 * [pliegue_muslo] / 10 "
                "+ [pierna_perim] - 3.14159 * [pliegue_pierna] / 10 "
                "+ [perim_torax] - 3.14159 * [pliegue_subescapular] / 10"
            ),
        },
        {
            # Parte 3 — muscular. Z-score sobre Σ perímetros corregidos.
            "key": "parte_muscular", "label": "Parte muscular (proporción)",
            "type": "calculated", "unit": "kg",
            "formula": (
                "((([sum_perim_muscle] * (170.18 / [talla]) - 207.21) / 13.74) * 5.4 + 24.5) "
                "/ ((170.18 / [talla]) ** 3)"
            ),
        },
        {
            # Σ residual = APCH + TRCH + cintura − π · abdominal / 10.
            "key": "sum_residual", "label": "Σ residual",
            "type": "calculated", "unit": "cm",
            "formula": (
                "[diam_torax_transverso] + [diam_torax_ap] "
                "+ [cintura] - 3.14159 * [pliegue_abdomen] / 10"
            ),
        },
        {
            # Parte 4 — residual. Escalado por talla SENTADO (Phantom 89.92).
            "key": "parte_residual", "label": "Parte residual (proporción)",
            "type": "calculated", "unit": "kg",
            "formula": (
                "((([sum_residual] * (89.92 / [talla_sentado]) - 109.35) / 7.08) * 1.24 + 6.10) "
                "/ ((89.92 / [talla_sentado]) ** 3)"
            ),
        },
        {
            # Parte 5a — ósea cabeza. Lineal sobre perim_cabeza (sin
            # escalado de talla — cabeza es relativamente invariante).
            "key": "parte_osea_cabeza", "label": "Parte ósea cabeza (proporción)",
            "type": "calculated", "unit": "kg",
            "formula": "(([perim_cabeza] - 56) / 1.44) * 0.18 + 1.2",
        },
        {
            # Parte 5b — ósea cuerpo. Z-score de la suma ponderada de
            # 4 diámetros: biacromial + bi-iliocrestídeo + 2·húmero + 2·fémur.
            "key": "parte_osea_cuerpo", "label": "Parte ósea cuerpo (proporción)",
            "type": "calculated", "unit": "kg",
            "formula": (
                "(((([biacromial] + [bi_iliocrestideo] + 2 * [humero] + 2 * [femur]) "
                "* (170.18 / [talla]) - 98.88) / 5.33) * 1.34 + 6.7) "
                "/ ((170.18 / [talla]) ** 3)"
            ),
        },
        {
            "key": "parte_osea", "label": "Parte ósea (proporción)",
            "type": "calculated", "unit": "kg",
            "formula": "[parte_osea_cabeza] + [parte_osea_cuerpo]",
        },
        {
            # Σ de las 5 partes — denominador del método proporcional.
            "key": "sum_partes", "label": "Σ partes",
            "type": "calculated", "unit": "kg",
            "formula": (
                "[parte_piel] + [parte_adiposa] + [parte_muscular] "
                "+ [parte_residual] + [parte_osea]"
            ),
        },

        # ─── Masas absolutas (kg) — proporcionales al peso ──────────
        {
            "key": "masa_piel", "label": "Masa Piel", "type": "calculated", "unit": "kg",
            "formula": "[peso] * [parte_piel] / [sum_partes]",
            "chart_type": "line",
        },
        {
            "key": "masa_osea_cabeza", "label": "Masa Ósea — Cabeza",
            "type": "calculated", "unit": "kg",
            "formula": "[peso] * [parte_osea_cabeza] / [sum_partes]",
            "chart_type": "line",
        },
        {
            "key": "masa_osea_cuerpo", "label": "Masa Ósea — Cuerpo",
            "type": "calculated", "unit": "kg",
            "formula": "[peso] * [parte_osea_cuerpo] / [sum_partes]",
            "chart_type": "line",
        },
        {
            "key": "masa_osea", "label": "Masa Ósea", "type": "calculated", "unit": "kg",
            "formula": "[peso] * [parte_osea] / [sum_partes]",
            "chart_type": "line",
        },
        {
            "key": "masa_adiposa", "label": "Masa Adiposa", "type": "calculated", "unit": "kg",
            "formula": "[peso] * [parte_adiposa] / [sum_partes]",
            "chart_type": "line",
        },
        {
            "key": "masa_muscular", "label": "Masa Muscular", "type": "calculated", "unit": "kg",
            "formula": "[peso] * [parte_muscular] / [sum_partes]",
            "chart_type": "line",
        },
        {
            "key": "masa_residual", "label": "Masa Residual", "type": "calculated", "unit": "kg",
            "formula": "[peso] * [parte_residual] / [sum_partes]",
            "chart_type": "line",
        },

        # ─── Calculados — Porcentajes y derivados ────────────────────
        {
            "key": "masa_adiposa_pct", "label": "% Masa Adiposa", "type": "calculated", "unit": "%",
            "formula": "[masa_adiposa] / [peso] * 100",
            "chart_type": "line",
            "direction_of_good": "down",
            "reference_ranges": [
                {"label": "Élite",     "max": 16,             "color": "#16a34a"},
                {"label": "Bueno",     "min": 16, "max": 19,  "color": "#86efac"},
                {"label": "Aceptable", "min": 19, "max": 23,  "color": "#f59e0b"},
                {"label": "Elevado",   "min": 23,             "color": "#dc2626"},
            ],
        },
        {
            "key": "masa_muscular_pct", "label": "% Masa Muscular", "type": "calculated", "unit": "%",
            "formula": "[masa_muscular] / [peso] * 100",
            "chart_type": "line",
            "direction_of_good": "up",
            "reference_ranges": [
                {"label": "Bajo",      "max": 47,             "color": "#dc2626"},
                {"label": "Aceptable", "min": 47, "max": 48,  "color": "#f59e0b"},
                {"label": "Bueno",     "min": 48, "max": 54,  "color": "#86efac"},
                {"label": "Élite",     "min": 54,             "color": "#16a34a"},
            ],
        },
        {
            "key": "masa_osea_pct", "label": "% Masa Ósea", "type": "calculated", "unit": "%",
            "formula": "[masa_osea] / [peso] * 100",
            "chart_type": "line",
        },
        {
            "key": "masa_residual_pct", "label": "% Masa Residual", "type": "calculated", "unit": "%",
            "formula": "[masa_residual] / [peso] * 100",
            "chart_type": "line",
        },
        {
            "key": "masa_piel_pct", "label": "% Masa Piel", "type": "calculated", "unit": "%",
            "formula": "[masa_piel] / [peso] * 100",
            "chart_type": "line",
        },
        {
            # IMO — proxy de calidad del tejido magro. Cuarta métrica
            # del semáforo nutricional.
            "key": "imo", "label": "IMO (Muscular/Óseo)", "type": "calculated", "unit": "",
            "formula": "[masa_muscular] / [masa_osea]",
            "chart_type": "line",
            "direction_of_good": "up",
            "reference_ranges": [
                {"label": "Bajo",      "max": 3.8,             "color": "#dc2626"},
                {"label": "Aceptable", "min": 3.8, "max": 4.2, "color": "#f59e0b"},
                {"label": "Bueno",     "min": 4.2, "max": 4.5, "color": "#86efac"},
                {"label": "Élite",     "min": 4.5,             "color": "#16a34a"},
            ],
        },
        {
            # Índice adipo-muscular (IAM) — útil para seguimiento de
            # cambios de composición durante pre-temporada / cargas.
            "key": "iam", "label": "IAM (Adiposo/Muscular)", "type": "calculated", "unit": "",
            "formula": "[masa_adiposa] / [masa_muscular]",
            "chart_type": "line",
            "direction_of_good": "down",
        },

        # ─── Texto libre ──────────────────────────────────────────────
        {
            "key": "objetivo", "label": "Objetivo", "type": "text",
            "multiline": True, "rows": 2, "group": "Notas",
            "placeholder": "Objetivo general de esta evaluación o ciclo.",
        },
        {
            "key": "notas", "label": "Comentarios", "type": "text",
            "multiline": True, "rows": 4, "group": "Notas",
            "placeholder": "Observaciones del antropometrista, contexto, anomalías…",
        },
    ]
}


class Command(BaseCommand):
    help = (
        "Overwrite the Pentacompartimental ExamTemplate's config_schema "
        "with the Kerr/De Rose Phantom-Stratagem 5-mass fractionation. "
        "Use --unlock when historical results exist; this WILL change "
        "the calculated values for old rows because the formulas differ "
        "from the previous (Carter-simple / Drinkwater-Ross) versions."
    )

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Pentacompartimental",
                            help="Template name to match (default: 'Pentacompartimental').")
        parser.add_argument("--club", default=None,
                            help="Scope to a club by name (required for --create-if-missing when multi-club).")
        parser.add_argument("--department-slug", default=None,
                            help="Department slug. Required only with --create-if-missing.")
        parser.add_argument("--create-if-missing", action="store_true",
                            help="Create the template if no matching one exists.")
        parser.add_argument("--all-applicable-categories", action="store_true",
                            help="Attach to every category in the department's club.")
        parser.add_argument("--unlock", action="store_true",
                            help="Also clear is_locked. Required when results already exist.")

    def handle(self, *args, **options):
        name = options["name"]
        club_name = options["club"]
        department_slug = options["department_slug"]
        create_if_missing = options["create_if_missing"]
        attach_all = options["all_applicable_categories"]
        unlock = options["unlock"]

        qs = ExamTemplate.objects.filter(name=name).select_related("department__club")
        if club_name:
            qs = qs.filter(department__club__name=club_name)
        templates = list(qs)

        if not templates and create_if_missing:
            templates = [self._create_template(name, club_name, department_slug, attach_all)]

        if not templates:
            raise CommandError(
                f"No ExamTemplate found with name='{name}'"
                + (f" in club='{club_name}'" if club_name else "")
                + ". Pass --create-if-missing --department-slug <slug> [--club <name>] "
                  "to create it from scratch."
            )

        for template in templates:
            if template.is_locked and not unlock:
                self.stdout.write(self.style.WARNING(
                    f"Skipping '{template.name}' (club: "
                    f"{template.department.club.name}) — template is locked. "
                    "Pass --unlock if you want to overwrite the schema."
                ))
                continue
            template.config_schema = PENTACOMPARTIMENTAL_SCHEMA
            update_fields = ["config_schema", "updated_at"]
            if unlock and template.is_locked:
                template.is_locked = False
                update_fields.append("is_locked")
            template.save(update_fields=update_fields)
            template.rebuild_template_fields()

            if attach_all:
                cats = Category.objects.filter(
                    club=template.department.club,
                    departments=template.department,
                )
                template.applicable_categories.set(cats)

            self.stdout.write(self.style.SUCCESS(
                f"Updated '{template.name}' (club: {template.department.club.name}, "
                f"department: {template.department.name}, "
                f"fields: {len(PENTACOMPARTIMENTAL_SCHEMA['fields'])}, "
                f"categories: {template.applicable_categories.count()})"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(templates)} template(s) updated to Phantom-Stratagem 5-mass."
        ))

    @transaction.atomic
    def _create_template(self, name, club_name, department_slug, attach_all):
        if not department_slug:
            raise CommandError("--create-if-missing requires --department-slug.")
        if club_name:
            club = Club.objects.filter(name=club_name).first()
            if club is None:
                raise CommandError(f"Club '{club_name}' not found.")
        else:
            clubs = list(Club.objects.all()[:2])
            if not clubs:
                raise CommandError("No clubs in database.")
            if len(clubs) > 1:
                raise CommandError("Multiple clubs exist; pass --club <name>.")
            club = clubs[0]

        department = Department.objects.filter(club=club, slug=department_slug).first()
        if department is None:
            raise CommandError(
                f"Department slug='{department_slug}' not found in club '{club.name}'."
            )

        template = ExamTemplate.objects.create(
            name=name, slug="pentacompartimental",
            department=department, config_schema={},
        )
        if attach_all:
            cats = Category.objects.filter(club=club, departments=department)
            template.applicable_categories.set(cats)
        return template
