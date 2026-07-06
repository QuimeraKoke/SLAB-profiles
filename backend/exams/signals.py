"""ExamResult post-save side effects.

Three responsibilities triggered on every newly-created ExamResult:

1. **Player profile write-back** — fields with `writes_to_player_field` set
   copy their value into the named Player attribute (last-write-wins by
   `recorded_at`). Back-dated entries don't clobber newer readings.
2. **Episode lifecycle** — when the result is on an episodic template, the
   linked Episode's stage/status/title/ended_at are recomputed from the
   latest linked result, and the Player.status cache is recomputed from
   the player's open episodes.
3. **WADA medication alert** — when a result is saved with a medication
   whose risk level is PROHIBIDO or CONDICIONAL (per `option_risk` on the
   medicamento field), fire an Alert via the goals alert infrastructure.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import ExamResult

# A training-load breach is a "right now" signal — only sessions within this
# window create an active alert. Live entries are always recent (so real-time
# behavior is unchanged); this just stops a backfill/seed from raising stale
# alerts for sessions logged weeks ago.
_TRAINING_LOAD_ALERT_WINDOW = timedelta(days=10)


@receiver(post_save, sender=ExamResult)
def episode_lifecycle_on_result_save(sender, instance, created, **kwargs):
    """Refresh Episode + Player.status when an episode-linked result is saved."""
    if not created or instance.episode_id is None:
        return
    from .episode_lifecycle import (
        recompute_player_status,
        refresh_episode_from_results,
    )
    refresh_episode_from_results(instance.episode)
    recompute_player_status(instance.player)


@receiver(post_save, sender=ExamResult)
def writeback_player_fields_on_result_save(sender, instance, created, **kwargs):
    if not created:
        return  # Only initial save can establish a write-back.

    template = instance.template
    fields = (template.config_schema or {}).get("fields") or []
    writers = [
        f for f in fields
        if isinstance(f, dict)
        and f.get("writes_to_player_field")
        and f.get("key") in (instance.result_data or {})
    ]
    if not writers:
        return

    # Skip the writeback if a newer result exists for the same template.
    # That keeps back-dated entries from overwriting a fresher reading.
    newer_exists = (
        ExamResult.objects
        .filter(player_id=instance.player_id, template_id=template.id)
        .filter(recorded_at__gt=instance.recorded_at)
        .exists()
    )
    if newer_exists:
        return

    player = instance.player
    update_fields: list[str] = []
    for f in writers:
        value = instance.result_data.get(f["key"])
        if value in (None, ""):
            continue
        target = f["writes_to_player_field"]
        if target in {"current_weight_kg", "current_height_cm"}:
            try:
                setattr(player, target, Decimal(str(value)))
            except (InvalidOperation, TypeError, ValueError):
                continue
            update_fields.append(target)
        elif target == "sex":
            if value in {"M", "F"}:
                player.sex = value
                update_fields.append("sex")

    if update_fields:
        # Dedupe in case multiple fields write to the same attribute.
        player.save(update_fields=list(set(update_fields)))


def medication_alert_payload(template, result_data, recorded_at=None) -> tuple[str, str] | None:
    """Return `(severity, message)` for a flagged medication result, or None
    when the template isn't a medication template, no medicine was chosen, or
    the chosen medicine is PERMITIDO (silent).

    The WADA risk + notes + action are read from the `medicamento` field's
    `option_risk` / `option_notes` / `option_actions` maps (seeded from
    `data/medicamentos.csv`). Shared by the post-save signal and the
    `reevaluate_medication_alerts` command so both stay in lockstep.
    """
    fields = (template.config_schema or {}).get("fields") or []
    med_field = next(
        (
            f for f in fields
            if isinstance(f, dict)
            and f.get("key") == "medicamento"
            and isinstance(f.get("option_risk"), dict)
        ),
        None,
    )
    if med_field is None:
        return None

    chosen = (result_data or {}).get("medicamento")
    if not chosen:
        return None

    risk = (med_field["option_risk"].get(chosen) or "").upper()
    if risk not in {"PROHIBIDO", "CONDICIONAL"}:
        return None

    label = (med_field.get("option_labels") or {}).get(chosen, chosen)
    note = (med_field.get("option_notes") or {}).get(chosen, "")
    action = (med_field.get("option_actions") or {}).get(chosen, "")

    severity = "critical" if risk == "PROHIBIDO" else "warning"
    parts = [f"WADA — {label}: {risk}"]
    if note:
        parts.append(note)
    if action:
        parts.append(f"Acción: {action}")
    message = " · ".join(parts)
    if recorded_at is not None:
        from django.utils import timezone as _tz
        message = f"{message} ({_tz.localtime(recorded_at).date().isoformat()})"
    return severity, message


@receiver(post_save, sender=ExamResult)
def medication_wada_alert_on_result_save(sender, instance, created, **kwargs):
    """Fire a WADA alert when a result records a flagged medication.

    Delegates risk resolution to `medication_alert_payload`. If the chosen
    medicine resolves to PROHIBIDO or CONDICIONAL, raises an Alert with
    `source_type=MEDICATION` and `source_id=result.id` (one alert per result —
    re-runs are idempotent thanks to `_upsert_alert`).

    PERMITIDO medicines are silent. Templates without a `medicamento` field or
    without `option_risk` metadata are skipped — this signal is safe to leave
    globally subscribed.
    """
    if not created:
        return

    payload = medication_alert_payload(instance.template, instance.result_data, instance.recorded_at)
    if payload is None:
        return
    severity, message = payload

    # Lazy-import to avoid a circular dependency at app-load time.
    from goals.evaluator import _upsert_alert
    from goals.models import AlertSource

    _upsert_alert(
        player=instance.player,
        source_type=AlertSource.MEDICATION,
        source_id=instance.id,
        severity=severity,
        message=message,
    )


def enqueue_player_state_recompute(player_id) -> None:
    """Schedule a refresh of the player's materialized metric state (latest
    values + weekly chronic load) for after the current transaction commits,
    so the worker sees the committed rows. If the broker is unreachable
    (tests / no worker) it falls back to a synchronous recompute so the
    state still updates. Shared by the post_save signal and bulk writers
    (`gps_session_ingest`), which don't emit signals."""
    from django.db import transaction

    pid = str(player_id)

    def _enqueue() -> None:
        from dashboards.tasks import recompute_player_state, recompute_readiness
        try:
            recompute_player_state.delay(pid)
        except Exception:  # noqa: BLE001 — broker down: recompute inline rather than skip
            recompute_player_state(pid)
        # Readiness (agent-refined) is best-effort + signature-gated; never
        # run its LLM call inline, so skip if the broker is unreachable.
        try:
            recompute_readiness.delay(pid)
        except Exception:  # noqa: BLE001
            pass

    transaction.on_commit(_enqueue)


