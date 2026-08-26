"""Who counts as being in a category — the one implementation of that rule.

SLAB has two different answers to "who is in this team", and mixing them up is
the most reliably damaging mistake in this codebase:

* **Working group** = home players ∪ active call-ups. Anything you *do* with a
  squad — importing their data, showing the roster, writing notes — uses this.
* **Home roster** = a plain `category=` filter. Anything you *count* uses this,
  because a called-up player must not inflate two teams at once.

Measured on Universidad de Chile 2026, **26 % of youth appearances are loans**,
so the gap between those two is not an edge case.

This lives in `core` rather than `api.scoping` because the ingest paths need it
too, and a helper the importers can't import gets reimplemented — which is
exactly what happened: `bulk_ingest` grew its own copy while
`gps_session_ingest`, `wellness_ingest` and `catapult_sync` silently kept
matching against the home roster only, dropping every called-up player's row.
"""
from __future__ import annotations

from django.db.models import Q, QuerySet


def players_in_category(
    category, *, include_call_ups: bool = True, active_only: bool = True,
) -> QuerySet:
    """Players in `category` — the WORKING GROUP by default.

    Pass `include_call_ups=False` for counts and aggregation: call-ups are shown
    flagged, never counted. Callers can tell a call-up apart with
    `p.category_id != category.id`.

    `active_only=False` is for historical imports, where a file may name someone
    who has since left and dropping their rows would lose real data.
    """
    from core.models import Player

    qs = Player.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    if not include_call_ups:
        return qs.filter(category=category)
    return qs.filter(
        Q(category=category)
        | Q(call_ups__category=category, call_ups__active=True)
    ).distinct()


def player_ids_in_category(category, **kwargs) -> list:
    """The same set as a list of ids, for `player__in=` / `player_id__in=` filters.

    Worth its own name because the id list is what de-duplication lookups need:
    an importer that resolves a called-up player but then checks for existing
    rows with `player__category=category` will not find them, and will write the
    row a second time on the next run. Getting the match right and the dedup
    wrong just moves the bug.
    """
    return list(players_in_category(category, **kwargs).values_list("id", flat=True))
