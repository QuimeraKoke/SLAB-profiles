from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.shortcuts import get_object_or_404
from ninja import File, Form, NinjaAPI, Query
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.models import Category, Contract, Department, Player, Position
from dashboards.aggregation import resolve_widget
from dashboards.models import DepartmentLayout, TeamReportLayout
from dashboards.team_aggregation import resolve_team_widget
from events.models import Event
from exams.bulk_ingest import IngestError, run_ingest
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate

from .auth import issue_token, jwt_auth
from .scoping import (
    get_membership,
    has_full_access,
    scope_categories,
    scope_departments,
    scope_events,
    scope_players,
    scope_positions,
    scope_results,
    scope_templates,
)
from .schemas import (
    CategoryOut,
    DepartmentOut,
    EventIn,
    EventOut,
    LayoutResponseOut,
    LoginIn,
    LoginOut,
    MeOut,
    MembershipOut,
    PlayerDetailOut,
    PlayerIn,
    PlayerOut,
    PlayerPatchIn,
    PositionOut,
    AlertOut,
    AlertPatchIn,
    AlertWithPlayerOut,
    AttachmentOut,
    ContractIn,
    ContractOut,
    ContractPatchIn,
    EpisodeOut,
    EpisodePatchIn,
    GoalIn,
    GoalOut,
    GoalPatchIn,
    ResultIn,
    ResultOut,
    ResultPatchIn,
    TeamReportResponseOut,
    TeamResultsIn,
    TeamResultsOut,
    TemplateOut,
    UserOut,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Permission helpers — declared early so the endpoint decorators below
# can reference them without forward-ref gymnastics.
# ---------------------------------------------------------------------------


def _has_perm(user, codename: str) -> bool:
    """Cheap helper around `user.has_perm`. Handles anonymous + superuser.

    Codename format is `<app_label>.<codename>` (e.g. `core.view_contract`).
    Superusers always return True (matches Django's default).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.has_perm(codename)


def require_perm(codename: str):
    """Decorator: raise HttpError(403) when the request user lacks `codename`.

    Use on Ninja endpoint functions; the decorator forwards `*args,
    **kwargs` after the permission check. Superusers bypass via
    `_has_perm`.

    Example:

        @api.delete("/results/{result_id}")
        @require_perm("exams.delete_examresult")
        def delete_result(request, result_id: UUID):
            ...
    """
    from functools import wraps

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not _has_perm(request.user, codename):
                raise HttpError(
                    403,
                    f"No tienes permiso para esta acción ({codename}).",
                )
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


api = NinjaAPI(title="SLAB API", version="0.1.0", auth=jwt_auth)


@api.get("/health", auth=None)
def health(request):
    return {"status": "ok"}


# Reports / per-player views accept a date window (date_from / date_to) and
# we cap it to keep responses bounded — a bypassed UI can't load arbitrary
# years of data. Cap value applies uniformly across team and per-player
# endpoints so the two layers stay consistent.
DATE_WINDOW_MAX_DAYS = 90


def _parse_date_window(
    date_from: str | None,
    date_to: str | None,
) -> tuple[datetime | None, datetime | None]:
    """Parse + sanitize a (date_from, date_to) pair from query params.

    - Strings are parsed as ISO-8601 (date or datetime). Malformed values
      become None silently — same "don't break on stale frontend state"
      posture used everywhere else in this module.
    - If both bounds are present and inverted (from > to), they swap.
    - If the resulting span exceeds DATE_WINDOW_MAX_DAYS, the lower bound
      is pinned so the window equals the cap.

    Returns the parsed (from, to) tuple ready to hand to the resolvers.
    """
    from datetime import datetime as _dt, timedelta as _td

    def _parse(raw: str | None) -> _dt | None:
        if not raw:
            return None
        try:
            return _dt.fromisoformat(raw)
        except (TypeError, ValueError):
            return None

    parsed_from = _parse(date_from)
    parsed_to = _parse(date_to)
    if parsed_from and parsed_to:
        if parsed_to < parsed_from:
            parsed_from, parsed_to = parsed_to, parsed_from
        if (parsed_to - parsed_from).days > DATE_WINDOW_MAX_DAYS:
            parsed_from = parsed_to - _td(days=DATE_WINDOW_MAX_DAYS)
    return parsed_from, parsed_to


def _serialize_user(user):
    """Project the Django User into the `UserOut` shape with all
    effective permission codenames flattened. Superusers get a single
    `"*"` sentinel — the frontend treats it as "match anything"
    instead of pretending to enumerate the entire permission table."""
    if user.is_superuser:
        permissions = ["*"]
    else:
        permissions = sorted(user.get_all_permissions())
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "permissions": permissions,
    }


def _serialize_membership(membership):
    if membership is None:
        return None
    return {
        "club": membership.club,
        "all_categories": membership.all_categories,
        "categories": list(membership.categories.all()),
        "all_departments": membership.all_departments,
        "departments": list(membership.departments.all()),
    }


@api.post("/auth/login", response=LoginOut, auth=None)
def login(request, payload: LoginIn):
    """Authenticate by email + password.

    Django's default `authenticate()` uses username, so we resolve the user by
    email first and then call authenticate() with that username.
    """
    user_record = User.objects.filter(email__iexact=payload.email).first()
    if user_record is None:
        raise HttpError(401, "Invalid credentials")
    user = authenticate(request, username=user_record.username, password=payload.password)
    if user is None or not user.is_active:
        raise HttpError(401, "Invalid credentials")
    token, expires_at = issue_token(user)
    membership = get_membership(user)
    return {
        "access_token": token,
        "expires_at": expires_at,
        "user": _serialize_user(user),
        "membership": _serialize_membership(membership),
    }


@api.get("/auth/me", response=MeOut)
def me(request):
    membership = get_membership(request.user)
    return {
        "user": _serialize_user(request.user),
        "membership": _serialize_membership(membership),
    }


@api.get("/clubs/{club_id}/departments", response=list[DepartmentOut])
def list_club_departments(request, club_id: str):
    membership = get_membership(request.user)
    qs = Department.objects.filter(club_id=club_id)
    return scope_departments(qs, membership)


@api.get("/clubs/{club_id}/positions", response=list[PositionOut])
def list_club_positions(request, club_id: str):
    membership = get_membership(request.user)
    qs = Position.objects.filter(club_id=club_id)
    return scope_positions(qs, membership)


@api.get("/categories", response=list[CategoryOut])
def list_categories(request, club_id: str | None = None):
    """List categories visible to the user. Optional `club_id` filter."""
    membership = get_membership(request.user)
    qs = scope_categories(
        Category.objects.prefetch_related("departments"),
        membership,
    )
    if club_id:
        qs = qs.filter(club_id=club_id)
    return list(qs.order_by("name"))


@api.get("/categories/{category_id}", response=CategoryOut)
def get_category(request, category_id: str):
    membership = get_membership(request.user)
    qs = scope_categories(
        Category.objects.prefetch_related("departments"),
        membership,
    )
    category = qs.filter(id=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    # Hide departments the user can't access (otherwise the frontend builds
    # tabs they'll get 403/empty data on).
    if not has_full_access(membership) and not membership.all_departments:
        allowed = set(membership.departments.values_list("pk", flat=True))
        category._prefetched_departments = [
            d for d in category.departments.all() if d.pk in allowed
        ]
    return {
        "id": category.id,
        "name": category.name,
        "club_id": category.club_id,
        "departments": getattr(
            category,
            "_prefetched_departments",
            list(category.departments.all()),
        ),
    }


@api.get("/players", response=list[PlayerOut])
def list_players(
    request,
    category_id: str | None = None,
    include_inactive: bool = False,
):
    """Default behavior excludes inactive players (consumers like Equipo and
    team reports want roster-only). The configuraciones page passes
    `include_inactive=true` so admins can manage availability."""
    membership = get_membership(request.user)
    qs = Player.objects.select_related("category", "position")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    qs = scope_players(qs, membership)
    if category_id:
        qs = qs.filter(category_id=category_id)
    return qs.order_by("last_name", "first_name")


@api.get("/players/{player_id}", response=PlayerDetailOut)
def get_player(request, player_id: str):
    membership = get_membership(request.user)
    qs = scope_players(
        Player.objects.select_related("category__club", "position").prefetch_related(
            "category__departments"
        ),
        membership,
    )
    player = qs.filter(id=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    # Filter category.departments to ones the user is allowed to see.
    departments = list(player.category.departments.all())
    if not has_full_access(membership) and not membership.all_departments:
        allowed = set(membership.departments.values_list("pk", flat=True))
        departments = [d for d in departments if d.pk in allowed]
    from exams.models import Episode as _Episode
    open_eps = _Episode.objects.filter(
        player=player, status=_Episode.STATUS_OPEN,
    ).count()

    return {
        "id": player.id,
        "first_name": player.first_name,
        "last_name": player.last_name,
        "date_of_birth": player.date_of_birth,
        "sex": player.sex,
        "nationality": player.nationality,
        "is_active": player.is_active,
        "status": player.status,
        "club": player.category.club,
        "category": {
            "id": player.category.id,
            "name": player.category.name,
            "club_id": player.category.club_id,
            "departments": departments,
        },
        "position": player.position,
        "current_contract": _serialize_current_contract(player, request.user),
        "current_weight_kg": (
            float(player.current_weight_kg)
            if player.current_weight_kg is not None else None
        ),
        "current_height_cm": (
            float(player.current_height_cm)
            if player.current_height_cm is not None else None
        ),
        "age": player.age,
        "open_episode_count": open_eps,
    }


def _check_category_in_scope(category_id, membership):
    """Validates the user can see the given category. Returns the Category
    instance on success, raises 404/403 otherwise — used by player CRUD
    so a doctor can't move a player into a category they don't manage."""
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    return category


def _check_position_in_scope(position_id, club_id):
    """Validates the position exists and belongs to the same club. Positions
    aren't membership-scoped (they're per-club), but we still cross-check
    the club so admins can't accidentally assign a position from another club."""
    if position_id is None:
        return None
    pos = Position.objects.filter(pk=position_id, club_id=club_id).first()
    if pos is None:
        raise HttpError(400, "Position not found in this club.")
    return pos


