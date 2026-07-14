import logging
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404
from ninja import File, Form, NinjaAPI, Query, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.models import (
    Category,
    Club,
    Contract,
    DailyNote,
    Department,
    Player,
    Position,
    StaffMembership,
)
from dashboards.aggregation import position_comparison, resolve_widget
from dashboards.models import DepartmentLayout, TeamReportLayout, Widget
from dashboards.team_aggregation import resolve_team_widget
from events.models import Event
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q

from exams.bulk_ingest import IngestError, run_ingest
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate

from .alert_rules import BacktestIn, RuleUpdateIn, RuleWriteIn
from .auth import issue_token, jwt_auth
from .scoping import (
    get_membership,
    has_full_access,
    scope_categories,
    scope_departments,
    scope_events,
    scope_players,
    scope_players_for_roster,
    scope_positions,
    scope_results,
    scope_templates,
)
from .schemas import (
    AdminUserCreateIn,
    AdminUserCreateOut,
    AdminUserOut,
    AdminUserUpdateIn,
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
    PositionComparisonOut,
    PositionOut,
    AlertOut,
    AlertPatchIn,
    AlertWithPlayerOut,
    AttachmentOut,
    ContractIn,
    ContractOut,
    ContractPatchIn,
    DailyNoteIn,
    DailyNoteOut,
    EpisodeOut,
    EpisodePatchIn,
    GoalIn,
    GoalOut,
    GoalPatchIn,
    ResultIn,
    ResultOut,
    ResultPatchIn,
    MatchReportResponseOut,
    ResetPasswordOut,
    RosterEntryOut,
    RosterReplaceIn,
    TeamReportResponseOut,
    TeamResultsIn,
    TeamResultsOut,
    TemplateOut,
    TriageOut,
    UserOut,
    UsersMetaOut,
)

User = get_user_model()

logger = logging.getLogger(__name__)


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
DATE_WINDOW_MAX_DAYS = 730


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


# ---------------------------------------------------------------------------
# User management — Administración → Usuarios.
#
# A club "manager" (Administrador role group) can create staff users, assign
# them a role + data scope, and reset their passwords — all scoped to their
# own club. Guardrails (enforced below, not just in the UI):
#   * managers only see/touch users in their own StaffMembership.club;
#   * they can never grant a scope wider than their own, nor mint superusers;
#   * assignable roles exclude "Administrador" for non-superusers.
# Superusers (no membership) bypass the club filter and may target any club.
# ---------------------------------------------------------------------------

# Managed role groups, in priority order (a user's "role" is the first of
# these they belong to). Seeded by `core/management/commands/seed_role_groups`.
MANAGED_ROLE_GROUPS = ["Administrador", "Editor", "Solo Lectura"]


def generate_temp_password() -> str:
    """A short, URL-safe temporary password (~12 chars). Emailed to the new
    user and returned once to the caller — never stored in plaintext."""
    return secrets.token_urlsafe(9)


def _assignable_roles(user) -> list[str]:
    """Role groups this requester may assign. Only superusers can hand out
    the "Administrador" (manager) role — a manager can't mint more managers."""
    if user.is_superuser:
        return list(MANAGED_ROLE_GROUPS)
    return ["Editor", "Solo Lectura"]


def _user_role(user) -> str:
    names = set(user.groups.values_list("name", flat=True))
    for role in MANAGED_ROLE_GROUPS:
        if role in names:
            return role
    return ""


def _membership_for(user) -> StaffMembership | None:
    try:
        return user.staff_membership
    except StaffMembership.DoesNotExist:
        return None


def _serialize_admin_user(user) -> dict:
    membership = _membership_for(user)
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "last_login": user.last_login,
        "role": _user_role(user),
        "club": membership.club if membership else None,
        "all_categories": membership.all_categories if membership else False,
        "categories": (
            [{"id": c.id, "name": c.name} for c in membership.categories.all()]
            if membership else []
        ),
        "all_departments": membership.all_departments if membership else False,
        "departments": (
            [{"id": d.id, "name": d.name} for d in membership.departments.all()]
            if membership else []
        ),
    }


def _get_managed_user(requester, membership, user_id: int):
    """Fetch a user the requester is allowed to manage, or raise 404/403.

    Club-scoped requesters only reach users in their own club; nobody but a
    superuser can touch a superuser account."""
    qs = User.objects.filter(pk=user_id)
    if membership is not None:
        qs = qs.filter(staff_membership__club=membership.club)
    target = qs.first()
    if target is None:
        raise HttpError(404, "Usuario no encontrado.")
    if target.is_superuser and not requester.is_superuser:
        raise HttpError(403, "No puedes gestionar a un administrador de plataforma.")
    return target


def _resolve_scope_for_write(requester, membership, club_id, all_cats, cat_ids,
                             all_deps, dep_ids):
    """Validate a requested (club, categories, departments) scope against the
    requester's own grantable scope. Returns
    (club, all_cats, categories, all_deps, departments)."""
    if membership is None:  # superuser / platform admin
        if not club_id:
            raise HttpError(400, "Selecciona un club.")
        club = Club.objects.filter(id=club_id).first()
        if club is None:
            raise HttpError(404, "Club no encontrado.")
        creator_all_cats = creator_all_deps = True
        grantable_cats = grantable_deps = None
    else:
        club = membership.club
        creator_all_cats = membership.all_categories
        creator_all_deps = membership.all_departments
        grantable_cats = (
            None if creator_all_cats
            else {str(x) for x in membership.categories.values_list("id", flat=True)}
        )
        grantable_deps = (
            None if creator_all_deps
            else {str(x) for x in membership.departments.values_list("id", flat=True)}
        )

    if all_cats and not creator_all_cats:
        raise HttpError(403, "No puedes otorgar acceso a todas las categorías.")
    if all_deps and not creator_all_deps:
        raise HttpError(403, "No puedes otorgar acceso a todos los departamentos.")

    categories: list = []
    if not all_cats:
        ids = [str(c) for c in (cat_ids or [])]
        categories = list(Category.objects.filter(club=club, id__in=ids))
        if len(categories) != len(set(ids)):
            raise HttpError(400, "Alguna categoría no pertenece a este club.")
        if grantable_cats is not None:
            for c in categories:
                if str(c.id) not in grantable_cats:
                    raise HttpError(403, "No puedes otorgar una categoría fuera de tu alcance.")

    departments: list = []
    if not all_deps:
        ids = [str(d) for d in (dep_ids or [])]
        departments = list(Department.objects.filter(club=club, id__in=ids))
        if len(departments) != len(set(ids)):
            raise HttpError(400, "Algún departamento no pertenece a este club.")
        if grantable_deps is not None:
            for d in departments:
                if str(d.id) not in grantable_deps:
                    raise HttpError(403, "No puedes otorgar un departamento fuera de tu alcance.")

    return club, all_cats, categories, all_deps, departments


def _validate_role(requester, role: str) -> None:
    if role not in _assignable_roles(requester):
        raise HttpError(400, f"Rol inválido: {role}.")


def _apply_role(user, role: str) -> None:
    """Set the user's managed role group, replacing any existing one."""
    user.groups.remove(*Group.objects.filter(name__in=MANAGED_ROLE_GROUPS))
    grp = Group.objects.filter(name=role).first()
    if grp is not None:
        user.groups.add(grp)


