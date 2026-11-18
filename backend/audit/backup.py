"""Daily database backup: pg_dump → verify → private S3 bucket.

* Custom-format dump (`pg_dump -Fc`), the whole database.
* Verified before upload: `pg_restore --list` must read it back.
* Uploaded with a put-only key to `BACKUP_BUCKET` (SSE AES-256). The key
  cannot list, read or delete; the bucket's versioning and lifecycle rules
  keep `diario/` 35 days and `mensual/` (the 1st of each month) 13 months.
* Every run leaves a `BackupRun` row, failed or not, so the club can see when
  the last good copy was made (Configuraciones › Registro).
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile

from django.conf import settings
from django.utils import timezone

from .models import BackupRun

logger = logging.getLogger(__name__)


def _pg_env() -> dict:
    db = settings.DATABASES["default"]
    env = dict(os.environ)
    env.update({"PGHOST": str(db.get("HOST") or ""), "PGPORT": str(db.get("PORT") or "5432"),
                "PGUSER": str(db.get("USER") or ""), "PGPASSWORD": str(db.get("PASSWORD") or ""),
                "PGDATABASE": str(db.get("NAME") or "")})
    return env


def _client():
    import boto3
    return boto3.client(
        "s3", region_name=settings.BACKUP_AWS_REGION,
        aws_access_key_id=settings.BACKUP_AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.BACKUP_AWS_SECRET_ACCESS_KEY or None,
    )


def run_backup(*, upload: bool = True) -> BackupRun:
    run = BackupRun.objects.create()
    now = timezone.localtime()
    name = f"slab-{now:%Y%m%dT%H%M%S}.dump"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, name)
            env = _pg_env()
            subprocess.run(["pg_dump", "-Fc", "--no-owner", "--no-privileges", "-f", path],
                           env=env, check=True, capture_output=True, timeout=1800)
            listing = subprocess.run(["pg_restore", "--list", path], check=True,
                                     capture_output=True, text=True, timeout=600)
            run.tables = sum(1 for ln in listing.stdout.splitlines() if " TABLE DATA " in ln)
            if not run.tables:
                raise RuntimeError("El respaldo no contiene datos de tablas.")
            run.size_bytes = os.path.getsize(path)
            if upload:
                if not settings.BACKUP_BUCKET:
                    raise RuntimeError("BACKUP_BUCKET no está configurado.")
                s3 = _client()
                keys = [f"diario/{name}"] + ([f"mensual/{name}"] if now.day == 1 else [])
                for key in keys:
                    with open(path, "rb") as fh:
                        s3.put_object(Bucket=settings.BACKUP_BUCKET, Key=key, Body=fh,
                                      ServerSideEncryption="AES256")
                run.key = keys[0]
            else:
                run.key = f"(local) {name}"
        run.status = BackupRun.OK
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        run.error = f"{exc.cmd[0]}: {err.strip()[:2000]}"
        logger.error("backup failed: %s", run.error)
    except Exception as exc:  # noqa: BLE001
        run.error = f"{type(exc).__name__}: {str(exc)[:2000]}"
        logger.exception("backup failed")
    run.finished_at = timezone.now()
    run.save()
    return run
