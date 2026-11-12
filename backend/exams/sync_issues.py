"""Datos › Fuentes › Problemas — what the automatic syncs could not load.

Each sync collects what it skipped into an `IssueCollector` and saves it at the
end of the run. The table holds one row per PROBLEM, not per run:

* a problem found again is upserted (`last_seen_at`, `rows` = what the latest
  run skipped, a few examples);
* an open problem of a document the run read successfully, that the run did
  NOT find again, is closed (`resolved_at`) — the club fixed it in Drive, or
  added the player to the roster. Documents the run could not read keep their
  problems open: not finding them says nothing.

Recording never breaks a sync: any failure here is logged and swallowed.

The per-ingest helpers (`from_*`) translate each importer's report into issues.
They read the reports as the importers already write them for the console, so
the importers themselves stay untouched.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_EXAMPLES = 5
# Google answers a 429/503 now and then; a sheet is "inaccesible" for the club
# only when it keeps failing. The page hides younger unreachable issues.
UNREACHABLE_GRACE_H = 20


def _norm(text: object) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def unreachable_key(sid: str) -> str:
    return f"planilla_inaccesible|{sid}"


class IssueCollector:
    def __init__(self, club, source: str, *, commit: bool = True, sheet_id: str = ""):
        self.club, self.source, self.commit, self.sheet_id = club, source, commit, sheet_id or ""
        self.items: dict[str, dict] = {}
        self.read_docs: set[str] = set()
        self.read_ids: set[str] = set()
        self.whole = False

    # ── what the run read ────────────────────────────────────────────────
    def read(self, document: str | None = None, sid: str | None = None) -> None:
        """A document the run read in full: its old problems may be closed."""
        if document:
            self.read_docs.add(document)
        if sid:
            self.read_ids.add(sid)

    def complete(self) -> None:
        """The run read everything this source has (single-document sources)."""
        self.whole = True

    # ── what it found ────────────────────────────────────────────────────
    def add(self, kind: str, subject: str, *, document: str = "", detail: str = "",
            rows: int = 1, example: str | None = None, data_date: date | None = None,
            key: str | None = None, sheet_id: str = "", where: dict | None = None) -> None:
        """`where`: how to find the example in the sheet — {tab, row?, find?,
        date?, header?}; see `locate()`."""
        k = key or f"{kind}|{_norm(document)}|{_norm(subject)}"
        it = self.items.get(k)
        if it is None:
            it = self.items[k] = {"kind": kind, "subject": str(subject)[:200], "document": document[:200],
                                  "detail": detail, "rows": 0, "examples": [], "latest_data_date": None,
                                  "sheet_id": sheet_id or self.sheet_id, "locations": []}
        it["rows"] += rows
        if example and example not in it["examples"] and len(it["examples"]) < MAX_EXAMPLES:
            it["examples"].append(example)
            if where:
                loc = {"label": example, **{k2: (v.isoformat() if isinstance(v, date) else v)
                                            for k2, v in where.items() if v not in (None, "")}}
                it["locations"].append(loc)
        elif where and not it["locations"] and not example:
            it["locations"].append({"label": "", **{k2: v for k2, v in where.items() if v not in (None, "")}})
        if data_date and (it["latest_data_date"] is None or data_date > it["latest_data_date"]):
            it["latest_data_date"] = data_date

    def unreachable(self, sid: str, error: object, document: str = "") -> None:
        from django.core.cache import cache

        title = document or cache.get(f"sheet-title:{sid}") or sid
        self.add("planilla_inaccesible", title, document=title, rows=0,
                 detail=_short_error(error), key=unreachable_key(sid), sheet_id=sid)

    # ── persist ──────────────────────────────────────────────────────────
    def save(self) -> dict:
        if not self.commit:
            return {"found": len(self.items), "saved": False}
        try:
            return self._save()
        except Exception:  # noqa: BLE001 — never break the sync for this
            logger.exception("sync issues (%s): could not save", self.source)
            return {"found": len(self.items), "saved": False}

    def _save(self) -> dict:
        from exams.models import SyncIssue

        now = timezone.now()
        mine = SyncIssue.objects.filter(club=self.club, source=self.source)
        existing = {i.key: i for i in mine.filter(key__in=list(self.items))}
        new, changed = [], []
        for key, it in self.items.items():
            row = existing.get(key)
            if row is None:
                new.append(SyncIssue(club=self.club, source=self.source, key=key, first_seen_at=now,
                                     last_seen_at=now, **it))
                continue
            if row.resolved_at is not None:  # came back: a new episode
                row.first_seen_at, row.resolved_at = now, None
            for f, v in it.items():
                setattr(row, f, v)
            row.last_seen_at = now
            changed.append(row)
        SyncIssue.objects.bulk_create(new)
        if changed:
            SyncIssue.objects.bulk_update(changed, ["kind", "subject", "document", "detail", "rows", "examples",
                                                    "sheet_id", "locations", "latest_data_date", "first_seen_at", "last_seen_at",
                                                    "resolved_at"])
        stale = mine.filter(resolved_at__isnull=True).exclude(key__in=list(self.items))
        if not self.whole:
            stale = stale.filter(
                (Q(document__in=self.read_docs) & ~Q(kind="planilla_inaccesible"))
                | Q(kind="planilla_inaccesible", key__in=[unreachable_key(s) for s in self.read_ids]))
        closed = stale.update(resolved_at=now)
        return {"found": len(self.items), "new": len(new), "closed": closed}


def _short_error(exc: object) -> str:
    s = str(exc)
    low = s.lower()
    if "403" in s or "permission" in low or "forbidden" in low:
        return "Sin permiso: la planilla dejó de estar compartida con la cuenta de SLAB."
    if "404" in s or "not found" in low:
        return "No existe: la planilla fue borrada o cambió de dirección."
    return s[:300]


# ── report → issues, one helper per importer ─────────────────────────────────

_ENTRY = re.compile(r"^(?P<name>.*?) \((?P<ctx>.*)\)$")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def _split(entry: str) -> tuple[str, str]:
    m = _ENTRY.match(str(entry).strip())
    return (m["name"].strip(), m["ctx"]) if m else (str(entry).strip(), "")


def _iso(text: str) -> date | None:
    m = _ISO.search(text or "")
    try:
        return date.fromisoformat(m.group()) if m else None
    except ValueError:
        return None


def _fmt(d: date | None) -> str:
    months = "ene feb mar abr may jun jul ago sep oct nov dic".split()
    return f"{d.day} {months[d.month - 1]} {d.year}" if d else ""


NOT_IN_ROSTER = "No se cargó: el nombre no coincide con ningún jugador del plantel."
AMBIGUOUS = "No se cargó: el nombre coincide con más de un jugador."


def from_sheet_rows(col: IssueCollector, report, document: str) -> None:  # noqa: C901
    """Formativo GPS / Evaluaciones. Entries: "NAME (HOJA, YYYY-MM-DD)";
    out of range: "NAME YYYY-MM-DD HOJA: key=val; …"."""
    for entry in report.sin_jugador:
        name, ctx = _split(entry)
        day = _iso(ctx)
        hoja = ctx.split(",")[0].strip()
        col.add("jugador_no_encontrado", name, document=document, detail=NOT_IN_ROSTER, data_date=day,
                example=f"{hoja} · {_fmt(day)}" if day else hoja, where={"tab": hoja, "find": name, "date": day})
    for entry in getattr(report, "fuera_de_rango", []):
        head, _, vals = str(entry).partition(": ")
        day = _iso(head)
        name = head.split(day.isoformat())[0].strip() if day else head
        hoja = head.split(day.isoformat())[1].strip() if day else ""
        for kv in filter(None, (v.strip() for v in vals.split(";"))):
            metric = kv.split("=")[0]
            col.add("fuera_de_rango", f"{name} · {metric}", document=document, data_date=day,
                    detail="No se cargó el valor: está fuera del rango posible de la métrica.",
                    example=f"{hoja} {_fmt(day)}: {kv}".strip(), where={"tab": hoja, "find": name, "date": day})
    for attr, kind, why in (
        ("columnas_sin_mapear", "columna_faltante", "La hoja ya no tiene esta métrica: no se está cargando."),
        ("columnas_desconocidas", "columna_nueva", "Columna que SLAB no reconoce: sus datos no se cargan."),
    ):
        found = getattr(report, attr, None) or {}
        items = found.items() if isinstance(found, dict) else [("", found)]
        for hoja, cols in items:
            for c in cols or []:
                col.add(kind, str(c), document=document, detail=why, rows=0,
                        key=f"{kind}|{_norm(document)}|{_norm(hoja)}|{_norm(c)}",
                        example=f"Hoja {hoja}" if hoja else None,
                        where={"tab": hoja, "header": c if kind == "columna_nueva" else None})


def from_saltos(col: IssueCollector, report, sid: str = "") -> None:
    """Entries: "NAME (TAB TITLE: reason)"."""
    doc = report.documento
    for entry in report.sin_jugador:
        name, ctx = _split(entry)
        tab, _, why = ctx.rpartition(": ")
        kind = "nombre_ambiguo" if why.startswith("ambiguo") else "jugador_no_encontrado"
        col.add(kind, name, document=doc, detail=AMBIGUOUS if kind == "nombre_ambiguo" else NOT_IN_ROSTER,
                example=tab or None, sheet_id=sid, where={"tab": tab, "find": name})
    for tab in report.pestanas_sin_partido:
        col.add("pestana_sin_partido", tab, document=doc, rows=0, sheet_id=sid, where={"tab": tab},
                detail="No se cargó la pestaña: no tiene fecha en el título ni un partido que calce. "
                       "Poner la fecha del partido en el nombre de la pestaña (ej. «vs Everton 28-02»).")


def from_kine(col: IssueCollector, report, document: str) -> None:
    for f in report.sin_jugador:
        col.add("jugador_no_encontrado", f.nombre, document=document, detail=NOT_IN_ROSTER,
                data_date=f.fecha, example=f"fila {f.n}" + (f" · {_fmt(f.fecha)}" if f.fecha else ""),
                where={"tab": "f", "row": f.n})
    for f in report.fecha_invalida:
        col.add("fila_rechazada", f"{f.nombre} · fila {f.n}", document=document,
                key=f"fila_rechazada|{_norm(document)}|{f.identidad()}",
                detail="No se cargó: falta la fecha o el año es imposible.",
                example=f"Fila {f.n} · " + (f"fecha escrita «{f.fecha_cruda}»" if str(f.fecha_cruda or "").strip()
                                            else "fecha vacía"),
                where={"tab": "f", "row": f.n})
    if report.borrado_bloqueado:
        col.add("proteccion", "Borrado masivo bloqueado", document=document, rows=0, where={"tab": "f"},
                detail="Desaparecieron muchas filas de golpe y SLAB no las borró por seguridad. "
                       "Revisar que la hoja no se haya vaciado o filtrado por error.")


def from_peso(col: IssueCollector, report, document: str) -> None:
    for lst, kind in ((report.sin_jugador, "jugador_no_encontrado"), (report.ambiguos, "nombre_ambiguo")):
        for entry in lst:
            name, ctx = _split(entry)
            m = re.search(r"fila (\d+)", ctx)
            col.add(kind, name, document=document, detail=AMBIGUOUS if kind == "nombre_ambiguo" else NOT_IN_ROSTER,
                    example=ctx or None, where={"tab": "Registro peso diario", "row": int(m.group(1)) if m else None,
                                                "find": None if m else name})
    for entry in report.fuera_de_rango:
        head, _, peso = str(entry).rpartition(": ")
        day = _iso(head)
        name = head.split(day.isoformat())[0].strip() if day else head
        col.add("fuera_de_rango", f"{name} · peso", document=document, data_date=day,
                detail="No se cargó el valor: está fuera del rango posible de la métrica.",
                example=f"{_fmt(day)}: {peso} kg", where={"tab": "Registro peso diario", "find": name})


def from_composicion(col: IssueCollector, report, document: str) -> None:
    """Composición corporal formativo: one tab per category."""
    for counts, kind, why in ((report.sin_jugador, "jugador_no_encontrado", NOT_IN_ROSTER),
                              (report.ambiguos, "nombre_ambiguo", AMBIGUOUS)):
        for (tab, name), rows in counts.items():
            col.add(kind, name, document=document, detail=why, rows=len(rows),
                    key=f"{kind}|{_norm(document)}|{_norm(tab)}|{_norm(name)}",
                    example=f"Hoja {tab} · fila {rows[0]}", where={"tab": tab, "row": rows[0]})
    for f, why in report.rechazadas:
        col.add("fila_rechazada", f"{f.nombre} · {f.hoja} fila {f.fila}", document=document,
                key=f"fila_rechazada|{_norm(document)}|{_norm(f.hoja)}|{f.fila}|{_norm(f.nombre)}",
                detail=f"No se cargó: {why[0].lower()}{why[1:]}", data_date=f.fecha,
                example=f"Hoja {f.hoja} · fila {f.fila}" + (f" · {f.fecha_txt}" if f.fecha_txt else ""),
                where={"tab": f.hoja, "row": f.fila})
    for f, keys in report.fuera_de_rango:
        col.add("fuera_de_rango", f"{f.nombre} · {f.hoja} fila {f.fila}", document=document,
                key=f"fuera_de_rango|{_norm(document)}|{_norm(f.hoja)}|{f.fila}|{_norm(f.nombre)}",
                detail="No se cargó " + ", ".join(f"{k} = {f.valores[k]:g}".replace(".", ",") for k in keys)
                       + ": está fuera del rango posible de la métrica. El resto de la fila sí se cargó.",
                data_date=f.fecha, example=f"Hoja {f.hoja} · fila {f.fila}", where={"tab": f.hoja, "row": f.fila})


def from_name_counts(col: IssueCollector, document: str, *, not_found: dict | None = None,
                     ambiguous: dict | None = None, sheet: str = "", sid: str = "") -> None:
    """Wellness (Primer Equipo and Formativo): {raw name: responses}."""
    for counts, kind, why in ((not_found or {}, "jugador_no_encontrado", NOT_IN_ROSTER),
                              (ambiguous or {}, "nombre_ambiguo", AMBIGUOUS)):
        for name, n in counts.items():
            col.add(kind, name, document=document, detail=why, rows=n, example=f"Hoja {sheet}" if sheet else None,
                    sheet_id=sid, where={"tab": sheet, "find": name, "last": True})


def from_new_columns(col: IssueCollector, document: str, cols, sheet: str = "", sid: str = "") -> None:
    for c in cols or []:
        col.add("columna_nueva", str(c), document=document, rows=0,
                key=f"columna_nueva|{_norm(document)}|{_norm(sheet)}|{_norm(c)}",
                detail="Pregunta o columna nueva que SLAB no reconoce: sus respuestas no se cargan.",
                example=f"Hoja {sheet}" if sheet else None, sheet_id=sid, where={"tab": sheet, "header": c})


# ── read side ────────────────────────────────────────────────────────────────

def open_issues(club) -> list[dict]:
    """Open problems of the club's syncs, plus the review queues VALD and
    COMET keep themselves (profiles not linked to a player)."""
    from datetime import timedelta

    from exams.models import CometPlayerLink, SyncIssue, ValdProfileLink

    now = timezone.now()
    labels = dict(SyncIssue.KIND_CHOICES)
    out = []
    qs = (SyncIssue.objects.filter(club=club, resolved_at__isnull=True, dismissed_at__isnull=True)
          .exclude(kind="planilla_inaccesible", first_seen_at__gt=now - timedelta(hours=UNREACHABLE_GRACE_H)))
    for i in qs:
        out.append({"id": str(i.id), "source": i.source, "kind": i.kind, "kind_label": labels.get(i.kind, i.kind),
                    "subject": i.subject, "document": i.document, "detail": i.detail, "rows": i.rows,
                    "examples": i.examples, "locations": [l.get("label", "") for l in (i.locations or [])],
                    "has_sheet": bool(i.sheet_id),
                    "latest_data_date": i.latest_data_date.isoformat() if i.latest_data_date else None,
                    "first_seen_at": i.first_seen_at.isoformat(), "last_seen_at": i.last_seen_at.isoformat()})

    def link_issue(source, lid, name, seen, detail):
        out.append({"id": f"{source}-{lid}", "source": source, "kind": "jugador_no_encontrado",
                    "kind_label": labels["jugador_no_encontrado"], "subject": name or "(sin nombre)",
                    "document": "", "detail": detail, "rows": 0, "examples": [], "latest_data_date": None,
                    "locations": [], "has_sheet": False,
                    "first_seen_at": seen.isoformat() if seen else None,
                    "last_seen_at": seen.isoformat() if seen else None})

    # VALD's hub holds every athlete the club ever tested (other teams, trials):
    # hundreds of unlinked profiles, most of them not a problem. One summary
    # row, newest first, instead of burying the rest of the list.
    vald = list(ValdProfileLink.objects.filter(club=club, player__isnull=True)
                .order_by("-last_seen_at", "-created_at"))
    if vald:
        seen = vald[0].last_seen_at or vald[0].created_at
        out.append({"id": "vald-unlinked", "source": "vald", "kind": "jugador_no_encontrado",
                    "kind_label": f"Perfiles sin jugador ({len(vald)})",
                    "subject": f"{len(vald)} perfiles de VALD sin jugador asignado", "document": "",
                    "detail": "Sus tests no se cargan. Muchos son deportistas que no son del plantel; "
                              "si alguno sí lo es, se vincula en el admin (VALD profile links).",
                    "rows": 0, "examples": [f"{l.given_name} {l.family_name}".strip() for l in vald[:MAX_EXAMPLES]],
                    "locations": [], "has_sheet": False, "latest_data_date": None, "first_seen_at": None,
                    "last_seen_at": seen.isoformat() if seen else None})
    for l in CometPlayerLink.objects.filter(integration__club=club, player__isnull=True,
                                            match_method=CometPlayerLink.MATCH_UNRESOLVED):
        link_issue("comet", l.id, l.person_name, l.last_seen_at or l.created_at,
                   "Jugador de las fichas COMET sin jugador asignado: sus minutos, goles y tarjetas "
                   "no se cargan.")
    return out


# ── "Ver en la planilla" ─────────────────────────────────────────────────────

SHEET_TAB_TTL = 24 * 3600
LOCATE_TTL = 3600


def _col_letter(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _cell_matches_date(cell, day: date) -> bool:
    from datetime import datetime

    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return int(cell) == (day - date(1899, 12, 30)).days
    if isinstance(cell, datetime):
        return cell.date() == day
    s = str(cell or "")
    return day.isoformat() in s or f"{day.day}/{day.month}/{day.year}" in s or f"{day.day:02d}/{day.month:02d}/{day.year}" in s


def locate(issue, index: int = 0) -> dict:
    """The link that opens the sheet where the problem is: the document, the
    tab (`#gid=`) and, when it can be found, the row or column (`&range=`).

    A row number the importer knew is used as is. Otherwise the tab is read
    once (cached an hour) and searched: the row whose cells contain the name
    (and the date, when there is one); the LAST such row for form responses,
    which are appended at the bottom; a header in the first rows → its column.
    Without credentials or on any error, the document link alone."""
    from django.conf import settings
    from django.core.cache import cache

    sid = issue.sheet_id
    if not sid:
        return {"url": None, "precise": False, "note": "Esta fuente no es una planilla."}
    base = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    locs = issue.locations or []
    loc = locs[index] if 0 <= index < len(locs) else (locs[0] if locs else {})
    tab = loc.get("tab")
    if not tab:
        return {"url": base, "precise": False, "note": "Se abre el documento."}
    ck = f"sheet-locate:{issue.pk}:{index}:{issue.last_seen_at.timestamp()}"
    if (hit := cache.get(ck)) is not None:
        return hit
    creds = dict(creds_file=settings.GOOGLE_SHEETS_CREDENTIALS_FILE,
                 creds_json=settings.GOOGLE_SHEETS_CREDENTIALS_JSON)
    out = {"url": base, "precise": False, "note": "Se abre el documento."}
    try:
        from integrations.google_sheets import Documento

        doc = None
        tabs = cache.get(f"sheet-tabs:{sid}")
        if tabs is None:
            doc = Documento(sid, **creds)
            tabs = doc.tab_ids()
            cache.set(f"sheet-tabs:{sid}", tabs, SHEET_TAB_TTL)
        real = next((t for t in tabs if t == tab), None) or next(
            (t for t in tabs if _norm(t) == _norm(tab)), None)
        if real is None:
            out["note"] = f"No se encontró la pestaña «{tab}»: puede que la hayan renombrado."
            return out
        url = f"{base}#gid={tabs[real]}"
        out = {"url": url, "precise": False, "note": f"Se abre la pestaña «{real}»."}
        rng = None
        if loc.get("row"):
            rng = f"{loc['row']}:{loc['row']}"
        elif loc.get("find") or loc.get("header"):
            grid = (doc or Documento(sid, **creds)).values(real)
            if loc.get("header"):
                want = _norm(loc["header"])
                for r in grid[:6]:
                    i = next((j for j, c in enumerate(r) if _norm(c) == want), None)
                    if i is not None:
                        rng = f"{_col_letter(i)}:{_col_letter(i)}"
                        break
            else:
                want = _norm(loc["find"])
                day = date.fromisoformat(loc["date"]) if loc.get("date") else None
                rows = [n for n, r in enumerate(grid, start=1)
                        if any(_norm(c) == want for c in r)
                        and (day is None or any(_cell_matches_date(c, day) for c in r))]
                if not rows:  # names split in two columns, or written slightly differently
                    toks = set(want.split())
                    rows = [n for n, r in enumerate(grid, start=1)
                            if toks and toks <= set(" ".join(_norm(c) for c in r).split())
                            and (day is None or any(_cell_matches_date(c, day) for c in r))]
                if rows:
                    n = rows[-1] if loc.get("last") else rows[0]
                    rng = f"{n}:{n}"
        if rng:
            what = "la columna" if ":" in rng and not rng[0].isdigit() else f"la fila {rng.split(':')[0]}"
            out = {"url": f"{url}&range={rng}", "precise": True, "note": f"Se abre la pestaña «{real}» en {what}."}
    except Exception:  # noqa: BLE001 — a link is a nicety; the document is still there
        logger.warning("locate %s failed", issue.pk, exc_info=True)
    cache.set(ck, out, LOCATE_TTL)
    return out
