"""Django config package.

Importing the Celery app here ensures it's available whenever Django boots —
@shared_task decorators in app modules find the right registry, and the
manage.py shell or runserver can introspect tasks via `celery_app.tasks`.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