def _dispatch_welcome_email(user_id: int, password: str, reason: str) -> None:
    """Fire-and-forget welcome/reset email. Wrapped so a down broker never
    breaks the create/reset request (same posture as goals/evaluator.py)."""
    try:
        from core.tasks import send_welcome_email
        send_welcome_email.delay(user_id, password, reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("welcome email dispatch failed for user %s: %s", user_id, exc)


@api.get("/users/meta", response=UsersMetaOut)
@require_perm("auth.view_user")
def users_meta(request):
    membership = get_membership(request.user)
    clubs = list(Club.objects.order_by("name")) if membership is None else [membership.club]
    return {"clubs": clubs, "assignable_roles": _assignable_roles(request.user)}


@api.get("/users", response=list[AdminUserOut])
@require_perm("auth.view_user")
def list_users(request, club_id: str | None = None):
    """Staff users the requester can manage. Club-scoped managers see only
    their club; superusers see everyone (optionally filtered by `club_id`)."""
    membership = get_membership(request.user)
    qs = User.objects.all()
    if membership is not None:
        qs = qs.filter(staff_membership__club=membership.club)
    elif club_id:
        qs = qs.filter(staff_membership__club_id=club_id)
    qs = qs.prefetch_related(
        "groups",
        "staff_membership__club",
        "staff_membership__categories",
        "staff_membership__departments",
    ).order_by("first_name", "last_name", "email")
    return [_serialize_admin_user(u) for u in qs]


@api.post("/users", response=AdminUserCreateOut)
@require_perm("auth.add_user")
def create_user(request, payload: AdminUserCreateIn):
    membership = get_membership(request.user)
    _validate_role(request.user, payload.role)
    club, all_cats, categories, all_deps, departments = _resolve_scope_for_write(
        request.user, membership, payload.club_id,
        payload.all_categories, payload.category_ids,
        payload.all_departments, payload.department_ids,
    )

    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HttpError(400, "Ingresá un email válido.")
    if not payload.first_name.strip() or not payload.last_name.strip():
        raise HttpError(400, "Nombre y apellido son requeridos.")
    if User.objects.filter(email__iexact=email).exists() or \
            User.objects.filter(username__iexact=email).exists():
        raise HttpError(400, "Ya existe un usuario con ese email.")

    password = generate_temp_password()
    user = User.objects.create(
        username=email,
        email=email,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        is_active=payload.is_active,
        is_staff=False,
    )
    user.set_password(password)
    user.save(update_fields=["password"])

    membership_row = StaffMembership.objects.create(
        user=user, club=club,
        all_categories=all_cats, all_departments=all_deps,
    )
    if not all_cats:
        membership_row.categories.set(categories)
    if not all_deps:
        membership_row.departments.set(departments)

    _apply_role(user, payload.role)
    _dispatch_welcome_email(user.id, password, "welcome")

    result = _serialize_admin_user(user)
    result["temp_password"] = password
    return result


@api.patch("/users/{user_id}", response=AdminUserOut)
@require_perm("auth.change_user")
def update_user(request, user_id: int, payload: AdminUserUpdateIn):
    membership = get_membership(request.user)
    target = _get_managed_user(request.user, membership, user_id)

    if payload.email is not None:
        email = payload.email.strip().lower()
        if email and email != (target.email or "").lower():
            if "@" not in email:
                raise HttpError(400, "Ingresá un email válido.")
            if User.objects.filter(email__iexact=email).exclude(pk=target.pk).exists() or \
                    User.objects.filter(username__iexact=email).exclude(pk=target.pk).exists():
                raise HttpError(400, "Ya existe un usuario con ese email.")
            target.email = email
            target.username = email
    if payload.first_name is not None:
        target.first_name = payload.first_name.strip()
    if payload.last_name is not None:
        target.last_name = payload.last_name.strip()
    if payload.is_active is not None:
        target.is_active = payload.is_active
    target.save()

    if payload.role is not None:
        _validate_role(request.user, payload.role)
        _apply_role(target, payload.role)

    scope_touched = any(
        f is not None for f in (
            payload.all_categories, payload.category_ids,
            payload.all_departments, payload.department_ids,
        )
    )
    if scope_touched:
        row = StaffMembership.objects.filter(user=target).select_related("club").first()
        if row is not None:
            all_cats = payload.all_categories if payload.all_categories is not None else row.all_categories
            all_deps = payload.all_departments if payload.all_departments is not None else row.all_departments
            cat_ids = (
                payload.category_ids if payload.category_ids is not None
                else list(row.categories.values_list("id", flat=True))
            )
            dep_ids = (
                payload.department_ids if payload.department_ids is not None
                else list(row.departments.values_list("id", flat=True))
            )
            _, all_cats, categories, all_deps, departments = _resolve_scope_for_write(
                request.user, membership,
                str(row.club_id) if membership is None else None,
                all_cats, cat_ids, all_deps, dep_ids,
            )
            row.all_categories = all_cats
            row.all_departments = all_deps
            row.save(update_fields=["all_categories", "all_departments", "updated_at"])
            row.categories.set([] if all_cats else categories)
            row.departments.set([] if all_deps else departments)

    target.refresh_from_db()
    return _serialize_admin_user(target)


@api.post("/users/{user_id}/reset-password", response=ResetPasswordOut)
@require_perm("auth.change_user")
def reset_user_password(request, user_id: int):
    membership = get_membership(request.user)
    target = _get_managed_user(request.user, membership, user_id)
    password = generate_temp_password()
    target.set_password(password)
    target.save(update_fields=["password"])
    _dispatch_welcome_email(target.id, password, "reset")
    return {"temp_password": password}


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
    search: str | None = None,
    limit: int | None = None,
    cross_category: bool = False,
):
    """Default behavior excludes inactive players (consumers like Equipo and
    team reports want roster-only). The configuraciones page passes
    `include_inactive=true` so admins can manage availability.

    `search` does a case-insensitive contains-match on `first_name` /
    `last_name` / `"first last"` — used by the roster picker on the
    match-edit page to find a player across every category. `limit`
    caps the result count (typeahead UX); omit for the full list.

    `cross_category=true` widens visibility to every player in the
    user's club, ignoring the user's category memberships. Used by
    the convocatoria picker on /partidos/[id]/editar so a Primer
    Equipo coach can promote a SUB-20 player even when their
    StaffMembership grants them Primer Equipo only.
    """
    from django.db.models import Q

    membership = get_membership(request.user)
    qs = Player.objects.select_related("category", "position")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    if cross_category:
        qs = scope_players_for_roster(qs, membership)
    else:
        qs = scope_players(qs, membership)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if search:
        # Single-string search hits first_name OR last_name; multi-token
        # query (e.g. "lucas a") matches across both via Concat.
        from django.db.models.functions import Concat
        from django.db.models import Value, CharField
        qs = qs.annotate(
            _full=Concat("first_name", Value(" "), "last_name",
                         output_field=CharField()),
        )
        terms = [t for t in search.strip().split() if t]
        for term in terms:
            qs = qs.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(_full__icontains=term)
            )
    qs = qs.order_by("last_name", "first_name")
    if limit is not None:
        qs = qs[: max(1, min(limit, 100))]
    return qs


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
        "photo_url": player.photo_url or None,
    }


@api.get("/players/{player_id}/triage", response=TriageOut)
def get_player_triage(request, player_id: str):
    """Player snapshot for the Resumen tab — see `api/triage.py` for the
    4-section structure and selection rules. Returns a single payload
    the frontend tab and the PDF generator both consume."""
    from .triage import build_triage_payload

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category", "position"),
        membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    return build_triage_payload(player)


@api.get("/players/{player_id}/resumen-slab")
def get_player_resumen_slab(request, player_id: str):
    """Resumen S-LAB stat cards (FAST, no LLM): jersey number + three season
    cards (estadísticas de juego, rendimiento físico, reporte médico). The
    agent narrative is a SEPARATE endpoint (`/resumen-narrative`) so the cards
    render instantly while the narrative — a ~20s LLM call on a cache miss —
    streams in on its own. All-time over the player's matches."""
    from api.player_summary import build_player_season_summary, player_squad_number

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category__club"), membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    return {
        "number": player_squad_number(player),
        "cards": build_player_season_summary(player),
    }


@api.get("/players/{player_id}/resumen-narrative")
def get_player_resumen_narrative(request, player_id: str):
    """The agents' narrative for the Resumen (estado / preocupaciones /
    recomendaciones). Cached — shares the PDF's content-addressed cache — so
    it's generated at most once per data signature (~20s on a miss, instant
    after). `narrative` is null when the LLM is unavailable; the frontend then
    just renders the cards. Plain dict so model output-shape variance can never
    fail response validation."""
    from dashboards.pdf.player_triage import get_or_build_triage_narrative

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category__club"), membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    return {"narrative": get_or_build_triage_narrative(player)}


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


# {uuid:...} constrains the URL pattern to real UUIDs — with the default
# greedy converter this pattern also matched the literal paths
# "/results/team" and "/results/bulk" (registered later), turning their
# POSTs into 405s. See §7 in STATUS.md.
@api.patch("/results/{uuid:result_id}", response=ResultOut)
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


@api.delete("/results/{uuid:result_id}")
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


@api.get("/results", response=list[ResultOut])
def list_results(
    request,
    template_id: str | None = None,
    event_id: str | None = None,
):
    """Filter ExamResults by `(template_id, event_id)`.

    Today only the team-table prefill consumes this — fetches every
    result for the chosen (template family, match) so the form opens
    with the existing values populated. We fan out across the
    template's `family_id` so reads survive template versioning.
    """
    membership = get_membership(request.user)
    qs = scope_results(ExamResult.objects.select_related("template", "event"), membership)
    if template_id:
        try:
            template = scope_templates(
                ExamTemplate.objects.all(), membership,
            ).filter(id=template_id).first()
        except (TypeError, ValueError):
            template = None
        if template is None:
            raise HttpError(404, "Template not found")
        qs = qs.filter(template__family_id=template.family_id)
    if event_id:
        try:
            qs = qs.filter(event_id=event_id)
        except (TypeError, ValueError):
            raise HttpError(400, "Invalid event_id")
    return [_serialize_result(r) for r in qs.order_by("recorded_at")]


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
    updated: list[ExamResult] = []
    skipped = 0

    with db_transaction.atomic():
        # When the submission is event-scoped, look up existing
        # ExamResults across the template family so we update rather
        # than duplicate. The unique conceptual key is
        # (player, template family, event) — a player has at most one
        # rendimiento_de_partido per match.
        existing_by_player: dict[UUID, ExamResult] = {}
        if event is not None:
            for er in ExamResult.objects.filter(
                template__family_id=template.family_id,
                event_id=event.id,
                player_id__in=submitted_player_ids,
            ).select_related("template"):
                existing_by_player[er.player_id] = er

        for row in payload.rows:
            if is_blank(row.result_data):
                skipped += 1
                continue
            merged = {**(payload.shared_data or {}), **row.result_data}
            target_player = valid_players[row.player_id]
            result_data, inputs_snapshot = compute_result_data(
                template, merged, player=target_player,
            )
            existing = existing_by_player.get(target_player.id)
            if existing is not None:
                existing.result_data = result_data
                existing.inputs_snapshot = inputs_snapshot
                # Keep the original recorded_at unless the event
                # itself moved — `effective_recorded_at` mirrors
                # event.starts_at when an event is bound.
                existing.recorded_at = effective_recorded_at
                # Template version may have evolved between original
                # write and this edit — point at the current active
                # version so dashboards using the active schema
                # see the new shape.
                existing.template = template
                existing.save()
                updated.append(existing)
            else:
                result = ExamResult.objects.create(
                    player=target_player,
                    template=template,
                    recorded_at=effective_recorded_at,
                    result_data=result_data,
                    inputs_snapshot=inputs_snapshot,
                    event=event,
                )
                created.append(result)

        if (created or updated) and not template.is_locked:
            template.is_locked = True
            template.save(update_fields=["is_locked"])

    return {
        "created": len(created),
        "updated": len(updated),
        "skipped": skipped,
        "results": [_serialize_result(r) for r in (created + updated)],
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


# NB: path lives OUTSIDE /results/ on purpose — django-ninja's
# /results/{result_id} converter is greedy ([^/]+) and would shadow a
# /results/<literal> POST (the same quirk that currently masks /results/bulk
# and /results/team — see the routing note in STATUS).
@api.post("/gps-sessions/upload")
@require_perm("exams.add_examresult")
def gps_session_upload(
    request,
    file: UploadedFile = File(...),
    category_id: str = Form(...),
    template_id: str = Form(""),
    kind: str = Form("match"),
    dry_run: bool = Form(True),
):
    """Self-service per-session GPS upload (match or training).

    Unlike `/results/bulk` (one result per player), this groups by
    (player, session) so a player in both the main session and a reintegro on
    the same day gets two results. Dates come from the session labels (or the
    `Days` column on match exports).

    `kind="match"` creates/links a match Event per match-day; `kind="training"`
    stores flat dated results (no Event). `dry_run=True` returns a preview.
    Idempotent (match: per player+day; training: per player+day+session).
    """
    from exams import gps_session_ingest
    from exams.gps_session import GpsParseError

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.all(), membership
    ).filter(id=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    qs = scope_templates(ExamTemplate.objects.select_related("department"), membership)
    if template_id:
        template = qs.filter(id=template_id).first()
    else:
        # Matches and trainings live on separate templates: gps_partido
        # (event-linked) vs gps_sesion. Same field keys on both.
        slug = "gps_partido" if kind == "match" else "gps_sesion"
        template = qs.filter(slug=slug, department__club=category.club).first()
    if template is None:
        raise HttpError(404, (
            "Plantilla GPS de partido no encontrada (corre seed_gps_partido)."
            if kind == "match" else
            "Plantilla GPS de entrenamiento no encontrada (corre seed_gps_session)."
        ))

    try:
        file_bytes = file.read()
    finally:
        file.close()

    try:
        return gps_session_ingest.run(
            file_bytes, template=template, category=category,
            dry_run=dry_run, create_events=(kind == "match"),
            department=template.department, include_rows=True,
            # The selector is authoritative — don't let file-shape auto-detect
            # override "Partido" (else a no-Days file silently runs as training
            # and the missing-match check never fires).
            mode=("match" if kind == "match" else "training"),
            # UI requires a real match Event per match-day — never auto-create.
            auto_create_events=False,
        )
    except GpsParseError as exc:
        raise HttpError(400, str(exc))


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
    ).exclude(
        # Bulk-ingest-only templates (e.g. the legacy per-half match GPS
        # export) have no manual-entry form — offering a "+" button for
        # them just opens a dead registrar.
        input_config__input_modes=["bulk_ingest"],
    )
    if department:
        qs = qs.filter(department__slug=department)
    return qs.distinct()


