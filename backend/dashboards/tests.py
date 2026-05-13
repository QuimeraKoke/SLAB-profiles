"""Resolver tests for the body_map_heatmap chart_type.

Other resolvers (comparison_table, line_with_selector, …) are exercised
implicitly through fixture-driven UI testing; this file targets the new
surface area: counts-per-region + option_regions plumbing.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player
from exams.models import ExamResult, ExamTemplate

from .aggregation import resolve_widget
from .models import (
    Aggregation,
    ChartType,
    DepartmentLayout,
    LayoutSection,
    Widget,
    WidgetDataSource,
)


def _build_widget(template, field_keys, *, kind=ChartType.BODY_MAP_HEATMAP):
    """Helper: stand up a Widget + WidgetDataSource for the given template."""
    layout = DepartmentLayout.objects.create(
        department=template.department,
        category=template.applicable_categories.first(),
    )
    section = LayoutSection.objects.create(layout=layout)
    widget = Widget.objects.create(
        section=section,
        chart_type=kind,
        title="Body map",
    )
    WidgetDataSource.objects.create(
        widget=widget,
        template=template,
        field_keys=field_keys,
        aggregation=Aggregation.ALL,
    )
    return widget


class BodyMapResolverTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Med", slug="med")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B",
        )
        self.template = ExamTemplate.objects.create(
            name="Lesiones", slug="lesiones", department=self.dept,
            config_schema={
                "fields": [
                    {
                        "key": "body_part", "type": "categorical",
                        "label": "Parte del cuerpo",
                        "options": ["Muslo der.", "Muslo izq.", "Cabeza"],
                        "option_regions": {
                            "Muslo der.": "right_thigh",
                            "Muslo izq.": "left_thigh",
                            "Cabeza": "head",
                        },
                    },
                    {"key": "stage", "type": "categorical", "options": ["injured"]},
                ],
            },
        )
        self.template.applicable_categories.add(self.cat)

    def _result(self, body_part: str, days_ago: int = 0):
        return ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now() - timedelta(days=days_ago),
            result_data={"body_part": body_part, "stage": "injured"},
        )

    def test_counts_per_region(self):
        # 3 hamstring (right), 1 head, 1 left thigh.
        for d in (10, 8, 5):
            self._result("Muslo der.", days_ago=d)
        self._result("Cabeza", days_ago=4)
        self._result("Muslo izq.", days_ago=2)

        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)

        self.assertEqual(payload["chart_type"], "body_map_heatmap")
        self.assertEqual(payload["counts"], {
            "right_thigh": 3,
            "head": 1,
            "left_thigh": 1,
        })
        self.assertEqual(payload["max_count"], 3)
        self.assertEqual(payload["total_results"], 5)

    def test_items_carry_option_labels_and_per_option_counts(self):
        self._result("Muslo der.")
        self._result("Muslo der.")
        self._result("Cabeza")

        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)

        items_by_region = {it["region"]: it for it in payload["items"]}
        self.assertEqual(items_by_region["right_thigh"]["count"], 2)
        # Should expose the option that contributed.
        opts = items_by_region["right_thigh"]["options"]
        self.assertEqual(opts, [{"value": "Muslo der.", "label": "Muslo der.", "count": 2}])

    def test_unmapped_options_are_silently_skipped(self):
        # "Espalda" isn't in option_regions for this template — should be
        # excluded from counts but the result still inflates total_results.
        self._result("Cabeza")
        self.template.config_schema["fields"][0]["option_regions"]["Cabeza"] = "head"
        # Save a result with an unmapped option:
        ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now(),
            result_data={"body_part": "Espalda", "stage": "injured"},
        )
        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)
        # Only the mapped option counted.
        self.assertEqual(payload["counts"], {"head": 1})
        self.assertEqual(payload["total_results"], 2)

    def test_no_results_gives_zero_max(self):
        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)
        self.assertEqual(payload["counts"], {})
        self.assertEqual(payload["max_count"], 0)
        self.assertEqual(payload["total_results"], 0)

    def test_template_without_option_regions_returns_zero_counts(self):
        # Strip option_regions from the field config.
        self.template.config_schema["fields"][0].pop("option_regions", None)
        self.template.save(update_fields=["config_schema"])

        self._result("Muslo der.")
        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)
        self.assertEqual(payload["counts"], {})
        self.assertEqual(payload["max_count"], 0)
        # Result still counts in total_results — useful so the widget header
        # can show "1 resultado" and the empty-state hint kicks in.
        self.assertEqual(payload["total_results"], 1)


class BodyMapStageBucketingTests(TestCase):
    """Episodic templates with a stage_field bucket counts per stage so
    the frontend can render a stage-filter chip selector."""

    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Med", slug="med")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.player = Player.objects.create(
            category=self.cat, first_name="A", last_name="B",
        )
        self.template = ExamTemplate.objects.create(
            name="Lesiones", slug="lesiones", department=self.dept,
            is_episodic=True,
            episode_config={
                "stage_field": "stage",
                "open_stages": ["injured", "recovery", "reintegration"],
                "closed_stage": "closed",
            },
            config_schema={
                "fields": [
                    {
                        "key": "body_part", "type": "categorical",
                        "label": "Parte del cuerpo",
                        "options": ["Muslo der.", "Cabeza", "Espalda alta"],
                        "option_regions": {
                            "Muslo der.": "right_thigh",
                            "Cabeza": "head",
                            "Espalda alta": "upper_back",
                        },
                    },
                    {
                        "key": "stage", "type": "categorical",
                        "options": ["injured", "recovery", "reintegration", "closed"],
                        "option_labels": {
                            "injured": "Lesionado",
                            "recovery": "Recuperación",
                            "reintegration": "Reintegración",
                            "closed": "Cerrado",
                        },
                    },
                ],
            },
        )
        self.template.applicable_categories.add(self.cat)

    def _result(self, body_part: str, stage: str, days_ago: int = 0):
        return ExamResult.objects.create(
            player=self.player, template=self.template,
            recorded_at=timezone.now() - timedelta(days=days_ago),
            result_data={"body_part": body_part, "stage": stage},
        )

    def test_counts_by_stage_bucketed(self):
        self._result("Muslo der.", "injured", days_ago=10)
        self._result("Muslo der.", "recovery", days_ago=8)
        self._result("Muslo der.", "closed", days_ago=5)
        self._result("Cabeza", "injured", days_ago=4)
        self._result("Espalda alta", "recovery", days_ago=2)

        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)

        # Total counts (all stages combined) — same as the simple resolver path.
        self.assertEqual(payload["counts"], {
            "right_thigh": 3, "head": 1, "upper_back": 1,
        })
        # Per-stage buckets:
        self.assertEqual(payload["counts_by_stage"], {
            "injured": {"right_thigh": 1, "head": 1},
            "recovery": {"right_thigh": 1, "upper_back": 1},
            "closed": {"right_thigh": 1},
        })
        # No reintegration results → no bucket for it (frontend handles missing).
        self.assertNotIn("reintegration", payload["counts_by_stage"])

    def test_stages_list_in_canonical_order_with_labels(self):
        # Even with no results, the stages list reflects the configured order
        # so the chip selector renders the same chips for any player.
        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)

        stages = payload["stages"]
        # Order: open_stages worst→best, then closed.
        self.assertEqual(
            [s["value"] for s in stages],
            ["injured", "recovery", "reintegration", "closed"],
        )
        # Labels carried over from option_labels.
        self.assertEqual(stages[0], {"value": "injured", "label": "Lesionado", "kind": "open"})
        # Closed stage marked separately so the UI can color it differently.
        self.assertEqual(stages[-1]["kind"], "closed")
        self.assertEqual(payload["stage_field_key"], "stage")

    def test_non_episodic_template_returns_no_stages(self):
        non_episodic = ExamTemplate.objects.create(
            name="Plain", slug="plain", department=self.dept,
            config_schema={
                "fields": [
                    {
                        "key": "body_part", "type": "categorical",
                        "options": ["Cabeza"],
                        "option_regions": {"Cabeza": "head"},
                    },
                ],
            },
        )
        non_episodic.applicable_categories.add(self.cat)
        ExamResult.objects.create(
            player=self.player, template=non_episodic,
            recorded_at=timezone.now(),
            result_data={"body_part": "Cabeza"},
        )
        widget = _build_widget(non_episodic, ["body_part"])
        payload = resolve_widget(widget, self.player.id)
        self.assertEqual(payload["stages"], [])
        self.assertEqual(payload["stage_field_key"], "")
        self.assertEqual(payload["counts_by_stage"], {})

    def test_back_only_region_counted(self):
        # Espalda alta → upper_back exercises a back-only region.
        self._result("Espalda alta", "injured", days_ago=1)
        widget = _build_widget(self.template, ["body_part"])
        payload = resolve_widget(widget, self.player.id)
        self.assertEqual(payload["counts"], {"upper_back": 1})
        self.assertEqual(
            payload["counts_by_stage"], {"injured": {"upper_back": 1}},
        )


# =============================================================================
# Team aggregation — team_horizontal_comparison resolver
# =============================================================================

from .models import (
    Aggregation,
    TeamReportLayout,
    TeamReportSection,
    TeamReportWidget,
    TeamReportWidgetDataSource,
)
from .team_aggregation import resolve_team_widget


class TeamHorizontalComparisonTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Nutri", slug="nutri")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)

        self.alice = Player.objects.create(
            category=self.cat, first_name="Alice", last_name="A", is_active=True,
        )
        self.bob = Player.objects.create(
            category=self.cat, first_name="Bob", last_name="B", is_active=True,
        )
        self.cleo = Player.objects.create(
            category=self.cat, first_name="Cleo", last_name="C", is_active=True,
        )

        self.template = ExamTemplate.objects.create(
            name="Antropo", slug="antropo", department=self.dept,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
            ]},
        )
        self.template.applicable_categories.add(self.cat)

    def _build_widget(
        self,
        *,
        template=None,
        field_keys=("peso",),
        limit=3,
        attach_source=True,
    ) -> TeamReportWidget:
        layout = TeamReportLayout.objects.create(
            department=self.dept, category=self.cat,
        )
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_HORIZONTAL_COMPARISON.value,
            title="Peso — últimas 3",
        )
        if attach_source:
            TeamReportWidgetDataSource.objects.create(
                widget=widget,
                template=template or self.template,
                field_keys=list(field_keys),
                aggregation=Aggregation.LAST_N,
                aggregation_param=limit,
            )
        return widget

    def _result(self, player, peso, days_ago):
        return ExamResult.objects.create(
            player=player, template=self.template,
            recorded_at=timezone.now() - timedelta(days=days_ago),
            result_data={"peso": peso},
        )

    def test_happy_path_returns_last_n_per_player(self):
        # Alice: 4 readings — only most recent 3 should appear.
        self._result(self.alice, 70.0, 30)
        self._result(self.alice, 71.0, 20)
        self._result(self.alice, 72.0, 10)
        self._result(self.alice, 73.0, 1)
        # Bob: 2 readings — both appear.
        self._result(self.bob, 80.0, 15)
        self._result(self.bob, 81.0, 5)
        # Cleo: no readings.

        widget = self._build_widget(limit=3)
        payload = resolve_team_widget(widget, self.cat)

        self.assertEqual(payload["chart_type"], "team_horizontal_comparison")
        self.assertEqual(payload["fields"], [
            {"key": "peso", "label": "Peso", "unit": "kg"},
        ])
        self.assertEqual(payload["default_field_key"], "peso")
        self.assertFalse(payload["empty"])

        rows = {r["player_name"]: r for r in payload["rows"]}
        self.assertEqual(len(rows["Alice A"]["values"]["peso"]), 3)
        # Newest first: 73 (1d ago), 72 (10d), 71 (20d).
        self.assertEqual(
            [v["value"] for v in rows["Alice A"]["values"]["peso"]],
            [73.0, 72.0, 71.0],
        )
        self.assertEqual(
            [v["value"] for v in rows["Bob B"]["values"]["peso"]],
            [81.0, 80.0],
        )
        self.assertEqual(rows["Cleo C"]["values"]["peso"], [])

    def test_player_with_no_data_still_appears(self):
        # No results at all — every player should show up with empty values.
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertEqual(len(payload["rows"]), 3)
        for r in payload["rows"]:
            self.assertEqual(r["values"], {"peso": []})

    def test_widget_with_no_data_source_returns_helpful_error(self):
        widget = self._build_widget(attach_source=False)
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("Data Source", payload["error"])

    def test_data_source_with_no_field_keys_returns_helpful_error(self):
        widget = self._build_widget(field_keys=())
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("field_keys", payload["error"])

    def test_non_numeric_values_are_filtered(self):
        # A typo / categorical value sneaks into the result_data — resolver
        # should silently drop it from that player's bars.
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": "abc"},
        )
        self._result(self.bob, 80.0, 1)
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        rows = {r["player_name"]: r for r in payload["rows"]}
        self.assertEqual(rows["Alice A"]["values"]["peso"], [])
        self.assertEqual(
            [v["value"] for v in rows["Bob B"]["values"]["peso"]], [80.0],
        )

    def test_inactive_players_excluded(self):
        self.cleo.is_active = False
        self.cleo.save()
        self._result(self.alice, 70.0, 1)
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        names = {r["player_name"] for r in payload["rows"]}
        self.assertEqual(names, {"Alice A", "Bob B"})

    def test_multiple_field_keys_returned_for_selector(self):
        # Add a second numeric field on the template so we can configure two
        # field_keys and expect both back in `fields[]` + per-row values.
        self.template.config_schema = {"fields": [
            {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
            {"key": "altura", "type": "number", "label": "Altura", "unit": "cm"},
        ]}
        self.template.save()

        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now() - timedelta(days=2),
            result_data={"peso": 70.0, "altura": 175.0},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            # Second reading missing altura — should NOT pollute altura's bucket.
            result_data={"peso": 71.0},
        )

        widget = self._build_widget(field_keys=("peso", "altura"))
        payload = resolve_team_widget(widget, self.cat)

        self.assertEqual(
            payload["fields"],
            [
                {"key": "peso", "label": "Peso", "unit": "kg"},
                {"key": "altura", "label": "Altura", "unit": "cm"},
            ],
        )
        self.assertEqual(payload["default_field_key"], "peso")

        rows = {r["player_name"]: r for r in payload["rows"]}
        # Two peso readings (newest-first), one altura reading.
        self.assertEqual(
            [v["value"] for v in rows["Alice A"]["values"]["peso"]],
            [71.0, 70.0],
        )
        self.assertEqual(
            [v["value"] for v in rows["Alice A"]["values"]["altura"]],
            [175.0],
        )


# =============================================================================
# Team aggregation — team_roster_matrix resolver
# =============================================================================


class TeamRosterMatrixTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Nutri", slug="nutri")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)

        self.alice = Player.objects.create(
            category=self.cat, first_name="Alice", last_name="A", is_active=True,
        )
        self.bob = Player.objects.create(
            category=self.cat, first_name="Bob", last_name="B", is_active=True,
        )

        self.template = ExamTemplate.objects.create(
            name="Antropo", slug="antropo", department=self.dept,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
                {"key": "altura", "type": "number", "label": "Altura", "unit": "cm"},
                {"key": "imc", "type": "number", "label": "IMC", "unit": "kg/m²"},
            ]},
        )
        self.template.applicable_categories.add(self.cat)

    def _build_widget(
        self,
        *,
        field_keys=("peso", "altura", "imc"),
        coloring=None,
        variation=None,
        attach_source=True,
    ) -> TeamReportWidget:
        layout = TeamReportLayout.objects.create(
            department=self.dept, category=self.cat,
        )
        section = TeamReportSection.objects.create(layout=layout)
        cfg: dict = {}
        if coloring:
            cfg["coloring"] = coloring
        if variation:
            cfg["variation"] = variation
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_ROSTER_MATRIX.value,
            title="Plantel",
            display_config=cfg,
        )
        if attach_source:
            TeamReportWidgetDataSource.objects.create(
                widget=widget,
                template=self.template,
                field_keys=list(field_keys),
                aggregation=Aggregation.LAST_N,
                aggregation_param=1,
            )
        return widget

    def test_latest_value_per_field_is_returned(self):
        # Alice: 2 readings, latest peso=71, altura=175 (only set in older read).
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now() - timedelta(days=10),
            result_data={"peso": 70.0, "altura": 175.0, "imc": 22.9},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            # Recent reading: peso & imc updated, altura skipped.
            result_data={"peso": 71.0, "imc": 23.2},
        )
        ExamResult.objects.create(
            player=self.bob, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 80.0, "altura": 180.0, "imc": 24.7},
        )

        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)

        self.assertEqual(payload["chart_type"], "team_roster_matrix")
        self.assertEqual(
            [c["key"] for c in payload["columns"]],
            ["peso", "altura", "imc"],
        )
        self.assertFalse(payload["empty"])

        rows = {r["player_name"]: r for r in payload["rows"]}
        # Alice's altura should come from the older reading (latest didn't have it).
        self.assertEqual(rows["Alice A"]["cells"]["peso"]["value"], 71.0)
        self.assertEqual(rows["Alice A"]["cells"]["altura"]["value"], 175.0)
        self.assertEqual(rows["Alice A"]["cells"]["imc"]["value"], 23.2)
        # Bob: single reading, all fields present.
        self.assertEqual(rows["Bob B"]["cells"]["peso"]["value"], 80.0)

    def test_team_ranges_computed_per_field(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 70.0, "imc": 22.0},
        )
        ExamResult.objects.create(
            player=self.bob, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 85.0, "imc": 28.0},
        )
        widget = self._build_widget(field_keys=("peso", "imc"))
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["ranges"]["peso"], {"min": 70.0, "max": 85.0})
        self.assertEqual(payload["ranges"]["imc"], {"min": 22.0, "max": 28.0})

    def test_player_with_no_readings_appears_with_empty_cells(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 70.0},
        )
        # Bob: nothing.
        widget = self._build_widget(field_keys=("peso",))
        payload = resolve_team_widget(widget, self.cat)
        rows = {r["player_name"]: r for r in payload["rows"]}
        self.assertEqual(rows["Alice A"]["cells"]["peso"]["value"], 70.0)
        self.assertEqual(rows["Bob B"]["cells"], {})

    def test_field_missing_on_specific_player_is_omitted(self):
        # Alice has only peso, never altura — altura should be missing from
        # her cells entirely (the frontend renders these as "—").
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 70.0},
        )
        widget = self._build_widget(field_keys=("peso", "altura"))
        payload = resolve_team_widget(widget, self.cat)
        rows = {r["player_name"]: r for r in payload["rows"]}
        self.assertIn("peso", rows["Alice A"]["cells"])
        self.assertNotIn("altura", rows["Alice A"]["cells"])

    def test_coloring_display_config_propagates(self):
        widget = self._build_widget(coloring="vs_team_range")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["coloring"], "vs_team_range")

    def test_invalid_coloring_falls_back_to_none(self):
        widget = self._build_widget(coloring="rainbow_unicorn")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["coloring"], "none")

    def test_no_data_source_returns_helpful_error(self):
        widget = self._build_widget(attach_source=False)
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("Data Source", payload["error"])

    # ---- variation indicator -----------------------------------------------

    def test_variation_off_omits_previous_value(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now() - timedelta(days=10),
            result_data={"peso": 70.0},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 71.0},
        )
        widget = self._build_widget(field_keys=("peso",))  # no variation set
        payload = resolve_team_widget(widget, self.cat)
        rows = {r["player_name"]: r for r in payload["rows"]}
        cell = rows["Alice A"]["cells"]["peso"]
        self.assertEqual(cell["value"], 71.0)
        self.assertNotIn("previous_value", cell)
        self.assertEqual(payload["variation"], "off")

    def test_variation_absolute_includes_previous_value(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now() - timedelta(days=10),
            result_data={"peso": 70.0},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 71.5},
        )
        widget = self._build_widget(field_keys=("peso",), variation="absolute")
        payload = resolve_team_widget(widget, self.cat)
        rows = {r["player_name"]: r for r in payload["rows"]}
        cell = rows["Alice A"]["cells"]["peso"]
        self.assertEqual(cell["value"], 71.5)
        self.assertEqual(cell["previous_value"], 70.0)
        self.assertIn("previous_iso", cell)
        self.assertEqual(payload["variation"], "absolute")

    def test_variation_skips_readings_where_field_was_missing(self):
        # The "previous" reading for `peso` should come from the most recent
        # result that ACTUALLY had a numeric peso, not just the most recent
        # result. A reading where peso wasn't recorded shouldn't poison
        # the comparison.
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now() - timedelta(days=20),
            result_data={"peso": 70.0},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now() - timedelta(days=10),
            # No peso here.
            result_data={"altura": 175.0},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 72.0},
        )
        widget = self._build_widget(field_keys=("peso",), variation="absolute")
        payload = resolve_team_widget(widget, self.cat)
        cell = {r["player_name"]: r for r in payload["rows"]}["Alice A"]["cells"]["peso"]
        self.assertEqual(cell["value"], 72.0)
        self.assertEqual(cell["previous_value"], 70.0)

    def test_variation_with_only_one_reading_omits_previous(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 70.0},
        )
        widget = self._build_widget(field_keys=("peso",), variation="percent")
        payload = resolve_team_widget(widget, self.cat)
        cell = {r["player_name"]: r for r in payload["rows"]}["Alice A"]["cells"]["peso"]
        self.assertEqual(cell["value"], 70.0)
        self.assertNotIn("previous_value", cell)

    def test_invalid_variation_falls_back_to_off(self):
        widget = self._build_widget(variation="bonkers")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["variation"], "off")


# =============================================================================
# Team aggregation — team_status_counts resolver
# =============================================================================

from exams.models import Episode


class TeamStatusCountsTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Med", slug="med")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)

        self.alice = Player.objects.create(
            category=self.cat, first_name="Alice", last_name="A", is_active=True,
        )
        self.bob = Player.objects.create(
            category=self.cat, first_name="Bob", last_name="B", is_active=True,
        )
        self.cleo = Player.objects.create(
            category=self.cat, first_name="Cleo", last_name="C", is_active=True,
        )
        self.dan = Player.objects.create(
            category=self.cat, first_name="Dan", last_name="D", is_active=True,
        )

        self.template = ExamTemplate.objects.create(
            name="Lesiones", slug="lesiones", department=self.dept,
            is_episodic=True,
            episode_config={
                "stage_field": "stage",
                "open_stages": ["injured", "recovery", "reintegration"],
                "closed_stage": "closed",
            },
            config_schema={"fields": [
                {
                    "key": "stage", "type": "categorical",
                    "options": ["injured", "recovery", "reintegration", "closed"],
                    "option_labels": {
                        "injured": "Lesionado",
                        "recovery": "Recuperación",
                        "reintegration": "Reintegración",
                    },
                },
            ]},
        )
        self.template.applicable_categories.add(self.cat)

    def _build_widget(
        self,
        *,
        template=None,
        attach_source=True,
        display_config=None,
    ) -> TeamReportWidget:
        layout = TeamReportLayout.objects.create(
            department=self.dept, category=self.cat,
        )
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_STATUS_COUNTS.value,
            title="Disponibilidad",
            display_config=display_config or {},
        )
        if attach_source:
            TeamReportWidgetDataSource.objects.create(
                widget=widget,
                template=template or self.template,
                field_keys=[],
                aggregation=Aggregation.LATEST,
            )
        return widget

    def _open_episode(self, player, stage):
        return Episode.objects.create(
            player=player, template=self.template,
            status=Episode.STATUS_OPEN, stage=stage,
            started_at=timezone.now(),
        )

    def test_no_open_episodes_means_all_available(self):
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)

        self.assertEqual(payload["chart_type"], "team_status_counts")
        self.assertEqual(payload["total"], 4)
        self.assertEqual(payload["available_count"], 4)
        # `available` first, then injured / recovery / reintegration in
        # template-declared order.
        self.assertEqual(
            [s["value"] for s in payload["stages"]],
            ["available", "injured", "recovery", "reintegration"],
        )
        self.assertEqual(payload["stages"][0]["count"], 4)
        for s in payload["stages"][1:]:
            self.assertEqual(s["count"], 0)

    def test_open_episodes_bucket_players_by_stage(self):
        self._open_episode(self.alice, "injured")
        self._open_episode(self.bob, "reintegration")
        # Cleo + Dan: no open episodes → available.

        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)

        stages = {s["value"]: s for s in payload["stages"]}
        self.assertEqual(stages["available"]["count"], 2)
        self.assertEqual(stages["injured"]["count"], 1)
        self.assertEqual(stages["reintegration"]["count"], 1)
        self.assertEqual(stages["recovery"]["count"], 0)

        self.assertEqual(payload["available_count"], 2)
        self.assertEqual(payload["total"], 4)

        # Player names embedded in the buckets.
        self.assertEqual(
            [p["name"] for p in stages["injured"]["players"]], ["Alice A"],
        )
        self.assertEqual(
            sorted(p["name"] for p in stages["available"]["players"]),
            ["Cleo C", "Dan D"],
        )

    def test_closed_episodes_dont_affect_status(self):
        # Closed episodes are recovered → available; should be ignored.
        Episode.objects.create(
            player=self.alice, template=self.template,
            status=Episode.STATUS_CLOSED, stage="closed",
            started_at=timezone.now() - timedelta(days=30),
            ended_at=timezone.now() - timedelta(days=5),
        )
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        stages = {s["value"]: s for s in payload["stages"]}
        self.assertEqual(stages["available"]["count"], 4)

    def test_multiple_open_episodes_take_most_recent_started(self):
        # Alice has two concurrent open episodes — most recently started wins.
        Episode.objects.create(
            player=self.alice, template=self.template,
            status=Episode.STATUS_OPEN, stage="recovery",
            started_at=timezone.now() - timedelta(days=10),
        )
        Episode.objects.create(
            player=self.alice, template=self.template,
            status=Episode.STATUS_OPEN, stage="injured",
            started_at=timezone.now() - timedelta(days=1),
        )
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        stages = {s["value"]: s for s in payload["stages"]}
        self.assertEqual([p["name"] for p in stages["injured"]["players"]], ["Alice A"])
        self.assertEqual(stages["recovery"]["count"], 0)

    def test_inactive_players_excluded(self):
        self.cleo.is_active = False
        self.cleo.save()
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["total"], 3)
        # Cleo should not appear in any bucket.
        all_names: set[str] = set()
        for s in payload["stages"]:
            for p in s["players"]:
                all_names.add(p["name"])
        self.assertNotIn("Cleo C", all_names)

    def test_stage_labels_picked_up_from_option_labels(self):
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        labels = {s["value"]: s["label"] for s in payload["stages"]}
        self.assertEqual(labels["injured"], "Lesionado")
        self.assertEqual(labels["reintegration"], "Reintegración")
        # `available` falls back to the platform default when option_labels
        # doesn't declare it.
        self.assertEqual(labels["available"], "Disponible")

    def test_color_overrides_via_display_config(self):
        widget = self._build_widget(
            display_config={
                "stage_colors": {
                    "injured": "#000000",
                    "available": "#abcdef",
                },
            },
        )
        payload = resolve_team_widget(widget, self.cat)
        colors = {s["value"]: s["color"] for s in payload["stages"]}
        self.assertEqual(colors["injured"], "#000000")
        self.assertEqual(colors["available"], "#abcdef")
        # Non-overridden stages keep their default palette colors.
        self.assertTrue(colors["recovery"].startswith("#"))

    def test_non_episodic_template_returns_helpful_error(self):
        non_episodic = ExamTemplate.objects.create(
            name="Plain", slug="plain", department=self.dept,
            config_schema={"fields": [{"key": "x", "type": "number"}]},
        )
        non_episodic.applicable_categories.add(self.cat)
        widget = self._build_widget(template=non_episodic)
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("episódica", payload["error"])

    def test_no_data_source_returns_helpful_error(self):
        widget = self._build_widget(attach_source=False)
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("Data Source", payload["error"])


# =============================================================================
# Cross-cutting: position_id filter on team aggregation
# =============================================================================

from core.models import Position


class PositionFilterTests(TestCase):
    """Verifies the position filter narrows the roster across resolvers."""

    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="Nutri", slug="nutri")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)

        self.gk_pos = Position.objects.create(
            club=self.club, name="Arquero", abbreviation="GK",
        )
        self.def_pos = Position.objects.create(
            club=self.club, name="Defensor", abbreviation="DEF",
        )

        self.gk = Player.objects.create(
            category=self.cat, first_name="Goalie", last_name="One",
            position=self.gk_pos, is_active=True,
        )
        self.defender = Player.objects.create(
            category=self.cat, first_name="Defender", last_name="Two",
            position=self.def_pos, is_active=True,
        )
        # No-position player — should be excluded by any specific position filter.
        self.no_pos = Player.objects.create(
            category=self.cat, first_name="Nobody", last_name="Three",
            is_active=True,
        )

        self.template = ExamTemplate.objects.create(
            name="Antropo", slug="antropo", department=self.dept,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
            ]},
        )
        self.template.applicable_categories.add(self.cat)

        for player, peso in [(self.gk, 90.0), (self.defender, 78.0), (self.no_pos, 75.0)]:
            ExamResult.objects.create(
                player=player, template=self.template,
                recorded_at=timezone.now(),
                result_data={"peso": peso},
            )

    def _build_horizontal(self) -> TeamReportWidget:
        layout = TeamReportLayout.objects.create(
            department=self.dept, category=self.cat,
        )
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_HORIZONTAL_COMPARISON.value,
            title="W",
        )
        TeamReportWidgetDataSource.objects.create(
            widget=widget, template=self.template, field_keys=["peso"],
            aggregation=Aggregation.LAST_N, aggregation_param=1,
        )
        return widget

    def test_no_filter_returns_all_active_players(self):
        widget = self._build_horizontal()
        payload = resolve_team_widget(widget, self.cat)
        names = {r["player_name"] for r in payload["rows"]}
        self.assertEqual(names, {"Goalie One", "Defender Two", "Nobody Three"})

    def test_filter_narrows_to_one_position(self):
        widget = self._build_horizontal()
        payload = resolve_team_widget(widget, self.cat, position_id=self.gk_pos.id)
        names = {r["player_name"] for r in payload["rows"]}
        self.assertEqual(names, {"Goalie One"})

    def test_filter_excludes_players_without_position(self):
        # When a position is selected, players with NULL position must
        # not appear (they're not "at" that position).
        widget = self._build_horizontal()
        payload = resolve_team_widget(widget, self.cat, position_id=self.def_pos.id)
        names = {r["player_name"] for r in payload["rows"]}
        self.assertEqual(names, {"Defender Two"})

    def test_filter_propagates_to_roster_matrix(self):
        layout = TeamReportLayout.objects.create(
            department=self.dept, category=self.cat,
        )
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_ROSTER_MATRIX.value,
            title="M",
        )
        TeamReportWidgetDataSource.objects.create(
            widget=widget, template=self.template, field_keys=["peso"],
            aggregation=Aggregation.LATEST,
        )
        payload = resolve_team_widget(widget, self.cat, position_id=self.gk_pos.id)
        names = {r["player_name"] for r in payload["rows"]}
        self.assertEqual(names, {"Goalie One"})


# =============================================================================
# Cross-department template enforcement on TeamReportWidgetDataSource
# =============================================================================

from django.core.exceptions import ValidationError as _ValidationError


class CrossDepartmentTemplateTests(TestCase):
    """Mirrors the per-player WidgetDataSource validator: cross-department
    sources allowed only for chart types whose data shape doesn't depend on
    department-specific config (i.e. anything but team_status_counts)."""

    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.club_b = Club.objects.create(name="Other FC")

        self.dept_nutri = Department.objects.create(
            club=self.club, name="Nutri", slug="nutri",
        )
        self.dept_perf = Department.objects.create(
            club=self.club, name="Performance", slug="performance",
        )
        # A department in a DIFFERENT club — same-club rule should reject.
        self.dept_other_club = Department.objects.create(
            club=self.club_b, name="Med", slug="med",
        )

        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept_nutri, self.dept_perf)

        # Layout sits in nutri.
        self.layout = TeamReportLayout.objects.create(
            department=self.dept_nutri, category=self.cat,
        )
        self.section = TeamReportSection.objects.create(layout=self.layout)

        # A Performance template (DIFFERENT department from the layout).
        self.cross_template = ExamTemplate.objects.create(
            name="GPS", slug="gps", department=self.dept_perf,
            config_schema={"fields": [
                {"key": "distancia", "type": "number", "label": "Distancia"},
            ]},
        )
        # A template from a different club entirely — should always reject.
        self.foreign_template = ExamTemplate.objects.create(
            name="Foreign", slug="foreign", department=self.dept_other_club,
            config_schema={"fields": [
                {"key": "x", "type": "number", "label": "X"},
            ]},
        )

    def test_cross_department_allowed_for_horizontal_comparison(self):
        widget = TeamReportWidget.objects.create(
            section=self.section,
            chart_type=ChartType.TEAM_HORIZONTAL_COMPARISON.value,
            title="W",
        )
        source = TeamReportWidgetDataSource(
            widget=widget, template=self.cross_template,
            field_keys=["distancia"],
            aggregation=Aggregation.LAST_N, aggregation_param=3,
        )
        # Should NOT raise.
        source.full_clean()

    def test_cross_department_allowed_for_roster_matrix(self):
        widget = TeamReportWidget.objects.create(
            section=self.section,
            chart_type=ChartType.TEAM_ROSTER_MATRIX.value,
            title="W",
        )
        source = TeamReportWidgetDataSource(
            widget=widget, template=self.cross_template,
            field_keys=["distancia"],
            aggregation=Aggregation.LATEST,
        )
        source.full_clean()

    def test_cross_department_allowed_for_status_counts(self):
        # Squad availability in a Nutricional report ("who can train hard
        # tomorrow?") is a coherent narrative — should NOT reject.
        self.cross_template.is_episodic = True
        self.cross_template.episode_config = {
            "stage_field": "stage",
            "open_stages": ["a"],
            "closed_stage": "closed",
        }
        self.cross_template.config_schema = {"fields": [
            {"key": "stage", "type": "categorical", "options": ["a", "closed"]},
        ]}
        self.cross_template.save()

        widget = TeamReportWidget.objects.create(
            section=self.section,
            chart_type=ChartType.TEAM_STATUS_COUNTS.value,
            title="W",
        )
        source = TeamReportWidgetDataSource(
            widget=widget, template=self.cross_template,
            field_keys=["stage"],
            aggregation=Aggregation.LATEST,
        )
        # Should NOT raise.
        source.full_clean()

    def test_cross_club_rejected_even_for_allowlisted_chart(self):
        # Cross-department is OK; cross-CLUB never is, regardless of chart.
        widget = TeamReportWidget.objects.create(
            section=self.section,
            chart_type=ChartType.TEAM_HORIZONTAL_COMPARISON.value,
            title="W",
        )
        source = TeamReportWidgetDataSource(
            widget=widget, template=self.foreign_template,
            field_keys=["x"],
            aggregation=Aggregation.LAST_N, aggregation_param=3,
        )
        with self.assertRaises(_ValidationError):
            source.full_clean()


# =============================================================================
# Multi-source on team_horizontal_comparison
# =============================================================================


class HorizontalComparisonMultiSourceTests(TestCase):
    """Two data sources on the same widget should combine their field_keys
    into the dropdown. With multiple sources, keys are disambiguated as
    `{source_pk}__{field_key}` and labels include the template name."""

    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept_nutri = Department.objects.create(
            club=self.club, name="Nutri", slug="nutri",
        )
        self.dept_perf = Department.objects.create(
            club=self.club, name="Perf", slug="perf",
        )
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept_nutri, self.dept_perf)

        self.alice = Player.objects.create(
            category=self.cat, first_name="Alice", last_name="A", is_active=True,
        )

        self.template_nutri = ExamTemplate.objects.create(
            name="Antropo", slug="antropo", department=self.dept_nutri,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
            ]},
        )
        self.template_perf = ExamTemplate.objects.create(
            name="GPS", slug="gps", department=self.dept_perf,
            config_schema={"fields": [
                {"key": "distancia", "type": "number", "label": "Distancia", "unit": "m"},
            ]},
        )

        # Layout in nutri; second source pulls perf data (cross-department).
        self.layout = TeamReportLayout.objects.create(
            department=self.dept_nutri, category=self.cat,
        )
        section = TeamReportSection.objects.create(layout=self.layout)
        self.widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_HORIZONTAL_COMPARISON.value,
            title="Comparación múltiple",
        )
        self.source_nutri = TeamReportWidgetDataSource.objects.create(
            widget=self.widget, template=self.template_nutri,
            field_keys=["peso"],
            aggregation=Aggregation.LAST_N, aggregation_param=3,
            sort_order=0,
        )
        self.source_perf = TeamReportWidgetDataSource.objects.create(
            widget=self.widget, template=self.template_perf,
            field_keys=["distancia"],
            aggregation=Aggregation.LAST_N, aggregation_param=3,
            sort_order=1,
        )

    def test_fields_from_all_sources_appear_in_dropdown(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template_nutri,
            recorded_at=timezone.now(),
            result_data={"peso": 78.5},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template_perf,
            recorded_at=timezone.now(),
            result_data={"distancia": 9800.0},
        )

        payload = resolve_team_widget(self.widget, self.cat)
        # Two fields total — one per source.
        self.assertEqual(len(payload["fields"]), 2)

        labels = [f["label"] for f in payload["fields"]]
        # Labels should disambiguate by template name when multi-source.
        self.assertIn("Peso · Antropo", labels)
        self.assertIn("Distancia · GPS", labels)

    def test_keys_are_namespaced_when_multiple_sources(self):
        payload = resolve_team_widget(self.widget, self.cat)
        keys = [f["key"] for f in payload["fields"]]
        # Synthetic keys for multi-source: `{source_pk}__{field_key}`.
        self.assertEqual(
            keys,
            [
                f"{self.source_nutri.pk}__peso",
                f"{self.source_perf.pk}__distancia",
            ],
        )

    def test_values_keyed_by_synthetic_key_per_source(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template_nutri,
            recorded_at=timezone.now(),
            result_data={"peso": 78.5},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template_perf,
            recorded_at=timezone.now(),
            result_data={"distancia": 9800.0},
        )

        payload = resolve_team_widget(self.widget, self.cat)
        row = payload["rows"][0]
        peso_key = f"{self.source_nutri.pk}__peso"
        dist_key = f"{self.source_perf.pk}__distancia"

        self.assertEqual(row["values"][peso_key][0]["value"], 78.5)
        self.assertEqual(row["values"][dist_key][0]["value"], 9800.0)

    def test_default_field_key_is_first_sources_first_field(self):
        payload = resolve_team_widget(self.widget, self.cat)
        # Sort by source.sort_order is preserved; nutri (sort_order=0) comes first.
        self.assertEqual(
            payload["default_field_key"],
            f"{self.source_nutri.pk}__peso",
        )

    def test_collision_safe_when_two_sources_share_a_field_key(self):
        # Both templates have a `peso` key (e.g. cross-department weight
        # measurements). Synthetic keys must keep them distinct.
        self.template_perf.config_schema = {"fields": [
            {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
        ]}
        self.template_perf.save()
        self.source_perf.field_keys = ["peso"]
        self.source_perf.save()

        ExamResult.objects.create(
            player=self.alice, template=self.template_nutri,
            recorded_at=timezone.now(),
            result_data={"peso": 78.5},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template_perf,
            recorded_at=timezone.now(),
            result_data={"peso": 80.0},
        )

        payload = resolve_team_widget(self.widget, self.cat)
        keys = [f["key"] for f in payload["fields"]]
        # Two distinct keys despite the same field_key on both sources.
        self.assertEqual(len(set(keys)), 2)
        row = payload["rows"][0]
        # Each synthetic key carries its OWN source's value, no collision.
        self.assertEqual(
            row["values"][f"{self.source_nutri.pk}__peso"][0]["value"], 78.5,
        )
        self.assertEqual(
            row["values"][f"{self.source_perf.pk}__peso"][0]["value"], 80.0,
        )


# =============================================================================
# Multi-source on team_roster_matrix
# =============================================================================


class RosterMatrixMultiSourceTests(TestCase):
    """Two data sources on a roster_matrix should produce one column per
    (source, field_key). Synthetic keys disambiguate same-named fields."""

    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept_n = Department.objects.create(club=self.club, name="N", slug="n")
        self.dept_p = Department.objects.create(club=self.club, name="P", slug="p")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept_n, self.dept_p)

        self.alice = Player.objects.create(
            category=self.cat, first_name="Alice", last_name="A", is_active=True,
        )

        self.tn = ExamTemplate.objects.create(
            name="Antropo", slug="antropo", department=self.dept_n,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
            ]},
        )
        self.tp = ExamTemplate.objects.create(
            name="GPS", slug="gps", department=self.dept_p,
            config_schema={"fields": [
                {"key": "distancia", "type": "number", "label": "Distancia", "unit": "m"},
            ]},
        )

        self.layout = TeamReportLayout.objects.create(
            department=self.dept_n, category=self.cat,
        )
        section = TeamReportSection.objects.create(layout=self.layout)
        self.widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_ROSTER_MATRIX.value,
            title="Mixed",
        )
        self.s_n = TeamReportWidgetDataSource.objects.create(
            widget=self.widget, template=self.tn,
            field_keys=["peso"], aggregation=Aggregation.LATEST, sort_order=0,
        )
        self.s_p = TeamReportWidgetDataSource.objects.create(
            widget=self.widget, template=self.tp,
            field_keys=["distancia"], aggregation=Aggregation.LATEST, sort_order=1,
        )

    def test_columns_from_all_sources(self):
        ExamResult.objects.create(
            player=self.alice, template=self.tn,
            recorded_at=timezone.now(),
            result_data={"peso": 78.5},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.tp,
            recorded_at=timezone.now(),
            result_data={"distancia": 9800.0},
        )
        payload = resolve_team_widget(self.widget, self.cat)
        keys = [c["key"] for c in payload["columns"]]
        self.assertEqual(
            keys,
            [f"{self.s_n.pk}__peso", f"{self.s_p.pk}__distancia"],
        )
        labels = [c["label"] for c in payload["columns"]]
        self.assertIn("Peso · Antropo", labels)
        self.assertIn("Distancia · GPS", labels)

        cells = payload["rows"][0]["cells"]
        self.assertEqual(cells[f"{self.s_n.pk}__peso"]["value"], 78.5)
        self.assertEqual(cells[f"{self.s_p.pk}__distancia"]["value"], 9800.0)

    def test_collision_safe_when_two_sources_share_a_field_key(self):
        # Both templates have a `peso` field — synthetic keys must disambiguate.
        self.tp.config_schema = {"fields": [
            {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
        ]}
        self.tp.save()
        self.s_p.field_keys = ["peso"]
        self.s_p.save()

        ExamResult.objects.create(
            player=self.alice, template=self.tn,
            recorded_at=timezone.now(),
            result_data={"peso": 78.5},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.tp,
            recorded_at=timezone.now(),
            result_data={"peso": 80.0},
        )
        payload = resolve_team_widget(self.widget, self.cat)
        keys = [c["key"] for c in payload["columns"]]
        self.assertEqual(len(set(keys)), 2)
        cells = payload["rows"][0]["cells"]
        self.assertEqual(cells[f"{self.s_n.pk}__peso"]["value"], 78.5)
        self.assertEqual(cells[f"{self.s_p.pk}__peso"]["value"], 80.0)


# =============================================================================
# Team aggregation — team_trend_line resolver
# =============================================================================


class TeamTrendLineTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="N", slug="n")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.alice = Player.objects.create(
            category=self.cat, first_name="Alice", last_name="A", is_active=True,
        )
        self.bob = Player.objects.create(
            category=self.cat, first_name="Bob", last_name="B", is_active=True,
        )
        self.template = ExamTemplate.objects.create(
            name="Antropo", slug="antropo", department=self.dept,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
                {"key": "imc", "type": "number", "label": "IMC", "unit": "kg/m²"},
            ]},
        )

    def _build_widget(self, *, field_keys=("peso",), bucket_size=None) -> TeamReportWidget:
        layout = TeamReportLayout.objects.create(department=self.dept, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_TREND_LINE.value,
            title="Trend",
            display_config={"bucket_size": bucket_size} if bucket_size else {},
        )
        TeamReportWidgetDataSource.objects.create(
            widget=widget, template=self.template,
            field_keys=list(field_keys), aggregation=Aggregation.ALL,
        )
        return widget

    def test_weekly_buckets_average_across_roster(self):
        # Two readings in the same week from different players → averaged.
        ref = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=ref - timedelta(days=14),
            result_data={"peso": 70.0},
        )
        ExamResult.objects.create(
            player=self.bob, template=self.template,
            recorded_at=ref - timedelta(days=14),
            result_data={"peso": 80.0},
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=ref - timedelta(days=1),
            result_data={"peso": 71.0},
        )

        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["bucket_size"], "week")
        self.assertEqual(len(payload["buckets"]), 2)
        # Earliest bucket: average of 70 and 80 = 75.
        self.assertEqual(payload["buckets"][0]["values"]["peso"], 75.0)
        # Most recent bucket: just Alice = 71.
        self.assertEqual(payload["buckets"][-1]["values"]["peso"], 71.0)

    def test_monthly_bucketing_when_configured(self):
        ref = timezone.now().replace(day=15, hour=12)
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=ref,
            result_data={"peso": 70.0},
        )
        widget = self._build_widget(bucket_size="month")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["bucket_size"], "month")
        self.assertEqual(len(payload["buckets"]), 1)
        self.assertEqual(payload["buckets"][0]["values"]["peso"], 70.0)

    def test_invalid_bucket_size_falls_back_to_week(self):
        widget = self._build_widget(bucket_size="decade")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["bucket_size"], "week")

    def test_no_data_source_returns_helpful_error(self):
        layout = TeamReportLayout.objects.create(department=self.dept, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_TREND_LINE.value,
            title="W",
        )
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("Data Source", payload["error"])

    def test_multiple_fields_become_selectable_series(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 70.0, "imc": 22.0},
        )
        widget = self._build_widget(field_keys=("peso", "imc"))
        payload = resolve_team_widget(widget, self.cat)
        keys = [f["key"] for f in payload["fields"]]
        self.assertEqual(keys, ["peso", "imc"])
        self.assertEqual(payload["default_field_key"], "peso")
        bucket = payload["buckets"][0]
        self.assertEqual(bucket["values"]["peso"], 70.0)
        self.assertEqual(bucket["values"]["imc"], 22.0)


# =============================================================================
# Team aggregation — team_distribution resolver
# =============================================================================


class TeamDistributionTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="N", slug="n")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.players = [
            Player.objects.create(
                category=self.cat, first_name=f"P{i}", last_name="L",
                is_active=True,
            )
            for i in range(5)
        ]
        self.template = ExamTemplate.objects.create(
            name="Antropo", slug="antropo", department=self.dept,
            config_schema={"fields": [
                {"key": "peso", "type": "number", "label": "Peso", "unit": "kg"},
            ]},
        )

    def _build_widget(self, *, bin_count=None) -> TeamReportWidget:
        layout = TeamReportLayout.objects.create(department=self.dept, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_DISTRIBUTION.value,
            title="Dist",
            display_config={"bin_count": bin_count} if bin_count else {},
        )
        TeamReportWidgetDataSource.objects.create(
            widget=widget, template=self.template,
            field_keys=["peso"], aggregation=Aggregation.LATEST,
        )
        return widget

    def test_distributes_latest_values_into_bins(self):
        # 5 players, weights spread 70 → 90.
        for i, p in enumerate(self.players):
            ExamResult.objects.create(
                player=p, template=self.template,
                recorded_at=timezone.now(),
                result_data={"peso": 70 + i * 5},  # 70, 75, 80, 85, 90
            )
        widget = self._build_widget(bin_count=5)
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["bin_count"], 5)
        self.assertEqual(payload["stats"]["min"], 70.0)
        self.assertEqual(payload["stats"]["max"], 90.0)
        self.assertEqual(payload["stats"]["n"], 5)
        self.assertEqual(payload["stats"]["median"], 80.0)
        # Sum of bin counts == n.
        self.assertEqual(sum(b["count"] for b in payload["bins"]), 5)
        # Max value lands in the last bin (last bin is inclusive of `hi`).
        self.assertGreaterEqual(payload["bins"][-1]["count"], 1)

    def test_uses_latest_value_per_player(self):
        # Two readings — latest 80 should be binned, earlier 60 ignored.
        ExamResult.objects.create(
            player=self.players[0], template=self.template,
            recorded_at=timezone.now() - timedelta(days=10),
            result_data={"peso": 60.0},
        )
        ExamResult.objects.create(
            player=self.players[0], template=self.template,
            recorded_at=timezone.now(),
            result_data={"peso": 80.0},
        )
        widget = self._build_widget(bin_count=5)
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["stats"]["n"], 1)
        self.assertEqual(payload["stats"]["min"], 80.0)
        self.assertEqual(payload["stats"]["max"], 80.0)

    def test_empty_when_no_readings(self):
        widget = self._build_widget()
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])

    def test_no_data_source_returns_helpful_error(self):
        layout = TeamReportLayout.objects.create(department=self.dept, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_DISTRIBUTION.value,
            title="W",
        )
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("Data Source", payload["error"])

    def test_invalid_bin_count_clamped(self):
        for p in self.players:
            ExamResult.objects.create(
                player=p, template=self.template,
                recorded_at=timezone.now(),
                result_data={"peso": 70.0},
            )
        widget = self._build_widget(bin_count=99)
        payload = resolve_team_widget(widget, self.cat)
        self.assertLessEqual(payload["bin_count"], 30)

    def test_no_band_overlay_when_field_has_no_reference_ranges(self):
        # The default template in setUp() has no reference_ranges. Verify
        # we don't emit `band_counts` and bins don't carry a `color`.
        for i, p in enumerate(self.players):
            ExamResult.objects.create(
                player=p, template=self.template,
                recorded_at=timezone.now(),
                result_data={"peso": 70 + i * 2},
            )
        widget = self._build_widget(bin_count=5)
        payload = resolve_team_widget(widget, self.cat)
        self.assertNotIn("band_counts", payload)
        for b in payload["bins"]:
            self.assertNotIn("color", b)
            self.assertNotIn("band_label", b)

    def test_band_overlay_colors_bins_and_emits_counts(self):
        # Reseed the template with reference_ranges on `peso`.
        self.template.config_schema = {
            "fields": [
                {
                    "key": "peso", "type": "number", "label": "Peso", "unit": "kg",
                    "reference_ranges": [
                        {"label": "Bajo",   "max": 75,            "color": "#16a34a"},
                        {"label": "Normal", "min": 75, "max": 85, "color": "#86efac"},
                        {"label": "Alto",   "min": 85,            "color": "#dc2626"},
                    ],
                }
            ]
        }
        self.template.save(update_fields=["config_schema"])

        # Five players, weights 70-90 stepping 5. Bands:
        #   70 → Bajo, 75 → Bajo (boundary lands in lower band by
        #                         first-match-wins), 80 → Normal,
        #   85 → Normal (boundary), 90 → Alto.
        for i, p in enumerate(self.players):
            ExamResult.objects.create(
                player=p, template=self.template,
                recorded_at=timezone.now(),
                result_data={"peso": 70 + i * 5},
            )

        widget = self._build_widget(bin_count=5)
        payload = resolve_team_widget(widget, self.cat)

        # band_counts present, ordered as declared, every band has a count.
        counts = payload["band_counts"]
        self.assertEqual(len(counts), 3)
        labels = [c["label"] for c in counts]
        self.assertEqual(labels, ["Bajo", "Normal", "Alto"])
        by_label = {c["label"]: c["count"] for c in counts}
        # Sum equals N — every player landed in a band.
        self.assertEqual(sum(by_label.values()), 5)
        # Bajo gets {70, 75}, Normal gets {80, 85}, Alto gets {90}.
        self.assertEqual(by_label, {"Bajo": 2, "Normal": 2, "Alto": 1})

        # Every bin now carries a color matching one of the configured bands.
        configured_colors = {"#16a34a", "#86efac", "#dc2626"}
        for b in payload["bins"]:
            self.assertIn("color", b)
            self.assertIn(b["color"], configured_colors)
            self.assertIn("band_label", b)

    def test_coloring_none_disables_band_overlay(self):
        # Same band config, but display_config.coloring="none" should
        # suppress band_counts and per-bin colors.
        self.template.config_schema = {
            "fields": [
                {
                    "key": "peso", "type": "number", "label": "Peso", "unit": "kg",
                    "reference_ranges": [
                        {"label": "Bajo",   "max": 75,            "color": "#16a34a"},
                        {"label": "Normal", "min": 75,            "color": "#86efac"},
                    ],
                }
            ]
        }
        self.template.save(update_fields=["config_schema"])
        for i, p in enumerate(self.players):
            ExamResult.objects.create(
                player=p, template=self.template,
                recorded_at=timezone.now(),
                result_data={"peso": 70 + i * 5},
            )

        layout = TeamReportLayout.objects.create(department=self.dept, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_DISTRIBUTION.value,
            title="Dist",
            display_config={"bin_count": 5, "coloring": "none"},
        )
        TeamReportWidgetDataSource.objects.create(
            widget=widget, template=self.template,
            field_keys=["peso"], aggregation=Aggregation.LATEST,
        )

        payload = resolve_team_widget(widget, self.cat)
        self.assertNotIn("band_counts", payload)
        for b in payload["bins"]:
            self.assertNotIn("color", b)


# =============================================================================
# Team aggregation — team_active_records resolver
# =============================================================================


class TeamActiveRecordsTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Test FC")
        self.dept = Department.objects.create(club=self.club, name="M", slug="m")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept)
        self.alice = Player.objects.create(
            category=self.cat, first_name="Alice", last_name="A", is_active=True,
        )
        self.bob = Player.objects.create(
            category=self.cat, first_name="Bob", last_name="B", is_active=True,
        )
        self.template = ExamTemplate.objects.create(
            name="Medicación", slug="medicacion", department=self.dept,
            config_schema={"fields": [
                {"key": "medicamento", "type": "categorical", "label": "Medicamento"},
                {"key": "dosis", "type": "text", "label": "Dosis"},
                {"key": "fecha_inicio", "type": "date", "label": "Inicio"},
                {"key": "fecha_fin", "type": "date", "label": "Fin"},
            ]},
        )

    def _build_widget(self, *, field_keys=("medicamento", "dosis"), as_of=None) -> TeamReportWidget:
        layout = TeamReportLayout.objects.create(department=self.dept, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        cfg: dict = {}
        if as_of:
            cfg["as_of"] = as_of
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_ACTIVE_RECORDS.value,
            title="Active",
            display_config=cfg,
        )
        TeamReportWidgetDataSource.objects.create(
            widget=widget, template=self.template,
            field_keys=list(field_keys), aggregation=Aggregation.LATEST,
        )
        return widget

    def test_open_ended_record_is_active(self):
        # Started yesterday, no end date → active today.
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={
                "medicamento": "Paracetamol",
                "dosis": "500mg c/8h",
                "fecha_inicio": "2026-05-01",
            },
        )
        widget = self._build_widget(as_of="2026-05-03")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["active_count"], 1)
        self.assertEqual(payload["rows"][0]["player_name"], "Alice A")
        self.assertEqual(payload["rows"][0]["values"]["medicamento"], "Paracetamol")
        self.assertIsNone(payload["rows"][0]["ends_at"])

    def test_record_within_range_is_active(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={
                "medicamento": "Ibuprofeno",
                "fecha_inicio": "2026-05-01",
                "fecha_fin": "2026-05-10",
            },
        )
        widget = self._build_widget(as_of="2026-05-05")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["active_count"], 1)
        self.assertEqual(payload["rows"][0]["ends_at"], "2026-05-10")

    def test_expired_record_excluded(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={
                "medicamento": "Ibuprofeno",
                "fecha_inicio": "2026-04-01",
                "fecha_fin": "2026-04-05",
            },
        )
        widget = self._build_widget(as_of="2026-05-03")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["active_count"], 0)
        self.assertEqual(payload["total"], 2)  # roster intact

    def test_future_record_excluded(self):
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={
                "medicamento": "Future",
                "fecha_inicio": "2027-01-01",
            },
        )
        widget = self._build_widget(as_of="2026-05-03")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["active_count"], 0)

    def test_latest_record_per_player_wins(self):
        # Older one expired; newer one active — should pick the newer.
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now() - timedelta(days=30),
            result_data={
                "medicamento": "Old",
                "fecha_inicio": "2026-03-01",
                "fecha_fin": "2026-03-10",
            },
        )
        ExamResult.objects.create(
            player=self.alice, template=self.template,
            recorded_at=timezone.now(),
            result_data={
                "medicamento": "New",
                "fecha_inicio": "2026-05-01",
            },
        )
        widget = self._build_widget(as_of="2026-05-03")
        payload = resolve_team_widget(widget, self.cat)
        self.assertEqual(payload["active_count"], 1)
        self.assertEqual(payload["rows"][0]["values"]["medicamento"], "New")

    def test_no_data_source_returns_helpful_error(self):
        layout = TeamReportLayout.objects.create(department=self.dept, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        widget = TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_ACTIVE_RECORDS.value,
            title="W",
        )
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertIn("Data Source", payload["error"])


# =============================================================================
# player_alerts + team_alerts resolvers
# =============================================================================


def _make_banded_template_for_alerts(department, *, field_key="valor"):
    """Helper: template with reference_ranges including a red band."""
    return ExamTemplate.objects.create(
        name=f"T-{department.slug}",
        slug=f"t-{department.slug}",
        department=department,
        config_schema={
            "fields": [{
                "key": field_key, "label": "Valor", "type": "number", "unit": "U",
                "reference_ranges": [
                    {"label": "OK",      "max": 100, "color": "#16a34a"},
                    {"label": "Elevado", "min": 100, "color": "#dc2626"},
                ],
            }],
        },
    )


class PlayerAlertsResolverTests(TestCase):
    """Coverage for `_resolve_player_alerts`. Department scoping is the
    interesting behavior — every other branch is glue."""

    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.medico = Department.objects.create(club=self.club, name="Médico", slug="medico")
        self.nutri = Department.objects.create(club=self.club, name="Nutri", slug="nutri")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.medico, self.nutri)
        self.player = Player.objects.create(
            category=self.cat, first_name="Juan", last_name="P", is_active=True,
        )

        # Two banded templates: one per department, each with a BAND rule
        # that fires when value lands in the red band.
        self.t_medico = _make_banded_template_for_alerts(self.medico)
        self.t_medico.applicable_categories.add(self.cat)
        self.t_nutri = _make_banded_template_for_alerts(self.nutri)
        self.t_nutri.applicable_categories.add(self.cat)

        from goals.models import AlertRule, AlertRuleKind, AlertSeverity
        AlertRule.objects.create(
            template=self.t_medico, field_key="valor",
            kind=AlertRuleKind.BAND, config={}, severity=AlertSeverity.CRITICAL,
        )
        AlertRule.objects.create(
            template=self.t_nutri, field_key="valor",
            kind=AlertRuleKind.BAND, config={}, severity=AlertSeverity.CRITICAL,
        )

        # Both templates get a red-band reading → both should fire alerts.
        ExamResult.objects.create(
            player=self.player, template=self.t_medico,
            recorded_at=timezone.now(),
            result_data={"valor": 150},  # red
        )
        ExamResult.objects.create(
            player=self.player, template=self.t_nutri,
            recorded_at=timezone.now(),
            result_data={"valor": 150},  # red
        )

    def _widget_for_department(self, department):
        layout = DepartmentLayout.objects.create(department=department, category=self.cat)
        section = LayoutSection.objects.create(layout=layout)
        widget = Widget.objects.create(
            section=section,
            chart_type=ChartType.PLAYER_ALERTS.value,
            title="Alertas",
        )
        return widget

    def test_returns_only_alerts_from_same_department(self):
        widget = self._widget_for_department(self.medico)
        payload = resolve_widget(widget, self.player.id)
        self.assertEqual(payload["total"], 1)
        only = payload["alerts"][0]
        self.assertEqual(only["template_name"], self.t_medico.name)
        self.assertEqual(only["severity"], "critical")
        # And the nutri template's alert is NOT in this department payload.
        for a in payload["alerts"]:
            self.assertNotEqual(a["template_name"], self.t_nutri.name)

    def test_empty_when_no_alerts_in_department(self):
        # Fresh department layout has alerts, but if we create a 3rd dept
        # with no rules / no alerts, the resolver returns empty.
        other = Department.objects.create(club=self.club, name="Otro", slug="otro")
        self.cat.departments.add(other)
        widget = self._widget_for_department(other)
        payload = resolve_widget(widget, self.player.id)
        self.assertTrue(payload["empty"])
        self.assertEqual(payload["total"], 0)

    def test_dismissed_alerts_excluded(self):
        from goals.models import Alert, AlertStatus
        Alert.objects.filter(player=self.player).update(status=AlertStatus.DISMISSED)
        widget = self._widget_for_department(self.medico)
        payload = resolve_widget(widget, self.player.id)
        self.assertTrue(payload["empty"])


class TeamAlertsResolverTests(TestCase):
    """Coverage for `_resolve_team_alerts`. Ranking + department scoping."""

    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.dept = Department.objects.create(club=self.club, name="Nutri", slug="nutri")
        self.other_dept = Department.objects.create(club=self.club, name="Otro", slug="otro")
        self.cat = Category.objects.create(club=self.club, name="A")
        self.cat.departments.add(self.dept, self.other_dept)
        self.template = _make_banded_template_for_alerts(self.dept)
        self.template.applicable_categories.add(self.cat)

        from goals.models import AlertRule, AlertRuleKind, AlertSeverity
        AlertRule.objects.create(
            template=self.template, field_key="valor",
            kind=AlertRuleKind.BAND, config={}, severity=AlertSeverity.CRITICAL,
        )

        self.heavy = Player.objects.create(
            category=self.cat, first_name="Heavy", last_name="A", is_active=True,
        )
        self.light = Player.objects.create(
            category=self.cat, first_name="Light", last_name="B", is_active=True,
        )
        self.safe = Player.objects.create(
            category=self.cat, first_name="Safe", last_name="C", is_active=True,
        )

        # heavy: 2 alerts (older + newer reading both red → resolver fires
        # once and refreshes via _upsert_alert; effectively 1 alert per
        # rule per player). To get TWO alerts on heavy we add another
        # template+rule below.
        ExamResult.objects.create(
            player=self.heavy, template=self.template,
            recorded_at=timezone.now(),
            result_data={"valor": 150},
        )
        ExamResult.objects.create(
            player=self.light, template=self.template,
            recorded_at=timezone.now(),
            result_data={"valor": 130},
        )
        ExamResult.objects.create(
            player=self.safe, template=self.template,
            recorded_at=timezone.now(),
            result_data={"valor": 50},  # safe — no alert
        )
        # Second template & rule in the SAME department to give heavy 2 alerts.
        second_template = _make_banded_template_for_alerts(self.dept, field_key="otro")
        second_template.applicable_categories.add(self.cat)
        AlertRule.objects.create(
            template=second_template, field_key="otro",
            kind=AlertRuleKind.BAND, config={}, severity=AlertSeverity.CRITICAL,
        )
        ExamResult.objects.create(
            player=self.heavy, template=second_template,
            recorded_at=timezone.now(),
            result_data={"otro": 150},
        )

    def _team_widget(self, department):
        layout = TeamReportLayout.objects.create(department=department, category=self.cat)
        section = TeamReportSection.objects.create(layout=layout)
        return TeamReportWidget.objects.create(
            section=section,
            chart_type=ChartType.TEAM_ALERTS.value,
            title="Alertas equipo",
        )

    def test_ranks_players_by_critical_count(self):
        widget = self._team_widget(self.dept)
        payload = resolve_team_widget(widget, self.cat)
        self.assertFalse(payload["empty"])
        names = [c["player_name"] for c in payload["players"]]
        # heavy has 2 critical → first. light has 1. safe has 0 → not listed.
        self.assertEqual(names[0], "Heavy A")
        self.assertEqual(names[1], "Light B")
        self.assertNotIn("Safe C", names)

    def test_other_department_widget_excludes_alerts_from_this_dept(self):
        # The same alerts exist, but the widget lives in a different
        # department's layout — payload should be empty.
        widget = self._team_widget(self.other_dept)
        payload = resolve_team_widget(widget, self.cat)
        self.assertTrue(payload["empty"])
        self.assertEqual(payload["total_alerts"], 0)

    def test_alert_count_and_max_severity(self):
        widget = self._team_widget(self.dept)
        payload = resolve_team_widget(widget, self.cat)
        heavy_card = next(c for c in payload["players"] if c["player_name"] == "Heavy A")
        self.assertEqual(heavy_card["alert_count"], 2)
        self.assertEqual(heavy_card["critical_count"], 2)
        self.assertEqual(heavy_card["max_severity"], "critical")
