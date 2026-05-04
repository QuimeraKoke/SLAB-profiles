"""End-to-end demo seed for Universidad de Chile / Primer Equipo.

Runs every other seed command in the right order so a fresh database
boots into a working showcase:

    1. Roster + departments + positions     (seed_uchile_2026)
    2. Exam templates per department:
         - Pentacompartimental (Nutricional)
         - Lesiones (Médico, episodic)
         - Medicación (Médico, with WADA alerts)
         - CK / Hidratación / CMJ              (existing — assumed seeded)
         - GPS Partido (Físico)
         - GPS Entrenamiento (Físico)
         - Rendimiento de partido (Táctico)
         - Daily-notes templates per dept
    3. TemplateField rebuild (`sync_template_fields`)
    4. Fake historical results so widgets show data
    5. Per-player + team-report layouts for all 4 departments

Run:

    docker compose exec backend python manage.py seed_demo

By default this targets `Universidad de Chile / Primer Equipo`. Pass
`--reset-fake-exams` to wipe + regenerate fake history (otherwise it
will skip if results already exist).
"""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run all seed commands in order to bootstrap the U. de Chile demo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--club", default="Universidad de Chile",
            help="Club name to scope seed commands to.",
        )
        parser.add_argument(
            "--category", default="Primer Equipo",
            help="Category name to seed layouts for.",
        )
        parser.add_argument(
            "--reset-fake-exams", action="store_true",
            help="Wipe + regenerate fake historical results.",
        )
        parser.add_argument(
            "--skip-fake-exams", action="store_true",
            help="Skip the fake-exam generation step entirely.",
        )

    def handle(self, *args, **opts):
        club: str = opts["club"]
        category: str = opts["category"]

        steps: list[tuple[str, list[str], dict]] = [
            # 1. Rosters (idempotent — safe to re-run on existing DB)
            # Skeleton first: club + 5 departments + Primer Equipo category
            # + 4 positions. seed_uchile_2026 (player insertion) needs all
            # of this in place.
            ("seed_uchile_skeleton", [], {}),
            ("seed_uchile_2026", [], {}),
            # Bare second-club skeleton (club + 4 empty departments) so the
            # demo shows the platform's multi-tenant model alongside the
            # populated U. de Chile data.
            ("seed_slab_skeleton", [], {}),

            # 2. Templates — every seed gets `club` so we don't accidentally
            # write to the SLAB skeleton in a multi-club DB.
            ("seed_pentacompartimental", [], {
                "create_if_missing": True,
                "department_slug": "nutricional",
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),
            ("seed_lesiones", [], {
                "create_if_missing": True,
                "department_slug": "medico",
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),
            ("seed_medicacion_template", [], {
                "create_if_missing": True,
                "department_slug": "medico",
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),
            ("seed_medico_indicators", [], {
                "create_if_missing": True,
                "department_slug": "medico",
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),
            ("seed_gps_match", [], {
                "create_if_missing": True,
                "department_slug": "fisico",
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),
            ("seed_gps_training", [], {
                "create_if_missing": True,
                "department_slug": "fisico",
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),
            ("seed_match_performance", [], {
                "create_if_missing": True,
                "department_slug": "tactico",
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),
            ("seed_daily_notes", [], {
                "create_if_missing": True,
                "all_applicable_categories": True,
                "club": club,
                "unlock": True,
            }),

            # 3. TemplateField rebuild — exposes the schema as inline rows in admin.
            ("sync_template_fields", [], {"all": True}),
        ]

        for name, args_list, kwargs in steps:
            self.stdout.write(self.style.NOTICE(f"\n→ {name}"))
            try:
                call_command(name, *args_list, **kwargs)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"  ! {name} failed: {exc}"))
                self.stdout.write(self.style.WARNING(
                    "  Continuing with the remaining steps so partial seeds still land."
                ))

        # 4. Fake historical results — separate step because it's destructive
        # and slow. Skip when --skip-fake-exams or when results already exist
        # (the command itself is idempotent via its --reset flag).
        if not opts["skip_fake_exams"]:
            self.stdout.write(self.style.NOTICE("\n→ seed_fake_exams"))
            try:
                fake_kwargs: dict = {"club": club}
                if opts["reset_fake_exams"]:
                    fake_kwargs["reset"] = True
                call_command("seed_fake_exams", **fake_kwargs)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"  ! seed_fake_exams failed: {exc}"))

        # 5. Layouts (per-player + team-report) for all 4 demo departments.
        self.stdout.write(self.style.NOTICE("\n→ seed_demo_layouts"))
        try:
            call_command("seed_demo_layouts", club=club, category=category)
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f"  ! seed_demo_layouts failed: {exc}"))

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ Demo seed complete for {category} / {club}.\n"
            f"   Frontend: http://localhost:3000\n"
            f"   Admin:    http://localhost:8000/admin/\n"
        ))
