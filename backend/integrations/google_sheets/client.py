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

from datetime import date as _date, timedelta as _timedelta
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


def _client(creds_file: str, creds_json: str):
    try:
        import gspread
    except ImportError as exc:  # pragma: no cover — dependency missing
        raise GoogleSheetsError(f"Dependencia faltante: {exc}")
    return gspread.authorize(_load_credentials(creds_file, creds_json))


class Documento:
    """One open spreadsheet, reused across worksheet reads.

    `open_by_key` costs an API request of its own (it fetches the document
    metadata), so opening per worksheet doubles the request count and burns the
    quota: reading the club's two documents that way tripped Sheets'
    "Read requests per minute per user" (60) less than a minute in. One handle
    per sync is ~17 requests instead of ~34.
    """

    def __init__(self, sheet_id: str, *, creds_file: str = "",
                 creds_json: str = ""):
        if not sheet_id or not (creds_file or creds_json):
            raise GoogleSheetsError("Falta el id de la hoja o las credenciales.")
        try:
            self._sheet = _client(creds_file, creds_json).open_by_key(sheet_id)
        except GoogleSheetsError:
            raise
        except Exception as exc:
            raise GoogleSheetsError(f"No se pudo abrir el documento: {exc}")

    def titulo(self) -> str:
        """The document's own name.

        The Formativo's eight wellness documents carry the category in their
        title (`… CAT 15`, `… SUB 21`) and nowhere else — the rows themselves
        only have a player name. Reading it from the metadata already fetched by
        `open_by_key` costs no extra request.
        """
        try:
            return self._sheet.title
        except Exception as exc:
            raise GoogleSheetsError(f"No se pudo leer el título: {exc}")

    def worksheets(self) -> list[str]:
        try:
            return [w.title for w in self._sheet.worksheets()]
        except Exception as exc:
            raise GoogleSheetsError(f"No se pudieron listar las hojas: {exc}")

    def values(self, worksheet: str) -> list[list[Any]]:
        """Raw grid, unformatted. See `fetch_values` for why unformatted."""
        try:
            ws = self._sheet.worksheet(worksheet)
            return ws.get_values(value_render_option="UNFORMATTED_VALUE")
        except Exception as exc:
            raise GoogleSheetsError(f"No se pudo leer la hoja '{worksheet}': {exc}")


def list_worksheets(
    sheet_id: str, *, creds_file: str = "", creds_json: str = "",
) -> list[str]:
    """Worksheet titles, in tab order.

    The Formativo importers pick sheets by name, and the names in the live
    document are NOT the ones in an .xlsx export of it: Excel truncates a tab
    title to 31 characters, so `FORMATO CONDICIONAL 15-16 y 18-20` arrives as
    `FORMATO CONDICIONAL 15-16 y 18-`. Callers match on a prefix.
    """
    if not sheet_id or not (creds_file or creds_json):
        raise GoogleSheetsError("Falta el id de la hoja o las credenciales.")
    try:
        sheet = _client(creds_file, creds_json).open_by_key(sheet_id)
        return [w.title for w in sheet.worksheets()]
    except GoogleSheetsError:
        raise
    except Exception as exc:
        raise GoogleSheetsError(f"No se pudieron listar las hojas: {exc}")


def fetch_values(
    sheet_id: str, worksheet: str, *,
    creds_file: str = "", creds_json: str = "",
) -> list[list[Any]]:
    """Raw cell grid — positional, unformatted, header row included.

    Two differences from `fetch_rows`, both required by the Formativo parsers:

    * **Positional, not header-keyed.** `PRESS DE BANCO` repeats the header
      `20 KG` for its two attempts and declares a phantom leading `FECHA`, so a
      dict keyed by header loses a column and hides the shift.
    * **`UNFORMATTED_VALUE`.** The rendered text is locale-formatted and lossy:
      the same `DT (m)` cell reads `4.159` formatted and `4158.9` raw, because
      the dot is a THOUSANDS separator — reading the formatted value divides
      every distance by a thousand in silence. Dates render as `8/01/2025`,
      which reintroduces the day/month ambiguity that already cost us two
      birth dates; unformatted they are serial numbers, which are exact.
    """
    if not sheet_id or not (creds_file or creds_json):
        raise GoogleSheetsError("Falta el id de la hoja o las credenciales.")
    try:
        sheet = _client(creds_file, creds_json).open_by_key(sheet_id)
        ws = sheet.worksheet(worksheet)
        return ws.get_values(value_render_option="UNFORMATTED_VALUE")
    except GoogleSheetsError:
        raise
    except Exception as exc:
        raise GoogleSheetsError(f"No se pudo leer la hoja '{worksheet}': {exc}")


# Google Sheets shares Excel's serial-date epoch: day 1 is 1900-01-01, with
# the 1900-leap-year bug baked in, which makes 1899-12-30 the effective zero.
SERIAL_EPOCH = _date(1899, 12, 30)


def serial_to_date(value: Any) -> _date | None:
    """Serial number → date. Anything else returns None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Below 1 is not a date; above ~2100 it is a measurement, not a day.
    if not (1 <= float(value) <= 73415):
        return None
    return SERIAL_EPOCH + _timedelta(days=int(float(value)))


def serial_to_datetime(value: Any) -> "datetime | None":
    """Serial number → naive datetime, keeping the time of day.

    `serial_to_date` throws away the fractional part, which in a Google Form
    response sheet is the submission TIME — and the wellness ingest keys its
    idempotency on `(player, recorded_at)`, so collapsing every response of a
    day to midnight would make a player's second check-in of the week look like
    a duplicate of the first.

    Truncated to whole seconds, for the same reason `wellness_ingest` does it:
    the key has to be stable no matter which source produced the row.
    """
    from datetime import datetime as _datetime

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not (1 <= float(value) <= 73415):
        return None
    entero = int(float(value))
    resto = float(value) - entero
    base = _datetime.combine(SERIAL_EPOCH + _timedelta(days=entero),
                             _datetime.min.time())
    return base + _timedelta(seconds=round(resto * 86400))


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
