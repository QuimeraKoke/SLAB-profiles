"""The wellness resolver: which form a category fills, and how it scores.

Every failure this guards against is silent and looks like a real number.

* Pinning the surfaces to the `checkin_fisico` slug made the Formativo's
  65.000 check-ins invisible: the Daily and the Centro de mando queried a
  template that youth categories don't fill, found nothing, and reported
  "0/68 respondieron" — indistinguishable from a squad that didn't answer.
* Averaging the Formativo's items raw scores a wrecked player at 90. Three of
  its five items are inverted (fatiga, estrés, daño muscular) where all five of
  Primer Equipo's point the same way, and the result still looks like a
  wellness score.
* Inverting as `1 − v/max` caps a perfect answer at 88 instead of 100, because
  the best value on a 1–5 scale is 1 and `1 − 1/5` is 0.8.
* A dimension that is not also a score item used to render nothing: its max was
  never collected, `dimension_pct` returned None and the chip simply wasn't
  there.
"""
from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from api import wellness as w
from api.command_center import build_command_center
from core.models import Category, Club, Department, Player
from exams.models import ExamResult, ExamTemplate


def _escala(key, mn, mx):
    return {"key": key, "label": key, "type": "number", "min": mn, "max": mx}


class WellnessRoleResolverTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="U")
        self.dept = Department.objects.create(club=self.club, name="Físico", slug="fisico")
        self.senior = Category.objects.create(club=self.club, name="Primer Equipo")
        self.youth = Category.objects.create(club=self.club, name="Serie 2013")
        for c in (self.senior, self.youth):
            c.departments.add(self.dept)

        # Primer Equipo's legacy form: no `wellness` block at all. It has to
        # keep working unchanged — that is the whole point of the fallback.
        self.legacy = ExamTemplate.objects.create(
            name="Check-in físico", slug="checkin_fisico", department=self.dept,
            config_schema={"fields": [
                _escala("recuperacion", 1, 10), _escala("cuerpo", 1, 5),
                _escala("energia", 1, 5), _escala("animo", 1, 5),
                _escala("sueno", 1, 5),
            ]},
        )
        self.legacy.applicable_categories.add(self.senior)

        self.checkin = ExamTemplate.objects.create(
            name="Check-IN formativo", slug="checkin_formativo", department=self.dept,
            config_schema={
                "fields": [
                    _escala("calidad_sueno", 1, 5), _escala("nivel_fatiga", 1, 5),
                    _escala("nivel_estres", 1, 5), _escala("estado_animo", 1, 5),
                    _escala("dano_muscular", 1, 5),
                ],
                "wellness": {
                    "role": "checkin",
                    "items": [["calidad_sueno", "Sueño"], ["nivel_fatiga", "Fatiga"],
                              ["nivel_estres", "Estrés"], ["estado_animo", "Ánimo"],
                              ["dano_muscular", "Daño muscular"]],
                    "inverted": ["nivel_fatiga", "nivel_estres", "dano_muscular"],
                    "dimensions": [["calidad_sueno", "Sueño"]],
                },
            },
        )
        self.checkin.applicable_categories.add(self.youth)

        self.checkout = ExamTemplate.objects.create(
            name="Check-OUT formativo", slug="checkout_formativo", department=self.dept,
            config_schema={
                "fields": [_escala("rpe", 0, 10), _escala("dano_muscular", 1, 5)],
                "wellness": {
                    "role": "checkout",
                    "items": [["rpe", "RPE"], ["dano_muscular", "Daño muscular"]],
                    "inverted": ["rpe", "dano_muscular"],
                    "dimensions": [["rpe", "RPE"], ["dano_muscular", "Daño muscular"]],
                },
            },
        )
        self.checkout.applicable_categories.add(self.youth)

    # ── which template is the form ─────────────────────────────────────

    def test_una_categoria_sin_declaracion_cae_al_checkin_historico(self):
        self.assertEqual([t.slug for t in w.templates_for(self.senior)],
                         ["checkin_fisico"])

    def test_la_categoria_que_declara_gana_al_slug_historico(self):
        self.assertEqual([t.slug for t in w.templates_for(self.youth)],
                         ["checkin_formativo"])

    def test_el_checkout_solo_existe_donde_se_declara(self):
        self.assertEqual([t.slug for t in w.templates_for(self.youth, role="checkout")],
                         ["checkout_formativo"])
        # Sin declaración NO hay fallback: el Primer Equipo no llena check-out,
        # y devolver el check-in acá lo mostraría como si lo llenara.
        self.assertEqual(w.templates_for(self.senior, role="checkout"), [])

    def test_roles_for(self):
        self.assertEqual(w.roles_for(self.senior), ["checkin"])
        self.assertEqual(w.roles_for(self.youth), ["checkin", "checkout"])

    # ── el puntaje ─────────────────────────────────────────────────────

    def test_el_checkin_perfecto_del_formativo_da_100(self):
        """El caso que el `1 − v/max` tapaba: llegaba a 88, no a 100."""
        perfecto = {"calidad_sueno": 5, "estado_animo": 5,
                    "nivel_fatiga": 1, "nivel_estres": 1, "dano_muscular": 1}
        self.assertEqual(w.score_for(self.youth, perfecto), 100)

    def test_el_peor_checkin_del_formativo_toca_el_piso_de_la_escala(self):
        """20, no 0.

        La fracción es `v ÷ max`, no un reescalado min–max, así que el peor
        valor posible de una escala 1–5 vale 1/5. Es la misma propiedad que
        hace que el peor check-in del Primer Equipo dé 18 en vez de 0; tocarla
        movería todos los números históricos de los dos planteles.
        """
        pesimo = {"calidad_sueno": 1, "estado_animo": 1,
                  "nivel_fatiga": 5, "nivel_estres": 5, "dano_muscular": 5}
        self.assertEqual(w.score_for(self.youth, pesimo), 20)

    def test_ignorar_los_invertidos_da_el_puntaje_al_reves(self):
        """La razón de que exista `score_for`: acertar los items y errar los
        invertidos produce un número que apunta exactamente al revés."""
        destruido = {"calidad_sueno": 1, "estado_animo": 1,
                     "nivel_fatiga": 5, "nivel_estres": 5, "dano_muscular": 5}
        crudo = w.score(destruido, w.field_max(self.youth),
                        w.items_for(self.youth))          # sin `inverted`
        self.assertEqual(crudo, 68, "el jugador destruido puntúa 'bueno'")
        self.assertEqual(w.score_for(self.youth, destruido), 20)

    def test_el_primer_equipo_no_cambia(self):
        # Escalas mixtas: recuperación 1–10 contra cuatro de 1–5.
        pleno = {"recuperacion": 10, "cuerpo": 5, "energia": 5, "animo": 5, "sueno": 5}
        self.assertEqual(w.score_for(self.senior, pleno), 100)
        self.assertEqual(w.score_for(self.senior, {"recuperacion": 1, "cuerpo": 1,
                                                   "energia": 1, "animo": 1, "sueno": 1}), 18)

    def test_un_item_ausente_no_hunde_el_puntaje(self):
        # Promedia lo respondido; un campo vacío no cuenta como cero.
        self.assertEqual(w.score_for(self.youth, {"calidad_sueno": 5, "estado_animo": 5}), 100)

    def test_sin_ninguna_respuesta_devuelve_None(self):
        self.assertIsNone(w.score_for(self.youth, {}))

    def test_el_checkout_puntua_invertido(self):
        # Sesión suave y sin molestias → alto; dura y dolorida → bajo.
        self.assertEqual(w.score_for(self.youth, {"rpe": 0, "dano_muscular": 1},
                                     role="checkout"), 100)
        # 10 y no 0: el RPE va de 0 a 10 (llega al piso real) y el daño
        # muscular de 1 a 5, cuyo peor valor vale 1/5.
        self.assertEqual(w.score_for(self.youth, {"rpe": 10, "dano_muscular": 5},
                                     role="checkout"), 10)

    # ── dimensiones ────────────────────────────────────────────────────

    def test_una_dimension_que_no_es_item_del_puntaje_igual_tiene_escala(self):
        """La regresión silenciosa: sin su max, `dimension_pct` da None y el
        chip no aparece — sin error que lo delate."""
        self.checkin.config_schema["wellness"]["dimensions"] = [["estado_animo", "Ánimo"]]
        self.checkin.config_schema["wellness"]["items"] = [["calidad_sueno", "Sueño"]]
        self.checkin.save()
        self.assertIn("estado_animo", w.field_max(self.youth))
        self.assertEqual(
            w.dimension_pct_for(self.youth, {"estado_animo": 5}, "estado_animo"), 100)

    def test_la_dimension_invertida_se_espeja(self):
        self.assertEqual(
            w.dimension_pct_for(self.youth, {"nivel_fatiga": 1}, "nivel_fatiga"), 100)
        self.assertEqual(
            w.dimension_pct_for(self.youth, {"nivel_fatiga": 5}, "nivel_fatiga"), 20)


