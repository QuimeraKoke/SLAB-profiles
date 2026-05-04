"""Celery tasks for the goals/alerts engine."""

from __future__ import annotations

import logging
from uuid import UUID

from celery import shared_task

from .evaluator import apply_due_goals, evaluate_goal_warnings

logger = logging.getLogger(__name__)


@shared_task(name="goals.tasks.evaluate_due_goals")
def evaluate_due_goals():
    """Daily tick wrapping `apply_due_goals()` + `evaluate_goal_warnings()`.

    The two passes are intentionally sequential and within the same task —
    if a goal hits its due_date it gets transitioned (and any warning is
    auto-dismissed) before the warning pass runs, so we never re-warn
    a goal we just closed.
    """
    due_summary = apply_due_goals()
    warning_summary = evaluate_goal_warnings()
    logger.info(
        "evaluate_due_goals: evaluated=%(evaluated)s met=%(met)s missed=%(missed)s "
        "alerts_fired=%(alerts_fired)s",
        due_summary,
    )
    logger.info(
        "evaluate_goal_warnings: checked=%(checked)s warned=%(warned)s",
        warning_summary,
    )
    return {"due": due_summary, "warnings": warning_summary}


@shared_task(name="goals.tasks.send_alert_email")
def send_alert_email(alert_id: str) -> dict:
    """Notify everyone with access to the alert's player by email.

    Recipients are derived from `StaffMembership` rows whose scoping would
    let them see (a) the player's category, (b) the source template's
    department (when applicable). Platform admins (no membership) are NOT
    spammed — they have admin access for a reason and can opt in later.

    The task is fire-and-forget. Failures log but don't raise so a flaky
    SMTP doesn't blow up the alert pipeline.
    """
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    from core.models import Category, Department, StaffMembership
    from .models import Alert, AlertSource

    alert = (
        Alert.objects
        .filter(pk=alert_id)
        .select_related("player__category__club")
        .first()
    )
    if alert is None:
        logger.warning("send_alert_email: alert %s not found", alert_id)
        return {"sent": 0}

    player = alert.player
    club = player.category.club

    # Resolve the source template's department when the alert came from a
    # template (goal / threshold / goal_warning all carry source_id pointing
    # at a Goal or AlertRule which has a template FK).
    department: Department | None = _department_for_alert(alert)

    # Collect candidate recipients via StaffMembership scoping.
    qs = StaffMembership.objects.select_related("user").filter(
        club=club, user__is_active=True, user__email__contains="@",
    )
    if not _membership_unscoped(qs, "all_categories"):
        # Some members are scoped — narrow to those that include this player's category.
        qs = qs.filter(
            models.Q(all_categories=True) | models.Q(categories=player.category),
        ).distinct()
    if department is not None:
        qs = qs.filter(
            models.Q(all_departments=True) | models.Q(departments=department),
        ).distinct()
    recipients = sorted({m.user.email for m in qs if m.user.email})
    if not recipients:
        logger.info("send_alert_email: no recipients for alert %s", alert_id)
        return {"sent": 0}

    subject_prefix = {
        AlertSource.GOAL: "[Objetivo no cumplido]",
        AlertSource.GOAL_WARNING: "[Aviso de objetivo]",
        AlertSource.THRESHOLD: "[Alerta de umbral]",
    }.get(alert.source_type, "[Alerta]")
    subject = f"{subject_prefix} {player.first_name} {player.last_name}"

    profile_url = (
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}"
        f"/perfil/{player.id}?tab=objetivos"
    )
    text_body = (
        f"Jugador: {player.first_name} {player.last_name}\n"
        f"Categoría: {player.category.name}\n"
        f"Severidad: {alert.severity}\n\n"
        f"{alert.message}\n\n"
        f"Abrir perfil: {profile_url}\n"
    )
    html_body = (
        f'<p><strong>Jugador:</strong> {player.first_name} {player.last_name}<br>'
        f'<strong>Categoría:</strong> {player.category.name}<br>'
        f'<strong>Severidad:</strong> {alert.severity}</p>'
        f'<p>{alert.message}</p>'
        f'<p><a href="{profile_url}">Abrir perfil del jugador</a></p>'
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send(fail_silently=False)
    except Exception as exc:
        logger.warning("send_alert_email failed for alert %s: %s", alert_id, exc)
        return {"sent": 0, "error": str(exc)}
    logger.info("send_alert_email: alert %s → %d recipients", alert_id, len(recipients))
    return {"sent": len(recipients)}


def _department_for_alert(alert):
    """Resolve the relevant Department for an alert, or None."""
    from .models import AlertRule, AlertSource, Goal

    if alert.source_type in (AlertSource.GOAL, AlertSource.GOAL_WARNING):
        goal = Goal.objects.select_related("template__department").filter(
            pk=alert.source_id,
        ).first()
        return goal.template.department if goal else None
    if alert.source_type == AlertSource.THRESHOLD:
        rule = AlertRule.objects.select_related("template__department").filter(
            pk=alert.source_id,
        ).first()
        return rule.template.department if rule else None
    return None


def _membership_unscoped(qs, flag: str) -> bool:
    """True iff every membership in the queryset has the given 'all_*' flag set —
    i.e., we don't need to filter by the matching M2M.
    """
    return not qs.filter(**{flag: False}).exists()


# Late import to avoid circular reference at module top.
from django.db import models  # noqa: E402
