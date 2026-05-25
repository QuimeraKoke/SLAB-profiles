"""Shared context object threaded through every phase.

Bundles the legacy DB connection, the audit log, the dry-run flag, the
scope window (date_from/date_to), the resolved SLAB Club + Departments,
and the cached lookup maps (legacy_id → SLAB UUID) so phases can
cross-reference without re-querying.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from core.models import Club, Department


_DRY_NS = uuid.UUID("12345678-1234-5678-1234-567812345678")


def dry_uuid(kind: str, legacy_id: Any) -> str:
    """Stable deterministic UUID used in dry-run lookups so cascading
    phases can resolve FKs without writing anything. Real runs replace
    these with the database-assigned UUIDs."""
    return str(uuid.uuid5(_DRY_NS, f"{kind}-{legacy_id}"))


@dataclass
class MigrationContext:
    legacy_db: Any                 # connection.LegacyDB instance
    audit: Any                     # audit.AuditLog instance
    dry_run: bool
    date_from: date                # scope start (inclusive)
    date_to: date                  # scope end (inclusive)
    club: Club                     # destination SLAB club
    limit: int | None = None       # per-phase row cap (None = no cap)
    # Skip the per-player photo download + storage copy. When True the
    # Player row is still created, just without `photo_url`. Useful for
    # local / fast re-runs where the Drive fetch is the slowest step.
    skip_photos: bool = False
    departments: dict[str, Department] = field(default_factory=dict)
    # Per-phase lookup caches: legacy_id → SLAB UUID. Populated as the
    # phases run; later phases (events, results) consume what earlier
    # phases (players, categories) wrote.
    category_by_legacy_id: dict[int, str] = field(default_factory=dict)   # id_categoria → Category UUID
    position_by_legacy_id: dict[int, str] = field(default_factory=dict)   # id_posicion → Position UUID
    player_by_legacy_id: dict[int, str] = field(default_factory=dict)     # id_jugador → Player UUID
    event_by_legacy_id: dict[int, str] = field(default_factory=dict)      # id_partido → Event UUID
    # Lookup used to resolve evaluacion_partido 2025+ rows that carry
    # only `citacion_id` (FKs to partido/jugador are NULL post-2025):
    # citacion_id → (legacy partido_id, legacy jugador_id).
    citacion_lookup: dict[int, tuple[int, int]] = field(default_factory=dict)

    def get_department(self, slug: str) -> Department:
        """Cached department lookup."""
        if slug not in self.departments:
            self.departments[slug] = Department.objects.get(club=self.club, slug=slug)
        return self.departments[slug]
