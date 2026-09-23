"""Guards del comparador entre divisiones.

Lo que puede salir mal acá no es que falte un dato: es que un número aparezca
con más autoridad de la que tiene. La media de la línea profesional es la vara
contra la que el club va a juzgar a un juvenil, y si sale de tres jugadores
tiene que decir tres.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Category, Club, Department, Player, Position
from dashboards.player_comparison import compare
from exams.models import ExamResult, ExamTemplate


class PlayerComparisonTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.dept = Department.objects.create(club=self.club, name="F", slug="f")
        self.primera = Category.objects.create(
            club=self.club, name="Primer Equipo", is_senior=True)
        self.juvenil = Category.objects.create(club=self.club, name="Sub 17")
        # Dos posiciones DISTINTAS de la MISMA línea: es el punto del arreglo
        # de posiciones — un lateral se mide contra la línea, no contra el
        # nombre exacto de su puesto.
        self.central = Position.objects.create(
            club=self.club, abbreviation="DC", name="Defensa central",
            role="Defensa", sort_order=12)
        self.lateral = Position.objects.create(
            club=self.club, abbreviation="LD", name="Lateral derecho",
            role="Defensa", sort_order=14)
        self.template = ExamTemplate.objects.create(
            name="Salto", slug="salto", department=self.dept,
            config_schema={"fields": [
                {"key": "cmj", "type": "number", "label": "CMJ", "unit": "cm",
                 "direction_of_good": "up"},
            ]},
        )

    def _jugador(self, cat, pos, nombre, dob=None):
        return Player.objects.create(
            category=cat, position=pos, first_name=nombre, last_name="X",
            is_active=True, date_of_birth=dob)

    def _lectura(self, jugador, valor, dias_atras=0):
        ExamResult.objects.create(
            player=jugador, template=self.template,
            recorded_at=timezone.now() - timedelta(days=dias_atras),
            result_data={"cmj": valor})

    def _comparar(self, jugadores):
        return compare(jugadores, [(self.template, "cmj")], club_id=self.club.id)

    # ── lo básico ────────────────────────────────────────────────────────
    def test_devuelve_el_ultimo_valor_y_la_serie_completa(self):
        j = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        self._lectura(j, 30.0, dias_atras=10)
        self._lectura(j, 35.0, dias_atras=1)
        self._lectura(otro, 40.0)

        out = self._comparar([j, otro])
        pj = out["players"][0]
        self.assertEqual(pj["values"]["salto:cmj"]["value"], 35.0)
        self.assertEqual([p["value"] for p in pj["series"]["salto:cmj"]],
                         [30.0, 35.0], "la serie va en orden cronológico")

    def test_respeta_el_orden_en_que_se_pidieron_los_jugadores(self):
        # La pantalla pone uno a cada lado; el de la izquierda tiene que
        # quedarse a la izquierda.
        a = self._jugador(self.juvenil, self.central, "Aaa")
        b = self._jugador(self.juvenil, self.central, "Bbb")
        self.assertEqual([p["name"] for p in self._comparar([b, a])["players"]],
                         ["Bbb X", "Aaa X"])

    # ── la referencia ────────────────────────────────────────────────────
    def test_la_referencia_cruza_por_LINEA_y_no_por_nombre_de_posicion(self):
        juve = self._jugador(self.juvenil, self.lateral, "Juve")
        otro = self._jugador(self.juvenil, self.lateral, "Otro")
        pro = self._jugador(self.primera, self.central, "Pro")
        self._lectura(juve, 30.0)
        self._lectura(otro, 31.0)
        self._lectura(pro, 50.0)

        bench = self._comparar([juve, otro])["benchmark"]
        # El juvenil es lateral derecho y el profesional defensa central: por
        # nombre no cruzarían, por línea sí.
        self.assertEqual(bench["Defensa"]["metrics"]["salto:cmj"]["mean"], 50.0)

    def test_la_media_promedia_ultimos_valores_no_todas_las_lecturas(self):
        # Un profesional con 3 mediciones no puede pesar 3 veces más que uno
        # con una sola.
        juve = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        pro1 = self._jugador(self.primera, self.central, "Pro1")
        pro2 = self._jugador(self.primera, self.central, "Pro2")
        for v, d in ((10.0, 30), (20.0, 20), (60.0, 1)):
            self._lectura(pro1, v, dias_atras=d)
        self._lectura(pro2, 40.0)

        bench = self._comparar([juve, otro])["benchmark"]
        self.assertEqual(bench["Defensa"]["metrics"]["salto:cmj"]["mean"], 50.0,
                         "(60 + 40) / 2, no el promedio de las cinco lecturas")

    def test_line_size_y_n_son_numeros_distintos(self):
        # Diez profesionales en la línea pero sólo tres con este examen: si la
        # UI mostrara `line_size`, diría que la vara sale de diez.
        juve = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        pros = [self._jugador(self.primera, self.central, f"Pro{i}")
                for i in range(4)]
        self._lectura(pros[0], 50.0)

        bench = self._comparar([juve, otro])["benchmark"]["Defensa"]
        self.assertEqual(bench["line_size"], 4)
        self.assertEqual(bench["metrics"]["salto:cmj"]["n"], 1)

    def test_sin_profesionales_con_el_dato_la_media_es_None_y_no_cero(self):
        # Cero sería un valor plausible en muchas métricas; None dice "no hay".
        juve = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        self._jugador(self.primera, self.central, "Pro")  # sin lecturas
        bench = self._comparar([juve, otro])["benchmark"]["Defensa"]
        self.assertIsNone(bench["metrics"]["salto:cmj"]["mean"])
        self.assertEqual(bench["metrics"]["salto:cmj"]["n"], 0)

    # ── lo que la vista necesita ─────────────────────────────────────────
    def test_manda_fecha_de_nacimiento_para_que_el_eje_pueda_ser_la_edad(self):
        nac = date(2008, 5, 4)
        j = self._jugador(self.juvenil, self.central, "Juve", dob=nac)
        otro = self._jugador(self.juvenil, self.central, "Otro")
        out = self._comparar([j, otro])
        self.assertEqual(out["players"][0]["date_of_birth"], nac.isoformat())
        self.assertIsNone(out["players"][1]["date_of_birth"])

    def test_la_foto_ausente_viaja_como_None(self):
        # Hoy es el caso de los 445 jugadores del formativo: la tarjeta
        # necesita saber que tiene que dibujar un fallback.
        j = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        self.assertIsNone(self._comparar([j, otro])["players"][0]["photo_url"])

    def test_un_jugador_sin_lecturas_aparece_igual_con_valores_vacios(self):
        # Excluirlo sería peor: el usuario lo eligió y su ausencia ES el dato.
        j = self._jugador(self.juvenil, self.central, "Juve")
        vacio = self._jugador(self.juvenil, self.central, "Vacio")
        self._lectura(j, 30.0)
        out = self._comparar([j, vacio])
        self.assertEqual(len(out["players"]), 2)
        self.assertIsNone(out["players"][1]["values"]["salto:cmj"])
        self.assertEqual(out["players"][1]["series"]["salto:cmj"], [])


class SeriesPerezosaTests(PlayerComparisonTests):
    """`series_for` — la serie completa viaja sólo para lo que se va a graficar.

    Es lo que permite que el selector ofrezca 238 métricas: el costo de una
    métrica extra pasa a ser su último valor, no su historia entera.
    """

    def test_sin_series_for_no_viaja_ninguna_serie(self):
        j = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        self._lectura(j, 30.0, dias_atras=5)
        self._lectura(j, 35.0)

        out = compare([j, otro], [(self.template, "cmj")],
                      club_id=self.club.id, series_for=frozenset())
        pj = out["players"][0]
        self.assertEqual(pj["series"]["salto:cmj"], [])
        # El último valor SIGUE viajando: es lo que dibujan la tabla y la
        # tarjeta, y sin él la pantalla quedaría vacía.
        self.assertEqual(pj["values"]["salto:cmj"]["value"], 35.0)

    def test_la_metrica_pedida_si_trae_su_serie(self):
        j = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        self._lectura(j, 30.0, dias_atras=5)
        self._lectura(j, 35.0)

        out = compare([j, otro], [(self.template, "cmj")],
                      club_id=self.club.id, series_for=frozenset({"salto:cmj"}))
        self.assertEqual(
            [p["value"] for p in out["players"][0]["series"]["salto:cmj"]],
            [30.0, 35.0])

    def test_la_referencia_no_depende_de_series_for(self):
        # La media profesional sale de últimos valores, así que tiene que salir
        # igual aunque no se haya pedido ninguna serie.
        j = self._jugador(self.juvenil, self.central, "Juve")
        otro = self._jugador(self.juvenil, self.central, "Otro")
        pro = self._jugador(self.primera, self.central, "Pro")
        self._lectura(pro, 50.0)
        out = compare([j, otro], [(self.template, "cmj")],
                      club_id=self.club.id, series_for=frozenset())
        self.assertEqual(
            out["benchmark"]["Defensa"]["metrics"]["salto:cmj"]["mean"], 50.0)


class PercentilesTests(PlayerComparisonTests):
    """El percentil del radar. Lo que puede salir mal acá es invisible: un
    polígono perfectamente dibujado que pone al más rápido como el más lento."""

    def _poblar_categoria(self, valores):
        """Compañeros de la categoría juvenil con un valor cada uno."""
        for i, v in enumerate(valores):
            companiero = self._jugador(self.juvenil, self.central, f"C{i}")
            self._lectura(companiero, v)

    def test_invierte_el_percentil_cuando_menos_es_mejor(self):
        # `cmj` está declarado `up`; se agrega un campo `down` para el contraste.
        self.template.config_schema = {"fields": [
            {"key": "cmj", "type": "number", "label": "CMJ",
             "direction_of_good": "up"},
            {"key": "t10", "type": "number", "label": "T10",
             "direction_of_good": "down"},
        ]}
        self.template.save(update_fields=["config_schema"])

        rapido = self._jugador(self.juvenil, self.central, "Rapido")
        lento = self._jugador(self.juvenil, self.central, "Lento")
        ExamResult.objects.create(player=rapido, template=self.template,
                                  recorded_at=timezone.now(),
                                  result_data={"t10": 1.5})
        ExamResult.objects.create(player=lento, template=self.template,
                                  recorded_at=timezone.now(),
                                  result_data={"t10": 2.5})
        for i, v in enumerate((1.8, 1.9, 2.0)):
            otro = self._jugador(self.juvenil, self.central, f"O{i}")
            ExamResult.objects.create(player=otro, template=self.template,
                                      recorded_at=timezone.now(),
                                      result_data={"t10": v})

        out = compare([rapido, lento], [(self.template, "t10")],
                      club_id=self.club.id, con_percentiles=True)
        p = out["percentiles"]
        self.assertGreater(
            p[str(rapido.id)]["salto:t10"]["pct"],
            p[str(lento.id)]["salto:t10"]["pct"],
            "el más rápido tiene que quedar MÁS LEJOS del centro del radar",
        )

    def test_sin_suficientes_companieros_el_percentil_es_None(self):
        # Un percentil sobre dos personas no es un percentil.
        a = self._jugador(self.juvenil, self.central, "A")
        b = self._jugador(self.juvenil, self.central, "B")
        self._lectura(a, 30.0)
        self._lectura(b, 40.0)
        out = compare([a, b], [(self.template, "cmj")],
                      club_id=self.club.id, con_percentiles=True)
        self.assertIsNone(out["percentiles"][str(a.id)]["salto:cmj"]["pct"])
        self.assertEqual(out["percentiles"][str(a.id)]["salto:cmj"]["n"], 2)

    def test_el_percentil_lee_el_MISMO_valor_que_la_tarjeta(self):
        # La última fila puede no traer el campo; la tarjeta usa la última CON
        # valor. Si el radar usara la última fila a secas, diría "sin dato"
        # para alguien cuya tarjeta muestra un número.
        a = self._jugador(self.juvenil, self.central, "A")
        b = self._jugador(self.juvenil, self.central, "B")
        self._poblar_categoria([31.0, 32.0, 33.0])
        self._lectura(a, 30.0, dias_atras=5)
        ExamResult.objects.create(  # más reciente, SIN el campo
            player=a, template=self.template, recorded_at=timezone.now(),
            result_data={"otro": 1})
        self._lectura(b, 40.0)

        out = compare([a, b], [(self.template, "cmj")],
                      club_id=self.club.id, con_percentiles=True)
        tarjeta = out["players"][0]["values"]["salto:cmj"]["value"]
        radar = out["percentiles"][str(a.id)]["salto:cmj"]["value"]
        self.assertEqual(tarjeta, 30.0)
        self.assertEqual(radar, tarjeta)

    def test_sin_con_percentiles_no_viajan(self):
        a = self._jugador(self.juvenil, self.central, "A")
        b = self._jugador(self.juvenil, self.central, "B")
        self.assertNotIn("percentiles", compare(
            [a, b], [(self.template, "cmj")], club_id=self.club.id))


class BandasPorCategoriaTests(PlayerComparisonTests):
    """La etiqueta de banda de cada jugador sale de SU categoría.

    Es el error que las bandas por categoría vinieron a evitar, y sería
    invisible: la etiqueta se ve igual de bien esté bien o mal calculada.
    """

    def _regla(self, categoria, ranges):
        from goals.models import AlertRule, AlertRuleKind, AlertSeverity
        return AlertRule.objects.create(
            template=self.template, field_key="cmj", category=categoria,
            kind=AlertRuleKind.BAND, severity=AlertSeverity.WARNING,
            config={"ranges": ranges}, is_active=True)

    def test_cada_jugador_se_clasifica_con_las_bandas_de_su_categoria(self):
        # El MISMO 40 cm: "Bueno" en la juvenil, "Bajo" en el primer equipo.
        self._regla(self.juvenil, [
            {"label": "Bajo", "max": 35, "color": "#f00"},
            {"label": "Bueno", "min": 35, "color": "#0f0"},
        ])
        self._regla(self.primera, [
            {"label": "Bajo", "max": 50, "color": "#f00"},
            {"label": "Bueno", "min": 50, "color": "#0f0"},
        ])
        juve = self._jugador(self.juvenil, self.central, "Juve")
        pro = self._jugador(self.primera, self.central, "Pro")
        self._lectura(juve, 40.0)
        self._lectura(pro, 40.0)

        out = compare([juve, pro], [(self.template, "cmj")], club_id=self.club.id)
        self.assertEqual(out["players"][0]["band_labels"]["salto:cmj"], "Bueno")
        self.assertEqual(out["players"][1]["band_labels"]["salto:cmj"], "Bajo",
                         "el mismo número, medido con la vara de su categoría")

    def test_manda_las_bandas_de_cada_uno_para_que_el_grafico_decida(self):
        self._regla(self.juvenil, [{"label": "Bajo", "max": 35}])
        juve = self._jugador(self.juvenil, self.central, "Juve")
        pro = self._jugador(self.primera, self.central, "Pro")
        self._lectura(juve, 30.0)
        out = compare([juve, pro], [(self.template, "cmj")], club_id=self.club.id)
        self.assertEqual(len(out["players"][0]["bands"]["salto:cmj"]), 1)
        self.assertEqual(out["players"][1]["bands"]["salto:cmj"], [],
                         "el primer equipo no tiene regla propia acá")

    def test_sin_bandas_la_etiqueta_es_None(self):
        a = self._jugador(self.juvenil, self.central, "A")
        b = self._jugador(self.juvenil, self.central, "B")
        self._lectura(a, 30.0)
        out = compare([a, b], [(self.template, "cmj")], club_id=self.club.id)
        self.assertIsNone(out["players"][0]["band_labels"]["salto:cmj"])


class VentanaTemporalTests(PlayerComparisonTests):
    """La ventana aplica a TODO, no sólo a los gráficos.

    Si la tarjeta mostrara el último valor histórico mientras la curva muestra
    los últimos 6 meses, las dos superficies hablarían de momentos distintos
    sin decirlo — y el percentil compararía al jugador de hoy contra el plantel
    de hace dos años.
    """

    def test_acota_la_serie_y_tambien_el_ultimo_valor(self):
        from django.utils import timezone as tz
        a = self._jugador(self.juvenil, self.central, "A")
        b = self._jugador(self.juvenil, self.central, "B")
        self._lectura(a, 30.0, dias_atras=400)   # fuera
        self._lectura(a, 35.0, dias_atras=10)    # dentro
        self._lectura(b, 40.0, dias_atras=5)

        desde = tz.now() - timedelta(days=180)
        out = compare([a, b], [(self.template, "cmj")], club_id=self.club.id,
                      date_from=desde)
        pa = out["players"][0]
        self.assertEqual([p["value"] for p in pa["series"]["salto:cmj"]], [35.0])
        self.assertEqual(pa["values"]["salto:cmj"]["value"], 35.0)

    def test_el_universo_del_percentil_tambien_se_acota(self):
        from django.utils import timezone as tz
        a = self._jugador(self.juvenil, self.central, "A")
        b = self._jugador(self.juvenil, self.central, "B")
        self._lectura(a, 30.0, dias_atras=10)
        self._lectura(b, 31.0, dias_atras=10)
        for i, v in enumerate((32.0, 33.0, 34.0)):
            viejo = self._jugador(self.juvenil, self.central, f"V{i}")
            self._lectura(viejo, v, dias_atras=400)   # fuera de la ventana

        desde = tz.now() - timedelta(days=180)
        out = compare([a, b], [(self.template, "cmj")], club_id=self.club.id,
                      con_percentiles=True, date_from=desde)
        # Sólo dos jugadores quedan en ventana: por debajo de _MIN_N, así que
        # el percentil no se calcula en vez de salir de una muestra de dos.
        self.assertEqual(out["percentiles"][str(a.id)]["salto:cmj"]["n"], 2)
        self.assertIsNone(out["percentiles"][str(a.id)]["salto:cmj"]["pct"])

    def test_sin_ventana_entra_todo(self):
        a = self._jugador(self.juvenil, self.central, "A")
        b = self._jugador(self.juvenil, self.central, "B")
        self._lectura(a, 30.0, dias_atras=400)
        self._lectura(a, 35.0)
        out = compare([a, b], [(self.template, "cmj")], club_id=self.club.id)
        self.assertEqual(len(out["players"][0]["series"]["salto:cmj"]), 2)
