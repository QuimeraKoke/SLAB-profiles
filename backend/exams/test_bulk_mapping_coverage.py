"""Ninguna plantilla puede ofrecer carga masiva sin saber leer el archivo.

Este archivo existe por un bug de configuración que se repitió dos veces:
`seed_pentacompartimental` y `seed_peso_talla` agregaban `bulk_ingest` a
`input_modes` y nunca definían `column_mapping`. El modo aparecía en la UI y
tanto la subida como la descarga de la plantilla devolvían 400.

El primer test es el que importa: recorre TODAS las plantillas activas, así que
la próxima que habilite el modo sin mapping falla acá y no en la cara del club.
"""
from __future__ import annotations

import io

import openpyxl
from django.core.management import call_command
from django.test import TestCase

from core.models import Category, Club, Department
from exams.bulk_ingest import blank_workbook, mapping_from_schema
from exams.models import ExamTemplate


class BulkModeNeedsAMappingTests(TestCase):
    """El invariante, sobre todas las plantillas que los seeds crean."""

    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        for name, slug in (("Nutricional", "nutricional"),
                           ("Psicosocial", "psicosocial")):
            Department.objects.create(club=cls.club, name=name, slug=slug)
        cat = Category.objects.create(
            club=cls.club, name="Primer Equipo", is_senior=True)
        cat.departments.set(Department.objects.filter(club=cls.club))
        for cmd in ("seed_peso_talla", "seed_fatiga_central"):
            call_command(cmd, "--create-if-missing",
                         "--club", "Universidad de Chile", verbosity=0)

    def test_every_template_offering_bulk_can_read_a_file(self):
        offenders = []
        for t in ExamTemplate.objects.filter(is_active_version=True):
            cfg = t.input_config or {}
            if "bulk_ingest" not in (cfg.get("input_modes") or []):
                continue
            field_map = (cfg.get("column_mapping") or {}).get("field_map")
            if not field_map:
                offenders.append(t.slug)
        self.assertEqual(
            offenders, [],
            f"ofrecen carga masiva sin column_mapping: {offenders}",
        )

    def test_every_template_offering_bulk_can_hand_out_its_template(self):
        for t in ExamTemplate.objects.filter(is_active_version=True):
            cfg = t.input_config or {}
            if "bulk_ingest" not in (cfg.get("input_modes") or []):
                continue
            content = blank_workbook(t)          # no debe lanzar
            ws = openpyxl.load_workbook(io.BytesIO(content)).active
            self.assertGreater(ws.max_column, 1, t.slug)
            self.assertEqual(ws.max_row, 1, t.slug)


class MappingFromSchemaTests(TestCase):
    """La derivación, que es lo que evita listas paralelas que se desincronizan."""

    SCHEMA = {
        "fields": [
            {"key": "peso", "label": "Peso", "type": "number", "unit": "kg"},
            {"key": "talla", "label": "Talla", "type": "number", "unit": "cm"},
            {"key": "sexo", "label": "Sexo (1=M, 2=F)", "type": "number"},
            {"key": "imc", "label": "IMC", "type": "calculated", "unit": "kg/m²"},
            {"key": "notas", "label": "Comentarios", "type": "text"},
            {"key": "chequeado", "label": "Chequeado", "type": "boolean"},
        ],
    }

    def test_it_takes_only_the_number_fields(self):
        fm = mapping_from_schema(self.SCHEMA)["field_map"]
        self.assertEqual(
            set(fm), {"Peso (kg)", "Talla (cm)", "Sexo (1=M, 2=F)"})

    def test_the_header_carries_the_unit(self):
        """La unidad no es decoración.

        El error que corrompe una antropometría es una talla en metros, y el
        encabezado que dice "(cm)" es la primera defensa contra eso.
        """
        fm = mapping_from_schema(self.SCHEMA)["field_map"]
        self.assertIn("Talla (cm)", fm)
        self.assertNotIn("Talla", fm)

    def test_exclusions_are_honoured(self):
        fm = mapping_from_schema(self.SCHEMA, exclude=("sexo",))["field_map"]
        self.assertNotIn("Sexo (1=M, 2=F)", fm)

    def test_the_player_column_is_configurable(self):
        m = mapping_from_schema(self.SCHEMA, player_column="Atleta")
        self.assertEqual(m["player_lookup"]["column"], "Atleta")

    def test_calculated_and_text_never_appear(self):
        # Un calculado se pisa al guardar; un archivo de mediciones no lleva
        # texto libre ni checkboxes.
        fm = mapping_from_schema(self.SCHEMA)["field_map"]
        for excluded in ("IMC (kg/m²)", "Comentarios", "Chequeado"):
            self.assertNotIn(excluded, fm)
