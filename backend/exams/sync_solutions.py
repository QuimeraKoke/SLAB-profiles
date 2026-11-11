"""Datos › Fuentes › Problemas › "Ver soluciones".

For one problem, the ways to fix it — explained, with what each one would do —
and `apply()` for the one the staff choose. Nothing is applied on its own.

* Jugador no encontrado / Nombre ambiguo → "Vincular a <jugador>" (suggested
  candidates first, any player of the club allowed), or "No es del plantel".
  A link is a `PlayerAlias` every sheet sync checks first
  (`exams.sheet_aliases`), so it fixes the name in EVERY sheet that writes it.
* Pestaña sin partido (saltos) → "Asignar al partido del <día>" (the club's
  reviewed table `load_control.JumpTabMatch`), or "No es partido".
* Columna nueva / faltante, fila rechazada, fuera de rango, protección,
  planilla inaccesible → what to do in Drive, plus "Ignorar".
* COMET → link the COMET person to a player (its own link table).

After a change the source's sync is queued, so the rows load in minutes
instead of at the next scheduled tick.
"""
from __future__ import annotations

import re
from datetime import date

from django.utils import timezone

from exams.sheet_aliases import key as akey

PLAYER_KINDS = ("jugador_no_encontrado", "nombre_ambiguo")

RESYNC = {
    "wellness_pe": ("exams.tasks.sync_wellness_responses", {"mode": "reconcile", "since_days": 3}),
    "wellness_formativo": ("exams.tasks.sync_wellness_formativo", {}),
    "gps_formativo": ("exams.tasks.sync_formativo_sheets", {}),
    "eval_formativo": ("exams.tasks.sync_formativo_sheets", {}),
    "saltos_formativo": ("exams.tasks.sync_formativo_saltos", {}),
    "kine_formativo": ("exams.tasks.sync_kine_formativo", {}),
    "peso_diario": ("exams.tasks.sync_peso_diario", {}),
}


def resync(sources) -> list[str]:
    from celery import current_app

    queued = []
    for task, kwargs in {RESYNC[s][0]: RESYNC[s][1] for s in sources if s in RESYNC}.items():
        try:
            current_app.send_task(task, kwargs=kwargs)
            queued.append(task)
        except Exception:  # noqa: BLE001 — the hourly tick will catch up
            pass
    return queued


# ── candidates ───────────────────────────────────────────────────────────────

