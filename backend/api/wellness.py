"""Shared wellness scoring, whatever form the category actually fills in.

The score is a mean of items normalized by each field's configured `max`,
because the form mixes scales — in Primer Equipo recuperación is 1–10 and the
other four are 1–5. Used by the Equipo roster, the Centro de mando KPI and the
Daily so the three agree.

Which template IS the wellness form, and which of its fields make up the score,
are **declared by the template** and not hardcoded here:

    config_schema = {
        "fields": [...],
        "wellness": {
            "role": "checkin",                  # or "checkout"
            "items": [["sueno", "Sueño"], ...],  # what the score averages
            "dimensions": [["sueno", "Sueño"]],  # chips on the KPI
        },
    }

Two reasons it lives in `config_schema` rather than a model column. It needs no
migration, and it is **versioned with the schema** — when the club changes the
form, the new template version carries its own items instead of the old ones
silently applying.

And it had to stop being hardcoded. The Formativo fills a *different* form:
calidad de sueño, fatiga, daño muscular, estrés, ánimo — where Primer Equipo
has recuperación, cuerpo, energía, ánimo, sueño. They overlap on two items and
diverge on the rest, so one slug and one item list cannot serve both, and
pinning the surfaces to `checkin_fisico` is why the Formativo's 65.000 check-ins
would have imported into a screen that never looks at them.

`checkin_fisico` needs no change: a template with no `wellness` block falls back
to the constants below, which are exactly what it declared implicitly.
"""

from __future__ import annotations

from exams.models import ExamResult, ExamTemplate

WELLNESS_SLUG = "checkin_fisico"
# The legacy declaration, kept as the fallback for a template that carries no
# `wellness` block — which is every template that existed before it.
ITEMS = [
    ("recuperacion", "Recuperación"),
    ("cuerpo", "Cuerpo"),
    ("energia", "Energía"),
    ("animo", "Ánimo"),
    ("sueno", "Sueño"),
]
DIMENSIONS = [("sueno", "Sueño"), ("energia", "Energía"), ("animo", "Ánimo")]

ROLE_CHECKIN = "checkin"
ROLE_CHECKOUT = "checkout"


def _bloque(template) -> dict:
    return ((template.config_schema or {}).get("wellness") or {}) if template else {}


def templates_for(category, *, role: str = ROLE_CHECKIN) -> list:
    """The category's wellness templates for `role`, newest version first.

    Resolution order, and the fallback matters: a category that declares
    nothing still gets `checkin_fisico`, so every surface keeps working for the
    clubs that were live before templates could declare a role.

    ⚠️ Every step is scoped to the category's own CLUB. The last-resort lookup
    used to be a bare `slug=checkin_fisico` across the whole database, so a
    category with no template linked resolved to *another club's* form — the
    four femenino categories were picking up Selección Chilena's. Nothing was
    miscounted, because every caller also filters by `player_id__in`, but the
    next reader that does not would be reading another club's data with no
    error to notice.
    """
    club_id = getattr(getattr(category, "club", None), "id", None)
    declarados = [
        t for t in ExamTemplate.objects.filter(
            applicable_categories=category, is_active_version=True)
        if _bloque(t).get("role", ROLE_CHECKIN) == role and _bloque(t)
    ]
    if declarados:
        return declarados
    if role != ROLE_CHECKIN:
        return []
    propias = ExamTemplate.objects.filter(slug=WELLNESS_SLUG,
                                          applicable_categories=category)
    if propias:
        return list(propias)
    if club_id is None:
        return []
    return list(ExamTemplate.objects.filter(slug=WELLNESS_SLUG,
                                            department__club_id=club_id))


def items_for(category, *, role: str = ROLE_CHECKIN) -> list[tuple[str, str]]:
    """The (key, label) pairs whose mean is this category's wellness score."""
    for t in templates_for(category, role=role):
        items = _bloque(t).get("items")
        if items:
            return [(k, l) for k, l in items]
    return list(ITEMS) if role == ROLE_CHECKIN else []


def dimensions_for(category, *, role: str = ROLE_CHECKIN) -> list[tuple[str, str]]:
    for t in templates_for(category, role=role):
        dims = _bloque(t).get("dimensions")
        if dims:
            return [(k, l) for k, l in dims]
    return list(DIMENSIONS) if role == ROLE_CHECKIN else []


