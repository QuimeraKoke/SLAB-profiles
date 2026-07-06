"""End-to-end demo workspace for the Chile men's national team (La Roja).

Bootstraps a SECOND, self-contained showcase club alongside the Universidad
de Chile demo — same platform, every department, every exam — but with
**in-range data** (`seed_fake_exams --healthy`) so the workspace demos clean:
numeric metrics land in their good reference band, wellness reads high, and
nobody trips a band alert. A handful of players are then deliberately set to
injured / recovery / reintegration so the availability surfaces aren't all
green. Finally a scoped staff login is created so you can sign in and explore.

Run (fresh):

    docker compose exec backend python manage.py seed_chile_demo

Re-run cleanly (wipe + regenerate this club's results):

    docker compose exec backend python manage.py seed_chile_demo --reset-fake-exams
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


# A few players set to non-available states (the rest stay available).
# (last_name, stage, injury type, body part, severity).
STATUS_PLAN: list[tuple[str, str, str, str, str]] = [
    ("Sierralta", "injured",       "Muscular",    "Muslo der.",       "Moderada"),
    ("Morales",   "injured",       "Ligamentosa", "Tobillo izq.",     "Moderada"),
    ("Pizarro",   "recovery",      "Muscular",    "Pantorrilla der.", "Leve"),
    ("Cepeda",    "recovery",      "Tendinosa",   "Rodilla izq.",     "Moderada"),
    ("Méndez",    "reintegration", "Muscular",    "Isquiotibial izq.","Leve"),
]

_STAGE_PROGRESSION = {
    "injured":       ["injured"],
    "recovery":      ["injured", "recovery"],
    "reintegration": ["injured", "recovery", "reintegration"],
}


class Command(BaseCommand):
    help = "Bootstrap the Chile national team demo workspace (all exams, in-range data)."

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Selección Chilena")
        parser.add_argument("--category", default="Selección Nacional")
        parser.add_argument("--weeks", type=int, default=13,
                            help="History window for generated results (default: 13).")
        parser.add_argument("--reset-fake-exams", action="store_true",
                            help="Wipe this club's results before regenerating.")
        parser.add_argument("--skip-fake-exams", action="store_true")
        parser.add_argument("--email", default="demo@laroja.cl",
                            help="Login email for the workspace staff user.")
        parser.add_argument("--password", default="laroja2026",
                            help="Login password for the workspace staff user.")

    def handle(self, *args, **opts):
        club = opts["club"]
        category = opts["category"]

        common = {
            "create_if_missing": True,
            "all_applicable_categories": True,
            "club": club,
            "unlock": True,
        }
        # Every department's exams. checkin_fisico has no
        # --all-applicable-categories flag (auto-attaches to its dept's cats).
        template_steps: list[tuple[str, dict]] = [
            ("seed_pentacompartimental", {**common, "department_slug": "nutricional"}),
            ("seed_lesiones",            {**common, "department_slug": "medico"}),
            ("seed_medicacion_template", {**common, "department_slug": "medico"}),
            ("seed_medico_indicators",   {**common, "department_slug": "medico"}),
            ("seed_analisis_sangre",     {**common, "department_slug": "medico"}),
            ("seed_hoja_diaria_medico",  {**common, "department_slug": "medico"}),
            ("seed_fase_densidad",       {**common, "department_slug": "medico"}),
            ("seed_molestias",           {**common, "department_slug": "medico"}),
            ("seed_gps_partido",         {**common, "department_slug": "fisico"}),
            ("seed_gps_session",         {**common, "department_slug": "fisico"}),
            ("seed_checkin_fisico",      {"create_if_missing": True, "club": club,
                                          "unlock": True, "department_slug": "fisico"}),
            ("seed_match_performance",   {**common, "department_slug": "tactico"}),
            ("seed_daily_notes",         {**common}),
            ("seed_metas",               {**common}),
        ]

        steps: list[tuple[str, dict]] = [
            ("seed_uchile_skeleton", {"club_name": club, "category_name": category}),
            ("seed_chile_roster", {"club": club, "category": category}),
            *template_steps,
            ("sync_template_fields", {"all": True}),
        ]

        for name, kwargs in steps:
            self.stdout.write(self.style.NOTICE(f"\n→ {name}"))
            self._run(name, kwargs)

        # Band-alert rules so the alert system is configured (rules only — no
        # historical backfill, so we don't touch any other club's data).
        self.stdout.write(self.style.NOTICE("\n→ seed_band_alerts (rules only)"))
        self._run("seed_band_alerts", {"no_backfill": True})

        # In-range historical data.
        if not opts["skip_fake_exams"]:
            self.stdout.write(self.style.NOTICE("\n→ seed_fake_exams --healthy"))
            fake = {"club": club, "healthy": True, "weeks": opts["weeks"]}
            if opts["reset_fake_exams"]:
                fake["reset"] = True
            self._run("seed_fake_exams", fake)

        # Deliberate availability mix + scoped login.
        self.stdout.write(self.style.NOTICE("\n→ availability (injured / recovery / reintegración)"))
        self._seed_statuses(club, category)

        self.stdout.write(self.style.NOTICE("\n→ staff login"))
        self._ensure_staff_user(club, opts["email"], opts["password"])

        # Dashboards/report layouts for the 4 demo departments.
        self.stdout.write(self.style.NOTICE("\n→ seed_demo_layouts"))
        self._run("seed_demo_layouts", {"club": club, "category": category})

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Chile demo workspace ready: {category} / {club}.\n"
            f"   Login: {opts['email']} / {opts['password']}\n"
            f"   Frontend: http://localhost:3001\n"
        ))

    # ------------------------------------------------------------------

    def _run(self, name: str, kwargs: dict) -> None:
        try:
            call_command(name, **kwargs)
        except Exception as exc:  # noqa: BLE001 — keep going so partial seeds land
            self.stdout.write(self.style.ERROR(f"  ! {name} failed: {exc}"))

    def _seed_statuses(self, club: str, category: str) -> None:
        from core.models import Player
        from exams.calculations import compute_result_data
        from exams.models import Episode, ExamResult, ExamTemplate

        les = (
            ExamTemplate.objects
            .filter(slug="lesiones", department__club__name=club, is_active_version=True)
            .first()
        )
        if les is None:
            self.stdout.write(self.style.WARNING("  Lesiones template missing; skipping statuses."))
            return

        now = timezone.now()
        applied = 0
        for last_name, stage, etype, body_part, severity in STATUS_PLAN:
            player = (
                Player.objects
                .filter(category__club__name=club, category__name=category,
                        last_name=last_name, is_active=True)
                .first()
            )
            if player is None:
                self.stdout.write(self.style.WARNING(f"  · {last_name}: not found, skipping."))
                continue
            # Idempotent: clear any prior open episode (its results first —
            # ExamResult.episode is PROTECT) so re-runs rebuild a correct status.
            for ep in Episode.objects.filter(player=player, template=les, status=Episode.STATUS_OPEN):
                ExamResult.objects.filter(episode=ep).delete()
                ep.delete()

            stages = _STAGE_PROGRESSION[stage]
            started_at = now - timedelta(days=7 * len(stages) + 3)
            episode = Episode.objects.create(
                player=player, template=les, status=Episode.STATUS_OPEN,
                stage="injured", started_at=started_at,
            )
            expected_return = (started_at + timedelta(days=35)).date().isoformat()
            for idx, st in enumerate(stages):
                recorded_at = started_at + timedelta(days=idx * 9)
                raw = {
                    "diagnosed_at": started_at.date().isoformat(),
                    "type": etype, "body_part": body_part, "severity": severity,
                    "stage": st, "expected_return_date": expected_return,
                    "notes": "Plan de readaptación progresivo. Control semanal.",
                }
                result_data, inputs_snapshot = compute_result_data(les, raw, player=player)
                # Fires episode_lifecycle signal → syncs episode.stage + player.status.
                ExamResult.objects.create(
                    player=player, template=les, episode=episode,
                    recorded_at=recorded_at, result_data=result_data,
                    inputs_snapshot=inputs_snapshot,
                )
            player.refresh_from_db()
            self.stdout.write(f"  · {last_name}: {player.status}")
            applied += 1
        self.stdout.write(self.style.SUCCESS(f"  Availability set for {applied} player(s)."))

    def _ensure_staff_user(self, club: str, email: str, password: str) -> None:
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        from core.models import Club, StaffMembership

        User = get_user_model()
        club_obj = Club.objects.filter(name=club).first()
        if club_obj is None:
            self.stdout.write(self.style.WARNING("  Club missing; skipping staff user."))
            return

        username = email.split("@")[0].replace(".", "_")
        user = User.objects.filter(username=username).first() or User.objects.filter(email=email).first()
        created = user is None
        if user is None:
            user = User(username=username)
        user.email = email
        user.first_name = "Demo"
        user.last_name = "La Roja"
        user.is_active = True
        user.set_password(password)
        user.save()

        membership, _ = StaffMembership.objects.get_or_create(
            user=user, defaults={"club": club_obj},
        )
        membership.club = club_obj
        membership.all_categories = True
        membership.all_departments = True
        membership.save()

        # Without a role group the user has ZERO permissions → can't see/add
        # exam values (frontend hides actions; create_result requires
        # exams.add_examresult). Editor = full editing within the club; the
        # membership keeps it scoped to this club (non-superuser).
        editor = Group.objects.filter(name="Editor").first()
        if editor is None:
            try:
                call_command("seed_role_groups")
                editor = Group.objects.filter(name="Editor").first()
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.WARNING(f"  seed_role_groups failed: {exc}"))
        role = "—"
        if editor is not None:
            user.groups.add(editor)
            role = editor.name

        self.stdout.write(self.style.SUCCESS(
            f"  Staff user {'created' if created else 'updated'}: {email} "
            f"(role {role}, scoped to {club})."
        ))
