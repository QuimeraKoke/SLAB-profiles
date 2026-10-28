"""Cargar GPS + MD+2 behind `core.view_gps_upload` / `core.view_md2`.

Opposite posture to `view_development`: the three base roles (Editor, Solo
Lectura, Administrador) DO hold both — the Primer Equipo staff must keep the
screens — and the "… Formativo" twins are those roles without them. So the
tests pin both halves: a formativo role is shut out of every endpoint, and a
re-run of `seed_role_groups` (which `.set()`s each group's permissions) neither
strips the screens from the base roles nor slips them into the twins.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase

from api.auth import issue_token
from core.models import Category, Club, Department, StaffMembership

User = get_user_model()

SCREENS = ["core.view_gps_upload", "core.view_md2"]


class OperativaScreenPermissionTests(TestCase):
    def setUp(self):
        call_command("seed_role_groups", "--skip-backfill", stdout=open("/dev/null", "w"))
        self.club = Club.objects.create(name="FC")
        Department.objects.create(club=self.club, name="Físico", slug="fis")
        self.category = Category.objects.create(club=self.club, name="Serie 2010", cohort_year=2010)

    def _user(self, role: str):
        n = User.objects.count()
        user = User.objects.create_user(username=f"{role}-{n}", password="x")
        user.groups.add(Group.objects.get(name=role))
        m = StaffMembership.objects.create(user=user, club=self.club, all_departments=True)
        m.categories.add(self.category)
        return User.objects.get(pk=user.pk)

    def _client(self, user):
        return Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(user)[0]}")

    def _requests(self, c):
        cid = str(self.category.id)
        return {
            "GET /md2": c.get("/api/md2", {"category_id": cid}),
            "GET /md2/version": c.get("/api/md2/version", {"category_id": cid, "event_id": cid}),
            "POST /md2": c.post("/api/md2", {"category_id": cid, "event_id": cid, "valores": []},
                                content_type="application/json"),
            # With a file: Ninja validates the form before the view's
            # decorators run, so a missing field would 422 ahead of the gate.
            "POST /gps-sessions/upload": c.post("/api/gps-sessions/upload", {
                "category_id": cid, "file": SimpleUploadedFile("gps.xlsx", b"x"),
            }),
        }

    def test_formativo_roles_are_shut_out(self):
        for role in ("Editor Formativo", "Lectura Formativo"):
            for name, resp in self._requests(self._client(self._user(role))).items():
                self.assertEqual(resp.status_code, 403, f"{role}: {name}")

    def test_base_roles_keep_the_screens(self):
        for role in ("Editor", "Solo Lectura", "Administrador"):
            user = self._user(role)
            for perm in SCREENS:
                self.assertTrue(user.has_perm(perm), f"{role}: {perm}")
        # Editor gets past the gate (whatever comes after it is not a 403).
        resp = self._client(self._user("Editor")).get(
            "/api/md2", {"category_id": str(self.category.id)})
        self.assertNotEqual(resp.status_code, 403)

    def test_formativo_twin_is_its_base_role_minus_the_screens(self):
        for base, twin in (("Editor", "Editor Formativo"), ("Solo Lectura", "Lectura Formativo")):
            base_perms = set(Group.objects.get(name=base).permissions.values_list("codename", flat=True))
            twin_perms = set(Group.objects.get(name=twin).permissions.values_list("codename", flat=True))
            self.assertEqual(base_perms - twin_perms, {"view_gps_upload", "view_md2"}, twin)
            self.assertEqual(twin_perms - base_perms, set(), twin)

    def test_managers_can_assign_the_formativo_roles(self):
        from api.routers import _assignable_roles

        roles = _assignable_roles(self._user("Administrador"))
        self.assertIn("Editor Formativo", roles)
        self.assertIn("Lectura Formativo", roles)
        self.assertNotIn("Administrador", roles)
