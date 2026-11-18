from django.core.management.base import BaseCommand, CommandError

from audit.backup import run_backup


class Command(BaseCommand):
    help = "Respaldo de la base: pg_dump, verificación con pg_restore --list y subida a BACKUP_BUCKET."

    def add_arguments(self, parser):
        parser.add_argument("--no-upload", action="store_true", help="Solo genera y verifica el respaldo.")

    def handle(self, *args, **opts):
        run = run_backup(upload=not opts["no_upload"])
        if run.status != run.OK:
            raise CommandError(run.error)
        self.stdout.write(self.style.SUCCESS(
            f"OK {run.key} · {run.size_bytes / 1e6:.1f} MB · {run.tables} tablas verificadas"))
