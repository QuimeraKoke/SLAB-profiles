"""Guards for `exams.formativo_roster`: the club's register is the rule for
Serie and birth date, and a correction never lands on the wrong player."""
from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase, TestCase

from core.models import Category, Club, Player
from exams import formativo_roster as r

HEAD = ["JUGADOR", "FECHA DE NACIMIENTO", "AÑOS Y MESES", "CATEGORÍA"]


class RuleTests(SimpleTestCase):
    def test_categoria_de_la_hoja_a_serie(self):
        self.assertEqual(r.target_category("U20", 2006, 2026), "SUB-20")
        self.assertEqual(r.target_category("U18", 2008, 2026), "Serie 2008")
        self.assertEqual(r.target_category("U18", 2009, 2026), "Serie 2009")
        self.assertEqual(r.target_category("U15", 2011, 2026), "Serie 2011")
        # The club's rule for December births: one category down — followed.
        self.assertEqual(r.target_category("U14", 2011, 2026), "Serie 2012")
        self.assertIsNone(r.target_category("#N/A (No match.)", 2011, 2026))

    def test_una_categoria_imposible_es_contradiccion(self):
        self.assertTrue(r.is_contradiction("U20", 2013, 2026))
        self.assertFalse(r.is_contradiction("U14", 2011, 2026), "diciembre: 1 año de diferencia")


class PlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.cats = {n: Category.objects.create(club=cls.club, name=n)
                    for n in ("Serie 2010", "Serie 2011", "Serie 2012", "Serie 2013", "SUB-20", "Primer Equipo")}

    def player(self, first, last, second, cat, dob, active=True):
        return Player.objects.create(category=self.cats[cat], first_name=first, last_name=last,
                                     second_last_name=second, date_of_birth=dob, is_active=active)

    def plan(self, *rows):
        return r.plan([HEAD, *rows], self.club, 2026)

    def test_mueve_a_la_serie_de_la_hoja_y_corrige_la_fecha(self):
        p = self.player("Edouarlins", "Joseph", "", "Serie 2010", date(2011, 3, 2))
        rep = self.plan(["EDOUARLINS JOSEPH", "2011-03-03 00:00:00", 15.6, "U15"])
        (c,) = rep.cambios
        self.assertEqual((c.serie_antes, c.serie_despues, c.nac_despues), ("Serie 2010", "Serie 2011", date(2011, 3, 3)))
        r.apply(rep, self.club)
        p.refresh_from_db()
        self.assertEqual((p.category.name, p.date_of_birth), ("Serie 2011", date(2011, 3, 3)))

    def test_nombre_abreviado_si_es_unico(self):
        self.player("Ignacio", "Alvizu", "Gomez", "Serie 2012", date(2012, 3, 21))
        rep = self.plan(["IGNACIO ALVIZU", "2012-03-27 00:00:00", 14, "U14"])
        self.assertEqual(rep.cambios[0].nac_despues, date(2012, 3, 27))

    def test_homonimos_no_se_tocan(self):
        self.player("Lucas", "Gonzalez", "Perez", "Serie 2012", date(2012, 1, 1))
        self.player("Lucas", "Gonzalez", "Soto", "Serie 2013", date(2013, 1, 1))
        rep = self.plan(["LUCAS GONZALEZ", "2012-06-06 00:00:00", 14, "U14"])
        self.assertEqual((rep.cambios, rep.saltados["ambiguo"]), ([], ["LUCAS GONZALEZ"]))

    def test_contradiccion_de_la_hoja_no_se_aplica(self):
        self.player("Tomas", "Mandiola", "", "Serie 2013", date(2013, 1, 23))
        rep = self.plan(["TOMAS MANDIOLA", "2013-01-23 00:00:00", 13, "U20"])
        self.assertEqual((rep.cambios, len(rep.saltados["contradiccion"])), ([], 1))

    def test_fecha_repetida_en_la_hoja_no_se_copia(self):
        for i, (f, l) in enumerate((("Ruben", "Vera"), ("Diego", "Vargas"), ("Ignacio", "Vasquez"))):
            self.player(f, l, "", "SUB-20", date(2006, 3, 1 + i))
        rep = self.plan(*[[f"{f} {l}", "2006-05-26 00:00:00", 20, "U20"]
                          for f, l in (("RUBEN", "VERA"), ("DIEGO", "VARGAS"), ("IGNACIO", "VASQUEZ"))])
        self.assertEqual((rep.cambios, len(rep.saltados["fecha_repetida"])), ([], 3))

    def test_primer_equipo_e_inactivos_no_se_tocan(self):
        self.player("Andres", "Bolaño", "Vera", "Primer Equipo", date(2008, 1, 16))
        self.player("Ignacio", "Saez", "", "SUB-20", date(2008, 5, 5), active=False)
        rep = self.plan(["ANDRES BOLAÑO VERA", "2008-01-10 00:00:00", 18, "U18"],
                        ["IGNACIO SAEZ", "2008-05-05 00:00:00", 18, "U18"])
        self.assertEqual(rep.cambios, [])

    def test_sin_commit_no_escribe(self):
        p = self.player("Tomas", "Meneses", "", "Serie 2010", date(2011, 3, 2))
        self.plan(["TOMAS MENESES", "2011-03-02 00:00:00", 15, "U15"])
        p.refresh_from_db()
        self.assertEqual(p.category.name, "Serie 2010")
