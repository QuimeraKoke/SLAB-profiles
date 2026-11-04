"""SLAB Admin — clubs from the Base template (`core.club_setup`, `/platform/*`).

Pins: a new club gets the three departments, the positions and the base exams,
every category sees all of them; applying the template again creates only
what's missing and never refreshes what the club already has; a later category
copies its sibling; and only superusers get in.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase

from api.auth import issue_token
from core import club_setup
from core.models import Category, Club, Player, Position, StaffMembership
from exams.models import ExamTemplate

User = get_user_model()

BASE_EXAMS = {
    "medico": {"notas_diarias_medico"},
    "fisico": {"notas_diarias_fisico", "gps_partido", "gps_sesion"},
    "nutricional": {"notas_diarias_nutricional", "peso_talla", "pentacompartimental"},
}


def _exams(club: Club) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for slug, dept in ExamTemplate.objects.filter(
            department__club=club, is_active_version=True).values_list("slug", "department__slug"):
        out.setdefault(dept, set()).add(slug)
    return out


class ClubSetupTests(TestCase):
    def test_un_club_nuevo_nace_con_la_plantilla_base(self):
        club, applied = club_setup.create_club(
            "Deportes Prueba", [{"name": "Primer Equipo", "is_senior": True},
                                {"name": "Serie 2010", "cohort_year": 2010}])
        self.assertEqual(_exams(club), BASE_EXAMS)
        self.assertEqual(Position.objects.filter(club=club).count(), 4)
        self.assertEqual(club_setup.missing_from_base(club), [])
        n_exams = sum(len(v) for v in BASE_EXAMS.values())
        for cat in club.categories.all():
            self.assertEqual(cat.departments.count(), 3, cat.name)
            self.assertEqual(cat.exam_templates.count(), n_exams, cat.name)
        self.assertEqual(len(applied.exams), n_exams)

    def test_reaplicar_crea_solo_lo_que_falta_y_no_pisa_lo_existente(self):
        club, _ = club_setup.create_club("Deportes Prueba", [{"name": "Serie 2010"}])
        gps = ExamTemplate.objects.get(department__club=club, slug="gps_sesion")
        gps.config_schema = {"fields": [{"key": "tot_dist", "label": "Mía", "type": "number"}]}
        gps.save(update_fields=["config_schema"])
        ExamTemplate.objects.filter(department__club=club, slug="peso_talla").delete()

        self.assertEqual(club_setup.missing_from_base(club), ["Nutricional · Peso y Talla"])
        applied = club_setup.apply_base_template(club)
        self.assertEqual((applied.departments, applied.exams, applied.positions),
                         ([], ["Nutricional · Peso y Talla"], 0))
        gps.refresh_from_db()
        self.assertEqual(gps.config_schema["fields"][0]["label"], "Mía",
                         "el GPS ajustado por el club queda como estaba")

    def test_una_categoria_nueva_copia_a_su_modelo(self):
        club, _ = club_setup.create_club("Deportes Prueba", [{"name": "Primer Equipo"}])
        modelo = club.categories.get()
        gps = ExamTemplate.objects.get(department__club=club, slug="gps_partido")
        gps.applicable_categories.remove(modelo)

        copia = club_setup.add_category(club, name="Serie 2011", like=modelo)
        self.assertNotIn(gps, copia.exam_templates.all())
        self.assertEqual(set(copia.departments.all()), set(modelo.departments.all()))
        todas = club_setup.add_category(club, name="Serie 2012")
        self.assertIn(gps, todas.exam_templates.all(), "sin modelo, todo el club")

    def test_un_departamento_del_catalogo_llega_a_todas_las_categorias(self):
        club, _ = club_setup.create_club("Deportes Prueba", [{"name": "Serie 2010"}])
        dept = club_setup.add_department(club, "kinesiologico")
        cat = club.categories.get()
        self.assertIn(dept, cat.departments.all())
        self.assertTrue(cat.exam_templates.filter(slug="notas_diarias_kinesiologico").exists())

    def test_nombres_unicos(self):
        club_setup.create_club("Deportes Prueba", [])
        with self.assertRaises(club_setup.SetupError):
            club_setup.create_club("deportes prueba", [])


class PlatformEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_role_groups", "--skip-backfill", stdout=open("/dev/null", "w"))
        cls.root = User.objects.create_superuser("root", "root@slab.cl", "x")
        cls.staff = User.objects.create_user("staff", "staff@slab.cl", "x")

    def _c(self, user) -> Client:
        return Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(user)[0]}")

    def test_solo_superusuarios(self):
        c = self._c(self.staff)
        self.assertEqual(c.get("/api/platform/clubs").status_code, 403)
        r = c.post("/api/platform/clubs", {"name": "X"}, content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Club.objects.filter(name="X").exists())

    def test_crear_club_con_su_primer_administrador(self):
        r = self._c(self.root).post("/api/platform/clubs", {
            "name": "Deportes Prueba",
            "categories": [{"name": "Primer Equipo", "is_senior": True}],
            "admin": {"first_name": "Ana", "last_name": "Pérez", "email": "Ana@Club.cl"},
        }, content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual([d["slug"] for d in body["club"]["departments"]],
                         ["fisico", "medico", "nutricional"])
        self.assertEqual(body["club"]["missing"], [])
        self.assertEqual(body["admin_email"], "ana@club.cl")
        admin = User.objects.get(email="ana@club.cl")
        self.assertTrue(admin.check_password(body["admin_temp_password"]))
        self.assertEqual(list(admin.groups.values_list("name", flat=True)), ["Administrador"])
        m = admin.staff_membership
        self.assertTrue(m.all_categories and m.all_departments)

    def test_si_el_administrador_falla_no_queda_club_a_medias(self):
        User.objects.create_user("ya", "ya@club.cl", "x")
        r = self._c(self.root).post("/api/platform/clubs", {
            "name": "Deportes Prueba",
            "admin": {"first_name": "A", "last_name": "B", "email": "ya@club.cl"},
        }, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Club.objects.filter(name="Deportes Prueba").exists())

    def test_no_se_borra_una_categoria_con_jugadores(self):
        club, _ = club_setup.create_club("Deportes Prueba", [{"name": "Serie 2010"}])
        cat = club.categories.get()
        Player.objects.create(category=cat, first_name="A", last_name="B")
        url = f"/api/platform/clubs/{club.id}/categories/{cat.id}"
        self.assertEqual(self._c(self.root).delete(url).status_code, 400)
        self.assertTrue(Category.objects.filter(id=cat.id).exists())

    def test_detalle_cuenta_usuarios_y_ofrece_el_catalogo(self):
        club, _ = club_setup.create_club("Deportes Prueba", [])
        StaffMembership.objects.create(user=self.staff, club=club)
        d = self._c(self.root).get(f"/api/platform/clubs/{club.id}").json()
        self.assertEqual(d["users"], 1)
        self.assertEqual([x["slug"] for x in d["available_departments"]],
                         ["kinesiologico", "psicosocial", "tactico"])
