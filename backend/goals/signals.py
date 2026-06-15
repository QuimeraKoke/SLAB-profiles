"""Live re-evaluation: any new ExamResult triggers active goals on the same
(player, template) to re-check, so a goal can flip to MET as soon as a
qualifying reading is saved (no need to wait for the daily Celery tick).

Filled in when the evaluator lands. Importing the module here is enough to
register the receiver(s) on app boot.

Bulk loaders (legacy migration, fixtures, big imports) should wrap their
writes in :func:`suppress_alert_evaluation` so the signal does NOT fire on
every historical row — otherwise an alert message ends up reflecting some
arbitrary intermediate reading rather than the player's current state.
The caller is then responsible for running a finalize pass against the
latest result per (player, template) — see
``goals.evaluator.finalize_threshold_alerts_for_template``.
"""

import contextlib
import contextvars

from django.db.models.signals import post_save
from django.dispatch import receiver

from exams.models import ExamResult


# Thread/async-safe flag honored by the post_save receiver below. ContextVar
# (not threading.local) so it composes correctly with Django's async views
# and Celery's task isolation.
_suppress_alerts: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "suppress_alerts", default=False,
)


@contextlib.contextmanager
def suppress_alert_evaluation():
    """Skip alert / goal evaluation on ExamResult saves inside this block.

    Used by bulk loaders so 1,937 antropometría rows don't each fire alert
    evaluation against intermediate values. The caller is responsible for
    running ``finalize_threshold_alerts_for_template`` afterwards to evaluate
    each player's latest reading once.
    """
    token = _suppress_alerts.set(True)
    try:
        yield
    finally:
        _suppress_alerts.reset(token)


@receiver(post_save, sender=ExamResult)
def reevaluate_goals_on_result_save(sender, instance, created, **kwargs):
    if not created:
        return  # only the initial save can flip a goal to MET / fire a threshold
    if _suppress_alerts.get():
        return  # bulk loader is in charge; it will finalize afterwards
    # Lazy import — the evaluator may not be imported during early Django boot.
    from .evaluator import (
        evaluate_threshold_rules_for_result,
        sync_evaluate_for_result,
    )

    sync_evaluate_for_result(instance)
    evaluate_threshold_rules_for_result(instance)