class CommandCenterCheckoutTests(TestCase):
    """El payload sólo trae el check-out donde la categoría lo llena."""

    def setUp(self):
        base = WellnessRoleResolverTests()
        base.setUp()
        self.__dict__.update(base.__dict__)
        self.jugador = Player.objects.create(
            category=self.youth, first_name="A", last_name="B", is_active=True)
        Player.objects.create(category=self.senior, first_name="C", last_name="D",
                              is_active=True)

    def test_una_categoria_sin_checkout_no_trae_la_llave(self):
        cc = build_command_center(self.senior)
        self.assertEqual(cc["wellness_roles"], ["checkin"])
        self.assertNotIn("checkout", cc)
        # Y tampoco la fila de calidad de datos: "Sin plantilla" se leería como
        # una falta de configuración y no como un formulario que no existe.
        self.assertNotIn("Check-OUT", [r["source"] for r in cc["data_quality"]])

    def test_la_categoria_con_checkout_trae_su_carga_interna(self):
        """El KPI del check-out mide CARGA, no bienestar.

        Medido sobre las 49.573 respuestas del club: `rpe` viene en el 100% de
        las filas y `dano_muscular` en el 8% — y cuatro de los ocho documentos
        no lo preguntan nunca. Un puntaje 0–100 armado sobre ese ítem diría
        "Sin datos" para siempre en la mitad de las categorías.
        """
        ExamResult.objects.create(
            player=self.jugador, template=self.checkout,
            recorded_at=timezone.now(),
            result_data={"rpe": 7, "duracion_min": 60,
                         "molestia_post": "Isquiotibiales Der."},
        )
        cc = build_command_center(self.youth)
        self.assertEqual(cc["wellness_roles"], ["checkin", "checkout"])
        ko = cc["checkout"]["wellness"]
        self.assertEqual(ko["value"], 420, "7 × 60 = la UA del club")
        self.assertEqual(ko["unit"], "UA")
        self.assertEqual(ko["tone"], "info", "una sesión dura no es una alarma")
        self.assertIn({"label": "RPE medio", "value": 7.0}, ko["dimensions"])
        self.assertIn({"label": "con molestia", "value": 1}, ko["dimensions"])
        self.assertEqual(cc["checkout"]["adherence"]["responded"], 1)
        self.assertIn("Check-OUT", [r["source"] for r in cc["data_quality"]])

    def test_el_checkout_sin_respuestas_no_inventa_un_numero(self):
        cc = build_command_center(self.youth)
        self.assertIsNone(cc["checkout"]["wellness"]["value"])
        self.assertEqual(cc["checkout"]["wellness"]["status"], "Sin datos")

    def test_el_checkin_del_formativo_ya_no_mira_el_slug_del_primer_equipo(self):
        """La regresión de origen: `checkin_formativo` contaba como 0 respuestas."""
        ExamResult.objects.create(
            player=self.jugador, template=self.checkin, recorded_at=timezone.now(),
            result_data={"calidad_sueno": 5, "estado_animo": 5, "nivel_fatiga": 1,
                         "nivel_estres": 1, "dano_muscular": 1},
        )
        cc = build_command_center(self.youth)
        self.assertEqual(cc["kpis"]["wellness"]["value"], 100)
        self.assertEqual(cc["kpis"]["wellness"]["responses"], 1)
        self.assertEqual(cc["checkin_adherence"]["responded"], 1)