@api.get("/players/{player_id}/summary")
def get_player_summary(request, player_id: str):
    """Aggregate summary card payload for the player profile's Resumen tab.

    Pulls match stats from `rendimiento_de_partido`, physical metrics from
    `gps_partido`, and the latest 3 injury episodes
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
        slug="gps_partido",
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
                "distance_avg_m": _avg([r.get("tot_dist") for r in gps_results]),
                "max_velocity_avg": _avg([r.get("max_vel") for r in gps_results]),
                "hiaa_avg": _avg([r.get("hiaa") for r in gps_results]),
                "hmld_avg": _avg([r.get("hmld") for r in gps_results]),
                "acc_avg": _avg([r.get("acc") for r in gps_results]),
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
    before each widget runs its aggregation. Capped at 730 days; widgets like
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


@api.get(
    "/players/{player_id}/widgets/{widget_id}/position-comparison",
    response=PositionComparisonOut,
)
def get_position_comparison(request, player_id: str, widget_id: str, key: str):
    """Same-position peer series for one widget field, fetched on demand
    when the user flips a chart's comparison toggle.

    `key` is the composite series key the chart already uses:
    `<data_source_id>::<field_key>`.
    """
    membership = get_membership(request.user)
    player = (
        scope_players(
            Player.objects.select_related("category", "position"), membership
        )
        .filter(id=player_id)
        .first()
    )
    if player is None:
        raise HttpError(404, "Player not found")

    widget = (
        Widget.objects.filter(id=widget_id)
        .prefetch_related("data_sources__template")
        .first()
    )
    if widget is None:
        raise HttpError(404, "Widget not found")

    source_id, sep, field_key = key.partition("::")
    if not sep or not field_key:
        raise HttpError(422, "Malformed key — expected '<source_id>::<field_key>'")
    source = next(
        (s for s in widget.data_sources.all() if str(s.id) == source_id), None
    )
    if source is None:
        raise HttpError(404, "Data source not found on this widget")
    if not scope_templates(
        ExamTemplate.objects.filter(pk=source.template_id), membership
    ).exists():
        raise HttpError(404, "Template not accessible")

    return position_comparison(source, field_key, player)


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
    match_ids: str | None = None,
):
    """Return the active TeamReportLayout for `(department, category)`.

    Resolved server-side: every widget's payload is computed by the team
    aggregation registry and returned in `data`. Returns `{layout: null}`
    when no active layout exists so the frontend renders the placeholder.

    Optional filters (all applied uniformly across every widget):
      - `position_id`: narrows roster to players at this position.
      - `player_ids`: comma-separated UUIDs; further narrows roster.
      - `date_from` / `date_to`: ISO-8601 dates bounding ExamResult
        `recorded_at`. Capped at 730 days at the API layer. `status_counts`
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
        .filter(department=dept, category=category, scope="period", is_active=True)
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
    selector_mode = (raw_cfg.get("mode") or "single").lower()
    if selector_mode not in {"single", "multi"}:
        selector_mode = "single"
    selector_event_type = (
        raw_cfg.get("event_type") or Event.TYPE_MATCH
    )
    # `show_recent <= 0` means "no limit" — capped at 500 so a misconfig
    # can't load thousands of rows into the dropdown. Positive values keep
    # the original soft-cap-50 ceiling. Use explicit `is None` so a
    # configured `0` doesn't get coalesced back to the default 10.
    raw_show_recent_val = raw_cfg.get("show_recent")
    raw_show_recent = 10 if raw_show_recent_val is None else int(raw_show_recent_val)
    if raw_show_recent <= 0:
        selector_show_recent = 500
    else:
        selector_show_recent = max(1, min(raw_show_recent, 50))
    selector_past_only = bool(raw_cfg.get("past_only"))
    selector_label = raw_cfg.get("label") or "Partido"

    selector_options: list[Event] = []
    parsed_match_id: _UUID | None = None
    parsed_match_ids: list[_UUID] = []
    if selector_enabled:
        # Recent matches in scope: matches tied to this category, of the
        # configured event_type, newest first. Soft cap via show_recent.
        # `past_only` clips out scheduled / future matches — useful for
        # views that aggregate finished-match data only.
        from django.utils import timezone as _tz
        options_qs = Event.objects.filter(
            club_id=category.club_id,
            event_type=selector_event_type,
            category_id=category.id,
        )
        if selector_past_only:
            options_qs = options_qs.filter(starts_at__lte=_tz.now())
        selector_options = list(
            options_qs.order_by("-starts_at")[:selector_show_recent]
        )
        option_ids = {e.id for e in selector_options}

        if selector_mode == "multi":
            # Multi-mode: parse comma-separated match_ids, intersect with
            # the visible options. Stale / out-of-scope IDs are dropped
            # silently — same defensive posture as position_id / player_ids.
            if match_ids:
                for raw in match_ids.split(","):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        candidate = _UUID(raw)
                    except (TypeError, ValueError):
                        continue
                    if candidate in option_ids and candidate not in parsed_match_ids:
                        parsed_match_ids.append(candidate)
            # Required + nothing valid passed → default to ALL options
            # so the page renders the full season aggregate on first load.
            # `match_ids is None` means the URL didn't carry the param at
            # all (first load); `match_ids == ""` means the user explicitly
            # cleared their selection (Limpiar button) — respect that and
            # don't second-guess them with an auto-fill.
            param_absent = match_ids is None
            if (
                selector_required
                and not parsed_match_ids
                and selector_options
                and param_absent
            ):
                parsed_match_ids = [e.id for e in selector_options]
        else:
            # Single-mode: existing behavior.
            if match_id:
                try:
                    candidate = _UUID(match_id)
                except (TypeError, ValueError):
                    candidate = None
                if candidate is not None and candidate in option_ids:
                    parsed_match_id = candidate
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
                        event_ids=parsed_match_ids or None,
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
                "mode": selector_mode,
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
                "selected_ids": parsed_match_ids,
            },
        }
    }


@api.get("/matches/{event_id}/report", response=MatchReportResponseOut)
def get_match_report(request, event_id: str, position_id: str | None = None):
    """Return the combined, cross-department MATCH report for one match.

    This is the `scope="match"` TeamReportLayout (department=None, one per
    category) shown in the Partidos view. Unlike `GET /reports/{slug}`, the
    match is NOT chosen in-page — it's locked to `event_id`, which the route
    injects into every widget. No match selector is returned.

    Returns `{layout: null}` when the event isn't a match, has no category,
    or the category has no match-report layout — so the Partidos view can
    render a placeholder instead of erroring.
    """
    from uuid import UUID as _UUID

    membership = get_membership(request.user)

    try:
        parsed_event_id = _UUID(event_id)
    except (TypeError, ValueError):
        raise HttpError(404, "Match not found")

    event = (
        Event.objects.select_related("category", "category__club")
        .filter(pk=parsed_event_id, event_type=Event.TYPE_MATCH)
        .first()
    )
    if event is None or event.category_id is None:
        return {"layout": None}

    # Auth: the caller must be able to see this match's category.
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=event.category_id).first()
    if category is None:
        raise HttpError(404, "Match not found")

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

    layout = (
        TeamReportLayout.objects
        .filter(category=category, scope="match", is_active=True)
        .select_related("category")
        .prefetch_related("sections__widgets")
        .first()
    )
    if layout is None:
        return {"layout": None}

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
                        # Locked to this match — no date window, no selector.
                        event_id=event.id,
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
            "department": None,
            "category": category,
            "name": layout.name,
            "sections": sections_payload,
            "match": {
                "id": event.id,
                "title": event.title,
                "starts_at": event.starts_at,
                "location": event.location or "",
            },
        }
    }


