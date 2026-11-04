"""SLAB Admin — standing up a club, and growing it, from the panel.

A new club starts from the **Base template**: three departments, the four
positions, and in each department the exams every club records from day one.

    Médico       Notas diarias
    Físico       Notas diarias · GPS Partido · GPS Entrenamiento
    Nutricional  Notas diarias · Peso y Talla · Pentacompartimental

The exams are the existing seed commands, called as they would be from a shell
(`--club … --create-if-missing`), so a template made here is the same template
the other clubs have. Applying the template is idempotent and ADD-ONLY: a
department, position or exam the club already has is left exactly as it is —
the seeds refresh a template's schema when re-run, and a club that tuned its
GPS fields must not get them reset by "Reaplicar plantilla". Only what's
missing is created.

Categories attach to departments and exams. A club's first categories take all
of them; a later one copies a sibling (`like=`) — in a club like U. de Chile
the Primer Equipo and the series record different exams, and "all of them"
would hand a Sub 13 the senior team's forms.

Club names are unique (case-insensitive): the seeds find the club by name.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from django.core.management import call_command
from django.db import transaction

from core.models import Category, Club, Department, Position

POSITIONS: list[tuple[str, str, int]] = [
    ("Arquero", "POR", 0),
    ("Defensor", "DF", 1),
    ("Mediocampista", "MC", 2),
    ("Delantero", "DEL", 3),
]


@dataclass(frozen=True)
class Exam:
    command: str
    slug: str
    name: str
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DepartmentSpec:
    slug: str
    name: str
    exams: tuple[Exam, ...] = ()


def _notas(dept_slug: str) -> Exam:
    return Exam("seed_daily_notes", f"notas_diarias_{dept_slug}", "Notas diarias",
                {"department_slug": dept_slug, "all_applicable_categories": True})


# Every department the panel can add. Base ones carry their exams; the rest
# start with Notas diarias and grow from Configuraciones.
CATALOG: dict[str, DepartmentSpec] = {d.slug: d for d in (
    DepartmentSpec("medico", "Médico", (_notas("medico"),)),
    DepartmentSpec("fisico", "Físico", (
        _notas("fisico"),
        Exam("seed_gps_partido", "gps_partido", "GPS Partido",
             {"department_slug": "fisico", "all_applicable_categories": True}),
        Exam("seed_gps_session", "gps_sesion", "GPS Entrenamiento",
             {"department_slug": "fisico", "all_applicable_categories": True}),
    )),
    DepartmentSpec("nutricional", "Nutricional", (
        _notas("nutricional"),
        Exam("seed_peso_talla", "peso_talla", "Peso y Talla",
             {"department_slug": "nutricional"}),
        Exam("seed_pentacompartimental", "pentacompartimental", "Pentacompartimental",
             {"department_slug": "nutricional", "all_applicable_categories": True}),
    )),
    DepartmentSpec("kinesiologico", "Kinesiológico", (_notas("kinesiologico"),)),
    DepartmentSpec("psicosocial", "Psicología", (_notas("psicosocial"),)),
    DepartmentSpec("tactico", "Táctico", (_notas("tactico"),)),
)}

BASE_TEMPLATE = ("medico", "fisico", "nutricional")


class SetupError(ValueError):
    """A request the panel should answer with a 400 and this message."""


@dataclass
class Applied:
    departments: list[str] = field(default_factory=list)
    exams: list[str] = field(default_factory=list)
    positions: int = 0


def name_taken(name: str, *, exclude: Club | None = None) -> bool:
    qs = Club.objects.filter(name__iexact=name.strip())
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.exists()


def _templates(department: Department):
    from exams.models import ExamTemplate
    return ExamTemplate.objects.filter(department=department, is_active_version=True)


def add_department(club: Club, slug: str, *, applied: Applied | None = None) -> Department:
    """The catalog department `slug` with its exams, attached to every category
    of the club. Whatever already exists is kept."""
    spec = CATALOG.get(slug)
    if spec is None:
        raise SetupError(f"Departamento desconocido: {slug}.")
    applied = applied if applied is not None else Applied()
    dept = Department.objects.filter(club=club, slug=slug).first()
    if dept is None:
        if Department.objects.filter(club=club, name__iexact=spec.name).exists():
            raise SetupError(f"Ya existe un departamento llamado {spec.name}.")
        dept = Department.objects.create(club=club, name=spec.name, slug=slug)
        applied.departments.append(spec.name)
        # A department nobody sees isn't one: every category gets the tab —
        # BEFORE the seeds, which attach each exam to the categories showing
        # its department. Only when new: a category the club took the tab
        # away from on purpose keeps it that way.
        for cat in club.categories.all():
            cat.departments.add(dept)

    existentes = set(_templates(dept).values_list("slug", flat=True))
    for exam in spec.exams:
        if exam.slug in existentes:
            continue
        call_command(exam.command, club=club.name, create_if_missing=True,
                     stdout=io.StringIO(), stderr=io.StringIO(), **exam.options)
        applied.exams.append(f"{spec.name} · {exam.name}")
    return dept


def apply_base_template(club: Club) -> Applied:
    """Base departments, their exams and the positions — only what's missing."""
    applied = Applied()
    with transaction.atomic():
        for slug in BASE_TEMPLATE:
            add_department(club, slug, applied=applied)
        for name, abbr, order in POSITIONS:
            _, made = Position.objects.get_or_create(
                club=club, abbreviation=abbr, defaults={"name": name, "sort_order": order})
            applied.positions += made
    return applied


