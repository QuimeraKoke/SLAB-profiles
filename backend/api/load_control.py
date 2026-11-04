"""Control de carga · planning API (PLAN_CONTROL_CARGA.md §8.4).

A ninja Router mounted at /load-control by `api/routers.py`. The logic lives in
`load_control.planning`; this module only resolves who may see which team,
parses input and maps domain errors to HTTP. Permissions are the models' own
(`load_control.view_microcycle` to see, `add_` / `change_` to plan), granted to
the role groups like every other operational model (`seed_role_groups`).
"""
from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from ninja import Router, Schema
from ninja.errors import HttpError

from api.scoping import get_membership, scope_categories
from core.models import Category
from load_control import planning
from load_control.models import Microcycle
from load_control.services import open_microcycle

router = Router(tags=["control-de-carga"])

PERM_VIEW = "load_control.view_microcycle"
PERM_ADD = "load_control.add_microcycle"
PERM_CHANGE = "load_control.change_microcycle"


def _require(request, *codenames: str):
    user = request.user
    if not user or not user.is_authenticated:
        raise HttpError(401, "No autenticado.")
    if user.is_superuser:
        return
    for codename in codenames:
        if not user.has_perm(codename):
            raise HttpError(403, f"No tienes permiso para esta acción ({codename}).")


def _team(request, category_id: str, season: int | None) -> planning.Team:
    membership = get_membership(request.user)
    category = (scope_categories(Category.objects.select_related("club"), membership)
                .filter(pk=category_id).first())
    if category is None:
        raise HttpError(404, "Categoría no encontrada.")
    team = planning.team_for(category, season)
    if team is None:
        raise HttpError(404, f"{category.name} no compite en un tramo esta temporada.")
    return team


def _week_key(request, key: str) -> Microcycle | None:
    """`<YYYY-MM-DD>_<category_id>` → that day's calendar week of the
    category's team, planned or not (`load_control.week`). None if `key` is
    not one (a planned week's id)."""
    day_s, _, category_id = key.partition("_")
    try:
        day = date.fromisoformat(day_s)
    except ValueError:
        return None
    from load_control.week import week_for

    team = _team(request, category_id, day.year)
    return week_for(team, day)


def _microcycle(request, microcycle_id: str) -> Microcycle:
    week = _week_key(request, microcycle_id)
    if week is not None:
        return week
    membership = get_membership(request.user)
    qs = Microcycle.objects.select_related("club", "bracket", "copied_from")
    if membership is not None:
        qs = qs.filter(club=membership.club)
    mc = qs.filter(pk=microcycle_id).first()
    if mc is None:
        raise HttpError(404, "Semana no encontrada.")
    return mc


def _bad_request(exc: ValidationError):
    raise HttpError(400, "; ".join(exc.messages))


class DayIn(Schema):
    date: date
    kind: str
    targets_pct: dict[str, float | None] = {}


class CreateIn(Schema):
    category_id: str
    season: int | None = None
    start_date: date
    end_date: date
    number: int
    kind: str = ""
    copy_from_id: str | None = None
    days: list[DayIn] | None = None


class UpdateIn(Schema):
    kind: str | None = None
    notes: str | None = None
    days: list[DayIn] | None = None


@router.get("/team")
def team_view(request, category_id: str, season: int | None = None):
    """The team the selected category competes in this season (U20, U18…) and
    its microcycles, newest first."""
    _require(request, PERM_VIEW)
    team = _team(request, category_id, season)
    microcycles = Microcycle.objects.filter(club=team.club, season=team.season,
                                            bracket=team.bracket).order_by("-start_date")
    return {"season": team.season, "label": team.label, "bracket_id": str(team.bracket.id),
            "bracket": team.bracket.name, "categories": [c.name for c in team.categories()],
            "microcycles": [planning.serialize_summary(m) for m in microcycles]}


