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


def get_saved_pdf(player, kind: str, signature: str) -> bytes | None:
    """Return the stored PDF bytes for this exact data signature, or None
    if there's no snapshot (or its file is unreadable → regenerate)."""
    from dashboards.models import PlayerReportSnapshot

    snap = (
        PlayerReportSnapshot.objects
        .filter(player=player, kind=kind, data_hash=signature)
        .first()
    )
    if snap is None or not snap.pdf:
        return None
    try:
        with snap.pdf.open("rb") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001 — a missing storage file shouldn't 500 the download
        logger.exception("Saved report PDF unreadable (snapshot=%s); regenerating.", snap.pk)
        return None


def save_pdf(
    player, kind: str, signature: str, pdf_bytes: bytes, *, model: str, narrative
) -> None:
    """Persist a freshly-rendered report. Swallows the unique-constraint
    race (a concurrent identical request already saved it) — the point is
    that exactly one snapshot exists per signature, not who wrote it."""
    from dashboards.models import PlayerReportSnapshot

    snap = PlayerReportSnapshot(
        player=player, kind=kind, data_hash=signature,
        model=model or "", narrative=narrative or None,
    )
    try:
        snap.pdf.save(f"{signature}.pdf", ContentFile(pdf_bytes), save=True)
    except IntegrityError:
        logger.info("Report snapshot already saved concurrently (sig=%s).", signature[:12])


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)
