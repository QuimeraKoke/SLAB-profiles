"""Nothing that identifies a person reaches the AI provider; the answer comes
back with the real names."""
import json
import sys
import types
from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import Category, Club, Player, StaffMembership
from dashboards import ai_privacy


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(name, inp, id_="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=id_)


class FakeAnthropic:
    """Records every request; replies from a script of responses."""

    sent: list = []
    script: list = []

    def __init__(self, api_key=None):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        FakeAnthropic.sent.append(json.loads(json.dumps(kw, default=lambda o: getattr(o, "__dict__", str(o)))))
        content, stop = FakeAnthropic.script.pop(0)
        return SimpleNamespace(content=content, stop_reason=stop,
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))


@override_settings(ANTHROPIC_API_KEY="test", AI_PSEUDONYMIZE=True)
class AiPrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Test FC")
        cls.cat = Category.objects.create(club=cls.club, name="Sub-20")
        cls.ana = Player.objects.create(category=cls.cat, first_name="Matías", last_name="Fernández",
                                        second_last_name="Toledo", national_id="12.345.678-9",
                                        date_of_birth=date(2007, 3, 1))
        cls.b1 = Player.objects.create(category=cls.cat, first_name="Diego", last_name="Neira")
        cls.b2 = Player.objects.create(category=cls.cat, first_name="Pablo", last_name="Neira")
        cls.doc = User.objects.create_user("dr@test.cl", email="dr@test.cl", first_name="Rodrigo",
                                           last_name="Molina", password="pw")
        StaffMembership.objects.create(user=cls.doc, club=cls.club)

    def setUp(self):
        FakeAnthropic.sent, FakeAnthropic.script = [], []
        self.pz = ai_privacy.Pseudonymizer.for_club(self.club.id)

    def _leaks(self, blob: str):
        return [w for w in ("Matías", "Matias", "Fernández", "Fernandez", "Neira", "Molina", "12.345.678-9",
                            "dr@test.cl", str(self.ana.pk)) if w in blob]

    # ── the pseudonymizer ─────────────────────────────────────────────────

    def test_nombres_en_todas_sus_formas_y_vuelta(self):
        txt = ("¿Cómo llega MATIAS FERNANDEZ? Fernández Toledo, Fernández y matías fernández. "
               "Habló Rodrigo Molina (dr@test.cl), RUT 12.345.678-9.")
        masked = self.pz.mask(txt)
        self.assertEqual(self._leaks(masked), [], masked)
        back = self.pz.unmask(masked)
        self.assertIn("Matías Fernández", back)
        self.assertIn("Rodrigo Molina", back)
        self.assertIn("[RUT]", back)  # removed, never restored

    def test_apellido_compartido_usa_codigo_reversible(self):
        masked = self.pz.mask("¿Y Neira?")
        self.assertNotIn("Neira", masked)
        self.assertEqual(self.pz.unmask(masked), "¿Y Neira?")

    def test_palabras_comunes_no_se_tocan(self):
        self.assertEqual(self.pz.mask("el doctor revisa la defensa"), "el doctor revisa la defensa")

    def test_payload_estructurado(self):
        out = self.pz.mask_obj({"player": {"id": str(self.ana.pk), "first_name": "Matías",
                                           "last_name": "Fernández", "photo_url": "https://x/foto.jpg",
                                           "date_of_birth": "2007-03-01"},
                                "alerts": [{"message": "CK alto en Matías Fernández"}]})
        blob = json.dumps(out, ensure_ascii=False)
        self.assertEqual(self._leaks(blob), [], blob)
        self.assertNotIn("foto", blob)
        self.assertNotIn("2007", blob)
        self.assertTrue(out["player"]["jugador"].startswith("JUG-"))

    def test_codigos_tolerantes(self):
        tok = self.pz.mask("Matías Fernández")
        n = int(tok.split("-")[1])
        self.assertEqual(self.pz.unmask(f"JUG-{n}"), "Matías Fernández")

    # ── end to end: what actually leaves the server ───────────────────────

    def _run_player_chat(self, question):
        from dashboards.assistant import answer_player_resumen_question
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=FakeAnthropic)}):
            return answer_player_resumen_question(self.ana, [{"role": "user", "content": question}])

    def test_chat_no_envia_identidad_y_responde_con_nombres(self):
        tok = self.pz.mask("Matías Fernández")
        FakeAnthropic.script = [
            ([_tool("estado_jugador", {"jugador": tok})], "tool_use"),
            ([_text(f"{tok} llega bien; revisar con STAFF-01.")], "end_turn"),
        ]
        r = self._run_player_chat("¿Cómo está Matías Fernández? Lo vio Rodrigo Molina.")

        blob = json.dumps(FakeAnthropic.sent, ensure_ascii=False)
        self.assertEqual(self._leaks(blob), [], "datos identificables enviados a la IA")
        # The tool ran on the real player (tokens resolved server-side)…
        tool_result = FakeAnthropic.sent[1]["messages"][-1]["content"][0]["content"]
        self.assertNotIn("No encontré", tool_result)
        self.assertIn(tok, tool_result)
        # …and the staff sees names, not codes.
        self.assertEqual(r["reply"], "Matías Fernández llega bien; revisar con Rodrigo Molina.")

    def test_si_el_seudonimizador_falla_no_se_envia_nada(self):
        with mock.patch.object(ai_privacy.Pseudonymizer, "for_club", side_effect=RuntimeError("boom")):
            r = self._run_player_chat("¿Cómo está Matías Fernández?")
        self.assertEqual(FakeAnthropic.sent, [])
        self.assertIn("No pude consultar", r["reply"])

    def test_readiness_no_envia_el_nombre(self):
        from dashboards.readiness import _agent_readiness
        FakeAnthropic.script = [([_text('{"score": 70, "rationale": "JUG-001 viene cansado", "flags": []}')],
                                  "end_turn")]
        inp = {"jugador": "Matías Fernández", "molestias": ["Rodilla"], "alertas": []}
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=FakeAnthropic)}):
            out = _agent_readiness(inp, 70, "m", self.ana)
        self.assertEqual(self._leaks(json.dumps(FakeAnthropic.sent, ensure_ascii=False)), [])
        self.assertIn("Rodilla", json.dumps(FakeAnthropic.sent, ensure_ascii=False))  # PHI goes, by design
        self.assertNotIn("JUG-", out["rationale"])

    def test_narrativa_no_envia_foto_ni_nombre(self):
        from dashboards.pdf.narrative import generate_player_narrative
        FakeAnthropic.script = [([_text('{"resumen": "JUG-001 estable.", "hallazgos": [], "objetivos": []}')],
                                  "end_turn")]
        payload = {"player": {"id": str(self.ana.pk), "first_name": "Matías", "last_name": "Fernández",
                              "photo_url": "https://s3/foto.jpg"}, "alerts": []}
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=FakeAnthropic)}):
            out = generate_player_narrative(payload)
        blob = json.dumps(FakeAnthropic.sent, ensure_ascii=False)
        self.assertEqual(self._leaks(blob), [])
        self.assertNotIn("foto.jpg", blob)
        self.assertIsNotNone(out)
        self.assertNotIn("JUG-", out["resumen"])