# ---------- PDF reports ----------


@api.get("/reports/{department_slug}/team.docx")
def download_team_report_docx(
    request,
    department_slug: str,
    category_id: str,
    position_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    player_ids: str | None = None,
    match_id: str | None = None,
):
    """Render the team-view report as an editable Word document (landscape).

    Same filter inputs as `GET /reports/{slug}` so the download button
    can pass through the exact URL query params the user is already
    looking at. Auth scoping mirrors the JSON endpoint.
    """
    from uuid import UUID as _UUID

    from django.http import HttpResponse

    from dashboards.docx.team_report_docx import render_team_docx

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

    docx_bytes = render_team_docx(
        department=dept,
        category=category,
        position_id=parsed_position_id,
        player_ids=parsed_player_ids or None,
        date_from=parsed_from,
        date_to=parsed_to,
        event_id=parsed_match_id,
    )

    filename = f"reporte-{department_slug}-{category.name}.docx".replace(" ", "_")
    response = HttpResponse(docx_bytes, content_type=_DOCX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# Word (OOXML) MIME type for the editable report downloads.
_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class ChatMessageIn(Schema):
    role: str
    content: str


class TeamAssistantIn(Schema):
    category_id: str
    messages: list[ChatMessageIn]


@api.post("/assistant/team")
def team_assistant(request, payload: TeamAssistantIn):
    """Floating team assistant — answers free-form questions about the squad,
    grounded in the category's live snapshot (Centro de mando data + roster).
    Stateless: the client sends the full conversation each turn."""
    from dashboards.assistant import answer_team_question

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=payload.category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    reply = answer_team_question(
        category, [{"role": m.role, "content": m.content} for m in payload.messages],
    )
    return {"reply": reply}


class DashboardAssistantIn(Schema):
    category_id: str
    department_slug: str
    messages: list[ChatMessageIn]
    position_id: str | None = None
    player_ids: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None


@api.post("/assistant/dashboard")
def dashboard_assistant(request, payload: DashboardAssistantIn):
    """Embedded, department-scoped Dashboard assistant: answers questions AND can
    propose charts (rendered transiently; promotable to the panel). Returns
    `{reply, charts}`. Separate from the floating team chat — only this view-bound
    surface visualizes. Filters mirror the report endpoint so a proposed chart
    respects the panel's current position/player/date scope."""
    from uuid import UUID as _UUID

    from dashboards.assistant import answer_dashboard_question

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=payload.category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    dept = scope_departments(
        Department.objects.filter(club_id=category.club_id), membership,
    ).filter(slug=payload.department_slug).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    position_id = None
    if payload.position_id:
        try:
            position_id = _UUID(payload.position_id)
        except (TypeError, ValueError):
            position_id = None
    player_ids: list | None = None
    if payload.player_ids:
        player_ids = []
        for pid in payload.player_ids:
            try:
                player_ids.append(_UUID(pid))
            except (TypeError, ValueError):
                continue
    date_from, date_to = _parse_date_window(payload.date_from, payload.date_to)

    return answer_dashboard_question(
        category,
        dept,
        [{"role": m.role, "content": m.content} for m in payload.messages],
        position_id=position_id,
        player_ids=player_ids,
        date_from=date_from,
        date_to=date_to,
    )


class PlayerAssistantIn(Schema):
    player_id: str
    department_slug: str
    messages: list[ChatMessageIn]
    date_from: str | None = None
    date_to: str | None = None


@api.post("/assistant/player")
def player_assistant(request, payload: PlayerAssistantIn):
    """Per-player profile assistant (V4): answers about ONE player + proposes
    per-player charts (promotable to the department's profile layout, rendered
    per player). Scoped to the player's category + the user's departments."""
    from dashboards.assistant import answer_player_question

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category__club"), membership,
    ).filter(pk=payload.player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    dept = scope_departments(
        Department.objects.filter(club_id=player.category.club_id), membership,
    ).filter(slug=payload.department_slug).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    date_from, date_to = _parse_date_window(payload.date_from, payload.date_to)
    return answer_player_question(
        player,
        dept,
        [{"role": m.role, "content": m.content} for m in payload.messages],
        date_from=date_from,
        date_to=date_to,
    )


class PlayerResumenAssistantIn(Schema):
    player_id: str
    messages: list[ChatMessageIn]
    date_from: str | None = None
    date_to: str | None = None


@api.post("/assistant/player/resumen")
def player_resumen_assistant(request, payload: PlayerResumenAssistantIn):
    """Cross-department per-player assistant for the Resumen tab: answers about
    ONE player across ALL areas + proposes per-player charts to review inline
    (transient — the Resumen view is not a configurable layout, so charts are
    NOT promotable). Scoped to the user's visible players."""
    from dashboards.assistant import answer_player_resumen_question

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category__club"), membership,
    ).filter(pk=payload.player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    date_from, date_to = _parse_date_window(payload.date_from, payload.date_to)
    return answer_player_resumen_question(
        player,
        [{"role": m.role, "content": m.content} for m in payload.messages],
        date_from=date_from,
        date_to=date_to,
    )


class PromoteChartIn(Schema):
    category_id: str
    spec: dict


class WidgetArrangeIn(Schema):
    column_span: int | None = None
    title: str | None = None
    sort_order: int | None = None
    section_id: str | None = None


class WidgetReorderIn(Schema):
    widget_ids: list[str]


class WidgetConfigIn(Schema):
    """Edit a widget's config in place (§5) — same spec shape as promote."""
    spec: dict


@api.post("/reports/{department_slug}/widgets")
@require_perm("dashboards.add_teamreportwidget")
def promote_chart(request, department_slug: str, payload: PromoteChartIn):
    """V3 — "Promover al panel": persist a proposed chart's echoed `spec` as a
    real TeamReportWidget (+ data sources) on the department's active layout,
    under a "Mis gráficos" section (created on demand). Editor-gated; scoped to
    the user's club. Returns the created widget/section/layout ids."""
    from dashboards.chart_spec import promote_chart_spec

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=payload.category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    dept = scope_departments(
        Department.objects.filter(club_id=category.club_id), membership,
    ).filter(slug=department_slug).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    result = promote_chart_spec(category=category, department=dept, spec=payload.spec)
    if result.get("error"):
        raise HttpError(400, result["error"])
    return result


# ── Panel builder — arrange existing team-report widgets (§2.c) ──────────────
# NOTE: the literal /reports/widgets/reorder MUST be registered before the
# /reports/widgets/{widget_id} param route, or Django's pattern resolver
# swallows "reorder" as a widget_id (405). Same lesson as /alert-rules/backtest.


@api.post("/reports/widgets/reorder")
@require_perm("dashboards.change_teamreportwidget")
def reorder_team_widgets(request, payload: WidgetReorderIn):
    """Bulk-assign sort_order from the given widget order (drag-reorder)."""
    from dashboards.models import TeamReportWidget

    widgets = list(
        TeamReportWidget.objects
        .select_related("section__layout__department__club")
        .filter(pk__in=payload.widget_ids)
    )
    for w in widgets:
        _club_access_or_403(request, w.section.layout.department.club)
    order = {wid: i for i, wid in enumerate(payload.widget_ids)}
    for w in widgets:
        w.sort_order = order.get(str(w.id), w.sort_order)
    TeamReportWidget.objects.bulk_update(widgets, ["sort_order"])
    return {"ok": True, "updated": len(widgets)}


@api.patch("/reports/widgets/{widget_id}")
@require_perm("dashboards.change_teamreportwidget")
def update_team_widget(request, widget_id: str, payload: WidgetArrangeIn):
    """Resize (column_span 1–12), rename, reorder or move a widget between
    sections of the same layout."""
    from dashboards.models import TeamReportSection, TeamReportWidget

    w = (
        TeamReportWidget.objects
        .select_related("section__layout__department__club")
        .filter(pk=widget_id).first()
    )
    if w is None:
        raise HttpError(404, "Widget no encontrado.")
    _club_access_or_403(request, w.section.layout.department.club)

    data = payload.dict(exclude_unset=True)
    if data.get("column_span") is not None:
        w.column_span = max(1, min(int(data["column_span"]), 12))
    if data.get("title") is not None:
        w.title = str(data["title"])[:160]
    if data.get("sort_order") is not None:
        w.sort_order = max(0, int(data["sort_order"]))
    if data.get("section_id"):
        sec = TeamReportSection.objects.filter(
            pk=data["section_id"], layout=w.section.layout,
        ).first()
        if sec is None:
            raise HttpError(404, "Sección no encontrada.")
        w.section = sec
    w.save()
    return {"ok": True, "id": str(w.id), "column_span": w.column_span, "sort_order": w.sort_order}


@api.delete("/reports/widgets/{widget_id}")
@require_perm("dashboards.delete_teamreportwidget")
def delete_team_widget(request, widget_id: str):
    from dashboards.models import TeamReportWidget

    w = (
        TeamReportWidget.objects
        .select_related("section__layout__department__club")
        .filter(pk=widget_id).first()
    )
    if w is None:
        raise HttpError(404, "Widget no encontrado.")
    _club_access_or_403(request, w.section.layout.department.club)
    w.delete()
    return {"ok": True}


@api.get("/reports/widgets/{widget_id}/config")
@require_perm("dashboards.change_teamreportwidget")
def get_team_widget_config(request, widget_id: str):
    """Read a widget's editable config to pre-fill the edit modal (§5)."""
    from dashboards.chart_spec import widget_config
    from dashboards.models import TeamReportWidget

    w = (
        TeamReportWidget.objects
        .select_related("section__layout__department__club")
        .filter(pk=widget_id).first()
    )
    if w is None:
        raise HttpError(404, "Widget no encontrado.")
    _club_access_or_403(request, w.section.layout.department.club)
    return widget_config(w)


@api.patch("/reports/widgets/{widget_id}/config")
@require_perm("dashboards.change_teamreportwidget")
def update_team_widget_config(request, widget_id: str, payload: WidgetConfigIn):
    """Apply a new spec (chart type / metric(s) / title) to an existing widget,
    preserving its layout position (§5)."""
    from dashboards.chart_spec import edit_chart_spec
    from dashboards.models import TeamReportWidget

    w = (
        TeamReportWidget.objects
        .select_related("section__layout__department__club", "section__layout__category")
        .filter(pk=widget_id).first()
    )
    if w is None:
        raise HttpError(404, "Widget no encontrado.")
    _club_access_or_403(request, w.section.layout.department.club)
    result = edit_chart_spec(widget=w, category=w.section.layout.category, spec=payload.spec)
    if result.get("error"):
        raise HttpError(400, result["error"])
    return result


@api.get("/reports/{department_slug}/widget-options")
@require_perm("dashboards.add_teamreportwidget")
def team_widget_options(request, department_slug: str, category_id: str):
    """Form vocab for 'add widget': the category's templates + numeric fields,
    plus the chart types the builder offers. (department_slug scopes access.)"""
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

    numeric_types = {"number", "calculated"}
    templates = []
    for t in (
        ExamTemplate.objects.filter(applicable_categories=category, is_active_version=True)
        .select_related("department").order_by("department__name", "name").distinct()
    ):
        fields = (t.config_schema or {}).get("fields", []) or []
        numeric = [
            {"key": f["key"], "label": f.get("label") or f["key"], "unit": f.get("unit", "")}
            for f in fields
            if isinstance(f, dict) and f.get("type") in numeric_types and f.get("key")
        ]
        if numeric:
            templates.append({
                "slug": t.slug, "name": t.name, "department": t.department.name,
                "numeric_fields": numeric,
            })
    chart_types = [
        {"value": "team_leaderboard", "label": "Ranking por jugador", "multi_field": False},
        {"value": "team_horizontal_comparison", "label": "Comparación por jugador", "multi_field": True},
        {"value": "team_roster_matrix", "label": "Tabla de plantel", "multi_field": True},
    ]
    return {"templates": templates, "chart_types": chart_types}


@api.get("/reports/{department_slug}/forecast-accuracy")
def report_forecast_accuracy(
    request, department_slug: str, category_id: str,
    date_from: str = "", date_to: str = "",
):
    """§3.2 — injury return-prognosis accuracy (bias + MAE) for the department's
    category, over an optional period (filters on the real availability date)."""
    from api.injury_forecast import _to_date, forecast_accuracy

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

    return forecast_accuracy(
        category=category, department=dept,
        date_from=_to_date(date_from) if date_from else None,
        date_to=_to_date(date_to) if date_to else None,
    )


# ── Panel builder — arrange per-player profile widgets (§5b) ─────────────────
# Mirror of the team arrange endpoints for the Widget model. Same 405 lesson:
# /players/widgets/reorder is registered before /players/widgets/{widget_id}.


def _player_widget_or_404(request, widget_id):
    from dashboards.models import Widget
    w = (
        Widget.objects
        .select_related("section__layout__department__club", "section__layout__category")
        .filter(pk=widget_id).first()
    )
    if w is None:
        raise HttpError(404, "Widget no encontrado.")
    _club_access_or_403(request, w.section.layout.department.club)
    return w


@api.post("/players/widgets/reorder")
@require_perm("dashboards.change_widget")
def reorder_player_widgets(request, payload: WidgetReorderIn):
    from dashboards.models import Widget
    widgets = list(
        Widget.objects.select_related("section__layout__department__club")
        .filter(pk__in=payload.widget_ids)
    )
    for w in widgets:
        _club_access_or_403(request, w.section.layout.department.club)
    order = {wid: i for i, wid in enumerate(payload.widget_ids)}
    for w in widgets:
        w.sort_order = order.get(str(w.id), w.sort_order)
    Widget.objects.bulk_update(widgets, ["sort_order"])
    return {"ok": True, "updated": len(widgets)}


@api.patch("/players/widgets/{widget_id}")
@require_perm("dashboards.change_widget")
def update_player_widget(request, widget_id: str, payload: WidgetArrangeIn):
    from dashboards.models import LayoutSection
    w = _player_widget_or_404(request, widget_id)
    data = payload.dict(exclude_unset=True)
    if data.get("column_span") is not None:
        w.column_span = max(1, min(int(data["column_span"]), 12))
    if data.get("title") is not None:
        w.title = str(data["title"])[:160]
    if data.get("sort_order") is not None:
        w.sort_order = max(0, int(data["sort_order"]))
    if data.get("section_id"):
        sec = LayoutSection.objects.filter(pk=data["section_id"], layout=w.section.layout).first()
        if sec is None:
            raise HttpError(404, "Sección no encontrada.")
        w.section = sec
    w.save()
    return {"ok": True, "id": str(w.id), "column_span": w.column_span, "sort_order": w.sort_order}


@api.delete("/players/widgets/{widget_id}")
@require_perm("dashboards.delete_widget")
def delete_player_widget(request, widget_id: str):
    w = _player_widget_or_404(request, widget_id)
    w.delete()
    return {"ok": True}


class PromotePlayerChartIn(Schema):
    department_slug: str
    spec: dict


@api.post("/players/{player_id}/dashboard-widgets")
@require_perm("dashboards.add_widget")
def promote_player_chart(request, player_id: str, payload: PromotePlayerChartIn):
    """V4 — promote a per-player chart: persist its spec as a real per-player
    Widget on the department's DepartmentLayout, under a "Mis gráficos" section
    (rendered per player across the category). Editor-gated; scoped to the
    player's club."""
    from dashboards.chart_spec import promote_player_chart_spec

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category__club"), membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    dept = scope_departments(
        Department.objects.filter(club_id=player.category.club_id), membership,
    ).filter(slug=payload.department_slug).first()
    if dept is None:
        raise HttpError(404, "Department not found")

    result = promote_player_chart_spec(
        category=player.category, department=dept, spec=payload.spec
    )
    if result.get("error"):
        raise HttpError(400, result["error"])
    return result


