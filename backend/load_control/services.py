"""State changes of a microcycle that more than one caller needs."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from load_control.models import LoadControlConfig, Microcycle
from load_control.reference import compute_reference


@transaction.atomic
def open_microcycle(microcycle: Microcycle, *, now=None) -> Microcycle:
    """Freeze the match reference as of the first day and open the plan.

    Freezing is the point: a match played next week must not rewrite the
    targets of this one, so the evaluation of a closed week stays the one the
    staff saw (PLAN_CONTROL_CARGA.md §4.0, "congelamiento")."""
    if microcycle.status != Microcycle.STATUS_DRAFT:
        raise ValidationError("Sólo una semana en borrador se puede publicar.")
    cfg = LoadControlConfig.resolved(microcycle.club, microcycle.bracket)
    microcycle.ref_snapshot = compute_reference(
        club=microcycle.club, bracket=microcycle.bracket,
        anchor=microcycle.start_date, cfg=cfg)
    microcycle.frozen_at = now or timezone.now()
    microcycle.status = Microcycle.STATUS_OPEN
    microcycle.save(update_fields=["ref_snapshot", "frozen_at", "status", "updated_at"])
    return microcycle