@router.get("/microcycles/suggestion")
def suggestion(request, category_id: str, season: int | None = None,
               start_date: date | None = None):
    """What a new microcycle would look like (not saved): dates, MICRO number
    and TIPO from the GPS sheet, match days from fixtures + friendlies, and
    the microcycle its % would be copied from."""
    _require(request, PERM_VIEW, PERM_ADD)
    team = _team(request, category_id, season)
    return planning.serialize_suggestion(team, planning.suggest(team, start_date))


@router.post("/microcycles")
def create_microcycle(request, payload: CreateIn):
    _require(request, PERM_VIEW, PERM_ADD)
    team = _team(request, payload.category_id, payload.season)
    copy_from = _microcycle(request, payload.copy_from_id) if payload.copy_from_id else None
    try:
        mc = planning.create(
            team, start=payload.start_date, end=payload.end_date, number=payload.number,
            kind=payload.kind, copy_from=copy_from, user=request.user,
            days=[d.dict() for d in payload.days] if payload.days else None)
    except ValidationError as exc:
        _bad_request(exc)
    return planning.serialize(mc)


@router.get("/microcycles/{microcycle_id}")
def microcycle_detail(request, microcycle_id: str):
    _require(request, PERM_VIEW)
    return planning.serialize(_microcycle(request, microcycle_id))


@router.put("/microcycles/{microcycle_id}")
def update_microcycle(request, microcycle_id: str, payload: UpdateIn):
    _require(request, PERM_VIEW, PERM_CHANGE)
    mc = _microcycle(request, microcycle_id)
    try:
        planning.update(mc, kind=payload.kind, notes=payload.notes,
                        days=[d.dict() for d in payload.days] if payload.days is not None else None)
    except ValidationError as exc:
        _bad_request(exc)
    mc.refresh_from_db()
    return planning.serialize(mc)


@router.post("/microcycles/{microcycle_id}/open")
def open_view(request, microcycle_id: str):
    """Freeze the match reference and open the microcycle."""
    _require(request, PERM_VIEW, PERM_CHANGE)
    mc = _microcycle(request, microcycle_id)
    try:
        open_microcycle(mc)
    except ValidationError as exc:
        _bad_request(exc)
    return planning.serialize(mc)


@router.get("/microcycles/{microcycle_id}/evaluation")
def evaluation_view(request, microcycle_id: str, day: date | None = None,
                    sparring: bool | None = None, matches: bool = True):
    """Plan vs real GPS for one day (`day`) or the microcycle so far: per player
    and metric target / real / Δ% / band, the squad summary, the day's alerts
    and what data was used. See `load_control.evaluation`."""
    from load_control.evaluation import evaluate

    _require(request, PERM_VIEW)
    mc = _microcycle(request, microcycle_id)
    try:
        return evaluate(mc, day=day, include_sparring=sparring, include_matches=matches)
    except ValueError as exc:
        raise HttpError(400, str(exc))


@router.get("/microcycles/{microcycle_id}/wellness")
def wellness_view(request, microcycle_id: str, day: date | None = None,
                  player_id: str | None = None):
    """Check-in / out: the microcycle day by day (group or one player) and, for
    `day`, low wellness and pain, everyone's answers and who did not answer.
    See `load_control.wellness`."""
    from load_control.wellness import wellness

    _require(request, PERM_VIEW)
    mc = _microcycle(request, microcycle_id)
    try:
        return wellness(mc, day=day, player_id=player_id)
    except ValueError as exc:
        raise HttpError(400, str(exc))


@router.get("/microcycles/{microcycle_id}/availability")
def availability_view(request, microcycle_id: str, day: date | None = None):
    """Kinesia y lesiones: who is not available, since when and until when, and
    the season's injury history. See `load_control.availability`."""
    from load_control.availability import availability

    _require(request, PERM_VIEW)
    mc = _microcycle(request, microcycle_id)
    try:
        return availability(mc, day=day)
    except ValueError as exc:
        raise HttpError(400, str(exc))


