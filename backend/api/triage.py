"""Player triage report — aggregates the 4 sections of the Resumen tab.

This is the **single source of truth** for the player-snapshot data. Both
the API endpoint (`GET /players/{id}/triage`) and the PDF generator
(`GET /players/{id}/triage.pdf`) call into `build_triage_payload()` so
they never diverge.

Sections (in order, matching the agent-validated UI structure):

  1. ``alerts``           — every active Alert for this player,
                            severity-ordered. Headline only (no numeric
                            value — that's section 2's job).

  2. ``alerted_metrics``  — for each active THRESHOLD alert, the field
                            that triggered it: current value + previous
                            value + delta. Cross-linked back to section 1
                            via ``alert_id``.

  3. ``other_metrics``    — every OTHER tracked exam field (i.e. fields
                            with reference_ranges or an active rule, NOT
                            currently triggering an alert), with up to
                            ~30 days of history for a sparkline + delta
                            vs. previous.

  4. ``last_match``       — the most recent match-event the player's
                            CATEGORY had, with the player's match_role
                            label (Titular / Lesionado / No citado / …)
                            and, if cited, the performance data linked
                            to that event.

All field selection (which counts as "tracked", which `direction_of_good`
applies) is driven by ``ExamTemplate.config_schema`` — never hardcoded
per slug. Adding a new template with reference_ranges automatically
surfaces it in section 3.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from core.models import Player
from dashboards.references import build_metric_references
from events.models import Event, EventParticipant
from exams.models import ExamResult, ExamTemplate
from goals.models import Alert, AlertRule, AlertSource, AlertStatus


# Sections 3 history window. Keep small enough to fit a sparkline; large
# enough to register a multi-week trend.
HISTORY_DAYS = 30


# Sections 1 + 2 cap. Section 1 is headline-only and the panel is
# severity-ordered; 8 is more than any healthy player should have and
# already overflows the one-viewport goal. Anything beyond gets a "+N más"
# tail in the UI.
MAX_ALERTS = 8


@dataclass
class FieldRef:
    """Locator for a single exam field across a player's data."""
    template_id: UUID
    template_slug: str
    template_label: str
    field_key: str
    field_label: str
    unit: str | None
    direction_of_good: str | None  # "up" / "down" / None


def _field_specs(template: ExamTemplate) -> dict[str, dict]:
    """Flatten a template's config_schema into {field_key: field_dict}."""
    fields = (template.config_schema or {}).get("fields") or []
    return {f.get("key"): f for f in fields if isinstance(f, dict) and f.get("key")}


