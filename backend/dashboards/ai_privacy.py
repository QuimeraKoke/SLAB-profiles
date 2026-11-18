"""Pseudonymisation of everything SLAB sends to the AI provider.

The model never needs to know WHO a player is to reason about his data, so
nothing that identifies a person leaves the server:

* players  → `JUG-042`, staff → `STAFF-03`, in free text (system prompt, chat
  history, what the user types, tool results) and in structured payloads;
* RUT, e-mails, photos, birth dates and internal UUIDs are removed;
* the model's tool calls arrive with tokens and are resolved back to the real
  player before the query runs (`unmask_obj`); its answer is rewritten with the
  real names before the user sees it (`unmask`).

The mapping lives only in memory for one request and is never sent or stored.

What this is NOT: anonymisation. The health data itself (injuries, check-in,
loads) still goes out — it is what the analysis is about — together with
quasi-identifiers like age, position and category. Re-identification by
someone who knows the squad stays possible; the provider's contract (no
training, retention) covers that part.

Limits, by design: a nickname the platform does not know ("el Chino") cannot
be recognised; a first name or surname alone is masked only when it is unique
in the club and written capitalised, to avoid swallowing ordinary words.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

# Keys whose values identify a person and add nothing to the analysis.
_DROP_KEYS = {"photo_url", "photo", "photo_src", "national_id", "rut", "date_of_birth",
              "fecha_nacimiento", "email", "correo", "phone", "telefono"}
_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_TOKEN = re.compile(r"\b(JUG|STAFF|NOM)-(\d{1,4})\b")
# Single-word names that are also ordinary Spanish words: never masked alone.
_COMMON_WORDS = {"angel", "paz", "luz", "mar", "cruz", "leon", "rosa", "flores", "campos", "santos",
                 "salas", "rios", "nieves", "soto", "vera", "ramos", "toro", "lobos", "bravo", "rey",
                 "pino", "luna", "sol", "rojo", "rojas", "blanco", "moreno", "cano", "castillo", "torres"}

_ACCENTS = {"a": "aáàäâ", "e": "eéèëê", "i": "iíìïî", "o": "oóòöô", "u": "uúùüû", "n": "nñ", "c": "cç"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").lower().split())


def _pattern(variant: str) -> str:
    """Accent-, case- and spacing-insensitive regex for a normalised name."""
    out = []
    for ch in variant:
        if ch == " ":
            out.append(r"\s+")
        elif ch in _ACCENTS:
            out.append(f"[{_ACCENTS[ch]}{_ACCENTS[ch].upper()}]")
        else:
            out.append(f"[{re.escape(ch)}{re.escape(ch.upper())}]" if ch.isalpha() else re.escape(ch))
    return "".join(out)


def _upper(ch: str) -> str:
    """Capital-only class for a name's first letter (accented forms too)."""
    return f"[{_ACCENTS.get(ch, ch).upper()}]"


