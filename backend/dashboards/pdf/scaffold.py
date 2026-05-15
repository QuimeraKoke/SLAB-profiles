"""PDF document scaffold — cover page, section headers, paginated footer.

The builders here are content-agnostic: they take strings + images +
flowables and emit a ready-to-write Story for reportlab. The team /
player PDF orchestrators (`team_report.py`, `player_report.py`) feed
this scaffold their executive-summary block + chart images.

Design goals (driven by the client's PEM/WIMU report aesthetics):
- Cover page legible from across the room: large logo + a 2-3 line
  identification block.
- Every page footer: "SLAB" left-aligned, page X / Y right-aligned.
- Section headers visually distinct from body — colored bar on the
  left + bold uppercase title.
- No "trapped" colors: the palette stays muted (slate / indigo /
  emerald / amber / red) so the document prints fine on B&W too.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


# Visual constants — kept in one place so the look stays cohesive
# across cover, sections, tables, footers.
COLOR_PRIMARY = colors.HexColor("#0f172a")     # deep slate (titles)
COLOR_ACCENT = colors.HexColor("#1e3a8a")      # navy (section bars)
COLOR_MUTED = colors.HexColor("#6b7280")       # gray (meta text)
COLOR_RULE = colors.HexColor("#e5e7eb")        # light gray (separators)
COLOR_OK = colors.HexColor("#16a34a")
COLOR_WARN = colors.HexColor("#f59e0b")
COLOR_CRIT = colors.HexColor("#dc2626")

PAGE_MARGIN = 14 * mm


# --- Custom doc template with header/footer drawn on every page ----------


class _PaginatedDoc(BaseDocTemplate):
    """BaseDocTemplate that draws the "SLAB · page X / Y" footer on
    every page. We can't know the total page count on first pass, so
    we render the doc twice (multiBuild) and inject the totals on the
    second pass — reportlab idiom."""

    def __init__(self, filename, pagesize, **kwargs):
        super().__init__(filename, pagesize=pagesize, **kwargs)
        page_width, page_height = pagesize
        frame = Frame(
            PAGE_MARGIN, PAGE_MARGIN,
            page_width - 2 * PAGE_MARGIN,
            page_height - 2 * PAGE_MARGIN - 10 * mm,  # leave room for footer
            id="content",
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        )
        self.addPageTemplates([
            PageTemplate(
                id="default", frames=[frame],
                onPage=self._draw_footer,
            ),
        ])

    def _draw_footer(self, canvas, doc):
        canvas.saveState()
        page_width, _ = doc.pagesize
        y = PAGE_MARGIN / 2
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(COLOR_MUTED)
        # Left: SLAB wordmark always present (per user spec)
        canvas.drawString(PAGE_MARGIN, y, "SLAB")
        # Right: "Página N" — `doc.page` is 1-indexed
        canvas.drawRightString(
            page_width - PAGE_MARGIN, y,
            f"Página {doc.page}",
        )
        # Optional center band on the rule line above the footer
        canvas.setStrokeColor(COLOR_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(PAGE_MARGIN, y + 4 * mm, page_width - PAGE_MARGIN, y + 4 * mm)
        canvas.restoreState()


# --- Public API -----------------------------------------------------------


def build_pdf(
    *,
    orientation: str,
    cover: dict[str, Any],
    sections: list[dict[str, Any]],
) -> bytes:
    """Render a PDF and return its bytes.

    `orientation` — "portrait" (player reports) or "landscape" (team).
    `cover` — see `cover_page()` for the dict shape.
    `sections` — list of {title, flowables} dicts; each section gets a
                 header bar + the supplied flowables (paragraphs,
                 tables, images) + a page break after.
    """
    pagesize = A4 if orientation == "portrait" else landscape(A4)
    buf = io.BytesIO()
    doc = _PaginatedDoc(
        buf, pagesize=pagesize,
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN, bottomMargin=PAGE_MARGIN,
        title=cover.get("title", "Reporte SLAB"),
        author=cover.get("club_name", "SLAB"),
    )

    story: list = []
    story.extend(cover_page(cover, pagesize))
    story.append(PageBreak())
    for section in sections:
        story.extend(section_block(section))
    doc.build(story)
    return buf.getvalue()


def cover_page(meta: dict[str, Any], pagesize: tuple[float, float]) -> list:
    """Cover page flowables. Expected meta keys:
        title, subtitle, club_name, club_logo (PIL/ImageReader/file-like),
        category_name, period_label, generated_at (datetime).
    """
    page_width, page_height = pagesize
    content_width = page_width - 2 * PAGE_MARGIN
    elements: list = []

    # Logo — centered, ~6cm tall. Auto-scaled. Falls back to a 0-height
    # spacer if no logo was uploaded (clubs created via tests, etc.).
    logo_source = meta.get("club_logo")
    if logo_source is not None:
        try:
            img = Image(logo_source, width=6 * cm, height=6 * cm, kind="proportional")
            img.hAlign = "CENTER"
            elements.append(Spacer(1, 2 * cm))
            elements.append(img)
        except Exception:  # noqa: BLE001 — bad image shouldn't kill the PDF
            elements.append(Spacer(1, 6 * cm))
    else:
        elements.append(Spacer(1, 6 * cm))

    elements.append(Spacer(1, 1 * cm))

    # Title block
    styles = _styles()
    elements.append(Paragraph(meta.get("club_name", ""), styles["cover_club"]))
    elements.append(Paragraph(meta.get("title", "Reporte SLAB"), styles["cover_title"]))
    if meta.get("subtitle"):
        elements.append(Paragraph(meta["subtitle"], styles["cover_subtitle"]))

    elements.append(Spacer(1, 1.5 * cm))

    # Meta table — 2 columns key/value
    meta_rows: list[tuple[str, str]] = []
    if meta.get("category_name"):
        meta_rows.append(("Categoría", meta["category_name"]))
    if meta.get("period_label"):
        meta_rows.append(("Período", meta["period_label"]))
    if meta.get("generated_at"):
        gen: datetime = meta["generated_at"]
        meta_rows.append(("Generado", gen.strftime("%d/%m/%Y · %H:%M")))

    if meta_rows:
        # Center the meta block as a compact unit. Narrow columns + the
        # table itself horizontally centered. The original sizing used
        # the full content width which made the values drift to the
        # right edge of the cover — unbalanced under the centered title.
        tbl = Table(
            meta_rows,
            colWidths=[3 * cm, 6 * cm],
            hAlign="CENTER",
        )
        tbl.setStyle(TableStyle([
            ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
            ("FONT", (1, 0), (1, -1), "Helvetica", 10),
            ("TEXTCOLOR", (0, 0), (0, -1), COLOR_MUTED),
            ("TEXTCOLOR", (1, 0), (1, -1), COLOR_PRIMARY),
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("ALIGN", (1, 0), (1, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(tbl)

    return elements


def section_block(section: dict[str, Any]) -> list:
    """One section = a bar-style title + flowables. The section ends
    with a PageBreak so each major section opens on a fresh page —
    consistent rhythm + room for future per-section narrative."""
    elements: list = section_header(section["title"])
    elements.extend(section.get("flowables", []))
    elements.append(PageBreak())
    return elements


def section_header(title: str) -> list:
    """Reusable section title — colored bar on the left + bold title."""
    styles = _styles()
    return [
        Spacer(1, 4 * mm),
        Table(
            [[" ", title]],
            colWidths=[3 * mm, None],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), COLOR_ACCENT),
                ("FONT", (1, 0), (1, 0), "Helvetica-Bold", 13),
                ("TEXTCOLOR", (1, 0), (1, 0), COLOR_PRIMARY),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]),
        ),
        Spacer(1, 5 * mm),
    ]


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_club": ParagraphStyle(
            "cover_club", parent=base["Normal"],
            fontName="Helvetica", fontSize=11, alignment=TA_CENTER,
            textColor=COLOR_MUTED, spaceAfter=4,
        ),
        "cover_title": ParagraphStyle(
            "cover_title", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=24, alignment=TA_CENTER,
            textColor=COLOR_PRIMARY, leading=28, spaceAfter=4,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle", parent=base["Normal"],
            fontName="Helvetica", fontSize=12, alignment=TA_CENTER,
            textColor=COLOR_MUTED,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName="Helvetica", fontSize=10, alignment=TA_LEFT,
            textColor=COLOR_PRIMARY, leading=14,
        ),
        "body_muted": ParagraphStyle(
            "body_muted", parent=base["Normal"],
            fontName="Helvetica", fontSize=9, alignment=TA_LEFT,
            textColor=COLOR_MUTED, leading=12,
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label", parent=base["Normal"],
            fontName="Helvetica", fontSize=8, alignment=TA_CENTER,
            textColor=COLOR_MUTED,
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=22, alignment=TA_CENTER,
            textColor=COLOR_PRIMARY,
        ),
    }


def styles() -> dict[str, ParagraphStyle]:
    """Public accessor for orchestrators that need paragraph styles."""
    return _styles()


# --- Helpers consumed by the team / player orchestrators -----------------


def logo_image_for_club(club) -> Any | None:
    """Return a logo handle reportlab can embed, or None if the club
    has no logo uploaded. Reads the file once into memory so the PDF
    build doesn't hold an S3 connection open.

    Returns a `BytesIO` (NOT an `ImageReader`) because reportlab's
    `Image` flowable expects a filename or a file-like — passing an
    ImageReader raises `TypeError: expected str, bytes or os.PathLike
    object, not ImageReader` inside `os.path.splitext`. The bare
    BytesIO works because it duck-types as a file (has `.read()`)
    and reportlab's `Image` checks for that and switches to `fp` mode.
    """
    if not club.logo:
        return None
    try:
        with club.logo.open("rb") as fh:
            data = fh.read()
        return io.BytesIO(data)
    except Exception:  # noqa: BLE001 — missing storage file shouldn't kill the PDF
        return None
