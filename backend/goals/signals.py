"""Live re-evaluation: any new ExamResult triggers active goals on the same
(player, template) to re-check, so a goal can flip to MET as soon as a
qualifying reading is saved (no need to wait for the daily Celery tick).

Filled in when the evaluator lands. Importing the module here is enough to
register the receiver(s) on app boot.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from exams.models import ExamResult


@receiver(post_save, sender=ExamResult)
def reevaluate_goals_on_result_save(sender, instance, created, **kwargs):
    if not created:
        return  # only the initial save can flip a goal to MET / fire a threshold
    # Lazy import — the evaluator may not be imported during early Django boot.
    from .evaluator import (
        evaluate_threshold_rules_for_result,
        sync_evaluate_for_result,
    )

    sync_evaluate_for_result(instance)
    evaluate_threshold_rules_for_result(instance)
