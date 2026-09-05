"""Read-only Google Sheets access for SLAB ingests.

Two shapes, because two callers need different things:

* `fetch_rows` — header→value dicts of rendered text. What the wellness form
  ingest wants: a flat response table with unique headers.
* `fetch_values` + `list_worksheets` + `serial_to_date` — the raw cell grid,
  unformatted. What the Formativo importers need, because their sheets repeat
  headers, hide a column shift, and carry numbers whose rendered form is lossy.

Thin wrapper over gspread + a service-account credential. Mirrors the
`integrations/api_football` package shape (client + exceptions).
"""

from .client import (Documento, fetch_rows, fetch_values, list_worksheets,
                     serial_to_date, serial_to_datetime, SERIAL_EPOCH)
from .exceptions import GoogleSheetsError

__all__ = [
    "Documento", "fetch_rows", "fetch_values", "list_worksheets",
    "serial_to_date", "serial_to_datetime", "SERIAL_EPOCH", "GoogleSheetsError",
]
