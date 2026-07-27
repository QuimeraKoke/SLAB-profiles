# Strategy — player call-ups (secondary category membership)

**Goal.** Model the academy reality that a player belongs to one **home**
category but can be *called up* to another (a SUB-20 who trains/plays with — and
is being groomed for — the Primer Equipo). Give the call-up category's staff
**equal working access** to that player, show the player **flagged** in that
category's views, and **do not double-count** them in that category's team
stats. Do it **without** rewriting the single-category data model.

Immediate driver: the 5-componentes anthropometry report lists youth players
(e.g. Franco Fernandez, Jose Tomas Alburquenque — SUB-20) inside the first-team
report. Call-ups let a Primer-Equipo bulk upload match them, store the result on
their own record, and show them flagged — no fuzzy club-wide matching, no data
loss.

---

## 1. Decisions locked

1. **Aggregation:** team stats/counts are **main-category only**. A call-up is
   shown **flagged** in the call-up category's views but is **not folded into**
   its averages, "disponibles X/Y", dashboards, or reports. (No double-count.)
2. **Permissions / access:** the secondary category works **equally** to the
   main one — a category's staff can view, edit, add exams / notes / injuries
   for its call-ups just like its home players. (Access is equal; **counting**
   is not — see §3, the load-bearing rule.)
3. **Rollout:** phased; phase 1 unblocks the penta bulk import.

---

## 2. Data model (additive — the FK stays authoritative)

- **`Player.category` (FK) stays = the MAIN/home category.** Untouched, so all
  ~230 `category=` filters, 82 `scope_players` calls, 51 `player__category`
  joins, and 173 frontend `categoryId` usages keep working. This is the
  non-negotiable that keeps blast radius small.
- **Add a secondary membership** (additive; nothing reads it until a surface
  opts in). A small through-model carries the flag + provenance:
  ```
  PlayerCallUp(
    player      FK(Player, related_name="call_ups"),
    category    FK(Category),            # the category they're called up TO
    status      "call_up" | "promotion_track",   # "convocado" vs "listo para subir"
    since       date (optional),
    note        text (optional),
    created_by  FK(User),
    active      bool,
  )   # unique(player, category)
  ```
- **"main / secondary" is derived**, not a rewrite: main = `player.category`;
  secondary = active `PlayerCallUp` rows. UI shows both as chips.

Precedent: staff already have a multi-category M2M (`categories`); players do
not — this adds the player-side equivalent, but keeps the main FK as the anchor.

---

## 3. THE load-bearing rule — two distinct scopes

Combining decision #1 (main-only counts) and #2 (equal access) means the app
needs **two** notions of "in this category". Conflating them silently
double-counts call-ups. Keep them separate:

| Scope | Members | Backing query | Used by |
|---|---|---|---|
| **Access / visibility** | main **∪** active secondary | `scope_players` (extend in ONE place) | view, edit, add exams, notes, injuries, alerts, profile access |
| **Roster / aggregation** | **main only** | new `roster_of(category)` helper (secondary listed but flagged, not counted) | team averages, "disponibles X/Y", "no respondieron", dashboards, reports, Daily KPIs |

**Implementation task (the real work):** audit the **82 `scope_players` call
sites** and split them:
- Leave as `scope_players` (now main ∪ secondary) → the *access* sites.
- Switch to the main-only `roster_of()` → the *counting/aggregation* sites.

Getting this split right is the crux; a counting query that accidentally keeps
the widened `scope_players` will double-count every call-up.

---

## 4. Permissions

- Extend `scope_players(qs, membership)` so a `StaffMembership` scoped to
  category X returns players whose **main OR active-secondary** category is X.
  One change, propagates everywhere access is gated → equal access to call-ups.
- Admin/CRUD: who can flag a call-up? (Likely club managers / the category's
  lead.) Add/remove via Django admin first; a config-UI affordance later.
- `all_categories` staff (see `StaffMembership`) already see everyone — unchanged.

---

## 5. UI / flagging

- **Badge** wherever a call-up appears in a non-home category: e.g.
  `SUB-20 · convocado` / `proyección`. Never show a call-up unbadged in a
  category that isn't their home.
- **Profile header:** show main + secondary category chips.
- **Roster / Equipo & Daily:** list call-ups with the badge; exclude from the
  numeric counts (per §3). A subtle "incluye N convocados" caption is enough.

---

## 6. Import integration (phase 1 — unblocks penta)

