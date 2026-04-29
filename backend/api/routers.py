from datetime import datetime
from uuid import UUID

from django.contrib.auth import authenticate, get_user_model
from django.shortcuts import get_object_or_404
from ninja import File, Form, NinjaAPI, Query
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.models import Category, Department, Player, Position
from dashboards.aggregation import resolve_widget
from dashboards.models import DepartmentLayout
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

    result_data = compute_result_data(template, payload.raw_data)

    result = ExamResult.objects.create(
        player=player,
        template=template,
        recorded_at=recorded_at,
        result_data=result_data,
        event=event,
    )

    if not template.is_locked:
        template.is_locked = True
        template.save(update_fields=["is_locked"])

    return _serialize_result(result)


def _serialize_result(result: ExamResult) -> dict:
    return {
        "id": result.id,
        "player_id": result.player_id,
        "template_id": result.template_id,
        "recorded_at": result.recorded_at,
        "result_data": result.result_data,
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
        ExamResult.objects.filter(player_id=player_id).select_related(
            "template__department", "event",
        ),
        membership,
    )
    if department:
        qs = qs.filter(template__department__slug=department)
    return [_serialize_result(r) for r in qs]


@api.get("/players/{player_id}/views", response=LayoutResponseOut)
def get_player_view(request, player_id: str, department: str):
    """Return the configured DepartmentLayout for (player.category, department).

    Returns `{"layout": null}` when no active layout exists — the frontend
    falls back to the legacy auto-rendered template grid in that case.
    """
    membership = get_membership(request.user)

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
                    "sort_order": widget.sort_order,
                    "display_config": widget.display_config or {},
                    "data": resolve_widget(widget, player.id),
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
def delete_event(request, event_id: UUID):
    membership = get_membership(request.user)
    event = scope_events(Event.objects.all(), membership).filter(pk=event_id).first()
    if event is None:
        raise HttpError(404, "Event not found")
    event.delete()
    return {"deleted": True}