def _coerce_number(raw: Any) -> float | None:
    """ExamResult.result_data carries mixed types — coerce to float for
    delta math. Returns None if value isn't a finite number."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None  # booleans aren't comparable as scalars
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return v


def _build_field_ref(template: ExamTemplate, spec: dict) -> FieldRef:
    return FieldRef(
        template_id=template.id,
        template_slug=template.slug,
        template_label=template.name,
        field_key=spec.get("key"),
        field_label=spec.get("label") or spec.get("key"),
        unit=spec.get("unit"),
        direction_of_good=spec.get("direction_of_good"),
    )


def _serialize_field(ref: FieldRef) -> dict:
    return {
        "field_key": ref.field_key,
        "field_label": ref.field_label,
        "template_slug": ref.template_slug,
        "template_label": ref.template_label,
        "unit": ref.unit,
        "direction_of_good": ref.direction_of_good,
    }


def _two_most_recent(
    results: list[ExamResult], field_key: str,
) -> tuple[tuple[float, datetime] | None, tuple[float, datetime] | None]:
    """Walk ordered ExamResults and pluck the two most-recent finite
    numeric values for the given field_key. Returns (current, previous).
    Each item is (value, recorded_at) or None.
    """
    current = None
    previous = None
    for r in results:
        v = _coerce_number((r.result_data or {}).get(field_key))
        if v is None:
            continue
        if current is None:
            current = (v, r.recorded_at)
        elif previous is None:
            previous = (v, r.recorded_at)
            break
    return current, previous


def _delta_payload(
    current: tuple[float, datetime] | None,
    previous: tuple[float, datetime] | None,
) -> dict:
    if current is None:
        return {
            "current_value": None,
            "current_at": None,
            "previous_value": None,
            "previous_at": None,
            "delta": None,
            "delta_pct": None,
        }
    cur_v, cur_at = current
    payload = {
        "current_value": cur_v,
        "current_at": cur_at,
        "previous_value": None,
        "previous_at": None,
        "delta": None,
        "delta_pct": None,
    }
    if previous is not None:
        prev_v, prev_at = previous
        payload["previous_value"] = prev_v
        payload["previous_at"] = prev_at
        payload["delta"] = cur_v - prev_v
        if prev_v != 0:
            payload["delta_pct"] = (cur_v - prev_v) / prev_v * 100
    return payload


def _player_templates(player: Player) -> list[ExamTemplate]:
    """All templates that apply to this player's category — that's the
    universe of fields we consider for "tracked". A field is tracked iff
    (a) it has non-empty reference_ranges, OR (b) an active AlertRule
    targets it."""
    if player.category_id is None:
        return []
    return list(
        ExamTemplate.objects
        .filter(applicable_categories=player.category, is_active_version=True)
        .order_by("name")
    )


def _is_tracked_field(spec: dict, rule_keys: set[tuple[UUID, str]],
                       template_id: UUID) -> bool:
    if spec.get("type") not in ("number", "calculated"):
        return False
    ranges = spec.get("reference_ranges") or []
    if ranges:
        return True
    if (template_id, spec.get("key")) in rule_keys:
        return True
    return False


def build_triage_payload(player: Player) -> dict:
    """Returns the full triage payload as a plain dict — Ninja serializes
    it via TriageOut and the PDF generator consumes it directly."""
    now = timezone.now()
    window_start = now - timedelta(days=HISTORY_DAYS)

    templates = _player_templates(player)
    templates_by_id = {t.id: t for t in templates}
    template_field_specs = {t.id: _field_specs(t) for t in templates}

    # ─── 1) Active alerts (all sources) ──────────────────────────────
    # The severity column is text ("info"/"warning"/"critical") — alphabetic
    # sort puts info first. Use a custom rank so critical floats to the top.
    severity_rank = Case(
        When(severity="critical", then=Value(0)),
        When(severity="warning", then=Value(1)),
        When(severity="info", then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )
    alerts_qs = (
        Alert.objects
        .filter(player=player, status=AlertStatus.ACTIVE)
        .annotate(_severity_rank=severity_rank)
        .order_by("_severity_rank", "-fired_at")[:MAX_ALERTS]
    )
    alerts = list(alerts_qs)

    # Pre-load all AlertRules referenced by threshold alerts in one query.
    threshold_alerts = [a for a in alerts if a.source_type == AlertSource.THRESHOLD]
    rule_ids = [a.source_id for a in threshold_alerts]
    rules_by_id: dict[UUID, AlertRule] = {
        r.id: r for r in AlertRule.objects.filter(id__in=rule_ids).select_related("template")
    } if rule_ids else {}

    # ─── 2) Alerted metrics ──────────────────────────────────────────
    # For each threshold alert, find the (template, field) and pull the
    # last 2 readings. Dedupe so the same (template, field) doesn't show
    # twice if two rules target it.
    alerted_metrics: list[dict] = []
    alerted_pairs: set[tuple[UUID, str]] = set()
    # Cache ExamResults per template (one query per template, reused for
    # alerted_metrics + other_metrics + history).
    results_by_template: dict[UUID, list[ExamResult]] = {}

    def _results_for(template_id: UUID) -> list[ExamResult]:
        if template_id in results_by_template:
            return results_by_template[template_id]
        qs = (
            ExamResult.objects
            .filter(player=player, template_id=template_id)
            .order_by("-recorded_at")
        )
        results = list(qs)
        results_by_template[template_id] = results
        return results

    for alert in threshold_alerts:
        rule = rules_by_id.get(alert.source_id)
        if rule is None or rule.template_id not in templates_by_id:
            continue
        spec = template_field_specs[rule.template_id].get(rule.field_key)
        if spec is None:
            continue
        key = (rule.template_id, rule.field_key)
        if key in alerted_pairs:
            continue
        alerted_pairs.add(key)

        results = _results_for(rule.template_id)
        current, previous = _two_most_recent(results, rule.field_key)
        template = templates_by_id[rule.template_id]
        ref = _build_field_ref(template, spec)
        alerted_metrics.append({
            "alert_id": alert.id,
            **_serialize_field(ref),
            **_delta_payload(current, previous),
            "references": build_metric_references(
                template, rule.field_key, spec,
                current[0] if current else None,
                sex=player.sex or None,
                position=player.position.name if player.position else None,
                category=player.category,
            ),
        })

    # ─── 3) Other tracked metrics with 30d history ───────────────────
    # Build the set of (template, field) keys targeted by ANY active rule
    # for this player's templates (not just the firing ones) so we include
    # tracked-but-not-firing fields too — that's what "tracked" means.
    active_rule_keys: set[tuple[UUID, str]] = set(
        AlertRule.objects
        .filter(template__in=templates, is_active=True)
        .values_list("template_id", "field_key")
    )

    other_metrics: list[dict] = []
    for template in templates:
        specs = template_field_specs[template.id]
        for field_key, spec in specs.items():
            if (template.id, field_key) in alerted_pairs:
                continue
            if not _is_tracked_field(spec, active_rule_keys, template.id):
                continue

            results = _results_for(template.id)
            current, previous = _two_most_recent(results, field_key)
            if current is None:
                continue  # never recorded — skip the empty row

            # 30-day history for sparkline (oldest → newest).
            history: list[dict] = []
            for r in reversed(results):
                if r.recorded_at < window_start:
                    continue
                v = _coerce_number((r.result_data or {}).get(field_key))
                if v is None:
                    continue
                history.append({"value": v, "recorded_at": r.recorded_at})

            ref = _build_field_ref(template, spec)
            other_metrics.append({
                **_serialize_field(ref),
                **_delta_payload(current, previous),
                "history_30d": history,
                "references": build_metric_references(
                    template, field_key, spec,
                    current[0] if current else None,
                    sex=player.sex or None,
                    position=player.position.name if player.position else None,
                    category=player.category,
                    history=history,
                ),
            })

    # Stable ordering: by template label, then field label.
    other_metrics.sort(key=lambda m: (m["template_label"], m["field_label"]))

    # ─── 4) Last match ───────────────────────────────────────────────
    last_match = _build_last_match(player)

    return {
        "player": {
            "id": player.id,
            "first_name": player.first_name,
            "last_name": player.last_name,
            "category_name": player.category.name if player.category else None,
            "position_label": (
                player.position.abbreviation if player.position else None
            ),
            "photo_url": player.photo_url or None,
        },
        "generated_at": now,
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "message": a.message,
                "fired_at": a.fired_at,
                "last_fired_at": a.last_fired_at or a.fired_at,
                "source_type": a.source_type,
                "source_template_slug": (
                    rules_by_id.get(a.source_id).template.slug
                    if a.source_type == AlertSource.THRESHOLD
                    and a.source_id in rules_by_id
                    else None
                ),
            }
            for a in alerts
        ],
        "alerted_metrics": alerted_metrics,
        "other_metrics": other_metrics,
        "last_match": last_match,
    }


def _build_last_match(player: Player) -> dict | None:
    """Return the most recent match event for this player's CATEGORY,
    with the player's participation (or "no citado" sentinel) and any
    match-linked performance results.

    "Most recent" = chronologically latest match whose start time has
    already passed, OR if none have passed yet, the next upcoming one —
    so an idle preseason still shows the team's last/next fixture.
    """
    if player.category is None:
        return None

    now = timezone.now()
    # Most recent past match first; fall back to upcoming if no past exists.
    past = (
        Event.objects
        .filter(
            event_type=Event.TYPE_MATCH,
            category=player.category,
            starts_at__lte=now,
        )
        .order_by("-starts_at")
        .first()
    )
    upcoming = (
        Event.objects
        .filter(
            event_type=Event.TYPE_MATCH,
            category=player.category,
            starts_at__gt=now,
        )
        .order_by("starts_at")
        .first()
        if past is None else None
    )
    event = past or upcoming
    if event is None:
        return None

    participation = (
        EventParticipant.objects
        .filter(event=event, player=player)
        .first()
    )

    match_role_label = None
    if participation and participation.match_role:
        choices = dict(EventParticipant.MatchRole.choices)
        match_role_label = choices.get(participation.match_role, participation.match_role)
    elif participation is None:
        match_role_label = "No citado"

    # Performance: ExamResults linked to this event (gps_partido,
    # match_performance, etc.). We surface the result_data dict per
    # template so the UI can decide which fields to render; the PDF
    # picks the headline numbers.
    performance: list[dict] = []
    if participation is not None and participation.match_role not in (
        EventParticipant.MatchRole.NO_CITADO,
        EventParticipant.MatchRole.LESIONADO,
        EventParticipant.MatchRole.SUSPENDIDO,
        None,
    ):
        match_results = (
            ExamResult.objects
            .filter(player=player, event=event)
            .select_related("template")
        )
        for r in match_results:
            performance.append({
                "template_slug": r.template.slug,
                "template_label": r.template.name,
                "result_data": r.result_data or {},
            })

    return {
        "event_id": event.id,
        "event_title": event.title,
        "event_starts_at": event.starts_at,
        "is_past": past is not None,
        "match_role": participation.match_role if participation else None,
        "match_role_label": match_role_label,
        "minutes_played": participation.minutes_played if participation else None,
        "goals": participation.goals if participation else None,
        "performance": performance,
    }
