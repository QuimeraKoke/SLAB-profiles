"""La puerta del comparador de jugadores.

El endpoint expone los valores de CUALQUIER jugador del club a quien lo llame,
plantel profesional incluido. Ocultar el link del sidebar es cosmético; esto es
la puerta de verdad, y por eso tiene sus propios tests.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from ninja.errors import HttpError

from core.models import Category, Club, Department, Player, Position
from exams.models import ExamTemplate


class PlayerComparisonEndpointTests(TestCase):
    def setUp(self):
        from api.routers import get_player_comparison
        self.vista = get_player_comparison
        self.rf = RequestFactory()

        self.club = Club.objects.create(name="FC")
        self.dept = Department.objects.create(club=self.club, name="F", slug="f")
        self.cat = Category.objects.create(club=self.club, name="Sub 17")
        self.cat.departments.add(self.dept)
        self.pos = Position.objects.create(
            club=self.club, abbreviation="DC", name="Defensa central",
            role="Defensa", sort_order=12)
        self.template = ExamTemplate.objects.create(
            name="Salto", slug="salto", department=self.dept,
            config_schema={"fields": [
                {"key": "cmj", "type": "number", "label": "CMJ", "unit": "cm"},
            ]},
        )
        self.template.applicable_categories.add(self.cat)
        self.a = Player.objects.create(
            category=self.cat, position=self.pos, first_name="A", last_name="A")
        self.b = Player.objects.create(
            category=self.cat, position=self.pos, first_name="B", last_name="B")

        self.su = get_user_model().objects.create_superuser("su", "su@x.com", "x")
        self.pelado = get_user_model().objects.create_user("raso", "r@x.com", "x")

    def _pedir(self, user, players=None, metrics="salto:cmj"):
        req = self.rf.get("/players/comparison")
        req.user = user
        ids = players if players is not None else f"{self.a.id},{self.b.id}"
        return self.vista(req, players=ids, metrics=metrics)

    # ── la puerta ────────────────────────────────────────────────────────
    def test_sin_el_permiso_responde_403(self):
        with self.assertRaises(HttpError) as ctx:
            self._pedir(self.pelado)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_con_el_permiso_pasa(self):
        self.pelado.user_permissions.add(
            Permission.objects.get(codename="view_player_comparison"))
        # El permiso se cachea por request; este usuario se recarga limpio.
        usuario = get_user_model().objects.get(pk=self.pelado.pk)
        out = self._pedir(usuario)
        self.assertEqual(len(out["players"]), 2)

    def test_el_superusuario_pasa_sin_permiso_explicito(self):
        out = self._pedir(self.su)
        self.assertEqual(len(out["players"]), 2)

    # ── validación de entrada ────────────────────────────────────────────
    def test_un_solo_jugador_es_valido(self):
        # Ver la ficha de un jugador contra la vara de su línea es una lectura
        # completa: obligar a elegir un segundo para mirar al primero no tiene
        # sentido.
        out = self._pedir(self.su, players=str(self.a.id))
        self.assertEqual([p["name"] for p in out["players"]], ["A A"])

    def test_sin_jugadores_es_422(self):
        with self.assertRaises(HttpError) as ctx:
            self._pedir(self.su, players=" , ")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_una_metrica_mal_formada_es_422(self):
        with self.assertRaises(HttpError) as ctx:
            self._pedir(self.su, metrics="salto")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_una_plantilla_inexistente_es_404(self):
        with self.assertRaises(HttpError) as ctx:
            self._pedir(self.su, metrics="noexiste:cmj")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_un_jugador_inexistente_es_404(self):
        import uuid
        with self.assertRaises(HttpError) as ctx:
            self._pedir(self.su, players=f"{self.a.id},{uuid.uuid4()}")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_respeta_el_orden_pedido(self):
        out = self._pedir(self.su, players=f"{self.b.id},{self.a.id}")
        self.assertEqual([p["name"] for p in out["players"]], ["B B", "A A"])


class SlugPorClubTests(TestCase):
    """El slug de plantilla NO es único en la plataforma: es único POR CLUB.

    `gps_sesion` existe para la U. de Chile y para la Selección Chilena, con
    `family_id` distinto. Buscar la plantilla sólo por slug dejaba que ganara
    la que devolviera la consulta de último, y una comparación de jugadores de
    un club podía leer la familia del otro: la pantalla salía sin errores y con
    todas las series vacías, que es la peor forma de fallar.
    """

    def setUp(self):
        from api.routers import get_player_comparison
        self.vista = get_player_comparison
        self.rf = RequestFactory()
        self.su = get_user_model().objects.create_superuser("su", "su@x.com", "x")

        self.mio, self.otro = [], []
        for nombre in ("Club A", "Club B"):
            club = Club.objects.create(name=nombre)
            dept = Department.objects.create(club=club, name="F", slug=f"f-{nombre}")
            cat = Category.objects.create(club=club, name="Sub 17")
            cat.departments.add(dept)
            pos = Position.objects.create(
                club=club, abbreviation="DC", name="Defensa central",
                role="Defensa", sort_order=12)
            # MISMO slug en los dos clubes — es el escenario real.
            tpl = ExamTemplate.objects.create(
                name="GPS", slug="gps_sesion", department=dept,
                config_schema={"fields": [
                    {"key": "dist", "type": "number", "label": "Distancia"},
                ]},
            )
            tpl.applicable_categories.add(cat)
            jugadores = [
                Player.objects.create(category=cat, position=pos,
                                      first_name=f"{nombre}{i}", last_name="X")
                for i in range(2)
            ]
            (self.mio if nombre == "Club A" else self.otro).extend([tpl, *jugadores])

    def test_lee_la_plantilla_del_club_de_los_jugadores(self):
        from django.utils import timezone
        from exams.models import ExamResult

        tpl, a, b = self.mio
        ExamResult.objects.create(player=a, template=tpl,
                                  recorded_at=timezone.now(),
                                  result_data={"dist": 9000})
        req = self.rf.get("/players/comparison")
        req.user = self.su
        out = self.vista(req, players=f"{a.id},{b.id}", metrics="gps_sesion:dist")
        self.assertEqual(out["players"][0]["values"]["gps_sesion:dist"]["value"],
                         9000.0,
                         "si agarró la plantilla del otro club, esto es None")


class RutasGolosasTests(TestCase):
    """Que ninguna ruta de un solo segmento bajo /players/ vuelva a ser golosa.

    Historia: `/api/players/comparison` es una ruta LITERAL, y convive con
    `/api/players/{player_id}`. Con el converter por defecto de Ninja, el
    patrón genérico se come cualquier segmento —"comparison" incluido— y el
    comparador respondía 500 al intentar parsearlo como UUID. Acotar el GET no
    alcanzó: el PATCH y el DELETE seguían golosos, matcheaban el path y
    convertían el GET en un 405.

    Es el mismo incidente que ya había pasado con `/results/bulk` y
    `/results/team`. Por eso esto es un test y no un comentario: el próximo
    `@api.post("/players/{algo}")` lo rompe otra vez sin que nadie lo note
    hasta que un usuario vea un 405.
    """

    def test_ninguna_ruta_de_un_segmento_usa_el_converter_goloso(self):
        import re
        from pathlib import Path

        fuente = Path(__file__).with_name("routers.py").read_text()
        golosas = re.findall(
            r'@api\.(?:get|post|patch|put|delete)\("(/players/\{(?!uuid:)[a-z_]+\})"',
            fuente,
        )
        self.assertEqual(
            golosas, [],
            "Usá {uuid:player_id}: con el converter por defecto estas rutas "
            "se comen /players/comparison y cualquier otra ruta literal.",
        )


class SchemaCompletoTests(TestCase):
    """Que el schema de respuesta declare TODO lo que el servicio manda.

    Ninja serializa contra el schema y descarta en silencio lo que no figura.
    Un campo agregado al servicio y olvidado en el schema no rompe ningún test
    que llame a la vista directo —el dict está completo ahí— pero nunca llega
    al navegador. Fue exactamente lo que pasó con `percentiles` y `bands`: el
    radar recibía un payload sin percentiles y no se dibujaba, sin un solo
    error en ninguna parte.
    """

    def test_el_payload_serializado_conserva_percentiles_y_bandas(self):
        from api.schemas import PlayerComparisonOut

        crudo = {
            "metrics": [{
                "key": "t:f", "field_key": "f", "template": "t",
                "template_label": "T", "label": "F", "unit": "s",
                "direction_of_good": "down",
            }],
            "players": [{
                "id": "1", "name": "A", "category": "Sub 17", "position": "DC",
                "line": "Defensa", "photo_url": None, "date_of_birth": None,
                "values": {"t:f": {"value": 1.0, "recorded_at": "x"}},
                "series": {"t:f": []},
                "bands": {"t:f": [{"label": "Bueno", "max": 2}]},
                "band_labels": {"t:f": "Bueno"},
            }],
            "benchmark": {},
            "percentiles": {"1": {"t:f": {"pct": 50, "n": 9, "value": 1.0}}},
        }
        salida = PlayerComparisonOut(**crudo).dict()

        self.assertIsNotNone(salida.get("percentiles"),
                             "sin esto el radar no se dibuja")
        jugador = salida["players"][0]
        self.assertEqual(jugador["band_labels"], {"t:f": "Bueno"})
        self.assertEqual(len(jugador["bands"]["t:f"]), 1)
