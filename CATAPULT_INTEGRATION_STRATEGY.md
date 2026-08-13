# Catapult GPS Integration — Strategy

Status: **design** (not yet implemented). Captured 2026-08-12 after live
exploration of the Catapult OpenField API with the U. de Chile test token
(`TEST_UCHILE_CATAPULT_API_KEY`).

Goal: pull GPS session data (match + training) **directly from the vendor**
into the existing `gps_partido` / `gps_sesion` templates, as a **configurable
automation** — per category, Django-admin-editable, no code change to onboard
a new team. First vendor: **Catapult** (OpenField Cloud API v6).

This mirrors the established vendor-integration pattern already in the repo
(**VALD Hub**, **API-Football**): `integrations/<vendor>/` client + a per-scope
config model + a per-athlete link model + a `services/<vendor>_sync.py` +
a management command + a Celery-beat task + Django admin.

---

## 1. Confirmed facts from the live API

- **Base URL**: `https://backend-us.openfield.catapultsports.com/api/v6/`
  (US region — read from the JWT issuer claim). Store the region/base per row.
- **Auth**: `Authorization: Bearer <JWT>`. The test token is long-lived
  (expires ~2126) and carries scopes: `connect`, `sensor-read-only`,
  `athletes-update`, `tags-update`, `activities-update`, `parameters-update`.
- **`GET /activities`** — one row per session. Fields we use:
  `id`, `name`, `start_time` (epoch), `end_time`, `period_count`, `periods`,
  `athlete_count`, `game_id` (**always set — NOT a match/training signal**),
  `tag_list` (typed tags — dicts), `tags` (plain strings), `venue`.
  Names follow the club convention: `"Sesión DD-MM-YY"` (training),
  `"F## vs Opponent"` (match) — the same strings that appear in the manual
  upload files.
- **`GET /activities/{id}/athletes`** — the session roster, each with
  `id`, `first_name`, `last_name`, `date_of_birth`, `jersey`, `position_name`.
  (Only athlete config maxima here — **not** the session metric values.)
- **`GET /athletes`** — full athlete list with `current_team_id`,
  `date_of_birth`, `is_deleted`, `is_demo`, `is_synced`.
- **`GET /teams`** — 5 teams (see §3).
- **`GET /parameters`** — 1,857 metric definitions (`slug`, `name`,
  `unit_type`). The GPS-relevant ones use the **same display names as the
  club's export file** (e.g. `"Acceleration B2 Efforts (Gen 2)"`,
  `"Deceleration B1-3 Total Efforts"`), so the metric mapping is already known
  (see §6).
- **`POST /stats`** — where the real per-athlete metric values live. Endpoint
  exists (returns 422 on a wrong body). Exact request body + performance to be
  finalized in Phase 1 (it is slow; expect to page/scope by activity).

---

## 2. Match vs training classification

No single Catapult tag is reliable — the club has mixed schemes over time:

- **Activity** tag: `Entrenamiento` / `Pretemporada` / `CDA` (training-ish) vs
  `Partido` / `Partido Amistoso` / `Campeonato Nacional` / `Copa Chile` (match).
- **DayCode** tag: `Game` / `MD` / `Day N` **all coexist** (`Game -1` and
  `MD-1` both appear).
- **Name**: `" vs "` → match (185 of 2012 activities); `"Sesión…"` → training.

**Decision — SLAB's fixture calendar is the authoritative signal.** For each
activity's date, if there is a match `Event` that day for the category →
`gps_partido`, else `gps_sesion`. SLAB already owns fixtures (from the
API-Football sync), so this sidesteps the tag mess.

Make it a config knob `classify_strategy`:
- `fixture` (default) — match iff a fixture Event exists that day.
- `tag` — match iff Activity tag ∈ {Partido, Amistoso, competition names} or
  DayCode ∈ {Game, MD}.
- `name` — match iff name contains `" vs "`.
- `hybrid` — fixture first, fall back to tag/name when no fixture is defined.

---

## 3. Team → category mapping

