"""Passwords: the forced change after a temporary password, the user's own
change, and "Olvidé mi contraseña" links (`core.account`, `/auth/password/*`).

Pins: a temporary password flags the account until the user picks their own;
the forgot form answers the same for unknown emails and emails once per
cooldown; a reset link works once and signs the user in.
"""
from __future__ import annotations

import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from api.auth import issue_token
from core.models import AccountSecurity, Club

GOOD = "Cancha-Larga-2026"


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_BASE_URL="https://app.test",
)
class PasswordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_role_groups", "--skip-backfill", stdout=open("/dev/null", "w"))
        cls.club = Club.objects.create(name="Club Test")
        cls.root = User.objects.create_superuser("root", "root@slab.cl", "x")
        cls.ana = User.objects.create_user("ana@club.cl", "ana@club.cl", "vieja-Clave-99")

    def setUp(self):
        cache.clear()

    def _c(self, user=None) -> Client:
        if user is None:
            return Client()
        return Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(user)[0]}")

    def _post(self, client, url, body):
        return client.post(url, body, content_type="application/json")

    def _me(self, user) -> dict:
        return self._c(user).get("/api/auth/me").json()["user"]

    def test_una_contrasena_temporal_obliga_a_cambiarla(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self._post(self._c(self.root), "/api/users", {
                "email": "nuevo@club.cl", "first_name": "N", "last_name": "U",
                "role": "Editor", "club_id": str(self.club.id),
                "all_categories": True, "all_departments": True,
            })
        self.assertEqual(r.status_code, 200, r.content)
        nuevo = User.objects.get(email="nuevo@club.cl")
        self.assertTrue(self._me(nuevo)["must_change_password"])

        r = self._post(self._c(nuevo), "/api/auth/password/change", {
            "current_password": r.json()["temp_password"], "new_password": GOOD})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["user"]["must_change_password"])
        nuevo.refresh_from_db()
        self.assertTrue(nuevo.check_password(GOOD))

    def test_el_reset_del_administrador_tambien_es_temporal(self):
        r = self._post(self._c(self.root), f"/api/users/{self.ana.id}/reset-password", {})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(self._me(self.ana)["must_change_password"])

    def test_cambio_propio_valida(self):
        c = self._c(self.ana)
        r = self._post(c, "/api/auth/password/change",
                       {"current_password": "mala", "new_password": GOOD})
        self.assertEqual(r.status_code, 400)
        r = self._post(c, "/api/auth/password/change",
                       {"current_password": "vieja-Clave-99", "new_password": "12345678"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("común", r.json()["detail"], "mensajes de Django en castellano")
        self.assertFalse(AccountSecurity.objects.filter(must_change_password=True).exists())

    def test_olvide_mi_contrasena_no_revela_quien_existe(self):
        a = self._post(self._c(), "/api/auth/password/forgot", {"email": "nadie@club.cl"})
        b = self._post(self._c(), "/api/auth/password/forgot", {"email": "ANA@club.cl"})
        self.assertEqual((a.status_code, a.json()), (b.status_code, b.json()))
        self.assertEqual([m.to for m in mail.outbox], [["ana@club.cl"]])

        self._post(self._c(), "/api/auth/password/forgot", {"email": "ana@club.cl"})
        self.assertEqual(len(mail.outbox), 1, "un correo por cuenta cada pocos minutos")

    def test_el_enlace_sirve_una_vez_e_inicia_sesion(self):
        self._post(self._c(), "/api/auth/password/forgot", {"email": "ana@club.cl"})
        url = re.search(r"https://app\.test/restablecer\?\S+", mail.outbox[0].body).group(0)
        uid, token = re.search(r"uid=([^&]+)&token=(\S+)", url).groups()

        r = self._post(self._c(), "/api/auth/password/reset",
                       {"uid": uid, "token": token, "password": GOOD})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["user"]["email"], "ana@club.cl")
        self.assertIn("access_token", r.json())
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.check_password(GOOD))

        r = self._post(self._c(), "/api/auth/password/reset",
                       {"uid": uid, "token": token, "password": "Otra-Clave-2026"})
        self.assertEqual(r.status_code, 400, "el enlace ya se usó")

    def test_enlace_invalido(self):
        r = self._post(self._c(), "/api/auth/password/reset",
                       {"uid": "xx", "token": "yy", "password": GOOD})
        self.assertEqual(r.status_code, 400)

    def test_limite_por_ip(self):
        for _ in range(10):
            self._post(self._c(), "/api/auth/password/forgot", {"email": "x@y.cl"})
        r = self._post(self._c(), "/api/auth/password/forgot", {"email": "x@y.cl"})
        self.assertEqual(r.status_code, 429)
