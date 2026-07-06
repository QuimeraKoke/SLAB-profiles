"""Read-only Google Sheets access for SLAB ingests (wellness Check-IN form).

Thin wrapper over gspread + a service-account credential. Mirrors the
`integrations/api_football` package shape (client + exceptions).
"""

from .client import fetch_rows
from .exceptions import GoogleSheetsError

__all__ = ["fetch_rows", "GoogleSheetsError"]