| Catapult team | id | athletes | mapping |
|---|---|--:|---|
| **Plantel 2019** | `8db37797-534b-4be7-b851-9953f364185c` | 60 | ✅ **Primer Equipo** (active squad) |
| TRANSFERIDOS | `a21aa97f-2c03-4b57-89f8-eddaa4da8f03` | 87 | ex-players / archive |
| Selectivo | `8492afdb-8f6f-4018-922c-4354e8293b9f` | 6 | small group |
| Club Universidad de Chile | `75054b55-9900-11e3-b9b6-22000af8166b` | 15 | basketball — ignore |
| Archive | `7f37a5ba-5aea-4167-9d78-4859ed41d5ce` | 0 | — |

The most recent training (24 athletes) and match (15) map 100% to **Plantel
2019** — that's the active first team. Its 60-athlete count is historical
accumulation since 2019 (transfers in/out); only the ~24 who actually wear
devices show up on recent activities. The integration should therefore key on
each **activity's roster**, not the team's full athlete list.

---

## 4. Architecture (mirror VALD)

1. `integrations/catapult/client.py` — auth + typed `GET /activities`,
   `/activities/{id}/athletes`, `/teams`, `/parameters`, `POST /stats`.
2. **`CatapultIntegration`** — per-category config model (§5).
3. **`CatapultAthleteLink`** — `athlete_id → Player`, match method
   (external-id → name+DOB → name); **manual links never overwritten**.
4. `services/catapult_sync.py` — the sync flow (§7).
5. `management/commands/sync_catapult.py` — `--dry-run` (default) / `--commit`.
6. Celery-beat task `sync_catapult` — **hourly**.
7. Django admin for the config + link tables.

---

## 5. `CatapultIntegration` config model

Per **category** (one row per squad/tenant), Django-admin-editable:

| field | purpose |
|---|---|
| `category` (FK) | which SLAB squad this feeds |
| `enabled` | automation on/off (skipped by the hourly task when off) |
| `region` / `base_url` | Catapult cloud (default US) |
| **`api_token`** | the Bearer JWT — **per row**, since different teams/tenants use different tokens |
| `catapult_team_id` | the Catapult team = this category (e.g. Plantel 2019) |
| `classify_strategy` | `fixture` (default) / `tag` / `name` / `hybrid` |
| `sync_matches` / `sync_training` | ingest match and/or training |
| `min_training_minutes` | skip trainings shorter than this (data cleaning) |
| `partido_template_slug` / `sesion_template_slug` | default `gps_partido` / `gps_sesion` |
| `lookback_days` | how far back each run scans |
| `last_synced_at` | incremental cursor |

---

## 6. Metric mapping (anchored to the club's export)

The Catapult parameter **names** equal the file-export headers, so the mapping
is the one already used by the file importer. Target = `gps_sesion` /
`gps_partido` field keys:

| gps field key | Catapult parameter (name) |
|---|---|
| `tot_dur` | Total Duration |
| `tot_dist` | Total Distance |
| `mpm` | Meterage Per Minute |
| `hsr` | Distancia MAI >19,8 km/h (HSR) |
| `sprint_dist` | Sprint >25 km/h distance |
| `sprints` | N.º Sprints >25 km/h |
| `max_vel` | Maximum Velocity |
| `acc` | Acceleration B2-3 Total Efforts (Gen 2) |
| `dec` | Deceleration B2-3 Total Efforts (Gen 2) |
| `dist_acc` | Dist Acc > 3 m/s |
| `dist_dec` | Dist Dec > -3 m/s |
| `hmld` | Alta Potencia Metabólica - Distancia (HMLD) |

Exact `slug`s confirmed against `/parameters` in Phase 1. Calculated template
fields recompute server-side via the formula engine on save. Note the
`Acc/Dec B2-3` band-threshold caveat carried over from the file reshape.

---

## 7. Sync flow (per enabled category)

1. Resolve the config; skip if `enabled=false`.
2. `GET /activities` for `catapult_team_id` within `lookback_days`.
3. **Filter (data cleaning):** only GPS-tagged activities; drop 0-athlete
   activities; drop trainings under `min_training_minutes`.
