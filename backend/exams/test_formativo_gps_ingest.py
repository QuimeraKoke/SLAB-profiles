"""Guards for `exams.formativo_gps_ingest`.

The bug this file exists for: the club bakes its thresholds into the column
headers (`HSR (m) >20km/h`, `AC (#) >3ms2`, `SPRINT (m) >25km/h`), so an exact
header map is pinned to those numbers. The first version was, and five of the
twelve metrics went unmapped — `acc`, `dec`, `hsr`, `sprint_dist`, `sprints`,
most of the point of a GPS import. It reported 15.352 rows and "0 filas sin
métricas", because the other seven columns did map.

So the mapping is by pattern, and a sheet that fails to yield an expected
metric says so instead of loading partial rows quietly.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase
from django.utils import timezone

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import Bracket, Category, Club, Department, Player
from events.models import Event
from exams import formativo_gps_ingest as ing
from exams.models import ExamResult, ExamTemplate

# The club's real headers, thresholds included.
CAB = ["FECHA", "JUGADOR", "FECHA DE NACIMIENTO", "EDAD", "CATEGORÍA",
       "POSICIÓN", "CÓDIGO", "MICRO", "DURACIÓN (m)", "DT (m)", "MM",
       "AC (#) >3ms2", "DEC (#) >3ms2", "VMÁX (km/h)", "PL (UA)",
       "HSR (m) >20km/h", "SPRINT (m) >25km/h", "SPRINT (#) >25km/h",
       "Heart Rate - AVG HR  (% of player max HR)",
       "Heart Rate - Max Heart Rate (BPM)", "OBSERVACIÓN", "LOCALIA",
       "CALIDAD OPONENTE", "RESULTADO"]

D = datetime(2026, 3, 11)


def fila(nombre="CESAR PEREZ GALLEGOS", dia=D, codigo="MD-4", *,
         localia=None, calidad=None, resultado=None, hr=(None, None),
         vmax=21.8, dur=36.8, obs=""):
    return [dia, nombre, datetime(2011, 6, 23), 15, "U15", "EXTREMO", codigo,
            1.0, dur, 2856.4, 77.6, 27.0, 10.0, vmax, 42.6, 262.4, 118.0, 3.0,
            hr[0], hr[1], obs, localia, calidad, resultado]


def escribir(ruta: Path, hojas: dict[str, list[list]]) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    book.remove(book.active)
    for nombre, filas in hojas.items():
        ws = book.create_sheet(nombre)
        ws.append(CAB)
        for f in filas:
            ws.append(f)
    book.save(ruta)


class FormativoGpsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.dept = Department.objects.create(club=cls.club, name="Físico",
                                             slug="fisico")
        for order, (code, name, age) in enumerate(BRACKETS):
            Bracket.objects.create(code=code, name=name, age=age, order=order)
        cls.cat = Category.objects.create(club=cls.club, name="Serie 2011",
                                          cohort_year=2011)
        cls.player = Player.objects.create(
            category=cls.cat, first_name="Cesar", last_name="Perez",
            second_last_name="Gallegos", date_of_birth=date(2011, 6, 23))
        campos = [
            {"key": "fecha", "label": "Fecha", "type": "date"},
            {"key": "sesion", "label": "Sesión", "type": "text"},
            {"key": "tot_dur", "label": "Duración", "type": "number", "unit": "min"},
            {"key": "tot_dist", "label": "DT", "type": "number", "unit": "m"},
            {"key": "mpm", "label": "MM", "type": "number", "unit": "m/min"},
            {"key": "acc", "label": "Acc", "type": "number"},
            {"key": "dec", "label": "Dec", "type": "number"},
            {"key": "acc_dec", "label": "Acc+Dec", "type": "number"},
            {"key": "max_vel", "label": "Vmáx", "type": "number", "unit": "km/h"},
            {"key": "player_load", "label": "PL", "type": "number"},
            {"key": "hsr", "label": "HSR", "type": "number", "unit": "m"},
            {"key": "sprint_dist", "label": "Sprint m", "type": "number", "unit": "m"},
            {"key": "sprints", "label": "Sprints", "type": "number"},
            {"key": "avg_hr_pct", "label": "FC media", "type": "number",
             "unit": "%", "min": 30, "max": 100},
            {"key": "max_hr_bpm", "label": "FC máx", "type": "number",
             "unit": "bpm", "min": 100, "max": 230},
        ]
        for slug, nombre in (("gps_sesion", "GPS sesión"),
                             ("gps_partido", "GPS partido")):
            extra = ([{"key": "tipo_sesion", "label": "Tipo",
                       "type": "categorical",
                       "options": ["entrenamiento", "reintegro"]}]
                     if slug == "gps_sesion" else [])
            t = ExamTemplate.objects.create(
                department=cls.dept, name=nombre, slug=slug,
                config_schema={"fields": campos + extra})
            t.applicable_categories.set([cls.cat])

    def correr(self, hojas, **kw):
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "gps.xlsx"
            escribir(ruta, hojas)
            return ing.run(str(ruta), self.club, **kw)

    # ── el bug que motivó el archivo ────────────────────────────────────
    def test_mapea_las_metricas_aunque_el_umbral_este_en_el_encabezado(self):
        """`HSR (m) >20km/h` tiene que llegar a `hsr`.

        Con un mapa exacto, cambiar 20 por 21 en la planilla vuelve a dejar la
        métrica afuera sin que nada falle.
        """
        self.correr({"U15": [fila()]}, commit=True)
        d = ExamResult.objects.get(template__slug="gps_sesion").result_data
        for key, esperado in (("tot_dur", 36.8), ("tot_dist", 2856.4),
                              ("mpm", 77.6), ("acc", 27.0), ("dec", 10.0),
                              ("max_vel", 21.8), ("player_load", 42.6),
                              ("hsr", 262.4)):
            self.assertEqual(d.get(key), esperado, key)

    def test_distingue_sprint_en_metros_de_sprint_en_cuenta(self):
        # Los dos encabezados normalizan casi igual; el orden los separa.
        self.correr({"U15": [fila()]}, commit=True)
        d = ExamResult.objects.get(template__slug="gps_sesion").result_data
        self.assertEqual(d["sprint_dist"], 118.0)
        self.assertEqual(d["sprints"], 3.0)

    def test_avisa_cuando_una_metrica_esperada_no_mapea(self):
        """El silencio es peor que el error.

        Si la hoja cambia de forma, la corrida tiene que decirlo en vez de
        cargar filas a medias.
        """
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "gps.xlsx"
            sin_hsr = [c for c in CAB if not c.startswith("HSR")]
            import openpyxl
            book = openpyxl.Workbook()
            book.remove(book.active)
            ws = book.create_sheet("U15")
            ws.append(sin_hsr)
            book.save(ruta)
            _, faltantes, _, _ = ing.parse_workbook(str(ruta))
        self.assertIn("hsr", faltantes.get("U15", []))

    def test_avisa_cuando_aparece_una_columna_nueva(self):
        """El riesgo espejo, y el silencioso.

        La planilla la mantienen a mano. Que falte una métrica ya avisa; que
        AGREGUEN una columna no avisaba nada — simplemente no llegaba, y la
        corrida seguía reportando una carga completa.
        """
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "gps.xlsx"
            import openpyxl
            book = openpyxl.Workbook()
            book.remove(book.active)
            ws = book.create_sheet("U15")
            ws.append(CAB + ["HMLD (m)"])
            ws.append(fila() + [1022.4])
            book.save(ruta)
            _, faltantes, desconocidas, _ = ing.parse_workbook(str(ruta))
        self.assertEqual(faltantes, {}, "no falta ninguna métrica esperada")
        self.assertEqual(desconocidas.get("U15"), ["HMLD (m)"])

    def test_no_avisa_por_las_columnas_que_se_ignoran_a_proposito(self):
        # Identidad, microciclo, observación y las tres marcas de partido no
        # son métricas y no deben ensuciar el aviso.
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "gps.xlsx"
            escribir(ruta, {"U15": [fila()]})
            _, _, desconocidas, _ = ing.parse_workbook(str(ruta))
        self.assertEqual(desconocidas, {})

    # ── partido o sesión ────────────────────────────────────────────────
    def test_las_marcas_del_club_definen_que_es_partido(self):
        rep = self.correr({"U15": [
            fila(codigo="MD", localia="LOCAL", calidad="ALTA", resultado="2-1"),
            fila(dia=datetime(2026, 3, 14), codigo="MD-2"),
        ]}, commit=True)
        self.assertEqual(rep.partidos, 1)
        self.assertEqual(rep.sesiones, 1)
        self.assertTrue(ExamResult.objects.filter(template__slug="gps_partido").exists())

    def test_dia_de_partido_sin_marcas_va_a_sesion(self):
        """2174 filas del archivo son así, y no parecen partidos.

        Median 47,0 min y 5180 m, contra 82,2 min y 8214 m de las marcadas.
        Y sin marcas no hay rival ni resultado, así que un `gps_partido` sería
        un registro de partido sin partido.
        """
        rep = self.correr({"U15": [fila(codigo="MD")]}, commit=True)
        self.assertEqual(rep.partidos, 0)
        self.assertEqual(rep.md_sin_marca, 1)
        r = ExamResult.objects.get()
        self.assertEqual(r.template.slug, "gps_sesion")
        self.assertEqual(r.result_data["tipo_sesion"], "entrenamiento")

    def test_una_sola_marca_alcanza(self):
        # 577 filas del archivo traen localía y resultado pero no calidad.
        rep = self.correr({"U15": [
            fila(codigo="MD", localia="VISITA", resultado="0-3")]}, commit=True)
        self.assertEqual(rep.partidos, 1)

    def partido(self, dias=0, titulo="Universidad de Chile vs Colo Colo", bracket="Sub 15",
                categoria=None):
        from datetime import timedelta

        return Event.objects.create(
            club=self.club, category=categoria or self.cat, department=self.dept,
            event_type="match", title=titulo, bracket=Bracket.objects.get(name=bracket),
            starts_at=timezone.make_aware(D + timedelta(days=dias, hours=15)))

    def test_vincula_el_partido_al_evento_de_ese_dia(self):
        ev = self.partido()
        self.correr({"U15": [
            fila(codigo="MD", localia="LOCAL", resultado="1-0")]}, commit=True)
        self.assertEqual(ExamResult.objects.get().event, ev)

    def test_vincula_por_el_equipo_de_la_hoja_no_por_la_categoria(self):
        """Un Serie 2011 que juega en la U16 está en la hoja U16: su partido es
        el Sub 16 — de otra categoría —, no el Sub 15 del mismo día."""
        otra = Category.objects.create(club=self.club, name="Serie 2010", cohort_year=2010)
        self.partido(titulo="U. de Chile vs Palestino")                    # Sub 15
        sub16 = self.partido(titulo="U. de Chile vs Palestino", bracket="Sub 16",
                             categoria=otra)
        self.correr({"U16": [fila(codigo="MD", localia="LOCAL", obs="PALESTINO")]},
                    commit=True)
        self.assertEqual(ExamResult.objects.get().event, sub16)

    def test_el_rival_vincula_aunque_la_fecha_del_fixture_difiera(self):
        ev = self.partido(dias=2, titulo="Universidad de Chile vs O'Higgins")
        self.partido(dias=0, titulo="Universidad de Chile vs Palestino")
        self.correr({"U15": [fila(codigo="MD", localia="LOCAL", obs="O´HIGGINS")]},
                    commit=True)
        self.assertEqual(ExamResult.objects.get().event, ev)

    def test_otro_rival_no_se_vincula(self):
        self.partido(titulo="Universidad de Chile vs Palestino")
        self.correr({"U15": [fila(codigo="MD", localia="LOCAL", obs="COQUIMBO UNIDO")]},
                    commit=True)
        self.assertIsNone(ExamResult.objects.get().event)

    def test_recodificar_md_como_oficial_no_duplica(self):
        """El club re-codificó sus MD como «MD OFICIAL»: es la misma fila."""
        self.correr({"U15": [fila(codigo="MD", localia="LOCAL")]}, commit=True)
        rep = self.correr({"U15": [fila(codigo="MD OFICIAL", localia="LOCAL")]}, commit=True)
        self.assertEqual((rep.creados, rep.ya_existian), (0, 1))
        self.assertEqual(ExamResult.objects.count(), 1)

    def test_guarda_rival_localia_calidad_y_resultado(self):
        self.correr({"U15": [fila(codigo="MD OFICIAL", localia="VISITA", calidad="4 (CAMPEÓN)",
                                  resultado="GANADO", obs="COLO COLO")]}, commit=True)
        d = ExamResult.objects.get().result_data
        self.assertEqual(
            {k: d.get(k) for k in ing.CLAVES_PARTIDO},
            {"opponent": "COLO COLO", "match_type": "official", "venue": "away",
             "result": "won", "opponent_quality": "4 (CAMPEÓN)", "opponent_rank": 4})

    def test_una_fase_no_es_una_posicion(self):
        self.correr({"U15": [fila(codigo="MD OFICIAL", localia="LOCAL",
                                  calidad="SEMIFINAL", resultado="PERDIDO")]}, commit=True)
        d = ExamResult.objects.get().result_data
        self.assertEqual((d["opponent_quality"], d.get("opponent_rank")), ("SEMIFINAL", None))

    def test_el_amistoso_guarda_rival_y_tipo(self):
        self.correr({"U15": [fila(codigo="MD AMISTOSO", obs="AUDAX ITALIANO")]}, commit=True)
        d = ExamResult.objects.get().result_data
        self.assertEqual((d["opponent"], d["match_type"]), ("AUDAX ITALIANO", "friendly"))
        self.assertNotIn("venue", d)

    def test_un_entrenamiento_no_tiene_rival(self):
        self.correr({"U15": [fila(codigo="MD-2", obs="ENTRENAMIENTO")]}, commit=True)
        self.assertNotIn("opponent", ExamResult.objects.get().result_data)

    def test_la_sync_actualiza_los_datos_de_partido_sin_tocar_metricas(self):
        """El club completa la localía / el resultado después."""
        self.correr({"U15": [fila(codigo="MD OFICIAL", localia="LOCAL")]}, commit=True)
        r = ExamResult.objects.get()
        r.result_data["tot_dist"] = 1.0       # a metric the sync must not rewrite
        r.save(update_fields=["result_data"])
        rep = self.correr({"U15": [fila(codigo="MD OFICIAL", localia="LOCAL",
                                        resultado="EMPATADO", obs="PALESTINO")]}, commit=True)
        r.refresh_from_db()
        self.assertEqual(rep.partido_actualizados, 1)
        self.assertEqual((r.result_data["result"], r.result_data["opponent"]),
                         ("drawn", "PALESTINO"))
        self.assertEqual(r.result_data["tot_dist"], 1.0)
        rep = self.correr({"U15": [fila(codigo="MD OFICIAL", localia="LOCAL",
                                        resultado="EMPATADO", obs="PALESTINO")]})
        self.assertEqual(rep.partido_actualizados, 0, "idempotente")

    def test_dos_filas_con_la_misma_identidad_no_se_pisan(self):
        hojas = {"U15": [fila(codigo="MD-1", obs="ENTRENAMIENTO"), fila(codigo="MD-1", obs="SPARRING")]}
        self.correr(hojas, commit=True)
        self.assertEqual(self.correr(hojas).partido_actualizados, 0)

    def test_el_md_del_club_es_el_dia_de_microciclo(self):
        self.correr({"U15": [fila(codigo="MD-2"), fila(dia=datetime(2026, 3, 12), codigo="MD+1"),
                             fila(dia=datetime(2026, 3, 13), codigo="NO MD"),
                             fila(dia=datetime(2026, 3, 14), codigo="MD OFICIAL",
                                  localia="LOCAL")]}, commit=True)
        por_dia = {r.recorded_at.date().day: r.result_data for r in ExamResult.objects.all()}
        self.assertEqual(por_dia[11]["md_label"], "MD-2")
        self.assertEqual(por_dia[12]["md_label"], "MD+1")
        self.assertIsNone(por_dia[13]["md_label"], "NO MD: el club dice que no hay microciclo")
        self.assertEqual(por_dia[14]["md_label"], "MD")
        self.assertTrue(all(d["md_label_source"] == "club" for d in por_dia.values()))

    def test_el_calendario_no_pisa_el_md_del_club(self):
        from exams.microcycle import apply_md_labels

        self.partido(dias=1)          # by the calendar this session would be MD-1
        self.correr({"U15": [fila(codigo="MD-3")]}, commit=True)
        r = ExamResult.objects.select_related("player").get()
        self.assertEqual(apply_md_labels([r]), [])
        self.assertEqual(r.result_data["md_label"], "MD-3")

    def test_la_sync_pone_el_md_a_filas_viejas(self):
        self.correr({"U15": [fila(codigo="MD-4")]}, commit=True)
        r = ExamResult.objects.get()
        for k in ("md_label", "md_label_source"):
            r.result_data.pop(k)
        r.save(update_fields=["result_data"])
        self.assertEqual(self.correr({"U15": [fila(codigo="MD-4")]}, commit=True)
                         .partido_actualizados, 1)
        r.refresh_from_db()
        self.assertEqual(r.result_data["md_label"], "MD-4")

    def test_repair_quita_una_reimportacion_y_deja_la_vieja(self):
        from io import StringIO

        from django.core.management import call_command

        self.correr({"U15": [fila(codigo="MD-2")]}, commit=True)
        viejo = ExamResult.objects.get()
        ExamResult.objects.create(player=viejo.player, template=viejo.template,
                                  recorded_at=viejo.recorded_at,
                                  result_data=dict(viejo.result_data))
        call_command("repair_formativo_gps", "--club", self.club.name, "--commit",
                     stdout=StringIO())
        self.assertEqual(list(ExamResult.objects.values_list("pk", flat=True)), [viejo.pk])

    def test_un_amistoso_es_sesion_pero_marcada(self):
        self.correr({"U15": [fila(codigo="MD AMISTOSO")]}, commit=True)
        r = ExamResult.objects.get()
        self.assertEqual((r.template.slug, r.result_data["tipo_sesion"]),
                         ("gps_sesion", "amistoso"))

    def test_repair_marca_los_amistosos_y_agrega_la_opcion(self):
        from io import StringIO

        from django.core.management import call_command

        t = ExamTemplate.objects.get(slug="gps_sesion")
        self.correr({"U15": [fila(codigo="MD AMISTOSO")]}, commit=True)
        r = ExamResult.objects.get()
        r.result_data["tipo_sesion"] = "entrenamiento"       # as the old sync left it
        r.save(update_fields=["result_data"])
        call_command("repair_formativo_gps", "--club", self.club.name, "--commit",
                     stdout=StringIO())
        r.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(r.result_data["tipo_sesion"], "amistoso")
        campo = next(f for f in t.config_schema["fields"] if f["key"] == "tipo_sesion")
        self.assertIn("amistoso", campo["options"])
        self.assertEqual(campo["option_labels"]["amistoso"], "Amistoso")

    def test_repair_quita_el_duplicado_y_deja_el_mas_nuevo(self):
        from io import StringIO

        from django.core.management import call_command

        ev = self.partido(titulo="U. de Chile vs Palestino")
        self.correr({"U15": [fila(codigo="MD", localia="LOCAL", obs="PALESTINO")]},
                    commit=True)
        viejo = ExamResult.objects.get()
        # The duplicate as the old identity created it: raw code in the id,
        # corrected numbers, no event.
        nuevo = ExamResult.objects.create(
            player=viejo.player, template=viejo.template, recorded_at=viejo.recorded_at,
            result_data=viejo.result_data | {
                "origen_codigo": "MD OFICIAL", "tot_dist": 3000.0,
                "origen_id": viejo.result_data["origen_id"].replace("|MD|", "|MD OFICIAL|")})
        ExamResult.objects.filter(pk=viejo.pk).update(event=None)
        call_command("repair_formativo_gps", "--club", self.club.name, "--commit",
                     stdout=StringIO())
        queda = ExamResult.objects.get()
        self.assertEqual(queda.pk, nuevo.pk)
        self.assertEqual(queda.result_data["tot_dist"], 3000.0)
        self.assertEqual(queda.event, ev)
        self.assertEqual(queda.result_data["origen_id"], viejo.result_data["origen_id"])
        # And the next sync recognises it.
        rep = self.correr({"U15": [fila(codigo="MD OFICIAL", localia="LOCAL", obs="PALESTINO")]})
        self.assertEqual(rep.ya_existian, 1)

    def test_un_partido_sin_evento_en_SLAB_igual_se_importa(self):
        # El archivo arranca en 2024 y los eventos COMET en 2025-01-23: toda
        # la primera temporada no tiene evento al que colgarse.
        rep = self.correr({"U15": [
            fila(codigo="MD", localia="LOCAL", resultado="1-0")]}, commit=True)
        self.assertEqual(rep.creados, 1)
        self.assertIsNone(ExamResult.objects.get().event)
        self.assertEqual(rep.con_evento, 0)

    # ── hojas que no van ────────────────────────────────────────────────
    def test_excluye_las_hojas_de_otros_equipos_y_los_bloques(self):
        """`U17WC`/`U20 WC`/`WC CLUBES` traen jugadores de Panamá, Guatemala,
        Al Ahly e Inter Miami. `Pasing Indi.` parte una sesión en bloques de
        15 minutos, así que importarla contaría el mismo trabajo varias veces.
        """
        rep = self.correr({"U15": [fila()], "U17WC": [fila()],
                           "WC CLUBES": [fila()], "Pasing Indi.": [fila()],
                           "GPS PARTIDOS": [fila()]}, commit=True)
        self.assertEqual(rep.creados, 1)
        self.assertEqual(dict(rep.por_hoja), {"U15": 1})

    # ── decisiones de campo ─────────────────────────────────────────────
    def test_acc_dec_queda_vacio(self):
        """Catapult tampoco lo llena (no está en su SLUG_MAP).

        Sumar AC+DEC acá haría del formativo el único origen que lo trae, que
        es la misma inconsistencia al revés.
        """
        self.correr({"U15": [fila()]}, commit=True)
        self.assertNotIn("acc_dec", ExamResult.objects.get().result_data)

    def test_un_pulso_en_cero_no_es_una_medicion(self):
        rep = self.correr({"U15": [fila(hr=(0.0, 0.0))]}, commit=True)
        d = ExamResult.objects.get().result_data
        self.assertNotIn("avg_hr_pct", d)
        self.assertNotIn("max_hr_bpm", d)
        self.assertEqual(len(rep.fuera_de_rango), 1)
        self.assertEqual(rep.creados, 1, "la fila igual se carga")

    def test_guarda_el_pulso_cuando_viene(self):
        self.correr({"U15": [fila(hr=(82.0, 191.0))]}, commit=True)
        d = ExamResult.objects.get().result_data
        self.assertEqual(d["avg_hr_pct"], 82.0)
        self.assertEqual(d["max_hr_bpm"], 191.0)

    def test_el_codigo_de_microciclo_va_como_procedencia_no_como_metrica(self):
        # `exams.microcycle` deriva MD-n de las fechas de partido del club.
        self.correr({"U15": [fila(codigo="MD-4")]}, commit=True)
        d = ExamResult.objects.get().result_data
        self.assertEqual(d["origen_codigo"], "MD-4")
        self.assertIn("MD-4", d["sesion"])

    # ── procedencia e idempotencia ──────────────────────────────────────
    def test_escribe_la_procedencia(self):
        self.correr({"U15": [fila()]}, commit=True)
        d = ExamResult.objects.get().result_data
        self.assertEqual(d["origen"], ing.ORIGEN)
        self.assertEqual(d["origen_hoja"], "U15")
        self.assertNotEqual(d["origen"], "planilla_club_formativo",
                            "distinto del import físico, para poder filtrar")

    def test_correrlo_dos_veces_no_duplica(self):
        hojas = {"U15": [fila()]}
        self.correr(hojas, commit=True)
        rep = self.correr(hojas, commit=True)
        self.assertEqual(rep.creados, 0)
        self.assertEqual(rep.ya_existian, 1)
        self.assertEqual(ExamResult.objects.count(), 1)

    def test_la_misma_fecha_con_codigos_distintos_son_dos_filas(self):
        # Un jugador puede tener sesión y partido el mismo día.
        rep = self.correr({"U15": [
            fila(codigo="MD-1"),
            fila(codigo="MD", localia="LOCAL", resultado="1-0"),
        ]}, commit=True)
        self.assertEqual(rep.creados, 2)

    def test_sin_commit_no_escribe(self):
        rep = self.correr({"U15": [fila()]})
        self.assertEqual(rep.creados, 1)
        self.assertEqual(ExamResult.objects.count(), 0)

    def test_una_fila_sin_fecha_se_reporta(self):
        rep = self.correr({"U15": [fila(dia=None)]}, commit=True)
        self.assertEqual(rep.creados, 0)
        self.assertEqual(rep.sin_fecha, 1)
