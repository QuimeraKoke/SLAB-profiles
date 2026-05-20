"""Data-table companions for chart widgets in the per-player PDF.

The web shows charts that the user can hover/inspect; the PDF can't.
Per client feedback we render chart + data side-by-side, so the
reader can both see the trend AND verify the exact numbers without
hunting through a separate page.

Public API: `build_data_table(widget, payload, *, max_width_cm)` returns
a reportlab Flowable (Table) or None when the widget type doesn't
have a data twin (e.g. it's already a table itself).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from .scaffold import COLOR_MUTED, COLOR_PRIMARY, COLOR_RULE, styles, wrap_header_cells


# Chart types whose data this module knows how to tabulate. Other
# chart types (tables, activity logs, etc.) already display the
# numbers — they get None back and the orchestrator falls through to
# the single-cell rendering path.
CHART_TYPES_WITH_DATA_TABLE = {
    "donut_per_result",
    "multi_line",
    "line_with_selector",
}


def build_data_table(widget, payload: dict[str, Any], *, max_width_cm: float):
    """Return a reportlab Flowable showing the chart data as a table,
    or None when the widget type doesn't support it / has no data."""
    if not payload or payload.get("empty"):
        return None
    chart_type = widget.chart_type
    if chart_type == "donut_per_result":
        return _donut_table(payload, max_width_cm)
    if chart_type == "multi_line":
        return _multi_line_table(payload, max_width_cm)
    if chart_type == "line_with_selector":
        return _line_with_selector_table(payload, max_width_cm)
    return None


def expected_column_count(widget, payload: dict[str, Any]) -> int | None:
    """How many columns the data table would have if `build_data_table`
    were called on this widget/payload. The orchestrator uses this to
    decide between side-by-side (chart + table) and stacked (chart on
    top, full-width table below) layouts WITHOUT actually building the
    table — building it twice would be wasteful. Returns None when the
    widget type has no data twin."""
    ct = widget.chart_type
    if ct == "donut_per_result":
        # Always Categoría / Valor / %.
        return 3
    if ct == "multi_line":
        # Fecha + one column per series.
        return 1 + len(payload.get("series") or [])
    if ct == "line_with_selector":
        # Fecha + one column per available_field.
        return 1 + len(payload.get("available_fields") or [])
    return None


# --- Per-type builders ----------------------------------------------------


def _donut_table(payload: dict, max_width_cm: float):
    """Donut data: rows = slice labels, cols = (Categoría, Valor, %).
    When the resolver returns multiple donuts, take the most recent."""
    donuts = payload.get("donuts") or []
    if not donuts:
        return None
    latest = max(donuts, key=lambda d: d.get("recorded_at") or "")
    slices = latest.get("slices") or []
    if not slices:
        return None

    total = sum(_to_float(s.get("value")) or 0 for s in slices)
    rows: list[list] = [wrap_header_cells(["Categoría", "Valor", "%"], font_size=7.5)]
    for s in slices:
        v = _to_float(s.get("value"))
        pct = (v / total * 100.0) if (v is not None and total > 0) else None
        rows.append([
            s.get("label") or s.get("key", ""),
            _fmt_num(v),
            f"{pct:.1f}%" if pct is not None else "—",
        ])

    label_w = max_width_cm * 0.50 * cm
    value_w = max_width_cm * 0.27 * cm
    pct_w = max_width_cm * 0.23 * cm
    tbl = Table(rows, colWidths=[label_w, value_w, pct_w], hAlign="LEFT")
    tbl.setStyle(_base_table_style(numeric_cols_from=1))
    return _with_caption(_fmt_date(latest.get("recorded_at")), tbl)


