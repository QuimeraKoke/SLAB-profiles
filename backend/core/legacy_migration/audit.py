"""JSONL audit log for the legacy migrator.

Every action (created / updated / skipped / failed) is appended as one
JSON line so a post-run grep tells you exactly what happened. The file
lives at `BASE_DIR/migration_runs/run-YYYYMMDDTHHMM.jsonl`. The path is
returned from `AuditLog.path` so the management command can echo it.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings


class AuditLog:
    """Append-only JSONL writer with summary counters per phase."""

    def __init__(self, run_id: str | None = None, dry_run: bool = False) -> None:
        ts = run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
        runs_dir = Path(getattr(settings, "BASE_DIR", ".")) / "migration_runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        suffix = "-DRY" if dry_run else ""
        self.path: Path = runs_dir / f"run-{ts}{suffix}.jsonl"
        self.dry_run = dry_run
        self._fh = self.path.open("a", encoding="utf-8")
        self._counts: dict[str, dict[str, int]] = {}

    def _write(self, payload: dict[str, Any]) -> None:
        payload.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        payload.setdefault("dry_run", self.dry_run)
        self._fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def record(
        self,
        *,
        phase: str,
        action: str,                  # created / updated / skipped / failed
        source_table: str,
        source_pk: Any,
        target_model: str | None = None,
        target_pk: Any | None = None,
        reason: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record a single source-row outcome."""
        self._counts.setdefault(phase, {}).setdefault(action, 0)
        self._counts[phase][action] += 1
        payload: dict[str, Any] = {
            "phase": phase,
            "action": action,
            "source_table": source_table,
            "source_pk": source_pk,
        }
        if target_model:
            payload["target_model"] = target_model
        if target_pk:
            payload["target_pk"] = target_pk
        if reason:
            payload["reason"] = reason
        if extra:
            payload["extra"] = extra
        self._write(payload)

    def info(self, message: str, **extra: Any) -> None:
        """Free-form informational log line (phase start/end, totals, …)."""
        payload = {"level": "info", "message": message, **extra}
        self._write(payload)

    def warn(self, message: str, **extra: Any) -> None:
        payload = {"level": "warn", "message": message, **extra}
        self._write(payload)

    def summary(self) -> dict[str, dict[str, int]]:
        """Per-phase totals: {phase: {action: count}}."""
        return dict(self._counts)

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()
