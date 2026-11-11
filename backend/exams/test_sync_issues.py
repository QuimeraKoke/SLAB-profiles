"""Datos › Fuentes › Problemas: the collector upserts, closes what a read
document no longer has, and leaves alone what it could not read."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import Club
from exams import sync_issues as si
from exams.models import SyncIssue


class CollectorTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Club")

    def col(self, **kw):
        return si.IssueCollector(self.club, "saltos_formativo", **kw)

    def test_un_problema_por_nombre_y_documento_acumula_filas(self):
        c = self.col()
        c.add("jugador_no_encontrado", "Nicolás Marcano", document="U16", example="M1")
        c.add("jugador_no_encontrado", "NICOLAS  MARCANO", document="U16", example="M2", data_date=date(2026, 3, 1))
        c.save()
        i = SyncIssue.objects.get()
        self.assertEqual((i.rows, i.examples, i.latest_data_date), (2, ["M1", "M2"], date(2026, 3, 1)))

    def test_se_cierra_solo_si_el_documento_se_leyo_y_ya_no_aparece(self):
        c = self.col()
        c.add("jugador_no_encontrado", "A", document="U16")
        c.add("jugador_no_encontrado", "B", document="U18")
        c.save()
        c = self.col()
        c.read("U16", "sid16")  # U18 could not be read this time
        c.save()
        self.assertIsNotNone(SyncIssue.objects.get(subject="A").resolved_at)
        self.assertIsNone(SyncIssue.objects.get(subject="B").resolved_at)

    def test_reaparece_como_episodio_nuevo(self):
        c = self.col(); c.add("jugador_no_encontrado", "A", document="U16"); c.save()
        c = self.col(); c.read("U16"); c.save()
        c = self.col(); c.add("jugador_no_encontrado", "A", document="U16"); c.save()
        i = SyncIssue.objects.get()
        self.assertIsNone(i.resolved_at)
        self.assertEqual(SyncIssue.objects.count(), 1)

    def test_planilla_inaccesible_se_cierra_al_volver_a_leerla_y_espera_un_dia(self):
        c = self.col(); c.unreachable("sid16", "APIError: [403]: The caller does not have permission"); c.save()
        i = SyncIssue.objects.get()
        self.assertIn("compartida", i.detail)
        self.assertEqual(si.open_issues(self.club), [])  # a single failure is not shown yet
        SyncIssue.objects.update(first_seen_at=timezone.now() - timedelta(hours=si.UNREACHABLE_GRACE_H + 1))
        self.assertEqual(len(si.open_issues(self.club)), 1)
        c = self.col(); c.read("U16 doc", "sid16"); c.save()
        self.assertIsNotNone(SyncIssue.objects.get().resolved_at)

    def test_modo_prueba_no_escribe(self):
        c = self.col(commit=False); c.add("jugador_no_encontrado", "A"); c.save()
        self.assertFalse(SyncIssue.objects.exists())

    def test_fuente_completa_cierra_todo_lo_que_no_vio(self):
        c = si.IssueCollector(self.club, "kine_formativo"); c.add("fila_rechazada", "x"); c.save()
        c = si.IssueCollector(self.club, "kine_formativo"); c.complete(); c.save()
        self.assertIsNotNone(SyncIssue.objects.get().resolved_at)


class ReportParsingTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="Club")

    def test_saltos(self):
        c = si.IssueCollector(self.club, "saltos_formativo", commit=False)
        si.from_saltos(c, SimpleNamespace(documento="U20", sin_jugador=[
            "ROJAS (M16: ambiguo (2))", "ANDHER (M38: sin coincidencia)", "ANDHER (M39: sin coincidencia)"],
            pestanas_sin_partido=["AMISTOSO"]))
        kinds = sorted((i["kind"], i["subject"], i["rows"]) for i in c.items.values())
        self.assertEqual(kinds, [("jugador_no_encontrado", "ANDHER", 2), ("nombre_ambiguo", "ROJAS", 1),
                                 ("pestana_sin_partido", "AMISTOSO", 0)])

    def test_gps(self):
        c = si.IssueCollector(self.club, "gps_formativo", commit=False)
        si.from_sheet_rows(c, SimpleNamespace(
            sin_jugador=["VICENTE GONZALEZ (U16, 2026-11-04)", "VICENTE GONZALEZ (U15, 2026-11-10)"],
            fuera_de_rango=["JUAN PEREZ 2026-11-01 U16: dist=99999"],
            columnas_sin_mapear={}, columnas_desconocidas={"U18": ["RSI (m)"]}), "GPS")
        by = {i["subject"]: i for i in c.items.values()}
        self.assertEqual(by["VICENTE GONZALEZ"]["latest_data_date"], date(2026, 11, 10))
        self.assertEqual(by["JUAN PEREZ · dist"]["kind"], "fuera_de_rango")
        self.assertEqual(by["RSI (m)"]["kind"], "columna_nueva")


class LastLoginTests(TestCase):
    def test_login_y_actividad_registran_el_ultimo_ingreso(self):
        u = get_user_model().objects.create_user("u", "u@x.cl", "pw-123456")
        r = self.client.post("/api/auth/login", {"email": "u@x.cl", "password": "pw-123456"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        u.refresh_from_db()
        self.assertIsNotNone(u.last_login)
        # A long-lived session stamps it again on activity (throttled).
        get_user_model().objects.filter(pk=u.pk).update(last_login=timezone.now() - timedelta(days=3))
        token = r.json()["access_token"]
        self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")
        u.refresh_from_db()
        self.assertGreater(u.last_login, timezone.now() - timedelta(minutes=1))


class SolutionsTests(TestCase):
    def setUp(self):
        from core.models import Category, Player

        self.club = Club.objects.create(name="Club")
        cat = Category.objects.create(club=self.club, name="Serie 2013")
        self.david = Player.objects.create(category=cat, first_name="David", last_name="Quintero",
                                           date_of_birth=date(2013, 3, 1))
        Player.objects.create(category=cat, first_name="Pedro", last_name="Rojas", date_of_birth=date(2001, 1, 1))
        now = timezone.now()
        mk = lambda **kw: SyncIssue.objects.create(club=self.club, first_seen_at=now, last_seen_at=now, **kw)
        self.gps = mk(source="gps_formativo", kind="jugador_no_encontrado", key="a", subject="DAVID QUINTEROS",
                      document="Planilla GPS Formativo", rows=3, examples=["U13 · 3 oct 2026"])
        self.kine = mk(source="kine_formativo", kind="jugador_no_encontrado", key="b", subject="David Quinteros",
                       rows=2)
        self.user = get_user_model().objects.create_user("u", "u@x.cl", "x")

    def test_sugiere_por_nombre_y_categoria(self):
        from exams import sync_solutions as ss

        s = ss.solutions(self.club, str(self.gps.id))
        link = s["options"][0]
        self.assertEqual(link["action"], "link")
        self.assertEqual([c["name"] for c in link["candidates"]], ["David Quintero"])
        self.assertTrue(link["candidates"][0]["recommended"])
        self.assertEqual(len(s["same_name"]), 1)  # also missing in kine
        self.assertIn("5 filas", link["impact"])

    def test_vincular_guarda_el_alias_y_cierra_el_nombre_en_todas_las_fuentes(self):
        from exams import sheet_aliases
        from exams import sync_solutions as ss

        r = ss.apply(self.club, str(self.gps.id), "link", self.user, player_id=str(self.david.id))
        self.assertEqual(r["closed"], 2)
        self.assertEqual(sheet_aliases.load(self.club)[sheet_aliases.key("david quinteros")], self.david)
        self.assertFalse(SyncIssue.objects.filter(resolved_at__isnull=True).exists())

    def test_ignorado_no_vuelve_aunque_la_sync_lo_encuentre(self):
        from exams import sync_solutions as ss

        ss.apply(self.club, str(self.kine.id), "dismiss", self.user)
        c = si.IssueCollector(self.club, "kine_formativo")
        c.add("jugador_no_encontrado", "David Quinteros", key="b"); c.save()
        self.assertNotIn(str(self.kine.id), [i["id"] for i in si.open_issues(self.club)])
        ss.restore(self.club, str(self.kine.id))
        self.assertIn(str(self.kine.id), [i["id"] for i in si.open_issues(self.club)])

    def test_los_matchers_de_planillas_respetan_el_vinculo(self):
        from exams import sheet_aliases
        from exams.formativo_gps_ingest import build_matcher

        self.assertIsNone(build_matcher(self.club)("DAVID QUINTEROS", None))
        sheet_aliases.link(self.david, "DAVID QUINTEROS")
        self.assertEqual(build_matcher(self.club)("David Quinteros", None), self.david)


class LocateTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.club = Club.objects.create(name="Club")

    def issue(self, **kw):
        now = timezone.now()
        return SyncIssue.objects.create(club=self.club, source="gps_formativo", kind="jugador_no_encontrado",
                                        key=str(kw), subject="x", first_seen_at=now, last_seen_at=now,
                                        sheet_id="SID", **kw)

    def fake_doc(self, grid):
        from unittest import mock

        doc = mock.Mock()
        doc.tab_ids.return_value = {"U16": 111, "CHECK IN": 222}
        doc.values.return_value = grid
        return mock.patch("integrations.google_sheets.Documento", return_value=doc)

    def test_fila_conocida(self):
        i = self.issue(locations=[{"label": "fila 11", "tab": "U16", "row": 11}])
        with self.fake_doc([]):
            r = si.locate(i, 0)
        self.assertEqual(r["url"], "https://docs.google.com/spreadsheets/d/SID/edit#gid=111&range=11:11")

    def test_busca_la_fila_por_nombre_y_fecha(self):
        serial = (date(2026, 11, 4) - date(1899, 12, 30)).days
        grid = [["NOMBRE", "FECHA"], ["VICENTE GONZALEZ", serial - 1], ["Vicente González", serial]]
        i = self.issue(locations=[{"label": "U16 · 4 nov", "tab": "U16", "find": "VICENTE GONZALEZ",
                                   "date": "2026-11-04"}])
        with self.fake_doc(grid):
            r = si.locate(i, 0)
        self.assertTrue(r["precise"])
        self.assertTrue(r["url"].endswith("#gid=111&range=3:3"))

    def test_columna_nueva_marca_la_columna(self):
        grid = [["Marca temporal", "Nombre", "¿Entrenamiento complementario?"]]
        i = self.issue(locations=[{"label": "Hoja CHECK IN", "tab": "CHECK IN", "header": "¿Entrenamiento complementario?"}])
        with self.fake_doc(grid):
            r = si.locate(i, 0)
        self.assertTrue(r["url"].endswith("#gid=222&range=C:C"))

    def test_sin_credenciales_o_pestana_renombrada_abre_el_documento(self):
        i = self.issue(locations=[{"label": "x", "tab": "NO EXISTE"}])
        with self.fake_doc([]):
            r = si.locate(i, 0)
        self.assertEqual(r["url"], "https://docs.google.com/spreadsheets/d/SID/edit")
        self.assertIn("renombrado", r["note"])