def _lev1(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 4:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def _birth_years(issue, season: int) -> tuple[set[int], str]:
    """Birth years the document points at, and how to say it: "CAT 07-05" →
    2005-2007; "U16" / "SUB 16" → 2010-2011 in 2026."""
    text = " ".join([issue.document or "", *(issue.examples or [])]).upper()
    m = re.search(r"CAT\s*(\d{2})(?:\s*-\s*(\d{2}))?", text)
    if m:
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        lo, hi = sorted((2000 + a, 2000 + b))
        return set(range(lo, hi + 1)), f"CAT {m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else "")
    m = re.search(r"(?<![A-Z0-9])(?:U|SUB\s?)(\d{2})(?!\d)", text)
    if m:
        age = int(m.group(1))
        return {season - age, season - age + 1}, f"U{age}"
    return set(), ""


def _player_label(p) -> dict:
    return {"id": str(p.id), "name": " ".join(x for x in (p.first_name, p.last_name, p.second_last_name) if x),
            "category": p.category.name if p.category_id else "",
            "birth_year": p.date_of_birth.year if p.date_of_birth else None, "active": p.is_active}


def candidates(club, written: str, issue=None, limit: int = 4) -> list[dict]:
    """Players of the club whose name could be `written`, best first, each with
    the reasons in words. Needs at least a surname in common."""
    from core.models import Player

    toks = [t for t in akey(written).split() if len(t) > 1]
    if not toks:
        return []
    season = timezone.localdate().year
    years, label = _birth_years(issue, season) if issue else (set(), "")
    surname_only = len(toks) == 1
    scored = []
    for p in Player.objects.filter(category__club=club).select_related("category"):
        first = akey(p.first_name).split()
        last = akey(p.last_name).split()
        second = akey(p.second_last_name).split()
        reasons, score = [], 0.0
        hit_first = any(_lev1(t, f) for t in toks for f in first)
        hit_last = any(_lev1(t, l) for t in toks for l in last)
        hit_second = bool(second) and any(_lev1(t, s) for t in toks for s in second)
        # Sheets write "ANDHER" or "ROJAS": one word, first name or surname.
        if not (hit_last or (hit_second and hit_first) or (len(toks) == 1 and hit_first)):
            continue
        if hit_first:
            score += 2; reasons.append("nombre")
        if hit_last:
            score += 3; reasons.append("apellido paterno")
        if hit_second:
            score += 1.5; reasons.append("apellido materno")
        why = ["Coinciden " + ", ".join(reasons)] if reasons else []
        fits = None
        if years and p.date_of_birth:
            fits = p.date_of_birth.year in years
            if fits:
                score += 1.5; why.append(f"nacido en {p.date_of_birth.year}, calza con {label}")
            else:
                score -= 1; why.append(f"nacido en {p.date_of_birth.year}: no calza con {label}")
        if surname_only and not fits:
            continue  # a bare surname only means something inside the team
        if not p.is_active:
            score -= 1; why.append("inactivo")
        if score >= (3.5 if not surname_only else 3):
            scored.append((score, p, why))
    scored.sort(key=lambda t: (-t[0], t[1].last_name))
    top = scored[:limit if not surname_only else 6]
    out = []
    for i, (score, p, why) in enumerate(top):
        clear = i == 0 and score >= 5 and (len(top) == 1 or score - top[1][0] >= 1.5)
        out.append({**_player_label(p), "reasons": why, "recommended": clear})
    return out


# ── solutions per problem ────────────────────────────────────────────────────

def _issue_dict(issue) -> dict:
    return {"id": str(issue.id), "source": issue.source, "kind": issue.kind,
            "kind_label": issue.get_kind_display(), "subject": issue.subject, "document": issue.document,
            "detail": issue.detail, "rows": issue.rows, "examples": issue.examples,
            "locations": [l.get("label", "") for l in (issue.locations or [])], "has_sheet": bool(issue.sheet_id)}


def _sheet_url(issue) -> str | None:
    from django.conf import settings

    single = {"gps_formativo": settings.FORMATIVO_GPS_SHEET_ID, "eval_formativo": settings.FORMATIVO_EVAL_SHEET_ID,
              "kine_formativo": settings.KINE_FORMATIVO_SHEET_ID, "peso_diario": settings.PESO_DIARIO_SHEET_ID,
              "wellness_pe": settings.WELLNESS_SHEET_ID}
    sid = issue.sheet_id or single.get(issue.source)
    if not sid and issue.kind == "planilla_inaccesible":
        sid = issue.key.split("|", 1)[1]
    if not sid:
        from django.core.cache import cache

        multi = list(settings.FORMATIVO_SALTOS_SHEET_IDS) + list(settings.FORMATIVO_WELLNESS_SHEET_IDS)
        sid = next((s for s in multi if cache.get(f"sheet-title:{s}") == issue.document), None)
    return f"https://docs.google.com/spreadsheets/d/{sid}" if sid else None


def _impact(rows: int) -> str:
    if not rows:
        return ""
    if rows == 1:
        return "Se cargaría 1 fila que hoy queda fuera."
    return f"Se cargarían {rows} filas que hoy quedan fuera."


def solutions(club, issue_id: str) -> dict:
    from exams.models import SyncIssue

    if issue_id.startswith("comet-"):
        return _comet_solutions(club, issue_id)
    issue = SyncIssue.objects.get(club=club, pk=issue_id)
    url = _sheet_url(issue)
    opts: list[dict] = []
    k = issue.kind
    same_name = []
    if k in PLAYER_KINDS:
        cands = candidates(club, issue.subject, issue)
        same_name = [{"source": i.source, "document": i.document, "rows": i.rows}
                     for i in SyncIssue.objects.filter(club=club, kind__in=PLAYER_KINDS, resolved_at__isnull=True,
                                                       dismissed_at__isnull=True).exclude(pk=issue.pk)
                     if akey(i.subject) == akey(issue.subject)]
        total = issue.rows + sum(s["rows"] for s in same_name)
        opts.append({
            "action": "link", "title": "Vincular a un jugador del plantel",
            "explanation": (f"SLAB recordará que «{issue.subject}» es ese jugador, en esta y en todas las planillas "
                            "que lo escriban así. La planilla se vuelve a sincronizar enseguida."
                            + (" Es un nombre ambiguo: elige cuál de los dos es." if k == "nombre_ambiguo" else "")),
            "impact": _impact(total), "candidates": cands, "search": True,
            "recommended": any(c["recommended"] for c in cands),
        })
        opts.append({
            "action": "dismiss", "title": "No es del plantel", "note": "No es del plantel",
            "explanation": "Un jugador a prueba, de otro club o que ya no está. El problema se oculta y no vuelve "
                           "a aparecer; sus filas siguen sin cargarse.",
            "impact": "", "recommended": not cands,
        })
    elif k == "pestana_sin_partido":
        matches = _tab_match_options(club, issue)
        opts.append({
            "action": "assign_match", "title": "Asignar la pestaña a un partido",
            "explanation": "Queda guardado en la tabla de pestañas revisadas por el club: ninguna sincronización "
                           "lo vuelve a mover. Alternativa: poner la fecha en el nombre de la pestaña en Drive.",
            "impact": "Se cargarían los saltos de esa pestaña.", "matches": matches,
            "recommended": any(m["recommended"] for m in matches),
        })
        opts.append({"action": "not_a_match", "title": "No es un partido",
                     "explanation": "Una pestaña de prueba o de evaluación. Se guarda como «no es partido» y "
                                    "no se vuelve a reportar.", "impact": "", "recommended": False})
    elif k in ("columna_nueva", "columna_faltante"):
        opts.append({"action": "info", "title": "Pedir que SLAB la cargue",
                     "explanation": ("Agregar una columna nueva a un examen lo hacemos nosotros (hay que decidir a qué "
                                     "métrica corresponde). Avisa al equipo de SLAB con el nombre de la columna."
                                     if k == "columna_nueva" else
                                     "Si la columna se renombró, volver al nombre anterior en Drive la recupera. "
                                     "Si se quitó a propósito, avisa al equipo de SLAB."),
                     "impact": "", "url": url, "recommended": True})
        opts.append({"action": "dismiss", "title": "Ignorar esta columna", "note": "Columna ignorada",
                     "explanation": "No es un dato que interese guardar. No vuelve a aparecer.", "impact": "",
                     "recommended": False})
    elif k == "planilla_inaccesible":
        from exams.data_sources import _service_account

        opts.append({"action": "info", "title": "Volver a compartir la planilla",
                     "explanation": f"Compartirla como lector con {_service_account() or 'la cuenta de SLAB'}. "
                                    "Se cierra sola en la siguiente sincronización.",
                     "impact": "", "url": url, "recommended": True})
    else:  # fila rechazada, fuera de rango, protección
        opts.append({"action": "info", "title": "Corregir en la planilla",
                     "explanation": "Se arregla en Drive: " + {
                         "fila_rechazada": "completar o corregir la fecha de la fila.",
                         "fuera_de_rango": "corregir el valor (suele ser un error de tipeo o una celda con formato "
                                           "de fecha).",
                         "proteccion": "revisar que la hoja no se haya vaciado o filtrado. Si las filas se borraron "
                                       "a propósito, avisa al equipo de SLAB.",
                     }.get(k, "corregir la celda.") + " El problema se cierra solo en la siguiente sincronización.",
                     "impact": _impact(issue.rows), "url": url, "recommended": True})
        opts.append({"action": "dismiss", "title": "Ignorar", "note": "Ignorado",
                     "explanation": "No interesa cargarlo. No vuelve a aparecer.", "impact": "",
                     "recommended": False})
    return {"issue": _issue_dict(issue), "same_name": same_name, "options": opts}


def _tab_match_options(club, issue) -> list[dict]:
    from core.models import Bracket
    from exams.formativo_saltos_ingest import team_of_document
    from load_control.matches import match_links, team_match_days

    season = issue.first_seen_at.year
    name = team_of_document(issue.document)
    bracket = Bracket.objects.filter(name=name).first() if name else None
    if bracket is None:
        return []
    today = timezone.localdate()
    kinds = team_match_days(club, season, bracket, date(season, 1, 1), min(today, date(season, 12, 31)))
    links = match_links(club, season, bracket, kinds)
    tab = akey(issue.subject)
    out = []
    for day in sorted(kinds, reverse=True):
        opp = (links.get(day) or {}).get("opponent") or ""
        opp_toks = [t for t in akey(opp).split() if len(t) > 2]
        # Tabs are often "M40 UE": initials of the opponent.
        initials = "".join(t[0] for t in opp_toks)
        hit = bool(opp_toks) and (any(t in tab.split() for t in opp_toks)
                                  or (len(initials) >= 2 and initials in tab.split()))
        out.append({"date": day.isoformat(), "opponent": opp, "kind": kinds[day], "recommended": hit})
    if sum(m["recommended"] for m in out) != 1:
        for m in out:
            m["recommended"] = False
    return out


def _comet_solutions(club, issue_id: str) -> dict:
    from exams.models import CometPlayerLink

    link = CometPlayerLink.objects.get(pk=issue_id.removeprefix("comet-"), integration__club=club)
    cands = candidates(club, link.person_name)
    issue = {"id": issue_id, "source": "comet", "kind": "jugador_no_encontrado", "kind_label": "Jugador no encontrado",
             "subject": link.person_name, "document": "", "detail": "", "rows": 0, "examples": [],
             "locations": [], "has_sheet": False}
    return {"issue": issue, "same_name": [], "options": [{
        "action": "link", "title": "Vincular a un jugador del plantel",
        "explanation": "COMET identifica a cada persona con un número estable: el vínculo es definitivo y sus "
                       "minutos, goles y tarjetas se cargan en la próxima sincronización de COMET.",
        "impact": "", "candidates": cands, "search": True, "recommended": any(c["recommended"] for c in cands)}]}


# ── apply ────────────────────────────────────────────────────────────────────

class ApplyError(ValueError):
    pass


def apply(club, issue_id: str, action: str, user, *, player_id: str | None = None,
          match_date: date | None = None) -> dict:
    from core.models import Player
    from exams.models import SyncIssue

    now = timezone.now()
    if issue_id.startswith("comet-"):
        from exams.models import CometPlayerLink

        if action != "link" or not player_id:
            raise ApplyError("Elige un jugador.")
        link = CometPlayerLink.objects.get(pk=issue_id.removeprefix("comet-"), integration__club=club)
        link.player = Player.objects.get(pk=player_id, category__club=club)
        link.match_method = CometPlayerLink.MATCH_MANUAL
        link.save(update_fields=["player", "match_method"])
        return {"message": f"«{link.person_name}» quedó vinculado a {_player_label(link.player)['name']}.",
                "closed": 1, "resync": []}

    issue = SyncIssue.objects.get(club=club, pk=issue_id)
    if action == "dismiss":
        note = {"jugador_no_encontrado": "No es del plantel", "nombre_ambiguo": "No es del plantel",
                "columna_nueva": "Columna ignorada"}.get(issue.kind, "Ignorado")
        issue.dismissed_at, issue.dismissed_by, issue.dismissed_note = now, user, note
        issue.save(update_fields=["dismissed_at", "dismissed_by", "dismissed_note"])
        return {"message": "Listo: no vuelve a aparecer.", "closed": 1, "resync": []}

    if action == "link":
        if issue.kind not in PLAYER_KINDS:
            raise ApplyError("Esta solución es para nombres de jugadores.")
        try:
            player = Player.objects.get(pk=player_id, category__club=club)
        except (Player.DoesNotExist, ValueError, TypeError):
            raise ApplyError("Elige un jugador del plantel.")
        from exams import sheet_aliases

        sheet_aliases.link(player, issue.subject)
        same = [i for i in SyncIssue.objects.filter(club=club, kind__in=PLAYER_KINDS, resolved_at__isnull=True)
                if akey(i.subject) == akey(issue.subject)]
        SyncIssue.objects.filter(pk__in=[i.pk for i in same]).update(resolved_at=now)
        queued = resync({i.source for i in same})
        return {"message": f"«{issue.subject}» quedó vinculado a {_player_label(player)['name']}. "
                           "Las filas se cargan en unos minutos.", "closed": len(same), "resync": queued}

    if action in ("assign_match", "not_a_match"):
        if issue.kind != "pestana_sin_partido":
            raise ApplyError("Esta solución es para pestañas de saltos.")
        if action == "assign_match" and not match_date:
            raise ApplyError("Elige el partido.")
        from exams.formativo_saltos_ingest import team_of_document
        from load_control.models import JumpTabMatch

        team = (team_of_document(issue.document) or "").replace("Sub ", "U")
        JumpTabMatch.objects.update_or_create(
            club=club, team=team, season=issue.first_seen_at.year, tab=issue.subject.strip(),
            defaults={"match_date": match_date if action == "assign_match" else None})
        issue.resolved_at = now
        issue.save(update_fields=["resolved_at"])
        queued = resync({issue.source}) if action == "assign_match" else []
        return {"message": ("Pestaña asignada al partido. Los saltos se cargan en unos minutos."
                            if action == "assign_match" else "Listo: queda marcada como «no es partido»."),
                "closed": 1, "resync": queued}
    raise ApplyError("Acción desconocida.")


def dismissed(club) -> list[dict]:
    from exams.models import SyncIssue

    return [{"id": str(i.id), "source": i.source, "kind_label": i.get_kind_display(), "subject": i.subject,
             "document": i.document, "note": i.dismissed_note,
             "by": (i.dismissed_by.get_full_name() or i.dismissed_by.username) if i.dismissed_by else "",
             "at": i.dismissed_at.isoformat()}
            for i in SyncIssue.objects.filter(club=club, dismissed_at__isnull=False)
            .select_related("dismissed_by").order_by("-dismissed_at")]


def restore(club, issue_id: str) -> None:
    from exams.models import SyncIssue

    SyncIssue.objects.filter(club=club, pk=issue_id).update(dismissed_at=None, dismissed_by=None, dismissed_note="")
