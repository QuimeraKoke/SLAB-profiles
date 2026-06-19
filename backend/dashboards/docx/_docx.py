"""Shared Word-document helpers for the report builders.

Styling mirrors the PDF "ficha" look (navy headings, red rule, shaded
table headers) but produces an *editable* Word document. The only
chart path is `render_widget()`, which drives the existing PDF chart
renderers under `capture_docx_figures()` and embeds the resulting PNGs,
then renders the widget's data as a native Word table from its payload.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


# ─── Palette (mirrors scaffold.COLOR_FICHA_*) ─────────────────────────
NAVY = RGBColor(0x0A, 0x22, 0x40)
RED = RGBColor(0xC8, 0x10, 0x2E)
INK = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x6B, 0x72, 0x80)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
HEADER_FILL = "0A2240"   # table header row background (navy)
RED_HEX = "C8102E"

# A4 page geometry (cm) and usable content widths after margins.
_MARGIN_CM = 1.8
PORTRAIT_CONTENT_CM = 21.0 - 2 * _MARGIN_CM      # ≈ 17.4
LANDSCAPE_CONTENT_CM = 29.7 - 2 * _MARGIN_CM     # ≈ 26.1


# ─── Document setup ───────────────────────────────────────────────────


def new_document(*, landscape: bool = False) -> Document:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(4)

    section = doc.sections[0]
    section.top_margin = Cm(_MARGIN_CM)
    section.bottom_margin = Cm(_MARGIN_CM)
    section.left_margin = Cm(_MARGIN_CM)
    section.right_margin = Cm(_MARGIN_CM)
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width = Cm(29.7)
        section.page_height = Cm(21.0)
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
    return doc


def content_width_cm(*, landscape: bool = False) -> float:
    return LANDSCAPE_CONTENT_CM if landscape else PORTRAIT_CONTENT_CM


def to_bytes(doc: Document) -> bytes:
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ─── Headings / text ──────────────────────────────────────────────────


def report_header(
    doc: Document,
    *,
    club_name: str = "",
    club_logo: Any = None,
    title: str = "",
    subtitle: str | None = None,
    meta: list[tuple[str, str]] | None = None,
) -> None:
    """Cover-style identity block: optional logo, club name, big navy
    title, muted subtitle, and a small label/value meta grid."""
    if club_logo is not None:
        try:
            doc.add_picture(club_logo, width=Cm(2.6))
        except Exception:  # noqa: BLE001 — a bad logo must never break the report
            pass
    if club_name:
        p = doc.add_paragraph()
        r = p.add_run(club_name.upper())
        r.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = MUTED

    if title:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(title)
        r.bold = True
        r.font.size = Pt(20)
        r.font.color.rgb = NAVY

    if subtitle:
        p = doc.add_paragraph()
        r = p.add_run(subtitle)
        r.font.size = Pt(11)
        r.font.color.rgb = MUTED

    for label, value in meta or []:
        if value in (None, ""):
            continue
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        lab = p.add_run(f"{label}: ")
        lab.font.size = Pt(9)
        lab.font.color.rgb = MUTED
        val = p.add_run(str(value))
        val.bold = True
        val.font.size = Pt(9)
        val.font.color.rgb = INK

    _hr(doc, RED_HEX)


def section_heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run((text or "").upper())
    r.bold = True
    r.font.size = Pt(12)
    r.font.color.rgb = NAVY
    _paragraph_bottom_border(p, RED_HEX, size=8)


def widget_title(doc: Document, title: str, description: str | None = None) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(1)
    r = p.add_run(title or "")
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.color.rgb = NAVY
    if description:
        d = doc.add_paragraph()
        dr = d.add_run(description)
        dr.italic = True
        dr.font.size = Pt(8.5)
        dr.font.color.rgb = MUTED


def body(doc: Document, text: str, *, muted: bool = False) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text or "")
    r.font.size = Pt(10)
    r.font.color.rgb = MUTED if muted else INK
    if muted:
        r.italic = True


def add_narrative(doc: Document, narrative: dict | None) -> None:
    """Render the agent narrative (resumen / hallazgos / objetivos) as
    editable Word text — the client's primary edit surface."""
    if not narrative:
        return
    resumen = (narrative.get("resumen") or "").strip()
    if resumen:
        section_heading(doc, "Resumen")
        body(doc, resumen)

    hallazgos = [h for h in (narrative.get("hallazgos") or []) if h]
    if hallazgos:
        section_heading(doc, "Hallazgos destacados")
        for h in hallazgos:
            doc.add_paragraph(str(h), style="List Bullet")

    objetivos = [o for o in (narrative.get("objetivos") or []) if isinstance(o, dict)]
    if objetivos:
        section_heading(doc, "Objetivos de trabajo")
        for o in objetivos:
            p = doc.add_paragraph(style="List Bullet")
            foco = (o.get("foco") or "").strip()
            estado = (o.get("estado_actual") or "").strip()
            estrategia = (o.get("estrategia") or "").strip()
            if foco:
                r = p.add_run(foco)
                r.bold = True
                r.font.color.rgb = INK
            if estado:
                r = p.add_run(f": {estado}")
                r.font.color.rgb = MUTED
            if estrategia:
                p.add_run("  →  ")
                r = p.add_run(estrategia)
                r.bold = True
                r.font.color.rgb = INK


