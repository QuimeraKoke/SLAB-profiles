"""Desarrollo + Crecimiento behind `core.view_development`, granted to nobody.

The five endpoints these two modules read are the whole surface, so the tests
walk all five rather than sampling one: a gate that covers four of five is not a
gate. `/teams` is the one that would be easiest to forget, because its name
sounds generic enough to look like shared infrastructure — it isn't, it feeds the
Desarrollo table only.

The second half of the file is the part worth keeping: it asserts the permission
is not reachable by any route other than an explicit grant. A feature flag that
silently ends up inside "Solo Lectura" on the next `seed_role_groups` run is
worse than no flag, because nobody would notice.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase

from api.auth import issue_token
from core.models import Category, Club, Department, Player, StaffMembership

User = get_user_model()

ENDPOINTS = [
    "/api/development/cohorts",
    "/api/fixtures/upcoming",
    "/api/teams",
    "/api/maturation/overview",
]


class DevelopmentPermissionTests(TestCase):
    def setUp(self):
        self.club = Club.objects.create(name="FC")
        self.dept = Department.objects.create(club=self.club, name="Físico", slug="fis")
        self.category = Category.objects.create(
            club=self.club, name="Serie 2014", cohort_year=2014)
        self.player = Player.objects.create(
            category=self.category, first_name="A", last_name="B")

        self.user = User.objects.create_user(username="staff", password="x")
        m = StaffMembership.objects.create(
            user=self.user, club=self.club, all_departments=True)
        m.categories.add(self.category)

    def _client(self, user):
        from django.test import Client

        return Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(user)[0]}")

    def _paths(self):
        return ENDPOINTS + [f"/api/players/{self.player.id}/physical-context"]

    # ── the gate ────────────────────────────────────────────────────────
    def test_every_endpoint_is_closed_without_the_permission(self):
        c = self._client(self.user)
        for path in self._paths():
            self.assertEqual(c.get(path).status_code, 403, path)

    def test_the_permission_opens_every_endpoint(self):
        perm = Permission.objects.get(
            content_type__app_label="core", codename="view_development")
        self.user.user_permissions.add(perm)
        self.user = User.objects.get(pk=self.user.pk)     # drop the perm cache

        c = self._client(self.user)
        for path in self._paths():
            self.assertNotEqual(c.get(path).status_code, 403, path)

    def test_a_superuser_passes(self):
        """Django's default, which the project's `_has_perm` follows.

        Worth pinning: it is the only way the module is reachable today, and how
        an admin verifies the screens still work while nobody else can.

        The superuser gets a membership because these endpoints require one
        independently of the permission ("Sin membresía de club") — without it
        the 403 would come from the wrong place and this test would pass for a
        reason that has nothing to do with the gate.
        """
        su = User.objects.create_superuser(username="root", password="x")
        m = StaffMembership.objects.create(
            user=su, club=self.club, all_departments=True)
        m.categories.add(self.category)
        c = self._client(su)
        for path in self._paths():
            self.assertNotEqual(c.get(path).status_code, 403, path)

    def test_unrelated_permissions_do_not_open_it(self):
        # Being an Editor is not enough, which is the entire point.
        for codename in ("view_player", "change_player", "add_player"):
            perm = Permission.objects.filter(
                content_type__app_label="core", codename=codename).first()
            if perm:
                self.user.user_permissions.add(perm)
        self.user = User.objects.get(pk=self.user.pk)

        c = self._client(self.user)
        self.assertEqual(c.get("/api/teams").status_code, 403)

    # ── granted to nobody, and not sweepable ────────────────────────────
    def test_no_group_carries_it(self):
        from django.core.management import call_command

        call_command("seed_role_groups", "--skip-backfill", verbosity=0)

        for group in Group.objects.all():
            self.assertFalse(
                group.permissions.filter(codename="view_development").exists(),
                f"el grupo {group.name!r} lo recibió",
            )

    def test_seeding_roles_twice_does_not_grant_it(self):
        # `_perms_for` builds codenames as f"{action}_{model}", so a custom
        # codename can't be swept in. Pinned because that is an implementation
        # detail of another file, and the guarantee here depends on it.
        from django.core.management import call_command

        call_command("seed_role_groups", "--skip-backfill", verbosity=0)
        call_command("seed_role_groups", "--skip-backfill", verbosity=0)

        self.assertFalse(
            Group.objects.filter(
                permissions__codename="view_development").exists())

    def test_no_user_has_it(self):
        # The state the club asked for: the flag exists and reaches nobody.
        holders = [
            u.username for u in User.objects.filter(is_superuser=False)
            if u.has_perm("core.view_development")
        ]
        self.assertEqual(holders, [])

    def test_the_permission_row_exists_so_it_can_be_granted_later(self):
        # A gate nobody can open is a bug, not a policy. The row has to be there
        # for a club manager to hand it out from the admin.
        self.assertTrue(
            Permission.objects.filter(
                content_type__app_label="core",
                codename="view_development",
            ).exists()
        )
