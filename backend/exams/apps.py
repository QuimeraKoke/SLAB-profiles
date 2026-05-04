from django.apps import AppConfig


class ExamsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "exams"

    def ready(self):
        # Wire post_save handler for ExamResult → Player profile writeback.
        from . import signals  # noqa: F401
