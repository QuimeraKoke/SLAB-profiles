"""Creating and editing a microcycle plan (PLAN_CONTROL_CARGA.md §8.3–8.4).

The plan is the source of truth for which days are matches: friendlies have no
`Event` (they are `gps_sesion` rows coded `MD AMISTOSO`), so a new microcycle
is PRE-FILLED from what SLAB already knows — the team's official fixtures, the
friendly codes in its GPS sheet, the club's MICRO number and TIPO — and the
staff corrects it. Training % are copied from the previous microcycle by MD
label, which is how the staff works ("copiar M40, cambiar 3 celdas").
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Bracket, Category, TeamSeason
from dashboards.team_scope import season_rows
from exams.models import ExamResult
from load_control.labels import labels_for, neighbour_matches, relabel
from load_control.matches import match_links, team_match_days
from load_control.models import LoadControlConfig, Microcycle, MicrocycleDay
from load_control.reference import compute_reference, day_targets

GPS_SLUGS = ("gps_sesion", "gps_partido")
WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


@dataclass(frozen=True)
class Team:
    club: object
    season: int
    bracket: Bracket

    @property
    def label(self) -> str:
        """The club's own name for the team: its GPS tab (U20, U18…)."""
        parts = self.bracket.name.split()
        return f"U{parts[-1]}" if len(parts) == 2 and parts[-1].isdigit() else self.bracket.name

    def categories(self) -> list[Category]:
        return [ts.team for ts in TeamSeason.objects.filter(
            season=self.season, bracket=self.bracket, team__club=self.club,
        ).select_related("team").order_by("team__name")]


def team_for(category: Category, season: int | None = None) -> Team | None:
    season = season or timezone.localdate().year
    ts = TeamSeason.objects.filter(team=category, season=season).select_related("bracket").first()
    return Team(category.club, season, ts.bracket) if ts else None


def team_of(microcycle: Microcycle) -> Team:
    return Team(microcycle.club, microcycle.season, microcycle.bracket)


def _dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _gps_rows(team: Team, start: date, end: date):
    return ExamResult.objects.filter(
        season_rows(team.club.id, team.season, team.bracket),
        template__slug__in=GPS_SLUGS,
        recorded_at__date__gte=start, recorded_at__date__lte=end,
    )


def detect_day_kinds(team: Team, start: date, end: date) -> dict[date, str]:
    """The club's match days (its GPS codes; fixtures only where it has none)
    → day kinds; every other day starts as training."""
    played = team_match_days(team.club, team.season, team.bracket, start, end)
    return {d: played.get(d, MicrocycleDay.KIND_TRAINING) for d in _dates(start, end)}


def _most_common(values) -> object | None:
    c = Counter(v for v in values if v not in (None, ""))
    return c.most_common(1)[0][0] if c else None


def previous_microcycle(team: Team, before: date) -> Microcycle | None:
    return (Microcycle.objects.filter(club=team.club, bracket=team.bracket,
                                      start_date__lt=before)
            .order_by("-start_date").first())


def suggest(team: Team, start: date | None = None) -> dict:
    """A not-yet-saved microcycle for the week of `start` (default: next
    Monday after the team's last microcycle, else this week's Monday)."""
    prev = previous_microcycle(team, start or date.max)
    if start is None:
        start = (prev.end_date + timedelta(days=1)) if prev else \
            timezone.localdate() - timedelta(days=timezone.localdate().weekday())
    end = start + timedelta(days=6)
    prev = previous_microcycle(team, start)
    rows = list(_gps_rows(team, start, end).values_list("result_data", flat=True))
    number = _most_common((r or {}).get("microciclo") for r in rows)
    if number is None:
        number = (prev.number + 1) if prev else 1
    kind = _most_common((r or {}).get("tipo_microciclo") for r in rows) or (prev.kind if prev else "")
    kinds = detect_day_kinds(team, start, end)
    return {"start_date": start, "end_date": end, "number": int(number), "kind": kind,
            "copy_from": prev, "days": [{"date": d, "kind": k} for d, k in kinds.items()]}


def _validate_span(start: date, end: date):
    """The planner is WEEKLY (decided 2026-11-03): Monday to Sunday, numbered
    by the GPS's MICRO, which the club counts by calendar week. A week holds
    0, 1 or 2 matches; "microcycle" in the club's other sheets (the jump
    tabs) means match-to-match, which is why the planner does not use it."""
    if start.weekday() != 0:
        raise ValidationError("La semana debe empezar un lunes.")
    if end != start + timedelta(days=6):
        raise ValidationError("La semana va de lunes a domingo (7 días).")


