"""Per-player department report PDF.

Walks the DepartmentLayout for the player's department + category and
renders each widget with its per-player resolver. Portrait A4.

P5 fully wires the widget renderers; for now ships the cover + exec
summary + a skeleton list of section titles so a download already
returns a real-looking PDF.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import cm, mm

from core.models import Department, Player
from dashboards.models import DepartmentLayout
from dashboards.aggregation import resolve_widget
from dashboards.references import build_metric_references
from exams.models import ExamResult, ExamTemplate

from .charts import render_widget_for_pdf
from .chart_data_tables import (
    CHART_TYPES_WITH_DATA_TABLE,
    build_data_table,
    expected_column_count,
)
from .injury_summary import player_injury_summary
from .narrative import generate_player_narrative, resolve_insight_agent
from .report_cache import get_saved_file, report_signature, save_file
from .scaffold import (
    build_pdf,
    logo_image_for_club,
    styles,
)


# Portrait A4 content frame width (after page margins in scaffold.py).
_PORTRAIT_CONTENT_WIDTH_CM = 17.5
_CELL_HORIZONTAL_PADDING_CM = 0.4

# Bump when the department report's rendered layout changes, to supersede
# previously saved snapshots without a data change.
_DEPT_RENDER_VERSION = 1

# Display timezone for cover-page "Generado" timestamp.
# Mirrors team_report._DISPLAY_TZ.
_DISPLAY_TZ = ZoneInfo("America/Santiago")

# Per-player chart types that produce tall, page-spanning tables.
# These skip the title+content `KeepTogether` wrap so reportlab can
# start filling the current page instead of jumping to a fresh one.
# (Multi-column packing was also dropped on the player report — every
# widget renders at full portrait width, see `_pack_widgets_into_rows`.)
_SPLITTABLE_CHART_TYPES = {
    "activity_log",
    "comparison_table",
    "grouped_bar",      # takes × fields table, may span pages
    "body_map_heatmap", # region × count table
}


def render_or_get_player_pdf(
    *,
    player: Player,
    department: Department,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> bytes:
    """Download entry point for the per-department report. Resolves the
    department's InsightAgent, builds the department data payload, and
    returns the saved PDF for that data+agent signature if one exists —
    otherwise generates the narrative once, renders, persists, and returns.
    Mirrors the Resumen's `render_or_get_triage_pdf`."""
    from django.conf import settings

    agent = resolve_insight_agent(department.slug)
    model = (
        (agent.model or "").strip() if agent else ""
    ) or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-8")
    fingerprint = agent.config_fingerprint() if agent else "builtin"

    payload = build_department_payload(player, department, date_from, date_to)
    kind = f"dept:{department.slug}"
    signature = report_signature(
        payload, model=model, kind=kind,
        render_version=_DEPT_RENDER_VERSION, agent_fingerprint=fingerprint,
    )

    saved = get_saved_file(player, kind, signature, fmt="pdf")
    if saved is not None:
        return saved

    narrative = generate_player_narrative(payload, agent=agent)
    pdf_bytes = render_player_pdf(
        player=player, department=department,
        date_from=date_from, date_to=date_to, narrative=narrative,
        weekly_evolution=payload.get("weekly_load_evolution"),
    )
    try:
        save_file(player, kind, signature, pdf_bytes, fmt="pdf", model=model, narrative=narrative)
    except Exception:  # noqa: BLE001 — persistence is best-effort, never block the download
        import logging
        logging.getLogger(__name__).exception("Failed to persist department report snapshot.")
    return pdf_bytes


