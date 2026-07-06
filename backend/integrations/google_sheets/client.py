"""Fetch rows from a Google Sheet worksheet as a list of header→value dicts.

Credentials come from EITHER a file path (local/Docker: a mounted key) OR an
env-var JSON blob (Railway/Heroku/etc., where there's no file to mount). The
env blob may be raw service-account JSON or base64-encoded JSON (base64 is the
safe single-line form for platform variable editors).

The Sheets API returns every cell as a **string** (numbers like "6", dates
like "16/4/2026 8:28:48") — callers coerce. We keep the client dumb: auth +
read + return rows.
"""
from __future__ import annotations

from typing import Any

from .exceptions import GoogleSheetsError

# Read-only is the least privilege the ingest needs.
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _parse_creds_json(raw: str) -> dict:
    import base64
    import binascii
    import json

    raw = raw.strip()
    # Prefer base64 (collapse any wrapping whitespace first); fall back to raw JSON.
    compact = "".join(raw.split())
    try:
        decoded = base64.b64decode(compact, validate=True).decode("utf-8")
        return json.loads(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        pass
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise GoogleSheetsError(f"GOOGLE_SHEETS_CREDENTIALS_JSON inválido: {exc}")


def _load_credentials(creds_file: str, creds_json: str):
    from google.oauth2.service_account import Credentials

    if creds_json:
        return Credentials.from_service_account_info(
            _parse_creds_json(creds_json), scopes=_SCOPES,
        )
    if creds_file:
        return Credentials.from_service_account_file(creds_file, scopes=_SCOPES)
    raise GoogleSheetsError("No hay credenciales (ni archivo ni JSON en variable).")


def fetch_rows(
    sheet_id: str,
    worksheet: str,
    *,
    creds_file: str = "",
    creds_json: str = "",
) -> list[dict[str, str]]:
    """Return non-blank rows of `worksheet` as header→value dicts.

    Pass `creds_json` (env blob, raw or base64) on platforms without a file
    mount, or `creds_file` (path) locally. Raises GoogleSheetsError on any
    auth/access/parse failure so callers can treat the sync as a no-op.
    """
    if not sheet_id or not (creds_file or creds_json):
        raise GoogleSheetsError("Falta WELLNESS_SHEET_ID o credenciales.")
    try:
        import gspread
    except ImportError as exc:  # pragma: no cover — dependency missing
        raise GoogleSheetsError(f"Dependencia faltante: {exc}")

    try:
        creds = _load_credentials(creds_file, creds_json)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id)
        ws = sheet.worksheet(worksheet)
        values: list[list[Any]] = ws.get_all_values()
    except FileNotFoundError as exc:
        raise GoogleSheetsError(f"No se encontró el archivo de credenciales: {exc}")
    except GoogleSheetsError:
        raise
    except Exception as exc:  # gspread / google-auth raise many types
        raise GoogleSheetsError(f"No se pudo leer la hoja '{worksheet}': {exc}")

    if not values:
        return []
    headers = [str(h).strip() for h in values[0]]
    rows: list[dict[str, str]] = []
    for raw in values[1:]:
        if not any(str(c).strip() for c in raw):
            continue
        rows.append({h: (str(v).strip() if v is not None else "")
                     for h, v in zip(headers, raw) if h})
    return rows
