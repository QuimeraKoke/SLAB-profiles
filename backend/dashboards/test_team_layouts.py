"""Several team layouts per (department, category): resolution, CRUD, promote."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from ninja.errors import HttpError

from core.models import Category, Club, Department
from dashboards.models import TeamReportLayout, TeamReportSection


class TeamLayoutsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="FC")
        cls.med = Department.objects.create(club=cls.club, name="Médico", slug="medico")
        cls.cat = Category.objects.create(club=cls.club, name="Primer Equipo")
        cls.su = get_user_model().objects.create_superuser("su", "su@x.com", "x")

    def setUp(self):
        self.general = TeamReportLayout.objects.create(department=self.med, category=self.cat,
                                                       name="General", sort_order=0)
        TeamReportSection.objects.create(layout=self.general, title="Resumen", sort_order=0)

    def req(self):
        r = RequestFactory().get("/x")
        r.user = self.su
        return r

    def report(self, slug=None):
        from api.routers import get_team_report

        return get_team_report(self.req(), department_slug="medico",
                               category_id=str(self.cat.id), layout=slug)

    def test_un_solo_layout_se_ve_como_siempre(self):
        out = self.report()
        self.assertEqual(out["layout"]["slug"], "general")
        self.assertEqual([l["slug"] for l in out["layouts"]], ["general"])

    def test_crear_resolver_por_slug_y_el_primero_es_el_default(self):
        from api.routers import TeamLayoutCreateIn, create_team_layout

        nuevo = create_team_layout(self.req(), "medico",
                                   TeamLayoutCreateIn(category_id=self.cat.id, name="Lesiones"))
        self.assertEqual(nuevo["slug"], "lesiones")
        self.assertEqual(self.report("lesiones")["layout"]["name"], "Lesiones")
        self.assertEqual(self.report()["layout"]["slug"], "general", "sin slug, el primero")
        self.assertIsNone(self.report("no-existe")["layout"])

    def test_nombre_repetido_se_rechaza(self):
        from api.routers import TeamLayoutCreateIn, create_team_layout

        with self.assertRaises(HttpError):
            create_team_layout(self.req(), "medico",
                               TeamLayoutCreateIn(category_id=self.cat.id, name="general"))

    def test_renombrar_mueve_el_slug_y_reordenar_cambia_el_default(self):
        from api.routers import (TeamLayoutPatchIn, TeamLayoutReorderIn, rename_team_layout,
                                 reorder_team_layouts)

        otro = TeamReportLayout.objects.create(department=self.med, category=self.cat,
                                               name="Lesiones", sort_order=1)
        r = rename_team_layout(self.req(), otro.id, TeamLayoutPatchIn(name="Lesiones 2026"))
        self.assertEqual(r["slug"], "lesiones-2026")
        reorder_team_layouts(self.req(), TeamLayoutReorderIn(layout_ids=[otro.id, self.general.id]))
        self.assertEqual(self.report()["layout"]["name"], "Lesiones 2026")

    def test_no_se_puede_borrar_el_ultimo(self):
        from api.routers import delete_team_layout

        with self.assertRaises(HttpError) as ctx:
            delete_team_layout(self.req(), self.general.id)
        self.assertIn("única vista", str(ctx.exception))
        otro = TeamReportLayout.objects.create(department=self.med, category=self.cat, name="Otra")
        delete_team_layout(self.req(), otro.id)
        self.assertFalse(TeamReportLayout.objects.filter(pk=otro.pk).exists())

    def test_promover_va_a_la_vista_elegida(self):
        from dashboards.chart_spec import promote_chart_spec

        from exams.models import ExamTemplate

        t = ExamTemplate.objects.create(name="CK", slug="ck", department=self.med, config_schema={
            "fields": [{"key": "ck", "label": "CK", "type": "number", "chart_type": "line"}]})
        t.applicable_categories.add(self.cat)
        les = TeamReportLayout.objects.create(department=self.med, category=self.cat,
                                              name="Lesiones", sort_order=1)
        spec = {"chart_type": "team_trend_line", "title": "CK",
                "sources": [{"template_slug": "ck", "field_keys": ["ck"], "aggregation": "all"}]}
        out = promote_chart_spec(category=self.cat, department=self.med, spec=spec, layout_id=les.id)
        self.assertNotIn("error", out, out.get("error"))
        self.assertEqual(str(out["layout_id"]), str(les.id), "a la vista que se estaba mirando")
        sin = promote_chart_spec(category=self.cat, department=self.med, spec=spec)
        self.assertEqual(str(sin["layout_id"]), str(self.general.id), "sin vista: la de por defecto")

    def test_el_slug_es_unico_dentro_del_departamento(self):
        a = TeamReportLayout.objects.create(department=self.med, category=self.cat, name="Lesiones")
        b = TeamReportLayout.objects.create(department=self.med, category=self.cat, name="Lesiones")
        self.assertEqual((a.slug, b.slug), ("lesiones", "lesiones-2"))
