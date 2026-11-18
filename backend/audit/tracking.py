"""Change tracking: every create, edit and delete of a clinical or staff record.

Signals, not per-endpoint code, so every write path is covered: the web, the
admin, the Celery syncs and the management commands. What signals cannot see:
`bulk_create`/`bulk_update`/`QuerySet.update()` (the bulk importers) — those
log one summary event themselves via `log_bulk`.

An edit that changes nothing (a sync re-saving the same row) logs nothing.
"""
from __future__ import annotations

import datetime as dt
import decimal
import logging
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import m2m_changed, post_save, pre_delete, pre_save

from . import context
from .models import ChangeEvent

logger = logging.getLogger(__name__)

# Fields that change on their own or are bulky copies of something else.
_SKIP = {"created_at", "updated_at", "uploaded_at", "legacy_raw", "inputs_snapshot", "last_login",
         "password"}


# ── What is tracked, and how each row finds its club and player ────────────

def _player_of(model_label, obj):
    """(player, label) for a tracked row; player may be None."""
    from core.models import Player

    if model_label == "core.Player":
        return obj, "Datos del jugador"
    if model_label == "exams.ExamResult":
        name = getattr(obj.template, "name", "") if obj.template_id else ""
        when = obj.recorded_at.date().strftime("%d-%m-%Y") if obj.recorded_at else ""
        return obj.player, " · ".join(x for x in (name, when) if x)
    if model_label == "exams.Episode":
        return obj.player, f"Lesión: {obj.title}" if obj.title else "Lesión"
    if model_label == "exams.EpisodeNote":
        return obj.episode.player, f"Bitácora de lesión · {obj.entry_date:%d-%m-%Y}" if obj.entry_date else "Bitácora de lesión"
    if model_label == "core.DailyNote":
        return obj.player, f"Nota diaria · {obj.date:%d-%m-%Y}" if obj.date else "Nota diaria"
    if model_label == "core.KineDailyEntry":
        return obj.player, f"Plan kinésico · {obj.date:%d-%m-%Y}" if obj.date else "Plan kinésico"
    if model_label == "core.PlayerCallUp":
        return obj.player, "Convocatoria"
    if model_label == "core.Contract":
        return obj.player, "Contrato"
    if model_label == "attachments.Attachment":
        player = None
        try:
            from exams.models import EpisodeNote, ExamResult
            from core.models import Contract
            lookup = {"exam_result": ExamResult, "exam_field": ExamResult, "contract": Contract,
                      "episode_note": EpisodeNote}.get(obj.source_type)
            src = lookup.objects.filter(pk=obj.source_id).first() if lookup else None
            if src is not None:
                player = src.episode.player if lookup is EpisodeNote else src.player
        except Exception:  # noqa: BLE001 — a label must never break a save
            player = None
        return player, f"Adjunto: {obj.filename}"
    return None, ""


def _club_of(model_label, obj, player):
    if player is not None:
        cat = getattr(player, "category", None)
        return str(cat.club_id) if cat is not None else ""
    if model_label == "core.StaffMembership":
        return str(obj.club_id)
    if model_label == "auth.User":
        from core.models import StaffMembership
        cid = StaffMembership.objects.filter(user_id=obj.pk).values_list("club_id", flat=True).first()
        return str(cid) if cid else ""
    return context.current().club_id or ""


def _label_of(model_label, obj):
    if model_label == "auth.User":
        return f"Usuario: {obj.email or obj.get_username()}"
    if model_label == "core.StaffMembership":
        return f"Accesos de {obj.user.email}" if obj.user_id else "Accesos"
    return ""


def tracked_models():
    from attachments.models import Attachment
    from core.models import Contract, DailyNote, KineDailyEntry, Player, PlayerCallUp, StaffMembership
    from exams.models import Episode, EpisodeNote, ExamResult

    return [ExamResult, Episode, EpisodeNote, Player, DailyNote, KineDailyEntry, PlayerCallUp,
            Contract, Attachment, StaffMembership, get_user_model()]


# ── Serialisation ──────────────────────────────────────────────────────────