@receiver(post_save, sender=ExamResult)
def recompute_player_state_on_result_save(sender, instance, created, **kwargs):
    """Refresh the player's materialized metric state whenever a reading
    changes."""
    enqueue_player_state_recompute(instance.player_id)


def _num(raw):
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@receiver(post_save, sender=ExamResult)
def training_load_alert_on_result_save(sender, instance, created, **kwargs):
    """Signal wrapper around `check_training_load_alert` for single saves.
    Bulk writers (`gps_session_ingest`) don't emit post_save — they call the
    check directly per created result."""
    if not created:
        return
    check_training_load_alert(instance)


def check_training_load_alert(instance) -> None:
    """Fire an alert when a GPS *training* session reaches ≥85% of the player's
    match-load reference — acute (max match in 7 d) or chronic (max in 28 d),
    counting only matches with ≥75 GPS-min.

    Watches the cumulative external-load metrics the físico agent flagged
    (distance, player load, HSR, sprint, accel, decel, HIAA, HMLD); duration,
    mpm and max velocity are deliberately excluded. Per-result + idempotent via
    `_upsert_alert` (source_id = result id). Best-effort: never breaks a save.
    Self-filtering: non-training slugs and stale sessions (backfills) no-op.
    """
    try:
        from dashboards.player_state import (
            _GPS_TRAIN_SLUG,
            TRAINING_LOAD_ALERT_METRICS,
            TRAINING_LOAD_ALERT_RATIO,
            match_load_refs,
        )

        if instance.template.slug != _GPS_TRAIN_SLUG:
            return
        if instance.recorded_at < timezone.now() - _TRAINING_LOAD_ALERT_WINDOW:
            return  # stale session (backfill) — not an actionable load alert
        data = instance.result_data or {}
        refs = match_load_refs(
            instance.player_id, instance.recorded_at, TRAINING_LOAD_ALERT_METRICS,
        )
        if not refs:
            return  # no qualifying match to compare against

        labels = {
            f.get("key"): (f.get("label") or f.get("key"))
            for f in (instance.template.config_schema or {}).get("fields") or []
            if isinstance(f, dict) and f.get("key")
        }

        breaches: list[tuple[str, str, float]] = []  # (label, kind, pct)
        worst_pct = 0.0
        for metric in TRAINING_LOAD_ALERT_METRICS:
            val = _num(data.get(metric))
            if not val or val <= 0:
                continue
            ref = refs.get(metric) or {}
            best: tuple[float, str] | None = None  # (pct, kind)
            for kind, klabel in (("acute", "aguda"), ("chronic", "crónica")):
                r = ref.get(kind)
                if r and val >= TRAINING_LOAD_ALERT_RATIO * r:
                    pct = val / r * 100.0
                    if best is None or pct > best[0]:
                        best = (pct, klabel)
            if best is not None:
                breaches.append((labels.get(metric, metric), best[1], best[0]))
                worst_pct = max(worst_pct, best[0])

        if not breaches:
            return

        breaches.sort(key=lambda b: b[2], reverse=True)
        shown = breaches[:4]
        parts = [f"{label} {pct:.0f}% carga {kind}" for label, kind, pct in shown]
        if len(breaches) > len(shown):
            parts.append(f"+{len(breaches) - len(shown)} más")
        severity = "critical" if worst_pct >= 100 else "warning"
        message = ("Carga de entrenamiento alta (≥85% de partido) — " + " · ".join(parts)
                   + f" ({timezone.localtime(instance.recorded_at).date().isoformat()})")

        from goals.evaluator import _upsert_alert
        from goals.models import AlertSource

        _upsert_alert(
            player=instance.player,
            source_type=AlertSource.TRAINING_LOAD,
            source_id=instance.id,
            severity=severity,
            message=message,
        )
    except Exception:  # noqa: BLE001 — alert eval must never break a result save
        import logging

        logging.getLogger(__name__).exception("training-load alert evaluation failed")