@router.get("/microcycles/{microcycle_id}/participation")
def participation_view(request, microcycle_id: str, scope: str = "microcycle"):
    """Minutos y asistencia for the microcycle or the season so far.
    See `load_control.participation`."""
    from load_control.participation import participation

    _require(request, PERM_VIEW)
    mc = _microcycle(request, microcycle_id)
    try:
        return participation(mc, scope=scope)
    except ValueError as exc:
        raise HttpError(400, str(exc))


@router.get("/microcycles/{microcycle_id}/fatigue")
def fatigue_view(request, microcycle_id: str, match_date: date | None = None,
                 player_id: str | None = None):
    """Fatiga post-partido: PRE/POST of a match of the week, each player's
    basal and the squad's accumulated fatigue. See `load_control.fatigue`."""
    from load_control.fatigue import fatigue

    _require(request, PERM_VIEW)
    mc = _microcycle(request, microcycle_id)
    try:
        return fatigue(mc, match_date=match_date, player_id=player_id)
    except ValueError as exc:
        raise HttpError(400, str(exc))


@router.get("/photos")
def photos_view(request, category_id: str):
    """Photo (or initials) of every player of the category, call-ups included,
    keyed by id: one request feeds every name the Centro de mando shows."""
    from api.scoping import players_in_category

    _require(request, PERM_VIEW)
    membership = get_membership(request.user)
    category = (scope_categories(Category.objects.select_related("club"), membership)
                .filter(pk=category_id).first())
    if category is None:
        raise HttpError(404, "Categoría no encontrada.")
    out = {}
    for p in players_in_category(category).only("id", "first_name", "last_name", "photo", "photo_url"):
        initials = "".join(x[:1] for x in (p.first_name, p.last_name) if x).upper()
        out[str(p.id)] = {"photo": p.photo_src, "initials": initials}
    return {"players": out}


@router.get("/composition")
def composition_view(request, category_id: str, player_id: str | None = None):
    """Composición corporal of the selected category: last anthropometry of
    each player vs his previous one, and one player's history. Not weekly —
    see `load_control.composition`."""
    from load_control.composition import composition

    _require(request, PERM_VIEW)
    membership = get_membership(request.user)
    category = (scope_categories(Category.objects.select_related("club"), membership)
                .filter(pk=category_id).first())
    if category is None:
        raise HttpError(404, "Categoría no encontrada.")
    return composition(category, player_id=player_id)


@router.get("/microcycles/{microcycle_id}/players")
def players_view(request, microcycle_id: str):
    """The week's team, for the Jugador picker."""
    from load_control.player_card import roster

    _require(request, PERM_VIEW)
    return roster(_microcycle(request, microcycle_id))


@router.get("/microcycles/{microcycle_id}/players/{player_id}")
def player_card_view(request, microcycle_id: str, player_id: str):
    """Jugador: one player in the week, every panel — see `load_control.player_card`."""
    from load_control.player_card import player_card

    _require(request, PERM_VIEW)
    mc = _microcycle(request, microcycle_id)
    try:
        return player_card(mc, player_id)
    except ValueError as exc:
        raise HttpError(400, str(exc))


@router.get("/microcycles/{microcycle_id}/summary")
def summary_view(request, microcycle_id: str):
    """Resumen: the week at a glance — see `load_control.summary`."""
    from load_control.summary import summary

    _require(request, PERM_VIEW)
    return summary(_microcycle(request, microcycle_id))



@router.get("/day")
def day_view(request, category_id: str, day: date | None = None):
    """The day navigator of the squad panels: which week holds `day` (default
    today), whether it is planned, and the key the panels read it by."""
    from django.utils import timezone

    from load_control.week import describe, week_for

    _require(request, PERM_VIEW)
    day = day or timezone.localdate()
    team = _team(request, category_id, day.year)
    mc = week_for(team, day)
    return {"team": {"label": team.label, "season": team.season, "categories": [c.name for c in team.categories()]},
            "week_key": f"{day.isoformat()}_{category_id}", **describe(mc, day)}