def _alternation(variants: dict, to_pattern):
    if not variants:
        return None
    alts = "|".join(to_pattern(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)")


@dataclass
class _Person:
    token: str
    display: str
    full: list[str] = field(default_factory=list)     # multi-word variants, any case
    single: list[str] = field(default_factory=list)   # unique one-word variants, capitalised only
    ids: set[str] = field(default_factory=set)


class Pseudonymizer:
    def __init__(self, people: list[_Person]):
        self.people = people
        self.by_token = {p.token: p for p in people}
        self.by_id = {i: p.token for p in people for i in p.ids}
        # One alternation per kind, longest first; the match is normalised and
        # looked up, so 2.000+ variants cost one pass over the text.
        self._multi_map = {v: p.token for p in people for v in p.full}
        self._single_map = {v: p.token for p in people for v in p.single}
        self._multi = _alternation(self._multi_map, _pattern)
        self._single = _alternation(self._single_map, lambda v: _upper(v[0]) + _pattern(v[1:]))

    # ── building ──────────────────────────────────────────────────────────
    @classmethod
    def for_club(cls, club_id) -> "Pseudonymizer":
        from django.contrib.auth import get_user_model

        from core.models import Player

        players = list(Player.objects.filter(category__club_id=club_id)
                       .order_by("id").values("id", "first_name", "middle_name", "last_name", "second_last_name"))
        first_count, last_count = {}, {}
        for p in players:
            f, l = _norm(p["first_name"]), _norm(p["last_name"])
            first_count[f] = first_count.get(f, 0) + 1
            last_count[l] = last_count.get(l, 0) + 1

        people = []
        for i, p in enumerate(players, 1):
            f, m, l, s = (_norm(p[k]) for k in ("first_name", "middle_name", "last_name", "second_last_name"))
            full = {x for x in (f"{f} {l}", f"{f} {m} {l}", f"{f} {l} {s}", f"{f} {m} {l} {s}",
                                f"{l} {s}", f"{l}, {f}") if x.count(" ") >= 1 and "  " not in x
                    and not x.endswith(" ") and not x.startswith(" ")}
            single = {x for x in (l, f)
                      if first_count.get(x, 0) + last_count.get(x, 0) == 1
                      and len(x) >= 4 and " " not in x and x not in _COMMON_WORDS}
            people.append(_Person(token=f"JUG-{i:03d}",
                                  display=" ".join(x for x in (p["first_name"], p["last_name"]) if x).strip(),
                                  full=sorted(full), single=sorted(single), ids={str(p["id"])}))

        # A first name or surname shared by several players identifies no one
        # alone but still narrows it down: a reversible placeholder (NOM-07)
        # hides it; unmasked, a tool gets the word back and lists candidates.
        originals = {}
        for p in players:
            for k in ("first_name", "last_name"):
                originals.setdefault(_norm(p[k]), (p[k] or "").strip())
        shared = sorted(w for w in set(first_count) | set(last_count)
                        if first_count.get(w, 0) + last_count.get(w, 0) > 1 and len(w) >= 4
                        and " " not in w and w not in _COMMON_WORDS)
        for k, w in enumerate(shared, 1):
            people.append(_Person(token=f"NOM-{k:03d}", display=originals.get(w, w), single=[w]))

        User = get_user_model()
        staff = User.objects.filter(staff_membership__club_id=club_id).order_by("id")
        for j, u in enumerate(staff, 1):
            name = _norm(f"{u.first_name} {u.last_name}")
            people.append(_Person(token=f"STAFF-{j:02d}", display=(f"{u.first_name} {u.last_name}".strip() or u.email),
                                  full=[name] if " " in name else [], ids={str(u.pk), (u.email or "").lower()}))
        return cls(people)

    @classmethod
    def for_player(cls, player) -> "Pseudonymizer":
        cat = getattr(player, "category", None)
        return cls.for_club(cat.club_id) if cat is not None else cls([])

    @classmethod
    def for_category(cls, category) -> "Pseudonymizer":
        return cls.for_club(category.club_id) if category is not None else cls([])

    # ── outgoing ──────────────────────────────────────────────────────────
    def mask(self, text: str) -> str:
        if not text:
            return text
        text = _EMAIL.sub(lambda m: self.by_id.get(m.group(0).lower(), "[correo]"), text)
        text = _RUT.sub("[RUT]", text)
        if self._multi is not None:
            text = self._multi.sub(lambda m: self._multi_map.get(_norm(m.group(0)), m.group(0)), text)
        if self._single is not None:
            text = self._single.sub(lambda m: self._single_map.get(_norm(m.group(0)), m.group(0)), text)
        return text

    def mask_obj(self, obj):
        if isinstance(obj, str):
            if _UUID.match(obj):
                return self.by_id.get(obj.lower(), self.by_id.get(obj, obj))
            return self.mask(obj)
        if isinstance(obj, list):
            return [self.mask_obj(x) for x in obj]
        if isinstance(obj, tuple):
            return tuple(self.mask_obj(x) for x in obj)
        if isinstance(obj, dict):
            out = {}
            # {"first_name": "Ana", "last_name": "Rojas"} → {"jugador": "JUG-007"}
            if "first_name" in obj and "last_name" in obj:
                ident = str(obj.get("id") or obj.get("player_id") or "")
                tok = self.by_id.get(ident) or self.mask(f"{obj['first_name']} {obj['last_name']}".strip())
                out["jugador"] = tok
            for k, v in obj.items():
                if k in _DROP_KEYS or k in ("first_name", "last_name", "middle_name", "second_last_name"):
                    continue
                out[k] = self.mask_obj(v)
            return out
        return obj

    def mask_messages(self, messages: list) -> list:
        """Chat turns: plain-dict content (str or blocks) is masked; SDK
        objects echoed from a previous response already carry tokens only."""
        out = []
        for m in messages:
            if not isinstance(m, dict):
                out.append(m)
                continue
            c = m.get("content")
            if isinstance(c, str):
                c = self.mask(c)
            elif isinstance(c, list):
                c = [self._mask_block(b) for b in c]
            out.append({**m, "content": c})
        return out

    def _mask_block(self, b):
        if not isinstance(b, dict):
            return b
        b = dict(b)
        if isinstance(b.get("text"), str):
            b["text"] = self.mask(b["text"])
        if isinstance(b.get("content"), str):  # tool_result
            b["content"] = self.mask(b["content"])
        return b

    # ── incoming ──────────────────────────────────────────────────────────
    def unmask(self, text: str) -> str:
        if not text:
            return text

        def sub(m):
            # Tolerate the model dropping/adding leading zeros (JUG-42 / JUG-042).
            kind, n = m.group(1), int(m.group(2))
            p = self.by_token.get(f"{kind}-{n:02d}" if kind == "STAFF" else f"{kind}-{n:03d}")
            return p.display if p else m.group(0)
        return _TOKEN.sub(sub, text)

    def unmask_obj(self, obj):
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, list):
            return [self.unmask_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.unmask_obj(v) for k, v in obj.items()}
        return obj