@api.post("/players", response=PlayerDetailOut)
@require_perm("core.add_player")
def create_player(request, payload: PlayerIn):
    """Create a player. The signed-in user must have access to the target
    category (via StaffMembership). Position is optional but if provided
    must belong to the same club as the category."""
    membership = get_membership(request.user)
    category = _check_category_in_scope(payload.category_id, membership)
    _check_position_in_scope(payload.position_id, category.club_id)

    player = Player.objects.create(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        date_of_birth=payload.date_of_birth,
        sex=payload.sex,
        nationality=payload.nationality,
        is_active=payload.is_active,
        category=category,
        position_id=payload.position_id,
        current_weight_kg=payload.current_weight_kg,
        current_height_cm=payload.current_height_cm,
    )
    return get_player(request, str(player.id))


@api.patch("/players/{player_id}", response=PlayerDetailOut)
@require_perm("core.change_player")
def update_player(request, player_id: str, payload: PlayerPatchIn):
    """Partial update for a player. Each provided field is written; others
    remain. `status` is **not** writable — it's auto-derived from open
    episodes. Moving a player to a different category re-checks scope."""
    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category"), membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    fields_to_update: list[str] = []

    # If category is changing, re-check that the user can see the destination.
    if payload.category_id is not None and payload.category_id != player.category_id:
        new_category = _check_category_in_scope(payload.category_id, membership)
        player.category = new_category
        fields_to_update.append("category")
        # Re-validate position against the (possibly new) club.
        target_club_id = new_category.club_id
    else:
        target_club_id = player.category.club_id

    if payload.position_id is not None:
        # `position_id=None` is a valid intent (clear position). The schema
        # field is `UUID | None` so we can't distinguish "not provided" from
        # "set to null" via Pydantic alone; treat None as "no change" — to
        # explicitly clear, the frontend must send a separate signal. For
        # MVP, callers send the actual UUID or omit the key altogether.
        _check_position_in_scope(payload.position_id, target_club_id)
        player.position_id = payload.position_id
        fields_to_update.append("position")

    simple_fields: dict[str, Any] = {
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "date_of_birth": payload.date_of_birth,
        "sex": payload.sex,
        "nationality": payload.nationality,
        "is_active": payload.is_active,
        "current_weight_kg": payload.current_weight_kg,
        "current_height_cm": payload.current_height_cm,
    }
    for field, value in simple_fields.items():
        if value is None:
            continue
        if field in ("first_name", "last_name") and isinstance(value, str):
            value = value.strip()
        setattr(player, field, value)
        fields_to_update.append(field)

    if fields_to_update:
        player.save(update_fields=fields_to_update)

    return get_player(request, str(player.id))


@api.delete("/players/{player_id}")
@require_perm("core.delete_player")
def delete_player(request, player_id: str):
    """Hard-delete a player. Refuses (409) when there are linked records
    (results, episodes, contracts) — those reflect real history and the
    correct move there is to deactivate (`is_active=False`) the player.
    For mistaken creates with no history, deletion is allowed."""
    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.all(), membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    from django.db.models import ProtectedError

    try:
        player.delete()
    except ProtectedError as exc:
        # PROTECT relations (Category) shouldn't fire here, but if any
        # related model adds PROTECT later, surface a clean error.
        raise HttpError(
            409,
            "No se puede borrar: hay datos asociados que protegen al jugador. "
            "Desactiva al jugador (is_active=false) en su lugar para "
            "preservar el historial.",
        ) from exc

    return {"deleted": True}


# ---------- Contracts ----------

def _user_can_see_salary(user) -> bool:
    """Salary visibility gate.

    Backed by the standard `core.view_contract` permission. Granted
    granularly to users via /admin/auth/user/<id>/ → User permissions,
    or via a custom group. Superusers always pass.
    """
    return _has_perm(user, "core.view_contract")


def _serialize_contract(contract: Contract, user) -> dict:
    salary_visible = _user_can_see_salary(user)
    base = {
        "id": contract.id,
        "player_id": contract.player_id,
        "contract_type": contract.contract_type,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "signing_date": contract.signing_date,
        "ownership_percentage": float(contract.ownership_percentage),
        "salary_currency": contract.salary_currency,
        "agent_name": contract.agent_name,
        "notes": contract.notes,
        "season_label": contract.season_label,
        "salary_visible": salary_visible,
    }
    if salary_visible:
        base["total_gross_amount"] = (
            float(contract.total_gross_amount)
            if contract.total_gross_amount is not None else None
        )
        base["fixed_bonus"] = contract.fixed_bonus
        base["variable_bonus"] = contract.variable_bonus
        base["salary_increase"] = contract.salary_increase
        base["purchase_option"] = contract.purchase_option
        base["release_clause"] = contract.release_clause
        base["renewal_option"] = contract.renewal_option
    else:
        base["total_gross_amount"] = None
        base["fixed_bonus"] = ""
        base["variable_bonus"] = ""
        base["salary_increase"] = ""
        base["purchase_option"] = ""
        base["release_clause"] = ""
        base["renewal_option"] = ""
    return base


def _serialize_current_contract(player: Player, user) -> dict | None:
    from datetime import date as _date
    today = _date.today()
    current = (
        Contract.objects
        .filter(player=player, start_date__lte=today, end_date__gte=today)
        .order_by("-start_date")
        .first()
    )
    if current is None:
        return None
    return _serialize_contract(current, user)


@api.get("/players/{player_id}/contracts", response=list[ContractOut])
@require_perm("core.view_contract")
def list_player_contracts(request, player_id: str):
    membership = get_membership(request.user)
    player = scope_players(Player.objects.all(), membership).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    contracts = Contract.objects.filter(player=player).order_by("-end_date", "-start_date")
    return [_serialize_contract(c, request.user) for c in contracts]


# Contract mutations are gated per-action via the standard
# `core.add_contract` / `core.change_contract` / `core.delete_contract`
# permissions. Assigned granularly through /admin/auth/user/<id>/
# rather than via the Editor / Solo Lectura groups (those don't
# include contract perms by design).