def _claves(category, role) -> set[str]:
    """Score items PLUS declared dimensions.

    Dimensions have to be in here. `dimension_pct` returns None when the key has
    no max, so a dimension that is not also a score item used to render nothing
    at all — the chip just wasn't there, with no error to notice.
    """
    return {k for k, _ in items_for(category, role=role)} | {
        k for k, _ in dimensions_for(category, role=role)}


def field_max(category, *, role: str = ROLE_CHECKIN) -> dict[str, float]:
    """field_key → configured max, for the items that make up the score.

    Read from the template rather than assumed, because the scales are not
    uniform: 1–10 for recuperación against 1–5 for the rest.
    """
    claves = _claves(category, role)
    out: dict[str, float] = {}
    for t in templates_for(category, role=role):
        for f in ((t.config_schema or {}).get("fields") or []):
            k = f.get("key")
            if k in claves and k not in out:
                out[k] = float(f.get("max") or 10)
    return out


def field_min(category, *, role: str = ROLE_CHECKIN) -> dict[str, float]:
    """field_key → configured min. Needed to MIRROR an inverted item.

    Inverting as `1 − v/max` looks right and is not: on a 1–5 scale the best
    possible answer (1) would score 0.8 while a non-inverted item's best (5)
    scores 1.0, so a perfect Formativo check-in capped at 88. Mirroring the
    value inside its own scale first — `max + min − v` — puts both endpoints in
    the same place, and leaves the non-inverted path (and Primer Equipo's
    numbers) exactly as they were.
    """
    claves = _claves(category, role)
    out: dict[str, float] = {}
    for t in templates_for(category, role=role):
        for f in ((t.config_schema or {}).get("fields") or []):
            k = f.get("key")
            if k in claves and k not in out:
                out[k] = float(f.get("min") or 0)
    return out


def score(data: dict, fmax: dict[str, float],
          items: list[tuple[str, str]] | None = None,
          inverted: set[str] | frozenset[str] = frozenset(),
          fmin: dict[str, float] | None = None) -> int | None:
    """0–100 wellness for one response: mean of (value ÷ field-max).

    `items` defaults to the legacy list so existing callers are unchanged; pass
    `items_for(category)` for a category whose form declares its own.

    ⚠️ `inverted` is not optional for the Formativo. Its form asks three items
    where a HIGH answer is bad — fatiga, estrés and daño muscular — against
    Primer Equipo's five where high is always good. Averaging them raw makes a
    wrecked player score 90 and a fresh one score 30, and the number still
    looks like a wellness score. Use `inverted_for(category)`.
    """
    fracs = []
    for key, _ in (items or ITEMS):
        v = _coerce((data or {}).get(key))
        mx = fmax.get(key)
        if v is None or not mx:
            continue
        if key in inverted:
            v = mx + (fmin or {}).get(key, 0) - v      # mirror inside the scale
        fracs.append(min(1.0, max(0.0, v / mx)))
    return round(sum(fracs) / len(fracs) * 100) if fracs else None


def inverted_for(category, *, role: str = ROLE_CHECKIN) -> frozenset[str]:
    """Items where a HIGH answer means WORSE, per the template's declaration."""
    for t in templates_for(category, role=role):
        bloque = _bloque(t)
        if bloque.get("items"):
            return frozenset(bloque.get("inverted") or ())
    return frozenset()


def score_for(category, data: dict, *, role: str = ROLE_CHECKIN) -> int | None:
    """The whole thing for one category, so callers cannot forget a piece.

    Three lookups have to agree — items, their maxima and which are inverted —
    and a caller that gets `items` right and `inverted` wrong produces a score
    that is exactly backwards. Prefer this over calling `score` directly.
    """
    return score(data, field_max(category, role=role),
                 items_for(category, role=role),
                 inverted_for(category, role=role),
                 field_min(category, role=role))


def dimension_pct(data: dict, key: str, fmax: dict[str, float],
                  inverted: set[str] | frozenset[str] = frozenset(),
                  fmin: dict[str, float] | None = None) -> int | None:
    v = _coerce((data or {}).get(key))
    mx = fmax.get(key)
    if v is None or not mx:
        return None
    if key in inverted:
        v = mx + (fmin or {}).get(key, 0) - v
    return round(min(1.0, max(0.0, v / mx)) * 100)


