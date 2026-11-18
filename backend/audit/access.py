"""Access log: who opened a player's record or downloaded a report.

The middleware resets the audit context per request and, after a successful
GET, matches the path against the player-scoped endpoints below. A record
view fans out into many API calls (detail, results, widgets…), so views are
de-duplicated per user, player and kind for 30 minutes; downloads are logged
every time.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import context
from .models import AccessEvent

logger = logging.getLogger(__name__)

_UUID = r"[0-9a-fA-F-]{36}"
VIEW_WINDOW = timedelta(minutes=30)

# (regex, kind, how to find the player, is a download)
_ROUTES = [
    (rf"^/api/players/(?P<player>{_UUID})/(ficha\.pdf|triage\.docx|departments/[^/]+/report\.docx)$", "descarga", "player", True),
    (rf"^/api/players/(?P<player>{_UUID})/contracts$", "contratos", "player", False),
    (rf"^/api/players/(?P<player>{_UUID})/(episodes)$", "lesiones", "player", False),
    (rf"^/api/players/(?P<player>{_UUID})/daily-notes$", "notas", "player", False),
    (rf"^/api/players/(?P<player>{_UUID})(/(results|summary|views|triage|resumen-slab|resumen-narrative|alerts|goals|physical-context|templates))?$", "ficha", "player", False),
    (rf"^/api/episodes/(?P<episode>{_UUID})(/(notes|results))?$", "lesiones", "episode", False),
    (rf"^/api/attachments/(?P<attachment>{_UUID})/(download|signed-url)$", "adjunto", "attachment", True),
    (r"^/api/(export/[^/]+\.(pdf|xlsx)|daily-report\.pdf|reports/[^/]+/team\.docx)$", "exportacion", None, True),
]
_COMPILED = [(re.compile(p), k, how, dl) for p, k, how, dl in _ROUTES]

KIND_LABEL = {
    "ficha": "Abrió la ficha", "lesiones": "Vio lesiones", "notas": "Vio notas diarias",
    "contratos": "Vio contratos", "adjunto": "Descargó un adjunto", "descarga": "Descargó un informe",
    "exportacion": "Exportó datos del plantel", "ingreso": "Inició sesión",
}


def client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", ""))[:64]


def _resolve_player(how, groups):
    from core.models import Player
    if how == "player":
        return Player.objects.select_related("category").filter(pk=groups["player"]).first()
    if how == "episode":
        from exams.models import Episode
        ep = Episode.objects.select_related("player__category").filter(pk=groups["episode"]).first()
        return ep.player if ep else None
    if how == "attachment":
        from attachments.models import Attachment
        from .tracking import _player_of
        att = Attachment.objects.filter(pk=groups["attachment"]).first()
        return _player_of("attachments.Attachment", att)[0] if att else None
    return None


def log_access(kind: str, *, player=None, path: str = "", detail: str = "", download: bool = True) -> None:
    a = context.current()
    if a.user_id is None:
        return
    pid = str(player.pk) if player is not None else ""
    if not download and AccessEvent.objects.filter(
            actor_id=a.user_id, player_id=pid, kind=kind, at__gte=timezone.now() - VIEW_WINDOW).exists():
        return
    club = str(player.category.club_id) if player is not None and player.category_id else (a.club_id or "")
    AccessEvent.objects.create(
        kind=kind, club_id=club, player_id=pid,
        player_name=" ".join(x for x in (player.first_name, player.last_name) if x)[:200] if player else "",
        actor_id=a.user_id, actor_email=a.email, ip=a.ip, path=path[:300], detail=detail[:300],
    )


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        context.reset(ip=client_ip(request))
        user = getattr(request, "user", None)
        if request.path.startswith("/admin/") and user is not None and user.is_authenticated:
            context.set_user(user)  # Django admin: session auth, not the JWT
        response = self.get_response(request)
        if request.method == "GET" and 200 <= response.status_code < 300:
            try:
                with transaction.atomic():
                    self._log(request)
            except Exception:  # noqa: BLE001 — never break the response
                logger.exception("audit: no se pudo registrar el acceso")
        context.reset()
        return response

    def _log(self, request):
        path = request.path
        for rx, kind, how, download in _COMPILED:
            m = rx.match(path)
            if not m:
                continue
            player = _resolve_player(how, m.groupdict()) if how else None
            if how and player is None:
                return
            log_access(kind, player=player, path=path, detail=request.META.get("QUERY_STRING", ""),
                       download=download)
            return