@api.get("/briefing")
def briefing(request, category_id: str):
    """Centro de mando AI Briefing — ranked recommendation cards generated by
    the department agents from the squad's live data. Cached; fetched lazily
    by the dashboard so it never blocks the initial render."""
    from dashboards.briefing import generate_briefing

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    return {"items": generate_briefing(category)}


@api.get("/events/{event_id}/match-data")
def event_match_data(request, event_id: str):
    """Imported results + tactical data (API-Football) for a match Event:
    score, both lineups + formations, the events timeline, and team match
    statistics. `has_data=False` when nothing has been synced for it."""
    membership = get_membership(request.user)
    event = scope_events(
        Event.objects.select_related("category"), membership,
    ).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")

    md = getattr(event, "match_data", None)
    meta = event.metadata or {}
    if md is None:
        return {"has_data": False, "competition": meta.get("competition"),
                "score": meta.get("score"), "status": meta.get("status")}

    def _lineup(l: dict) -> dict:
        team = l.get("team") or {}
        def _xi(rows):
            out = []
            for p in rows or []:
                pl = p.get("player") or {}
                out.append({"name": pl.get("name"), "number": pl.get("number"), "pos": pl.get("pos")})
            return out
        return {
            "team": team.get("name"), "team_id": team.get("id"),
            "formation": l.get("formation"),
            "coach": (l.get("coach") or {}).get("name"),
            "start_xi": _xi(l.get("startXI")),
            "substitutes": _xi(l.get("substitutes")),
        }

    def _event(e: dict) -> dict:
        t = e.get("time") or {}
        return {
            "minute": t.get("elapsed"), "extra": t.get("extra"),
            "team": (e.get("team") or {}).get("name"),
            "player": (e.get("player") or {}).get("name"),
            "assist": (e.get("assist") or {}).get("name"),
            "type": e.get("type"), "detail": e.get("detail"),
        }

    def _team_stats(s: dict) -> dict:
        return {
            "team": (s.get("team") or {}).get("name"),
            "stats": [
                {"type": x.get("type"), "value": x.get("value")}
                for x in (s.get("statistics") or [])
            ],
        }

    return {
        "has_data": True,
        "competition": meta.get("competition"),
        "status": meta.get("status"),
        "score": meta.get("score"),
        "is_home": meta.get("is_home"),
        "opponent": meta.get("opponent"),
        "synced_at": md.synced_at.isoformat() if md.synced_at else None,
        "lineups": [_lineup(l) for l in (md.lineups or [])],
        "events": [_event(e) for e in (md.events or [])],
        "team_statistics": [_team_stats(s) for s in (md.team_statistics or [])],
    }


@api.get("/roster")
def roster(request, category_id: str):
    """Plantel roster with per-player readiness / wellness / ACWR / forma +
    status counts, for the Equipo view."""
    from api.roster import build_roster

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    return build_roster(category)


@api.get("/command-center")
def command_center(request, category_id: str):
    """Centro de mando dashboard — one aggregated read of the squad's
    availability, competitive risk, microcycle load (ACWR), wellness, data
    quality, squad status, and the players requiring a decision. Built from
    data SLAB already owns (player state, alerts, events, GPS, wellness)."""
    from api.command_center import build_command_center

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    return build_command_center(category)


# ── Alert & Threshold editor (§1.g) — Editor-role gated ──────────────────────