class _Identity:
    """No-op stand-in when pseudonymisation is switched off (AI_PSEUDONYMIZE=False)."""

    def mask(self, t):
        return t

    def unmask(self, t):
        return t

    def mask_obj(self, o):
        return o

    def unmask_obj(self, o):
        return o

    def mask_messages(self, m):
        return m


def enabled() -> bool:
    return bool(getattr(settings, "AI_PSEUDONYMIZE", True))


class AiDisabled(Exception):
    """The club switched the AI off (Club.ai_enabled = False)."""


DISABLED_MESSAGE = ("La IA está desactivada para este club. Un administrador puede activarla en "
                    "Administración › Privacidad e IA.")


def club_ai_enabled(club_id) -> bool:
    from core.models import Club
    return bool(Club.objects.filter(pk=club_id).values_list("ai_enabled", flat=True).first())


def open_session(feature: str, *, model: str = "", player=None, category=None, club_id=None,
                 detail: str = ""):
    """The one gate in front of every request to the AI provider.

    1. The club must have the AI switched on, else `AiDisabled`.
    2. Builds the club's pseudonymizer; any failure raises, and callers fail
       closed (no call is made).
    3. Records the send in the audit log (audit.AccessEvent kind "ia": who,
       for which player, which feature). If it cannot be recorded it is not
       sent either: there is no AI call without a trace.
    """
    if club_id is None:
        cat = getattr(player, "category", None) if player is not None else category
        club_id = getattr(cat, "club_id", None)
    if not club_id:
        raise RuntimeError("AI call without a club: refusing to send unscoped data.")
    if not club_ai_enabled(club_id):
        raise AiDisabled()
    pz = Pseudonymizer.for_club(club_id) if enabled() else _Identity()
    _record_send(feature, club_id, player, model, detail)
    return pz


def _record_send(feature, club_id, player, model, detail):
    from audit import context
    from audit.models import AccessEvent

    a = context.current()
    parts = [feature, detail, model, "seudonimizado" if enabled() else "SIN seudonimizar"]
    with transaction.atomic():  # savepoint: a failure never poisons the caller's transaction
        AccessEvent.objects.create(
            kind="ia", club_id=str(club_id),
            player_id=str(player.pk) if player is not None else "",
            player_name=" ".join(x for x in (player.first_name, player.last_name) if x)[:200]
            if player is not None else "",
            actor_id=a.user_id, actor_email=a.email or "", ip=a.ip or "",
            detail=" · ".join(p for p in parts if p)[:300],
        )


def for_club(club_id):
    return Pseudonymizer.for_club(club_id) if enabled() and club_id else _Identity()


def for_player(player):
    return Pseudonymizer.for_player(player) if enabled() else _Identity()


def for_category(category):
    return Pseudonymizer.for_category(category) if enabled() else _Identity()


PROMPT_NOTE = (
    "Privacidad: los jugadores aparecen con un código (p. ej. JUG-042) y el staff como STAFF-03. "
    "Refiérete a ellos SIEMPRE con ese código exacto, nunca inventes nombres; el sistema lo "
    "reemplaza por el nombre real al mostrar tu respuesta. Para consultar a un jugador con las "
    "herramientas, usa su código."
)
