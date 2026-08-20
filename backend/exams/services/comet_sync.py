"""Pull PLAYED matches from COMET LIVE into SLAB.

Two targets per match, matching how the data is actually shaped:

  * the match **Event** gets the general, non-player facts (score, half-time
    score, round, competition, referee, venue, official match id) written into
    `Event.metadata`, following the exact key convention `fixtures_sync`
    established — plus the raw lineups/events blobs into `MatchData`
    (`source="comet"`), which already exists for imported match detail.
  * the **"Ficha oficial de partido"** template gets one ExamResult per
    (player, match): titular, minutos, dorsal, capitán, goles, asistencias,
    autogoles, penales, tarjetas.

Per-club, not per-category: one COMET team id returns matches for every
category the club enters, so the category is resolved from each match's
competition via `CometCompetitionLink`.

Deliberate non-goals: no future fixtures (the calendar slice is separate) and
no physical metrics — COMET has none, that's Catapult's job.

Two field-level traps this module exists to get right, both verified against
live ANFP data:
  * minutes come from the lineup's `starting` flag plus substitution events, and
    substitution minutes must be read from `minuteFull` (the match minute), NOT
    `minute` (which restarts each half — a 64' change reads as 19).
  * on a Substitution, `player` comes ON and `player2` goes OFF.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone as _tz
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import Player
from events.models import Event, EventParticipant, MatchData
from exams.calculations import compute_result_data
from exams.models import (
    CometCompetitionLink, CometPlayerLink, ExamResult, ExamTemplate,
)
from integrations.comet.client import CometClient
from integrations.comet.exceptions import CometError

logger = logging.getLogger(__name__)

SOURCE = "comet"
# Official minutes cap at regulation; COMET reports a full match as 90 even
# though the clock runs past it (confirmed against /player/{id}/stats).
FULL_TIME = 90
EXTRA_TIME = 120
# ±16h, same tolerance fixtures_sync uses to adopt an event created by another
# source (the GPS importer keys events by date, not kickoff).
EVENT_MATCH_WINDOW = timedelta(hours=16)

_SUB_RE = re.compile(r"\bsub\s*\.?\s*(\d{1,2})\b", re.IGNORECASE)


# ---------- competition → category ----------

def _category_from_names(*names: str) -> int | None:
    """The `Sub NN` age number in any of the given strings, or None.

    Checks every name because for cup/CONMEBOL ties the competition `name` is
    only the phase and the age lives in the parent ("Grupo 2" under
    "Sub 12 Apertura 2025"). Returns the number, not a Category.
    """
    for name in names:
        if not name:
            continue
        m = _SUB_RE.search(name)
        if m:
            return int(m.group(1))
    return None


def _resolve_category(club, comp: dict, roster_by_age: dict[int, Any], default_category):
    """(category, auto) for a COMET competition dict."""
    age = _category_from_names(comp.get("name") or "", comp.get("parentName") or "")
    if age is not None:
        cat = roster_by_age.get(age)
        return (cat, True) if cat else (None, False)
    # No age token → a senior competition (Primera, Copa Chile, CONMEBOL…).
    return (default_category, True) if default_category else (None, False)


def _category_index(club) -> dict[int, Any]:
    """{age_number: Category} from names like 'SUB-15'."""
    from core.models import Category

    out: dict[int, Any] = {}
    for cat in Category.objects.filter(club=club):
        m = re.search(r"(\d{1,2})", cat.name or "")
        # Skip the women's categories: COMET's feed for this tenant carries no
        # femenino competitions, so mapping them would create phantom links.
        if m and "F" not in (cat.name or "").upper().replace("SUB", ""):
            out.setdefault(int(m.group(1)), cat)
    return out


# ---------- player matching ----------

def _norm(s: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _name_tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if len(t) > 1}


def _resolve_player(person: dict, roster: list) -> tuple[Any, str]:
    """COMET person → (Player, match_method). COMET names are 'LAST FIRST'."""
    ptoks = _name_tokens(person.get("name") or "")
    if not ptoks:
        return None, CometPlayerLink.MATCH_UNRESOLVED
    cands = [
        p for p in roster
        if _name_tokens(f"{p.first_name} {p.last_name}") & ptoks
        and _name_tokens(f"{p.first_name} {p.last_name}") <= ptoks
    ]
    if len(cands) == 1:
        return cands[0], CometPlayerLink.MATCH_NAME
    if len(cands) > 1:
        return None, CometPlayerLink.MATCH_UNRESOLVED
    return None, CometPlayerLink.MATCH_UNRESOLVED


# ---------- per-match derivation ----------

def _our_side(match: dict, team_id: int) -> str | None:
    """'home' | 'away' — which side of the match is us."""
    if str((match.get("homeTeam") or {}).get("id")) == str(team_id):
        return "home"
    if str((match.get("awayTeam") or {}).get("id")) == str(team_id):
        return "away"
    return None


def _went_to_extra_time(events: list[dict]) -> bool:
    return any(
        "EXTRA" in ((e.get("matchPhase") or {}).get("fcdName") or "").upper()
        for e in events
    )


def build_player_rows(lineup_players: list[dict], events: list[dict], is_home: bool) -> dict[int, dict]:
    """{personId: raw_data} for the ficha template, from lineup + events.

    Minutes: starters open at 0; substitutes open at their `minuteFull`; anyone
    replaced closes at theirs. A player on the bench who never came on gets 0
    minutes and is still recorded (an official 0 is information — it says they
    were available and unused).
    """
    end = EXTRA_TIME if _went_to_extra_time(events) else FULL_TIME
    rows: dict[int, dict] = {}
    for p in lineup_players:
        pid = p.get("personId")
        if pid is None:
            continue
        rows[pid] = {
            "titular": bool(p.get("starting")),
            "capitan": bool(p.get("captain")),
            "dorsal": p.get("shirtNumber"),
            "posicion_comet": (p.get("position") or "").strip(),
            "min_ingreso": 0 if p.get("starting") else None,
            "min_salida": None,
            "goles": 0, "asistencias": 0, "penales": 0, "autogoles": 0,
            "amarillas": 0, "rojas": 0,
        }

    for e in events:
        # Only our side's events; the payload carries both teams'.
        if bool(e.get("homeTeam")) != is_home:
            continue
        etype = ((e.get("eventType") or {}).get("name") or "").lower()
        fcd = ((e.get("eventType") or {}).get("fcdName") or "").upper()
        minute = e.get("minuteFull")  # NOT `minute` — that restarts each half.
        main = (e.get("player") or {}).get("personId")
        second = (e.get("player2") or {}).get("personId")

        if "substitution" in etype or fcd == "SUBSTITUTION":
            if main in rows:
                rows[main]["min_ingreso"] = minute
            if second in rows:
                rows[second]["min_salida"] = minute
            continue
        if main not in rows:
            continue
        if "own goal" in etype or fcd == "OWN_GOAL":
            rows[main]["autogoles"] += 1
        elif "penalty" in etype or "PENALTY" in fcd:
            rows[main]["goles"] += 1
            rows[main]["penales"] += 1
        elif "goal" in etype or fcd == "GOAL":
            rows[main]["goles"] += 1
            # COMET puts the assisting player in player2 on a goal event.
            if second in rows:
                rows[second]["asistencias"] += 1
        elif "yellow" in etype or "YELLOW" in fcd:
            rows[main]["amarillas"] += 1
        elif "red" in etype or "RED" in fcd:
            rows[main]["rojas"] += 1

    for row in rows.values():
        entered = row["min_ingreso"]
        left = row["min_salida"] if row["min_salida"] is not None else end
        row["minutos"] = max(0, left - entered) if entered is not None else 0
    return rows


# COMET liveStatus → the human string `status_long` carries. Written alongside
# `status` so the pair can't end up contradicting itself (an API-Football
# "Not Started" left next to a COMET "PLAYED" is worse than an overwrite).
_STATUS_LONG = {
    "PLAYED": "Jugado",
    "SCHEDULED": "Programado",
    "LIVE": "En juego",
    "CANCELLED": "Cancelado",
    "POSTPONED": "Postergado",
    "ABANDONED": "Abandonado",
}

# Roles that assert the player did NOT take part. COMET's minute count is the
# federation's official record, so it overrides these — but nothing else a human
# entered, since the remaining roles (selección, promovido…) carry context COMET
# cannot see.
_NON_PARTICIPATION = frozenset({
    EventParticipant.MatchRole.NO_CITADO,
    EventParticipant.MatchRole.CITADO_NO_VESTIR,
    EventParticipant.MatchRole.LESIONADO,
    EventParticipant.MatchRole.SUSPENDIDO,
})


def match_role_for(row: dict) -> str:
    """A COMET player row → `EventParticipant.match_role`."""
    if row.get("titular"):
        return EventParticipant.MatchRole.TITULAR
    if (row.get("minutos") or 0) > 0:
        return EventParticipant.MatchRole.SUPLENTE_INGRESA
    return EventParticipant.MatchRole.SUPLENTE_NO_INGRESA


def _sync_participation(event, player, row: dict) -> bool:
    """Upsert the player's participation for `event`. True if anything was written.

    `match_role` is not decoration. `api.triage` suppresses a player's entire
    performance block — GPS included — when the role is NULL, and shows no role
    label either, so a substitute who came on reads as though he was never
    called up. Writing the role is what makes his match data visible at all.
    """
    role = match_role_for(row)
    part, created = EventParticipant.objects.get_or_create(
        event=event, player=player,
        defaults={
            "attendance": EventParticipant.Attendance.ATTENDED,
            "match_role": role,
        },
    )
    if created:
        return True
    played = bool(row.get("titular")) or (row.get("minutos") or 0) > 0
    # Fill a blank; otherwise defer to the human, except when they recorded a
    # non-participation for someone the federation says actually played.
    if part.match_role and not (played and part.match_role in _NON_PARTICIPATION):
        return False
    part.match_role = role
    part.save(update_fields=["match_role"])
    return True


def build_event_metadata(
    match: dict, match_officials: list[dict], team_id: int,
    *, team_staff: list[dict] | None = None,
) -> dict:
    """General, non-player match facts for `Event.metadata`.

    Same key names `fixtures_sync` uses (competition / round / status / venue /
    is_home / opponent / score) so any consumer reads one shape regardless of
    which provider filled it, plus the COMET-only extras.

    `match_officials` must be the REFEREES from `/match/{id}/info`. The lineup's
    `officials` array is the club's own coaching staff — it belongs under
    `team_staff`, not here, or `referee` silently resolves to null.
    """
    side = _our_side(match, team_id)
    is_home = side == "home"
    home, away = match.get("homeTeam") or {}, match.get("awayTeam") or {}
    opponent = (away if is_home else home).get("name") or ""
    comp = match.get("competition") or {}
    hr, ar = match.get("homeTeamResult") or {}, match.get("awayTeamResult") or {}
    facility = match.get("facility") or {}
    status = match.get("liveStatus")
    referee = next(
        (o.get("name") for o in match_officials
         if (o.get("role") or "").strip().lower() == "referee"),
        None,
    )
    meta = {
        "comet_match_id": match.get("id"),
        "competition": comp.get("parentName") or comp.get("name"),
        "competition_phase": comp.get("name"),
        "competition_id": comp.get("id"),
        "round": match.get("round"),
        "round_order": match.get("roundOrder"),
        "match_number": match.get("matchNumber"),
        "status": status,
        "status_long": _STATUS_LONG.get(status, status),
        "venue": facility.get("name"),
        "is_home": is_home,
        "opponent": opponent,
        "opponent_comet_team_id": (away if is_home else home).get("id"),
        "score": {"home": hr.get("current"), "away": ar.get("current")},
        "score_half_time": {"home": hr.get("half"), "away": ar.get("half")},
        "referee": referee,
        "match_officials": [
            {"role": o.get("role"), "name": o.get("name")} for o in match_officials
        ],
    }
    if team_staff:
        meta["team_staff"] = [
            {"role": o.get("role"), "name": o.get("name")} for o in team_staff
        ]
    return meta


def _find_event(club, category, kickoff, comet_match_id):
    """Existing Event for this match: by COMET id, else by date (±16h)."""
    by_id = Event.objects.filter(
        club=club, metadata__comet_match_id=comet_match_id,
    ).first()
    if by_id is not None:
        return by_id
    return (
        Event.objects.filter(
            club=club, category=category, event_type=Event.TYPE_MATCH,
            starts_at__gte=kickoff - EVENT_MATCH_WINDOW,
            starts_at__lte=kickoff + EVENT_MATCH_WINDOW,
        )
        .order_by("starts_at")
        .first()
    )


# ---------- orchestration ----------

def sync_club(integration, *, dry_run: bool = True, since=None) -> dict:
    """Sync one club's played matches. Returns a JSON-friendly report."""
    club = integration.club
    report: dict[str, Any] = {
        "club": club.name, "status": "ok",
        "matches_seen": 0, "matches_ingested": 0,
        "skipped_unmapped_competition": 0, "skipped_no_event": 0,
        "skipped_not_played": 0, "skipped_existing": 0,
        "events_updated": 0, "events_created": 0,
        "results_created": 0, "players_unresolved": 0,
        "participants_written": 0,
        "competitions_new": 0, "unmapped_competitions": [], "unresolved_players": [],
        "errors": [],
    }
    if not integration.enabled:
        return {**report, "status": "skipped", "reason": "integración deshabilitada"}

    template = ExamTemplate.objects.filter(
        slug=integration.template_slug, department__club=club, is_active_version=True,
    ).first()
    if template is None:
        return {
            **report, "status": "skipped",
            "reason": f"plantilla '{integration.template_slug}' no encontrada (corre seed_ficha_partido)",
        }

    cutoff = since or (timezone.now() - timedelta(days=integration.lookback_days))
    roster = list(Player.objects.filter(category__club=club).select_related("category"))
    by_age = _category_index(club)
    default_category = by_age.get(0) or next(
        (c for c in {p.category for p in roster if p.category} if c.name == "Primer Equipo"),
        None,
    )
    now = timezone.now()

    with CometClient(
        integration.api_key, tenant=integration.tenant,
        team_id=integration.comet_team_id, organization_id=integration.organization_id,
        base_url=integration.base_url,
    ) as client:
        # Newest-first, so stop as soon as we read past the window instead of
        # paging the club's whole history (2 800+ matches for one 30-day run).
        for match in client.iter_past_matches(utc_offset=integration.utc_offset):
            ts = match.get("dateTimeUTC")
            if ts and datetime.fromtimestamp(ts / 1000, _tz.utc) < cutoff:
                break
            report["matches_seen"] += 1
            if match.get("liveStatus") != "PLAYED":
                report["skipped_not_played"] += 1
                continue
            if not ts:
                continue
            kickoff = datetime.fromtimestamp(ts / 1000, _tz.utc)

            comp = match.get("competition") or {}
            # NOT get_or_create: that writes even on a dry run, and it used to
            # persist the row with a NULL category (the in-memory resolution was
            # never saved) which then poisoned every later run, since a
            # pre-existing row skipped resolution entirely.
            link = CometCompetitionLink.objects.filter(
                integration=integration, competition_id=comp.get("id"),
            ).first()
            if link is None:
                link = CometCompetitionLink(
                    integration=integration, competition_id=comp.get("id"),
                    competition_name=comp.get("name") or "",
                    parent_name=comp.get("parentName") or "",
                )
                report["competitions_new"] += 1
            # Retry resolution whenever it's still unset — a row created before
            # a category existed must be able to resolve later. `ignored` is how
            # a human says "leave this alone".
            if link.category_id is None and not link.ignored:
                cat, auto = _resolve_category(club, comp, by_age, default_category)
                link.category, link.auto_resolved = cat, auto
            link.last_seen_at = now
            if not dry_run:
                link.save()

            if link.ignored:
                continue
            if link.category is None:
                report["skipped_unmapped_competition"] += 1
                label = comp.get("parentName") or comp.get("name")
                if label and label not in report["unmapped_competitions"]:
                    report["unmapped_competitions"].append(label)
                continue

            try:
                got = _ingest_match(
                    client, integration, template, match, kickoff, link.category,
                    roster, report, dry_run=dry_run, now=now,
                )
            except CometError as exc:
                logger.warning("COMET match %s failed: %s", match.get("id"), exc)
                report["errors"].append(f"match {match.get('id')}: {exc}")
                continue
            if got:
                report["matches_ingested"] += 1

    if not dry_run:
        integration.last_synced_at = now
        integration.save(update_fields=["last_synced_at", "updated_at"])
    return report