4. Per activity: date = `start_time`; **classify** per `classify_strategy`.
5. `GET /activities/{id}/athletes` → resolve each to a `Player` via
   `CatapultAthleteLink` (name+DOB). Report unmatched, never invent.
6. `POST /stats` for the activity → map parameters → `gps_*` field keys.
7. **Idempotency / gap-fill:**
   - match key = `(player, day)`; training key = `(player, day, activity_id)`
     — so multiple sessions the same day stay **separate**, not merged.
   - if a result already exists for that key (incl. hand-uploaded files),
     **skip** — the sync only *fills missing data*, never overwrites.
   - store the Catapult `activity_id` on each created result for precise,
     repeatable idempotency.
8. `ExamResult.create`; recompute state/alerts like the manual importers.

---

## 8. Data cleaning knobs

- `min_training_minutes` — skip short activations (config).
- GPS-tag filter — only ingest activities carrying the `GPS` device tag.
- Skip `is_demo` / `is_deleted` athletes and 0-athlete activities.
- Separate same-day sessions (via the training idempotency key above).

---

## 9. Phased plan

- **Phase 1 — read-only.** Config + link models + client +
  `sync_catapult --dry-run`. Prove: auth, athlete match-rate (name+DOB →
  roster), classification, the `/stats` body, and the cleaning filters — no
  writes.
- **Phase 2 — commit path.** Idempotency/gap-fill + `activity_id`, then the
  hourly beat. Matches first (`gps_partido`), then training.
- **Phase 3 — self-service UI.** A club-facing *Integraciones* page (toggle,
  token, team↔category, strategy, min-minutes, last-run status).

---

## 10. Open items

- Finalize the `POST /stats` request body + paging/perf.
- Confirm each Catapult `slug` per §6 against `/parameters`.
- **Go-live creds on Railway** — like VALD, the automation is gated on the
  real (non-test) token being set on prod.
- Roster gap: run the roster reconciliation in §11 before first commit.

---

## 11. Pre-onboarding roster reconciliation (run for EVERY vendor / team)

**Required pre-flight step whenever adding a GPS vendor integration or a new
team.** A vendor's athlete list accumulates history — Catapult's "Plantel
2019" holds **60** athletes (everyone since 2019), but only the ~27 who
actually wear devices lately are the live squad. Reconcile the *currently
tracked* athletes against the SLAB roster **before** the first sync, so the
automation links cleanly and never invents players.

### Procedure (repeatable)
1. **Identify the active team.** Cross-reference the rosters of the most
   recent match + training against each athlete's `current_team_id`; the
   dominant team is the live squad (for U. de Chile: `Plantel 2019`).
2. **Compute the tracked set.** Union of athlete rosters across the last
   ~21 days of activities — NOT the team's full athlete list.
3. **Match against PROD** (the source of truth — local drifts): by DOB
   (skip placeholder DOBs such as `1970-01-01`), then accent-insensitive
   name, then `PlayerAlias`.
4. **Triage the two diffs:**
   - *Vendor-active but not in SLAB* → real new player (add to SLAB) /
     name variant (add a `PlayerAlias`) / placeholder-DOB test entry (ignore).
   - *SLAB but not vendor-tracked* → usually youth/rotation (fine — not
     everyone wears a device every session).

### Worked example — U. de Chile, 2026-08 (against PROD)
- 22 activities in 21 days → **27 distinct Catapult athletes**; **27/27
  matched** to the 33-player Primer Equipo roster.
- The 60 in "Plantel 2019" = historical accumulation; ~27 are live.
- Three athletes flagged only against **local** (stale): `Diego Cofre` and
  `Tobías Reinhart` exist by name in prod; `Juan Martín Lucero` ↔ SLAB
  `Juan Lucero` is reconciled via a player+alias. All resolved in prod.
- **Caveat:** several Catapult athletes carry a placeholder DOB
  (`1970-01-01`) + initials jersey — so **name/alias matching, not DOB, is
  the reliable key** for them. This is exactly why the sync matches on
  name+DOB + a manual link table and reports unmatched instead of inventing
  players (§4).

> This section is vendor-agnostic — repeat it for any GPS vendor or new team
> before enabling the automation.
