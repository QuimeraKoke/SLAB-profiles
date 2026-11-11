"""Names the club's sheets write for a player, linked by hand from
Datos › Fuentes › Problemas ("Vincular a un jugador").

Stored as `core.PlayerAlias(kind=nickname, source=manual, value=<name as the
sheet writes it>)`. Every sheet sync checks this table BEFORE its own matching
(birth date, surnames, cohort…): a person said who it is, which beats any
heuristic. A written name linked to two different players is ignored — the
matcher's own answer (usually "ambiguo") stands.
"""
from __future__ import annotations

import re
import unicodedata


def key(text: object) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip().upper()


def load(club) -> dict[str, object]:
    """{normalized written name: Player} for the club."""
    from core.models import PlayerAlias

    out: dict[str, object] = {}
    clash: set[str] = set()
    for a in (PlayerAlias.objects.filter(kind=PlayerAlias.KIND_NICKNAME, player__category__club=club)
              .select_related("player", "player__category")):
        k = key(a.value)
        if not k:
            continue
        if k in out and out[k].pk != a.player_id:
            clash.add(k)
        out[k] = a.player
    for k in clash:
        out.pop(k, None)
    return out


def link(player, written: str) -> bool:
    """Save the link. True if it is new."""
    from core.models import PlayerAlias

    _, created = PlayerAlias.objects.get_or_create(
        player=player, kind=PlayerAlias.KIND_NICKNAME, source=PlayerAlias.SOURCE_MANUAL,
        value=str(written).strip()[:120])
    return created