def _ingest_match(
    client, integration, template, match, kickoff, category, roster, report,
    *, dry_run: bool, now,
) -> bool:
    club = integration.club
    match_id = match.get("id")
    side = _our_side(match, integration.comet_team_id)
    if side is None:
        return False

    # Resolve the Event FIRST: a match we're going to skip shouldn't cost the
    # two per-match API calls. With youth calendars mostly absent from SLAB this
    # is the difference between ~12 calls and ~90 on a 45-day run.
    event = _find_event(club, category, kickoff, match_id)
    if event is None and not integration.create_missing_events:
        report["skipped_no_event"] += 1
        return False

    lineups = client.match_lineups(match_id)
    events = client.match_events(match_id)
    ours = lineups.get(side) or {}
    team_staff = ours.get("officials") or []      # OUR coaching staff, not referees
    players = ours.get("players") or []
    # `facility` only exists on the match record, and the referees only on
    # /info — neither is in the list payload the loop iterates.
    detail = client.match(match_id)
    match_officials = client.match_officials(match_id)
    full = {**match, **{k: v for k, v in detail.items() if v not in (None, {}, [])}}

    # Tournament context, fetched once here so the match view never calls COMET
    # inside a page request. Non-fatal: a missing table shouldn't lose a ficha.
    standings: list = []
    h2h: list = []
    if integration.store_raw_match_data:
        for label, fn, sink in (
            ("standings", client.match_standings, "standings"),
            ("h2h", lambda mid: client.match_head_to_head(
                mid, utc_offset=integration.utc_offset), "h2h"),
        ):
            try:
                value = fn(match_id)
            except CometError as exc:
                logger.info("COMET %s unavailable for match %s: %s", label, match_id, exc)
                value = []
            if sink == "standings":
                standings = value
            else:
                h2h = value

    metadata = build_event_metadata(
        full, match_officials, integration.comet_team_id, team_staff=team_staff,
    )
    home = (match.get("homeTeam") or {}).get("name") or ""
    away = (match.get("awayTeam") or {}).get("name") or ""

    if not dry_run:
        with transaction.atomic():
            if event is None:
                event = Event.objects.create(
                    club=club, category=category, department=template.department,
                    event_type=Event.TYPE_MATCH, scope=Event.SCOPE_CATEGORY,
                    title=f"{home} vs {away}", starts_at=kickoff,
                    location=metadata.get("venue") or "", metadata=metadata,
                )
                report["events_created"] += 1
            elif integration.update_event_metadata:
                # Merge: never clobber keys another source owns.
                event.metadata = {**(event.metadata or {}), **metadata}
                if not event.location and metadata.get("venue"):
                    event.location = metadata["venue"]
                event.save(update_fields=["metadata", "location", "updated_at"])
                report["events_updated"] += 1

            if integration.store_raw_match_data:
                MatchData.objects.update_or_create(
                    event=event,
                    defaults={
                        "source": SOURCE, "fixture_id": match_id,
                        "lineups": lineups, "events": events,
                        # COMET publishes no team match statistics — it's the
                        # official record, not analytics.
                        "team_statistics": [], "player_statistics": [],
                        "standings": standings, "head_to_head": h2h,
                    },
                )
    elif event is not None and integration.update_event_metadata:
        report["events_updated"] += 1

    rows = build_player_rows(players, events, is_home=(side == "home"))
    day = kickoff.date()

    for person_id, raw in rows.items():
        person = next((p for p in players if p.get("personId") == person_id), {})
        # Same reason as the competition link: get_or_create would write on a
        # dry run, and persist an unresolved row that never retries.
        link = CometPlayerLink.objects.filter(
            integration=integration, person_id=person_id,
        ).first()
        if link is None:
            link = CometPlayerLink(
                integration=integration, person_id=person_id,
                fifa_id=person.get("fifaId") or "",
                person_name=person.get("name") or "",
                shirt_number=person.get("shirtNumber"),
            )
        # A MANUAL link is a human decision — never re-derive it.
        if link.player_id is None and link.match_method != CometPlayerLink.MATCH_MANUAL:
            player, method = _resolve_player(person, roster)
            link.player, link.match_method = player, method
        link.last_seen_at = now
        if not dry_run:
            link.save()

        if link.player is None:
            report["players_unresolved"] += 1
            nm = person.get("name")
            if nm and nm not in report["unresolved_players"]:
                report["unresolved_players"].append(nm)
            continue

        # Deliberately BEFORE the ficha dedup: the participation link is a
        # separate fact from the exam row, so a re-run must still be able to
        # write (or repair) it. Bundling the two left every `match_role` NULL
        # once the ficha existed — see `_sync_participation`.
        if not dry_run and event is not None:
            if _sync_participation(event, link.player, raw):
                report["participants_written"] += 1

        exists = ExamResult.objects.filter(
            template__family_id=template.family_id, player=link.player,
            recorded_at__date=day,
        ).exists()
        if exists:
            report["skipped_existing"] += 1
            continue

        report["results_created"] += 1
        if dry_run:
            continue
        result_data, snapshot = compute_result_data(template, raw, player=link.player)
        ExamResult.objects.create(
            player=link.player, template=template, recorded_at=kickoff,
            result_data=result_data, inputs_snapshot=snapshot, event=event,
        )
    return True


def sync_all_clubs(*, dry_run: bool = True) -> list[dict]:
    from exams.models import CometIntegration

    reports = []
    for integ in CometIntegration.objects.filter(enabled=True).select_related("club"):
        try:
            reports.append(sync_club(integ, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001 — one club shouldn't abort the batch
            logger.exception("COMET sync failed for club %s: %s", integ.club_id, exc)
            reports.append({"club": integ.club.name, "status": "error", "reason": str(exc)})
    return reports