def dimension_pct_for(category, data: dict, key: str, *,
                      role: str = ROLE_CHECKIN) -> int | None:
    """One dimension chip, resolved. Same reason as `score_for`: a dimension
    read without its `inverted` flag renders "Fatiga 90%" for a wrecked squad.
    """
    return dimension_pct(data, key, field_max(category, role=role),
                         inverted_for(category, role=role),
                         field_min(category, role=role))


def roles_for(category) -> list[str]:
    """Which wellness roles this category actually has a template for.

    The Formativo fills a Check-OUT and Primer Equipo does not, so the surfaces
    that show one have to ask rather than assume. Returns `["checkin"]` or
    `["checkin", "checkout"]`, in that order.
    """
    return [r for r in (ROLE_CHECKIN, ROLE_CHECKOUT) if templates_for(category, role=r)]


def recent_by_player(category, player_ids: list, limit: int = 12, since=None,
                     with_dates: bool = False, role: str = ROLE_CHECKIN) -> dict:
    """{player_id: [result_data, ...]} newest-first, for the category's
    wellness responses (whichever template it declares). With `since` (an aware datetime) it returns every
    reading on/after that instant — a date window; otherwise caps to `limit`.
    With `with_dates=True` each item is a `(recorded_at, result_data)` tuple."""
    tids = [t.id for t in templates_for(category, role=role)]
    out: dict = {}
    if not tids:
        return out
    qs = ExamResult.objects.filter(player_id__in=player_ids, template_id__in=tids)
    if since is not None:
        qs = qs.filter(recorded_at__gte=since)
    rows = qs.order_by("player_id", "-recorded_at").values_list(
        "player_id", "recorded_at", "result_data",
    )
    for pid, rec, data in rows:
        bucket = out.setdefault(pid, [])
        if since is not None or len(bucket) < limit:
            bucket.append((rec, data or {}) if with_dates else (data or {}))
    return out


def _coerce(raw):
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_date(raw):
    """ISO date or None (bad/blank input tolerated)."""
    from datetime import date as _date

    try:
        return _date.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


def build_adherence(category, date_from: str = "", date_to: str = "",
                    role: str = ROLE_CHECKIN) -> dict:
    """Check-in (or check-out) adherence over a window. **Informative only.**

    The denominator is self-calibrated = days on which *any* active player
    logged a check-in (a proxy for "a response was expected that day"), so rest
    days with no expected check-in don't drag the %. Injured players are
    flagged so the UI can separate them. Default window: the last 4 weeks.
    """
    from datetime import timedelta

    from django.utils import timezone

    from core.models import Player

    today = timezone.localdate()
    d_to = _parse_date(date_to) or today
    d_from = _parse_date(date_from) or (d_to - timedelta(days=27))
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    players = list(
        Player.objects.filter(category=category, is_active=True)
        .select_related("position").order_by("last_name", "first_name")
    )
    pids = [p.id for p in players]
    tids = [t.id for t in templates_for(category, role=role)]

    responded: dict = {}          # player_id -> set(date ISO)
    activity_days: set = set()    # days ANY player responded → the denominator
    if tids and pids:
        rows = ExamResult.objects.filter(
            player_id__in=pids, template_id__in=tids,
            recorded_at__date__gte=d_from, recorded_at__date__lte=d_to,
        ).values_list("player_id", "recorded_at")
        for pid, rec in rows:
            di = timezone.localtime(rec).date().isoformat()
            responded.setdefault(pid, set()).add(di)
            activity_days.add(di)

    days = sorted(activity_days)
    expected_days = len(days)

    player_rows = []
    total_responded = 0
    for p in players:
        got = responded.get(p.id, set())
        k = len(got & activity_days)
        total_responded += k
        player_rows.append({
            "player_id": str(p.id),
            "name": f"{p.first_name} {p.last_name}".strip(),
            "position": p.position.abbreviation if p.position else None,
            "injured": p.status != Player.STATUS_AVAILABLE,
            "responded_days": k,
            "expected_days": expected_days,
            "pct": round(k / expected_days * 100) if expected_days else None,
            "grid": {d: (d in got) for d in days},
        })

    denom = expected_days * len(players)
    return {
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "activity_days": days,
        "squad": {
            "players": len(players),
            "expected_days": expected_days,
            "responded": total_responded,
            "expected": denom,
            "pct": round(total_responded / denom * 100) if denom else None,
        },
        "players": player_rows,
    }
