"""Generate fake exam results for every player so the dashboards have data.

Idempotency-friendly: deterministic per-player baselines (seeded from each
player's UUID) mean re-running with --reset reproduces the same shape.

Examples:

    # Default: weekly cadence, weeks+1 = 13 entries per (player × applicable
    # template) — one per week from `now - 12 weeks` to `now`, every club.
    docker compose exec backend python manage.py seed_fake_exams

    # Wipe existing results first, then seed weekly.
    docker compose exec backend python manage.py seed_fake_exams --reset

    # Heavier dataset, single club, 24 weeks of weekly data:
    docker compose exec backend python manage.py seed_fake_exams \
        --club "Demo FC" --weeks 24

    # Legacy spread mode (N results spread evenly across the window):
    docker compose exec backend python manage.py seed_fake_exams \
        --cadence spread --count 6 --weeks 12

Notes
-----
* Numeric inputs are pulled from a per-player baseline that's deterministic in
  the player's UUID and then jittered ±3% per result. This makes trend lines
  look like real measurements (slight drift) instead of random noise.
* Calculated fields are *not* generated directly — every result_data dict goes
  through `compute_result_data(template, raw_data)` so masa_adiposa, IMC, etc.
  are computed by the live formula engine.
* `recorded_at` is spread evenly across the time window. The newest result
  lands at "now" so the latest stat-card values are current.
* Special-cased templates (`lesiones`, `medicacion`, `gps_*`, daily notes)
  use their own cadence — they're episodic / date-range / per-event, not
  weekly check-ins, so the cadence flag doesn't apply to them.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Category, Club, Player
from events.models import Event
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate

# Per-key (min, max) for numeric inputs. Anything not listed falls back to
# DEFAULT_NUMERIC_RANGE (still sensible, just less domain-specific).
NUMERIC_BASELINES: dict[str, tuple[float, float]] = {
    # Pentacompartimental
    "peso": (65.0, 85.0),
    "talla": (165.0, 190.0),
    # Biepicondylar diameters — tuned slightly down so the Rocha bone-mass
    # formula produces values that let IMO span the full band spectrum
    # (Bajo ↔ Élite) rather than collapse into "Bajo" for every player.
    "humero": (5.4, 6.4),
    "femur": (8.4, 9.6),
    "biestiloideo": (5.2, 6.2),
    "torax": (95.0, 108.0),
    "cintura": (72.0, 85.0),
    "caderas": (92.0, 102.0),
    "perim_brazo_relajado": (28.0, 35.0),
    "muslo_gluteo": (56.0, 64.0),
    "muslo_medio": (51.0, 58.0),
    "pierna_perim": (37.0, 42.0),
    # Pliegues calibrated for elite soccer players — produces Σ6 ≈ 26-48mm,
    # giving a healthy spread across the Élite / Bueno / Aceptable bands
    # of the Nutricional dashboards. The pre-2026 baselines were generic-
    # population values and pushed every player into "Elevado" (>50mm).
    "pliegue_triceps": (3.5, 6.5),
    "pliegue_subescapular": (5.0, 8.0),
    "pliegue_supra": (4.0, 7.0),
    "pliegue_abdomen": (6.0, 11.0),
    "pliegue_muslo": (5.0, 10.0),
    "pliegue_pierna": (3.0, 6.0),
    "envergadura": (175.0, 195.0),
    "long_brazo": (55.0, 65.0),
    "long_pierna": (90.0, 105.0),
    # Generic physical-test-ish defaults
    "dist_30": (200.0, 280.0),
    "hr_avg": (140.0, 170.0),
    # Médico — clinical indicators
    "valor": (150.0, 500.0),       # CK U/L (athletes baseline; can spike post-match)
    "densidad": (1.005, 1.025),    # Hidratación (urine specific gravity)
    "contramovimiento": (32.0, 48.0),  # CMJ jump height in cm
    # Físico — GPS Entrenamiento (training-day totals; lower than match)
    "tot_dur": (60.0, 90.0),       # min
    "tot_dist": (4500.0, 8500.0),  # m
    "hsr": (200.0, 700.0),         # m above 19.8 km/h
    "sprint": (40.0, 250.0),       # m above 25 km/h
    "max_vel": (28.0, 33.0),       # km/h
    "acc": (15.0, 45.0),
    "dec": (15.0, 45.0),
    "hiaa": (50.0, 180.0),
    "hmld": (300.0, 1100.0),
    "player_load": (300.0, 650.0),
    "rpe": (4.0, 8.0),             # 1-10 perceived exertion scale
    # Táctico — Rendimiento de partido
    "minutes_played": (45.0, 90.0),
    "rating": (5.5, 8.5),
    "shots": (0.0, 5.0),
    "shots_on_target": (0.0, 3.0),
    "fouls_committed": (0.0, 4.0),
    "fouls_received": (0.0, 4.0),
    "goals": (0.0, 1.0),
    "assists": (0.0, 1.0),
    "yellow_cards": (0.0, 1.0),
    # Físico — GPS Partido (per-half inputs; the *_total fields are calculated
    # from these). A 90' match for an elite player ≈ 9-11 km total, so each
    # ~45' half ≈ 4.3-5.6 km. Without these the per-half keys fell back to the
    # generic (10, 100) m default → absurd ~190 m match totals.
    "tot_dur_p1": (44.0, 49.0), "tot_dur_p2": (45.0, 51.0),
    "tot_dist_p1": (4300.0, 5600.0), "tot_dist_p2": (4200.0, 5500.0),
    "hsr_p1": (220.0, 480.0), "hsr_p2": (200.0, 460.0),
    "sprint_p1": (40.0, 150.0), "sprint_p2": (35.0, 140.0),
    "dist_70_85_p1": (500.0, 1200.0), "dist_70_85_p2": (480.0, 1150.0),
    "dist_85_95_p1": (150.0, 520.0), "dist_85_95_p2": (140.0, 500.0),
    "acc_dec_p1": (28.0, 58.0), "acc_dec_p2": (26.0, 55.0),
    "acc_p1": (14.0, 32.0), "acc_p2": (13.0, 30.0),
    "dec_p1": (14.0, 32.0), "dec_p2": (13.0, 30.0),
    "max_vel_p1": (29.0, 34.0), "max_vel_p2": (28.5, 33.5),
    "hiaa_p1": (45.0, 110.0), "hiaa_p2": (40.0, 100.0),
    "hmld_p1": (320.0, 760.0), "hmld_p2": (300.0, 720.0),
    "player_load_p1": (230.0, 420.0), "player_load_p2": (220.0, 400.0),
    "mpm_p1": (98.0, 124.0), "mpm_p2": (95.0, 120.0),
    "hsr_rel_p1": (5.0, 12.0), "hsr_rel_p2": (4.5, 11.0),
    "sprint_rel_p1": (1.0, 4.0), "sprint_rel_p2": (0.8, 3.5),
    # Nutricional — Pentacompartimental anthropometry (elite male soccer).
    "biacromial": (38.0, 43.0), "bi_iliocrestideo": (26.0, 31.0),
    "diam_torax_ap": (18.0, 23.0), "diam_torax_transverso": (26.0, 31.0),
    "perim_cabeza": (55.0, 59.0), "perim_torax": (90.0, 104.0),
    "perim_antebrazo": (25.0, 30.0), "perim_brazo_contraido": (30.0, 38.0),
    "talla_sentado": (88.0, 99.0),
    "pliegue_bicipital": (2.5, 5.0), "pliegue_supracrestideo": (5.0, 12.0),
    # Médico — Análisis de sangre (male-athlete reference values).
    "hemoglobina": (14.0, 17.0), "hematocrito": (41.0, 50.0),
    "ferritina": (40.0, 200.0), "vitamina_d": (30.0, 55.0),
    "vitamina_b12": (300.0, 800.0), "cortisol": (8.0, 20.0),
    "testosterona_total": (400.0, 900.0), "testosterona_libre": (9.0, 25.0),
    "t3": (80.0, 190.0), "t4_libre": (0.9, 1.7), "tsh": (0.6, 3.8),
    # Físico — Fase / Densidad.
    "edad_phv": (13.0, 15.0), "indice_mad": (0.9, 1.1),
    "densidad_urinaria": (1.005, 1.022),
    # Médico misc.
    "dias_perdidos": (0.0, 21.0), "partidos_perdidos": (0.0, 4.0),
    "cantidad": (1.0, 30.0),
}

# Slugs that need episode-aware or date-range-aware generation. The main
# loop SKIPS these templates and dispatches to dedicated handlers below.
SPECIAL_TEMPLATE_SLUGS = {"lesiones", "medicacion", "molestias", "check_in",
                          "gps_sesion"}

# Training microcycle: training-day load as a % of the player's match-day
# reference, keyed by days-BEFORE the next match. The match (MD) and the
# recovery day after it (MD+1) get NO training GPS. Load rises from MD-5
# (≈ MD+2) to the MD-3 peak (~78%, i.e. 76–80%), then tapers to MD-1.
_TRAINING_MICROCYCLE: dict[int, float] = {
    5: 0.50,  # MD-5 (≈ MD+2) — rising start
    4: 0.65,  # MD-4
    3: 0.78,  # MD-3 — PEAK
    2: 0.58,  # MD-2 — decreasing
    1: 0.38,  # MD-1 — pre-match activation
}

# GPS realism: a per-session "intensity" factor (game/session-to-session
# variation — opponent, tactics, extra time, weather) shared by every metric
# in that session, layered on top of per-metric noise. Without it every match
# / training day comes out near-identical (and ACWR collapses to ~1.0).
_GPS_MATCH_SLUG = "gps_partido"
_GPS_SESSION_FACTOR = (0.85, 1.16)        # match: wide game-to-game variation
_GPS_TRAIN_SESSION_FACTOR = (0.86, 1.08)  # training: planned, tighter spread
_GPS_METRIC_NOISE = 0.08                  # ±8% independent per-metric noise

# Realistic Lesiones content. Picks one combo per episode so the Episode's
# `title_template` ("{type} — {body_part}") renders something believable.
LESION_PRESETS = [
    ("Muscular",      "Muslo der.",       "Moderada"),
    ("Muscular",      "Muslo izq.",       "Leve"),
    ("Muscular",      "Pantorrilla der.", "Leve"),
    ("Tendinosa",     "Rodilla izq.",     "Moderada"),
    ("Ligamentosa",   "Tobillo der.",     "Moderada"),
    ("Articular",     "Hombro izq.",      "Leve"),
    ("Contusión",     "Muslo der.",       "Leve"),
    ("Sobreuso",      "Espalda baja",     "Leve"),
    ("Ósea / fractura", "Mano izq.",      "Severa"),
]

LESION_NOTES = [
    "Plan de tratamiento con fisioterapia + crioterapia. Reevaluar en 5 días.",
    "Tratamiento conservador. Carga progresiva al avanzar fases.",
    "RICE las primeras 48 h. Movilidad activa según tolerancia.",
    "Ecografía descartó rotura completa. Continuar con rehabilitación.",
    "Sesión de readaptación funcional. Trabajo de fuerza y equilibrio.",
]

# Medicines we'll randomly pick from for the Medicación seeder.
# All PERMITIDO so the WADA alert noise stays manageable on first demo.
# (One CONDICIONAL is included to give the alert system a row to display.)
DEMO_MEDICINES = [
    ("Paracetamol 1 gr",                     "1 comp c/8h"),
    ("Ibuprofeno",                           "400 mg c/8h"),
    ("Diclofenaco gel crema",                "Aplicar c/12h"),
    ("Ketoprofen 100 mg",                    "1 comp c/12h"),
    ("Loratadina 10 mg",                     "1 comp diario"),
    ("Omeprazol 20 mg",                      "1 caps en ayunas"),
    ("Amoxicilina 500 mg",                   "1 caps c/8h x 7 días"),
    ("Traumeel",                             "Aplicar c/8h"),  # CONDICIONAL
]

MEDICATION_REASONS = [
    "Dolor muscular post-partido",
    "Rinitis alérgica",
    "Faringitis aguda",
    "Cefalea tensional",
    "Sobrecarga lumbar",
    "Profilaxis pre-temporada",
    "Dolor articular leve",
]

DEFAULT_NUMERIC_RANGE = (10.0, 100.0)
DRIFT_PCT = 0.03  # ±3% jitter from baseline per result

SAMPLE_DAILY_SUBJECTS = [
    "Sesión de entrenamiento",
    "Consulta de seguimiento",
    "Evaluación post-partido",
    "Revisión semanal",
    "Observación del día",
    "Recuperación activa",
]

SAMPLE_DAILY_NOTES = [
    "Sesión tolerada sin molestias. Mantener carga semanal y revaluar viernes.",
    "Refiere ligera molestia en isquiotibiales tras entrenamiento intenso. "
    "Indicado reposo activo, estiramientos y crioterapia. Control en 48 h.",
    "Post-partido: descansado, sin contracturas. Tolerancia adecuada al "
    "volumen de carrera.",
    "Trabajo de fuerza compensatoria. Buen control técnico, RPE 7.",
    "Pequeña sobrecarga en gemelo derecho. Reducir intensidad 48 h.",
    "Sin novedades. Continúa con plan habitual.",
    "Refiere dificultad para conciliar el sueño últimos días. Conversado con "
    "psicólogo, ajustar carga si persiste.",
]

SAMPLE_GOAL_SUBJECTS = [
    "Reducir masa adiposa",
    "Aumentar masa muscular en miembros inferiores",
    "Mejorar tolerancia aeróbica",
    "Recuperar simetría tras lesión",
    "Optimizar composición corporal pre-temporada",
    "Estabilizar peso corporal",
]

SAMPLE_GOAL_METRICS = [
    "masa_adiposa",
    "masa_muscular",
    "imc",
    "suma_pliegues",
    "grasa_faulkner",
]

SAMPLE_GOAL_TARGETS = [
    "< 10 kg",
    "> 35 kg",
    "≤ 12%",
    "≈ 22 kg/m²",
    "+1 kg en 8 semanas",
    "-2 kg en 6 semanas",
]

SAMPLE_PLANS = [
    "Plan nutricional con déficit calórico moderado (~300 kcal/día). Control "
    "quincenal. Reforzar hidratación y descanso.",
    "Trabajo de fuerza específico 3 sesiones/semana. Progresión lineal de "
    "cargas. Reevaluar en 6 semanas.",
    "Sesiones aeróbicas continuas 2× semana, intervalos 1× semana. Monitorear "
    "FC en zona 2-3.",
    "Movilidad y readaptación funcional. Test de simetría en 4 semanas.",
]

SAMPLE_PATIENT_OBSERVATIONS = [
    "Mantener consumo de proteína post-entrenamiento.",
    "Hidratarse antes, durante y después de la sesión.",
    "Priorizar descanso de 8 h por noche durante esta fase.",
    "Registrar peso semanalmente en ayunas.",
    "",
]

SAMPLE_GENERIC_TEXT = [
    "OK",
    "Sin observaciones",
    "Pendiente",
    "Revisar",
]


class Command(BaseCommand):
    help = "Generate fake exam results so the dashboards have data to render."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None,
                            help="Scope to one club by name. Default: all clubs.")
        parser.add_argument("--count", type=int, default=None,
                            help=(
                                "Historical results per (player × template). "
                                "Ignored when --cadence=weekly (then count is "
                                "derived as weeks + 1, one reading per week). "
                                "Default with --cadence=spread: 6."
                            ))
        parser.add_argument("--weeks", type=int, default=12,
                            help="Time window for spreading results. Default: 12 weeks.")
        parser.add_argument("--cadence",
                            choices=["weekly", "spread"], default="weekly",
                            help=(
                                "How to space results within --weeks. "
                                "`weekly` (default): one result every 7 days, "
                                "weeks+1 results per (player × template). "
                                "`spread`: --count results spread evenly across "
                                "the window (legacy behavior)."
                            ))
        parser.add_argument("--reset", action="store_true",
                            help="Delete every existing ExamResult in scope before seeding.")
        parser.add_argument("--healthy", action="store_true",
                            help=(
                                "Generate IN-RANGE data: numeric fields with "
                                "reference_ranges land in the good (green) band, "
                                "categoricals/booleans pick the healthy option, and "
                                "random injuries/molestias are suppressed (set them "
                                "deliberately instead). For clean demo workspaces."
                            ))

    def handle(self, *args, **options):
        club_name = options["club"]
        cadence = options["cadence"]
        weeks = options["weeks"]
        reset = options["reset"]
        self.healthy = options["healthy"]

        if weeks <= 0:
            raise CommandError("--weeks must be positive.")

        # Cadence resolves to a concrete (count, step) the loop below uses.
        # Weekly fixes step to 7 days and generates weeks+1 readings so the
        # window has both endpoints (oldest = now - weeks, newest = now).
        if cadence == "weekly":
            if options["count"] is not None:
                self.stdout.write(self.style.WARNING(
                    "--count is ignored when --cadence=weekly. Using "
                    f"weeks + 1 = {weeks + 1} results per player × template."
                ))
            count = weeks + 1
        else:
            count = options["count"] if options["count"] is not None else 6
            if count <= 0:
                raise CommandError("--count must be positive.")

        clubs = Club.objects.all()
        if club_name:
            clubs = clubs.filter(name=club_name)
            if not clubs.exists():
                raise CommandError(f"Club '{club_name}' not found.")

        total_created = 0
        total_deleted = 0

        for club in clubs:
            players = list(
                Player.objects.filter(category__club=club, is_active=True)
                .select_related("category")
            )
            if not players:
                self.stdout.write(self.style.WARNING(
                    f"Club '{club.name}': no active players, skipping."
                ))
                continue

            if reset:
                deleted, _ = ExamResult.objects.filter(player__category__club=club).delete()
                total_deleted += deleted
                # Per-result alerts (medication, training-load) key on
                # source_id = result.id with no FK cascade, so they'd orphan
                # (and pile up across re-runs). Clear them alongside the data.
                from goals.models import Alert, AlertSource
                club_pids = Player.objects.filter(
                    category__club=club,
                ).values_list("id", flat=True)
                alerts_deleted, _ = Alert.objects.filter(
                    player_id__in=club_pids,
                    source_type__in=[AlertSource.MEDICATION, AlertSource.TRAINING_LOAD],
                ).delete()
                self.stdout.write(self.style.NOTICE(
                    f"Club '{club.name}': deleted {deleted} existing results, "
                    f"{alerts_deleted} per-result alert(s)."
                ))

            templates_by_category: dict[str, list[ExamTemplate]] = {}
            for player in players:
                cat_id = str(player.category_id)
                if cat_id not in templates_by_category:
                    templates_by_category[cat_id] = list(
                        ExamTemplate.objects.filter(applicable_categories=player.category)
                        .select_related("department")
                        .distinct()
                    )

            now = datetime.now(timezone.utc)
            step = timedelta(weeks=weeks) / max(count - 1, 1) if count > 1 else timedelta(0)
            # Weekly match-day anchors (same grid the link_to_match templates
            # use); the training microcycle hangs off these.
            match_dates = [now - step * (count - 1 - i) for i in range(count)]

            # Resolve the special templates once per club.
            templates_by_slug: dict[str, ExamTemplate] = {
                t.slug: t
                for t in ExamTemplate.objects.filter(department__club=club)
                .filter(slug__in=SPECIAL_TEMPLATE_SLUGS)
            }

            # Pre-create match events for each (category × week tick).
            # Any template with link_to_match=True needs an event linked
            # at insert time. We index by the exact recorded_at the loop
            # uses below, so the lookup is O(1).
            match_event_by_category_step: dict[tuple, Event] = (
                self._pre_create_match_events(
                    club, count, step, now, reset=reset,
                )
            )

            with transaction.atomic():
                for player in players:
                    baseline = self._baseline_for(player.id)
                    rng = random.Random(f"{player.id}::results")
                    templates = templates_by_category[str(player.category_id)]
                    for template in templates:
                        if template.slug in SPECIAL_TEMPLATE_SLUGS:
                            # Skip in the generic loop; dispatched below
                            # so episodic / date-range semantics stay correct.
                            continue
                        for i in range(count):
                            recorded_at = now - step * (count - 1 - i)
                            raw_data = self._generate_raw_data(
                                template, baseline, recorded_at, rng,
                            )
                            result_data, inputs_snapshot = compute_result_data(
                                template, raw_data, player=player,
                            )
                            # link_to_match templates need a real event —
                            # look up the pre-created event for this
                            # (category, week tick).
                            ev: Event | None = None
                            if template.link_to_match:
                                ev = match_event_by_category_step.get(
                                    (player.category_id, i),
                                )
                            ExamResult.objects.create(
                                player=player,
                                template=template,
                                recorded_at=recorded_at,
                                result_data=result_data,
                                inputs_snapshot=inputs_snapshot,
                                event=ev,
                            )
                            total_created += 1

                    # ---- Special-cased templates ----
                    lesiones_t = templates_by_slug.get("lesiones")
                    if (
                        lesiones_t is not None
                        and lesiones_t in templates
                    ):
                        total_created += self._seed_lesiones_for_player(
                            player, lesiones_t, rng, now,
                        )
                    medicacion_t = templates_by_slug.get("medicacion")
                    if (
                        medicacion_t is not None
                        and medicacion_t in templates
                    ):
                        total_created += self._seed_medicacion_for_player(
                            player, medicacion_t, rng, now,
                        )
                    molestias_t = templates_by_slug.get("molestias")
                    if (
                        molestias_t is not None
                        and molestias_t in templates
                    ):
                        total_created += self._seed_molestias_for_player(
                            player, molestias_t, rng, now,
                        )
                    check_in_t = templates_by_slug.get("check_in")
                    if (
                        check_in_t is not None
                        and check_in_t in templates
                    ):
                        total_created += self._seed_check_in_for_player(
                            player, check_in_t, rng, now,
                        )
                    gps_train_t = templates_by_slug.get("gps_sesion")
                    if (
                        gps_train_t is not None
                        and gps_train_t in templates
                    ):
                        total_created += self._seed_gps_training_for_player(
                            player, gps_train_t, rng, match_dates,
                        )

            self.stdout.write(self.style.SUCCESS(
                f"Club '{club.name}': seeded results for {len(players)} player(s)."
            ))

        verb = f"deleted {total_deleted}, created" if reset else "created"
        self.stdout.write(self.style.SUCCESS(
            f"Done. {verb} {total_created} ExamResult row(s)."
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pre_create_match_events(
        self,
        club: Club,
        count: int,
        step: timedelta,
        now: datetime,
        *,
        reset: bool,
    ) -> dict[tuple, Event]:
        """For every category in the club that has at least one
        link_to_match template, pre-create `count` match events spaced
        like the result loop (one per week tick). Returns a lookup
        `{(category_id, tick_index): Event}` consumed by the inserter.

        When `reset=True` we also wipe any pre-existing synthetic
        seed-events on the same dates so re-running stays idempotent.
        Manually-created Events (without `metadata.seed=True`) are
        left alone.
        """
        # Find categories that own at least one link_to_match template.
        cat_ids_needing_events: set = set()
        link_templates = ExamTemplate.objects.filter(
            department__club=club, link_to_match=True,
        ).prefetch_related("applicable_categories")
        for t in link_templates:
            for cat in t.applicable_categories.all():
                cat_ids_needing_events.add(cat.id)

        if not cat_ids_needing_events:
            return {}

        out: dict[tuple, Event] = {}
        categories = Category.objects.filter(
            id__in=cat_ids_needing_events,
        ).select_related("club")

        for cat in categories:
            # We need a department FK on every Event; for match events
            # we pick any departent the category opted into (events are
            # cross-cutting). Falls back to the first link_to_match
            # template's department for stable seeding.
            dept = (
                link_templates.filter(applicable_categories=cat).first().department
            )
            if reset:
                # Wipe previous seed-generated synthetic match events.
                Event.objects.filter(
                    club=cat.club, category=cat,
                    event_type=Event.TYPE_MATCH,
                    metadata__seed=True,
                ).delete()
            for i in range(count):
                starts_at = now - step * (count - 1 - i)
                title = f"Partido sim. {starts_at:%d %b %Y}"
                ev = Event.objects.create(
                    club=cat.club,
                    department=dept,
                    event_type=Event.TYPE_MATCH,
                    title=title,
                    starts_at=starts_at,
                    scope=Event.SCOPE_CATEGORY,
                    category=cat,
                    metadata={"seed": True, "source": "seed_fake_exams"},
                )
                out[(cat.id, i)] = ev
        return out

    def _baseline_for(self, player_id) -> dict[str, Any]:
        """Per-player baseline that's deterministic in player.id."""
        rng = random.Random(f"{player_id}::baseline")
        baseline: dict[str, Any] = {
            key: rng.uniform(low, high)
            for key, (low, high) in NUMERIC_BASELINES.items()
        }
        baseline["sexo"] = rng.choice([0, 1])
        return baseline

    def _generate_raw_data(self, template: ExamTemplate, baseline: dict[str, Any],
                           recorded_at: datetime, rng: random.Random) -> dict[str, Any]:
        schema = template.config_schema or {}
        fields = schema.get("fields", []) or []
        out: dict[str, Any] = {}

        # Match GPS: one intensity factor per match, shared by all metrics
        # (game-to-game variation), on top of the per-metric noise below.
        is_gps_match = template.slug == _GPS_MATCH_SLUG
        session_factor = rng.uniform(*_GPS_SESSION_FACTOR) if is_gps_match else 1.0

        for field in fields:
            if not isinstance(field, dict):
                continue
            ftype = field.get("type")
            key = field.get("key")
            if not key or ftype == "calculated":
                continue
            value = self._value_for_field(field, baseline, recorded_at, rng)
            if value is not None and is_gps_match and ftype == "number":
                noisy = value * session_factor * (1 + rng.uniform(-_GPS_METRIC_NOISE, _GPS_METRIC_NOISE))
                value = round(noisy, 2)
            if value is not None:
                out[key] = value
        return out

    def _value_for_field(self, field: dict, baseline: dict, recorded_at: datetime,
                         rng: random.Random) -> Any:
        ftype = field.get("type")
        key = field.get("key", "")

        if ftype == "boolean":
            # In healthy mode boolean flags read as "no problem present".
            return False if getattr(self, "healthy", False) else rng.random() < 0.3

        if ftype == "date":
            return recorded_at.date().isoformat()

        if ftype == "categorical":
            options = field.get("options") or []
            if not options:
                return None
            if getattr(self, "healthy", False):
                return self._good_categorical(field, options)
            return rng.choice(options)

        if ftype == "text":
            return self._text_for_key(key, field, rng)

        if ftype == "number":
            if key == "sexo":
                return baseline.get("sexo", 0)
            # Healthy mode: if the field declares reference bands, draw inside
            # the good band so the value reads as in-range (no alert).
            if getattr(self, "healthy", False) and field.get("reference_ranges"):
                good = self._good_band_value(field, rng)
                if good is not None:
                    return good
            base = baseline.get(key)
            if base is None:
                low, high = DEFAULT_NUMERIC_RANGE
                base = rng.uniform(low, high)
            jittered = base * (1 + rng.uniform(-DRIFT_PCT, DRIFT_PCT))
            return round(jittered, 2)

        return None

    # --- Healthy-mode value pickers ----------------------------------

    _GOOD_COLOR = "#16a34a"  # green band used across the seed templates
    _BAD_RISK = {"PROHIBIDO", "CONDICIONAL"}

    def _good_categorical(self, field: dict, options: list) -> Any:
        """Pick the 'healthy' option: avoid WADA-flagged risks, prefer an
        option whose label/value reads positive, else the first option (the
        seed templates list the good/normal option first, e.g. 'disponible')."""
        risk = field.get("option_risk") or {}
        safe = [o for o in options if (risk.get(o) or "").upper() not in self._BAD_RISK]
        pool = safe or options
        positive = ("disponible", "normal", "bueno", "buena", "óptimo", "optimo",
                    "sano", "sin", "no", "ninguna", "ok", "verde", "leve")
        for o in pool:
            token = f"{o} {field.get('option_labels', {}).get(o, '')}".lower()
            if any(p in token for p in positive):
                return o
        return pool[0]

    def _good_band_value(self, field: dict, rng: random.Random):
        """Draw a numeric value inside the field's 'good' reference band.

        Picks the green band (or, lacking colors, the best band per
        direction_of_good), then samples uniformly within it. Open-ended
        edges fall back to the field's `max`/`min` or the union of band edges.
        """
        bands = [b for b in (field.get("reference_ranges") or []) if isinstance(b, dict)]
        if not bands:
            return None
        edges = [e for b in bands for e in (b.get("min"), b.get("max")) if isinstance(e, (int, float))]
        if not edges:
            return None
        emin, emax = min(edges), max(edges)
        field_min = field.get("min")
        field_max = field.get("max")
        floor = field_min if isinstance(field_min, (int, float)) else emin
        ceil = field_max if isinstance(field_max, (int, float)) else emax

        good = next((b for b in bands if (b.get("color") or "").lower() == self._GOOD_COLOR), None)
        if good is None:
            direction = (field.get("direction_of_good") or "").lower()
            if direction == "down":
                good = min(bands, key=lambda b: b.get("max", b.get("min", emax)))
            else:  # up / neutral → the band reaching the highest value
                good = max(bands, key=lambda b: b.get("min", b.get("max", emin)))

        b_lo = good.get("min")
        b_hi = good.get("max")
        edge_span = (emax - emin) or (abs(emax) * 0.2) or 1.0

        if b_hi is None and b_lo is not None:
            # Open upward (higher is better): spread ABOVE the threshold instead
            # of collapsing to it. Prefer the field max if declared.
            lo = b_lo
            hi = (field_max if isinstance(field_max, (int, float)) and field_max > b_lo
                  else b_lo + max(edge_span, abs(b_lo) * 0.12))
        elif b_lo is None and b_hi is not None:
            # Open downward (lower is better): spread BELOW the threshold.
            hi = b_hi
            lo = (field_min if isinstance(field_min, (int, float)) and field_min < b_hi
                  else max(0.0, b_hi - max(edge_span, abs(b_hi) * 0.8)))
        else:
            lo = b_lo if isinstance(b_lo, (int, float)) else floor
            hi = b_hi if isinstance(b_hi, (int, float)) else ceil

        if hi < lo:
            lo, hi = hi, lo
        if hi <= lo:
            hi = lo + max(1.0, abs(lo) * 0.1)
        # Stay a hair inside the edges so band boundaries never tip over.
        span = hi - lo
        val = rng.uniform(lo + span * 0.1, hi - span * 0.1)
        return round(val, 2)

    def _text_for_key(self, key: str, field: dict, rng: random.Random) -> str:
        # Pick contextual content where the key gives us a hint.
        if key in {"asunto"}:
            return rng.choice(SAMPLE_DAILY_SUBJECTS + SAMPLE_GOAL_SUBJECTS)
        if key == "metrica_relacionada":
            return rng.choice(SAMPLE_GOAL_METRICS)
        if key == "valor_objetivo":
            return rng.choice(SAMPLE_GOAL_TARGETS)
        if key == "plan_accion":
            return rng.choice(SAMPLE_PLANS)
        if key in {"observaciones_paciente", "observacion_paciente"}:
            return rng.choice(SAMPLE_PATIENT_OBSERVATIONS)
        if field.get("multiline"):
            return rng.choice(SAMPLE_DAILY_NOTES)
        return rng.choice(SAMPLE_GENERIC_TEXT)

    # ------------------------------------------------------------------
    # Special-cased generators (episodic / date-range templates)
    # ------------------------------------------------------------------

    def _seed_lesiones_for_player(
        self,
        player,
        template: ExamTemplate,
        rng: random.Random,
        now: datetime,
    ) -> int:
        """Generate realistic injury history: 0–2 episodes per player, each
        with 2–4 progressive ExamResults that walk the stage lifecycle
        (injured → recovery → reintegration → closed).

        Uses the real Episode model so the squad-availability widget +
        body-map heatmap show meaningful data. Player.status is recomputed
        automatically by the post_save signal.
        """
        # Lazy-import to avoid load-time cycles with the goals app's signals.
        from exams.models import Episode

        # Healthy mode: no random injuries — statuses are set deliberately
        # by the workspace orchestrator (seed_chile_demo) instead.
        if getattr(self, "healthy", False):
            return 0

        # ~70% of players have at least one episode. Of those, 40% have an
        # active one (open today) and the rest are historical.
        if rng.random() > 0.70:
            return 0
        episode_count = rng.choice([1, 1, 1, 2])  # mostly 1, sometimes 2
        created = 0

        for _ in range(episode_count):
            etype, body_part, severity = rng.choice(LESION_PRESETS)
            currently_active = rng.random() < 0.4

            # Diagnosis date: 2–14 weeks ago. Active episodes started more
            # recently so they're plausibly still in rehab.
            weeks_ago = rng.randint(2, 5) if currently_active else rng.randint(6, 14)
            started_at = now - timedelta(weeks=weeks_ago)

            episode = Episode.objects.create(
                player=player,
                template=template,
                status=Episode.STATUS_OPEN,  # signal flips it later if closed
                stage="injured",
                started_at=started_at,
            )

            # Build the progression: the doctor logs at week 0 (diagnosis),
            # week ~1-2 (recovery), week ~3-4 (reintegration), final close.
            stage_progression: list[tuple[str, int]]
            if currently_active:
                # Pick which stage they're currently in.
                cur = rng.choice(["injured", "recovery", "reintegration"])
                if cur == "injured":
                    stage_progression = [("injured", 0)]
                elif cur == "recovery":
                    stage_progression = [
                        ("injured", 0),
                        ("recovery", rng.randint(7, 12)),
                    ]
                else:  # reintegration
                    stage_progression = [
                        ("injured", 0),
                        ("recovery", rng.randint(7, 12)),
                        ("reintegration", rng.randint(18, 25)),
                    ]
            else:
                # Fully closed timeline.
                stage_progression = [
                    ("injured", 0),
                    ("recovery", rng.randint(7, 12)),
                    ("reintegration", rng.randint(18, 25)),
                    ("closed", weeks_ago * 7 - rng.randint(3, 7)),
                ]

            expected_return = (
                started_at + timedelta(days=rng.randint(21, 49))
            ).date().isoformat()

            for stage, day_offset in stage_progression:
                recorded_at = started_at + timedelta(days=day_offset)
                raw_data = {
                    "diagnosed_at": started_at.date().isoformat(),
                    "type": etype,
                    "body_part": body_part,
                    "severity": severity,
                    "stage": stage,
                    "expected_return_date": expected_return,
                    "notes": rng.choice(LESION_NOTES),
                }
                if stage == "closed":
                    raw_data["actual_return_date"] = recorded_at.date().isoformat()

                result_data, inputs_snapshot = compute_result_data(
                    template, raw_data, player=player,
                )
                ExamResult.objects.create(
                    player=player,
                    template=template,
                    episode=episode,
                    recorded_at=recorded_at,
                    result_data=result_data,
                    inputs_snapshot=inputs_snapshot,
                )
                created += 1

        return created

    def _seed_medicacion_for_player(
        self,
        player,
        template: ExamTemplate,
        rng: random.Random,
        now: datetime,
    ) -> int:
        """Generate realistic medication history: 1–4 prescriptions per
        player, mostly past with 1–2 currently active (so the active-records
        widget has data to display).

        Uses real medicine names from `DEMO_MEDICINES` (subset of the
        WADA-loaded option list) so the cascading dropdown values render
        correctly in the history table.
        """
        # ~60% of players have prescription history.
        if rng.random() > 0.60:
            return 0
        rx_count = rng.choice([1, 2, 2, 3, 4])
        created = 0

        # Make sure at least one is active when we have ≥2 prescriptions —
        # gives the active-records team widget something to display.
        guaranteed_active = rx_count >= 2 and rng.random() < 0.65

        for i in range(rx_count):
            medicine, dosis = rng.choice(DEMO_MEDICINES)
            is_active = guaranteed_active and i == 0 or rng.random() < 0.25

            if is_active:
                # Started 1–10 days ago, ends 5–14 days from now (or open-ended).
                start_offset_days = rng.randint(1, 10)
                fecha_inicio = (now - timedelta(days=start_offset_days)).date()
                if rng.random() < 0.5:
                    fecha_fin = (
                        now + timedelta(days=rng.randint(3, 14))
                    ).date().isoformat()
                else:
                    fecha_fin = ""  # open-ended
            else:
                # Historical: started 30–120 days ago, ended a few days later.
                start_offset_days = rng.randint(30, 120)
                duration_days = rng.choice([3, 5, 7, 10, 14])
                fecha_inicio = (
                    now - timedelta(days=start_offset_days)
                ).date()
                fecha_fin = (
                    now - timedelta(days=start_offset_days - duration_days)
                ).date().isoformat()

            recorded_at = datetime.combine(
                fecha_inicio, datetime.min.time(), tzinfo=timezone.utc,
            )

            raw_data = {
                "medicamento": medicine,
                "dosis": dosis,
                "via_admin": "oral",
                "fecha_inicio": fecha_inicio.isoformat(),
                "fecha_fin": fecha_fin,
                "motivo": rng.choice(MEDICATION_REASONS),
                "stage": "activa" if is_active else "completada",
            }
            result_data, inputs_snapshot = compute_result_data(
                template, raw_data, player=player,
            )
            ExamResult.objects.create(
                player=player,
                template=template,
                recorded_at=recorded_at,
                result_data=result_data,
                inputs_snapshot=inputs_snapshot,
            )
            created += 1

        return created

    # ------------------------------------------------------------------
    # GPS Entrenamiento — one entry per training day, microcycle-shaped
    # ------------------------------------------------------------------

    def _seed_gps_training_for_player(
        self, player, template: "ExamTemplate", rng: random.Random,
        match_dates: list,
    ) -> int:
        """One training-GPS entry per training day across each microcycle.

        For every match anchor we generate the 5 preceding days (MD-5…MD-1);
        the match day itself and MD+1 (the recovery day after the previous
        match) get nothing. Volume metrics scale to a % of the player's
        match-day reference per `_TRAINING_MICROCYCLE` — load rises from MD-5
        to the MD-3 peak (~78%) then tapers to MD-1.
        """
        # Anchor the microcycle "100%" to the player's OWN match demand (match
        # GPS was already generated this run, before this handler). Falls back
        # to a generic range only if the player has no match data. Anchoring
        # keeps training a real % of *their* match, so the ≥85% load alert
        # fires only for genuinely hard sessions, not random over-draws.
        match_rows = list(
            ExamResult.objects
            .filter(player=player, template__slug=_GPS_MATCH_SLUG)
            .values_list("result_data", flat=True)
        )

        def _match_mean(match_key: str, lo: float, hi: float) -> float:
            vals = [
                d[match_key] for d in match_rows
                if isinstance(d, dict) and isinstance(d.get(match_key), (int, float)) and d[match_key] > 0
            ]
            return sum(vals) / len(vals) if vals else rng.uniform(lo, hi)

        ref = {
            "tot_dist": _match_mean("tot_dist", 9000, 11000),
            "hsr": _match_mean("hsr", 550, 850),
            "sprint_dist": _match_mean("sprint_dist", 120, 260),
            "hmld": _match_mean("hmld", 900, 1400),
            "player_load": _match_mean("player_load", 480, 640),
            "hiaa": _match_mean("hiaa", 110, 190),
            "acc": _match_mean("acc", 40, 60),
            "dec": _match_mean("dec", 40, 60),
        }
        created = 0
        seen_days: set = set()
        for md in match_dates:
            for offset, pct in _TRAINING_MICROCYCLE.items():
                recorded_at = md - timedelta(days=offset)
                day_key = recorded_at.date()
                if day_key in seen_days:
                    continue  # overlapping windows → one session per calendar day
                seen_days.add(day_key)

                # Per-session intensity (shared by all metrics this day) ×
                # independent ±8% per-metric noise — the session feels different
                # week to week instead of a flat microcycle template.
                session = rng.uniform(*_GPS_TRAIN_SESSION_FACTOR)

                def j() -> float:
                    return session * (1 + rng.uniform(-_GPS_METRIC_NOISE, _GPS_METRIC_NOISE))

                raw_data = {
                    "fecha": recorded_at.date().isoformat(),
                    "sesion": f"Sesión {recorded_at.strftime('%d-%m-%y')}",
                    "tipo_sesion": "entrenamiento",
                    # Duration: its own noise, not scaled by session intensity.
                    "tot_dur": round((40 + pct * 55) * (1 + rng.uniform(-0.08, 0.08)), 1),
                    "tot_dist": round(ref["tot_dist"] * pct * j(), 1),
                    "hsr": round(ref["hsr"] * pct * j(), 1),
                    "sprint_dist": round(ref["sprint_dist"] * pct * j(), 1),
                    "hmld": round(ref["hmld"] * pct * j(), 1),
                    "player_load": round(ref["player_load"] * pct * j(), 1),
                    "hiaa": round(ref["hiaa"] * pct * j()),
                    "acc": round(ref["acc"] * pct * j()),
                    "dec": round(ref["dec"] * pct * j()),
                    # Intensity peaks less sharply than volume.
                    "max_vel": round(28 + pct * 6 + rng.uniform(-1.2, 1.2), 1),
                    "rpe": max(1, min(10, round(1 + pct * 8 + rng.uniform(-0.6, 0.6)))),
                }
                result_data, inputs_snapshot = compute_result_data(
                    template, raw_data, player=player,
                )
                ExamResult.objects.create(
                    player=player,
                    template=template,
                    recorded_at=recorded_at,
                    result_data=result_data,
                    inputs_snapshot=inputs_snapshot,
                )
                created += 1
        return created

    # ------------------------------------------------------------------
    # Molestias — sporadic daily-log entries (~1-2 per week per player)
    # ------------------------------------------------------------------

    _MOLESTIAS_TIPOS = [
        "Kinesiología", "Quiropráctica", "Fisiatría",
        "Masoterapia", "Crioterapia", "Termoterapia",
    ]
    _MOLESTIAS_ZONAS = [
        "Cuello", "Espalda alta", "Espalda baja",
        "Hombro izq.", "Hombro der.",
        "Muslo izq.", "Muslo der.",
        "Rodilla izq.", "Rodilla der.",
        "Pantorrilla izq.", "Pantorrilla der.",
        "Tobillo izq.", "Tobillo der.",
    ]
    _MOLESTIAS_COMENTARIOS = [
        "Tratamiento preventivo + activación pre sesión.",
        "Sobrecarga de fin de semana. TMO + crioterapia.",
        "Punto gatillo a la palpación. Liberación miofascial.",
        "Rigidez matinal moderada. Movilizaciones articulares.",
        "Molestia post entrenamiento. Manejo conservador.",
        "Trabajo correctivo + ejercicios de estabilización.",
    ]

    def _seed_molestias_for_player(
        self, player, template: "ExamTemplate", rng: random.Random,
        now: datetime,
    ) -> int:
        """Sprinkle ~1-2 molestias entries per week across the last 8
        weeks. Independent random seed per player so re-runs are stable.
        """
        # Healthy mode: keep the squad symptom-free (no discomfort noise).
        if getattr(self, "healthy", False):
            return 0
        weeks_back = 8
        entries_per_week_distribution = [0, 0, 1, 1, 1, 2, 2, 3]
        created = 0
        for w in range(weeks_back):
            n = rng.choice(entries_per_week_distribution)
            for _ in range(n):
                day_offset = rng.randint(0, 6)
                hour = rng.randint(9, 17)
                recorded_at = (
                    now - timedelta(weeks=w + 1)
                    + timedelta(days=day_offset, hours=hour)
                )
                raw_data = {
                    "tipo": rng.choice(self._MOLESTIAS_TIPOS),
                    "zona": rng.choice(self._MOLESTIAS_ZONAS),
                    "comentarios": rng.choice(self._MOLESTIAS_COMENTARIOS),
                }
                result_data, inputs_snapshot = compute_result_data(
                    template, raw_data, player=player,
                )
                ExamResult.objects.create(
                    player=player,
                    template=template,
                    recorded_at=recorded_at,
                    result_data=result_data,
                    inputs_snapshot=inputs_snapshot,
                )
                created += 1
        return created

    # ------------------------------------------------------------------
    # Check-IN — daily wellness checklist, 1 entry/day per player
    # ------------------------------------------------------------------

    def _seed_check_in_for_player(
        self, player, template: "ExamTemplate", rng: random.Random,
        now: datetime,
    ) -> int:
        """One Check-IN per day for the last 30 days. Each axis is a
        Likert 1-5 sampled around a per-player baseline so the trend
        feels realistic (a player drifting toward fatigue, another
        consistently rested, etc.)."""
        days_back = 30
        # Per-player baseline ∈ [3.0, 4.5] biased toward good values.
        # Healthy mode tightens it to [4.2, 4.9] so every axis lands in the
        # good band (4–5) with minimal jitter.
        healthy = getattr(self, "healthy", False)
        baseline = (4.2 + rng.random() * 0.7) if healthy else (3.0 + rng.random() * 1.5)
        jitter = 0.6 if healthy else 1.6
        created = 0
        for d in range(days_back, 0, -1):
            # Daily jitter around baseline, clamped 1..5.
            def sample_axis() -> int:
                v = baseline + (rng.random() - 0.5) * jitter
                return max(1, min(5, round(v)))
            recorded_at = now - timedelta(days=d, hours=rng.randint(7, 9))
            raw_data = {
                "doms":   sample_axis(),
                "animo":  sample_axis(),
                "estres": sample_axis(),
                "fatiga": sample_axis(),
                "sueno":  sample_axis(),
            }
            result_data, inputs_snapshot = compute_result_data(
                template, raw_data, player=player,
            )
            ExamResult.objects.create(
                player=player,
                template=template,
                recorded_at=recorded_at,
                result_data=result_data,
                inputs_snapshot=inputs_snapshot,
            )
            created += 1
        return created