def _flatten_validation(exc: DjangoValidationError) -> str:
    """Django ValidationError → a single human message for HttpError(422)."""
    msgs: list[str] = []
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for e in errs:
                msgs.append(e if field == "__all__" else f"{field}: {e}")
    elif hasattr(exc, "messages"):
        msgs = list(exc.messages)
    return "; ".join(msgs) or "Configuración inválida."


def _club_access_or_403(request, club) -> None:
    if request.user.is_superuser:
        return
    membership = get_membership(request.user)
    if membership is None or membership.club_id != club.id:
        raise HttpError(403, "Sin acceso a este club.")


def _resolve_rule_template(request, template_id: str, category_id: str | None):
    """(template, category|None) for a write/backtest, club-access enforced."""
    template = (
        ExamTemplate.objects.filter(pk=template_id)
        .select_related("department__club").first()
    )
    if template is None:
        raise HttpError(404, "Plantilla no encontrada.")
    _club_access_or_403(request, template.department.club)
    category = None
    if category_id:
        category = Category.objects.filter(
            pk=category_id, club=template.department.club,
        ).first()
        if category is None:
            raise HttpError(404, "Categoría no encontrada.")
    return template, category


def _scoped_category_or_404(request, category_id: str):
    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    return category


@api.get("/alert-rules/meta")
@require_perm("goals.view_alertrule")
def alert_rules_meta(request, category_id: str):
    """Form vocabulary for the editor: applicable templates + their numeric /
    band fields, kinds, severities, línea (role) values, microcycle labels."""
    from api.alert_rules import build_rule_meta
    return build_rule_meta(_scoped_category_or_404(request, category_id))


@api.get("/alert-rules")
@require_perm("goals.view_alertrule")
def list_alert_rules(request, category_id: str, template_id: str | None = None):
    """Rules that apply to a category: its own + template-wide (category null)
    rules on templates in the same club."""
    from api.alert_rules import serialize_rule
    from goals.models import AlertRule

    category = _scoped_category_or_404(request, category_id)
    qs = (
        AlertRule.objects
        .filter(template__department__club=category.club)
        .filter(Q(category_id=category.id) | Q(category__isnull=True))
        .select_related("template", "category")
    )
    if template_id:
        qs = qs.filter(template_id=template_id)
    return {"rules": [serialize_rule(r) for r in qs]}


@api.post("/alert-rules")
@require_perm("goals.add_alertrule")
def create_alert_rule(request, payload: RuleWriteIn):
    from api.alert_rules import serialize_rule
    from goals.models import AlertRule

    template, category = _resolve_rule_template(
        request, payload.template_id, payload.category_id,
    )
    rule = AlertRule(
        template=template, category=category, kind=payload.kind,
        field_key=payload.field_key, config=payload.config or {},
        scope=payload.scope or {}, severity=payload.severity,
        message_template=payload.message_template or "",
        is_active=payload.is_active, created_by=request.user,
    )
    try:
        rule.full_clean()
    except DjangoValidationError as exc:
        raise HttpError(422, _flatten_validation(exc))
    rule.save()
    return serialize_rule(rule)


@api.post("/alert-rules/backtest")
@require_perm("goals.change_alertrule")
def backtest_alert_rule(request, payload: BacktestIn):
    """Dry-run a draft rule over recent real data (no writes) → how many times
    it would have fired + the players it would have flagged.

    Registered BEFORE the /{rule_id} routes: Django matches URL patterns in
    registration order, so the literal `/backtest` must precede the
    `{rule_id}` catch-all or the param route swallows it (→ 405 on POST)."""
    from api.alert_rules import run_backtest

    template, category = _resolve_rule_template(
        request, payload.template_id, payload.category_id,
    )
    try:
        return run_backtest(template=template, category=category, payload=payload)
    except DjangoValidationError as exc:
        raise HttpError(422, _flatten_validation(exc))


@api.patch("/alert-rules/{rule_id}")
@require_perm("goals.change_alertrule")
def update_alert_rule(request, rule_id: UUID, payload: RuleUpdateIn):
    from api.alert_rules import serialize_rule
    from goals.models import AlertRule

    rule = (
        AlertRule.objects
        .select_related("template__department__club", "category")
        .filter(pk=rule_id).first()
    )
    if rule is None:
        raise HttpError(404, "Regla no encontrada.")
    _club_access_or_403(request, rule.template.department.club)

    data = payload.dict(exclude_unset=True)
    if "category_id" in data:
        cid = data.pop("category_id")
        if cid:
            cat = Category.objects.filter(
                pk=cid, club=rule.template.department.club,
            ).first()
            if cat is None:
                raise HttpError(404, "Categoría no encontrada.")
            rule.category = cat
        else:
            rule.category = None
    for field in ("field_key", "kind", "config", "scope",
                  "severity", "message_template", "is_active"):
        if field in data and data[field] is not None:
            setattr(rule, field, data[field])
    try:
        rule.full_clean()
    except DjangoValidationError as exc:
        raise HttpError(422, _flatten_validation(exc))
    rule.save()
    return serialize_rule(rule)


@api.delete("/alert-rules/{rule_id}")
@require_perm("goals.delete_alertrule")
def delete_alert_rule(request, rule_id: UUID):
    from goals.models import AlertRule

    rule = (
        AlertRule.objects.select_related("template__department__club")
        .filter(pk=rule_id).first()
    )
    if rule is None:
        raise HttpError(404, "Regla no encontrada.")
    _club_access_or_403(request, rule.template.department.club)
    rule.delete()
    return {"ok": True}


@api.get("/daily-report")
def daily_report(request, category_id: str, date: str = ""):
    """La Daily — the 8 AM planning-meeting view: lesionados (diagnosis,
    days out, stage, expected return, load vs habitual), available players
    with active alerts, and the meeting's per-player notes for the date.
    The rest of the squad ("anexo") comes from `/roster`."""
    from api.daily_report import build_daily_report, parse_date

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club").prefetch_related("departments"),
        membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    return build_daily_report(category, parse_date(date), request.user)


@api.get("/wellness-adherence")
def wellness_adherence(request, category_id: str, date_from: str = "", date_to: str = ""):
    """Check-in adherence over a window (informative, no alerts): per-player
    responded/missed grid + compliance % (denominator = days with any check-in
    activity in the category) + a squad roll-up. Default window: last 4 weeks."""
    from api.wellness import build_adherence

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    return build_adherence(category, date_from, date_to)


@api.get("/templates", response=list[TemplateOut])
def list_templates(request, category_id: str, department: str | None = None):
    """Templates applicable to a category (optionally one department), scoped by
    membership. Powers the export exam-picker (§5) and the "Subir datos"
    launcher (§7.1)."""
    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")
    qs = scope_templates(
        ExamTemplate.objects.select_related("department")
        .filter(applicable_categories=category),
        membership,
    )
    if department:
        qs = qs.filter(department__slug=department)
    return list(qs.order_by("department__name", "name").distinct())


@api.get("/export/results.xlsx")
def export_results_xlsx(request, category_id: str, templates: str = "",
                        player_ids: str = "", date_from: str = "",
                        date_to: str = "", event_type: str = ""):
    """Raw-data export (§5): one .xlsx, one sheet per exam type, row =
    (jugador, fecha) with all values incl. calculated. Filters: `templates`
    (comma-sep ids), `player_ids`, date range, `event_type` (match/training)."""
    from django.http import HttpResponse

    from api.export import build_export

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club"), membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    df, dt = _parse_date_window(date_from or None, date_to or None)
    tids = [x for x in templates.split(",") if x.strip()] or None
    pids = [x for x in player_ids.split(",") if x.strip()] or None
    xlsx = build_export(
        category=category, membership=membership, template_ids=tids,
        player_ids=pids, date_from=df, date_to=dt,
        event_type=(event_type or None),
    )
    filename = f"export-{category.name}.xlsx".replace(" ", "_")
    resp = HttpResponse(
        xlsx,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@api.get("/daily-report.pdf")
def download_daily_deck(request, category_id: str, date: str = ""):
    """La Daily as a projectable PDF deck (landscape, one slide per player):
    portada → lesionados (detalle con GPS actual vs. habitual) → alertas →
    anexo de disponibles. Deterministic — no LLM, no caching; always renders
    the data of the moment."""
    from django.http import HttpResponse

    from api.daily_report import parse_date
    from dashboards.pdf.daily_deck import render_daily_deck

    membership = get_membership(request.user)
    category = scope_categories(
        Category.objects.select_related("club").prefetch_related("departments"),
        membership,
    ).filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, "Category not found")

    target = parse_date(date)
    pdf = render_daily_deck(category, target, request.user)
    filename = f"daily-{category.name}-{target.isoformat()}.pdf".replace(" ", "_")
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api.get("/players/{player_id}/daily-notes", response=list[DailyNoteOut])
def list_player_daily_notes(
    request,
    player_id: str,
    date: str | None = None,
    limit: int = 60,
    kind: str = DailyNote.KIND_PAUTA,
):
    """One player's pauta del día (kind='pauta') or plan de trabajo
    (kind='plan').

    With `date` (ISO): that meeting day's notes, oldest first — the daily
    plan view. Without it: the player's most recent notes across all days
    (newest day first), capped at `limit` — the history view.
    """
    from api.daily_report import serialize_note

    membership = get_membership(request.user)
    player = scope_players(Player.objects.all(), membership).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")
    if kind not in dict(DailyNote.KIND_CHOICES):
        raise HttpError(422, "kind inválido — 'pauta' o 'plan'.")

    qs = DailyNote.objects.filter(player=player, kind=kind).select_related(
        "player", "department", "created_by",
    )
    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HttpError(422, "Fecha inválida — se espera YYYY-MM-DD.")
        notes = qs.filter(date=target).order_by("created_at")
    else:
        notes = qs.order_by("-date", "created_at")[: min(max(limit, 1), 200)]
    return [serialize_note(n, request.user) for n in notes]


