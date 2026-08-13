"""Catapult OpenField GPS sync — dry-run planner by default.

Two modes:

  * **Saved** — reads `CatapultIntegration` rows (Django admin). Runs every
    enabled category, or one via `--category`. Add `--commit` to write.

        python manage.py sync_catapult --dry-run
        python manage.py sync_catapult --category "Primer Equipo" --commit

  * **Ad-hoc** — pass `--token` (+ `--team`) to plan against a tenant with NO
    saved config. Dry-run only (never writes) — for exploring before binding a
    club in admin. The token defaults to $TEST_UCHILE_CATAPULT_API_KEY.

        python manage.py sync_catapult --category "Primer Equipo" \
            --team 8db37797-534b-4be7-b851-9953f364185c --strategy hybrid \
            --token "$(grep TEST_UCHILE .env | cut -d= -f2-)"

Never writes unless `--commit` is given AND a saved integration is used.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Plan (or, with --commit, run) the Catapult → gps_partido/gps_sesion sync. Read-only by default."

    def add_arguments(self, parser):
        parser.add_argument("--category", default=None, help="Category name (or exact match).")
        parser.add_argument("--commit", action="store_true",
                            help="Actually create ExamResults (saved integrations only). Default: dry-run.")
        parser.add_argument("--lookback", type=int, default=None, help="Override lookback days.")
        parser.add_argument("--verbose", action="store_true", help="Show every athlete row.")
        # Ad-hoc (no saved config) options:
        parser.add_argument("--token", default=None,
                            help="Ad-hoc: Catapult token (default $TEST_UCHILE_CATAPULT_API_KEY). Forces dry-run.")
        parser.add_argument("--team", default="", help="Ad-hoc: Catapult team id to scope to.")
        parser.add_argument("--strategy", default="tag",
                            choices=["fixture", "tag", "name", "hybrid"],
                            help="Ad-hoc: classification strategy (default tag: DayCode=MD / ' vs ').")
        parser.add_argument("--min-training-minutes", type=int, default=0)
        parser.add_argument("--base-url", default=None)

    def handle(self, *args, **opts):
        from exams.models import CatapultIntegration
        from exams.services import catapult_sync as S

        commit = opts["commit"]
        w = self.stdout.write

        ad_hoc_token = opts["token"] or (os.environ.get("TEST_UCHILE_CATAPULT_API_KEY", "")
                                         if opts["team"] else "")
        if ad_hoc_token:
            if commit:
                raise CommandError("Ad-hoc mode (--token) is dry-run only. Configure a "
                                   "CatapultIntegration in admin to --commit.")
            integ = self._adhoc_integration(opts, ad_hoc_token, S)
            plans = [S.plan_category(integ, dry_run=True)]
        else:
            qs = CatapultIntegration.objects.select_related("category")
            if opts["category"]:
                qs = qs.filter(category__name=opts["category"])
            else:
                qs = qs.filter(enabled=True)
            integs = list(qs)
            if not integs:
                raise CommandError(
                    "No matching CatapultIntegration. Configure one in Django admin, "
                    "or use ad-hoc mode: --token + --team + --category.")
            plans = []
            for integ in integs:
                if opts["lookback"]:
                    integ.lookback_days = opts["lookback"]
                plans.append(S.plan_category(integ, dry_run=not commit))

        for plan in plans:
            self._render(plan, w, verbose=opts["verbose"], commit=commit)

        if not commit:
            w(self.style.WARNING("\nDRY-RUN — nothing was written. Add --commit (saved integration) to ingest."))

    def _adhoc_integration(self, opts, token, S):
        from core.models import Category
        from exams.models import CatapultIntegration
        name = opts["category"]
        if not name:
            raise CommandError("Ad-hoc mode needs --category.")
        category = Category.objects.filter(name=name).order_by("id").first()
        if category is None:
            raise CommandError(f"No category named {name!r}.")
        return CatapultIntegration(
            category=category, enabled=True,
            base_url=opts["base_url"] or CatapultIntegration.DEFAULT_BASE_URL,
            api_token=token, catapult_team_id=opts["team"],
            classify_strategy=opts["strategy"], sync_matches=True, sync_training=True,
            min_training_minutes=opts["min_training_minutes"],
            partido_template_slug="gps_partido", sesion_template_slug="gps_sesion",
            lookback_days=opts["lookback"] or 14,
        )

    # ── rendering ──────────────────────────────────────────────────────────

    def _render(self, plan, w, *, verbose: bool, commit: bool):
        t = plan.totals()
        w(self.style.MIGRATE_HEADING(
            f"\n═══ {plan.category} · estrategia={plan.strategy} · ventana={plan.window_days}d ═══"))
        w(f"  actividades={t['activities']}  (partidos={t['partidos']}, "
          f"entrenamientos={t['entrenamientos']})")
        verb = "creadas" if commit else "a crear"
        w(f"  filas: {verb}={t['rows_new']}  ya_existen={t['rows_exists']}  "
          f"sin_jugador={t['rows_unresolved']}  sin_métricas={t['rows_no_metrics']}  "
          f"cortas={t['rows_short']}")
        for e in plan.errors:
            w(self.style.ERROR(f"  ! {e}"))

        for a in plan.activities:
            tag = self.style.SUCCESS("PARTIDO") if a.tipo == "partido" else "entren."
            ev = f" event={a.event_id[:8]}" if a.event_id else ""
            w(f"\n  • {a.day}  [{tag}]  {a.name!r}  ({a.athlete_count} atl · {a.signal}{ev})")
            if a.note:
                w(self.style.WARNING(f"      ⚠ {a.note}"))
            shown = a.rows if verbose else [r for r in a.rows if r.status in ("unresolved",)]
            if verbose:
                w(f"      {'atleta':24} {'→ jugador':24} {'via':8} "
                  f"{'dur':>5} {'dist':>7} {'m/min':>6} {'estado':>10}")
            for r in shown:
                if r.status == "unresolved":
                    w(self.style.WARNING(
                        f"      {r.athlete_name[:24]:24} → (SIN JUGADOR)"))
                    continue
                w(f"      {r.athlete_name[:24]:24} {(r.player_name or '')[:24]:24} "
                  f"{(r.match_method or ''):8} {str(r.data.get('tot_dur','')):>5} "
                  f"{str(r.data.get('tot_dist','')):>7} {str(r.data.get('mpm','')):>6} "
                  f"{r.status:>10}")
            if not verbose:
                unresolved = sum(1 for r in a.rows if r.status == "unresolved")
                if unresolved:
                    w(f"      ({unresolved} sin jugador — usá --verbose para el detalle)")
