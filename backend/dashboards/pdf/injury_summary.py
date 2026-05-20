"""Injury summary block for the per-player Médico PDF.

Pulls Episode rows for the `lesiones` template and lays them out as
two tables: any currently-open episodes (active) and the last few
closed ones. Designed to live at the top of the Médico department
report so the first thing a doctor sees is the player's injury status,
not a chart.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from core.models import Player
from exams.models import Episode

from .scaffold import (
    COLOR_CRIT,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_PRIMARY,
    COLOR_RULE,
    styles,
    wrap_header_cells,
)


_RECENT_CLOSED_LIMIT = 5


def player_injury_summary(player: Player) -> list:
    """Return a list of reportlab flowables representing the player's
    injury history block. Empty list when the player has no `lesiones`
    episodes at all (callers can omit the block, no empty-state needed)."""
    body = styles()

    episodes = list(
        Episode.objects
        .filter(player=player, template__slug="lesiones")
        .order_by("-status", "-started_at")  # open first (status="open" < "closed" alphabetically; explicit ordering below)
    )
    if not episodes:
        return []

    open_eps = [e for e in episodes if e.status == Episode.STATUS_OPEN]
    closed_eps = [e for e in episodes if e.status == Episode.STATUS_CLOSED]
    recent_closed = closed_eps[:_RECENT_CLOSED_LIMIT]

    flow: list = []

    # ----- Active injuries ------------------------------------------------
    if open_eps:
        flow.append(Paragraph("Lesión activa", body["body"]))
        flow.append(Paragraph(
            f"<b>{len(open_eps)}</b> episodio(s) abierto(s) en seguimiento.",
            body["body_muted"],
        ))
        flow.append(Spacer(1, 2 * mm))
        flow.append(_active_table(open_eps))
        flow.append(Spacer(1, 4 * mm))
    else:
        # No active injuries — small positive note + days-since-last marker.
        last_closed = closed_eps[0] if closed_eps else None
        if last_closed and last_closed.ended_at:
            days = _days_between(last_closed.ended_at, _now())
            msg = (
                f"<b>Disponible.</b> Sin lesiones activas. "
                f"Última lesión cerrada hace {days} día(s)."
            )
        else:
            msg = "<b>Disponible.</b> Sin lesiones activas registradas."
        flow.append(Paragraph(msg, body["body"]))
        flow.append(Spacer(1, 4 * mm))

    # ----- Recent closed --------------------------------------------------
    if recent_closed:
        title = (
            f"Historial reciente ({len(recent_closed)} de {len(closed_eps)} "
            f"lesión(es) cerrada(s))"
        )
        flow.append(Paragraph(title, body["body"]))
        flow.append(Spacer(1, 2 * mm))
        flow.append(_closed_table(recent_closed))
        flow.append(Spacer(1, 6 * mm))

    # Keep the whole block together — it's compact (rarely more than a
    # third of a page) and orphaning the title would defeat the point of
    # surfacing injuries first.
    return [KeepTogether(flow)]


# --- Tables ---------------------------------------------------------------


def _active_table(open_eps: list) -> Table:
    rows: list[list] = [
        wrap_header_cells(
            ["Lesión", "Etapa", "Inicio", "Días activos"], align="left",
        ),
    ]
    for ep in open_eps:
        days = _days_between(ep.started_at, _now())
        rows.append([
            ep.title or "(sin título)",
            (ep.stage or "—").capitalize(),
            ep.started_at.strftime("%d/%m/%Y") if ep.started_at else "—",
            str(days),
        ])

    tbl = Table(rows, colWidths=[7.5 * cm, 3.5 * cm, 2.5 * cm, 2.5 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_CRIT),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("FONT", (3, 1), (3, -1), "Helvetica-Bold", 9.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _closed_table(closed_eps: list) -> Table:
    rows: list[list] = [
        wrap_header_cells(["Lesión", "Inicio", "Cierre", "Duración"], align="left"),
    ]
    for ep in closed_eps:
        duration = (
            _days_between(ep.started_at, ep.ended_at)
            if (ep.started_at and ep.ended_at) else None
        )
        rows.append([
            ep.title or "(sin título)",
            ep.started_at.strftime("%d/%m/%Y") if ep.started_at else "—",
            ep.ended_at.strftime("%d/%m/%Y") if ep.ended_at else "—",
            f"{duration} días" if duration is not None else "—",
        ])

    tbl = Table(rows, colWidths=[8.0 * cm, 3.0 * cm, 3.0 * cm, 2.5 * cm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_PRIMARY),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


# --- helpers --------------------------------------------------------------


def _now() -> datetime:
    return timezone.now()


def _days_between(start, end) -> int:
    """Days between two datetimes — naive subtraction in UTC works fine
    for whole-day deltas since both come from the same DB column."""
    if start is None or end is None:
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt_timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt_timezone.utc)
    return max(0, (end - start).days)
