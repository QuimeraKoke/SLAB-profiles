"""The executive Word report: one or two pages that say what matters.

The full reports print every widget of a layout with its chart AND its data
table — dozens of pages, all weighted the same. The executive one answers, for
a period: how is it going (the agent's summary, three findings), which numbers
moved (4–6 indicators against the previous period of the same length), what
happened (injuries and alerts in the period), two key charts, and what to do
next. The rest stays in the full report.

Indicators are chosen, not configured: the department's metrics the club
cares about — a band, an alert rule, or a direction of good — that have a
reading in the period, ranked by what needs attention (a reading outside the
"good" side of its band, then the biggest change).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from docx.shared import Pt, RGBColor

from dashboards.report_period import Periodo

from . import _docx

MAX_INDICADORES = 6
# A department's report covers its tests, not just its busiest one: without a
# cap, the wellness check-in (a band on every question) took all six slots of
# Físico and the GPS load never appeared.
MAX_POR_PLANTILLA = 2
# A raw attempt ("t10_1", "cmj_2") is never an indicator: its "best of three"
# sibling is.
_INTENTO = re.compile(r"_\d$")
GREEN = RGBColor(0x16, 0x7D, 0x4A)
RED = RGBColor(0xB4, 0x23, 0x18)


@dataclass
class Indicador:
    label: str
    unit: str
    valor: float
    previo: float | None
    direccion: str            # up | down | neutral
    banda: dict | None
    lecturas: int
    agregacion: str           # "media" | "último"
    fuente: str = ""          # the template's name, to tell two "HSR" apart

    @property
    def cambio_pct(self) -> float | None:
        if self.previo in (None, 0):
            return None
        return (self.valor - self.previo) / abs(self.previo) * 100

    @property
    def lectura_cambio(self) -> str:
        """'mejora' / 'empeora' / '' — from the direction of good."""
        c = self.cambio_pct
        if c is None or abs(c) < 1 or self.direccion not in ("up", "down"):
            return ""
        return "mejora" if (c > 0) == (self.direccion == "up") else "empeora"


def _num(v: float) -> str:
    if v is None:
        return "—"
    if abs(v) >= 100:
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _campos_clave(templates, category) -> list[tuple]:
    """(template, field spec, bands) for every metric the club cares about."""
    from goals.models import AlertRule

    from dashboards import category_bands

    con_regla = set(AlertRule.objects.filter(template__in=templates, is_active=True)
                    .values_list("template_id", "field_key"))
    out = []
    with category_bands.scope(category.id if category else None):
        for t in templates:
            campos = (t.config_schema or {}).get("fields") or []
            claves = {f.get("key") for f in campos}
            for f in campos:
                key = f.get("key")
                if not key or f.get("type") not in ("number", "calculated") or _INTENTO.search(key):
                    continue
                # One number per test: "best of three" over its average.
                if key.endswith("_prom") and key[:-5] + "_best" in claves:
                    continue
                bandas = category_bands.for_field(t, key, f.get("reference_ranges"))
                direccion = f.get("direction_of_good") or "neutral"
                # Tier: what the club judges (a band or an alert rule) first,
                # then what has a direction of good, then what it charts
                # (GPS load: no band, but the first thing Físico looks at).
                if bandas or (t.id, key) in con_regla:
                    tier = 0
                elif direccion in ("up", "down"):
                    tier = 1
                elif f.get("chart_type"):
                    tier = 2
                else:
                    continue
                out.append((t, f, bandas, tier))
    return out


def _agregar(valores: list[float]) -> tuple[float, str]:
    if len(valores) >= 3:
        return sum(valores) / len(valores), "media"
    return valores[-1], "último"


def indicadores(templates: Iterable, category, player_ids, periodo: Periodo,
                maximo: int = MAX_INDICADORES) -> list[Indicador]:
    """The period's indicators for one player (`player_ids=[id]`) or a squad.
    A squad's value is the mean over everyone's readings."""
    from exams.bands import band_for_value
    from exams.models import ExamResult

    templates = list(templates)
    campos = _campos_clave(templates, category)
    if not campos:
        return []
    prev = periodo.anterior()
    lecturas: dict = {}
    familias = {t.family_id for t in templates}
    for fam, recorded, data in (ExamResult.objects
                                .filter(player_id__in=list(player_ids),
                                        template__family_id__in=familias,
                                        recorded_at__gte=prev.desde,
                                        recorded_at__lte=periodo.hasta)
                                .order_by("recorded_at")
                                .values_list("template__family_id", "recorded_at", "result_data")):
        lecturas.setdefault(fam, []).append((recorded, data or {}))

    out: list[tuple[int, Indicador]] = []
    for t, f, bandas, tier in campos:
        filas = lecturas.get(t.family_id) or []
        ahora, antes = [], []
        for recorded, data in filas:
            v = data.get(f["key"])
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            (ahora if recorded >= periodo.desde else antes).append(float(v))
        if not ahora:
            continue
        valor, agg = _agregar(ahora)
        previo = _agregar(antes)[0] if antes else None
        out.append((tier, t.family_id, Indicador(
            label=f.get("label") or f["key"], unit=f.get("unit") or "",
            valor=valor, previo=previo,
            direccion=f.get("direction_of_good") or "neutral",
            banda=band_for_value(valor, bandas) if bandas else None,
            lecturas=len(ahora), agregacion=agg, fuente=t.name,
        )))

    def urgencia(par):
        tier, _fam, i = par
        mala = 1 if i.lectura_cambio == "empeora" else 0
        return (tier, -mala, -abs(i.cambio_pct or 0))
    out.sort(key=urgencia)
    elegidos, por_familia = [], {}
    for _tier, fam, i in out:
        if por_familia.get(fam, 0) >= MAX_POR_PLANTILLA:
            continue
        por_familia[fam] = por_familia.get(fam, 0) + 1
        elegidos.append(i)
        if len(elegidos) >= maximo:
            break
    from collections import Counter

    repetidos = Counter(i.label for i in elegidos)
    for i in elegidos:
        if repetidos[i.label] > 1 and i.fuente:
            i.label = f"{i.label} · {i.fuente}"
    return elegidos


# ─── Word blocks ────────────────────────────────────────────────────────


def tabla_indicadores(doc, items: list[Indicador], *, width_cm: float, titulo_periodo: str) -> None:
    if not items:
        _docx.body(doc, "Sin mediciones de las métricas clave en el período.", muted=True)
        return
    filas = []
    for i in items:
        c = i.cambio_pct
        cambio = "—" if c is None else f"{'▲' if c > 0 else '▼' if c < 0 else '='} {abs(c):.1f} %".replace(".", ",")
        if i.lectura_cambio:
            cambio += f" ({i.lectura_cambio})"
        unidad = f" {i.unit}" if i.unit else ""
        filas.append([
            i.label,
            f"{_num(i.valor)}{unidad}",
            f"{_num(i.previo)}{unidad}" if i.previo is not None else "—",
            cambio,
            (i.banda or {}).get("label", "—"),
            f"{i.agregacion} · {i.lecturas}",
        ])
    _docx.add_table(doc, ["Indicador", titulo_periodo, "Período anterior", "Cambio", "Banda",
                          "Base"], filas, width_cm=width_cm, numeric_from=1)
    # Colour the change text by its reading — with the word, never colour alone.
    tabla = doc.tables[-1]
    for fila, i in zip(tabla.rows[1:], items):
        color = GREEN if i.lectura_cambio == "mejora" else RED if i.lectura_cambio == "empeora" else None
        if color is not None:
            for run in fila.cells[3].paragraphs[0].runs:
                run.font.color.rgb = color
                run.bold = True


def lo_esencial(doc, narrative: dict | None, *, max_hallazgos: int = 3) -> None:
    n = narrative or {}
    resumen = (n.get("resumen") or "").strip()
    hallazgos = [h for h in (n.get("hallazgos") or n.get("analisis") or []) if h][:max_hallazgos]
    if not (resumen or hallazgos):
        return
    _docx.section_heading(doc, "Lo esencial")
    if resumen:
        _docx.body(doc, resumen)
    for h in hallazgos:
        doc.add_paragraph(str(h), style="List Bullet")


def proximos_pasos(doc, narrative: dict | None, *, maximo: int = 3) -> None:
    n = narrative or {}
    objetivos = [o for o in (n.get("objetivos") or []) if isinstance(o, dict)][:maximo]
    conclusiones = [c for c in (n.get("conclusiones") or []) if c][:maximo]
    if not (objetivos or conclusiones):
        return
    _docx.section_heading(doc, "Próximos pasos")
    for o in objetivos:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run((o.get("foco") or "").strip())
        r.bold = True
        if (o.get("estrategia") or "").strip():
            p.add_run(f" — {o['estrategia'].strip()}")
    for c in conclusiones:
        doc.add_paragraph(str(c), style="List Bullet")


def disponibilidad(doc, players, periodo: Periodo, *, width_cm: float, max_filas: int = 5) -> None:
    """Injuries that overlap the period: how many, days lost inside it, the
    ones still open. One line when there were none."""
    from django.db.models import Q

    from exams.models import Episode

    eps = list(Episode.objects
               .filter(player__in=list(players), template__slug="lesiones",
                       started_at__lte=periodo.hasta)
               .filter(Q(ended_at__isnull=True) | Q(ended_at__gte=periodo.desde))
               .select_related("player").order_by("-started_at"))
    _docx.section_heading(doc, "Disponibilidad")
    if not eps:
        _docx.body(doc, "Sin lesiones en el período.")
        return

    def dias(e):
        a = max(e.started_at, periodo.desde)
        b = min(e.ended_at or periodo.hasta, periodo.hasta)
        return max(0, (b - a).days)

    nuevas = sum(1 for e in eps if e.started_at >= periodo.desde)
    abiertas = sum(1 for e in eps if e.status == Episode.STATUS_OPEN)
    perdidos = sum(dias(e) for e in eps)
    _docx.body(doc, f"{len(eps)} lesión(es) en el período ({nuevas} nueva(s), {abiertas} abierta(s) "
                    f"hoy) · {perdidos} día(s) perdido(s) dentro del período.")
    varios = len({e.player_id for e in eps}) > 1
    filas = [[*([f"{e.player.first_name} {e.player.last_name}"] if varios else []),
              e.title or "(sin título)", e.started_at.strftime("%d/%m/%Y"),
              e.ended_at.strftime("%d/%m/%Y") if e.ended_at else "abierta", str(dias(e))]
             for e in eps[:max_filas]]
    _docx.add_table(doc, [*(["Jugador"] if varios else []), "Lesión", "Inicio", "Cierre",
                          "Días en el período"], filas, width_cm=width_cm,
                    numeric_from=4 if varios else 3)
    if len(eps) > max_filas:
        _docx.body(doc, f"… y {len(eps) - max_filas} más en el informe completo.", muted=True)


def alertas(doc, players, periodo: Periodo, *, department=None, width_cm: float,
            maximo: int = 4) -> None:
    """Alerts that fired inside the period (resolved or not), most severe first."""
    from django.db.models import Q

    from goals.models import Alert

    qs = (Alert.objects.filter(player__in=list(players), fired_at__lte=periodo.hasta)
          .filter(Q(fired_at__gte=periodo.desde) | Q(last_fired_at__gte=periodo.desde))
          .select_related("player"))
    lista = list(qs)
    if department is not None:
        from dashboards.pdf.executive_summary import _filter_alerts_by_department

        lista = _filter_alerts_by_department(lista, department)
    _docx.section_heading(doc, "Alertas del período")
    if not lista:
        _docx.body(doc, "Sin alertas en el período.")
        return
    orden = {"critical": 0, "warning": 1, "info": 2}
    lista.sort(key=lambda a: (orden.get(a.severity, 3), -(a.last_fired_at or a.fired_at).timestamp()))
    crit = sum(1 for a in lista if a.severity == "critical")
    warn = sum(1 for a in lista if a.severity == "warning")
    _docx.body(doc, f"{len(lista)} alerta(s): {crit} crítica(s), {warn} advertencia(s).")
    varios = len({a.player_id for a in lista}) > 1
    for a in lista[:maximo]:
        quien = f"{a.player.first_name} {a.player.last_name}: " if varios else ""
        sev = {"critical": "Crítica", "warning": "Advertencia"}.get(a.severity, "Info")
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{sev} · ")
        r.bold = True
        p.add_run(f"{quien}{a.message}")
    if len(lista) > maximo:
        _docx.body(doc, f"… y {len(lista) - maximo} más en el informe completo.", muted=True)


def graficos_clave(doc, candidatos, *, maximo: int, width_cm: float) -> int:
    """The first `maximo` widgets that actually draw a chart, in layout order
    (the club put the important ones first), without their data tables. The
    heading only when there is at least one. `candidatos`: (widget, payload)
    pairs, or (widget, callable → payload) to resolve lazily."""
    elegidos = []
    for w, payload in candidatos:
        if len(elegidos) >= maximo:
            break
        if callable(payload):
            payload = payload()
        if not payload or payload.get("empty"):
            continue
        figs = _docx._widget_figs(w, payload, width_cm)
        if figs:
            elegidos.append((w, figs))
    if not elegidos:
        return 0
    _docx.section_heading(doc, "Gráficos clave")
    for w, figs in elegidos:
        _docx.widget_title(doc, getattr(w, "title", "") or "", getattr(w, "description", None))
        _docx.add_chart_images(doc, figs, max_width_cm=width_cm)
    return len(elegidos)


def nota_final(doc) -> None:
    p = doc.add_paragraph()
    r = p.add_run("Informe ejecutivo. El detalle de todas las vistas, con sus tablas de datos, "
                  "está en la versión Completa.")
    r.italic = True
    r.font.size = Pt(8.5)
    r.font.color.rgb = _docx.MUTED