@transaction.atomic
def create(team: Team, *, start: date, end: date, number: int, kind: str = "",
           days: list[dict] | None = None, copy_from: Microcycle | None = None,
           user=None) -> Microcycle:
    _validate_span(start, end)
    cfg = LoadControlConfig.resolved(team.club, team.bracket)
    if kind and kind not in cfg["microcycle_kinds"]:
        raise ValidationError(f"Tipo de semana desconocido: {kind}.")
    if copy_from is not None and (copy_from.club_id != team.club.id
                                  or copy_from.bracket_id != team.bracket.id):
        raise ValidationError("Sólo se puede copiar una semana del mismo equipo.")
    if Microcycle.objects.filter(club=team.club, season=team.season,
                                 bracket=team.bracket, number=number).exists():
        raise ValidationError(f"{team.label} ya tiene la semana {number} en {team.season}.")
    mc = Microcycle.objects.create(club=team.club, season=team.season, bracket=team.bracket,
                                   number=number, kind=kind, start_date=start, end_date=end,
                                   copied_from=copy_from, created_by=user)
    kinds = {d["date"]: d["kind"] for d in (days or [])} or detect_day_kinds(team, start, end)
    _write_days(mc, [{"date": d, "kind": kinds.get(d, MicrocycleDay.KIND_TRAINING),
                      "targets_pct": {}} for d in _dates(start, end)])
    if copy_from is not None:
        copy_percentages(copy_from, mc)
    return mc


def copy_percentages(source: Microcycle, target: Microcycle) -> int:
    """Training % from `source` onto `target`'s training days, by MD label
    (MD-2 takes MD-2's). Returns how many days got a plan."""
    by_label: dict[str, dict] = {}
    for d in source.days.filter(kind=MicrocycleDay.KIND_TRAINING).exclude(targets_pct={}):
        by_label.setdefault(d.md_label, d.targets_pct)
    n = 0
    for d in target.days.filter(kind=MicrocycleDay.KIND_TRAINING):
        pct = by_label.get(d.md_label)
        if pct:
            d.targets_pct = dict(pct)
            d.save(update_fields=["targets_pct"])
            n += 1
    return n


def _write_days(mc: Microcycle, days: list[dict]):
    expected = set(_dates(mc.start_date, mc.end_date))
    given = [d["date"] for d in days]
    if len(given) != len(set(given)) or set(given) != expected:
        raise ValidationError("El plan debe traer exactamente un registro por cada día de la semana.")
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    metric_keys = {m["key"] for m in cfg["metrics"]}
    existing = {d.date: d for d in mc.days.all()}
    for item in days:
        day = existing.get(item["date"]) or MicrocycleDay(microcycle=mc, date=item["date"])
        day.kind = item["kind"]
        pct = {k: v for k, v in (item.get("targets_pct") or {}).items() if v is not None}
        unknown = set(pct) - metric_keys
        if unknown:
            raise ValidationError(f"Métricas desconocidas: {', '.join(sorted(unknown))}.")
        day.targets_pct = pct if day.kind == MicrocycleDay.KIND_TRAINING else {}
        try:
            day.full_clean(exclude=["md_label"])
        except ValidationError as exc:
            raise ValidationError(f"{item['date'].isoformat()}: {'; '.join(exc.messages)}")
        day.save()
    relabel(mc)
    link_matches(mc)


def link_matches(mc: Microcycle) -> int:
    """Point each match day at the match loaded in SLAB (`MicrocycleDay.event`);
    a day that stops being a match loses its link. Returns how many changed."""
    days = list(mc.days.all())
    links = match_links(mc.club, mc.season, mc.bracket,
                        {d.date: d.kind for d in days if d.is_match})
    changed = []
    for d in days:
        event_id = (links.get(d.date) or {}).get("event_id") if d.is_match else None
        if str(d.event_id or "") != str(event_id or ""):
            d.event_id = event_id
            changed.append(d)
    if changed:
        MicrocycleDay.objects.bulk_update(changed, ["event"])
    return len(changed)


@transaction.atomic
def update(mc: Microcycle, *, days: list[dict] | None = None, kind: str | None = None,
           notes: str | None = None) -> Microcycle:
    if mc.status == Microcycle.STATUS_CLOSED:
        raise ValidationError("Una semana cerrada no se edita.")
    if kind is not None:
        cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
        if kind and kind not in cfg["microcycle_kinds"]:
            raise ValidationError(f"Tipo de semana desconocido: {kind}.")
        mc.kind = kind
    if notes is not None:
        mc.notes = notes
    mc.save(update_fields=["kind", "notes", "updated_at"])
    if days is not None:
        _write_days(mc, days)
    return mc


# ── serialisation ────────────────────────────────────────────────────────────