# ─── Tables ───────────────────────────────────────────────────────────


def add_table(
    doc: Document,
    header: list[str],
    rows: list[list[Any]],
    *,
    width_cm: float,
    numeric_from: int = 1,
) -> None:
    """A bordered Word table with a shaded navy header row. `numeric_from`
    right-aligns columns from that index onward."""
    if not header:
        return
    ncols = len(header)
    table = doc.add_table(rows=1, cols=ncols)
    table.style = "Table Grid"
    table.autofit = False
    table.allow_autofit = False

    hdr = table.rows[0].cells
    for i, label in enumerate(header):
        _fill_cell(
            hdr[i], str(label), bold=True, color=WHITE, fill=HEADER_FILL,
            align=(WD_ALIGN_PARAGRAPH.RIGHT if i >= numeric_from else WD_ALIGN_PARAGRAPH.LEFT),
            size=8.5,
        )
    for r in rows:
        cells = table.add_row().cells
        for i in range(ncols):
            val = r[i] if i < len(r) else ""
            _fill_cell(
                cells[i], "" if val is None else str(val),
                align=(WD_ALIGN_PARAGRAPH.RIGHT if i >= numeric_from else WD_ALIGN_PARAGRAPH.LEFT),
                size=9,
            )

    # Best-effort proportional widths: label column wider than value cols.
    label_w = width_cm * 0.34 if ncols > 1 else width_cm
    rest = (width_cm - label_w) / max(1, ncols - 1) if ncols > 1 else 0
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            cell.width = Cm(label_w if i == 0 else rest)


def add_chart_images(doc: Document, figs: list, *, max_width_cm: float) -> None:
    for png, w_cm, _h_cm in figs:
        try:
            doc.add_picture(BytesIO(png), width=Cm(min(w_cm or max_width_cm, max_width_cm)))
        except Exception:  # noqa: BLE001 — one bad chart shouldn't kill the report
            continue


def render_widget(doc: Document, widget, payload: dict, *, width_cm: float) -> None:
    """Render one widget: title, chart image(s) reused from the PDF chart
    renderers, then a native Word table of its data. Never raises."""
    widget_title(doc, getattr(widget, "title", "") or "", getattr(widget, "description", None))
    if not payload or payload.get("empty"):
        body(doc, "Sin datos en el período seleccionado.", muted=True)
        return

    # Charts: drive the unchanged PDF renderer, harvest its PNGs.
    figs: list = []
    try:
        from dashboards.pdf.charts import render_widget_for_pdf
        from dashboards.pdf.charts._mpl import capture_docx_figures

        with capture_docx_figures() as sink:
            render_widget_for_pdf(widget, payload, max_width_cm=width_cm)
        figs = list(sink)
    except Exception:  # noqa: BLE001
        figs = []
    add_chart_images(doc, figs, max_width_cm=width_cm)

    rendered = _render_payload_table(doc, getattr(widget, "chart_type", ""), payload, width_cm)
    if not figs and not rendered:
        _generic_table(doc, payload, width_cm)


# ─── Payload → table adapters (shapes verified against live resolvers) ──


def _render_payload_table(doc: Document, chart_type: str, payload: dict, width_cm: float) -> bool:
    try:
        builder = _TABLE_BUILDERS.get(chart_type)
        if builder is not None:
            return bool(builder(doc, payload, width_cm))
    except Exception:  # noqa: BLE001 — fall through to generic on any shape surprise
        return False
    return False


