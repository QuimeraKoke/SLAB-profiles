"""Player-photo copy from legacy Google Drive URLs to SLAB storage.

The legacy `jugador.foto` / `jugador.imagen` columns hold public Google
Drive image URLs. We can either:
  (a) keep them as URLs (no copy) — fast but the photo disappears if the
      Drive owner revokes access.
  (b) fetch the bytes and store under SLAB's media root / S3 — slower
      but durable. Picked by the user.

This module implements (b) with a fallback to (a) on fetch failure.
The destination key is `players/{external_id}.jpg` so future re-runs
overwrite the same path (idempotent).
"""
from __future__ import annotations

import io
import logging
import re
from typing import Optional

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


log = logging.getLogger(__name__)


# Google Drive URL → file ID extractor. Matches both
# `https://drive.google.com/uc?export=view&id=<ID>` and
# `https://lh3.googleusercontent.com/d/<ID>=...` shapes seen in legacy.
_GDRIVE_PATTERNS = [
    re.compile(r"id=([A-Za-z0-9_-]+)"),
    re.compile(r"/d/([A-Za-z0-9_-]+)"),
]


def _extract_drive_file_id(url: str) -> Optional[str]:
    for pat in _GDRIVE_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def fetch_bytes(url: str, timeout: int = 15) -> Optional[bytes]:
    """Download an image as bytes. Returns None on any failure (network,
    HTTP non-2xx, redirect to login). Caller falls back to storing the
    URL as-is when this returns None."""
    try:
        import requests  # type: ignore
    except ImportError:
        # Use urllib stdlib fallback so the migration runs in containers
        # that don't have `requests` installed.
        from urllib.request import urlopen
        try:
            with urlopen(url, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                return resp.read()
        except Exception as exc:
            log.warning("fetch_bytes failed for %s: %s", url, exc)
            return None

    try:
        # Google Drive's `uc?export=view&id=...` URL serves either the
        # image OR a confirm-page HTML for large files. We hit the
        # `lh3.googleusercontent.com/d/<id>=w1000` form first when
        # available — it serves the bytes directly.
        gd_id = _extract_drive_file_id(url)
        if gd_id and "lh3.googleusercontent.com" not in url:
            url = f"https://lh3.googleusercontent.com/d/{gd_id}=w1000"
        r = requests.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return None
        if not r.headers.get("Content-Type", "").startswith("image/"):
            return None
        return r.content
    except Exception as exc:
        log.warning("fetch_bytes failed for %s: %s", url, exc)
        return None


def copy_player_photo_to_storage(
    legacy_url: str | None,
    external_id: int,
) -> str | None:
    """Copy `legacy_url` into SLAB storage. Returns the public URL of
    the stored file, OR falls back to `legacy_url` itself on failure,
    OR None when there's no URL to begin with.

    The destination path is deterministic so re-runs overwrite the
    same key — idempotent under repeated migrations."""
    if not legacy_url:
        return None
    legacy_url = legacy_url.strip()
    if not legacy_url:
        return None

    data = fetch_bytes(legacy_url)
    if data is None:
        # Couldn't fetch; keep the URL so the player still has a photo.
        return legacy_url

    storage_key = f"players/{external_id}.jpg"
    # Overwrite if exists — true idempotency.
    if default_storage.exists(storage_key):
        default_storage.delete(storage_key)
    default_storage.save(storage_key, ContentFile(data))
    return default_storage.url(storage_key)
