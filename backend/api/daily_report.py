"""Daily ("la Daily") — morning planning-meeting aggregation.

One read that assembles the 8 AM cross-department meeting view, in the
order the staff actually runs the meeting:

1. **Lesionados** — every player not training with the group (injured /
   recovery / reintegration), with diagnosis, days out, stage, expected
   return, and GPS load vs. their habitual week.
2. **Alertas** — available players with active alerts (critical first).
3. The rest of the squad is the *anexo* (frontend reuses `/roster`).

Plus the meeting's own output: per-player **notes** tagged by department
("la pauta del día"), stored in `core.DailyNote`.

Everything returned here is JSON-serializable (dates → isoformat).
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta
from typing import Any

from django.utils import timezone

from core.models import DailyNote, Player
from exams.episode_lifecycle import stage_label as _stage_label
from exams.models import Episode
from goals.models import Alert, AlertStatus

_STATUS_LABEL = {
    Player.STATUS_INJURED: "Lesionado",
    Player.STATUS_RECOVERY: "Recuperación",
    Player.STATUS_REINTEGRATION: "Return to Train",
    Player.STATUS_AVAILABLE: "Disponible",
}
_STAGE_LABEL = {
    "injured": "Lesionado",
    "recovery": "Recuperación",
    "reintegration": "Return to Train",
    "closed": "Return to Play",
}
# Meeting order: worst first.
_STAGE_RANK = {"injured": 0, "recovery": 1, "reintegration": 2}

# GPS metrics compared "hoy vs. cuando estaba OK" on the lesionado cards.
# Per-session values from the training-type GPS templates (matches excluded —
# a rehabbing player's sessions are compared against his habitual trainings).
# `fields` maps template slug → result_data keys summed per session.
_GPS_TRAIN_SLUGS = ("gps_sesion",)
_MATCH_TIPOS = {"partido", "amistoso"}
_GPS_COMPARE = [
    {"key": "tot_dist", "label": "Distancia total", "unit": "m", "agg": "mean",
     "fields": {"gps_sesion": ["tot_dist"]}},
    {"key": "mpm", "label": "Ritmo", "unit": "m/min", "agg": "mean",
     "fields": {"gps_sesion": ["mpm"]}},
    {"key": "hsr", "label": "HSR", "unit": "m", "agg": "mean",
     "fields": {"gps_sesion": ["hsr"]}},
    {"key": "sprint", "label": "Sprint", "unit": "m", "agg": "mean",
     "fields": {"gps_sesion": ["sprint_dist"]}},
    {"key": "acc_dec", "label": "Acel + Desacel", "unit": "n", "agg": "mean",
     "fields": {"gps_sesion": ["acc_dec"]}},
    {"key": "max_vel", "label": "Vel. máxima", "unit": "km/h", "agg": "max",
     "fields": {"gps_sesion": ["max_vel"]}},
]
_BASELINE_DAYS = 56   # "cuando estaba OK": the 8 weeks before the injury
_CURRENT_DAYS = 7     # "cómo viene ahora": the last week of work


def parse_date(raw: str) -> date_cls:
    """Meeting date from the `?date=` param; today (local) when absent/bad."""
    try:
        return date_cls.fromisoformat(raw)
    except (TypeError, ValueError):
        return timezone.localdate()


def build_daily_report(category, target_date: date_cls, user) -> dict:
    now = timezone.now()
    players = list(
        Player.objects.filter(category=category, is_active=True)
        .select_related("position")
        .order_by("last_name", "first_name")
    )
    pids = [p.id for p in players]

    alerts = list(
        Alert.objects.filter(player_id__in=pids, status=AlertStatus.ACTIVE)
        .order_by("-severity", "-last_fired_at")
    )
    alerts_by_player: dict[Any, list] = {}
    for a in alerts:
        alerts_by_player.setdefault(a.player_id, []).append(a)

    from api.roster import _player_acwr
    acwr = _player_acwr(category, pids, with_detail=True)
    wellness = _latest_wellness(category, pids)
    notes_by_player, note_rows = _notes(category, target_date, user)

    out_players = [p for p in players if p.status != Player.STATUS_AVAILABLE]
    episodes = _open_episodes({p.id for p in out_players})
    gps_compare = _gps_compare(category, out_players, episodes, now)

    lesionados = [
        _lesionado(p, episodes.get(p.id), acwr.get(p.id), wellness.get(p.id),
                   alerts_by_player.get(p.id, []), notes_by_player.get(p.id, []),
                   gps_compare.get(p.id), target_date)
        for p in out_players
    ]
    lesionados.sort(key=lambda r: (
        _STAGE_RANK.get((r["episode"] or {}).get("stage"), 9),
        -(r["episode"] or {}).get("days_out", 0) if r["episode"] else 0,
        r["name"],
    ))

    alertas = _alert_rows(players, alerts_by_player)

    return {
        "date": target_date.isoformat(),
        "generated_at": now.isoformat(),
        "category": category.name,
        "kpis": _kpis(players, alerts, wellness, target_date),
        "lesionados": lesionados,
        "alertas": alertas,
        "kine": _kine_entries(category, target_date),
        "notes": note_rows,
        "players": [
            {"id": str(p.id), "name": f"{p.first_name} {p.last_name}".strip()}
            for p in players
        ],
        "departments": [
            {"id": str(d.id), "name": d.name, "slug": d.slug}
            for d in category.departments.all().order_by("name")
        ],
    }


# ─── Sections ─────────────────────────────────────────────────────────


def _kpis(players, alerts, wellness, target_date) -> dict:
    by_status: dict[str, int] = {}
    for p in players:
        by_status[p.status] = by_status.get(p.status, 0) + 1
    sev = {"critical": 0, "warning": 0}
    for a in alerts:
        if a.severity in sev:
            sev[a.severity] += 1
    tgt = target_date.isoformat()
    responded_ids = {pid for pid, w in wellness.items() if w and w.get("date") == tgt}
    no_respondieron = [
        {
            "player_id": str(p.id),
            "name": f"{p.first_name} {p.last_name}".strip(),
            "position": p.position.abbreviation if p.position else None,
            "injured": p.status != Player.STATUS_AVAILABLE,
        }
        for p in players if p.id not in responded_ids
    ]
    return {
        "disponibles": {
            "n": by_status.get(Player.STATUS_AVAILABLE, 0),
            "total": len(players),
        },
        "no_disponibles": {
            "n": len(players) - by_status.get(Player.STATUS_AVAILABLE, 0),
            "breakdown": [
                {"label": "lesionados", "n": by_status.get(Player.STATUS_INJURED, 0), "tone": "crit"},
                {"label": "recuperación", "n": by_status.get(Player.STATUS_RECOVERY, 0), "tone": "warn"},
                {"label": "return to train", "n": by_status.get(Player.STATUS_REINTEGRATION, 0), "tone": "info"},
            ],
        },
        "alertas": {"critical": sev["critical"], "warning": sev["warning"]},
        "wellness_hoy": {
            "n": len(responded_ids),
            "expected": len(players),
            "no_respondieron": no_respondieron,
        },
    }


def _lesionado(p, episode, acwr_meta, wellness, player_alerts, player_notes,
               gps_compare, target_date) -> dict:
    ep = None
    if episode is not None:
        data = episode["latest_data"]
        started = timezone.localtime(episode["started_at"]).date()
        diagnosed = _to_date(data.get("diagnosed_at")) or started
        expected = _to_date(data.get("expected_return_date"))
        # Real availability date ('disponible para citar') wins over the
        # per-result forecast. Days-out freezes once the player is available
        # (or the episode closes); otherwise it counts to target_date.
        avail_dt = episode.get("available_at")
        available = timezone.localtime(avail_dt).date() if avail_dt else None
        ended_dt = episode.get("ended_at")
        ended = timezone.localtime(ended_dt).date() if ended_dt else None
        end_anchor = available or ended or target_date
        ep = {
            "id": str(episode["id"]),
            "template_slug": episode["template_slug"],
            "title": episode["title"] or episode["template_name"],
            "stage": episode["stage"],
            "stage_label": episode.get("stage_label") or episode["stage"] or "—",
            "severity": data.get("severity") or None,
            "body_part": data.get("body_part") or None,
            "diagnosed_at": diagnosed.isoformat(),
            "days_out": max(0, (end_anchor - diagnosed).days),
            "available_at": available.isoformat() if available else None,
            "expected_return": expected.isoformat() if expected else None,
            "days_to_return": (
                None if available else ((expected - target_date).days if expected else None)
            ),
            "plan": (data.get("notes") or "").strip() or None,
        }

    load = None
    if acwr_meta:
        chronic = acwr_meta.get("chronic_week_km") or 0
        acute = acwr_meta.get("acute_km") or 0
        load = {
            **acwr_meta,
            # "está al 30% de lo que hace habitualmente" — this week's
            # volume vs. his typical (28d) week.
            "pct_habitual": round(acute / chronic * 100) if chronic else None,
        }

    return {
        "player_id": str(p.id),
        "name": f"{p.first_name} {p.last_name}".strip(),
        "initials": _initials(p),
        "photo": p.photo_url or None,
        "position": p.position.name if p.position else "—",
        "status": p.status,
        "status_label": _STATUS_LABEL.get(p.status, p.status),
        "episode": ep,
        "load": load,
        "gps_compare": gps_compare,
        "wellness": wellness,
        "alerts": [
            {"severity": a.severity, "message": a.message} for a in player_alerts[:3]
        ],
        "notes": player_notes,
    }


def serialize_kine(e) -> dict:
    """A kinesiology daily-tracking row (the 'Plan kinésico' table)."""
    return {
        "id": str(e.id),
        "player_id": str(e.player_id),
        "player_name": f"{e.player.first_name} {e.player.last_name}".strip(),
        "clinica": e.clinica,
        "gimnasio": e.gimnasio,
        "cancha": e.cancha,
        "objetivo": e.objetivo,
        "kinesiologo": e.kinesiologo,
    }


def _kine_entries(category, target_date) -> list[dict]:
    from core.models import KineDailyEntry
    entries = (
        KineDailyEntry.objects
        .filter(date=target_date, player__category=category)
        .select_related("player")
        .order_by("player__last_name", "player__first_name")
    )
    return [serialize_kine(e) for e in entries]


def _alert_rows(players, alerts_by_player) -> list[dict]:
    """Available players with active alerts — the 'después vemos alertas'
    part of the meeting. Non-available players surface in `lesionados`."""
    rows = []
    for p in players:
        if p.status != Player.STATUS_AVAILABLE:
            continue
        player_alerts = alerts_by_player.get(p.id)
        if not player_alerts:
            continue
        rows.append({
            "player_id": str(p.id),
            "name": f"{p.first_name} {p.last_name}".strip(),
            "initials": _initials(p),
            "worst": player_alerts[0].severity,
            "alerts": [
                {
                    "severity": a.severity,
                    "message": a.message,
                    "source_type": a.source_type,
                    "fired_at": a.last_fired_at.isoformat() if a.last_fired_at else None,
                }
                for a in player_alerts
            ],
        })
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda r: (sev_rank.get(r["worst"], 9), r["name"]))
    return rows


# ─── Data helpers ─────────────────────────────────────────────────────


def _gps_compare(category, out_players, episodes, now) -> dict:
    """Per lesionado: training-GPS per-session values, current week vs. the
    healthy baseline (the {_BASELINE_DAYS}d before the injury). This is the
    "está al 30% de lo que hace habitualmente" chart of the meeting.

    {player_id: {"metrics": [{key,label,unit,current,baseline,pct,
                              sessions_current,sessions_baseline}], ...}}
    """
    from exams.models import ExamResult, ExamTemplate

    if not out_players:
        return {}
    templates = {
        t.id: t.slug
        for t in ExamTemplate.objects.filter(
            slug__in=_GPS_TRAIN_SLUGS, applicable_categories=category,
        )
    }
    if not templates:
        return {}

    # Injury date per player (falls back to 28d ago when there's no episode,
    # so "baseline" still means "before the current problem").
    injured_at: dict[Any, Any] = {}
    for p in out_players:
        e = episodes.get(p.id)
        if e is not None:
            d = _to_date((e["latest_data"] or {}).get("diagnosed_at"))
            injured_at[p.id] = d or timezone.localtime(e["started_at"]).date()
        else:
            injured_at[p.id] = (now - timedelta(days=28)).date()

    earliest = min(injured_at.values()) - timedelta(days=_BASELINE_DAYS)
    rows = ExamResult.objects.filter(
        player_id__in=list(injured_at), template_id__in=list(templates),
        recorded_at__date__gte=earliest,
    ).values_list("player_id", "template_id", "recorded_at", "result_data")

    # Group each player's training sessions as (day, slug, data).
    sessions: dict[Any, list] = {pid: [] for pid in injured_at}
    for pid, tid, recorded_at, data in rows:
        slug = templates.get(tid)
        data = data or {}
        if slug == "gps_sesion" and (data.get("tipo_sesion") in _MATCH_TIPOS):
            continue  # trainings only — matches aren't a rehab comparable
        sessions[pid].append((timezone.localtime(recorded_at).date(), slug, data))

    def _agg(values, how):
        if not values:
            return None
        return max(values) if how == "max" else sum(values) / len(values)

    out = {}
    for pid, items in sessions.items():
        inj = injured_at[pid]
        # Baseline = the healthy weeks before the injury. Current = the last
        # _CURRENT_DAYS of *post-injury* work, anchored at the player's most
        # recent session (robust to stale uploads — "his latest week of work").
        post = [s for s in items if s[0] >= inj]
        anchor = max((s[0] for s in post), default=None)
        current_from = anchor - timedelta(days=_CURRENT_DAYS - 1) if anchor else None

        windows: dict[str, dict] = {"baseline": {}, "current": {}}
        for day, slug, data in items:
            if inj - timedelta(days=_BASELINE_DAYS) <= day < inj:
                window = "baseline"
            elif current_from and day >= current_from:
                window = "current"
            else:
                continue
            for spec in _GPS_COMPARE:
                keys = spec["fields"].get(slug) or []
                vals = [v for v in (_coerce(data.get(k)) for k in keys) if v is not None]
                if vals:
                    windows[window].setdefault(spec["key"], []).append(sum(vals))

        metrics = []
        for spec in _GPS_COMPARE:
            base_vals = windows["baseline"].get(spec["key"], [])
            cur_vals = windows["current"].get(spec["key"], [])
            baseline = _agg(base_vals, spec["agg"])
            current = _agg(cur_vals, spec["agg"])
            if baseline is None and current is None:
                continue
            metrics.append({
                "key": spec["key"],
                "label": spec["label"],
                "unit": spec["unit"],
                "current": round(current, 1) if current is not None else None,
                "baseline": round(baseline, 1) if baseline is not None else None,
                "pct": (
                    round(current / baseline * 100)
                    if (current is not None and baseline) else None
                ),
                "sessions_current": len(cur_vals),
                "sessions_baseline": len(base_vals),
            })
        if metrics:
            out[pid] = {
                "baseline_days": _BASELINE_DAYS,
                "current_days": _CURRENT_DAYS,
                "injured_at": inj.isoformat(),
                "current_to": anchor.isoformat() if anchor else None,
                "metrics": metrics,
            }
    return out


def _open_episodes(player_ids: set) -> dict:
    """Most relevant open episode per non-available player: prefer the
    `lesiones` template, then most recent. Includes the latest linked
    result's data (diagnosis / stage / expected return live there)."""
    from exams.models import ExamResult

    episodes = list(
        Episode.objects.filter(player_id__in=player_ids, status=Episode.STATUS_OPEN)
        .select_related("template")
        .order_by("-started_at")
    )
    chosen: dict[Any, Episode] = {}
    for e in episodes:
        cur = chosen.get(e.player_id)
        if cur is None or (e.template.slug == "lesiones" and cur.template.slug != "lesiones"):
            chosen[e.player_id] = e

    latest_data: dict[Any, dict] = {}
    for r in (
        ExamResult.objects.filter(episode_id__in=[e.id for e in chosen.values()])
        .order_by("episode_id", "-recorded_at")
        .values_list("episode_id", "result_data")
    ):
        latest_data.setdefault(r[0], r[1] or {})

    return {
        pid: {
            "id": e.id,
            "template_slug": e.template.slug or "",
            "template_name": e.template.name,
            "title": e.title,
            "stage": e.stage,
            "stage_label": _stage_label(e.template, e.stage),
            "started_at": e.started_at,
            "available_at": e.available_at,
            "ended_at": e.ended_at,
            "latest_data": latest_data.get(e.id, {}),
        }
        for pid, e in chosen.items()
    }