def _t_comparison_table(doc, payload, width_cm) -> bool:
    cols = payload.get("columns") or []
    rows = payload.get("rows") or []
    if not cols or not rows:
        return False
    header = ["Métrica"] + [_short_date(c.get("recorded_at")) for c in cols]
    out = []
    for r in rows:
        label = _with_unit(r.get("label") or r.get("key"), r.get("unit"))
        out.append([label] + [_num(v) for v in (r.get("values") or [])])
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_grouped_bar(doc, payload, width_cm) -> bool:
    groups = payload.get("groups") or []
    fields = payload.get("fields") or []
    if not groups or not fields:
        return False
    header = ["Fecha"] + [_with_unit(f.get("label"), f.get("unit")) for f in fields]
    out = []
    for g in groups:
        bars = {b.get("key"): b.get("value") for b in (g.get("bars") or [])}
        out.append([_short_date(g.get("recorded_at"))] + [_num(bars.get(f.get("key"))) for f in fields])
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_donut(doc, payload, width_cm) -> bool:
    donuts = payload.get("donuts") or []
    if not donuts:
        return False
    latest = max(donuts, key=lambda d: d.get("recorded_at") or "")
    slices = latest.get("slices") or []
    if not slices:
        return False
    header = ["Categoría", "Valor", "%"]
    out = [
        [s.get("label") or s.get("key"), _num(s.get("value")),
         (f"{s['percentage']:.1f}%" if s.get("percentage") is not None else "—")]
        for s in slices
    ]
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_multi_line(doc, payload, width_cm) -> bool:
    series = payload.get("series") or []
    if not series:
        return False
    all_ts = sorted({
        p.get("recorded_at")
        for s in series for p in (s.get("points") or []) if p.get("recorded_at")
    })[-18:]
    if not all_ts:
        return False
    by = {s.get("key"): {p.get("recorded_at"): p.get("value") for p in (s.get("points") or [])} for s in series}
    header = ["Fecha"] + [_with_unit(s.get("label") or s.get("key"), s.get("unit")) for s in series]
    out = [[_short_date(ts)] + [_num(by[s.get("key")].get(ts)) for s in series] for ts in all_ts]
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_line_selector(doc, payload, width_cm) -> bool:
    fields = payload.get("available_fields") or []
    series = payload.get("series") or {}
    if not fields or not series:
        return False
    all_ts = sorted({
        p.get("recorded_at")
        for pts in series.values() for p in (pts if isinstance(pts, list) else [])
        if isinstance(p, dict) and p.get("recorded_at")
    })[-18:]
    if not all_ts:
        return False
    header = ["Fecha"] + [_with_unit(f.get("label") or f.get("key"), f.get("unit")) for f in fields]
    out = []
    for ts in all_ts:
        line = [_short_date(ts)]
        for f in fields:
            pts = series.get(f["key"]) or []
            v = next((p.get("value") for p in pts if isinstance(p, dict) and p.get("recorded_at") == ts), None)
            line.append(_num(v))
        out.append(line)
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_roster_matrix(doc, payload, width_cm) -> bool:
    cols = payload.get("columns") or []
    rows = payload.get("rows") or []
    if not cols or not rows:
        return False
    header = ["Jugador"] + [_with_unit(c.get("label"), c.get("unit")) for c in cols]
    out = []
    for r in rows:
        cells = r.get("cells") or {}
        line = [r.get("player_name") or r.get("label") or "—"]
        for c in cols:
            cell = cells.get(c.get("key")) or {}
            line.append(_num(cell.get("value") if isinstance(cell, dict) else cell))
        out.append(line)
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_horizontal_comparison(doc, payload, width_cm) -> bool:
    fields = payload.get("fields") or []
    rows = payload.get("rows") or []
    if not fields or not rows:
        return False
    header = ["Jugador"] + [_with_unit(f.get("label"), f.get("unit")) for f in fields]
    out = []
    for r in rows:
        values = r.get("values") or {}
        line = [r.get("player_name") or "—"]
        for f in fields:
            readings = values.get(f.get("key")) or []
            v = _latest_reading(readings)
            line.append(_num(v))
        out.append(line)
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_stacked_bars(doc, payload, width_cm) -> bool:
    fields = payload.get("fields") or []
    rows = payload.get("rows") or []
    if not fields or not rows:
        return False
    header = ["Jugador"] + [_with_unit(f.get("label"), f.get("unit")) for f in fields] + ["Total"]
    out = []
    for r in rows:
        values = r.get("values") or {}
        line = [r.get("player_name") or "—"]
        line += [_num(values.get(f.get("key"))) for f in fields]
        line.append(_num(r.get("total")))
        out.append(line)
    add_table(doc, header, out, width_cm=width_cm)
    return True