def _multi_line_table(payload: dict, max_width_cm: float):
    """Multi-line data: rows = timestamps, cols = (Fecha, *series)."""
    series_list = payload.get("series") or []
    if not series_list:
        return None
    all_ts = sorted({
        p.get("recorded_at")
        for s in series_list
        for p in (s.get("points") or [])
        if p.get("recorded_at")
    })
    if not all_ts:
        return None

    # Limit to the most recent N readings — a year of weekly readings
    # would overflow the cell. The chart still shows the full series.
    all_ts = all_ts[-_max_rows_for(max_width_cm):]

    header_labels = ["Fecha"] + [
        (s.get("label") or s.get("key", "")) for s in series_list
    ]
    rows: list[list] = [wrap_header_cells(header_labels, font_size=7.5)]
    by_ts = {ts: {} for ts in all_ts}
    for s in series_list:
        sk = s.get("key")
        for p in s.get("points") or []:
            ts = p.get("recorded_at")
            if ts in by_ts:
                by_ts[ts][sk] = _to_float(p.get("value"))

    for ts in all_ts:
        unit_per_series = {s.get("key"): s.get("unit") or "" for s in series_list}
        line: list = [_fmt_date(ts, short=True)]
        for s in series_list:
            v = by_ts[ts].get(s.get("key"))
            line.append(_fmt_num(v, unit=unit_per_series.get(s.get("key"))))
        rows.append(line)

    return _build_dated_table(rows, max_width_cm, n_value_cols=len(series_list))


def _line_with_selector_table(payload: dict, max_width_cm: float):
    """Line-with-selector data. The resolver returns `series` as a dict
    mapping field_key → list-of-points (NOT a wrapper dict — be careful
    here, this was a previous bug)."""
    available = payload.get("available_fields") or []
    series_map = payload.get("series") or {}
    if not available or not series_map:
        return None

    all_ts = sorted({
        p.get("recorded_at")
        for points in series_map.values()
        for p in (points if isinstance(points, list) else [])
        if isinstance(p, dict) and p.get("recorded_at")
    })
    if not all_ts:
        return None
    all_ts = all_ts[-_max_rows_for(max_width_cm):]

    header_labels = ["Fecha"] + [
        (f.get("label") or f.get("key", "")) for f in available
    ]
    rows: list[list] = [wrap_header_cells(header_labels, font_size=7.5)]
    for ts in all_ts:
        line: list = [_fmt_date(ts, short=True)]
        for f in available:
            fk = f["key"]
            points = series_map.get(fk) or []
            v = None
            for p in points:
                if isinstance(p, dict) and p.get("recorded_at") == ts:
                    v = _to_float(p.get("value"))
                    break
            line.append(_fmt_num(v, unit=f.get("unit") or ""))
        rows.append(line)

    return _build_dated_table(rows, max_width_cm, n_value_cols=len(available))


# --- Shared bits ----------------------------------------------------------


def _build_dated_table(rows: list[list], max_width_cm: float, *, n_value_cols: int):
    date_w = min(2.0, max_width_cm * 0.22) * cm
    value_w = max(1.0 * cm, (max_width_cm * cm - date_w) / max(1, n_value_cols))
    tbl = Table(rows, colWidths=[date_w] + [value_w] * n_value_cols, hAlign="LEFT")
    tbl.setStyle(_base_table_style(numeric_cols_from=1))
    return tbl


def _base_table_style(*, numeric_cols_from: int) -> TableStyle:
    # Header cells are Paragraphs (so they word-wrap), so font/color
    # styling on row 0 is handled by the Paragraph itself — only the
    # background, padding, and value-row styling lives here.
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("TEXTCOLOR", (0, 1), (0, -1), COLOR_MUTED),
        ("TEXTCOLOR", (1, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (numeric_cols_from, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        # Header row gets a little extra padding so wrapped two-line
        # labels don't crowd the value row below.
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])


def _with_caption(caption: str, tbl) -> list:
    """Return a list of flowables: a small italic date caption above
    the table so the donut's "as-of" date is preserved next to the
    numbers it summarizes."""
    body = styles()
    return [
        Paragraph(f"<i>{caption}</i>", body["body_muted"]),
        Spacer(1, 1 * mm),
        tbl,
    ]


# --- Formatting helpers ---------------------------------------------------


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(value: float | None, *, unit: str = "") -> str:
    if value is None:
        return "—"
    if value == int(value):
        return f"{int(value)}{(' ' + unit) if unit else ''}"
    return f"{value:.2f}{(' ' + unit) if unit else ''}"


def _fmt_date(value, *, short: bool = False) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%d/%m" if short else "%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)[:10]


def _max_rows_for(width_cm: float) -> int:
    """Heuristic row cap so the table doesn't overflow the page next
    to a fixed-height chart."""
    return 12 if width_cm < 8 else 18