class DailyCheckoutDiaTests(TestCase):
    """La fecha del bloque de Check-OUT del Daily.

    Medido sobre las 49.573 respuestas del club: los check-out llegan entre las
    11:00 y las 18:00 (pico 17–18) contra el 07–09 del check-in, y casi ninguno
    antes de las 10. El Daily es la reunión de las 8, así que "quién no
    respondió el check-out de HOY" listaría al plantel completo todas las
    mañanas — por una sesión que todavía no pasó.
    """

    def setUp(self):
        base = WellnessRoleResolverTests()
        base.setUp()
        self.__dict__.update(base.__dict__)
        self.jugador = Player.objects.create(
            category=self.youth, first_name="A", last_name="B", is_active=True)
        self.otro = Player.objects.create(
            category=self.youth, first_name="C", last_name="D", is_active=True)

    def _bloque(self, fecha, categoria=None):
        from api.daily_report import _wellness_roles_block

        cat = categoria or self.youth
        jugadores = list(Player.objects.filter(category=cat, is_active=True))
        return _wellness_roles_block(cat, jugadores,
                                     [p.id for p in jugadores], fecha)

    def _checkout(self, player, dia, hora=17):
        from datetime import datetime

        ExamResult.objects.create(
            player=player, template=self.checkout,
            recorded_at=timezone.make_aware(datetime(dia.year, dia.month, dia.day, hora)),
            result_data={"rpe": 7, "duracion_min": 60})

    def test_sin_datos_de_hoy_cae_a_la_ultima_sesion(self):
        from datetime import timedelta

        hoy = timezone.localdate()
        ayer = hoy - timedelta(days=1)
        self._checkout(self.jugador, ayer)
        bloque = self._bloque(hoy)["checkout_hoy"]
        self.assertEqual(bloque["date"], ayer.isoformat())
        self.assertFalse(bloque["is_target_date"], "la pantalla tiene que nombrar el día")
        self.assertEqual(bloque["n"], 1)
        # El que NO cerró la sesión de ayer: eso es lo que se pregunta a las 8.
        self.assertEqual([p["name"] for p in bloque["no_respondieron"]], ["C D"])

    def test_con_datos_del_dia_usa_el_dia(self):
        hoy = timezone.localdate()
        self._checkout(self.jugador, hoy, hora=17)
        bloque = self._bloque(hoy)["checkout_hoy"]
        self.assertEqual(bloque["date"], hoy.isoformat())
        self.assertTrue(bloque["is_target_date"])

    def test_una_fecha_pasada_no_mira_hacia_adelante(self):
        """Navegar a un día pasado no puede traer el check-out de después."""
        from datetime import timedelta

        hoy = timezone.localdate()
        self._checkout(self.jugador, hoy)
        bloque = self._bloque(hoy - timedelta(days=1))["checkout_hoy"]
        self.assertIsNone(bloque["date"])
        self.assertEqual(bloque["no_respondieron"], [],
                         "sin sesión conocida no se acusa a nadie")

    def test_una_categoria_muerta_no_resucita_una_lista_vieja(self):
        """La ventana es de dos semanas.

        Sin cota, una categoría que dejó de llenar el formulario hace un año
        mostraría esa lista de hace un año como si fuera la última sesión.
        """
        from datetime import timedelta

        hoy = timezone.localdate()
        self._checkout(self.jugador, hoy - timedelta(days=40))
        bloque = self._bloque(hoy)["checkout_hoy"]
        self.assertIsNone(bloque["date"])

    def test_el_primer_equipo_no_trae_el_bloque(self):
        Player.objects.create(category=self.senior, first_name="E",
                              last_name="F", is_active=True)
        bloque = self._bloque(timezone.localdate(), self.senior)
        self.assertEqual(bloque["wellness_roles"], ["checkin"])
        self.assertNotIn("checkout_hoy", bloque)


