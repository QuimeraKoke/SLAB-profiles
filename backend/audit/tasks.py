from celery import shared_task


@shared_task(name="audit.tasks.backup_database")
def backup_database():
    from .backup import run_backup
    run = run_backup()
    return {"status": run.status, "key": run.key, "size": run.size_bytes, "error": run.error[:200]}
