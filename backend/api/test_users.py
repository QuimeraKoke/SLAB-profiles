"""Tests for the Usuarios admin module (`/api/users*`).

Covers the manager guardrails that can't be trusted to the UI: permission
gating, club isolation, scope-subset enforcement, the "managers can't mint
managers" rule, and the welcome/reset email dispatch.
"""

import json

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from api.auth import issue_token
from core.models import Category, Club, Department, StaffMembership


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class UsersApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Seed the real role groups (Editor / Solo Lectura / Administrador).
        call_command("seed_role_groups", skip_backfill=True)

        cls.club = Club.objects.create(name="Test FC")
        cls.other_club = Club.objects.create(name="Other FC")
        cls.cat_a = Category.objects.create(club=cls.club, name="Primer Equipo")
        cls.cat_b = Category.objects.create(club=cls.club, name="Sub-20")
        cls.other_cat = Category.objects.create(club=cls.other_club, name="Primer Equipo")
        cls.dept = Department.objects.create(club=cls.club, name="Médico", slug="medico")

        # Full-scope manager (Administrador).
        cls.manager = User.objects.create_user(
            "mgr@test.cl", email="mgr@test.cl", password="pw",
        )
        StaffMembership.objects.create(
            user=cls.manager, club=cls.club,
            all_categories=True, all_departments=True,
        )
        cls.manager.groups.add(Group.objects.get(name="Administrador"))

        # Editor without user-management perms.
        cls.editor = User.objects.create_user(
            "ed@test.cl", email="ed@test.cl", password="pw",
        )
        StaffMembership.objects.create(
            user=cls.editor, club=cls.club,
            all_categories=True, all_departments=True,
        )
        cls.editor.groups.add(Group.objects.get(name="Editor"))

        # A user living in a different club (isolation target).
        cls.outsider = User.objects.create_user(
            "out@other.cl", email="out@other.cl", password="pw",
        )
        StaffMembership.objects.create(
            user=cls.outsider, club=cls.other_club, all_categories=True,
        )
        cls.outsider.groups.add(Group.objects.get(name="Editor"))

    # ----- helpers ---------------------------------------------------------

    def _auth(self, user):
        token, _ = issue_token(user)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _post(self, path, payload, user):
        return self.client.post(
            path, data=json.dumps(payload),
            content_type="application/json", **self._auth(user),
        )

    def _patch(self, path, payload, user):
        return self.client.patch(
            path, data=json.dumps(payload),
            content_type="application/json", **self._auth(user),
        )

    def _base_payload(self, **over):
        payload = {
            "first_name": "Nueva",
            "last_name": "Persona",
            "email": "nueva@test.cl",
            "role": "Editor",
            "all_categories": True,
            "all_departments": True,
            "is_active": True,
        }
        payload.update(over)
        return payload

    # ----- tests -----------------------------------------------------------

    def test_editor_cannot_view_users(self):
        res = self.client.get("/api/users", **self._auth(self.editor))
        self.assertEqual(res.status_code, 403)

    def test_manager_can_list_own_club_only(self):
        res = self.client.get("/api/users", **self._auth(self.manager))
        self.assertEqual(res.status_code, 200)
        emails = {u["email"] for u in res.json()}
        self.assertIn("mgr@test.cl", emails)
        self.assertIn("ed@test.cl", emails)
        self.assertNotIn("out@other.cl", emails)  # isolation

    def test_manager_creates_scoped_user_and_emails_password(self):
        res = self._post(
            "/api/users",
            self._base_payload(
                all_categories=False,
                category_ids=[str(self.cat_a.id)],
                all_departments=False,
                department_ids=[str(self.dept.id)],
            ),
            self.manager,
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        temp = body["temp_password"]
        self.assertTrue(temp)

        created = User.objects.get(email="nueva@test.cl")
        self.assertEqual(created.username, "nueva@test.cl")
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertTrue(created.check_password(temp))
        self.assertEqual(
            list(created.groups.values_list("name", flat=True)), ["Editor"],
        )
        m = created.staff_membership
        self.assertEqual(m.club_id, self.club.id)
        self.assertFalse(m.all_categories)
        self.assertEqual(list(m.categories.all()), [self.cat_a])
        self.assertEqual(list(m.departments.all()), [self.dept])

        # Welcome email delivered with the temp password in the body.
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["nueva@test.cl"])
        self.assertIn(temp, msg.body)
        self.assertIn("Bienvenido", msg.subject)

    def test_duplicate_email_rejected(self):
        res = self._post(
            "/api/users", self._base_payload(email="ed@test.cl"), self.manager,
        )
        self.assertEqual(res.status_code, 400)

    def test_manager_cannot_assign_administrador_role(self):
        res = self._post(
            "/api/users", self._base_payload(role="Administrador"), self.manager,
        )
        self.assertEqual(res.status_code, 400)

    def test_scope_subset_enforced(self):
        # Manager scoped to cat_a only cannot grant cat_b.
        limited = User.objects.create_user(
            "limited@test.cl", email="limited@test.cl", password="pw",
        )
        lm = StaffMembership.objects.create(
            user=limited, club=self.club, all_categories=False, all_departments=True,
        )
        lm.categories.set([self.cat_a])
        limited.groups.add(Group.objects.get(name="Administrador"))

        # Cannot grant "all categories" (wider than own scope).
        res = self._post(
            "/api/users",
            self._base_payload(all_categories=True, email="a@test.cl"),
            limited,
        )
        self.assertEqual(res.status_code, 403)

        # Cannot grant a specific category outside own scope.
        res = self._post(
            "/api/users",
            self._base_payload(
                all_categories=False, category_ids=[str(self.cat_b.id)],
                email="b@test.cl",
            ),
            limited,
        )
        self.assertEqual(res.status_code, 403)

        # Granting the in-scope category works.
        res = self._post(
            "/api/users",
            self._base_payload(
                all_categories=False, category_ids=[str(self.cat_a.id)],
                email="c@test.cl",
            ),
            limited,
        )
        self.assertEqual(res.status_code, 200, res.content)

    def test_manager_cannot_touch_other_club_user(self):
        res = self._patch(
            f"/api/users/{self.outsider.id}", {"first_name": "Hax"}, self.manager,
        )
        self.assertEqual(res.status_code, 404)

    def test_reset_password_rotates_hash_and_emails(self):
        target = User.objects.create_user(
            "t@test.cl", email="t@test.cl", password="original",
        )
        StaffMembership.objects.create(user=target, club=self.club, all_categories=True)
        old_hash = target.password

        res = self._post(f"/api/users/{target.id}/reset-password", {}, self.manager)
        self.assertEqual(res.status_code, 200, res.content)
        temp = res.json()["temp_password"]

        target.refresh_from_db()
        self.assertNotEqual(target.password, old_hash)
        self.assertTrue(target.check_password(temp))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(temp, mail.outbox[0].body)
