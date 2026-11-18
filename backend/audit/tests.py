"""Audit trail: change log, access log, append-only guarantee, club isolation."""
from datetime import date
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import DatabaseError, transaction
from django.test import TestCase

from api.auth import issue_token
from audit import context
from audit.models import AccessEvent, BackupRun, ChangeEvent
from core.models import Category, Club, DailyNote, Player, StaffMembership


class AuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_role_groups", skip_backfill=True)
        cls.club = Club.objects.create(name="Test FC")
        cls.other = Club.objects.create(name="Other FC")
        cls.cat = Category.objects.create(club=cls.club, name="Sub-20")
        cls.other_cat = Category.objects.create(club=cls.other, name="Sub-20")
        cls.manager = User.objects.create_user("mgr@test.cl", email="mgr@test.cl", password="pw")
        StaffMembership.objects.create(user=cls.manager, club=cls.club, all_categories=True, all_departments=True)
        cls.manager.groups.add(Group.objects.get(name="Administrador"))
        cls.editor = User.objects.create_user("ed@test.cl", email="ed@test.cl", password="pw")
        StaffMembership.objects.create(user=cls.editor, club=cls.club, all_categories=True, all_departments=True)
        cls.editor.groups.add(Group.objects.get(name="Editor"))
        cls.outsider = User.objects.create_user("mgr@other.cl", email="mgr@other.cl", password="pw")
        StaffMembership.objects.create(user=cls.outsider, club=cls.other, all_categories=True, all_departments=True)
        cls.outsider.groups.add(Group.objects.get(name="Administrador"))

    def setUp(self):
        context.reset()

    def _auth(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {issue_token(user)[0]}"}

    def _player(self, cat=None, **kw):
        return Player.objects.create(category=cat or self.cat, first_name="Ana", last_name="Rojas", **kw)

    # ── change log ────────────────────────────────────────────────────────

    def test_crear_editar_y_borrar_dejan_rastro_con_autor_y_valores(self):
        context.set_user(self.editor)
        p = self._player()
        note = DailyNote.objects.create(player=p, kind="pauta", date=date(2026, 11, 17), text="Trote 20'",
                                        created_by=self.editor)
        note.text = "Trote 10'"
        note.save()
        note.save()  # sin cambios: no debe registrar nada
        note_id = note.pk
        note.delete()

        ev = list(ChangeEvent.objects.filter(model="core.DailyNote").order_by("id"))
        self.assertEqual([e.action for e in ev], ["create", "update", "delete"])
        self.assertTrue(all(e.actor_email == "ed@test.cl" and e.club_id == str(self.club.pk) for e in ev))
        self.assertEqual(ev[1].changes["text"], ["Trote 20'", "Trote 10'"])
        self.assertEqual(ev[2].changes["text"], "Trote 10'")  # contenido al borrar
        self.assertEqual(ev[2].object_id, str(note_id))
        self.assertEqual(ev[0].player_name, "Ana Rojas")

    def test_sin_usuario_queda_como_sistema(self):
        with context.acting_as("sync:catapult"):
            self._player()
        e = ChangeEvent.objects.get(model="core.Player")
        self.assertEqual((e.actor_id, e.source), (None, "sync:catapult"))

    def test_cambio_de_contrasena_se_registra_sin_valores(self):
        context.set_user(self.manager)
        self.editor.set_password("nueva")
        self.editor.save()
        e = ChangeEvent.objects.filter(model="auth.User", action="update").latest("id")
        self.assertEqual(e.changes["contraseña"], ["(oculta)", "(cambiada)"])
        self.assertNotIn("password", e.changes)

    def test_registro_no_se_puede_editar_ni_borrar(self):
        self._player()
        e = ChangeEvent.objects.latest("id")
        with self.assertRaises(DatabaseError), transaction.atomic():
            ChangeEvent.objects.filter(pk=e.pk).update(actor_email="otro")
        with self.assertRaises(DatabaseError), transaction.atomic():
            ChangeEvent.objects.filter(pk=e.pk).delete()
        with self.assertRaises(DatabaseError), transaction.atomic():
            AccessEvent.objects.create(kind="ficha", actor_id=1)
            AccessEvent.objects.all().delete()

    def test_si_el_registro_falla_el_guardado_sigue(self):
        from django.db import connection
        with transaction.atomic():
            with connection.cursor() as c:
                c.execute("ALTER TABLE audit_changeevent RENAME TO audit_tmp")
            p = self._player()  # the audit insert fails inside the savepoint
            p.first_name = "Bea"
            p.save()
            self.assertEqual(Player.objects.get(pk=p.pk).first_name, "Bea")
            with connection.cursor() as c:
                c.execute("ALTER TABLE audit_tmp RENAME TO audit_changeevent")

    # ── access log ────────────────────────────────────────────────────────

    def test_abrir_la_ficha_queda_registrado_una_vez_por_media_hora(self):
        p = self._player()
        for _ in range(3):
            self.assertEqual(self.client.get(f"/api/players/{p.pk}", **self._auth(self.manager)).status_code, 200)
        ev = AccessEvent.objects.filter(kind="ficha")
        self.assertEqual(ev.count(), 1)
        self.assertEqual((ev[0].actor_email, ev[0].player_name, ev[0].club_id),
                         ("mgr@test.cl", "Ana Rojas", str(self.club.pk)))

    def test_ingreso_queda_registrado(self):
        r = self.client.post("/api/auth/login", {"email": "ed@test.cl", "password": "pw"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(AccessEvent.objects.filter(kind="ingreso", actor_email="ed@test.cl").exists())

    # ── the club's view ───────────────────────────────────────────────────

    def test_solo_administradores_y_cada_club_ve_lo_suyo(self):
        context.set_user(self.manager)
        self._player()
        context.set_user(self.outsider)
        self._player(cat=self.other_cat, national_id="x")
        context.reset()

        self.assertEqual(self.client.get("/api/audit/changes", **self._auth(self.editor)).status_code, 403)
        mine = self.client.get("/api/audit/changes", **self._auth(self.manager)).json()["rows"]
        self.assertTrue(any(r["actor"] == "mgr@test.cl" for r in mine))
        self.assertFalse(any(r["actor"] == "mgr@other.cl" for r in mine))
        # The club id in the query is ignored for a club manager.
        theirs = self.client.get(f"/api/audit/changes?club_id={self.other.pk}", **self._auth(self.manager)).json()
        self.assertFalse(any(r["actor"] == "mgr@other.cl" for r in theirs["rows"]))

        csv = self.client.get("/api/audit/changes.csv", **self._auth(self.manager))
        self.assertEqual(csv.status_code, 200)
        self.assertIn("Fecha;Usuario;Acción", csv.content.decode("utf-8-sig"))

    def test_respaldos_muestran_el_ultimo_bueno(self):
        BackupRun.objects.create(status=BackupRun.OK, size_bytes=10, tables=5, key="diario/a.dump")
        BackupRun.objects.create(status=BackupRun.FAILED, error="boom")
        d = self.client.get("/api/audit/backups", **self._auth(self.manager)).json()
        self.assertEqual(d["last_ok"]["tables"], 5)
        self.assertEqual(d["runs"][0]["status"], "failed")


class BackupTests(TestCase):
    def test_un_respaldo_sin_tablas_falla(self):
        from audit import backup
        done = mock.Mock(stdout="")
        with mock.patch.object(backup.subprocess, "run", return_value=done):
            run = backup.run_backup(upload=False)
        self.assertEqual(run.status, BackupRun.FAILED)
        self.assertIn("no contiene", run.error)