def _t_leaderboard(doc, payload, width_cm) -> bool:
    rows = payload.get("rows") or []
    if not rows:
        return False
    field = payload.get("field") or {}
    header = ["#", "Jugador", field.get("label") or "Valor", "Prom.", "Máx."]
    out = []
    for r in rows:
        agg = r.get("aggregates") or {}
        out.append([
            r.get("rank"), r.get("player_name") or "—",
            _num(r.get("value")), _num(agg.get("avg")), _num(agg.get("max")),
        ])
    add_table(doc, header, out, width_cm=width_cm, numeric_from=2)
    return True


def _t_match_summary(doc, payload, width_cm) -> bool:
    cards = payload.get("cards") or []
    if not cards:
        return False
    header = ["Métrica", "Prom.", "Total", "Mín.", "Máx.", "n"]
    out = [
        [_with_unit(c.get("label"), c.get("unit")), _num(c.get("avg")), _num(c.get("sum")),
         _num(c.get("min")), _num(c.get("max")), c.get("n")]
        for c in cards
    ]
    add_table(doc, header, out, width_cm=width_cm)
    return True


_TABLE_BUILDERS = {
    "comparison_table": _t_comparison_table,
    "grouped_bar": _t_grouped_bar,
    "donut_per_result": _t_donut,
    "multi_line": _t_multi_line,
    "line_with_selector": _t_line_selector,
    "team_roster_matrix": _t_roster_matrix,
    "team_horizontal_comparison": _t_horizontal_comparison,
    "team_stacked_bars": _t_stacked_bars,
    "team_leaderboard": _t_leaderboard,
    "team_match_summary": _t_match_summary,
}


def _generic_table(doc: Document, payload: dict, width_cm: float) -> None:
    """Fallback for chart types without a dedicated adapter: render the
    first list-of-dicts found as a table (union of scalar columns), or a
    key/value dump of the payload's scalars. Always emits SOMETHING."""
    list_key = next(
        (k for k in ("rows", "players", "entries", "items", "bins", "counts", "groups", "data")
         if isinstance(payload.get(k), list) and payload.get(k)
         and isinstance(payload[k][0], dict)),
        None,
    )
    if list_key:
        items = payload[list_key][:60]
        skip = {"player_id", "result_id", "department_id", "id", "color", "cells", "values",
                "aggregates", "dates", "points", "reference_ranges", "bars", "slices"}
        cols: list[str] = []
        for it in items:
            for k, v in it.items():
                if k in skip or k in cols:
                    continue
                if isinstance(v, (str, int, float, bool)) or v is None:
                    cols.append(k)
        cols = cols[:6]
        if cols:
            header = [_prettify(c) for c in cols]
            out = [[_scalar(it.get(c)) for c in cols] for it in items]
            add_table(doc, header, out, width_cm=width_cm, numeric_from=1)
            return

    pairs = [(k, v) for k, v in payload.items()
             if k not in {"chart_type", "empty", "title", "description", "error"}
             and isinstance(v, (str, int, float, bool))]
    if pairs:
        add_table(doc, ["Campo", "Valor"], [[_prettify(k), _scalar(v)] for k, v in pairs], width_cm=width_cm)
    else:
        body(doc, "Datos no tabulables para este widget.", muted=True)


# ─── Low-level XML / formatting helpers ───────────────────────────────


def _fill_cell(cell, text, *, bold=False, color=None, fill=None, align=None, size=9.0):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    if align is not None:
        p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    if fill is not None:
        _set_cell_shading(cell, fill)


def _set_cell_shading(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _paragraph_bottom_border(paragraph, hex_color: str, *, size: int = 6) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), hex_color)
    pbdr.append(bottom)
    pPr.append(pbdr)


def _hr(doc: Document, hex_color: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    _paragraph_bottom_border(p, hex_color, size=12)


def _num(v) -> str:
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".")


def _scalar(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, float):
        return _num(v)
    return str(v)


def _with_unit(label, unit) -> str:
    label = str(label or "")
    return f"{label} ({unit})" if unit else label


def _latest_reading(readings: list):
    """Most-recent value from a [{value,label,iso}] reading list."""
    if not isinstance(readings, list) or not readings:
        return None
    try:
        best = max(readings, key=lambda r: r.get("iso") or "")
    except Exception:  # noqa: BLE001
        best = readings[-1]
    return best.get("value") if isinstance(best, dict) else best


def _short_date(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d/%m/%y")
    except (ValueError, TypeError):
        return str(value)[:10]


def _prettify(key: str) -> str:
    return str(key).replace("_", " ").capitalize()