def _changed_vs_copy(mc: Microcycle, days: list[MicrocycleDay]) -> dict[str, list[str]]:
    if mc.copied_from_id is None:
        return {}
    src: dict[str, dict] = {}
    for d in mc.copied_from.days.filter(kind=MicrocycleDay.KIND_TRAINING):
        src.setdefault(d.md_label, d.targets_pct or {})
    out = {}
    for d in days:
        if d.kind != MicrocycleDay.KIND_TRAINING:
            continue
        base = src.get(d.md_label, {})
        keys = sorted(k for k in set(base) | set(d.targets_pct or {})
                      if base.get(k) != (d.targets_pct or {}).get(k))
        if keys:
            out[d.date.isoformat()] = keys
    return out


def serialize_summary(mc: Microcycle) -> dict:
    return {"id": str(mc.id), "number": mc.number, "kind": mc.kind, "status": mc.status,
            "start_date": mc.start_date.isoformat(), "end_date": mc.end_date.isoformat()}


def serialize(mc: Microcycle) -> dict:
    team = team_of(mc)
    cfg = LoadControlConfig.resolved(mc.club, mc.bracket)
    from load_control.week import days_of

    # An unplanned week (`load_control.week`) has its days in memory only.
    days = (list(days_of(mc)) if getattr(mc, "_week_days", None) is not None
            else list(mc.days.select_related("event").all()))
    links = match_links(mc.club, mc.season, mc.bracket,
                        {d.date: d.kind for d in days if d.is_match})
    preview = not mc.is_frozen
    if preview:
        # A draft shows the reference it WOULD freeze, recomputed each read.
        reference = compute_reference(club=mc.club, bracket=mc.bracket,
                                      anchor=mc.start_date, cfg=cfg)
        holder = Microcycle(ref_snapshot=reference)
    else:
        reference, holder = mc.ref_snapshot, mc
    groups = {g["code"]: g["label"] for g in cfg["position_groups"]}
    return {
        **serialize_summary(mc),
        "season": mc.season,
        "team": {"label": team.label, "bracket_id": str(mc.bracket_id),
                 "bracket": mc.bracket.name,
                 "categories": [c.name for c in team.categories()]},
        "notes": mc.notes,
        "frozen_at": mc.frozen_at.isoformat() if mc.frozen_at else None,
        "copied_from": serialize_summary(mc.copied_from) if mc.copied_from_id else None,
        "metrics": cfg["metrics"],
        "groups": [{"code": c, "label": groups.get(c, c)}
                   for c in (reference.get("groups") or {})],
        "kinds": cfg["microcycle_kinds"],
        "reference": {**reference, "preview": preview},
        "days": [{"date": d.date.isoformat(), "weekday": WEEKDAYS[d.date.weekday()],
                  "kind": d.kind, "md_label": d.md_label, "md_label_source": d.md_label_source,
                  "targets_pct": d.targets_pct,
                  # Stored link, else the one it would get (a plan saved before
                  # the match was loaded, or before links existed).
                  "event_id": (str(d.event_id) if d.event_id
                               else (links.get(d.date) or {}).get("event_id") if d.is_match else None),
                  "opponent": (links.get(d.date) or {}).get("opponent")} for d in days],
        "targets": {d.date.isoformat(): day_targets(holder, d) for d in days},
        "changed_vs_copy": _changed_vs_copy(mc, days),
    }


def serialize_suggestion(team: Team, s: dict) -> dict:
    labels = labels_for(team.club, team.season, team.bracket, s["start_date"], s["end_date"],
                        [(d["date"], d["kind"] in MicrocycleDay.MATCH_KINDS) for d in s["days"]],
                        _neighbours_for(team, s["start_date"], s["end_date"]))
    kinds = LoadControlConfig.resolved(team.club, team.bracket)["microcycle_kinds"]
    links = match_links(team.club, team.season, team.bracket,
                        {d["date"]: d["kind"] for d in s["days"] if d["kind"] in MicrocycleDay.MATCH_KINDS})
    return {"start_date": s["start_date"].isoformat(), "end_date": s["end_date"].isoformat(),
            "number": s["number"], "kind": s["kind"], "kinds": kinds,
            "copy_from": serialize_summary(s["copy_from"]) if s["copy_from"] else None,
            "days": [{"date": d["date"].isoformat(), "weekday": WEEKDAYS[d["date"].weekday()],
                      "kind": d["kind"], "md_label": labels[d["date"]][0],
                      "md_label_source": labels[d["date"]][1],
                      "event_id": (links.get(d["date"]) or {}).get("event_id"),
                      "opponent": (links.get(d["date"]) or {}).get("opponent")} for d in s["days"]]}


def _neighbours_for(team: Team, start: date, end: date) -> list[date]:
    probe = Microcycle(club=team.club, season=team.season, bracket=team.bracket,
                       start_date=start, end_date=end)
    return neighbour_matches(probe)