@api.post("/contracts", response=ContractOut)
@require_perm("core.add_contract")
def create_contract(request, payload: ContractIn):
    membership = get_membership(request.user)
    player = scope_players(Player.objects.all(), membership).filter(id=payload.player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    if payload.end_date < payload.start_date:
        raise HttpError(400, "end_date must be on or after start_date.")
    contract = Contract.objects.create(
        player=player,
        contract_type=payload.contract_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        signing_date=payload.signing_date,
        ownership_percentage=payload.ownership_percentage,
        total_gross_amount=payload.total_gross_amount,
        salary_currency=payload.salary_currency or "CLP",
        fixed_bonus=payload.fixed_bonus,
        variable_bonus=payload.variable_bonus,
        salary_increase=payload.salary_increase,
        purchase_option=payload.purchase_option,
        release_clause=payload.release_clause,
        renewal_option=payload.renewal_option,
        agent_name=payload.agent_name,
        notes=payload.notes,
    )
    return _serialize_contract(contract, request.user)


@api.patch("/contracts/{contract_id}", response=ContractOut)
@require_perm("core.change_contract")
def update_contract(request, contract_id: str, payload: ContractPatchIn):
    membership = get_membership(request.user)
    contract = (
        Contract.objects
        .filter(player__in=scope_players(Player.objects.all(), membership))
        .filter(pk=contract_id)
        .first()
    )
    if contract is None:
        raise HttpError(404, "Contract not found")

    fields = []
    for name in (
        "contract_type", "start_date", "end_date", "signing_date",
        "ownership_percentage", "total_gross_amount", "salary_currency",
        "fixed_bonus", "variable_bonus", "salary_increase",
        "purchase_option", "release_clause", "renewal_option",
        "agent_name", "notes",
    ):
        value = getattr(payload, name)
        if value is not None:
            setattr(contract, name, value)
            fields.append(name)
    if contract.end_date < contract.start_date:
        raise HttpError(400, "end_date must be on or after start_date.")
    if fields:
        fields.append("updated_at")
        contract.save(update_fields=fields)
    return _serialize_contract(contract, request.user)


@api.delete("/contracts/{contract_id}")
@require_perm("core.delete_contract")
def delete_contract(request, contract_id: str):
    membership = get_membership(request.user)
    contract = (
        Contract.objects
        .filter(player__in=scope_players(Player.objects.all(), membership))
        .filter(pk=contract_id)
        .first()
    )
    if contract is None:
        raise HttpError(404, "Contract not found")
    contract.delete()
    return {"deleted": True}


@api.get("/templates/{template_id}", response=TemplateOut)
def get_template(request, template_id: str):
    membership = get_membership(request.user)
    qs = scope_templates(
        ExamTemplate.objects.select_related("department"),
        membership,
    )
    template = qs.filter(id=template_id).first()
    if template is None:
        raise HttpError(404, "Template not found")
    return template


@api.post("/results", response=ResultOut)
@require_perm("exams.add_examresult")
def create_result(request, payload: ResultIn):
    """Create an ExamResult.

    Calculated fields in the template's config_schema are evaluated server-side
    via the AST formula engine and merged into result_data alongside the raw
    inputs. The doctor never types a calculated value — the engine does.

    When `event_id` is provided the linked Event is stored on the result and
    `recorded_at` is overridden to `event.starts_at` so the timestamp is
    always authoritative — same contract as `/api/results/bulk`.
    """
    membership = get_membership(request.user)

    template = scope_templates(
        ExamTemplate.objects.all(), membership
    ).filter(id=payload.template_id).first()
    if template is None:
        raise HttpError(404, "Template not found")

    player = scope_players(Player.objects.all(), membership).filter(id=payload.player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    event = None
    recorded_at = payload.recorded_at
    if payload.event_id:
        event = scope_events(Event.objects.all(), membership).filter(pk=payload.event_id).first()
        if event is None:
            raise HttpError(404, "Event not found")
        if event.club_id != player.category.club_id:
            raise HttpError(400, "El evento debe pertenecer al mismo club que el jugador.")
        recorded_at = event.starts_at

    result_data, inputs_snapshot = compute_result_data(
        template, payload.raw_data, player=player,
    )

    # Resolve / open episode for episodic templates. Returns None for non-episodic.
    from exams.episode_lifecycle import resolve_episode
    episode = resolve_episode(
        template=template,
        player=player,
        episode_id=payload.episode_id,
        recorded_at=recorded_at,
        user=request.user,
    )

    result = ExamResult.objects.create(
        player=player,
        template=template,
        recorded_at=recorded_at,
        result_data=result_data,
        inputs_snapshot=inputs_snapshot,
        event=event,
        episode=episode,
    )

    if not template.is_locked:
        template.is_locked = True
        template.save(update_fields=["is_locked"])

    return _serialize_result(result)


@api.patch("/results/{result_id}", response=ResultOut)
@require_perm("exams.change_examresult")
def update_result(request, result_id: UUID, payload: ResultPatchIn):
    """Update an existing ExamResult's raw_data and/or recorded_at.

    Re-runs the formula engine + inputs_snapshot. For results linked to
    an Episode, refreshes the Episode's derived state (stage/title/
    ended_at) and recomputes Player.status if the episode's status
    changes.

    Mutating result_data after the fact intentionally trades audit-trail
    purity for clinical UX (correcting typos, adding missed details).
    The original recorded_at is preserved unless explicitly changed.
    """
    membership = get_membership(request.user)
    result = (
        ExamResult.objects
        .filter(template__in=scope_templates(ExamTemplate.objects.all(), membership))
        .filter(player__in=scope_players(Player.objects.all(), membership))
        .filter(pk=result_id)
        .select_related("template", "player", "episode")
        .first()
    )
    if result is None:
        raise HttpError(404, "Result not found")

    fields_to_update: list[str] = []

    if payload.raw_data is not None:
        result_data, inputs_snapshot = compute_result_data(
            result.template, payload.raw_data, player=result.player,
        )
        result.result_data = result_data
        result.inputs_snapshot = inputs_snapshot
        fields_to_update.extend(["result_data", "inputs_snapshot"])

    if payload.recorded_at is not None:
        result.recorded_at = payload.recorded_at
        fields_to_update.append("recorded_at")

    if fields_to_update:
        result.save(update_fields=fields_to_update)
        # If this result belongs to an Episode, refresh derived state — the
        # latest result's stage may have changed, ended_at may need to flip,
        # and Player.status may need to recompute.
        if result.episode_id:
            from exams.episode_lifecycle import (
                recompute_player_status,
                refresh_episode_from_results,
            )
            refresh_episode_from_results(result.episode)
            recompute_player_status(result.player)

    return _serialize_result(result)


@api.delete("/results/{result_id}")
@require_perm("exams.delete_examresult")
def delete_result(request, result_id: UUID):
    """Hard-delete an ExamResult plus any attachments pinned to it.

    Episode bookkeeping: if the deleted result was part of an Episode, refresh
    the Episode's derived state (stage/title/ended_at) and recompute
    `Player.status`. If the result was the only one in its episode the
    episode's `latest_result_data` falls back to {} — the doctor can re-open
    or close the episode manually from the Lesiones tab.

    Files: `Attachment.file.delete()` clears the S3 object too. Attachments
    are not FK-linked to ExamResult (polymorphic source_id), so the cascade
    must run here.
    """
    from attachments.models import Attachment, AttachmentSource

    membership = get_membership(request.user)
    result = (
        ExamResult.objects
        .filter(template__in=scope_templates(ExamTemplate.objects.all(), membership))
        .filter(player__in=scope_players(Player.objects.all(), membership))
        .filter(pk=result_id)
        .select_related("template", "player", "episode")
        .first()
    )
    if result is None:
        raise HttpError(404, "Result not found")

    # Snapshot the bits we'll need for downstream cleanup before delete().
    episode = result.episode
    player = result.player

    # Cascade to attachments. Each Attachment.file.delete() purges the S3
    # object; calling .delete() in a loop is fine — these are typically <10
    # files per result.
    pinned = Attachment.objects.filter(
        source_type=AttachmentSource.EXAM_FIELD, source_id=result.id,
    )
    for att in pinned:
        att.file.delete(save=False)
        att.delete()

    result.delete()

    # Refresh episode + player.status if applicable.
    if episode is not None:
        from exams.episode_lifecycle import (
            recompute_player_status,
            refresh_episode_from_results,
        )
        refresh_episode_from_results(episode)
        recompute_player_status(player)

    return {"deleted": True}


@api.post("/results/team", response=TeamResultsOut)
@require_perm("exams.add_examresult")
def create_team_results(request, payload: TeamResultsIn):
    """Create one ExamResult per player from a roster-style submission.

    Each row's `result_data` is merged with `shared_data` (shared_data wins
    when keys overlap is impossible — overlap is rejected at template-config
    time). Rows where every row_field is empty/null are skipped silently so
    a doctor can leave blanks for players they didn't sample.

    All-or-nothing: any error rolls back the whole batch.
    """
    from django.db import transaction as db_transaction

    membership = get_membership(request.user)

    template = scope_templates(
        ExamTemplate.objects.all(), membership
    ).filter(id=payload.template_id).first()
    if template is None:
        raise HttpError(404, "Template not found")

    cfg = template.input_config or {}
    if ExamTemplate.MODE_TEAM_TABLE not in (cfg.get("input_modes") or []):
        raise HttpError(400, "This template does not enable team_table input mode.")
    if template.is_episodic:
        raise HttpError(
            400,
            "Episodic templates only support single-mode input (each result must "
            "be linked to a specific episode).",
        )

    category = scope_categories(
        Category.objects.all(), membership
    ).filter(id=payload.category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    if not template.applicable_categories.filter(pk=category.id).exists():
        raise HttpError(400, "Template is not applicable to this category.")

    # Resolve roster — every row's player must belong to this category.
    submitted_player_ids = {row.player_id for row in payload.rows}
    valid_players = {
        p.id: p
        for p in scope_players(Player.objects.all(), membership).filter(
            id__in=submitted_player_ids, category=category
        )
    }
    missing = submitted_player_ids - valid_players.keys()
    if missing:
        raise HttpError(400, f"{len(missing)} player(s) not in category or not accessible.")

    # Optional event link (e.g. match performance bulk-entry from the matches
    # editor). Server-side override on `recorded_at` so the saved timestamp
    # matches the event's `starts_at` — same behavior as single-mode.
    event = None
    effective_recorded_at = payload.recorded_at
    if payload.event_id is not None:
        event = scope_events(Event.objects.all(), membership).filter(
            id=payload.event_id,
        ).first()
        if event is None:
            raise HttpError(404, "Event not found")
        effective_recorded_at = event.starts_at

    team_cfg = cfg.get("team_table") or {}
    declared_row_fields = set(team_cfg.get("row_fields") or [])

    def is_blank(row_data: dict) -> bool:
        # If row_fields are declared, only those count toward "is the doctor
        # actually entering anything". Otherwise fall back to "any non-null
        # value in result_data".
        keys = declared_row_fields or set(row_data.keys())
        for key in keys:
            value = row_data.get(key)
            if value not in (None, "", []):
                return False
        return True

    created: list[ExamResult] = []
    skipped = 0

    with db_transaction.atomic():
        for row in payload.rows:
            if is_blank(row.result_data):
                skipped += 1
                continue
            merged = {**(payload.shared_data or {}), **row.result_data}
            target_player = valid_players[row.player_id]
            result_data, inputs_snapshot = compute_result_data(
                template, merged, player=target_player,
            )
            result = ExamResult.objects.create(
                player=target_player,
                template=template,
                recorded_at=effective_recorded_at,
                result_data=result_data,
                inputs_snapshot=inputs_snapshot,
                event=event,
            )
            created.append(result)

        if created and not template.is_locked:
            template.is_locked = True
            template.save(update_fields=["is_locked"])

    return {
        "created": len(created),
        "skipped": skipped,
        "results": [_serialize_result(r) for r in created],
    }


def _serialize_result(result: ExamResult) -> dict:
    return {
        "id": result.id,
        "player_id": result.player_id,
        "template_id": result.template_id,
        "recorded_at": result.recorded_at,
        "result_data": result.result_data,
        "inputs_snapshot": result.inputs_snapshot or {},
        "event": (
            {
                "id": result.event.id,
                "event_type": result.event.event_type,
                "title": result.event.title,
                "starts_at": result.event.starts_at,
                "metadata": result.event.metadata or {},
            }
            if result.event_id
            else None
        ),
    }


@api.post("/results/bulk")
@require_perm("exams.add_examresult")
def bulk_results(
    request,
    file: UploadedFile = File(...),
    template_id: str = Form(...),
    category_id: str = Form(...),
    recorded_at: str = Form(...),
    dry_run: bool = Form(True),
    event_id: str = Form(""),
):
    """Bulk-ingest a spreadsheet into a template configured for `bulk_ingest`.

    With `dry_run=True` (the default) the server parses + matches + transforms
    but commits nothing — the response is a preview the staff can review. With
    `dry_run=False` it commits the matched players as ExamResult rows.

    When `event_id` is provided the linked Event is stored on each created
    ExamResult AND `recorded_at` is overridden to `event.starts_at` so the
    timestamp is always authoritatively the match's start.
    """
    membership = get_membership(request.user)

    template = scope_templates(
        ExamTemplate.objects.all(), membership
    ).filter(id=template_id).first()
    if template is None:
        raise HttpError(404, "Template not found")

    if "bulk_ingest" not in (template.input_config or {}).get("input_modes", []):
        raise HttpError(400, "Esta plantilla no admite carga masiva.")
    if template.is_episodic:
        raise HttpError(
            400, "Episodic templates only support single-mode input.",
        )

    category = scope_categories(
        Category.objects.all(), membership
    ).filter(id=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    event = None
    if event_id:
        event = scope_events(Event.objects.all(), membership).filter(pk=event_id).first()
        if event is None:
            raise HttpError(404, "Event not found")
        if event.club_id != category.club_id:
            raise HttpError(400, "El evento debe pertenecer al mismo club que la categoría.")

    if event is not None:
        # Authoritative source for the timestamp when an event is linked.
        recorded_dt = event.starts_at
    else:
        try:
            recorded_dt = datetime.fromisoformat(recorded_at)
        except ValueError:
            raise HttpError(400, "recorded_at debe ser una fecha ISO 8601.")

    try:
        file_bytes = file.read()
    finally:
        file.close()

    try:
        result = run_ingest(
            file_bytes, template, category, recorded_dt,
            dry_run=dry_run, event=event,
        )
    except IngestError as exc:
        raise HttpError(400, str(exc))

    if not dry_run and result.get("created_results") and not template.is_locked:
        template.is_locked = True
        template.save(update_fields=["is_locked"])
    return result


@api.get("/players/{player_id}/templates", response=list[TemplateOut])
def list_player_templates(request, player_id: str, department: str | None = None):
    """Templates the doctor can fill in for this player.

    Filtered to: the player's category, the user's accessible departments, and
    optionally a single department slug for tab-scoped requests.
    """
    membership = get_membership(request.user)

    player = scope_players(
        Player.objects.select_related("category"),
        membership,
    ).filter(id=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    qs = scope_templates(
        ExamTemplate.objects.select_related("department").filter(
            applicable_categories=player.category,
            # Only the active version of each family is offered for new
            # writes. Inactive versions stay in the DB so historical
            # ExamResults remain queryable; they don't appear in the
            # registrar's picker.
            is_active_version=True,
        ),
        membership,
    )
    if department:
        qs = qs.filter(department__slug=department)
    return qs.distinct()


@api.get("/players/{player_id}/summary")
def get_player_summary(request, player_id: str):
    """Aggregate summary card payload for the player profile's Resumen tab.

    Pulls match stats from `rendimiento_de_partido`, physical metrics from
    `gps_rendimiento_fisico_de_partido`, and the latest 3 injury episodes
    from `lesiones`. Each section gracefully degrades to null when no data
    exists for the player on that template.

    Template slugs are conventional (matching the seed commands in
    `exams/management/commands/`). If a club later wires its own templates
    under different slugs, this endpoint will return null for those
    sections — fix is to add slug aliases here, not invent new endpoints.
    """
    from exams.models import Episode

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category"), membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    accessible_templates = scope_templates(ExamTemplate.objects.all(), membership)

    def _avg(values: list[float]) -> float | None:
        nums = [v for v in values if isinstance(v, (int, float))]
        if not nums:
            return None
        return round(sum(nums) / len(nums), 2)

    def _sum_int(values: list) -> int:
        return sum(int(v) for v in values if isinstance(v, (int, float)))

    # ---- Match stats ----
    match_stats = None
    match_template = accessible_templates.filter(slug="rendimiento_de_partido").first()
    if match_template is not None:
        match_results = list(
            ExamResult.objects.filter(player=player, template=match_template).values_list(
                "result_data", flat=True,
            )
        )
        if match_results:
            minutes = [r.get("minutes_played") for r in match_results]
            goals = [r.get("goals", 0) or 0 for r in match_results]
            assists = [r.get("assists", 0) or 0 for r in match_results]
            yellow = [r.get("yellow_cards", 0) or 0 for r in match_results]
            red = [r.get("red_card", 0) or 0 for r in match_results]
            ratings = [r.get("rating") for r in match_results if r.get("rating") is not None]
            match_stats = {
                "matches_played": len(match_results),
                "minutes_total": _sum_int(minutes),
                "goals": _sum_int(goals),
                "assists": _sum_int(assists),
                "yellow_cards": _sum_int(yellow),
                "red_cards": _sum_int(red),
                "rating_avg": _avg(ratings) if ratings else None,
            }

    # ---- Physical ----
    physical = None
    gps_template = accessible_templates.filter(
        slug="gps_rendimiento_fisico_de_partido",
    ).first()
    if gps_template is not None:
        gps_results = list(
            ExamResult.objects.filter(player=player, template=gps_template).values_list(
                "result_data", flat=True,
            )
        )
        if gps_results:
            physical = {
                "matches_with_gps": len(gps_results),
                "distance_avg_m": _avg([r.get("tot_dist_total") for r in gps_results]),
                "max_velocity_avg": _avg([r.get("max_vel_total") for r in gps_results]),
                "hiaa_avg": _avg([r.get("hiaa_total") for r in gps_results]),
                "hmld_avg": _avg([r.get("hmld_total") for r in gps_results]),
                "acc_avg": _avg([r.get("acc_total") for r in gps_results]),
            }

    # ---- Recent injuries (latest 3) ----
    injury_template = accessible_templates.filter(slug="lesiones").first()
    recent_injuries = []
    if injury_template is not None:
        episodes = (
            Episode.objects
            .filter(player=player, template=injury_template)
            .order_by("-started_at")[:3]
            .values("status", "stage", "title", "started_at", "ended_at")
        )
        for ep in episodes:
            recent_injuries.append({
                "title": ep["title"] or "Lesión",
                "stage": ep["stage"] or "",
                "started_at": ep["started_at"].date().isoformat() if ep["started_at"] else None,
                "ended_at": ep["ended_at"].date().isoformat() if ep["ended_at"] else None,
                "status": "active" if ep["status"] == Episode.STATUS_OPEN else "closed",
            })

    return {
        "player_id": str(player.id),
        "match_stats": match_stats,
        "physical": physical,
        "recent_injuries": recent_injuries,
    }


@api.get("/players/{player_id}/results", response=list[ResultOut])
def list_player_results(
    request,
    player_id: str,
    department: str | None = None,
    template: str | None = None,
):
    """List results for a player.

    `department` filters by Department.slug (scoped to the player's club).
    `template` filters by ExamTemplate UUID — used by the registrar's
    history panel to show only entries for the template being edited.
    """
    membership = get_membership(request.user)
    qs = scope_results(
        ExamResult.objects.filter(player_id=player_id).select_related(
            "template__department", "event",
        ),
        membership,
    )
    if department:
        qs = qs.filter(template__department__slug=department)
    if template:
        qs = qs.filter(template_id=template)
    return [_serialize_result(r) for r in qs]


@api.get("/players/{player_id}/views", response=LayoutResponseOut)
def get_player_view(
    request,
    player_id: str,
    department: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Return the configured DepartmentLayout for (player.category, department).

    Returns `{"layout": null}` when no active layout exists — the frontend
    falls back to the legacy auto-rendered template grid in that case.

    Optional `date_from` / `date_to` (ISO-8601) bound `ExamResult.recorded_at`
    before each widget runs its aggregation. Capped at 90 days; widgets like
    `body_map_heatmap` ignore the bounds by design (see resolver docs).
    """
    membership = get_membership(request.user)
    parsed_from, parsed_to = _parse_date_window(date_from, date_to)

    player = scope_players(
        Player.objects.select_related("category"),
        membership,
    ).filter(id=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    dept = scope_departments(
        Department.objects.filter(club_id=player.category.club_id),
        membership,
    ).filter(slug=department).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    layout = (
        DepartmentLayout.objects
        .filter(department=dept, category=player.category, is_active=True)
        .select_related("department")
        .prefetch_related("sections__widgets__data_sources__template__department")
        .first()
    )
    if layout is None:
        return {"layout": None}

    accessible_template_ids = set(
        scope_templates(ExamTemplate.objects.all(), membership).values_list(
            "pk", flat=True
        )
    )

    sections_payload = []
    for section in layout.sections.all():
        widgets_payload = []
        for widget in section.widgets.all():
            sources = list(widget.data_sources.all())
            # Drop widgets the user can't access any data for.
            if sources and not any(
                s.template_id in accessible_template_ids for s in sources
            ):
                continue
            widgets_payload.append(
                {
                    "id": widget.id,
                    "chart_type": widget.chart_type,
                    "title": widget.title,
                    "description": widget.description,
                    "column_span": widget.column_span,
                    "chart_height": widget.chart_height,
                    "sort_order": widget.sort_order,
                    "display_config": widget.display_config or {},
                    "data": resolve_widget(widget, player.id, parsed_from, parsed_to),
                }
            )
        sections_payload.append(
            {
                "id": section.id,
                "title": section.title,
                "is_collapsible": section.is_collapsible,
                "default_collapsed": section.default_collapsed,
                "sort_order": section.sort_order,
                "widgets": widgets_payload,
            }
        )

    return {
        "layout": {
            "id": layout.id,
            "department": dept,
            "category_id": player.category_id,
            "name": layout.name,
            "sections": sections_payload,
        }
    }


# ---------- Team reports ----------

@api.get("/reports/{department_slug}", response=TeamReportResponseOut)
def get_team_report(
    request,
    department_slug: str,
    category_id: str,
    position_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    player_ids: str | None = None,
    match_id: str | None = None,
):
    """Return the active TeamReportLayout for `(department, category)`.

    Resolved server-side: every widget's payload is computed by the team
    aggregation registry and returned in `data`. Returns `{layout: null}`
    when no active layout exists so the frontend renders the placeholder.

    Optional filters (all applied uniformly across every widget):
      - `position_id`: narrows roster to players at this position.
      - `player_ids`: comma-separated UUIDs; further narrows roster.
      - `date_from` / `date_to`: ISO-8601 dates bounding ExamResult
        `recorded_at`. Capped at 90 days at the API layer. `status_counts`
        and `active_records` ignore these by design (current-state widgets).
      - `match_id`: when the layout's `match_selector_config.enabled` is
        true, narrows every ExamResult queryset to results linked to
        this Event. Ignored when the selector isn't enabled. Required
        mode (`config.required=true`): if `match_id` is missing or
        invalid, the API auto-selects the most recent match in scope so
        the page renders something useful on first load.
    """
    from uuid import UUID as _UUID

    membership = get_membership(request.user)

    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    dept = scope_departments(
        Department.objects.filter(club_id=category.club_id), membership,
    ).filter(slug=department_slug).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    parsed_position_id: _UUID | None = None
    if position_id:
        # Validate the position exists + belongs to the same club. We don't
        # 404 on a bad UUID here — silently ignore so a stale picker on the
        # frontend doesn't break the whole report.
        try:
            candidate_uuid = _UUID(position_id)
        except (TypeError, ValueError):
            candidate_uuid = None
        if candidate_uuid is not None and Position.objects.filter(
            pk=candidate_uuid, club_id=category.club_id,
        ).exists():
            parsed_position_id = candidate_uuid

    # Parse player_ids: comma-separated UUIDs. Silently drop malformed
    # entries — same "don't break on stale frontend state" posture as
    # position_id above.
    parsed_player_ids: list[_UUID] = []
    if player_ids:
        for raw in player_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed_player_ids.append(_UUID(raw))
            except (TypeError, ValueError):
                continue

    parsed_from, parsed_to = _parse_date_window(date_from, date_to)

    layout = (
        TeamReportLayout.objects
        .filter(department=dept, category=category, is_active=True)
        .select_related("department", "category")
        .prefetch_related("sections__widgets")
        .first()
    )
    if layout is None:
        return {"layout": None}

    # -------- Match selector resolution --------
    # The layout's stored config drives what the frontend renders + how
    # the resolver filters. When `enabled=true`, we expose the dropdown
    # options and the currently-selected match id. When `required=true`
    # we auto-pick the most recent match if the caller didn't pass one
    # so the page doesn't render an empty state on first load.
    raw_cfg = layout.match_selector_config or {}
    selector_enabled = bool(raw_cfg.get("enabled"))
    selector_required = bool(raw_cfg.get("required"))
    selector_event_type = (
        raw_cfg.get("event_type") or Event.TYPE_MATCH
    )
    selector_show_recent = max(1, min(int(raw_cfg.get("show_recent") or 10), 50))
    selector_label = raw_cfg.get("label") or "Partido"

    selector_options: list[Event] = []
    parsed_match_id: _UUID | None = None
    if selector_enabled:
        # Recent matches in scope: matches tied to this category, of the
        # configured event_type, newest first. Soft cap via show_recent.
        selector_options = list(
            Event.objects
            .filter(
                club_id=category.club_id,
                event_type=selector_event_type,
                category_id=category.id,
            )
            .order_by("-starts_at")[:selector_show_recent]
        )
        if match_id:
            try:
                candidate = _UUID(match_id)
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and any(e.id == candidate for e in selector_options):
                parsed_match_id = candidate
        # Required + nothing valid passed → auto-select the most recent.
        if parsed_match_id is None and selector_required and selector_options:
            parsed_match_id = selector_options[0].id

    sections_payload = []
    for section in layout.sections.all():
        widgets_payload = []
        for widget in section.widgets.all():
            widgets_payload.append(
                {
                    "id": widget.id,
                    "chart_type": widget.chart_type,
                    "title": widget.title,
                    "description": widget.description,
                    "column_span": widget.column_span,
                    "chart_height": widget.chart_height,
                    "sort_order": widget.sort_order,
                    "data": resolve_team_widget(
                        widget, category,
                        position_id=parsed_position_id,
                        player_ids=parsed_player_ids or None,
                        date_from=parsed_from,
                        date_to=parsed_to,
                        event_id=parsed_match_id,
                    ),
                }
            )
        sections_payload.append(
            {
                "id": section.id,
                "title": section.title,
                "is_collapsible": section.is_collapsible,
                "default_collapsed": section.default_collapsed,
                "sort_order": section.sort_order,
                "widgets": widgets_payload,
            }
        )

    return {
        "layout": {
            "id": layout.id,
            "department": dept,
            "category": category,
            "name": layout.name,
            "sections": sections_payload,
            "match_selector": {
                "enabled": selector_enabled,
                "event_type": selector_event_type,
                "required": selector_required,
                "label": selector_label,
                "show_recent": selector_show_recent,
                "options": [
                    {
                        "id": e.id,
                        "title": e.title,
                        "starts_at": e.starts_at,
                        "location": e.location or "",
                    }
                    for e in selector_options
                ],
                "selected_id": parsed_match_id,
            },
        }
    }


# ---------- PDF reports ----------


@api.get("/reports/{department_slug}/team.pdf")
def download_team_report_pdf(
    request,
    department_slug: str,
    category_id: str,
    position_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    player_ids: str | None = None,
    match_id: str | None = None,
):
    """Render the team-view report as a PDF (landscape A4).

    Same filter inputs as `GET /reports/{slug}` so the download button
    can pass through the exact URL query params the user is already
    looking at. Auth scoping mirrors the JSON endpoint.
    """
    from uuid import UUID as _UUID

    from django.http import HttpResponse

    from dashboards.pdf.team_report import render_team_pdf

    membership = get_membership(request.user)

    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    dept = scope_departments(
        Department.objects.filter(club_id=category.club_id), membership,
    ).filter(slug=department_slug).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    parsed_position_id: _UUID | None = None
    if position_id:
        try:
            cand = _UUID(position_id)
        except (TypeError, ValueError):
            cand = None
        if cand is not None and Position.objects.filter(
            pk=cand, club_id=category.club_id,
        ).exists():
            parsed_position_id = cand

    parsed_player_ids: list[_UUID] = []
    if player_ids:
        for raw in player_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed_player_ids.append(_UUID(raw))
            except (TypeError, ValueError):
                continue

    parsed_from, parsed_to = _parse_date_window(date_from, date_to)

    parsed_match_id: _UUID | None = None
    if match_id:
        try:
            mid = _UUID(match_id)
        except (TypeError, ValueError):
            mid = None
        if mid is not None and Event.objects.filter(
            pk=mid, category_id=category.id,
        ).exists():
            parsed_match_id = mid

    pdf_bytes = render_team_pdf(
        department=dept,
        category=category,
        position_id=parsed_position_id,
        player_ids=parsed_player_ids or None,
        date_from=parsed_from,
        date_to=parsed_to,
        event_id=parsed_match_id,
    )

    filename = f"reporte-{department_slug}-{category.name}.pdf".replace(" ", "_")
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api.get("/players/{player_id}/departments/{department_slug}/report.pdf")
def download_player_department_pdf(
    request,
    player_id: str,
    department_slug: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Per-player department report as a PDF (portrait A4)."""
    from django.http import HttpResponse

    from dashboards.pdf.player_report import render_player_pdf

    membership = get_membership(request.user)

    player = scope_players(
        Player.objects.select_related("category__club"), membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    dept = scope_departments(
        Department.objects.filter(club_id=player.category.club_id), membership,
    ).filter(slug=department_slug).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    parsed_from, parsed_to = _parse_date_window(date_from, date_to)

    pdf_bytes = render_player_pdf(
        player=player, department=dept,
        date_from=parsed_from, date_to=parsed_to,
    )

    name = f"{player.first_name}-{player.last_name}".replace(" ", "_")
    filename = f"reporte-{name}-{department_slug}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ---------- Events ----------

def _serialize_event(event: Event) -> dict:
    return {
        "id": event.id,
        "club": event.club,
        "department": event.department,
        "event_type": event.event_type,
        "title": event.title,
        "description": event.description,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "location": event.location,
        "scope": event.scope,
        "category": event.category,
        "participants": [
            {"id": p.id, "first_name": p.first_name, "last_name": p.last_name}
            for p in event.participants.all()
        ],
        "metadata": event.metadata or {},
        # Pre-annotated by list_events; fall back to a live count for detail views.
        "result_count": getattr(event, "_result_count", None) or event.exam_results.count(),
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


@api.get("/events", response=list[EventOut])
def list_events(
    request,
    department: str | None = None,
    department_id: UUID | None = None,
    player_id: UUID | None = None,
    category_id: UUID | None = None,
    event_type: str | None = None,
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
):
    """List events visible to the user, with optional filters.

    `department` accepts a department slug (e.g. "fisico"); `department_id`
    accepts the UUID. Use either, not both. `starts_after` / `starts_before`
    are inclusive ISO 8601 datetimes.
    """
    from django.db.models import Count

    membership = get_membership(request.user)
    qs = (
        scope_events(Event.objects.all(), membership)
        .select_related("club", "department", "category")
        .prefetch_related("participants")
        .annotate(_result_count=Count("exam_results"))
    )

    if department:
        qs = qs.filter(department__slug=department)
    if department_id:
        qs = qs.filter(department_id=department_id)
    if player_id:
        qs = qs.filter(participants__id=player_id)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if event_type:
        qs = qs.filter(event_type=event_type)
    if starts_after:
        qs = qs.filter(starts_at__gte=starts_after)
    if starts_before:
        qs = qs.filter(starts_at__lte=starts_before)

    qs = qs.order_by("starts_at").distinct()
    return [_serialize_event(e) for e in qs]


@api.get("/events/{event_id}", response=EventOut)
def get_event(request, event_id: UUID):
    membership = get_membership(request.user)
    event = scope_events(Event.objects.all(), membership).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")
    return _serialize_event(event)


@api.post("/events", response=EventOut)
@require_perm("events.add_event")
def create_event(request, payload: EventIn):
    membership = get_membership(request.user)

    department = scope_departments(
        Department.objects.all(), membership
    ).filter(id=payload.department_id).first()
    if department is None:
        raise HttpError(404, "Department not found")

    category = None
    if payload.category_id:
        category = scope_categories(
            Category.objects.all(), membership
        ).filter(id=payload.category_id).first()
        if category is None:
            raise HttpError(404, "Category not found")
        if category.club_id != department.club_id:
            raise HttpError(400, "Category and department must belong to the same club.")

    valid_choices = {value for value, _ in Event.EVENT_TYPE_CHOICES}
    if payload.event_type not in valid_choices:
        raise HttpError(400, f"Unknown event_type: {payload.event_type!r}.")
    valid_scopes = {value for value, _ in Event.SCOPE_CHOICES}
    if payload.scope not in valid_scopes:
        raise HttpError(400, f"Unknown scope: {payload.scope!r}.")

    if payload.ends_at and payload.ends_at < payload.starts_at:
        raise HttpError(400, "ends_at must be on or after starts_at.")

    # Resolve participants — must all belong to the department's club + be visible.
    participants_qs = scope_players(Player.objects.all(), membership).filter(
        category__club=department.club, is_active=True,
    )
    if payload.participant_ids:
        participants_qs = participants_qs.filter(id__in=payload.participant_ids)
        participants = list(participants_qs)
        found_ids = {str(p.id) for p in participants}
        missing = [str(pid) for pid in payload.participant_ids if str(pid) not in found_ids]
        if missing:
            raise HttpError(404, f"Players not found or not accessible: {missing}")
    else:
        participants = []

    event = Event.objects.create(
        club=department.club,
        department=department,
        event_type=payload.event_type,
        title=payload.title,
        description=payload.description,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        location=payload.location,
        scope=payload.scope,
        category=category,
        metadata=payload.metadata or {},
        created_by=request.user if request.user.is_authenticated else None,
    )
    if participants:
        event.participants.set(participants)
    return _serialize_event(event)


@api.patch("/events/{event_id}", response=EventOut)
@require_perm("events.change_event")
def update_event(request, event_id: UUID, payload: EventIn):
    membership = get_membership(request.user)
    event = scope_events(Event.objects.all(), membership).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")

    department = scope_departments(
        Department.objects.all(), membership
    ).filter(id=payload.department_id).first()
    if department is None:
        raise HttpError(404, "Department not found")

    category = None
    if payload.category_id:
        category = scope_categories(
            Category.objects.all(), membership
        ).filter(id=payload.category_id).first()
        if category is None:
            raise HttpError(404, "Category not found")
        if category.club_id != department.club_id:
            raise HttpError(400, "Category and department must belong to the same club.")

    if payload.event_type not in {v for v, _ in Event.EVENT_TYPE_CHOICES}:
        raise HttpError(400, f"Unknown event_type: {payload.event_type!r}.")
    if payload.scope not in {v for v, _ in Event.SCOPE_CHOICES}:
        raise HttpError(400, f"Unknown scope: {payload.scope!r}.")
    if payload.ends_at and payload.ends_at < payload.starts_at:
        raise HttpError(400, "ends_at must be on or after starts_at.")

    event.club = department.club
    event.department = department
    event.event_type = payload.event_type
    event.title = payload.title
    event.description = payload.description
    event.starts_at = payload.starts_at
    event.ends_at = payload.ends_at
    event.location = payload.location
    event.scope = payload.scope
    event.category = category
    event.metadata = payload.metadata or {}
    event.save()

    # Resync participants (full replace — caller sends the desired list).
    participants_qs = scope_players(Player.objects.all(), membership).filter(
        category__club=department.club, is_active=True,
    )
    if payload.participant_ids:
        participants_qs = participants_qs.filter(id__in=payload.participant_ids)
        participants = list(participants_qs)
        found_ids = {str(p.id) for p in participants}
        missing = [str(pid) for pid in payload.participant_ids if str(pid) not in found_ids]
        if missing:
            raise HttpError(404, f"Players not found or not accessible: {missing}")
        event.participants.set(participants)
    else:
        event.participants.clear()
    return _serialize_event(event)


@api.delete("/events/{event_id}")
@require_perm("events.delete_event")
def delete_event(request, event_id: UUID):
    membership = get_membership(request.user)
    event = scope_events(Event.objects.all(), membership).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")
    event.delete()
    return {"deleted": True}


# =============================================================================
# Goals & Alerts
# =============================================================================

from goals.models import (  # noqa: E402
    Alert,
    AlertSource,
    AlertStatus,
    Goal,
    GoalOperator,
    GoalStatus,
)


def _resolve_goal_current_value(goal: Goal) -> tuple[float | None, "datetime | None"]:
    """Latest numeric reading for this goal's (player, template family, field_key).

    Fans out across the template version family so a forked v2 still sees v1
    history. Returns (value, recorded_at) or (None, None) if no reading exists
    or the latest reading has a non-numeric value at that key.
    """
    latest = (
        ExamResult.objects
        .filter(player_id=goal.player_id, template__family_id=goal.template.family_id)
        .order_by("-recorded_at")
        .only("recorded_at", "result_data")
        .first()
    )
    # We want the latest reading that actually HAS a numeric value for this
    # field — not just the latest reading at all. A doctor may have logged a
    # daily-note without setting `peso`; we shouldn't claim the goal has no
    # current value just because of that. Walk newest-first until we find one.
    candidates = (
        ExamResult.objects
        .filter(player_id=goal.player_id, template__family_id=goal.template.family_id)
        .order_by("-recorded_at")
        .only("recorded_at", "result_data")
    )
    for r in candidates.iterator():
        raw = (r.result_data or {}).get(goal.field_key)
        if raw is None or raw == "":
            continue
        try:
            return float(raw), r.recorded_at
        except (TypeError, ValueError):
            continue
    return None, (latest.recorded_at if latest else None)


def _goal_progress(goal: Goal, current_value: float | None) -> dict:
    """Compute {achieved, distance, distance_pct} for a goal against the
    given current value. Returns null fields when current_value is unknown."""
    if current_value is None:
        return {"achieved": None, "distance": None, "distance_pct": None}
    target = float(goal.target_value)
    op = goal.operator
    if op == "<=":
        achieved = current_value <= target
    elif op == "<":
        achieved = current_value < target
    elif op == ">=":
        achieved = current_value >= target
    elif op == ">":
        achieved = current_value > target
    elif op == "==":
        achieved = current_value == target
    else:
        achieved = False
    distance = round(current_value - target, 4)
    pct = round((distance / target) * 100, 2) if target != 0 else None
    return {"achieved": achieved, "distance": distance, "distance_pct": pct}


def _serialize_goal(goal: Goal) -> dict:
    """Find the field's label + unit in the template's config_schema, then
    compute the live current value + progress against the goal's target."""
    label = goal.field_key
    unit = ""
    for field in (goal.template.config_schema or {}).get("fields", []):
        if isinstance(field, dict) and field.get("key") == goal.field_key:
            label = field.get("label") or goal.field_key
            unit = field.get("unit") or ""
            break
    current_value, current_recorded_at = _resolve_goal_current_value(goal)
    return {
        "id": goal.id,
        "player_id": goal.player_id,
        "template_id": goal.template_id,
        "template_name": goal.template.name,
        "field_key": goal.field_key,
        "field_label": label,
        "field_unit": unit,
        "operator": goal.operator,
        "target_value": goal.target_value,
        "due_date": goal.due_date,
        "notes": goal.notes,
        "status": goal.status,
        "last_value": goal.last_value,
        "evaluated_at": goal.evaluated_at,
        "warn_days_before": goal.warn_days_before,
        "created_at": goal.created_at,
        "current_value": current_value,
        "current_recorded_at": current_recorded_at,
        "progress": _goal_progress(goal, current_value),
    }


def _scoped_goals(membership):
    qs = Goal.objects.select_related("template", "player__category")
    if membership is None:
        return qs
    qs = qs.filter(player__category__club=membership.club)
    if not membership.all_categories:
        qs = qs.filter(player__category__in=membership.categories.all())
    if not membership.all_departments:
        qs = qs.filter(template__department__in=membership.departments.all())
    return qs


@api.get("/players/{player_id}/goals", response=list[GoalOut])
def list_player_goals(request, player_id: UUID):
    membership = get_membership(request.user)
    player = scope_players(Player.objects.all(), membership).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    goals = _scoped_goals(membership).filter(player=player).order_by(
        # active first (so overdue ones bubble up), then most recent.
        "-status", "-due_date", "-created_at",
    )
    return [_serialize_goal(g) for g in goals]


@api.post("/goals", response=GoalOut)
@require_perm("goals.add_goal")
def create_goal(request, payload: GoalIn):
    membership = get_membership(request.user)

    player = scope_players(Player.objects.all(), membership).filter(id=payload.player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    template = scope_templates(
        ExamTemplate.objects.all(), membership
    ).filter(id=payload.template_id).first()
    if template is None:
        raise HttpError(404, "Template not found")

    if not template.applicable_categories.filter(pk=player.category_id).exists():
        raise HttpError(400, "Template is not applicable to this player's category.")

    valid_keys = {
        f.get("key")
        for f in (template.config_schema or {}).get("fields", [])
        if isinstance(f, dict) and f.get("key") and f.get("type") in {"number", "calculated"}
    }
    if payload.field_key not in valid_keys:
        raise HttpError(
            400,
            f"field_key must be a numeric/calculated field on this template. "
            f"Available: {', '.join(sorted(valid_keys)) or '(none)'}",
        )

    if payload.operator not in {op for op, _ in GoalOperator.choices}:
        raise HttpError(400, "Invalid operator.")

    goal = Goal.objects.create(
        player=player,
        template=template,
        field_key=payload.field_key,
        operator=payload.operator,
        target_value=payload.target_value,
        due_date=payload.due_date,
        notes=payload.notes or "",
        warn_days_before=payload.warn_days_before,
        created_by=request.user if request.user.is_authenticated else None,
    )
    return _serialize_goal(goal)


@api.patch("/goals/{goal_id}", response=GoalOut)
@require_perm("goals.change_goal")
def update_goal(request, goal_id: UUID, payload: GoalPatchIn):
    membership = get_membership(request.user)
    goal = _scoped_goals(membership).filter(pk=goal_id).first()
    if goal is None:
        raise HttpError(404, "Goal not found")

    fields_to_update = []
    if payload.operator is not None:
        if payload.operator not in {op for op, _ in GoalOperator.choices}:
            raise HttpError(400, "Invalid operator.")
        goal.operator = payload.operator
        fields_to_update.append("operator")
    if payload.target_value is not None:
        goal.target_value = payload.target_value
        fields_to_update.append("target_value")
    if payload.due_date is not None:
        goal.due_date = payload.due_date
        fields_to_update.append("due_date")
    if payload.notes is not None:
        goal.notes = payload.notes
        fields_to_update.append("notes")
    if payload.warn_days_before is not None:
        goal.warn_days_before = payload.warn_days_before or None
        fields_to_update.append("warn_days_before")
    if payload.status is not None:
        # Only manual cancellation is exposed via API; met/missed are
        # evaluator-driven so a human flipping them would corrupt the
        # status timeline.
        if payload.status != GoalStatus.CANCELLED:
            raise HttpError(400, "Status can only be transitioned to 'cancelled' via API.")
        goal.status = GoalStatus.CANCELLED
        fields_to_update.append("status")

    if fields_to_update:
        fields_to_update.append("updated_at")
        goal.save(update_fields=fields_to_update)
        # Cancellation should clean up any pending warning alert.
        if "status" in fields_to_update and goal.status == GoalStatus.CANCELLED:
            from goals.evaluator import _dismiss_active_warning
            _dismiss_active_warning(goal)
    return _serialize_goal(goal)


@api.delete("/goals/{goal_id}")
@require_perm("goals.delete_goal")
def delete_goal(request, goal_id: UUID):
    membership = get_membership(request.user)
    goal = _scoped_goals(membership).filter(pk=goal_id).first()
    if goal is None:
        raise HttpError(404, "Goal not found")
    # Also dismiss any active alerts pointing at this goal — both due-date
    # misses and pre-deadline warnings.
    Alert.objects.filter(
        source_type__in=(AlertSource.GOAL, AlertSource.GOAL_WARNING),
        source_id=goal.id, status=AlertStatus.ACTIVE,
    ).update(status=AlertStatus.DISMISSED, dismissed_at=timezone_now(), dismissed_by=request.user)
    goal.delete()
    return {"deleted": True}


def _scoped_alerts(membership):
    qs = Alert.objects.select_related("player__category")
    if membership is None:
        return qs
    qs = qs.filter(player__category__club=membership.club)
    if not membership.all_categories:
        qs = qs.filter(player__category__in=membership.categories.all())
    return qs


@api.get("/players/{player_id}/alerts", response=list[AlertOut])
def list_player_alerts(request, player_id: UUID, status: str | None = None):
    membership = get_membership(request.user)
    player = scope_players(Player.objects.all(), membership).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    qs = _scoped_alerts(membership).filter(player=player).order_by("-fired_at")
    if status:
        qs = qs.filter(status=status)
    return list(qs)


@api.get("/alerts", response=list[AlertWithPlayerOut])
def list_all_alerts(request, status: str | None = "active", limit: int = 50):
    """List alerts visible to the current user, with embedded player summary.

    Drives the navbar bell dropdown. Defaults to active-only because that's
    what the bell needs; pass `status=dismissed` / `resolved` to fetch
    history. `limit` capped at 200 to keep payloads bounded.
    """
    membership = get_membership(request.user)
    qs = (
        _scoped_alerts(membership)
        .select_related("player__category")
        .order_by("-fired_at")
    )
    if status:
        qs = qs.filter(status=status)
    qs = qs[: max(1, min(int(limit or 50), 200))]
    return [
        {
            "id": a.id,
            "player_id": a.player_id,
            "source_type": a.source_type,
            "source_id": a.source_id,
            "severity": a.severity,
            "status": a.status,
            "message": a.message,
            "fired_at": a.fired_at,
            "last_fired_at": a.last_fired_at,
            "trigger_count": a.trigger_count,
            "dismissed_at": a.dismissed_at,
            "player_first_name": a.player.first_name,
            "player_last_name": a.player.last_name,
            "player_category_name": a.player.category.name,
        }
        for a in qs
    ]


@api.patch("/alerts/{alert_id}", response=AlertOut)
@require_perm("goals.change_alert")
def update_alert(request, alert_id: UUID, payload: AlertPatchIn):
    membership = get_membership(request.user)
    alert = _scoped_alerts(membership).filter(pk=alert_id).first()
    if alert is None:
        raise HttpError(404, "Alert not found")
    if payload.status not in {AlertStatus.DISMISSED, AlertStatus.RESOLVED}:
        raise HttpError(400, "Alert status can only become 'dismissed' or 'resolved'.")
    alert.status = payload.status
    alert.dismissed_at = timezone_now()
    alert.dismissed_by = request.user if request.user.is_authenticated else None
    alert.save(update_fields=["status", "dismissed_at", "dismissed_by"])
    return alert


def timezone_now():
    """Tiny indirection so the goals/alerts block doesn't need to add a top-level import."""
    from django.utils import timezone
    return timezone.now()


# =============================================================================
# Attachments
# =============================================================================

from attachments.models import (  # noqa: E402
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_SIZE,
    Attachment,
    AttachmentSource,
)


def _check_attachment_source_access(
    request, source_type: str, source_id: UUID, mutate: bool
) -> None:
    """Re-uses scoping rules from the source row's domain.

    Reads (mutate=False): membership-scoped reads on the source row.
    Writes (mutate=True): same scoping + extra is_staff gate for contracts
    (matches the contract API's privilege boundary).
    """
    membership = get_membership(request.user)

    if source_type == AttachmentSource.CONTRACT:
        from core.models import Contract

        if mutate and not _has_perm(request.user, "core.change_contract"):
            raise HttpError(403, "No tienes permiso para modificar contratos.")
        contract = (
            Contract.objects
            .filter(player__in=scope_players(Player.objects.all(), membership))
            .filter(pk=source_id)
            .first()
        )
        if contract is None:
            raise HttpError(404, "Source contract not found.")
        return

    if source_type in (AttachmentSource.EXAM_FIELD, AttachmentSource.EXAM_RESULT):
        result = (
            ExamResult.objects
            .filter(template__in=scope_templates(ExamTemplate.objects.all(), membership))
            .filter(player__in=scope_players(Player.objects.all(), membership))
            .filter(pk=source_id)
            .first()
        )
        if result is None:
            raise HttpError(404, "Source exam result not found.")
        return

    if source_type == AttachmentSource.EVENT:
        event = scope_events(Event.objects.all(), membership).filter(pk=source_id).first()
        if event is None:
            raise HttpError(404, "Source event not found.")
        return

    raise HttpError(400, f"Unsupported source_type: {source_type}.")


@api.post("/attachments", response=AttachmentOut)
@require_perm("attachments.add_attachment")
def upload_attachment(
    request,
    file: UploadedFile = File(...),
    source_type: str = Form(...),
    source_id: UUID = Form(...),
    field_key: str = Form(""),
    label: str = Form(""),
):
    """Upload a file to S3 and link it to a source row.

    Validates mime type + size before any S3 write happens.
    """
    if source_type not in {s.value for s in AttachmentSource}:
        raise HttpError(400, f"Invalid source_type. Allowed: {[s.value for s in AttachmentSource]}.")

    _check_attachment_source_access(request, source_type, source_id, mutate=True)

    if file.size and file.size > MAX_UPLOAD_SIZE:
        raise HttpError(
            413,
            f"File too large ({file.size} bytes). Max is {MAX_UPLOAD_SIZE // (1024*1024)} MB.",
        )

    # The browser supplies a content-type but we trust it loosely — the
    # allowlist guards against, e.g., .exe being passed off as PDF. A
    # production hardening pass would use python-magic to sniff the bytes.
    declared_mime = (file.content_type or "").lower()
    if declared_mime and declared_mime not in ALLOWED_MIME_TYPES:
        raise HttpError(415, f"Unsupported file type: {declared_mime}.")

    if source_type == AttachmentSource.EXAM_FIELD and not field_key:
        raise HttpError(400, "field_key is required for source_type='exam_field'.")
    if source_type != AttachmentSource.EXAM_FIELD and field_key:
        raise HttpError(400, "field_key is only allowed for source_type='exam_field'.")

    attachment = Attachment(
        source_type=source_type,
        source_id=source_id,
        field_key=field_key,
        filename=file.name[:200],
        mime_type=declared_mime,
        size_bytes=file.size or 0,
        label=label,
        uploaded_by=request.user if request.user.is_authenticated else None,
    )
    # Save the FileField — django-storages writes to S3 transparently.
    attachment.file.save(file.name, file, save=False)
    attachment.save()
    return attachment


@api.get("/attachments", response=list[AttachmentOut])
def list_attachments(
    request,
    source_type: str,
    source_id: UUID,
    field_key: str = "",
):
    if source_type not in {s.value for s in AttachmentSource}:
        raise HttpError(400, "Invalid source_type.")
    _check_attachment_source_access(request, source_type, source_id, mutate=False)

    qs = Attachment.objects.filter(source_type=source_type, source_id=source_id)
    if field_key:
        qs = qs.filter(field_key=field_key)
    return list(qs)


def _public_signed_get_url(key: str) -> str:
    """Generate a pre-signed S3 GET URL using the PUBLIC endpoint.

    AWS Signature V4 hashes the host header into the signature, so we cannot
    string-rewrite `minio:9000` → `localhost:9000` after the fact (the
    signature would no longer match the new host — the browser sees
    `SignatureDoesNotMatch`). Instead we point a boto3 client at the public
    endpoint directly so the signed URL embeds the right host from the
    start. The backend never actually opens that connection — it just hands
    the URL to the browser via redirect.

    In production, AWS_S3_PUBLIC_ENDPOINT_URL is typically empty (or equal
    to the canonical S3 endpoint), so this picks up the same endpoint as
    the upload client and behaves identically.
    """
    import boto3
    from botocore.client import Config

    public_endpoint = (
        getattr(settings, "AWS_S3_PUBLIC_ENDPOINT_URL", None)
        or getattr(settings, "AWS_S3_ENDPOINT_URL", None)
        or None
    )
    addressing_style = getattr(settings, "AWS_S3_ADDRESSING_STYLE", "path")

    client = boto3.client(
        "s3",
        endpoint_url=public_endpoint,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=getattr(settings, "AWS_S3_REGION_NAME", None),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": addressing_style},
        ),
    )
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key},
        ExpiresIn=getattr(settings, "AWS_QUERYSTRING_EXPIRE", 300),
    )


@api.get("/attachments/{attachment_id}/download")
def download_attachment(request, attachment_id: UUID):
    """Scope-check then redirect to a short-lived signed S3 URL."""
    attachment = Attachment.objects.filter(pk=attachment_id).first()
    if attachment is None:
        raise HttpError(404, "Attachment not found.")
    _check_attachment_source_access(
        request, attachment.source_type, attachment.source_id, mutate=False,
    )

    signed = _public_signed_get_url(attachment.file.name)

    from django.http import HttpResponseRedirect
    return HttpResponseRedirect(signed)


@api.delete("/attachments/{attachment_id}")
@require_perm("attachments.delete_attachment")
def delete_attachment(request, attachment_id: UUID):
    attachment = Attachment.objects.filter(pk=attachment_id).first()
    if attachment is None:
        raise HttpError(404, "Attachment not found.")
    _check_attachment_source_access(
        request, attachment.source_type, attachment.source_id, mutate=True,
    )
    # FileField.delete() removes the underlying object from S3 too.
    attachment.file.delete(save=False)
    attachment.delete()
    return {"deleted": True}


# =============================================================================
# Episodes (clinical / longitudinal sequences on episodic templates)
# =============================================================================

from exams.models import Episode  # noqa: E402


def _serialize_episode(episode: Episode) -> dict:
    latest = (
        ExamResult.objects
        .filter(episode=episode)
        .order_by("-recorded_at")
        .first()
    )
    return {
        "id": episode.id,
        "player_id": episode.player_id,
        "template_id": episode.template_id,
        "template_slug": episode.template.slug or "",
        "template_name": episode.template.name,
        "status": episode.status,
        "stage": episode.stage,
        "title": episode.title,
        "started_at": episode.started_at,
        "ended_at": episode.ended_at,
        "metadata": episode.metadata or {},
        "result_count": ExamResult.objects.filter(episode=episode).count(),
        "latest_result_data": (latest.result_data if latest else {}) or {},
    }


@api.get("/players/{player_id}/episodes", response=list[EpisodeOut])
def list_player_episodes(
    request,
    player_id: str,
    status: str | None = None,
    template_slug: str | None = None,
):
    """List a player's episodes, newest first.

    `status` filters by open|closed. `template_slug` narrows to a single
    episodic template — used by the Lesiones tab to exclude Medicación
    (and any future episodic templates) so injuries stay grouped on
    their own surface.
    """
    membership = get_membership(request.user)
    player = scope_players(Player.objects.all(), membership).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    qs = (
        Episode.objects
        .filter(player=player)
        .filter(template__in=scope_templates(ExamTemplate.objects.all(), membership))
        .select_related("template")
        .order_by("-started_at")
    )
    if status:
        qs = qs.filter(status=status)
    if template_slug:
        qs = qs.filter(template__slug=template_slug)
    return [_serialize_episode(e) for e in qs]


@api.get("/episodes/{episode_id}", response=EpisodeOut)
def get_episode(request, episode_id: str):
    membership = get_membership(request.user)
    episode = (
        Episode.objects
        .filter(template__in=scope_templates(ExamTemplate.objects.all(), membership))
        .filter(player__in=scope_players(Player.objects.all(), membership))
        .filter(pk=episode_id)
        .select_related("template")
        .first()
    )
    if episode is None:
        raise HttpError(404, "Episode not found")
    return _serialize_episode(episode)


@api.get("/episodes/{episode_id}/results", response=list[ResultOut])
def list_episode_results(request, episode_id: str):
    """List every ExamResult linked to this Episode, oldest first.

    The Episode's audit timeline. Used by the UI to show the full progression
    of stage updates within an injury and surface per-result attachments.
    """
    membership = get_membership(request.user)
    episode = (
        Episode.objects
        .filter(template__in=scope_templates(ExamTemplate.objects.all(), membership))
        .filter(player__in=scope_players(Player.objects.all(), membership))
        .filter(pk=episode_id)
        .first()
    )
    if episode is None:
        raise HttpError(404, "Episode not found")

    results = (
        ExamResult.objects
        .filter(episode=episode)
        .select_related("template", "event")
        .order_by("recorded_at")
    )
    return [_serialize_result(r) for r in results]


@api.patch("/episodes/{episode_id}", response=EpisodeOut)
@require_perm("exams.change_episode")
def update_episode(request, episode_id: str, payload: EpisodePatchIn):
    """Force-close an episode without entering a final result.

    Doctors usually progress episodes by submitting new ExamResults. This
    endpoint is the escape hatch for abandoned episodes (e.g. a player
    transferred mid-recovery and the episode never got a 'closed' entry).
    """
    membership = get_membership(request.user)
    episode = (
        Episode.objects
        .filter(template__in=scope_templates(ExamTemplate.objects.all(), membership))
        .filter(player__in=scope_players(Player.objects.all(), membership))
        .filter(pk=episode_id)
        .select_related("template", "player")
        .first()
    )
    if episode is None:
        raise HttpError(404, "Episode not found")

    if payload.status is not None:
        if payload.status != Episode.STATUS_CLOSED:
            raise HttpError(
                400,
                "Episode status can only be transitioned to 'closed' via API; "
                "open / re-open requires a new result.",
            )
        from django.utils import timezone as _tz
        episode.status = Episode.STATUS_CLOSED
        if not episode.ended_at:
            episode.ended_at = _tz.now()
        episode.save(update_fields=["status", "ended_at", "updated_at"])
        # Recompute player.status now that this episode is no longer open.
        from exams.episode_lifecycle import recompute_player_status
        recompute_player_status(episode.player)

    return _serialize_episode(episode)