@api.post("/daily-notes", response=DailyNoteOut)
@require_perm("core.add_dailynote")
def create_daily_note(request, payload: DailyNoteIn):
    """Record a morning-meeting note for a player, tagged with the área
    (department) that raised it. Author is the logged-in user."""
    from api.daily_report import serialize_note

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category__club"), membership,
    ).filter(pk=payload.player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    text = (payload.text or "").strip()
    if not text:
        raise HttpError(400, "La nota no puede estar vacía.")
    if payload.kind not in dict(DailyNote.KIND_CHOICES):
        raise HttpError(422, "kind inválido — 'pauta' o 'plan'.")

    department = None
    if payload.department_id:
        department = Department.objects.filter(
            pk=payload.department_id, club=player.category.club,
        ).first()
        if department is None:
            raise HttpError(404, "Department not found")

    note = DailyNote.objects.create(
        player=player, department=department, kind=payload.kind,
        date=payload.date, text=text, created_by=request.user,
    )
    return serialize_note(note, request.user)


@api.delete("/daily-notes/{note_id}")
def delete_daily_note(request, note_id: str):
    """Remove a meeting note. Authors can delete their own; deleting
    someone else's requires `core.delete_dailynote`."""
    membership = get_membership(request.user)
    note = DailyNote.objects.filter(
        pk=note_id,
        player__in=scope_players(Player.objects.all(), membership),
    ).first()
    if note is None:
        raise HttpError(404, "Note not found")
    if note.created_by_id != request.user.id and not _has_perm(
        request.user, "core.delete_dailynote"
    ):
        raise HttpError(403, "Solo el autor puede eliminar esta nota.")
    note.delete()
    return {"ok": True}


@api.get("/players/{player_id}/triage.docx")
def download_player_triage_docx(request, player_id: str):
    """Editable Resumen (Word) — one-page snapshot of alerts, alerted metrics
    with previous reading, other tracked metrics with 30d trail, and the
    last match's citation status. Shares its data layer with the JSON
    endpoint so screen and document never diverge."""
    from django.http import HttpResponse
    from dashboards.docx.player_triage_docx import render_or_get_triage_docx

    membership = get_membership(request.user)
    player = scope_players(
        Player.objects.select_related("category__club", "position"),
        membership,
    ).filter(pk=player_id).first()
    if player is None:
        raise HttpError(404, "Player not found")

    # Content-addressed: returns the saved Word file for this data signature
    # if it exists, else generates once and persists it (see report_cache).
    docx_bytes = render_or_get_triage_docx(player)
    name = f"{player.first_name}-{player.last_name}".replace(" ", "_")
    filename = f"resumen-{name}.docx"
    response = HttpResponse(docx_bytes, content_type=_DOCX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api.get("/players/{player_id}/departments/{department_slug}/report.docx")
def download_player_department_docx(
    request,
    player_id: str,
    department_slug: str,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Per-player department report as an editable Word document (portrait A4)."""
    from django.http import HttpResponse

    from dashboards.docx.player_report_docx import render_or_get_player_docx

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

    # Content-addressed: uses the department's InsightAgent + saved snapshot
    # (same data + agent config ⇒ same report, generated once).
    docx_bytes = render_or_get_player_docx(
        player=player, department=dept,
        date_from=parsed_from, date_to=parsed_to,
    )

    name = f"{player.first_name}-{player.last_name}".replace(" ", "_")
    filename = f"reporte-{name}-{department_slug}.docx"
    response = HttpResponse(docx_bytes, content_type=_DOCX_CONTENT_TYPE)
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

    # Link a rival ExternalTeam when the payload identifies one (match-create
    # form passes opponent_team_id in metadata; matches the sync's shape).
    opponent_team = None
    otid = (payload.metadata or {}).get("opponent_team_id")
    if otid:
        from events.models import ExternalTeam
        opponent_team = ExternalTeam.objects.filter(
            provider="api_football", external_id=otid,
        ).first()

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
        opponent_team=opponent_team,
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


# ---------- Match roster (convocatoria) ----------
#
# A match's roster is the full set of EventParticipant rows attached to
# the Event. The roster panel on /partidos/[id]/editar talks to this
# trio of endpoints: read, replace, and copy-from-last-match.

@api.get("/events/{event_id}/roster", response=list[RosterEntryOut])
def get_event_roster(request, event_id: UUID):
    """Full per-player roster for a match — includes match_role + reason."""
    from events.models import EventParticipant

    membership = get_membership(request.user)
    event = scope_events(Event.objects.all(), membership).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")

    rows = (
        EventParticipant.objects
        .filter(event_id=event_id)
        .select_related("player__category", "position_played")
        .order_by("player__last_name", "player__first_name")
    )
    return [
        {
            "player_id": r.player_id,
            "first_name": r.player.first_name,
            "last_name": r.player.last_name,
            "category_id": r.player.category_id,
            "category_name": r.player.category.name if r.player.category else "",
            "match_role": r.match_role or "",
            "absence_reason": r.absence_reason or "",
            "position_played_id": r.position_played_id,
        }
        for r in rows
    ]


@api.put("/events/{event_id}/roster", response=list[RosterEntryOut])
@require_perm("events.change_event")
def replace_event_roster(request, event_id: UUID, payload: RosterReplaceIn):
    """Replace the entire roster atomically.

    Every payload entry is upserted to an EventParticipant; any
    pre-existing rows whose `player_id` isn't in the payload are
    DELETED. Use this for the bulk save on the convocatoria panel —
    the panel always sends the desired complete state.

    Players come from any category visible to the user (cross-category
    promotions are first-class — they just land with `match_role =
    "promovido"`).
    """
    from django.db import transaction
    from events.models import EventParticipant

    membership = get_membership(request.user)
    event = scope_events(Event.objects.all(), membership).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")

    # Validate player IDs are visible to the user. We use the wider
    # roster scope (club-level) instead of `scope_players` so coaches
    # can convocate cross-category — promoting a SUB-20 to a Primer
    # Equipo match is a normal operation that shouldn't be blocked by
    # the user's data-reading category memberships.
    requested_ids = {e.player_id for e in payload.entries}
    visible_players = {
        p.id: p
        for p in scope_players_for_roster(
            Player.objects.select_related("category"), membership,
        ).filter(id__in=requested_ids)
    }
    missing = requested_ids - set(visible_players.keys())
    if missing:
        raise HttpError(
            400,
            f"Some players are not in this club: {sorted(str(x) for x in missing)}",
        )

    # Validate match_role values.
    valid_roles = {choice[0] for choice in EventParticipant.MatchRole.choices}
    for entry in payload.entries:
        if entry.match_role and entry.match_role not in valid_roles:
            raise HttpError(
                400, f"Invalid match_role '{entry.match_role}'. "
                     f"Valid roles: {sorted(valid_roles)}"
            )

    with transaction.atomic():
        # Delete rows for players not in the new roster. Stats already
        # captured on those rows (minutes/goals/cards) are lost on
        # purpose — coaches drop a player from the convocatoria when
        # they want to revoke the participation.
        EventParticipant.objects.filter(event_id=event_id).exclude(
            player_id__in=requested_ids,
        ).delete()

        # Upsert each entry. Existing rows preserve their match stats —
        # we only overwrite the participation-status fields.
        for entry in payload.entries:
            EventParticipant.objects.update_or_create(
                event_id=event_id,
                player_id=entry.player_id,
                defaults={
                    "match_role": entry.match_role or None,
                    "absence_reason": entry.absence_reason or "",
                    "position_played_id": entry.position_played_id,
                    "attendance": "scheduled",
                },
            )

        # Keep the Event.participants M2M consistent with the new set.
        # (Other consumers — calendar widgets, badges — still query the
        # M2M directly rather than EventParticipant.)
        event.participants.set([visible_players[pid] for pid in requested_ids])

    # Return the new roster so the frontend can sync state without
    # a follow-up GET.
    rows = (
        EventParticipant.objects
        .filter(event_id=event_id)
        .select_related("player__category", "position_played")
        .order_by("player__last_name", "player__first_name")
    )
    return [
        {
            "player_id": r.player_id,
            "first_name": r.player.first_name,
            "last_name": r.player.last_name,
            "category_id": r.player.category_id,
            "category_name": r.player.category.name if r.player.category else "",
            "match_role": r.match_role or "",
            "absence_reason": r.absence_reason or "",
            "position_played_id": r.position_played_id,
        }
        for r in rows
    ]


@api.get("/events/{event_id}/suggested-roster", response=list[RosterEntryOut])
def suggested_roster(request, event_id: UUID):
    """Pre-fill source for the convocatoria panel.

    Returns the EventParticipant rows from the **most recent past
    match** in the same category as this one. The frontend uses this
    behind a "Copiar del último partido" button so a coach doesn't
    have to rebuild the roster from scratch every weekend.

    Returns `[]` when no prior match exists for the category — caller
    is expected to gracefully no-op the button in that case.
    """
    from django.utils import timezone as _tz
    from events.models import EventParticipant

    membership = get_membership(request.user)
    event = scope_events(
        Event.objects.select_related("category"), membership,
    ).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")

    if event.category_id is None:
        return []

    # The "previous" match is the latest match (excluding this one) in
    # the same category that ALREADY HAS A ROSTER. A bare "starts_at <
    # now()" filter would otherwise pick up an empty scheduled fixture
    # whose date just passed — which defeats the point of "copy from
    # last match". Annotating + filtering by participant count gives us
    # the last match the coach actually built a roster for.
    from django.db.models import Count
    prev_match = (
        Event.objects
        .filter(
            club_id=event.club_id,
            event_type=Event.TYPE_MATCH,
            category_id=event.category_id,
            starts_at__lt=event.starts_at,
        )
        .exclude(pk=event_id)
        .annotate(_p_count=Count("event_participants"))
        .filter(_p_count__gt=0)
        .order_by("-starts_at")
        .first()
    )
    if prev_match is None:
        return []

    rows = (
        EventParticipant.objects
        .filter(event_id=prev_match.id)
        .select_related("player__category", "position_played")
        .order_by("player__last_name", "player__first_name")
    )
    return [
        {
            "player_id": r.player_id,
            "first_name": r.player.first_name,
            "last_name": r.player.last_name,
            "category_id": r.player.category_id,
            "category_name": r.player.category.name if r.player.category else "",
            "match_role": r.match_role or "",
            "absence_reason": r.absence_reason or "",
            "position_played_id": r.position_played_id,
        }
        for r in rows
    ]


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
    current_value = current_recorded_at = None
    progress = None
    if goal.is_metric_goal:
        for field in (goal.template.config_schema or {}).get("fields", []):
            if isinstance(field, dict) and field.get("key") == goal.field_key:
                label = field.get("label") or goal.field_key
                unit = field.get("unit") or ""
                break
        current_value, current_recorded_at = _resolve_goal_current_value(goal)
        progress = _goal_progress(goal, current_value)
    return {
        "id": goal.id,
        "player_id": goal.player_id,
        "is_metric_goal": goal.is_metric_goal,
        "title": goal.title,
        "template_id": goal.template_id,
        "template_name": goal.template.name if goal.template_id else "",
        "field_key": goal.field_key,
        "field_label": label if goal.is_metric_goal else "",
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
        "progress": progress if progress is not None else {},
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

    creator = request.user if request.user.is_authenticated else None

    # Free goal (§7.3): just a title + due_date, closed manually.
    if not payload.template_id:
        if not (payload.title or "").strip():
            raise HttpError(400, "Un objetivo libre (sin métrica) requiere un título.")
        goal = Goal.objects.create(
            player=player, title=payload.title.strip(), due_date=payload.due_date,
            notes=payload.notes or "",
            warn_days_before=None,  # free goals nag via GOAL_OVERDUE, not pre-warnings
            created_by=creator,
        )
        return _serialize_goal(goal)

    # Metric goal — template + field + operator + target.
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
    if payload.target_value is None:
        raise HttpError(400, "target_value es obligatorio para un objetivo con métrica.")

    goal = Goal.objects.create(
        player=player,
        template=template,
        title=(payload.title or "").strip(),
        field_key=payload.field_key,
        operator=payload.operator,
        target_value=payload.target_value,
        due_date=payload.due_date,
        notes=payload.notes or "",
        warn_days_before=payload.warn_days_before,
        created_by=creator,
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
    if payload.title is not None:
        goal.title = payload.title.strip()
        fields_to_update.append("title")
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
        # Cancellation is allowed for any goal. FREE goals (§7.3) also close
        # manually to met / missed — a metric goal's met/missed stays
        # evaluator-driven so a human flip can't corrupt its status timeline.
        allowed = {GoalStatus.CANCELLED}
        if not goal.is_metric_goal:
            allowed |= {GoalStatus.MET, GoalStatus.MISSED}
        if payload.status not in allowed:
            raise HttpError(400, "Transición de estado no permitida para este objetivo.")
        goal.status = payload.status
        fields_to_update.append("status")

    if fields_to_update:
        fields_to_update.append("updated_at")
        goal.save(update_fields=fields_to_update)
        # Closing a goal clears its pending warning + overdue nags.
        if "status" in fields_to_update and goal.status != GoalStatus.ACTIVE:
            from goals.evaluator import _dismiss_active_warning, _dismiss_overdue_alert
            _dismiss_active_warning(goal)
            _dismiss_overdue_alert(goal)
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
    from exams.episode_lifecycle import stage_label as _episode_stage_label
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
        "stage_label": _episode_stage_label(episode.template, episode.stage),
        "title": episode.title,
        "started_at": episode.started_at,
        "ended_at": episode.ended_at,
        "available_at": episode.available_at,
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

    if payload.available_at is not None:
        from django.utils import timezone as _tz
        from django.utils.dateparse import parse_date, parse_datetime
        val = payload.available_at.strip()
        if val.lower() == "clear" or val == "":
            episode.available_at = None
        else:
            dt = parse_datetime(val)
            if dt is None:
                d = parse_date(val)
                if d is None:
                    raise HttpError(400, "available_at inválido (ISO date/datetime o 'clear').")
                dt = datetime.combine(d, datetime.min.time())
            if _tz.is_naive(dt):
                dt = _tz.make_aware(dt, _tz.get_default_timezone())
            episode.available_at = dt
        # available_at is independent of status/stage, so Player.status
        # (driven by open episodes' stages) is unaffected — no recompute.
        episode.save(update_fields=["available_at", "updated_at"])

    return _serialize_episode(episode)


# --- App usage analytics ---------------------------------------------------
#
# Bucketed counts of ExamResults grouped by department, for the /uso page.
# Superuser-only — the audience is platform admins watching adoption, not
# clinical staff. Scoped to the membership's club; superusers without a
# membership see all clubs.

@api.get("/admin/usage")
def admin_usage(
    request,
    category_id: str | None = None,
    bucket: str = "week",
    n: int = 12,
):
    """Time-bucketed ExamResult counts by department.

    Returns a flat array shaped for direct consumption by a stacked
    bar chart: each item is one bucket with one numeric column per
    department slug, plus a `departments` index of {slug, name} for the
    chart legend.
    """
    from datetime import timedelta
    from django.db.models import Count
    from django.db.models.functions import TruncMonth, TruncWeek
    from django.utils import timezone

    if not request.user.is_superuser:
        raise HttpError(403, "Solo administradores pueden ver el uso de la app.")

    if bucket not in {"week", "month"}:
        raise HttpError(400, "bucket debe ser 'week' o 'month'")
    # 120 covers 10 years monthly or ~2.3 years weekly — large enough
    # for any reasonable platform-adoption analysis without risking
    # runaway aggregation queries.
    n = max(1, min(n, 120))

    now = timezone.now()
    if bucket == "week":
        cutoff = now - timedelta(weeks=n)
        trunc = TruncWeek
    else:
        cutoff = now - timedelta(days=n * 31)
        trunc = TruncMonth

    qs = ExamResult.objects.filter(recorded_at__gte=cutoff)
    if category_id:
        qs = qs.filter(player__category_id=category_id)

    rows = (
        qs.annotate(b=trunc("recorded_at"))
        .values("b", "template__department__slug", "template__department__name")
        .annotate(count=Count("id"))
        .order_by("b")
    )

    # Pivot rows → {bucket_iso: {dept_slug: count}}; collect dept index.
    departments: dict[str, str] = {}
    pivot: dict[str, dict[str, int]] = {}
    for r in rows:
        slug = r["template__department__slug"]
        name = r["template__department__name"]
        b = r["b"]
        if not b:
            continue
        key = b.date().isoformat()
        departments[slug] = name
        pivot.setdefault(key, {})[slug] = r["count"]

    # Fill empty buckets so the chart x-axis has continuous ticks even on
    # weeks where nobody recorded anything (otherwise the missing bar
    # silently lies about engagement).
    series: list[dict[str, Any]] = []
    bucket_start = cutoff
    for i in range(n):
        if bucket == "week":
            # Match Django's TruncWeek (Monday-anchored).
            ws = bucket_start + timedelta(weeks=i)
            ws = ws - timedelta(days=ws.weekday())
            key = ws.date().isoformat()
        else:
            ws = bucket_start + timedelta(days=i * 31)
            ws = ws.replace(day=1)
            key = ws.date().isoformat()
        entry: dict[str, Any] = {"bucket": key}
        counts = pivot.get(key, {})
        for slug in departments:
            entry[slug] = counts.get(slug, 0)
        series.append(entry)

    # Per-template totals AND time series for the same window + filter.
    # Templates are returned sorted by total desc so the legend / stack order
    # surface the heaviest contributors first.
    template_meta: dict[str, dict[str, Any]] = {}
    template_pivot: dict[str, dict[str, int]] = {}
    template_totals: dict[str, int] = {}

    template_rows = (
        qs.annotate(b=trunc("recorded_at"))
        .values(
            "b",
            "template__slug",
            "template__name",
            "template__department__slug",
            "template__department__name",
        )
        .annotate(count=Count("id"))
        .order_by("b")
    )
    for r in template_rows:
        slug = r["template__slug"]
        if slug is None:
            continue
        template_meta[slug] = {
            "slug": slug,
            "name": r["template__name"],
            "department_slug": r["template__department__slug"],
            "department_name": r["template__department__name"],
        }
        b = r["b"]
        if not b:
            continue
        key = b.date().isoformat()
        template_pivot.setdefault(key, {})[slug] = r["count"]
        template_totals[slug] = template_totals.get(slug, 0) + r["count"]

    # Sort templates by total desc — heavy contributors come first.
    sorted_slugs = sorted(template_meta.keys(), key=lambda s: -template_totals.get(s, 0))
    templates_out = [
        {**template_meta[s], "count": template_totals.get(s, 0)} for s in sorted_slugs
    ]

    # Build the parallel time-series with zero-filling so the x-axis ticks
    # stay continuous even on weeks where a template recorded nothing.
    templates_series: list[dict[str, Any]] = []
    for entry in series:
        ts_entry: dict[str, Any] = {"bucket": entry["bucket"]}
        bucket_counts = template_pivot.get(entry["bucket"], {})
        for slug in sorted_slugs:
            ts_entry[slug] = bucket_counts.get(slug, 0)
        templates_series.append(ts_entry)

    return {
        "bucket": bucket,
        "departments": [{"slug": s, "name": n_} for s, n_ in sorted(departments.items(), key=lambda x: x[1])],
        "series": series,
        "templates": templates_out,
        "templates_series": templates_series,
    }