# ── the club's switch and the audit trail of every send ────────────────────

@override_settings(ANTHROPIC_API_KEY="test", AI_PSEUDONYMIZE=True)
class AiGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group
        from django.core.management import call_command

        call_command("seed_role_groups", skip_backfill=True)
        cls.club = Club.objects.create(name="Test FC")
        cls.cat = Category.objects.create(club=cls.club, name="Sub-20")
        cls.ana = Player.objects.create(category=cls.cat, first_name="Matías", last_name="Fernández")
        cls.manager = User.objects.create_user("mgr@test.cl", email="mgr@test.cl", password="pw")
        StaffMembership.objects.create(user=cls.manager, club=cls.club, all_categories=True, all_departments=True)
        cls.manager.groups.add(Group.objects.get(name="Administrador"))
        cls.editor = User.objects.create_user("ed@test.cl", email="ed@test.cl", password="pw")
        StaffMembership.objects.create(user=cls.editor, club=cls.club, all_categories=True, all_departments=True)
        cls.editor.groups.add(Group.objects.get(name="Editor"))

    def setUp(self):
        from audit import context
        context.reset()
        FakeAnthropic.sent, FakeAnthropic.script = [], []

    def _chat(self, q="¿Cómo está?"):
        from dashboards.assistant import answer_player_resumen_question
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=FakeAnthropic)}):
            return answer_player_resumen_question(self.ana, [{"role": "user", "content": q}])

    def _auth(self, user):
        from api.auth import issue_token
        return {"HTTP_AUTHORIZATION": f"Bearer {issue_token(user)[0]}"}

    def test_cada_envio_queda_en_el_registro(self):
        from audit import context
        from audit.models import AccessEvent
        context.set_user(self.manager)
        FakeAnthropic.script = [([_text("Bien.")], "end_turn")]
        self._chat()
        ev = AccessEvent.objects.get(kind="ia")
        self.assertEqual(ev.player_id, str(self.ana.pk))
        self.assertEqual(ev.actor_email, "mgr@test.cl")
        self.assertIn("Asistente del resumen", ev.detail)
        self.assertIn("seudonimizado", ev.detail)

    def test_con_la_ia_apagada_no_sale_nada(self):
        from dashboards.pdf.narrative import generate_player_narrative
        from dashboards.readiness import _agent_readiness
        Club.objects.filter(pk=self.club.pk).update(ai_enabled=False)
        r = self._chat()
        self.assertIn("desactivada", r["reply"])
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=FakeAnthropic)}):
            self.assertIsNone(_agent_readiness({"molestias": []}, 70, "m", self.ana))
            self.assertIsNone(generate_player_narrative(
                {"player": {"id": str(self.ana.pk), "first_name": "Matías", "last_name": "Fernández"}}))
        self.assertEqual(FakeAnthropic.sent, [])

    def test_si_no_se_puede_registrar_no_se_envia(self):
        with mock.patch("dashboards.ai_privacy._record_send", side_effect=RuntimeError("db")):
            r = self._chat()
        self.assertEqual(FakeAnthropic.sent, [])
        self.assertIn("No pude consultar", r["reply"])

    def test_sin_club_no_se_envia(self):
        from dashboards.pdf.narrative import generate_player_narrative
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=FakeAnthropic)}):
            self.assertIsNone(generate_player_narrative({"alerts": []}))
        self.assertEqual(FakeAnthropic.sent, [])

    def test_administrador_cambia_el_interruptor_y_queda_registrado(self):
        from audit.models import ChangeEvent
        r = self.client.get("/api/audit/ai-settings", **self._auth(self.manager))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ai_enabled"])
        r = self.client.put("/api/audit/ai-settings", data={"ai_enabled": False},
                            content_type="application/json", **self._auth(self.manager))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["ai_enabled"])
        self.club.refresh_from_db()
        self.assertFalse(self.club.ai_enabled)
        ev = ChangeEvent.objects.get(model="core.Club", action="update")
        self.assertEqual(ev.changes["ai_enabled"], [True, False])
        self.assertEqual(ev.actor_email, "mgr@test.cl")
        me = self.client.get("/api/auth/me", **self._auth(self.manager)).json()
        self.assertFalse(me["membership"]["club"]["ai_enabled"])

    def test_editor_no_puede_cambiarlo(self):
        r = self.client.put("/api/audit/ai-settings", data={"ai_enabled": False},
                            content_type="application/json", **self._auth(self.editor))
        self.assertEqual(r.status_code, 403)
        self.club.refresh_from_db()
        self.assertTrue(self.club.ai_enabled)