def create_club(name: str, categories: list[dict]) -> tuple[Club, Applied]:
    name = name.strip()
    if not name:
        raise SetupError("Ingresá el nombre del club.")
    if name_taken(name):
        raise SetupError(f"Ya existe un club llamado {name}.")
    with transaction.atomic():
        club = Club.objects.create(name=name)
        # Categories first: the seeds attach each exam to the categories that
        # already show its department.
        for c in categories:
            _new_category(club, **c)
        applied = apply_base_template(club)
    return club, applied


def _new_category(club: Club, *, name: str, cohort_year: int | None = None,
                  is_senior: bool = False) -> Category:
    name = (name or "").strip()
    if not name:
        raise SetupError("Ingresá el nombre de la categoría.")
    if club.categories.filter(name__iexact=name).exists():
        raise SetupError(f"Ya existe la categoría {name} en {club.name}.")
    if is_senior:
        # One first team per club (see Category.is_senior).
        club.categories.filter(is_senior=True).update(is_senior=False)
    return Category.objects.create(club=club, name=name, cohort_year=cohort_year,
                                   is_senior=is_senior)


def add_category(club: Club, *, name: str, cohort_year: int | None = None,
                 is_senior: bool = False, like: Category | None = None) -> Category:
    """A new category with the departments and exams of `like`, or — without
    one — every department and exam of the club."""
    if like is not None and like.club_id != club.id:
        raise SetupError("La categoría modelo no es de este club.")
    with transaction.atomic():
        cat = _new_category(club, name=name, cohort_year=cohort_year, is_senior=is_senior)
        if like is not None:
            cat.departments.set(like.departments.all())
            cat.exam_templates.set(like.exam_templates.all())
        else:
            cat.departments.set(club.departments.all())
            for dept in club.departments.all():
                cat.exam_templates.add(*_templates(dept))
    return cat


def missing_from_base(club: Club) -> list[str]:
    """What "Reaplicar plantilla" would create — empty when it's all there."""
    out: list[str] = []
    for slug in BASE_TEMPLATE:
        spec = CATALOG[slug]
        dept = Department.objects.filter(club=club, slug=slug).first()
        if dept is None:
            out.append(spec.name)
            continue
        have = set(_templates(dept).values_list("slug", flat=True))
        out += [f"{spec.name} · {e.name}" for e in spec.exams if e.slug not in have]
    have_pos = set(Position.objects.filter(club=club).values_list("abbreviation", flat=True))
    if any(abbr not in have_pos for _, abbr, _ in POSITIONS):
        out.append("Posiciones")
    return out