def build_department_payload(
    player: Player,
    department: Department,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """Agent-facing summary of the department's data: each configured
    widget's resolved payload (the same data the report renders), so the
    narrative is grounded in exactly what's shown. Empty widgets are
    dropped. No volatile fields — the signature is stable for unchanged
    data (period is reflected in the resolved values themselves)."""
    category = player.category
    layout = (
        DepartmentLayout.objects
        .filter(department=department, category=category, is_active=True)
        .prefetch_related("sections__widgets__data_sources")
        .first()
    )
    items: list[dict[str, Any]] = []
    if layout is not None:
        for section in layout.sections.all():
            for w in section.widgets.all():
                payload = resolve_widget(
                    w, player.id, date_from=date_from, date_to=date_to,
                )
                if payload.get("empty"):
                    continue
                items.append({
                    "title": w.title,
                    "chart_type": w.chart_type,
                    "data": payload,
                })
    payload = {
        "department": department.name,
        "category": category.name if category else None,
        "items": items,
        # Source-labeled references per metric (internal bands + external
        # norms + squad percentile) so the agent compares against trustworthy,
        # computed numbers rather than guessing.
        "references": _department_metric_references(player, department, category),
    }

    # Físico: surface the weekly chronic-load monitor (current) + its
    # evolution across state snapshots, from the player's materialized state.
    if department.slug == "fisico":
        from dashboards.models import PlayerMetricState
        from dashboards.player_state import weekly_load_evolution
        st = PlayerMetricState.objects.filter(player=player).only("state").first()
        weekly = (st.state or {}).get("weekly_load") if st else None
        if weekly:
            payload["weekly_load"] = weekly
        evo = weekly_load_evolution(player)
        if evo:
            payload["weekly_load_evolution"] = evo

    return payload


def _department_metric_references(player: Player, department: Department, category) -> list[dict]:
    """For each banded field of the department's templates, the player's
    latest value plus its reference block (internal band + external norms +
    squad percentile). Only fields with `reference_ranges` are included, to
    keep this focused and bound the per-field squad query."""
    if category is None:
        return []
    sex = player.sex or None
    position = player.position.name if player.position else None
    out: list[dict] = []
    templates = list(
        ExamTemplate.objects
        .filter(department=department, applicable_categories=category, is_active_version=True)
        .distinct()
    )
    # Fields with an external MetricReference but no internal band must still
    # surface (e.g. per-match GPS fields with Premier League norms).
    from dashboards.models import MetricReference
    ext_keys = set(
        MetricReference.objects
        .filter(template__in=templates, is_active=True)
        .values_list("template_id", "field_key")
    )
    for t in templates:
        fields = (t.config_schema or {}).get("fields") or []
        specs = {
            f["key"]: f for f in fields
            if isinstance(f, dict) and f.get("key")
            and (f.get("reference_ranges") or (t.id, f["key"]) in ext_keys)
        }
        if not specs:
            continue
        results = list(
            ExamResult.objects.filter(player=player, template=t).order_by("-recorded_at")
        )
        for field_key, spec in specs.items():
            latest = _latest_value(results, field_key)
            if latest is None:
                continue
            block = build_metric_references(
                t, field_key, spec, latest,
                sex=sex, position=position, category=category,
            )
            if block:
                out.append({
                    "template": t.name,
                    "field": spec.get("label") or field_key,
                    "value": latest,
                    "unit": spec.get("unit"),
                    "references": block,
                })
    return out


def _latest_value(results: list, field_key: str) -> float | None:
    for r in results:
        raw = (r.result_data or {}).get(field_key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _analysis_section(narrative: dict, body_styles) -> list:
    """Render the agent narrative (resumen / hallazgos / objetivos) as a
    section block, using the report's scaffold body styles."""
    out: list = []
    resumen = (narrative.get("resumen") or "").strip()
    if resumen:
        out.append(Paragraph(_esc(resumen), body_styles["body"]))

    hallazgos = narrative.get("hallazgos") or []
    if hallazgos:
        out.append(Spacer(1, 3 * mm))
        out.append(Paragraph("<b>Hallazgos destacados</b>", body_styles["body"]))
        for h in hallazgos:
            out.append(Paragraph(f"•  {_esc(str(h))}", body_styles["body"]))

    objetivos = narrative.get("objetivos") or []
    if objetivos:
        out.append(Spacer(1, 3 * mm))
        out.append(Paragraph("<b>Objetivos de trabajo</b>", body_styles["body"]))
        for o in objetivos:
            if not isinstance(o, dict):
                continue
            foco = _esc(str(o.get("foco") or ""))
            estado = _esc(str(o.get("estado_actual") or ""))
            estrategia = _esc(str(o.get("estrategia") or ""))
            line = f"<b>{foco}</b>" if foco else ""
            if estado:
                line += f": <font color='#6b7280'>{estado}</font>"
            if estrategia:
                line += f" → <b>{estrategia}</b>"
            if line:
                out.append(Paragraph(line, body_styles["body"]))
    return out


def _esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _weekly_load_evolution_section(evolution: list, body_styles) -> list:
    """One compact line chart per weekly-load concept — value over weekly
    snapshots, target band shaded, points red when out of range."""
    out: list = []
    for concept in evolution:
        chart = _weekly_load_chart(concept)
        if chart is None:
            continue
        unit = concept.get("unit") or ""
        label = (
            f"<b>{_esc(concept.get('label') or concept.get('key'))}</b>"
            f"  <font size='7' color='#6b7280'>objetivo {concept.get('min')}–"
            f"{concept.get('max')} {unit}</font>"
        )
        out.append(KeepTogether([Paragraph(label, body_styles["body"]), chart]))
        out.append(Spacer(1, 4 * mm))
    return out or [Paragraph("<i>Sin histórico suficiente.</i>", body_styles["body_muted"])]


def _weekly_load_chart(concept: dict, width_cm: float = 17.5):
    pts = concept.get("points") or []
    if len(pts) < 2:
        return None

    import matplotlib.pyplot as plt

    from .charts._mpl import figure_to_flowable, setup_axes

    xs = list(range(len(pts)))
    ys = [p.get("value") for p in pts]
    labels = [_short_iso(p.get("date")) for p in pts]
    lo, hi = concept.get("min"), concept.get("max")

    fig, ax = plt.subplots(figsize=(7.0, 1.9))
    setup_axes(ax)
    if lo is not None and hi is not None:
        ax.axhspan(lo, hi, color="#16a34a", alpha=0.10, zorder=0)
    ax.plot(xs, ys, color="#0a2240", linewidth=1.6, zorder=2)
    for x, p in zip(xs, pts):
        color = "#0a2240" if p.get("status") == "within" else "#c8102e"
        ax.plot([x], [p.get("value")], marker="o", markersize=5, color=color, zorder=3)
    if lo is not None and hi is not None:
        ymin, ymax = ax.get_ylim()
        pad = (hi - lo) * 0.3 or 1.0
        ax.set_ylim(min(ymin, lo - pad), max(ymax, hi + pad))
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=7)
    ax.margins(x=0.06, y=0.25)
    return figure_to_flowable(fig, width_cm=width_cm)


def _short_iso(iso_date: str | None) -> str:
    if not iso_date:
        return ""
    parts = str(iso_date).split("-")
    return f"{parts[2]}/{parts[1]}" if len(parts) == 3 else str(iso_date)


def render_player_pdf(
    *,
    player: Player,
    department: Department,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    narrative: dict | None = None,
    weekly_evolution: list | None = None,
) -> bytes:
    category = player.category
    layout = (
        DepartmentLayout.objects
        .filter(department=department, category=category, is_active=True)
        .prefetch_related("sections__widgets__data_sources")
        .first()
    )

    cover = {
        "club_name": category.club.name.upper() if category else "",
        "club_logo": logo_image_for_club(category.club) if category else None,
        "title": f"{player.first_name} {player.last_name}".strip(),
        "subtitle": f"Reporte de {department.name}",
        "category_name": category.name if category else "",
        "period_label": _format_period(date_from, date_to),
        "generated_at": timezone.now().astimezone(_DISPLAY_TZ),
    }

    body_styles = styles()
    sections: list[dict[str, Any]] = []

    # The department agent's narrative ("telling a story") goes first, as the
    # executive read of the period; the injury block + widget layout follow.
    # Skipped silently when no narrative was produced (no key / API error).
    if narrative:
        sections.append({
            "title": "Análisis del período",
            "flowables": _analysis_section(narrative, body_styles),
        })

    # Weekly chronic-load evolution (from state snapshots) — value over weeks
    # with the target band shaded. Only present once ≥2 snapshots exist.
    if weekly_evolution:
        sections.append({
            "title": "Evolución de carga semanal",
            "flowables": _weekly_load_evolution_section(weekly_evolution, body_styles),
        })

    # NOTE: the player-level executive summary was intentionally removed
    # per client feedback — on a per-player portrait report the team-wide
    # status columns add no signal, the KPI strip duplicates info already
    # in the layout, and the page was cluttering the report. Team PDFs
    # still emit the exec summary; only the player path skips it.

    # For Médico reports: surface the player's injury history (active +
    # recent closed) as the FIRST content block. Client feedback: the
    # doctor's primary question is "is this player injured right now?",
    # so the answer can't be buried under a layout of metrics.
    if department.slug == "medico":
        injury_block = player_injury_summary(player)
        if injury_block:
            sections.append({
                "title": "Lesiones",
                "flowables": injury_block,
            })

    if layout is not None:
        for section in layout.sections.all():
            widgets = list(section.widgets.all())
            section_flowables: list = []
            for row_widgets in _pack_widgets_into_rows(widgets):
                payloads = [
                    resolve_widget(w, player.id, date_from=date_from, date_to=date_to)
                    for w in row_widgets
                ]
                section_flowables.extend(
                    _render_widget_row(row_widgets, payloads, body_styles)
                )
            sections.append({
                # Empty section titles render headerless in scaffold —
                # widgets already carry their own titles, so a fallback
                # like "Sección" was just visual noise.
                "title": section.title or "",
                "flowables": section_flowables,
            })
    else:
        sections.append({
            "title": "Sin layout configurado",
            "flowables": [
                Paragraph(
                    "No hay un DepartmentLayout activo para esta categoría "
                    f"en {department.name}.",
                    body_styles["body_muted"],
                ),
            ],
        })

    return build_pdf(
        orientation="portrait",
        cover=cover,
        sections=sections,
    )


def _pack_widgets_into_rows(widgets: list) -> list[list]:
    """Player-PDF packing rule: ONE widget per row, full page width.

    The web's column_span is honored on screen, but in the printed
    per-player report the client asked for each chart/table to use the
    full portrait width — 3-across charts in a 17.5cm column rendered
    as tiny illegible thumbnails. The team report keeps the multi-row
    packing (landscape has the horizontal room)."""
    return [[w] for w in widgets]


# Chart-on-left, table-on-right cell-width split. Tuned so even the
# wide donut keeps a circular aspect and the data table has room for
# 2–3 value columns without clipping. The two cells share the portrait
# content width minus a small inter-cell gutter.
_CHART_CELL_CM = 10.5
_TABLE_CELL_CM = _PORTRAIT_CONTENT_WIDTH_CM - _CHART_CELL_CM - 0.4

# When the data table needs more than this many columns to render, the
# side-by-side layout starts squeezing each column to an unreadable
# width. In that case we switch to a stacked layout: chart at full
# portrait width on top, table at full width below.
_SIDE_BY_SIDE_MAX_COLS = 3


def _chart_with_data_twin(widget, payload: dict, body_styles):
    """Build a chart-with-data twin for a chart widget.

    Two layout modes depending on the data table's column count:
    - **Side-by-side** (≤ `_SIDE_BY_SIDE_MAX_COLS` cols): chart in the
      left cell, data table in the right cell.
    - **Stacked** (> `_SIDE_BY_SIDE_MAX_COLS` cols): chart at full
      portrait width, data table below it at full width. Wider tables
      (e.g. multi_line with 4+ series) need the room.

    Returns None when the data table couldn't be built — caller falls
    back to single-cell rendering.
    """
    n_cols = expected_column_count(widget, payload) or 0
    if n_cols > _SIDE_BY_SIDE_MAX_COLS:
        return _chart_stacked_table(widget, payload, body_styles)
    return _chart_beside_table(widget, payload, body_styles)


def _title_flowables(widget, body_styles) -> list:
    flow: list = [Paragraph(widget.title, body_styles["body"])]
    if widget.description:
        flow.append(Paragraph(widget.description, body_styles["body_muted"]))
    flow.append(Spacer(1, 2 * mm))
    return flow


def _chart_beside_table(widget, payload: dict, body_styles):
    """Side-by-side layout: chart left, data table right."""
    data_tbl = build_data_table(widget, payload, max_width_cm=_TABLE_CELL_CM)
    if data_tbl is None:
        return None

    chart_flowables = render_widget_for_pdf(
        widget, payload, max_width_cm=_CHART_CELL_CM,
    )
    # build_data_table returns either a Table or a list of flowables
    # (the donut path emits a caption + spacer + table).
    table_cell = data_tbl if isinstance(data_tbl, list) else [data_tbl]

    row = Table(
        [[chart_flowables, table_cell]],
        colWidths=[_CHART_CELL_CM * cm, _TABLE_CELL_CM * cm],
        hAlign="LEFT",
    )
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether(_title_flowables(widget, body_styles) + [row])


def _chart_stacked_table(widget, payload: dict, body_styles):
    """Stacked layout: chart at full portrait width on top, then the
    data table at full width below. Used when the table has more than
    `_SIDE_BY_SIDE_MAX_COLS` columns and won't fit beside the chart."""
    chart_flowables = render_widget_for_pdf(
        widget, payload, max_width_cm=_PORTRAIT_CONTENT_WIDTH_CM,
    )
    data_tbl = build_data_table(
        widget, payload, max_width_cm=_PORTRAIT_CONTENT_WIDTH_CM,
    )
    if data_tbl is None:
        return None
    table_block = data_tbl if isinstance(data_tbl, list) else [data_tbl]

    # KeepTogether wraps the title block so the chart can't orphan
    # from its title; the data table is allowed to flow to the next
    # page if the chart alone fills the remainder of the current one.
    return [
        KeepTogether(_title_flowables(widget, body_styles) + chart_flowables),
        Spacer(1, 3 * mm),
        *table_block,
    ]


def _widget_inner_flowables(widget, payload: dict, body_styles, *, max_width_cm=None) -> list:
    flow: list = [Paragraph(widget.title, body_styles["body"])]
    if widget.description:
        flow.append(Paragraph(widget.description, body_styles["body_muted"]))
        flow.append(Spacer(1, 2 * mm))
    flow.extend(render_widget_for_pdf(widget, payload, max_width_cm=max_width_cm))
    return flow


def _render_widget_row(row_widgets: list, payloads: list[dict], body_styles) -> list:
    if len(row_widgets) == 1:
        w = row_widgets[0]
        payload = payloads[0]

        # Chart-type widgets with a data twin → render either as
        # chart-beside-table (narrow tables, ≤3 cols) or chart-on-top
        # of full-width-table (wider tables). The reader always gets
        # both the visual trend AND exact numbers.
        if w.chart_type in CHART_TYPES_WITH_DATA_TABLE and not payload.get("empty"):
            twin = _chart_with_data_twin(w, payload, body_styles)
            if twin is not None:
                # Stacked path returns a list of flowables; side-by-side
                # returns a single KeepTogether. Spread either case so
                # both layouts get the same trailing inter-widget spacer.
                if isinstance(twin, list):
                    return [*twin, Spacer(1, 8 * mm)]
                return [twin, Spacer(1, 8 * mm)]

        # Fallback: full-width single widget (table widgets, empty
        # chart payloads, etc.).
        flow = _widget_inner_flowables(
            w, payload, body_styles,
            max_width_cm=_PORTRAIT_CONTENT_WIDTH_CM,
        )
        if w.chart_type in _SPLITTABLE_CHART_TYPES:
            return [*flow, Spacer(1, 8 * mm)]
        return [KeepTogether(flow), Spacer(1, 8 * mm)]

    total_span = sum(
        max(1, min(12, int(getattr(w, "column_span", 12) or 12)))
        for w in row_widgets
    )
    cells = []
    col_widths_cm = []
    for w, payload in zip(row_widgets, payloads):
        span = max(1, min(12, int(getattr(w, "column_span", 12) or 12)))
        cell_width_cm = _PORTRAIT_CONTENT_WIDTH_CM * (span / total_span)
        inner_width_cm = max(3.0, cell_width_cm - _CELL_HORIZONTAL_PADDING_CM)
        col_widths_cm.append(cell_width_cm)
        cells.append(_widget_inner_flowables(
            w, payload, body_styles, max_width_cm=inner_width_cm,
        ))

    row_table = Table(
        [cells],
        colWidths=[w * cm for w in col_widths_cm],
        hAlign="LEFT",
    )
    row_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [row_table, Spacer(1, 8 * mm)]


def _format_period(
    date_from: datetime | None,
    date_to: datetime | None,
) -> str:
    if date_from and date_to:
        return f"{date_from:%d/%m/%Y} – {date_to:%d/%m/%Y}"
    if date_from:
        return f"Desde {date_from:%d/%m/%Y}"
    if date_to:
        return f"Hasta {date_to:%d/%m/%Y}"
    return "Sin filtro de fecha"
