"""Content-addressed persistence for generated player report PDFs.

Same input data ⇒ same report. We hash the report's *input* (the triage
payload minus volatile fields like ``generated_at``) together with the LLM
model and a render-format version, then store the rendered PDF in the
default storage (S3 / MinIO) with a ``PlayerReportSnapshot`` index row. A
download recomputes the signature: a match returns the stored PDF verbatim
(no LLM call, no re-render); a miss regenerates once and saves.

This is what guarantees an LLM-backed report never differs for unchanged
data, and never costs a second generation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.files.base import ContentFile
from django.db import IntegrityError

logger = logging.getLogger(__name__)

# Payload keys that vary per request and must NOT affect the signature —
# otherwise the cache could never hit. `generated_at` is `now()`.
_VOLATILE_KEYS = {"generated_at"}


def stable_json(payload: dict) -> str:
    """Deterministic JSON of the report's input data with volatile keys
    stripped. Used for both the signature and (so the prompt is stable too)
    the narrative prompt."""
    data = {k: v for k, v in payload.items() if k not in _VOLATILE_KEYS}
    return json.dumps(data, default=_json_default, ensure_ascii=False, sort_keys=True)


def report_signature(
    payload: dict,
    *,
    model: str,
    kind: str,
    render_version: int,
    agent_fingerprint: str = "",
) -> str:
    """SHA-256 hex over (kind, render version, agent config, model, stable
    input data).

    `render_version` lets a layout change invalidate every prior snapshot
    without touching the data — bump it when the rendered output changes.
    `model` is included so switching LLM models regenerates rather than
    serving a narrative from a different model. `agent_fingerprint` is the
    InsightAgent's config hash, so editing its prompt/knowledge regenerates
    saved reports instead of serving a stale narrative."""
    basis = (
        f"{kind}\n{render_version}\n{agent_fingerprint}\n{model}\n"
        f"{stable_json(payload)}"
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def get_snapshot(player, kind: str, signature: str):
    """Return the PlayerReportSnapshot for this exact data signature, or
    None. Carries the (format-independent) narrative plus whatever rendered
    files have been persisted so far."""
    from dashboards.models import PlayerReportSnapshot

    return (
        PlayerReportSnapshot.objects
        .filter(player=player, kind=kind, data_hash=signature)
        .first()
    )


def get_saved_file(player, kind: str, signature: str, *, fmt: str = "docx") -> bytes | None:
    """Return the stored bytes of the requested format (`docx` / `pdf`) for
    this data signature, or None if there's no snapshot / no file of that
    format / the file is unreadable (→ regenerate)."""
    snap = get_snapshot(player, kind, signature)
    if snap is None:
        return None
    field = getattr(snap, fmt, None)
    if not field:
        return None
    try:
        with field.open("rb") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001 — a missing storage file shouldn't 500 the download
        logger.exception("Saved report %s unreadable (snapshot=%s); regenerating.", fmt, snap.pk)
        return None


def save_file(
    player, kind: str, signature: str, file_bytes: bytes,
    *, fmt: str = "docx", model: str, narrative,
) -> None:
    """Persist a freshly-rendered report file of `fmt`, attaching it to the
    one snapshot row for this signature (creating the row if needed). The
    narrative is stored once and shared by both formats, so requesting the
    other format later reuses it — no second LLM call. Concurrency-safe via
    get_or_create + a swallowed unique-constraint race."""
    from dashboards.models import PlayerReportSnapshot

    try:
        snap, _ = PlayerReportSnapshot.objects.get_or_create(
            player=player, kind=kind, data_hash=signature,
            defaults={"model": model or "", "narrative": narrative or None},
        )
    except IntegrityError:
        snap = get_snapshot(player, kind, signature)
        if snap is None:
            logger.info("Report snapshot vanished after race (sig=%s).", signature[:12])
            return
    # Backfill the narrative if an earlier (narrative-less) row exists.
    if narrative and not snap.narrative:
        snap.narrative = narrative
        snap.model = model or snap.model
        snap.save(update_fields=["narrative", "model"])
    ext = "docx" if fmt == "docx" else "pdf"
    getattr(snap, fmt).save(f"{signature}.{ext}", ContentFile(file_bytes), save=True)


def get_saved_narrative(player, kind: str, signature: str):
    """Return the cached narrative for this signature (any format already
    generated it), or None. Lets a format render reuse a narrative produced
    by a prior render of the other format — avoiding a redundant LLM call."""
    snap = get_snapshot(player, kind, signature)
    return snap.narrative if snap is not None else None


# ─── Team-report cache (department + category keyed) ──────────────────


def get_team_snapshot(department, category, signature: str):
    from dashboards.models import TeamReportSnapshot

    return (
        TeamReportSnapshot.objects
        .filter(department=department, category=category, data_hash=signature)
        .first()
    )


def get_saved_team_file(department, category, signature: str) -> bytes | None:
    snap = get_team_snapshot(department, category, signature)
    if snap is None or not snap.docx:
        return None
    try:
        with snap.docx.open("rb") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001 — a missing storage file shouldn't 500 the download
        logger.exception("Saved team report unreadable (snapshot=%s); regenerating.", snap.pk)
        return None


def get_saved_team_narrative(department, category, signature: str):
    snap = get_team_snapshot(department, category, signature)
    return snap.narrative if snap is not None else None


def save_team_file(
    department, category, signature: str, file_bytes: bytes, *, model: str, narrative,
) -> None:
    """Persist a freshly-rendered team report Word file + its narrative,
    one row per (department, category, signature). Concurrency-safe."""
    from dashboards.models import TeamReportSnapshot

    try:
        snap, _ = TeamReportSnapshot.objects.get_or_create(
            department=department, category=category, data_hash=signature,
            defaults={"model": model or "", "narrative": narrative or None},
        )
    except IntegrityError:
        snap = get_team_snapshot(department, category, signature)
        if snap is None:
            logger.info("Team report snapshot vanished after race (sig=%s).", signature[:12])
            return
    if narrative and not snap.narrative:
        snap.narrative = narrative
        snap.model = model or snap.model
        snap.save(update_fields=["narrative", "model"])
    snap.docx.save(f"{signature}.docx", ContentFile(file_bytes), save=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)