- The bulk-ingest match index (`_build_player_index`) already merges players +
  aliases for the upload category. Extend it to also include the category's
  **active call-ups** → the 2 youth match a Primer-Equipo upload once flagged.
- The dry-run **preview labels each matched player with their category** and a
  "convocado" badge, so cross-category matches are explicit before commit.
- Result lands on the player's own record (home = SUB-20); shows flagged in
  first-team views; not counted in first-team stats.
- This removes the need for fuzzy club-wide matching entirely.

---

## 7. Edge cases to handle

- **Double-count guard:** every aggregation path must use `roster_of()` (main
  only). Enumerate: roster counts, team-report widgets, Daily KPIs
  (`disponibles`, `no_respondieron`, wellness expected/responded), dashboards.
- **Alerts / readiness:** a call-up's alerts should surface for the call-up
  category's staff (access scope) — but "N alertas activas" KPIs count main
  only. Same split.
- **Global category picker:** selecting Primer Equipo shows its call-ups
  (flagged) on *access* surfaces; counts stay main-only.
- **A player called up to multiple categories:** `unique(player, category)`
  allows several rows; fine. Aggregation still main-only everywhere.
- **Removing a call-up:** set `active=False` (keep history) → player drops out
  of that category's access + views immediately; their data stays on their
  record.

---

## 8. Phased rollout

- **Phase 0 — foundation.** `PlayerCallUp` model + migration; admin CRUD; extend
  `scope_players`; add `roster_of()`; **audit the 82 call sites** and switch the
  counting ones. Ship behind no UI (empty table = zero behavior change).
- **Phase 1 — import.** Include call-ups in bulk-ingest match + preview/badge.
  Unblocks the penta upload.
- **Phase 2 — visibility.** Equipo roster + Daily show call-ups flagged (counts
  still main-only).
- **Phase 3 — analytics.** Dashboards/reports: main-only counts, with an
  optional "incluir convocados" toggle where it makes sense.

---

## 9. Migration & backout

- Fully additive: new table empty by default → **zero behavior change** until a
  call-up is created. Backout = delete the call-ups (or drop the table) and
  revert the `scope_players` / `roster_of` split.
- No change to `Player.category`, so existing data and every category-scoped
  query are unaffected on day one.

---

## 9b. Team reports — inclusion + toggle (built 2026-07-25, LOCAL only)

Decision (reversing §8's cautious default): call-ups **appear by default** in
team reports, flagged, with a per-report control to exclude them.

- **Backend** (`dashboards/team_aggregation.py`): a module `ContextVar`
  `_INCLUDE_SECONDARY` (default `True`) is set/reset around the dispatch in
  `resolve_team_widget(..., include_secondary=True)`. The single choke point
  `_roster_query` now calls `players_in_category(category, include_call_ups=…)`
  instead of a home-only `category_id=` filter — so all 16 widgets pick up the
  toggle without per-resolver edits. The dispatch was extracted into
  `_dispatch_team_widget`. Every widget payload also gets
  `call_up_player_ids` (roster players whose home category differs; empty when
  excluded) for flagging.
- **API**: `GET /reports/{slug}` gained `include_secondary: bool = True`.
  Match-report + assistant + docx paths inherit the default (include). Word
  export is deprecated so it wasn't given a toggle; Excel is client-side and
  reflects the fetched data automatically.
- **Frontend**: `ReportFiltersValue.includeSecondary` (default true) + an
  "Incluir convocados" checkbox in `ReportFilters`; `page.tsx` sends
  `include_secondary=false` only when unchecked. A shared `CallUpMark` badge
  (indigo "conv." pill, mirrors the roster badge) is rendered in the
  **leaderboard (list mode)** and **roster-matrix** widgets. Other widget types
  include the players in their aggregates but don't individually badge them yet
  (follow-up: vertical-bars labels, multi-field, active_records/activity_log).
- **Verified local**: PE reports = 13 badge-capable widgets; roster 33 w/
  secondaries vs 31 without; Franco Fernández + José Alburquenque flagged.

## 10. Open questions

- **Counting policy confirm:** decisions say access-equal / count-main-only. If
  the club ever wants a call-up counted in the call-up category's stats too
  (fully-equal membership), that's a per-report opt-in (§8 phase 3 toggle) — not
  the default.
- Who is allowed to create/remove call-ups (role)?
- Should a call-up expire automatically (e.g. `since` + a window), or stay until
  cleared?
