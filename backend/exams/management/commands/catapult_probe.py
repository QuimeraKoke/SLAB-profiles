"""Read-only Catapult connectivity + data probe — a manual test harness.

NO DB writes. Verifies the token/region, lists teams (with live athlete
counts), shows the most recent match + training, and prints per-athlete
`/stats` for one activity. With --match-slab it previews how that activity's
roster maps onto the local SLAB Primer Equipo roster (name+DOB) — the risky
part of the eventual sync.

    # token comes from the host .env (the container has no access to it):
    docker compose exec backend python manage.py catapult_probe \
        --token "$(grep TEST_UCHILE_CATAPULT_API_KEY .env | cut -d= -f2-)" \
        --match-slab

    # probe a specific activity instead of the latest match:
    ... --activity "vs Palestino"
"""
from __future__ import annotations

import os
import unicodedata
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

# Confirmed-valid slugs (a /stats call 422s on an unknown slug, so keep this
# to slugs we've verified; the full gps-field mapping is finalized in the sync).
PROBE_SLUGS = ["total_distance", "meterage_per_minute", "sprint_efforts"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").lower().split())


def _day(ts) -> str:
    try:
        return datetime.utcfromtimestamp(ts).date().isoformat()
    except Exception:  # noqa: BLE001
        return "?"


class Command(BaseCommand):
    help = "Read-only Catapult OpenField probe (connection + sample data). No writes."

    def add_arguments(self, parser):
        parser.add_argument("--token", default=os.environ.get("TEST_UCHILE_CATAPULT_API_KEY", ""))
        parser.add_argument("--base-url", default=None, help="Override the API base URL.")
        parser.add_argument("--activity", default=None,
                            help="Name substring to probe (default: most recent match).")
        parser.add_argument("--match-slab", action="store_true",
                            help="Preview roster → SLAB Primer Equipo matching.")

    def handle(self, *args, **opts):
        from integrations.catapult.client import DEFAULT_BASE_URL, CatapultClient
        from integrations.catapult.exceptions import CatapultError

        token = (opts["token"] or "").strip()
        if not token:
            raise CommandError("Pass --token (or set TEST_UCHILE_CATAPULT_API_KEY).")
        client = CatapultClient(token, base_url=opts["base_url"] or DEFAULT_BASE_URL)

        w = self.stdout.write
        try:
            teams = client.teams()
            athletes = client.athletes()
            acts = client.activities()
        except CatapultError as exc:
            raise CommandError(f"Catapult API error: {exc}")

        from collections import Counter
        cnt = Counter(a.get("current_team_id") for a in athletes
                      if not a.get("is_deleted") and not a.get("is_demo"))
        w(self.style.SUCCESS(f"✓ connected — {len(teams)} teams, {len(athletes)} athletes, "
                             f"{len(acts)} activities"))
        w("\nTeams (name · live athletes · id):")
        for t in sorted(teams, key=lambda t: -cnt.get(t["id"], 0)):
            w(f"   {(t.get('name') or '')[:30]:30}  {cnt.get(t['id'],0):>3}  {t['id']}")

        # pick the activity to probe
        acts.sort(key=lambda a: a.get("start_time") or 0, reverse=True)
        if opts["activity"]:
            q = opts["activity"].lower()
            target = next((a for a in acts if q in (a.get("name") or "").lower()), None)
            if target is None:
                raise CommandError(f"No activity matching {opts['activity']!r}.")
        else:
            target = next((a for a in acts if " vs " in (a.get("name") or "").lower()), acts[0])

        latest_match = next((a for a in acts if " vs " in (a.get("name") or "").lower()), None)
        latest_train = next((a for a in acts if (a.get("name") or "").startswith("Sesión")), None)
        w("\nMost recent:")
        for label, a in [("match", latest_match), ("training", latest_train)]:
            if a:
                w(f"   {label:9} {a.get('name')!r}  ({_day(a.get('start_time'))}, "
                  f"{a.get('athlete_count')} athletes)")

        w(self.style.MIGRATE_HEADING(f"\nProbing: {target.get('name')!r} ({_day(target.get('start_time'))})"))
        roster = client.activity_athletes(target["id"])
        try:
            rows = client.stats(target["id"], PROBE_SLUGS)
        except CatapultError as exc:
            raise CommandError(f"/stats failed: {exc}")
        by_id = {r.get("athlete_id"): r for r in rows}
        w(f"   roster={len(roster)}  stats_rows={len(rows)}  metrics={PROBE_SLUGS}")
        w(f"\n   {'athlete':26} {'dist(m)':>9} {'m/min':>7} {'sprints':>7}")
        for a in roster[:30]:
            r = by_id.get(a["id"], {})
            name = f"{a.get('first_name','')} {a.get('last_name','')}"[:26]
            w(f"   {name:26} {r.get('total_distance',0):>9.0f} "
              f"{r.get('meterage_per_minute',0):>7.1f} {int(r.get('sprint_efforts',0) or 0):>7}")

        if opts["match_slab"]:
            self._match_slab(roster, w)

    def _match_slab(self, roster, w):
        from core.models import Player, PlayerAlias
        players = list(Player.objects.filter(
            category__name="Primer Equipo", category__club__name="Universidad de Chile"))
        by_dob, by_name = {}, {}
        for p in players:
            if p.date_of_birth:
                by_dob.setdefault(p.date_of_birth.isoformat(), []).append(p)
            by_name[_norm(f"{p.first_name} {p.last_name}")] = p
        for a in PlayerAlias.objects.filter(player__in=players):
            by_name[_norm(a.value)] = a.player
        matched, unmatched = 0, []
        for a in roster:
            d = a.get("date_of_birth_date")
            nm = _norm(f"{a.get('first_name')} {a.get('last_name')}")
            hit = (by_dob[d][0] if d and len(by_dob.get(d, [])) == 1 else by_name.get(nm))
            if hit:
                matched += 1
            else:
                unmatched.append(f"{a.get('first_name')} {a.get('last_name')} (dob {d})")
        w(self.style.MIGRATE_HEADING(
            f"\nSLAB match (LOCAL roster, {len(players)} players): {matched}/{len(roster)}"))
        for u in unmatched:
            w(self.style.WARNING(f"   unmatched: {u}"))
        w("   (note: match against PROD for the real picture — local can be stale)")
