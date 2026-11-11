"""Datos › Fuentes — which Drive document (or API) feeds which exam.

A catalogue of every automatic source SLAB reads, built from the same settings
the syncs use (so it cannot drift from what actually runs), with live numbers
from the database: how many results each source wrote per exam and the date of
the newest one, for the club of the selected category.

Provenance is read the way each ingest marks its rows:
    result_data.origen = …        the club's sheets (wellness formativo, GPS,
                                  evaluaciones, saltos, kine, peso diario)
    result_data.catapult_activity_id   Catapult
Sources that leave no per-row mark (Wellness Primer Equipo, VALD, COMET) report
the exam's totals for the club — they are its only automatic writer.

Document titles come from Google once and are cached for a day (Sheets quota
is shared with the syncs); without credentials the page shows the ids.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max
from django.utils import timezone

TITLE_TTL = 24 * 3600


def _sheet_url(sid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sid}"


def _titles(ids: list[str]) -> dict[str, str]:
    """{sheet id: document title}, cached a day; missing ones stay out."""
    out, missing = {}, []
    for sid in ids:
        t = cache.get(f"sheet-title:{sid}")
        if t:
            out[sid] = t
        else:
            missing.append(sid)
    creds = dict(creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
                 creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
    if not missing or not (creds["creds_file"] or creds["creds_json"]):
        return out

    def fetch(sid):
        try:
            from integrations.google_sheets import Documento

            return sid, Documento(sid, **creds).titulo()
        except Exception:  # noqa: BLE001 — a title is a nicety, never an error
            return sid, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        for sid, title in pool.map(fetch, missing):
            if title:
                cache.set(f"sheet-title:{sid}", title, TITLE_TTL)
                out[sid] = title
    return out


def _catalogue() -> list[dict]:
    """The sources, as configured. `exams`: template slugs; `mark`: how its
    rows are recognised (origen value, a key, or None = the exam's totals).
    `every_h`: how long the source normally goes without NEW data (nobody
    answers wellness at night, there is no GPS on a rest day) — past it, the
    page says "Atrasada". None: no expectation (manual, VALD, COMET)."""
    s = settings
    return [
        {"key": "wellness_pe", "name": "Wellness Primer Equipo", "kind": "sheet",
         "what": "Formulario de Google del check-in diario de Primer Equipo",
         "docs": [s.WELLNESS_SHEET_ID] if s.WELLNESS_SHEET_ID else [],
         "tab": s.WELLNESS_SHEET_WORKSHEET, "exams": ["checkin_fisico"], "mark": None,
         "schedule": "Cada 5 min de 08:00 a 12:00; cada 30 min el resto del día", "every_h": 20},
        {"key": "wellness_formativo", "name": "Wellness Formativo", "kind": "sheet",
         "what": "Un documento por categoría con sus hojas CHECK IN y CHECK OUT",
         "docs": list(s.FORMATIVO_WELLNESS_SHEET_IDS), "tab": "CHECK IN · CHECK OUT",
         "exams": ["checkin_formativo", "checkout_formativo"], "mark": ("origen", "google_sheets_formativo"),
         "schedule": "Cada hora (:40); relectura completa los domingos a las 04:50",
         "every_h": 20},
        {"key": "gps_formativo", "name": "Planilla GPS Formativo", "kind": "sheet",
         "what": "GPS de entrenamientos y partidos de todas las series (una hoja por equipo)",
         "docs": [s.FORMATIVO_GPS_SHEET_ID] if s.FORMATIVO_GPS_SHEET_ID else [], "tab": "U11 … U20 · SPARRING",
         "exams": ["gps_sesion", "gps_partido"], "mark": ("origen", "planilla_club_formativo_gps"),
         "schedule": "Cada hora (:25)", "every_h": 96},
        {"key": "eval_formativo", "name": "Planilla de Evaluaciones Formativo", "kind": "sheet",
         "what": "Evaluaciones físicas del formativo; su hoja JUGADORES define Serie y fecha de nacimiento",
         "docs": [s.FORMATIVO_EVAL_SHEET_ID] if s.FORMATIVO_EVAL_SHEET_ID else [],
         "tab": "FUERZA · CARRERAS · SALTOS · YO-YO · 1000 METROS · JUGADORES",
         "exams": ["fuerza", "carreras", "neuromuscular", "resistencia", "resistencia_1000m"],
         "mark": ("origen", "planilla_club_formativo"),
         "schedule": "Cada hora (:25). La hoja JUGADORES se aplica a mano (sync_formativo_roster)",
         "every_h": None},
        {"key": "saltos_formativo", "name": "Planillas de control de salto", "kind": "sheet",
         "what": "Saltos PRE (MD-1) y POST (MD+1) por partido, un documento por categoría",
         "docs": list(s.FORMATIVO_SALTOS_SHEET_IDS), "tab": "una pestaña por partido",
         "exams": ["control_salto"], "mark": ("origen", "planilla_club_saltos"),
         "schedule": "Cada hora (:55)", "every_h": None},
        {"key": "kine_formativo", "name": "Registro de Kinesiología Formativo", "kind": "sheet",
         "what": "Atenciones de los kinesiólogos del formativo",
         "docs": [s.KINE_FORMATIVO_SHEET_ID] if s.KINE_FORMATIVO_SHEET_ID else [], "tab": "f",
         "exams": ["notas_diarias_kinesiologico"], "mark": ("origen", "planilla_kine_formativo"),
         "schedule": "Cada hora (:10)", "every_h": 72},
        {"key": "peso_diario", "name": "Peso diario Primer Equipo", "kind": "sheet",
         "what": "Planilla de nutrición con el pesaje diario",
         "docs": [s.PESO_DIARIO_SHEET_ID] if s.PESO_DIARIO_SHEET_ID else [], "tab": "Registro peso diario",
         "exams": ["peso_talla"], "mark": ("origen", "planilla_peso_diario"),
         "schedule": "Cada 15 min", "every_h": 48},
        {"key": "catapult", "name": "Catapult OpenField", "kind": "api",
         "what": "GPS de Primer Equipo desde la cuenta Catapult del club",
         "docs": [], "tab": "", "exams": ["gps_sesion", "gps_partido"], "mark": ("key", "catapult_activity_id"),
         "schedule": "Cada hora (:15)", "every_h": 96},
        {"key": "vald", "name": "VALD Hub", "kind": "api",
         "what": "ForceDecks (CMJ, IMTP), ForceFrame (Hip AD/AB) y NordBord (Nórdico)",
         "docs": [], "tab": "", "exams": ["cmj", "imtp", "hip_adab", "nordico"], "mark": None,
         "schedule": "Cada hora (:30)", "every_h": None},
        {"key": "comet", "name": "COMET (ANFP)", "kind": "api",
         "what": "Fichas de partido oficiales: minutos, titularidad, goles, tarjetas; calendario",
         "docs": [], "tab": "", "exams": ["ficha_partido"], "mark": None,
         "schedule": "Cada hora (:45)", "every_h": None},
        {"key": "api_football", "name": "API-Football", "kind": "api",
         "what": "Calendario y resultados de partidos (eventos, no exámenes)",
         "docs": [], "tab": "", "exams": [], "mark": None,
         "schedule": "Cada 6 horas", "every_h": None},
    ]


def data_sources(club) -> dict:
    from exams.models import ExamResult, ExamTemplate

    cat = _catalogue()
    names: dict[str, str] = {}
    for t in ExamTemplate.objects.filter(department__club=club).order_by("-is_active_version"):
        names.setdefault(t.slug, t.name)
    titles = _titles(sorted({d for src in cat for d in src["docs"]}))
    now = timezone.now()

    base = ExamResult.objects.filter(template__department__club=club)
    out = []
    for src in cat:
        exams = []
        for slug in src["exams"]:
            qs = base.filter(template__slug=slug)
            mark = src["mark"]
            if mark and mark[0] == "origen":
                qs = qs.filter(result_data__origen=mark[1])
            elif mark and mark[0] == "key":
                qs = qs.filter(result_data__has_key=mark[1])
            agg = qs.aggregate(n=Count("id"), last=Max("recorded_at"), loaded=Max("created_at"))
            exams.append({"slug": slug, "name": names.get(slug, slug), "count": agg["n"],
                          "last": agg["last"].date().isoformat() if agg["last"] else None,
                          "loaded": agg["loaded"].isoformat() if agg["loaded"] else None,
                          "exact": mark is not None})
        loaded = max((e["loaded"] for e in exams if e["loaded"]), default=None)
        docs = [{"id": d, "title": titles.get(d), "url": _sheet_url(d)} for d in src["docs"]]
        if not docs and src.get("manual") and src["mark"] and src["mark"][0] == "origen":
            # Imported by hand with the document id on the command line: the
            # rows keep the document's title, which is what the club knows.
            for title in set(base.filter(result_data__origen=src["mark"][1]).order_by()
                             .values_list("result_data__origen_documento", flat=True).distinct()):
                if title:
                    docs.append({"id": None, "title": title, "url": None})
            docs.sort(key=lambda x: x["title"])
        configured = bool(docs) or src["kind"] == "api"
        has_data = any(e["count"] for e in exams)
        status = ("sin_configurar" if not configured else "sin_datos" if exams and not has_data
                  else "manual" if src.get("manual") else "ok")
        if status == "ok" and src["every_h"] and loaded:
            from datetime import datetime

            age = now - datetime.fromisoformat(loaded)
            if age > timedelta(hours=src["every_h"]):
                status = "atrasada"
        out.append({
            "key": src["key"], "name": src["name"], "kind": src["kind"], "what": src["what"],
            "schedule": src["schedule"], "tab": src["tab"], "status": status, "last_loaded": loaded,
            "docs": docs,
            "exams": exams,
        })
    from exams.sync_issues import open_issues

    issues = open_issues(club)
    per_source: dict[str, int] = {}
    for i in issues:
        per_source[i["source"]] = per_source.get(i["source"], 0) + 1
    for src in out:
        src["issues"] = per_source.get(src["key"], 0)
    return {"club": club.name, "sources": out, "issues": issues,
            "service_account": _service_account()}


def _service_account() -> str | None:
    """The account the club must share a new sheet with."""
    import json

    raw = settings.GOOGLE_SHEETS_CREDENTIALS_JSON
    try:
        if raw:
            import base64

            try:
                data = json.loads(base64.b64decode(raw))
            except Exception:  # noqa: BLE001
                data = json.loads(raw)
            return data.get("client_email")
        if settings.GOOGLE_SHEETS_CREDENTIALS_FILE:
            with open(settings.GOOGLE_SHEETS_CREDENTIALS_FILE) as fh:
                return json.load(fh).get("client_email")
    except Exception:  # noqa: BLE001
        return None
    return None