def _latest_wellness(category, pids) -> dict:
    """{player_id: {"score", "date"} | None} from the latest check-in."""
    from api import wellness as w

    fmax = w.field_max(category)
    latest = w.recent_by_player(category, pids, limit=1, with_dates=True)
    out = {}
    for pid, items in latest.items():
        if not items:
            continue
        rec, data = items[0]
        s = w.score(data, fmax)
        if s is not None:
            out[pid] = {"score": s, "date": timezone.localtime(rec).date().isoformat()}
    return out


def _notes(category, target_date, user) -> tuple[dict, list]:
    """Meeting notes for the date: ({player_id: [note, ...]}, flat list)."""
    notes = list(
        DailyNote.objects.filter(
            player__category=category, date=target_date, kind=DailyNote.KIND_PAUTA,
        )
        .select_related("player", "department", "created_by")
        .order_by("created_at")
    )
    by_player: dict[Any, list] = {}
    rows = []
    for n in notes:
        row = serialize_note(n, user)
        by_player.setdefault(n.player_id, []).append(row)
        rows.append(row)
    return by_player, rows


def serialize_note(n: DailyNote, user) -> dict:
    author = ""
    if n.created_by:
        author = (
            f"{n.created_by.first_name} {n.created_by.last_name}".strip()
            or n.created_by.username
        )
    return {
        "id": str(n.id),
        "player_id": str(n.player_id),
        "player_name": f"{n.player.first_name} {n.player.last_name}".strip(),
        "department": (
            {"id": str(n.department.id), "name": n.department.name, "slug": n.department.slug}
            if n.department else None
        ),
        "kind": n.kind,
        "date": n.date.isoformat(),
        "text": n.text,
        "author": author,
        "mine": bool(user and n.created_by_id == user.id),
        "created_at": n.created_at.isoformat(),
    }


def _to_date(raw) -> date_cls | None:
    if not raw:
        return None
    if isinstance(raw, date_cls):
        return raw
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def _initials(p) -> str:
    return ((p.first_name or " ")[0] + (p.last_name or " ")[0]).upper()


def _coerce(raw) -> float | None:
    if raw is None or isinstance(raw, bool) or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