def _json(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (decimal.Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, dict):
        return {str(k): _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_json(x) for x in v]
    if hasattr(v, "name"):  # FieldFile
        return v.name or None
    return str(v)


def _snapshot(obj) -> dict:
    out = {}
    for f in obj._meta.concrete_fields:
        if f.name in _SKIP:
            continue
        out[f.attname] = _json(f.value_from_object(obj))
    return out


def _diff(before: dict, after: dict) -> dict:
    changes = {}
    for k in after.keys() | before.keys():
        a, b = before.get(k), after.get(k)
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            # JSON payloads (result_data, metrics): one entry per changed key.
            for sub in a.keys() | b.keys():
                if a.get(sub) != b.get(sub):
                    changes[f"{k}.{sub}"] = [a.get(sub), b.get(sub)]
        else:
            changes[k] = [a, b]
    return changes


# ── Writing events ─────────────────────────────────────────────────────────

def _write(action, obj, changes):
    label = obj._meta.label
    try:
        player, olabel = _player_of(label, obj)
    except Exception:  # noqa: BLE001 — parent already gone (cascade)
        player, olabel = None, ""
    a = context.current()
    ChangeEvent.objects.create(
        action=action, model=label, object_id=str(obj.pk),
        object_label=(olabel or _label_of(label, obj))[:200],
        club_id=_club_of(label, obj, player) or "",
        player_id=str(player.pk) if player is not None else "",
        player_name=_player_name(player),
        actor_id=a.user_id, actor_email=a.email, source=a.source, ip=a.ip,
        changes=changes,
    )


def _player_name(player) -> str:
    if player is None:
        return ""
    return " ".join(x for x in (player.first_name, player.last_name) if x)[:200]


def log_bulk(model_label: str, count: int, *, club_id: str = "", detail: str = "") -> None:
    """One event for a bulk write that bypasses signals (importers)."""
    if not count:
        return
    a = context.current()
    ChangeEvent.objects.create(
        action=ChangeEvent.CREATE, model=model_label, object_id="(varios)",
        object_label=f"Carga masiva: {count} registros{' · ' + detail if detail else ''}"[:200],
        club_id=club_id or a.club_id or "", actor_id=a.user_id, actor_email=a.email,
        source=a.source, ip=a.ip, changes={"registros": count},
    )


def log_bulk_results(objs, *, action: str, source: str) -> None:
    """One summary event per club for ExamResults written in bulk by a sync.

    `bulk_create`/`bulk_update` skip the signals; the row-level detail stays
    in the results themselves, this records that the sync wrote them.
    """
    objs = list(objs or [])
    if not objs:
        return
    try:
        from collections import Counter

        from core.models import Player
        from exams.models import ExamTemplate

        club_of = dict(Player.objects.filter(pk__in={o.player_id for o in objs})
                       .values_list("pk", "category__club_id"))
        tpl = dict(ExamTemplate.objects.filter(pk__in={o.template_id for o in objs}).values_list("pk", "name"))
        per_club = Counter(str(club_of.get(o.player_id, "")) for o in objs)
        names = ", ".join(sorted({tpl.get(o.template_id, "") for o in objs} - {""}))[:120]
        a = context.current()
        verb = "creó" if action == ChangeEvent.CREATE else "actualizó"
        with transaction.atomic():
            for club, n in per_club.items():
                ids = [str(o.pk) for o in objs if str(club_of.get(o.player_id, "")) == club][:500]
                ChangeEvent.objects.create(
                    action=action, model="exams.ExamResult", object_id="(varios)",
                    object_label=f"Sincronización {verb} {n} registros · {names}"[:200], club_id=club,
                    actor_id=a.user_id, actor_email=a.email,
                    source=source if a.source == "sistema" else a.source,
                    ip=a.ip, changes={"registros": n, "ids": ids},
                )
    except Exception:  # noqa: BLE001 — the trail must never break a sync
        logger.exception("audit: no se pudo registrar la carga masiva")


def _safe(fn):
    """Run in a savepoint and swallow errors: a failed audit write must not
    poison the caller's transaction (Postgres aborts it on any error)."""
    def wrapper(*args, **kwargs):
        try:
            with transaction.atomic():
                fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 — the trail must never break the write
            logger.exception("audit: no se pudo registrar el cambio")
    return wrapper


@_safe
def _pre_save(sender, instance, raw=False, **kwargs):
    if raw or instance._state.adding or instance.pk is None:
        instance._audit_before = None
        return
    old = sender._base_manager.filter(pk=instance.pk).first()
    instance._audit_before = _snapshot(old) if old is not None else None


@_safe
def _post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    after = _snapshot(instance)
    before = getattr(instance, "_audit_before", None)
    if created or before is None:
        _write(ChangeEvent.CREATE, instance, after)
        return
    changes = _diff(before, after)
    pw_changed = (sender is get_user_model()
                  and getattr(instance, "_audit_password", None) not in (None, instance.password))
    if pw_changed:
        changes["contraseña"] = ["(oculta)", "(cambiada)"]
    if changes:
        _write(ChangeEvent.UPDATE, instance, changes)


@_safe
def _pre_save_user(sender, instance, raw=False, **kwargs):
    if raw or instance._state.adding:
        return
    instance._audit_password = (sender._base_manager.filter(pk=instance.pk)
                                .values_list("password", flat=True).first())


@_safe
def _pre_delete(sender, instance, **kwargs):
    # Resolve player/club now: after the delete a cascade may have removed them.
    instance._audit_snapshot = _snapshot(instance)
    _write(ChangeEvent.DELETE, instance, instance._audit_snapshot)


_M2M_LABEL = {"groups": "rol", "categories": "categorías", "departments": "departamentos"}


@_safe
def _m2m(sender, instance, action, pk_set, model, reverse=False, **kwargs):
    """Before → after of the whole set (role, categories, departments)."""
    if reverse or action not in ("pre_clear", "post_add", "post_remove", "post_clear"):
        return
    field = next((f.name for f in instance._meta.many_to_many if f.remote_field.through is sender), None)
    if field is None:
        return
    if action == "pre_clear":
        instance._audit_m2m_before = sorted(str(o) for o in getattr(instance, field).all())
        return
    after = sorted(str(o) for o in getattr(instance, field).all())
    changed = sorted(str(o) for o in model._default_manager.filter(pk__in=pk_set or []))
    if action == "post_add":
        before = sorted(set(after) - set(changed))
    elif action == "post_remove":
        before = sorted(set(after) | set(changed))
    else:
        before = getattr(instance, "_audit_m2m_before", [])
    if before != after:
        _write(ChangeEvent.UPDATE, instance, {_M2M_LABEL.get(field, field): [before, after]})


def connect():
    from core.models import StaffMembership

    User = get_user_model()
    for m in tracked_models():
        uid = m._meta.label
        pre_save.connect(_pre_save, sender=m, dispatch_uid=f"audit-pre-{uid}")
        post_save.connect(_post_save, sender=m, dispatch_uid=f"audit-post-{uid}")
        pre_delete.connect(_pre_delete, sender=m, dispatch_uid=f"audit-del-{uid}")
    pre_save.connect(_pre_save_user, sender=User, dispatch_uid="audit-pre-user-pw")
    for through in (StaffMembership.categories.through, StaffMembership.departments.through,
                    User.groups.through):
        m2m_changed.connect(_m2m, sender=through, dispatch_uid=f"audit-m2m-{through._meta.label}")
