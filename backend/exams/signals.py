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

from decimal import Decimal, InvalidOperation

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ExamResult


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


@receiver(post_save, sender=ExamResult)
def medication_wada_alert_on_result_save(sender, instance, created, **kwargs):
    """Fire a WADA alert when a result records a flagged medication.

    Looks for a `medicamento` field on the template carrying an
    `option_risk` map. If the chosen medicine resolves to PROHIBIDO or
    CONDICIONAL, raises an Alert with `source_type=MEDICATION` and
    `source_id=result.id` (one alert per result — re-runs of the signal
    are idempotent thanks to `_upsert_alert`).

    PERMITIDO medicines are silent. Templates without a `medicamento`
    field or without `option_risk` metadata are skipped — this signal is
    safe to leave globally subscribed.
    """
    if not created:
        return

    template = instance.template
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
        return

    chosen = (instance.result_data or {}).get("medicamento")
    if not chosen:
        return

    risk = (med_field["option_risk"].get(chosen) or "").upper()
    if risk not in {"PROHIBIDO", "CONDICIONAL"}:
        return

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
