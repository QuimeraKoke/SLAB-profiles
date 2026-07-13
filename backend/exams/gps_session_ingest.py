"""Reusable per-session GPS ingest — shared by the `import_gps_sessions`
management command (one-time backfill) and the training-GPS upload endpoint
(self-service). Orchestration over the pure `exams.gps_session` helpers.

Groups rows by **(player, session)** so a player who appears in two sessions on
the same day (e.g. main training + reintegro) becomes two results — unlike
`bulk_ingest`, which collapses everything per player. Idempotent; optional
match-Event creation (off for training).
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from core.models import Player, PlayerAlias
from events.models import Competition, Event, EventParticipant
from exams.models import ExamResult
from exams import gps_session as G


def result_data_for(p: dict) -> dict:
    data = {"fecha": p["date"].isoformat(), "sesion": p["label"], "tipo_sesion": p["tipo"]}
    data.update(p["data"])
    return data


def _recorded_at(d, event) -> datetime:
    if event is not None:
        return event.starts_at
    return timezone.make_aware(
        datetime.combine(d, time(12, 0)), timezone.get_current_timezone(),
    )


def _best_match_label(labels: list[str]) -> str:
    return max(labels, key=lambda s: (1 if " vs" in f" {s.lower()}" else 0, len(s)))


def get_or_create_match_event(cat, department, d, labels):
    """One match Event per (club, match-day). Title = best 'vs' label."""
    start = timezone.make_aware(
        datetime.combine(d, time(12, 0)), timezone.get_current_timezone(),
    )
    existing = Event.objects.filter(
        club=cat.club, event_type=Event.TYPE_MATCH, starts_at__date=d,
    ).first()
    if existing:
        return existing, False
    best = _best_match_label(labels)
    competition, opponent = G.parse_match_parts(best)
    event = Event.objects.create(
        club=cat.club, department=department, event_type=Event.TYPE_MATCH,
        title=best[:140], starts_at=start, scope=Event.SCOPE_CATEGORY, category=cat,
        metadata={
            "opponent": opponent or "", "competition": competition or "",
            "source": "gps_import", "raw_session_labels": sorted(set(labels)),
        },
    )
    return event, True


def _apply_updates(template, present, is_match) -> int:
    updated = 0
    for p in present:
        qs = ExamResult.objects.filter(template=template, player=p["player"])
        if is_match:
            qs = qs.filter(recorded_at__date=p["date"], event__isnull=False)
        else:
            qs = qs.filter(recorded_at__date=p["date"], result_data__sesion=p["label"])
        updated += qs.update(result_data=result_data_for(p))
    return updated


def run(
    file_bytes: bytes,
    *,
    template,
    category,
    dry_run: bool = True,
    create_events: bool = False,
    department=None,
    default_year: int = G.DEFAULT_YEAR,
    mode: str = "auto",
    update: bool = False,
    include_rows: bool = False,
    auto_create_events: bool = True,
) -> dict:
    """Parse + plan + (optionally) commit a per-session GPS export.

    Returns a JSON-friendly report including a per-session preview, the matched
    player list, and unmatched/undated breakdowns — suitable for both a CLI
    summary and a UI dry-run preview. Raises `gps_session.GpsParseError`.
    """
    has_days, rows = G.parse_workbook(file_bytes)
    if mode == "auto":
        mode = "match" if has_days else "training"
    is_match = mode == "match"
    do_events = is_match and create_events

    # Player index: alias first, then full name (scoped to the category).
    by_name = {
        G.normalize(f"{p.first_name} {p.last_name}"): p
        for p in Player.objects.filter(category=category)
    }
    by_alias = {
        G.normalize(a.value): a.player
        for a in PlayerAlias.objects.filter(player__category=category).select_related("player")
    }

    def resolve(label: str):
        n = G.normalize(label)
        return by_alias.get(n) or by_name.get(n)

    planned: list[dict] = []
    unmatched: dict[str, int] = {}
    undated: dict[str, int] = {}
    for r in rows:
        player = resolve(r.player_label)
        if player is None:
            unmatched[r.player_label] = unmatched.get(r.player_label, 0) + 1
            continue
        d = G.resolve_date(r, default_year=default_year)
        if d is None:
            undated[r.session] = undated.get(r.session, 0) + 1
            continue
        planned.append({
            "player": player, "date": d, "label": r.session,
            "tipo": G.classify_session(r.session, is_match_file=is_match),
            "data": G.build_result_data(r),
        })

    # Idempotency: match keyed (player, day); training keyed (player, day, session).
    existing: set = set()
    if is_match:
        for pid, rec in ExamResult.objects.filter(
            template=template, player__category=category, event__isnull=False,
        ).values_list("player_id", "recorded_at"):
            existing.add((pid, rec.date()))
    else:
        for pid, rec, data in ExamResult.objects.filter(
            template=template, player__category=category, event__isnull=True,
        ).values_list("player_id", "recorded_at", "result_data"):
            existing.add((pid, rec.date(), (data or {}).get("sesion")))

    fresh: list[dict] = []
    present: list[dict] = []
    seen: set = set(existing)
    for p in planned:
        key = ((p["player"].id, p["date"]) if is_match
               else (p["player"].id, p["date"], p["label"]))
        (present if key in seen else fresh).append(p)
        seen.add(key)

    created, skipped, updated = len(fresh), len(present), 0
    events_created = events_reused = blocked = 0
    events_by_date: dict = {}
    match_days: list[dict] = []

    # --- Match-day Event resolution. A match always has an Event: link to the
    # existing one. `auto_create_events` (backfill command) creates a missing
    # one; the UI sets it False, so missing match-days are surfaced for the
    # user to create the match first (their rows are blocked until then). ---
    if do_events:
        labels_by_date: dict = {}
        for p in planned:
            labels_by_date.setdefault(p["date"], []).append(p["label"])
        for d in sorted(labels_by_date):
            labels = labels_by_date[d]
            ev = Event.objects.filter(
                club=category.club, event_type=Event.TYPE_MATCH, starts_at__date=d,
            ).first()
            if ev is None and auto_create_events and not dry_run:
                ev, _ = get_or_create_match_event(category, department, d, labels)
            if ev is not None:
                events_reused += 1
            elif auto_create_events:
                events_created += 1  # would-create (dry-run) / will create on commit
            events_by_date[d] = ev
            comp, opp = G.parse_match_parts(_best_match_label(labels))
            ev_meta = (ev.metadata or {}) if ev else {}
            match_days.append({
                "date": d.isoformat(), "label": _best_match_label(labels),
                "opponent": opp or "", "competition": comp or "",
                "players": sum(1 for p in planned if p["date"] == d),
                "event_id": str(ev.id) if ev else None,
                "event_title": ev.title if ev else None,
                # The matched match's real details (shown to confirm the link).
                "event": None if ev is None else {
                    "title": ev.title,
                    "date": ev.starts_at.date().isoformat(),
                    "competition": ev_meta.get("competition"),
                    "opponent": ev_meta.get("opponent"),
                    "score": ev_meta.get("score"),
                },
            })

    def _linkable(p) -> bool:
        # Match mode without auto-create needs an existing Event for the day.
        return (not do_events) or auto_create_events or events_by_date.get(p["date"]) is not None

    if not dry_run:
        with transaction.atomic():
            writable = [p for p in fresh if _linkable(p)]
            blocked = len(fresh) - len(writable)
            to_create = [
                ExamResult(
                    player=p["player"], template=template,
                    recorded_at=_recorded_at(p["date"], events_by_date.get(p["date"]) if do_events else None),
                    result_data=result_data_for(p), inputs_snapshot={},
                    event=events_by_date.get(p["date"]) if do_events else None,
                )
                for p in writable
            ]
            ExamResult.objects.bulk_create(to_create, batch_size=400)
            created = len(to_create)

            # Tag each fresh row with its microcycle day (§1.e) from the
            # category's match calendar, so microcycle-scoped rules can fire.
            from exams.microcycle import apply_md_labels
            md_changed = apply_md_labels(to_create)
            if md_changed:
                ExamResult.objects.bulk_update(md_changed, ["result_data"], batch_size=400)
            if do_events:
                for p in writable:
                    ev = events_by_date.get(p["date"])
                    if ev is not None:
                        EventParticipant.objects.get_or_create(
                            event=ev, player=p["player"],
                            defaults={"attendance": EventParticipant.Attendance.ATTENDED},
                        )
            if update and present:
                updated = _apply_updates(template, present, is_match)
                skipped -= updated

            # bulk_create emits no post_save signals, so the side effects a
            # single registrar save gets for free are invoked explicitly:
            # every affected player's materialized state (weekly load, ACWR
            # inputs, match references) refreshes on commit, and each fresh
            # training row is checked against the ≥85%-of-match load alert
            # (self-filtered by slug + freshness, so match files and old
            # backfills no-op).
            from exams.signals import check_training_load_alert, enqueue_player_state_recompute

            players_by_id = {p["player"].id: p["player"] for p in writable}
            if update:
                players_by_id.update({p["player"].id: p["player"] for p in present})
            for pid in players_by_id:
                enqueue_player_state_recompute(pid)
            for result in to_create:
                check_training_load_alert(result)
            # Refresh each touched player's ACWR alert (§1.f) now that new load
            # landed — fires/clears against the category's configured band.
            from dashboards.acwr import evaluate_acwr_alerts
            for player in players_by_id.values():
                evaluate_acwr_alerts(player)
    else:
        blocked = sum(1 for p in fresh if not _linkable(p))
        created = len(fresh) - blocked

    # ----- preview / report -----
    sessions: dict[tuple, dict] = {}
    for p in planned:
        k = (p["label"], p["date"])
        s = sessions.setdefault(k, {"label": p["label"], "date": p["date"].isoformat(),
                                    "tipo": p["tipo"], "players": 0})
        s["players"] += 1
    matched_names = sorted({f"{p['player'].first_name} {p['player'].last_name}" for p in planned})

    # Competitions this team plays, from the synced Competition cache — each
    # with its date window + roster of rival teams. Scoped to the league_ids
    # that appear on this category's synced match events. Drives the inline
    # "create match" form's date-filtered competition + rival dropdowns.
    cfg = category.external_config or {}
    season = cfg.get("season")
    own_team_id = cfg.get("team_id")
    league_ids = {
        int(x) for x in Event.objects.filter(
            category=category, event_type=Event.TYPE_MATCH,
            metadata__has_key="api_football_fixture_id",
        ).values_list("metadata__league_id", flat=True) if x is not None
    }
    competitions = []
    if season and league_ids:
        for c in (Competition.objects.filter(
            provider="api_football", season=int(season), external_id__in=league_ids,
        ).prefetch_related("teams").order_by("name")):
            competitions.append({
                "league_id": c.external_id, "name": c.name,
                "start": c.start_date.isoformat() if c.start_date else None,
                "end": c.end_date.isoformat() if c.end_date else None,
                "teams": [
                    {"external_id": t.external_id, "name": t.name}
                    for t in c.teams.all().order_by("name")
                    if not (own_team_id and t.external_id == int(own_team_id))
                ],
            })

    # Per-(player, session) value rows for the UI preview ("see before save").
    # Gated so large backfills don't bloat the command's run-log.
    rows_view: list[dict] = []
    if include_rows:
        def _rv(p, status):
            return {
                "player": f"{p['player'].first_name} {p['player'].last_name}",
                "session": p["label"], "date": p["date"].isoformat(),
                "tipo": p["tipo"], "status": status, "values": p["data"],
            }
        rows_view = ([_rv(p, "nuevo") for p in fresh]
                     + [_rv(p, "existente") for p in present])
        rows_view.sort(key=lambda r: (r["date"], r["session"], r["player"]))

    return {
        "mode": mode,
        "rows": rows_view,
        "dry_run": dry_run,
        "total_rows": len(rows),
        "planned": len(planned),
        "created": created,
        "skipped": skipped,
        "updated": updated,
        "matched_players": len(matched_names),
        "players": matched_names,
        "events_created": events_created,
        "events_reused": events_reused,
        "blocked": blocked,
        # Match-day Event status (match mode) — drives the "create the match
        # first" flow in the UI. `needs_match` = some day has no Event yet.
        "match_days": match_days,
        "needs_match": any(m["event_id"] is None for m in match_days),
        "department_id": str(template.department_id),
        "competitions": competitions,
        "sessions": sorted(sessions.values(), key=lambda s: (s["date"], s["label"])),
        "unmatched": [{"code": k, "rows": v} for k, v in
                      sorted(unmatched.items(), key=lambda kv: -kv[1])],
        "undated": [{"session": k, "rows": v} for k, v in sorted(undated.items())],
    }
