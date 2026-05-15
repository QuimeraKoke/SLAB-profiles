"""Executive summary block — the "30-second scan" at the top of every PDF.

Goal stated by the client: "muy fácil de leer y revisar en 30 segundos,
para saber con quién puedes contar o no". So this block answers ONE
question: who are the red flags vs. who's green-light?

Team variant: 4 KPI cards on top (Plantel · Disponibles · Críticas ·
Advertencias) + a "Banderas rojas" list of the top players by critical
alert count.

Player variant: a KPI strip (Status · Alertas activas · Críticas) plus
a list of every active alert, grouped by severity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from core.models import Category, Department, Player

from .scaffold import (
    COLOR_CRIT,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_PRIMARY,
    COLOR_RULE,
    COLOR_WARN,
    styles as _styles,
)


# Color the status badge by severity so the eye snaps to red flags fast.
_STATUS_COLORS = {
    "injured": COLOR_CRIT,
    "recovery": COLOR_WARN,
    "reintegration": colors.HexColor("#eab308"),  # darker amber
    "available": COLOR_OK,
}
_STATUS_LABELS = {
    "injured": "Lesionado",
    "recovery": "Recuperación",
    "reintegration": "Reintegración",
    "available": "Disponible",
}
_SEVERITY_LABELS = {
    "critical": "Crítica",
    "warning": "Advertencia",
    "info": "Info",
}
_SEVERITY_COLORS = {
    "critical": COLOR_CRIT,
    "warning": COLOR_WARN,
    "info": COLOR_MUTED,
}


# --- Team -----------------------------------------------------------------


def team_executive_summary(
    *,
    department: Department,
    category: Category,
    position_id: UUID | None = None,
    player_ids: list[UUID] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    event_id: UUID | None = None,
) -> list:
    """Block of flowables for the team-report cover. KPIs on top + a
    "Banderas rojas" table of players with the most critical alerts.

    Department-scoped: only counts alerts whose source's template lives
    in `department`. Same scoping rule as `_resolve_team_alerts`.
    """
    from goals.models import Alert, AlertRule, AlertSource, AlertStatus
    from goals.models import Goal

    styles = _styles()
    elements: list = []

    roster_qs = Player.objects.filter(category=category, is_active=True)
    if position_id is not None:
        roster_qs = roster_qs.filter(position_id=position_id)
    if player_ids:
        roster_qs = roster_qs.filter(id__in=player_ids)
    roster = list(roster_qs)

    available = sum(1 for p in roster if p.status == "available")
    not_available = len(roster) - available

    # Alerts scoped to this department, for the roster only.
    alerts = list(
        Alert.objects.filter(
            player__in=roster, status=AlertStatus.ACTIVE,
        )
    )
    department_alerts = _filter_alerts_by_department(alerts, department)
    crit = sum(1 for a in department_alerts if a.severity == "critical")
    warn = sum(1 for a in department_alerts if a.severity == "warning")

    elements.append(_kpi_row([
        ("Plantel",       str(len(roster)),   None),
        ("Disponibles",   str(available),     COLOR_OK if available == len(roster) else COLOR_PRIMARY),
        ("No disp.",      str(not_available), COLOR_CRIT if not_available > 0 else COLOR_MUTED),
        ("Críticas",      str(crit),          COLOR_CRIT if crit > 0 else COLOR_OK),
        ("Advertencias",  str(warn),          COLOR_WARN if warn > 0 else COLOR_MUTED),
    ]))
    elements.append(Spacer(1, 6 * mm))

    # Roster by status — 4 columns (Disponible / Lesionado / Recuperación /
    # Reintegración) each listing the players currently in that state.
    # Players with active alerts get a colored dot next to their name so
    # the page still surfaces "who's a red flag" without a separate table.
    elements.append(_status_columns_table(roster, department_alerts, styles))

    return elements


_NAMES_PER_SUBCOLUMN = 15


def _status_columns_table(roster, department_alerts, styles) -> Any:
    """One column per player.status value, each column listing the
    player names currently in that state. Players with one or more
    active alerts in this department get a colored dot prefix.

    Auto-wraps within a status: when a status has >15 players the
    column splits into 2+ sub-columns (15 names each) so the table
    stays on a single page. The status's header cell SPANs its
    sub-columns so the label/count still reads as one logical column.

    Sized to the full landscape content width (~26 cm) — all
    sub-columns share equally so the table always fills the page.
    """
    # Group roster by status. Order: Disponible first (the most common
    # state), then the worsening progression: Lesionado → Recuperación
    # → Reintegración.
    statuses = ["available", "injured", "recovery", "reintegration"]
    groups: dict[str, list] = {s: [] for s in statuses}
    for p in roster:
        groups.setdefault(p.status, []).append(p)
    for s in groups:
        groups[s].sort(key=lambda p: (p.last_name.lower(), p.first_name.lower()))

    alerted_player_ids = {a.player_id for a in department_alerts}

    # How many sub-columns each status needs. Min 1 (even for empty
    # statuses — keeps the header layout consistent).
    sub_cols: dict[str, int] = {}
    for s in statuses:
        n = len(groups[s])
        sub_cols[s] = max(1, (n + _NAMES_PER_SUBCOLUMN - 1) // _NAMES_PER_SUBCOLUMN)
    total_subcols = sum(sub_cols.values())

    # Header row: one label cell per status, spanning its sub-columns.
    header_row: list = []
    span_cmds: list = []
    col_cursor = 0
    for s in statuses:
        count = len(groups[s])
        label = _STATUS_LABELS.get(s, s)
        color = _STATUS_COLORS.get(s, COLOR_MUTED)
        cell = Paragraph(
            f'<font color="{_hex(color)}"><b>{label}</b></font>'
            f'<font color="{_hex(COLOR_MUTED)}"> · {count}</font>',
            styles["body"],
        )
        header_row.append(cell)
        # Pad with empty placeholders for the SPANed cells.
        for _ in range(sub_cols[s] - 1):
            header_row.append("")
        if sub_cols[s] > 1:
            span_cmds.append((
                "SPAN",
                (col_cursor, 0),
                (col_cursor + sub_cols[s] - 1, 0),
            ))
        col_cursor += sub_cols[s]

    # Body rows: column-major fill within each status's sub-columns.
    # Player[i] goes to sub-col `i // _NAMES_PER_SUBCOLUMN`, row
    # `i % _NAMES_PER_SUBCOLUMN`. So the first 15 fill sub-col 0
    # top-to-bottom, then sub-col 1 starts at row 0 with player 16.
    body_row_count = _NAMES_PER_SUBCOLUMN
    body_rows: list[list] = []
    for row_i in range(body_row_count):
        row: list = []
        for s in statuses:
            for sub_i in range(sub_cols[s]):
                player_idx = sub_i * _NAMES_PER_SUBCOLUMN + row_i
                if player_idx < len(groups[s]):
                    p = groups[s][player_idx]
                    dot = (
                        '<font color="' + _hex(COLOR_CRIT) + '">● </font>'
                        if p.id in alerted_player_ids else ""
                    )
                    full_name = f"{p.first_name} {p.last_name}".strip()
                    row.append(Paragraph(f"{dot}{full_name}", styles["body"]))
                else:
                    row.append("")
        body_rows.append(row)

    # Drop trailing all-empty body rows when no status actually filled
    # the 15-row capacity — keeps the table from looking padded.
    while body_rows and all(c == "" for c in body_rows[-1]):
        body_rows.pop()

    rows = [header_row] + body_rows

    col_width = 26.5 * cm / max(1, total_subcols)
    tbl = Table(
        rows,
        colWidths=[col_width] * total_subcols,
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f9fafb")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        *span_cmds,
    ]))
    return tbl


def _hex(color) -> str:
    """reportlab HexColor → '#RRGGBB' string for use in <font color=...> tags."""
    try:
        return color.hexval().replace("0x", "#")
    except AttributeError:
        return str(color)


def _red_flags_table(department_alerts, roster, styles) -> Any:
    """Table: jugador · status · # alertas críticas · # totales. Sorted
    by (critical desc, total desc, name asc). Limited to 10 to keep the
    cover page scannable in 30 seconds — the full breakdown is in the
    Alertas section that follows."""
    from collections import Counter
    crit_by_player: Counter = Counter()
    total_by_player: Counter = Counter()
    for a in department_alerts:
        total_by_player[a.player_id] += 1
        if a.severity == "critical":
            crit_by_player[a.player_id] += 1

    if not total_by_player:
        return Paragraph(
            "Sin alertas activas en este departamento. ✅",
            styles["body"],
        )

    roster_by_id = {p.id: p for p in roster}
    ranked = sorted(
        total_by_player.keys(),
        key=lambda pid: (
            -crit_by_player.get(pid, 0),
            -total_by_player[pid],
            roster_by_id.get(pid).last_name.lower() if roster_by_id.get(pid) else "",
        ),
    )[:10]

    rows = [["Jugador", "Estado", "Críticas", "Total"]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
    ]
    for i, pid in enumerate(ranked, start=1):
        p = roster_by_id.get(pid)
        if p is None:
            continue
        status_label = _STATUS_LABELS.get(p.status, p.status)
        status_color = _STATUS_COLORS.get(p.status, COLOR_MUTED)
        crit_cell = str(crit_by_player.get(pid, 0))
        total_cell = str(total_by_player[pid])
        rows.append([
            f"{p.first_name} {p.last_name}".strip(),
            status_label,
            crit_cell,
            total_cell,
        ])
        style_cmds.append(("TEXTCOLOR", (1, i), (1, i), status_color))
        if crit_by_player.get(pid, 0) > 0:
            style_cmds.append(("FONT", (2, i), (2, i), "Helvetica-Bold", 9))
            style_cmds.append(("TEXTCOLOR", (2, i), (2, i), COLOR_CRIT))

    tbl = Table(
        rows,
        colWidths=[7 * cm, 4 * cm, 2.5 * cm, 2 * cm],
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _filter_alerts_by_department(alerts, department: Department) -> list:
    """Subset alerts whose source template lives in `department`. Uses
    the same lookups as `_resolve_team_alerts` so the headline KPI on
    the cover matches what the user will see in the Alertas section."""
    from goals.models import AlertRule, AlertSource
    from goals.models import Goal

    goal_ids = {a.source_id for a in alerts if a.source_type in (
        AlertSource.GOAL, AlertSource.GOAL_WARNING,
    )}
    threshold_ids = {
        a.source_id for a in alerts if a.source_type == AlertSource.THRESHOLD
    }

    goal_dept: dict = {}
    if goal_ids:
        for g in Goal.objects.filter(id__in=goal_ids).only(
            "id", "template__department_id",
        ).select_related("template"):
            goal_dept[g.id] = g.template.department_id

    rule_dept: dict = {}
    if threshold_ids:
        for r in AlertRule.objects.filter(id__in=threshold_ids).only(
            "id", "template__department_id",
        ).select_related("template"):
            rule_dept[r.id] = r.template.department_id

    out = []
    for a in alerts:
        if a.source_type in (AlertSource.GOAL, AlertSource.GOAL_WARNING):
            dept_id = goal_dept.get(a.source_id)
        elif a.source_type == AlertSource.THRESHOLD:
            dept_id = rule_dept.get(a.source_id)
        else:
            dept_id = None
        if dept_id == department.id:
            out.append(a)
    return out


# --- Player ---------------------------------------------------------------


def player_executive_summary(
    *,
    player: Player,
    department: Department,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list:
    """KPI strip + list of every active alert for this player in this
    department. The 30-second answer to "Should this player play?"."""
    from goals.models import Alert, AlertStatus

    styles = _styles()
    elements: list = []

    alerts = list(Alert.objects.filter(player=player, status=AlertStatus.ACTIVE))
    department_alerts = _filter_alerts_by_department(alerts, department)
    crit = sum(1 for a in department_alerts if a.severity == "critical")
    warn = sum(1 for a in department_alerts if a.severity == "warning")
    total = len(department_alerts)

    status_label = _STATUS_LABELS.get(player.status, player.status)
    status_color = _STATUS_COLORS.get(player.status, COLOR_MUTED)
    position_label = (
        player.position.name if player.position_id else "—"
    )

    elements.append(_kpi_row([
        ("Estado",       status_label,   status_color),
        ("Posición",     position_label, COLOR_PRIMARY),
        ("Alertas",      str(total),     COLOR_PRIMARY if total > 0 else COLOR_OK),
        ("Críticas",     str(crit),      COLOR_CRIT if crit > 0 else COLOR_OK),
        ("Advertencias", str(warn),      COLOR_WARN if warn > 0 else COLOR_MUTED),
    ]))
    elements.append(Spacer(1, 5 * mm))

    if department_alerts:
        elements.append(_alerts_list_for_player(department_alerts, styles))
    else:
        elements.append(Paragraph(
            "Sin alertas activas en este departamento. ✅",
            styles["body"],
        ))

    return elements


def _alerts_list_for_player(alerts, styles) -> Any:
    """A compact table of (severidad, mensaje, fecha) per alert. Order:
    critical first, then warning, then info; within each severity,
    newest first."""
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    sorted_alerts = sorted(
        alerts,
        key=lambda a: (severity_rank.get(a.severity, 99), -a.fired_at.timestamp()),
    )

    rows = [["Severidad", "Mensaje", "Fecha"]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (1, 1), (1, -1), COLOR_PRIMARY),
        ("TEXTCOLOR", (2, 1), (2, -1), COLOR_MUTED),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, a in enumerate(sorted_alerts, start=1):
        sev_label = _SEVERITY_LABELS.get(a.severity, a.severity)
        sev_color = _SEVERITY_COLORS.get(a.severity, COLOR_MUTED)
        rows.append([
            sev_label,
            a.message,
            a.fired_at.strftime("%d/%m/%Y"),
        ])
        style_cmds.append(("TEXTCOLOR", (0, i), (0, i), sev_color))
        style_cmds.append(("FONT", (0, i), (0, i), "Helvetica-Bold", 9))

    tbl = Table(rows, colWidths=[3 * cm, 10 * cm, 2.5 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# --- Shared: KPI strip ----------------------------------------------------


def _kpi_row(kpis: list[tuple[str, str, Any | None]]) -> Any:
    """Render a horizontal strip of KPI cards. Each tuple is
    (label, value, optional color override for the value).

    Sized tight on purpose: the status-columns table below uses
    most of the remaining vertical space and we want 15+ rows to fit
    on the same page. Reducing the KPI value font from 22pt → 17pt
    and the row heights frees ~1cm of vertical room.
    """
    styles = _styles()
    # Compact KPI value style — overrides the default `kpi_value` (22pt)
    # so the exec-summary page stays single-page even with 15+ players
    # per status column.
    compact_value = ParagraphStyle(
        "kpi_value_compact", parent=styles["body"],
        fontName="Helvetica-Bold", fontSize=17, alignment=TA_CENTER,
        textColor=COLOR_PRIMARY, leading=20,
    )
    cells_top: list = []
    cells_bot: list = []
    style_cmds: list = []
    for i, (label, value, color_override) in enumerate(kpis):
        cells_top.append(Paragraph(label, styles["kpi_label"]))
        cells_bot.append(Paragraph(value, compact_value))
        if color_override is not None:
            style_cmds.append(("TEXTCOLOR", (i, 1), (i, 1), color_override))

    width_per = (28 * cm - 4 * cm) / max(1, len(kpis))  # 28cm ~ landscape A4 content width
    # Explicit rowHeights — tight to leave room for 15-row status table.
    tbl = Table(
        [cells_top, cells_bot],
        colWidths=[width_per] * len(kpis),
        rowHeights=[0.55 * cm, 0.85 * cm],
        hAlign="CENTER",
    )
    style_cmds.extend([
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, COLOR_RULE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f9fafb")),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])
    tbl.setStyle(TableStyle(style_cmds))
    return tbl
