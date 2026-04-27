from django.contrib.auth import authenticate, get_user_model
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI
from ninja.errors import HttpError

from core.models import Category, Department, Player, Position
from exams.calculations import compute_result_data
from exams.models import ExamResult, ExamTemplate

from .auth import issue_token, jwt_auth
from .scoping import (
    get_membership,
    has_full_access,
    scope_categories,
    scope_departments,
    scope_players,
    scope_positions,
    scope_results,
    scope_templates,
)
from .schemas import (
    CategoryOut,
    DepartmentOut,
    LoginIn,
    LoginOut,
    MeOut,
    MembershipOut,
    PlayerDetailOut,
    PlayerOut,
    PositionOut,
    ResultIn,
    ResultOut,
    TemplateOut,
    UserOut,
)

User = get_user_model()

api = NinjaAPI(title="SLAB API", version="0.1.0", auth=jwt_auth)


@api.get("/health", auth=None)
def health(request):
    return {"status": "ok"}


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
        "user": user,
        "membership": _serialize_membership(membership),
    }


@api.get("/auth/me", response=MeOut)
def me(request):
    membership = get_membership(request.user)
    return {
        "user": request.user,
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
def list_players(request, category_id: str | None = None):
    membership = get_membership(request.user)
    qs = Player.objects.filter(is_active=True).select_related("category", "position")
    qs = scope_players(qs, membership)
    if category_id:
        qs = qs.filter(category_id=category_id)
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
    return {
        "id": player.id,
        "first_name": player.first_name,
        "last_name": player.last_name,
        "date_of_birth": player.date_of_birth,
        "nationality": player.nationality,
        "is_active": player.is_active,
        "club": player.category.club,
        "category": {
            "id": player.category.id,
            "name": player.category.name,
            "club_id": player.category.club_id,
            "departments": departments,
        },
        "position": player.position,
    }


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
def create_result(request, payload: ResultIn):
    """Create an ExamResult.

    Calculated fields in the template's config_schema are evaluated server-side
    via the AST formula engine and merged into result_data alongside the raw
    inputs. The doctor never types a calculated value — the engine does.
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

    result_data = compute_result_data(template, payload.raw_data)

    result = ExamResult.objects.create(
        player=player,
        template=template,
        recorded_at=payload.recorded_at,
        result_data=result_data,
    )

    if not template.is_locked:
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
        ),
        membership,
    )
    if department:
        qs = qs.filter(department__slug=department)
    return qs.distinct()


@api.get("/players/{player_id}/results", response=list[ResultOut])
def list_player_results(request, player_id: str, department: str | None = None):
    """List results for a player.

    `department` filters by Department.slug (scoped to the player's club).
    """
    membership = get_membership(request.user)
    qs = scope_results(
        ExamResult.objects.filter(player_id=player_id).select_related("template__department"),
        membership,
    )
    if department:
        qs = qs.filter(template__department__slug=department)
    return qs
