"""Pure parsing helpers for the per-session GPS export.

Django-free on purpose: the management command (`import_gps_sessions`) does
the DB work (player resolution, Event + ExamResult creation), but everything
that turns a spreadsheet into clean per-(player, session) records lives here so
it can be unit-tested and dry-run without a database.

The export is the provider's *per-session aggregate*: one row per player per
session (matches, trainings, rehab). Two shapes seen in the wild:

  * Match export — has a `Days` column with a Java `Date.toString()` timestamp
    (`"Mon Mar 09 23:01:33 UTC 2026"`); every session is a match.
  * Training export — no `Days` column; the date is embedded in the session
    label (`"Sesión 04-01-26"`, `"Reintegro 11-02"`, day-month[-year]).

Files arrive named `*.xls` but are actually OOXML; we read them through
`io.BytesIO` so openpyxl's filename-extension guard doesn't reject them.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException


PLAYER_COL = "Players"
SESSION_COL = "Sessions"
DAYS_COL = "Days"

# Export header (after .strip()) -> per-session template field key.
# Keep in sync with seed_gps_session.py:CONFIG_SCHEMA field keys.
HEADER_TO_KEY: dict[str, str] = {
    "Tiempo (min)": "tot_dur",
    "Distance (m)": "tot_dist",
    "m/min": "mpm",
    "Distancia HSR > 19,8 km/h": "hsr",
    "Distancia Sprint > 25 km/h": "sprint_dist",
    "Sprints(#)": "sprints",
    "Max Speed (km/h)": "max_vel",
    "Acc&Dec +3": "acc_dec",
    "Acc > +3 m/s2": "acc",
    "Dec > -3 m/s2": "dec",
    "Distancia Acc (m)": "dist_acc",
    "Distancia Dec (m)": "dist_dec",
    "HMLD (m)": "hmld",
    "Speed Zones (m) [75.0, 85.0]": "zone_75_85",
    "Speed Zones (m) [85.0, 95.0]": "zone_85_95",
    "Speed Zones (m) [95.0, 100.0]": "zone_95_100",
}

DEFAULT_YEAR = 2026

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# day-month[-year] anywhere in a session label, e.g. "04-01-26", "11-02".
_DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})(?:-(\d{2,4}))?")
# split on a standalone "vs" (Spanish match labels: "F8 vs La Serena").
_VS_RE = re.compile(r"\bvs\.?\b", re.IGNORECASE)


class GpsParseError(ValueError):
    """Raised when the file can't be read or has no usable columns."""


@dataclass
class GpsRow:
    player_label: str
    session: str
    days_raw: Optional[str]
    metrics: dict[str, Any] = field(default_factory=dict)


def normalize(text: str) -> str:
    """Lowercase + strip diacritics — tolerant comparison (matches bulk_ingest)."""
    decomposed = unicodedata.normalize("NFD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def parse_workbook(file_bytes: bytes) -> tuple[bool, list[GpsRow]]:
    """Parse the export bytes. Returns (has_days_column, rows).

    Reads through BytesIO so a `.xls`-named OOXML file is accepted.
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except (InvalidFileException, OSError, KeyError, ValueError) as exc:
        raise GpsParseError(f"No se pudo leer el archivo: {exc}")

    sheet = wb.active
    if sheet is None:
        raise GpsParseError("El archivo no tiene hojas legibles.")

    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        raise GpsParseError("El archivo está vacío.")

    headers = [str(c).strip() if c is not None else "" for c in header_row]
    if PLAYER_COL not in headers or SESSION_COL not in headers:
        raise GpsParseError(
            f"Faltan columnas obligatorias '{PLAYER_COL}' / '{SESSION_COL}'. "
            f"Encabezados encontrados: {headers}"
        )
    has_days = DAYS_COL in headers
    col = {h: i for i, h in enumerate(headers)}

    def cell(raw, name):
        i = col.get(name)
        return raw[i] if (i is not None and i < len(raw)) else None

    rows: list[GpsRow] = []
    for raw in rows_iter:
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in raw):
            continue
        player = cell(raw, PLAYER_COL)
        if player is None or not str(player).strip():
            continue
        metrics = {
            h: cell(raw, h)
            for h in HEADER_TO_KEY
            if h in col
        }
        days = cell(raw, DAYS_COL) if has_days else None
        rows.append(GpsRow(
            player_label=str(player).strip(),
            session=str(cell(raw, SESSION_COL) or "").strip(),
            days_raw=str(days).strip() if days is not None else None,
            metrics=metrics,
        ))
    return has_days, rows


def parse_days(value: Any) -> Optional[date]:
    """Parse a Java `Date.toString()` value -> date, locale-independently.

    e.g. "Mon Mar 09 23:01:33 UTC 2026" -> date(2026, 3, 9).
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value
    parts = str(value).split()
    if len(parts) < 6:
        return None
    try:
        month = _MONTHS.get(parts[1][:3].lower())
        day = int(parts[2])
        year = int(parts[-1])
        if month is None:
            return None
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def extract_session_date(label: str, default_year: int = DEFAULT_YEAR) -> Optional[date]:
    """Pull a day-month[-year] date out of a session label, or None.

    A missing year defaults to `default_year`; a 2-digit year is read as 20xx.
    Returns None when no parseable date is present (undated session).
    """
    m = _DATE_RE.search(label or "")
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    if year is None:
        y = default_year
    else:
        y = int(year)
        if y < 100:
            y += 2000
    try:
        return date(y, month, day)
    except ValueError:
        return None


def resolve_date(row: GpsRow, default_year: int = DEFAULT_YEAR) -> Optional[date]:
    """Date for a row: the `Days` timestamp when present, else from the label."""
    if row.days_raw:
        d = parse_days(row.days_raw)
        if d is not None:
            return d
    return extract_session_date(row.session, default_year=default_year)


def classify_session(label: str, *, is_match_file: bool) -> str:
    """Derive the `tipo_sesion` categorical value from the session label."""
    if is_match_file:
        return "partido"
    n = normalize(label)
    if "reintegro" in n:
        return "reintegro"
    if "amistoso" in n:
        return "amistoso"
    if "tarea" in n:
        return "tareas"
    if "sub 20" in n or "sub20" in n or "juvenil" in n:
        return "otro"
    if "sesion" in n:
        return "entrenamiento"
    return "otro"


def parse_match_parts(label: str) -> tuple[Optional[str], Optional[str]]:
    """Split a match label into (competition, opponent).

    "C.Liga F2 vs ULC" -> ("C.Liga F2", "ULC"); "F8 vs La Serena" ->
    ("F8", "La Serena"). Returns (None, None) when there's no "vs".
    """
    if not label or not _VS_RE.search(label):
        return None, None
    parts = _VS_RE.split(label, maxsplit=1)
    left, right = parts[0], parts[-1]
    competition = _DATE_RE.sub("", left).strip() or None
    opponent = right.strip() or None
    return competition, opponent


def build_result_data(row: GpsRow) -> dict[str, Any]:
    """Map export headers -> template keys, coercing numerics, dropping blanks."""
    data: dict[str, Any] = {}
    for header, key in HEADER_TO_KEY.items():
        value = row.metrics.get(header)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            data[key] = float(value)
        else:
            try:
                data[key] = float(str(value).replace(",", "."))
            except ValueError:
                data[key] = value
    return data
