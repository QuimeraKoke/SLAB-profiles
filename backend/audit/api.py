"""Configuraciones › Registro: the club's change log, access log and backups.

Same audience as Usuarios (`auth.view_user`: the club's Administrador and
superusers). A club manager sees only his club; a superuser picks one.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta

from django.http import HttpResponse
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from api.scoping import get_membership

from .access import KIND_LABEL
from .models import AccessEvent, BackupRun, ChangeEvent

router = Router(tags=["registro"])
PAGE = 100

MODEL_LABEL = {
    "exams.ExamResult": "Evaluación", "exams.Episode": "Lesión", "exams.EpisodeNote": "Bitácora de lesión",
    "core.Player": "Jugador", "core.DailyNote": "Nota diaria", "core.KineDailyEntry": "Plan kinésico",
    "core.PlayerCallUp": "Convocatoria", "core.Contract": "Contrato", "attachments.Attachment": "Adjunto",
    "core.StaffMembership": "Accesos de usuario", "auth.User": "Usuario",
}
ACTION_LABEL = dict(ChangeEvent.ACTIONS)


def _club(request, club_id: str | None) -> str:
    u = request.user
    if not (u.is_superuser or u.has_perm("auth.view_user")):
        raise HttpError(403, "Solo los administradores del club ven el registro.")
    m = get_membership(u)
    if m is not None:
        return str(m.club_id)
    if not club_id:
        raise HttpError(400, "Elige un club.")
    return club_id


def _filtered(qs, club, desde, hasta, usuario, jugador):
    qs = qs.filter(club_id=club)
    tz = timezone.get_current_timezone()
    if desde:
        qs = qs.filter(at__gte=timezone.make_aware(datetime.combine(desde, time.min), tz))
    if hasta:
        qs = qs.filter(at__lt=timezone.make_aware(datetime.combine(hasta + timedelta(days=1), time.min), tz))
    if usuario:
        qs = qs.filter(actor_email__icontains=usuario)
    if jugador:
        qs = qs.filter(player_name__icontains=jugador) if len(jugador) != 36 else qs.filter(player_id=jugador)
    return qs


def _change_row(e: ChangeEvent) -> dict:
    return {
        "id": e.id, "at": e.at.isoformat(), "action": e.action, "action_label": ACTION_LABEL.get(e.action, e.action),
        "model": e.model, "model_label": MODEL_LABEL.get(e.model, e.model), "object_id": e.object_id,
        "object_label": e.object_label, "player_id": e.player_id, "player_name": e.player_name,
        "actor": e.actor_email or ("Sistema" if e.source == "sistema" else e.source),
        "source": e.source, "ip": e.ip, "changes": e.changes,
    }


def _access_row(e: AccessEvent) -> dict:
    return {
        "id": e.id, "at": e.at.isoformat(), "kind": e.kind, "kind_label": KIND_LABEL.get(e.kind, e.kind),
        "player_id": e.player_id, "player_name": e.player_name, "actor": e.actor_email,
        "ip": e.ip, "path": e.path, "detail": e.detail,
    }


def _page(qs, before: int | None):
    if before:
        qs = qs.filter(id__lt=before)
    rows = list(qs.order_by("-id")[:PAGE + 1])
    return rows[:PAGE], len(rows) > PAGE


@router.get("/changes")
def changes(request, club_id: str | None = None, desde: date | None = None, hasta: date | None = None,
            usuario: str = "", jugador: str = "", accion: str = "", before: int | None = None):
    club = _club(request, club_id)
    qs = _filtered(ChangeEvent.objects.all(), club, desde, hasta, usuario, jugador)
    if accion in ACTION_LABEL:
        qs = qs.filter(action=accion)
    rows, more = _page(qs, before)
    return {"rows": [_change_row(e) for e in rows], "more": more}


@router.get("/access")
def access(request, club_id: str | None = None, desde: date | None = None, hasta: date | None = None,
           usuario: str = "", jugador: str = "", before: int | None = None):
    club = _club(request, club_id)
    qs = _filtered(AccessEvent.objects.all(), club, desde, hasta, usuario, jugador)
    rows, more = _page(qs, before)
    return {"rows": [_access_row(e) for e in rows], "more": more}


def _csv(name: str, header: list[str], rows) -> HttpResponse:
    buf = io.StringIO()
    buf.write("﻿")  # Excel opens UTF-8 with accents correctly
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


def _local(dt_) -> str:
    return timezone.localtime(dt_).strftime("%Y-%m-%d %H:%M:%S")


@router.get("/changes.csv")
def changes_csv(request, club_id: str | None = None, desde: date | None = None, hasta: date | None = None,
                usuario: str = "", jugador: str = "", accion: str = ""):
    club = _club(request, club_id)
    qs = _filtered(ChangeEvent.objects.all(), club, desde, hasta, usuario, jugador)
    if accion in ACTION_LABEL:
        qs = qs.filter(action=accion)
    rows = ([_local(e.at), e.actor_email or e.source, ACTION_LABEL.get(e.action, e.action),
             MODEL_LABEL.get(e.model, e.model), e.object_label, e.player_name, e.object_id,
             _changes_text(e), e.ip] for e in qs.order_by("-id").iterator())
    return _csv("registro-cambios.csv",
                ["Fecha", "Usuario", "Acción", "Tipo", "Registro", "Jugador", "ID registro", "Cambios", "IP"], rows)


@router.get("/access.csv")
def access_csv(request, club_id: str | None = None, desde: date | None = None, hasta: date | None = None,
               usuario: str = "", jugador: str = ""):
    club = _club(request, club_id)
    qs = _filtered(AccessEvent.objects.all(), club, desde, hasta, usuario, jugador)
    rows = ([_local(e.at), e.actor_email, KIND_LABEL.get(e.kind, e.kind), e.player_name, e.path, e.ip]
            for e in qs.order_by("-id").iterator())
    return _csv("registro-accesos.csv", ["Fecha", "Usuario", "Acción", "Jugador", "Ruta", "IP"], rows)


def _changes_text(e: ChangeEvent) -> str:
    if e.action != ChangeEvent.UPDATE:
        return "" if e.action == ChangeEvent.CREATE else "Contenido al borrar: " + _short(e.changes)
    return " | ".join(f"{k}: {_short(v[0])} → {_short(v[1])}" for k, v in e.changes.items()
                      if isinstance(v, list) and len(v) == 2)


def _short(v) -> str:
    s = "—" if v in (None, "") else str(v)
    return s if len(s) <= 300 else s[:297] + "…"


@router.get("/backups")
def backups(request, club_id: str | None = None):
    _club(request, club_id)
    runs = list(BackupRun.objects.all()[:14])
    last_ok = BackupRun.objects.filter(status=BackupRun.OK).first()
    return {
        "last_ok": _backup_row(last_ok) if last_ok else None,
        "runs": [_backup_row(r) for r in runs],
        "retention": {"daily_days": 35, "monthly_months": 13},
    }


def _backup_row(r: BackupRun) -> dict:
    return {"started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status, "size_bytes": r.size_bytes, "tables": r.tables,
            "error": r.error[:300] if r.status != BackupRun.OK else ""}
