from django.apps import AppConfig


class GoalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "goals"

    def ready(self):
        # Wire post_save signal so new ExamResult triggers re-evaluation.
        from . import signals  # noqa: F401
