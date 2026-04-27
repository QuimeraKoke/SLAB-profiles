"""Generate fake exam results for every player so the dashboards have data.

Idempotency-friendly: deterministic per-player baselines (seeded from each
player's UUID) mean re-running with --reset reproduces the same shape.

Examples:

    # Default: 6 historical entries per (player × applicable template), spread
    # across the last 12 weeks, in every club.
    docker compose exec backend python manage.py seed_fake_exams

    # Wipe existing results first, then seed.
    docker compose exec backend python manage.py seed_fake_exams --reset

    # Heavier dataset, single club:
    docker compose exec backend python manage.py seed_fake_exams \
        --club "Demo FC" --count 12 --weeks 24

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
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Club, Player
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate

# Per-key (min, max) for numeric inputs. Anything not listed falls back to
# DEFAULT_NUMERIC_RANGE (still sensible, just less domain-specific).
NUMERIC_BASELINES: dict[str, tuple[float, float]] = {
    # Pentacompartimental
    "peso": (65.0, 85.0),
    "talla": (165.0, 190.0),
    "humero": (5.8, 7.0),
    "femur": (9.0, 10.5),
    "biestiloideo": (5.2, 6.2),
    "torax": (95.0, 108.0),
    "cintura": (72.0, 85.0),
    "caderas": (92.0, 102.0),
    "perim_brazo_relajado": (28.0, 35.0),
    "muslo_gluteo": (56.0, 64.0),
    "muslo_medio": (51.0, 58.0),
    "pierna_perim": (37.0, 42.0),
    "pliegue_triceps": (6.0, 11.0),
    "pliegue_subescapular": (8.0, 13.0),
    "pliegue_supra": (7.0, 12.0),
    "pliegue_abdomen": (10.0, 16.0),
    "pliegue_muslo": (10.0, 15.0),
    "pliegue_pierna": (4.0, 8.0),
    "envergadura": (175.0, 195.0),
    "long_brazo": (55.0, 65.0),
    "long_pierna": (90.0, 105.0),
    # Generic physical-test-ish defaults
    "dist_30": (200.0, 280.0),
    "hr_avg": (140.0, 170.0),
}

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
        parser.add_argument("--count", type=int, default=6,
                            help="Historical results per (player × template). Default: 6.")
        parser.add_argument("--weeks", type=int, default=12,
                            help="Time window for spreading results. Default: 12 weeks.")
        parser.add_argument("--reset", action="store_true",
                            help="Delete every existing ExamResult in scope before seeding.")

    def handle(self, *args, **options):
        club_name = options["club"]
        count = options["count"]
        weeks = options["weeks"]
        reset = options["reset"]

        if count <= 0:
            raise CommandError("--count must be positive.")
        if weeks <= 0:
            raise CommandError("--weeks must be positive.")

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
                self.stdout.write(self.style.NOTICE(
                    f"Club '{club.name}': deleted {deleted} existing results."
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

            with transaction.atomic():
                for player in players:
                    baseline = self._baseline_for(player.id)
                    rng = random.Random(f"{player.id}::results")
                    templates = templates_by_category[str(player.category_id)]
                    for template in templates:
                        for i in range(count):
                            recorded_at = now - step * (count - 1 - i)
                            raw_data = self._generate_raw_data(
                                template, baseline, recorded_at, rng,
                            )
                            result_data = compute_result_data(template, raw_data)
                            ExamResult.objects.create(
                                player=player,
                                template=template,
                                recorded_at=recorded_at,
                                result_data=result_data,
                            )
                            total_created += 1

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

        for field in fields:
            if not isinstance(field, dict):
                continue
            ftype = field.get("type")
            key = field.get("key")
            if not key or ftype == "calculated":
                continue
            value = self._value_for_field(field, baseline, recorded_at, rng)
            if value is not None:
                out[key] = value
        return out

    def _value_for_field(self, field: dict, baseline: dict, recorded_at: datetime,
                         rng: random.Random) -> Any:
        ftype = field.get("type")
        key = field.get("key", "")

        if ftype == "boolean":
            return rng.random() < 0.3

        if ftype == "date":
            return recorded_at.date().isoformat()

        if ftype == "categorical":
            options = field.get("options") or []
            return rng.choice(options) if options else None

        if ftype == "text":
            return self._text_for_key(key, field, rng)

        if ftype == "number":
            if key == "sexo":
                return baseline.get("sexo", 0)
            base = baseline.get(key)
            if base is None:
                low, high = DEFAULT_NUMERIC_RANGE
                base = rng.uniform(low, high)
            jittered = base * (1 + rng.uniform(-DRIFT_PCT, DRIFT_PCT))
            return round(jittered, 2)

        return None

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
