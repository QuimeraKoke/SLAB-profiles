"""Light DTOs for the VALD Hub integration.

Only `ValdProfile` gets a typed wrapper (the sync's player-matching reads a
handful of stable fields). Test payloads stay raw dicts — their metric shape
differs per product and is mapped explicitly in `exams/services/vald_sync.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValdProfile:
    """A VALD athlete profile, trimmed to what player-matching needs."""

    profile_id: str
    given_name: str
    family_name: str
    date_of_birth: str | None  # ISO date string or None
    external_id: str
    sync_id: str
    modified_date_utc: str | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> "ValdProfile":
        dob = item.get("dateOfBirth")
        # VALD returns date-time; keep just the date portion when present.
        if isinstance(dob, str) and "T" in dob:
            dob = dob.split("T", 1)[0]
        return cls(
            profile_id=str(item.get("profileId") or ""),
            given_name=(item.get("givenName") or "").strip(),
            family_name=(item.get("familyName") or "").strip(),
            date_of_birth=dob or None,
            external_id=(item.get("externalId") or "").strip(),
            sync_id=(item.get("syncId") or "").strip(),
            modified_date_utc=item.get("modifiedDateUtc"),
            raw=item,
        )

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()
