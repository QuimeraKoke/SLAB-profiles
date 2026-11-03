"""The club's calendar day of an instant.

The project runs in UTC (`TIME_ZONE = "UTC"`). That is right for the GPS and
wellness rows, which are DATE-only readings stored at UTC midnight. It is wrong
for an instant: a match kicking off at 21:30 in Santiago is 00:30 UTC the next
day, and youth fixtures COMET dates 01:00 UTC on the round's Monday are Sunday
22:00 here. Whoever asks "which day was this match?" asks it in local time.

`CLUB_TIME_ZONE` (setting, default America/Santiago) — every club so far is
Chilean; a per-club zone can replace this when one is not.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings


def local_tz() -> ZoneInfo:
    return ZoneInfo(getattr(settings, "CLUB_TIME_ZONE", "America/Santiago"))


def local_date(dt: datetime) -> date:
    """The local calendar day of an aware instant (a kickoff, a match sheet)."""
    return dt.astimezone(local_tz()).date()