class BandasYAlertasDelFormativoTests(TestCase):
    """Lo que el seeder deja sembrado, y sobre todo lo que NO siembra."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        cls.club = Club.objects.create(name="U")
        cls.dept = Department.objects.create(club=cls.club, name="Físico",
                                            slug="fisico")
        cat = Category.objects.create(club=cls.club, name="Serie 2013",
                                      cohort_year=2013)
        cat.departments.add(cls.dept)
        call_command("seed_wellness_formativo", club="U", season=2026,
                     verbosity=0)

    def _campo(self, slug, key):
        t = ExamTemplate.objects.get(slug=slug)
        return next(f for f in t.config_schema["fields"] if f["key"] == key)

    def test_las_escalas_1_5_traen_banda(self):
        for key in ("calidad_sueno", "nivel_fatiga", "nivel_estres",
                    "estado_animo", "dano_muscular"):
            bandas = self._campo("checkin_formativo", key).get("reference_ranges")
            self.assertTrue(bandas, key)
            self.assertEqual([b["label"] for b in bandas],
                             ["Crítico", "Aviso", "Normal"], key)

    def test_un_3_cae_en_aviso_y_no_en_critico(self):
        """Los límites son inclusivos y gana el primer match, así que el orden
        de declaración decide qué pasa en la frontera."""
        from exams.bands import band_for_value

        bandas = self._campo("checkin_formativo", "calidad_sueno")["reference_ranges"]
        self.assertEqual(band_for_value(2, bandas)["label"], "Crítico")
        self.assertEqual(band_for_value(3, bandas)["label"], "Aviso")
        self.assertEqual(band_for_value(4, bandas)["label"], "Normal")

    def test_la_hidratacion_no_tiene_banda_ni_alerta(self):
        """Medido sobre 46.512 respuestas: va de 1 a 9 y el 78% son 2 o 3 —
        litros de agua, no un nivel 1–5. Con la banda de escala puesta,
        marcaba el 55% de las respuestas como críticas y enterraba el resto."""
        from goals.models import AlertRule

        campo = self._campo("checkin_formativo", "hidratacion")
        self.assertEqual(campo["unit"], "L")
        self.assertEqual(campo["max"], 10, "los valores reales llegan a 9")
        self.assertNotIn("reference_ranges", campo)
        self.assertFalse(AlertRule.objects.filter(
            template__slug="checkin_formativo", field_key="hidratacion").exists())

    def test_el_peso_no_tiene_banda(self):
        # El peso "normal" es el del jugador, no un rango del formulario.
        self.assertNotIn("reference_ranges",
                         self._campo("checkin_formativo", "peso"))

    def test_el_rpe_tiene_zonas_pero_no_puede_disparar(self):
        from exams.bands import alert_bands
        from goals.models import AlertRule

        campo = self._campo("checkout_formativo", "rpe")
        bandas = campo["reference_ranges"]
        self.assertEqual([b["label"] for b in bandas],
                         ["Baja", "Moderada", "Alta", "Máxima"])
        # Sin `alert: False` explícito, la heurística de la banda más roja la
        # haría disparar sola: una sesión de RPE 9 es una sesión dura, no una
        # alarma.
        self.assertEqual(alert_bands(bandas), [])
        self.assertFalse(AlertRule.objects.filter(
            template__slug="checkout_formativo", field_key="rpe").exists())

    def test_cada_campo_vigilado_tiene_aviso_y_critica(self):
        from goals.models import AlertRule

        for slug, campos in (
            ("checkin_formativo", ["calidad_sueno", "nivel_fatiga",
                                   "nivel_estres", "estado_animo",
                                   "dano_muscular"]),
            ("checkout_formativo", ["dano_muscular", "partido_recuperacion",
                                    "partido_explosivas", "partido_fisico"]),
        ):
            for campo in campos:
                sev = set(AlertRule.objects.filter(
                    template__slug=slug, field_key=campo,
                ).values_list("severity", flat=True))
                self.assertEqual(sev, {"warning", "critical"}, f"{slug}.{campo}")

    def test_las_reglas_no_son_por_categoria(self):
        """Un 3 de sueño significa lo mismo en Serie 2018 que en SUB-20.

        Replicarlas por categoría serían 12 copias del mismo número esperando
        a desincronizarse — al revés de las pruebas físicas, donde el club mide
        el mismo test con umbrales distintos por edad.
        """
        from goals.models import AlertRule

        self.assertFalse(AlertRule.objects.filter(
            template__slug__in=("checkin_formativo", "checkout_formativo"),
        ).exclude(category=None).exists())

    def test_cada_severidad_dispara_su_propia_banda(self):
        from goals.evaluator import _band_evaluation
        from goals.models import AlertRule

        for sev, valor_que_dispara, valor_que_no in (("critical", 2, 3),
                                                     ("warning", 3, 2)):
            regla = AlertRule.objects.get(template__slug="checkin_formativo",
                                          field_key="calidad_sueno",
                                          severity=sev)
            banda, disparan = _band_evaluation(regla, valor_que_dispara)
            self.assertIn(banda["label"], [b["label"] for b in disparan], sev)
            banda, disparan = _band_evaluation(regla, valor_que_no)
            self.assertNotIn(banda["label"], [b["label"] for b in disparan], sev)

    def test_una_segunda_corrida_no_pisa_los_numeros_del_club(self):
        """El cuerpo médico va a ajustar estos umbrales desde el editor."""
        from django.core.management import call_command

        from goals.models import AlertRule

        regla = AlertRule.objects.filter(
            template__slug="checkin_formativo", field_key="calidad_sueno",
            severity="critical").first()
        regla.config = {"trigger_labels": ["Crítico"],
                        "ranges": [{"min": 1, "max": 1.5, "label": "Crítico"}]}
        regla.save()
        call_command("seed_wellness_formativo", club="U", season=2026,
                     unlock=True, verbosity=0)
        regla.refresh_from_db()
        self.assertEqual(regla.config["ranges"][0]["max"], 1.5)


class FallbackAcotadoAlClubTests(TestCase):
    """El último recurso de `templates_for` no puede saltar de club.

    Era un `slug=checkin_fisico` a secas contra toda la base, así que una
    categoría sin plantilla vinculada resolvía a la de OTRO club — las cuatro
    categorías femeninas de U. de Chile levantaban la de Selección Chilena.
    No falseaba ningún conteo, porque todos los llamadores cruzan además por
    `player_id__in`; el problema es la próxima lectura que no lo haga.
    """

    def setUp(self):
        self.uch = Club.objects.create(name="U. de Chile")
        self.otro = Club.objects.create(name="Selección Chilena")
        for club in (self.uch, self.otro):
            dept = Department.objects.create(club=club, name="Físico",
                                             slug="fisico")
            t = ExamTemplate.objects.create(
                name="Check-in físico", slug=w.WELLNESS_SLUG, department=dept,
                config_schema={"fields": [
                    {"key": "sueno", "type": "number", "label": "Sueño",
                     "min": 1, "max": 5},
                ]},
            )
            setattr(self, f"tpl_{'uch' if club is self.uch else 'otro'}", t)
        # Sin la M2M poblada: justo el caso que caía al fallback.
        self.huerfana = Category.objects.create(club=self.uch,
                                                name="SUB-19 F - Femenino")

    def test_una_categoria_sin_plantilla_no_toma_la_de_otro_club(self):
        resueltas = w.templates_for(self.huerfana)
        self.assertEqual([t.id for t in resueltas], [self.tpl_uch.id])
        self.assertNotIn(self.tpl_otro.id, [t.id for t in resueltas])

    def test_un_club_sin_ninguna_plantilla_devuelve_vacio(self):
        """Vacío, no la del vecino. Una lista vacía se ve en pantalla como
        "sin datos"; la plantilla de otro club se ve como un número real."""
        tercero = Club.objects.create(name="Otro club")
        sola = Category.objects.create(club=tercero, name="Primer Equipo")
        self.assertEqual(w.templates_for(sola), [])

    def test_la_vinculada_sigue_ganando(self):
        cat = Category.objects.create(club=self.uch, name="Primer Equipo")
        self.tpl_uch.applicable_categories.add(cat)
        self.assertEqual([t.id for t in w.templates_for(cat)], [self.tpl_uch.id])
