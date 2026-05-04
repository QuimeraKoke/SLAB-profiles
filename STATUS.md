# SLAB — Project Status & Handoff

> **Snapshot:** the platform now ships the team-reports system (six chart
> types, configurable per `(department, category)`), real-data
> ProfileSummary, full event CRUD on player profiles, bulk per-roster
> match performance entry, the Medicación template with WADA alerts, a
> tablet/mobile-responsive layout with a global category picker in the
> navbar, full player CRUD under `/configuraciones/jugadores`, and
> edit-in-place + delete on every result table. 145 backend tests pass;
> frontend lint is at zero problems.
>
> **Read first:** [`PROJECT.md`](./PROJECT.md) (vision, philosophy, persona model,
> architecture rationale). This doc is the *implementation* status — what exists
> in the repo today, what's still TODO, and how to keep building.

---

## 1. Quick start on a new machine

### Prerequisites
- Docker + Docker Compose
- Git
- (Optional) Node 20 / Python 3.12 for running pieces outside Docker

### First run

```bash
git clone <repo-url> slab-profiles
cd slab-profiles
cp .env.example .env
docker compose up --build
```

Wait for the `backend` container to log "Starting development server at
http://0.0.0.0:8000/". The Dockerfile's `CMD` runs `migrate` automatically,
but apps need their migration files generated the first time:

```bash
docker compose exec backend python manage.py makemigrations core exams
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

**Use a real email when creating the superuser** — the frontend signs in by
email, not username.

### Services

| Service  | URL                            | Notes                              |
| -------- | ------------------------------ | ---------------------------------- |
| Frontend | http://localhost:3000          | Next.js 16 dev server              |
| API      | http://localhost:8000/api      | OpenAPI docs at `/api/docs`        |
| Admin    | http://localhost:8000/admin    | Configuration UI (Django Admin)    |
| Postgres | localhost:5432                 | DB: `slab`, user: `slab`           |
| Redis    | localhost:6379                 | Celery broker + result backend     |
| MinIO    | localhost:9000 (S3 API), 9001 (console) | Local S3-compatible storage for `Attachment` files. Console login uses the AWS_* env vars from `.env`. |

### Minimum data to see the app

After superuser, in **Django Admin**:

1. **Core → Clubs → Add** → e.g. `Demo FC`.
2. **Core → Departments → Add** → e.g. `Médico`, `Físico`, `Nutricional`,
   `Psicosocial`. Slug auto-fills from name.
3. **Core → Categories → Add** → e.g. `First Team`, `U-21`, `U-8`. Tick the
   relevant departments per category. Filter for departments shown is scoped
   to the category's club only after the first save (set club, save, then pick
   departments).
4. **Core → Positions → Add** → per-club positions: e.g. `MC – Volante interior`.
5. **Core → Players → Add** → assign category + position + nationality.
6. **(Optional) Core → Staff memberships → Add** for non-superuser users (see
   §3.5).

Then bootstrap the demo template + fake data:

```bash
# 5-component anthropometry template:
docker compose exec backend python manage.py seed_pentacompartimental \
    --create-if-missing --department-slug nutricional \
    --all-applicable-categories

# Daily-notes templates per department. (`seed_metas` was retired —
# structured goals are now first-class via the Goal model; see §3.15.)
docker compose exec backend python manage.py seed_daily_notes \
    --create-if-missing --all-applicable-categories

# Fake historical exam results so dashboards have data:
docker compose exec backend python manage.py seed_fake_exams --reset

# Default Nutricional dashboard layout (mirrors the designer's mockup):
docker compose exec backend python manage.py seed_nutricional_layout \
    --all-applicable-categories
```

Log in at http://localhost:3000/login. Open any player → switch tabs.

---

## 2. Repository layout

```
slab-profiles/
├── PROJECT.md              # Product vision + architecture spec (the "why")
├── STATUS.md               # This file
├── DASHBOARDS.md           # Operator + developer guide for layouts/widgets
├── README.md               # Operator-facing quick reference
├── AGENTS.md               # Reminder: Next 16 has breaking changes
├── docker-compose.yml      # postgres + redis + backend + frontend
├── .env.example
│
├── backend/                # Django + Django Ninja
│   ├── manage.py
│   ├── requirements.txt   # + openpyxl (bulk ingest XLSX parsing)
│   ├── Dockerfile
│   ├── config/             # settings, urls, wsgi/asgi
│   ├── core/               # Club, Department, Category, Position, Player,
│   │                       # PlayerAlias, StaffMembership + admin + seeds
│   │   └── management/commands/seed_uchile_2026.py
│   ├── exams/              # ExamTemplate, TemplateField (authoring rows),
│   │                       # ExamResult (with event FK), Episode, calculations.py,
│   │                       # bulk_ingest.py, template_builders.py, signals.py
│   │                       # (writeback, episode lifecycle, WADA medication alerts),
│   │                       # management/commands/seed_*.py + data/medicamentos.csv
│   ├── dashboards/         # PLAYER: DepartmentLayout/Section/Widget/WidgetDataSource
│   │                       # TEAM:   TeamReportLayout/Section/Widget/WidgetDataSource
│   │                       # aggregation.py (per-player) + team_aggregation.py (team)
│   ├── events/             # Event model + admin (calendar + match metadata)
│   ├── goals/              # Goal + Alert + AlertRule models, evaluator, Celery tasks
│   │                       # (send_alert_email + evaluate_goal_warnings),
│   │                       # AlertSource enum: GOAL/GOAL_WARNING/THRESHOLD/MEDICATION
│   ├── attachments/        # Generic Attachment model (polymorphic source FK)
│   │                       # backed by S3 / MinIO via django-storages
│   └── api/                # Ninja routers, schemas, JWT auth, scoping helpers
│
└── frontend/               # Next.js 16 App Router
    ├── package.json
    ├── Dockerfile
    └── src/
        ├── app/
        │   ├── layout.tsx
        │   ├── login/
        │   └── (dashboard)/
        │       ├── layout.tsx                   # Wraps children in CategoryProvider; owns sidebar open/close state for tablet drawer
        │       ├── equipo/page.tsx              # Roster / pitch view (filters by navbar category)
        │       ├── perfil/[id]/page.tsx         # Dynamic player profile
        │       ├── perfil/[id]/registrar/[templateId]/  # Mode-dispatching form (+ ResultsHistoryPanel below)
        │       ├── perfil/[id]/eventos/nuevo/   # Per-player event creator
        │       ├── partidos/page.tsx            # Matches manager (calendar + table)
        │       ├── partidos/nuevo/              # Create match form
        │       ├── partidos/[id]/editar/        # Edit match form + bulk per-roster performance entry
        │       ├── reportes/[deptSlug]/         # Team reports — 6 chart types, position filter
        │       └── configuraciones/jugadores/   # Player CRUD (admin)
        ├── components/
        │   ├── equipo/
        │   ├── forms/
        │   │   ├── DynamicUploader.tsx          # single-mode form, inline file fields, edit mode (PATCH)
        │   │   ├── DeferredFilePicker.tsx       # client-side queueing for inline file uploads
        │   │   ├── BulkIngestForm.tsx           # file picker + preview/confirm
        │   │   ├── BulkIngestPlaceholder.tsx    # fallback when no column_mapping yet
        │   │   └── TeamTableForm.tsx            # roster-style entry; supports event_id + participantIds
        │   ├── partidos/
        │   │   ├── MatchForm.tsx                # shared create + edit form
        │   │   └── MatchesCalendar.tsx          # month-grid view
        │   ├── perfil/
        │   │   ├── ProfileHeader/
        │   │   ├── ProfileTabs/                 # generic, takes tabs[]
        │   │   ├── ProfileSummary/              # Resumen tab — live aggregator
        │   │   ├── ProfileTimeline/             # Línea de tiempo (sorts by result_data.fecha)
        │   │   ├── ProfileEvents/               # Eventos tab — edit/delete per card
        │   │   ├── ProfileEpisodes/             # Lesiones tab — filtered to template_slug=lesiones
        │   │   ├── ProfileGoals/                # Objetivos tab — Goal CRUD + Alert list
        │   │   ├── InjuryPanel/                 # Embedded in Lesiones registrar — open episodes only
        │   │   ├── ResultsHistoryPanel/         # Collapsible history table on the registrar page
        │   │   ├── MatchHistoryTable/           # Táctico-tab match performance view
        │   │   ├── ProfileDepartment/           # fetches layout + falls back to DepartmentCard grid
        │   │   │   └── DashboardEntryPanel/     # template-pick (links to registrar)
        │   │   └── DepartmentCard/              # Per-template card with chart + history table + edit/delete
        │   ├── dashboards/                      # PER-PLAYER configurable layout renderer
        │   │   ├── DepartmentDashboard.tsx
        │   │   ├── SectionGroup.tsx
        │   │   └── widgets/                     # chart_type → component
        │   │       ├── index.tsx                # renderWidget()
        │   │       ├── ComparisonTable.tsx, LineWithSelector.tsx, MultiLine.tsx,
        │   │       ├── DonutPerResult.tsx, GroupedBar.tsx, BodyMapHeatmap.tsx,
        │   │       └── Unsupported.tsx
        │   ├── reports/                         # TEAM reports renderer (parallel system)
        │   │   ├── TeamReportDashboard.tsx
        │   │   ├── TeamReportSection.tsx
        │   │   └── widgets/                     # one component per team chart_type
        │   │       ├── index.tsx
        │   │       ├── TeamHorizontalComparison.tsx, TeamRosterMatrix.tsx,
        │   │       ├── TeamStatusCounts.tsx, TeamTrendLine.tsx,
        │   │       ├── TeamDistribution.tsx, TeamActiveRecords.tsx,
        │   │       └── Unsupported.tsx
        │   ├── ui/
        │   │   ├── Modal/                       # portal + backdrop, shared modal
        │   │   └── AttachmentList/              # Attachment CRUD on existing results
        │   │       └── utils.ts                 # formatSize / iconFor / ACCEPTED_FILE_TYPES
        │   └── visualizations/                  # legacy registry (per-field chart_type, mostly unused now)
        │       ├── Registry.tsx, StatCard.tsx, LineChart.tsx,
        │       ├── BodyMap.tsx (placeholder)
        │       └── types.ts
        ├── context/
        │   ├── AuthContext.tsx                  # JWT + /auth/me hydration
        │   └── CategoryContext.tsx              # Global selected-category + localStorage persistence
        └── lib/
            ├── api.ts                           # fetch wrapper (FormData-aware)
            └── types.ts                         # mirrors backend schemas
```

---

## 3. What's been built

### 3.1 Data model (`backend/core/models.py` + `backend/exams/models.py` + `backend/events/models.py`)

Strict-relational core, JSONB-driven exams, events linked via FK.

| Model              | Key fields                                                     | Notes                                                                                              |
| ------------------ | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `Club`             | `id (UUID)`, `name`                                            |                                                                                                    |
| `Department`       | `id`, `club FK`, `name`, `slug`                                | Per-club. Slug auto-derived from name. `(club, name)` and `(club, slug)` unique-together.          |
| `Category`         | `id`, `club FK`, `name`, `departments M2M`                     | Categories opt in to which departments they run.                                                   |
| `Position`         | `id`, `club FK`, `name`, `abbreviation`, `role`, `sort_order`  | Per-club soccer positions.                                                                         |
| `Player`           | `id`, `category FK`, `position FK`, `first_name`, `last_name`, `date_of_birth`, `sex` (M/F/blank), `nationality`, `is_active`, `status` (available/injured/recovery/reintegration), `current_weight_kg`, `current_height_cm`, derived `age` | `position` is nullable. Admin filters position picker to the player's club. `current_weight_kg` / `current_height_cm` are caches updated by exam-template fields whose `writes_to_player_field` knob is set. `status` is a cache derived from open `Episode` rows on episodic templates (worst stage wins) — see §3.18. `age` is computed from `date_of_birth`. All five are referenceable in formulas as `[player.sex]`, `[player.current_weight_kg]`, `[player.current_height_cm]`, `[player.age]` (status is intentionally NOT exposed to formulas to avoid coupling clinical decisions to availability). |
| `Contract`         | `id`, `player FK`, `contract_type` (permanent/loan_in/loan_out/youth), `start_date`, `end_date`, `signing_date`, `ownership_percentage` (0–1), `total_gross_amount`, `salary_currency`, plus free-text columns for `fixed_bonus` / `variable_bonus` / `salary_increase` / `purchase_option` / `release_clause` / `renewal_option`, `agent_name`, `notes` | Multiple per player (history-aware). "Vigente" = the row covering today, surfaced as `PlayerDetail.current_contract`. The free-text columns mirror the team's existing Airtable convention ("NO" or a description). Salary fields are redacted server-side for non-staff users. |
| `PlayerAlias`      | `id`, `player FK`, `kind`, `source`, `value`                   | Alternate identifiers for matching: `nickname` / `squad_number` / `external_id` (with `source`: catapult, wimu, manual). External-IDs uniqueness validated per club via `clean()`. Inline on PlayerAdmin. |
| `StaffMembership`  | `id`, `user OneToOne`, `club FK`, `all_categories`, `categories M2M`, `all_departments`, `departments M2M` | One club per user. "All" flag bypasses the M2M list.                                  |
| `ExamTemplate`     | `id`, `name`, `slug`, `department FK`, `applicable_categories M2M`, `config_schema JSONB`, `input_config JSONB`, `version`, `is_locked`, `link_to_match` | Locks after first result. `slug` is the stable identifier formulas use to reference this template's results from another template (`[<slug>.<field_key>]`); auto-derived from name, unique per club, reserved name 'player'. `input_config` controls input modes (single / bulk_ingest / etc.) — see §3.10. `link_to_match` (admin checkbox) is mirrored into `input_config.allow_event_link` on save and gates the match selector across single + bulk + team forms. **Lineage versioning is still TODO** (§9b discussion); slug currently belongs to a single template row. |
| `TemplateField`    | `id`, `template FK`, `sort_order`, `key`, `label`, `type` (number/text/categorical/calculated/boolean/date/file), `unit`, `group`, `options JSONB`, `option_labels JSONB`, `option_regions JSONB`, `formula`, `chart_type`, `required`, `multiline`, `rows`, `placeholder`, `writes_to_player_field` | Authoring abstraction over `config_schema['fields']`. Saving in admin regenerates the JSON. See §3.13. `option_labels` localizes categorical-option display (e.g. `injured → Lesionado`). `option_regions` maps options to body regions for the `body_map_heatmap` widget (e.g. `Muslo der. → right_thigh`). `writes_to_player_field` (choices: '', current_weight_kg, current_height_cm, sex) — when set, post-save signal copies the value back to the player profile, last-write-wins by `recorded_at`. Field keys can't contain `.` or be `'player'` (reserved for namespace syntax). |
| `ExamResult`       | `id`, `player FK`, `template FK`, `recorded_at`, `result_data JSONB`, `inputs_snapshot JSONB`, `event FK (nullable)`, `episode FK (nullable, PROTECT)` | GIN-indexed on `result_data`. `event` FK links results to a calendar event (e.g. GPS upload from a match). `episode` FK links results to a clinical Episode for episodic templates (e.g. injuries) — populated by the episode-aware result-create endpoint. Calculated outputs computed server-side. `inputs_snapshot` is the audit-of-record: every external value (`player.X`, `<slug>.Y`) the formula engine read at calculation time, frozen so historical recomputes never silently change. |
| `Episode`          | `id`, `player FK`, `template FK`, `status` (open/closed), `stage`, `title`, `started_at`, `ended_at`, `metadata JSONB`, `created_by` | A clinical episode (injury, surgery, concussion protocol, …) tying a sequence of ExamResults together. Used by templates with `is_episodic=True`. `stage` / `title` / `ended_at` are auto-derived from the latest linked result via post-save signal. Worst stage among a player's open episodes drives `Player.status`. See §3.18. |
| `Event`            | `id`, `club FK`, `department FK`, `event_type`, `title`, `description`, `starts_at`, `ends_at`, `location`, `scope` (individual/category/custom), `category FK (nullable)`, `participants M2M Player`, `metadata JSONB`, `created_by FK User` | Calendar events: matches, training, medical_checkup, physical_test, team_speech, nutrition, other. Match-specific data (opponent, score, competition, is_home, duration_min) lives in `metadata`. |
| `DepartmentLayout` | `id`, `department FK`, `category FK`, `name`, `is_active`            | One layout per `(department, category)`. `clean()` enforces same club + category opt-in. |
| `LayoutSection`    | `id`, `layout FK`, `title`, `is_collapsible`, `default_collapsed`, `sort_order` | Visual grouping inside a layout.                                                          |
| `Widget`           | `id`, `section FK`, `chart_type`, `title`, `description`, `column_span`, `chart_height` (nullable px), `display_config JSONB`, `sort_order` | One chart card. `chart_type` is a TextChoices registry — see §3.9. `chart_height` is a per-widget override; null falls back to per-chart-type defaults (line 240, multi-line 280, grouped bar 220, donut 180). |
| `WidgetDataSource` | `id`, `widget FK`, `template FK`, `field_keys text[]`, `aggregation`, `aggregation_param`, `label`, `color`, `sort_order` | Bound data feed. `clean()` validates field_keys against the template schema. |
| `Goal`             | `id`, `player FK`, `template FK`, `field_key`, `operator (>= <= == > <)`, `target_value`, `due_date`, `notes`, `status (active / met / missed / cancelled)`, `last_value`, `evaluated_at`, `created_by` | Per-player objective evaluated against the latest reading on `(template, field_key)`. Daily Celery tick transitions active → met/missed; post_save signal flips → met early when a qualifying reading lands. |
| `Alert`            | `id`, `player FK`, `source_type` (goal / threshold), `source_id`, `severity`, `status (active / dismissed / resolved)`, `message`, `fired_at`, `last_fired_at`, `trigger_count`, `dismissed_at`, `dismissed_by` | Generic notification raised by either the goal evaluator or the threshold evaluator (§3.17). One active row per `(source_type, source_id)`: re-firing refreshes `last_fired_at` + increments `trigger_count` instead of duplicating. After dismissal a new violation creates a fresh row (counter resets). |
| `AlertRule`        | `id`, `template FK`, `field_key`, `category FK (nullable)`, `kind` (bound / variation), `config JSONB`, `severity`, `message_template`, `is_active`, `created_by` | A configured rule that the threshold evaluator runs on every new ExamResult. `bound` config = `{upper, lower}` (either side optional); `variation` config = `{window: {kind, n or days}, threshold_pct?, threshold_units?, direction}` — at least one of pct/units required, both can coexist (logical OR). `category=null` applies to all categories using this template. Field reference is a string validated in `clean()` (matches `Goal.field_key` pattern — TemplateField rows are ephemeral). |
| `Attachment`       | `id`, `source_type` (contract / exam_field / exam_result / event), `source_id (UUID)`, `field_key`, `file`, `filename`, `mime_type`, `size_bytes`, `label`, `uploaded_by`, `uploaded_at` | Generic file attachment. Polymorphic pointer (`source_type` + `source_id`) links to whatever the file belongs to; `field_key` pins exam-field uploads to a specific field key. Files live in S3 (MinIO for dev) via `django-storages`. |

### 3.2 Configuration-driven exam templates

Each `ExamTemplate.config_schema` is a JSON document:

```json
{
  "fields": [
    { "key": "peso",  "label": "Peso",  "type": "number", "unit": "kg",
      "group": "Datos básicos", "required": true },
    { "key": "nota",  "label": "Nota",  "type": "text",   "multiline": true,
      "rows": 8 },
    { "key": "fecha", "label": "Fecha", "type": "date",   "required": true },
    { "key": "estado","label": "Estado","type": "categorical",
      "options": ["Activa", "Cumplida"] },
    { "key": "imc",   "label": "IMC",   "type": "calculated",
      "formula": "[peso] / (([talla] / 100) ** 2)",
      "chart_type": "line" }
  ]
}
```

**Field types** the engine + frontend understand: `number`, `text` (with
optional `multiline` + `rows`), `categorical` (needs `options[]`), `boolean`,
`date`, `calculated` (server-evaluated, never user-typed). Optional knobs:
`unit`, `group`, `placeholder`, `required`, `chart_type`, `formula`.

### 3.3 Formula engine — `backend/exams/calculations.py`

Safe AST evaluator. Replaces `[var]` syntax with bare identifiers, parses to a
Python AST, walks it allowing only a whitelist of node types. Supported:

- `+ - * / // % **`
- comparisons (`== != < <= > >=`) returning 0/1
- boolean `and / or / not`
- ternary: **`a if cond else b`** (Python; **C-style `cond ? a : b` is rejected**)
- functions (whitelisted): `abs`, `min`, `max`, `round`, `sqrt`, `log`, `log10`,
  `ln`, `exp`, `pow`, **`coalesce`**
- constants `pi`, `e`

`coalesce(a, b, …)` is **lazy-evaluated** — returns the first argument that
yields a real number, swallowing `FormulaError` from null/missing variables.
If every argument is missing/null, the call raises (and the field is stored
as `None`). Critical for segmented data: a substitute who only played P2 has
`coalesce([tot_dist_p1], 0) + coalesce([tot_dist_p2], 0)` = 0 + P2 instead of
the whole formula failing because P1 is absent.

Calculated fields are computed in declaration order, so a later formula can
reference an earlier calculated field's key (see `masa_muscular` referencing
the four other masses in Pentacompartimental).

#### Dot-notation namespaces (`player.X`, `<slug>.Y`)

Beyond bare identifiers (own-template fields), formulas can reference:

- **`[player.<attr>]`** — the player's profile attributes:
  `player.sex` (string, "M"/"F"/""), `player.current_weight_kg`,
  `player.current_height_cm`, `player.age` (derived from date_of_birth).
- **`[<template_slug>.<field_key>]`** — the **most recent** result on the
  same player for that template (in the same club). Returns the field
  value as numeric (or string for text fields). When no qualifying result
  exists or the field is null/missing, the formula raises `FormulaError`
  for that field and the calculated value is stored as `None`.

Example formulas:
```python
# IMC from cached profile values:
[player.current_weight_kg] / (([player.current_height_cm] / 100) ** 2)

# Sex-specific anthropometric coefficient (string equality):
0.567 * [pliegue_tricipital] if [player.sex] == "M" else 0.610 * [pliegue_tricipital]

# Cross-template ratio:
[ck.valor] / [player.current_weight_kg] * 100
```

**Rules / safety:**
- Single-level attribute access only (`a.b` ✓; `a.b.c` ✗).
- `player` is reserved — cannot be used as a template slug or field key.
- Field keys cannot contain `.` (validated in `TemplateField.clean()`).
- The AST walker accepts string `Constant` nodes (for sex equality) but
  arithmetic on strings still raises naturally — that's a "user wrote a
  weird formula" failure.

#### `inputs_snapshot` — audit-of-record at calculation time

`compute_result_data(template, raw_data, player=...)` returns
`(result_data, inputs_snapshot)`. The snapshot captures every external
value the formula engine **actually read** during evaluation, keyed as
`"player.sex"`, `"pentacompartimental.peso"`, etc. The
`POST /api/results`, `/results/team`, and `/results/bulk` endpoints all
persist it on the `ExamResult` row, so:

- Recomputing or re-rendering an old result never silently changes
  because the player's weight or a referenced template's latest reading
  changed downstream.
- The frontend can show "this calculation used `player.sex='M'`,
  `pentacompartimental.peso=78.5` at the time" if it ever wants a
  "show calculation details" affordance.

### 3.4 API (`backend/api/routers.py`)

All endpoints are JWT-authenticated by default (NinjaAPI mounted with
`auth=jwt_auth`). `/api/health` and `/api/auth/login` are explicitly `auth=None`.

| Method | Path                                             | Notes                                                                |
| ------ | ------------------------------------------------ | -------------------------------------------------------------------- |
| GET    | `/api/health`                                    | Public                                                               |
| POST   | `/api/auth/login`                                | Email + password → `{ access_token, expires_at, user, membership }`  |
| GET    | `/api/auth/me`                                   | `{ user, membership }`                                               |
| GET    | `/api/clubs/{id}/departments`                    | Scoped by membership                                                 |
| GET    | `/api/clubs/{id}/positions`                      | Scoped                                                               |
| GET    | `/api/categories?club_id=…`                      | List scoped categories (used by partidos `MatchForm`)                |
| GET    | `/api/categories/{id}`                           | Scoped; embeds allowed departments                                   |
| GET    | `/api/players?category_id=…`                     | Scoped                                                               |
| GET    | `/api/players/{id}`                              | Scoped; rich `PlayerDetailOut` (club + category + position + `current_contract`). `current_contract` is the row whose `start_date <= today <= end_date`, with salary fields redacted for non-staff viewers. |
| GET    | `/api/players/{id}/contracts`                    | Scoped; full contract history newest-first. Salary fields redacted for non-staff. |
| POST   | `/api/contracts`                                 | Create. **is_staff/superuser only.** |
| PATCH  | `/api/contracts/{id}`                            | Partial update. **is_staff/superuser only.** |
| DELETE | `/api/contracts/{id}`                            | Delete. **is_staff/superuser only.** |
| GET    | `/api/players/{id}/episodes?status=open\|closed` | Scoped; newest first. Each entry embeds latest result_data + result_count. |
| GET    | `/api/episodes/{id}`                             | Scoped detail. |
| PATCH  | `/api/episodes/{id}`                             | Force-close an abandoned episode (`status: "closed"` only). Cascades to Player.status recompute. |
| POST   | `/api/attachments`                               | `multipart/form-data`. Required: `file`, `source_type`, `source_id`. Optional: `field_key` (req'd for `source_type=exam_field`), `label`. Validates mime allowlist + 25 MB cap. Re-uses the source row's scoping. |
| GET    | `/api/attachments?source_type&source_id&field_key` | Scoped list. |
| GET    | `/api/attachments/{id}/download`                 | Scope-checks the source, returns 302 to a short-lived signed S3 URL (5 min). Internal hostname is rewritten to `AWS_S3_PUBLIC_ENDPOINT_URL` for browser access. |
| DELETE | `/api/attachments/{id}`                          | Removes the row + the underlying S3 object. Same scoping as upload. |
| GET    | `/api/players/{id}/templates?department=…`       | Scoped to player's category + user's departments                     |
| GET    | `/api/players/{id}/results?department=…`         | Filter by department slug. Each result embeds optional `event` brief (id, type, title, starts_at, metadata). |
| GET    | `/api/players/{id}/views?department=…`           | Returns `{layout: …}` — server-aggregated dashboard payload, or `{layout: null}` for fallback |
| GET    | `/api/templates/{id}`                            | Scoped; includes `input_config`                                      |
| POST   | `/api/results`                                   | Runs formula engine on submit. Optional `event_id` links the result and overrides `recorded_at` to the event's start. |
| POST   | `/api/results/bulk`                              | `multipart/form-data`. Parse → match (PlayerAlias + name) → transform (segment-aware) → preview/commit. See §3.11. |
| POST   | `/api/results/team`                              | Roster-style batch: `{template_id, category_id, recorded_at, shared_data, rows: [{player_id, result_data}]}`. Merges shared into each row, runs formula engine, skips blank rows, transactional. See §3.10 `team_table`. |
| GET    | `/api/events?event_type=…&player_id=…&category_id=…&department=…&starts_after=…&starts_before=…` | List events visible to user, filterable. Annotated with `result_count` (linked ExamResult rows). |
| GET    | `/api/events/{id}`                               | Detail; full participants list                                       |
| POST   | `/api/events`                                    | Create. Resolves participants through `scope_players()`.             |
| PATCH  | `/api/events/{id}`                               | Full update with participant resync.                                 |
| DELETE | `/api/events/{id}`                               | Delete (linked ExamResults are preserved with `event=null`).         |
| GET    | `/api/players/{id}/goals`                        | Scoped; active first, then most-recent. Embeds `field_label` + `field_unit` resolved from the template schema. |
| POST   | `/api/goals`                                     | Create. `field_key` must be a numeric/calculated field on the template. Template must apply to player's category. |
| PATCH  | `/api/goals/{id}`                                | Partial update. `status` may only become `cancelled` via API (met/missed are evaluator-driven). |
| DELETE | `/api/goals/{id}`                                | Hard delete; also dismisses any active Alerts pointing at the goal. |
| GET    | `/api/players/{id}/alerts?status=…`              | Scoped; newest first. Filter by `active`/`dismissed`/`resolved`.    |
| PATCH  | `/api/alerts/{id}`                               | `status='dismissed' \| 'resolved'`. Stamps `dismissed_at` + `dismissed_by`. |

Interactive docs at http://localhost:8000/api/docs.

### 3.5 Auth & scoping (`backend/api/auth.py` + `backend/api/scoping.py`)

- **JWT** via PyJWT (HS256, signed with `JWT_SECRET`, default 12-hour TTL).
  Token in `Authorization: Bearer …`.
- **Login by email** — Django's `authenticate()` uses username, so the route
  resolves user-by-email first then calls `authenticate()`.
- **`StaffMembership` is the access-control object.** A user's view of every
  list endpoint goes through `scope_*` helpers:
  - **No membership** = platform admin = sees everything (typical for the
    initial superuser).
  - **Membership exists** = filtered to that one club, plus the chosen
    categories (or all if `all_categories=True`) and departments
    (`all_departments=True` likewise).
- Mutations (POST `/results`, POST `/events`, POST `/results/bulk`) check that
  the target template's department / event / category is one the user can
  access — silent 404 otherwise (no information leakage).
- `scope_events()` filters to user's club + accessible departments; same shape
  as `scope_templates`.
- `StaffMembershipAdmin.save_model` flips `is_staff=True` on the user so they
  can also sign into Django Admin for configuration tasks.

### 3.6 Frontend routes & key components

- **`/login`** — email + password → `useAuth().login()` → JWT in `localStorage`
  under `slab_token` → redirect to `/`.
- **`/equipo`** — fetches `/api/players`, renders the existing `PlayerTable` /
  `FieldView` / `SoccerField` components. Each row links to `/perfil/{id}`.
- **`/perfil`** — empty-state stub pointing to `/equipo`.
- **`/perfil/[id]`** (client component) — uses Next 16's `use(params)`. Fetches
  player detail and builds the tab list dynamically:
  ```
  Resumen | Línea de tiempo | Eventos | <category.departments>
  ```
  Reads `?tab=<slug>` from the URL to seed the active tab — used by all
  registrar / event-creation routes for round-trip navigation.
- **Resumen** = `ProfileSummary` (still hardcoded — see §6 TODO).
- **Línea de tiempo** = `ProfileTimeline` — newest-first chronological list
  across all results in all accessible departments.
- **Eventos** = `ProfileEvents` — fetches `/events?player_id=…`, splits into
  Próximos / Pasados, renders type-coded chips (medical=violet, match=red,
  training=blue…). Has a "+ Crear evento" button → `/perfil/[id]/eventos/nuevo`.
- **Department tabs** = `ProfileDepartment` → renders the dashboard layout if
  one is configured (see §3.8); otherwise falls back to a grid of cards, one
  per applicable template. Card type depends on the template's input_config:
  - `allow_event_link: true` → `MatchHistoryTable` (totals strip + per-match
    table with W/D/L pills, opponent, minutes, goals, cards). Used by the
    Táctico department's "Rendimiento de partido" template.
  - else → legacy `DepartmentCard` (sparklines + paginated 4-row table).
  - "+ Agregar" navigates to `/perfil/[id]/registrar/[templateId]?tab=<slug>`.
- **`/perfil/[id]/registrar/[templateId]`** — mode dispatcher. Reads
  `template.input_config.default_input_mode` and renders:
  - `single` → `DynamicUploader` (auto-generated form). Shows an optional
    "Asociar partido" picker when `input_config.allow_event_link === true`.
  - `bulk_ingest` + column_mapping configured → `BulkIngestForm` (file upload
    + preview + commit + optional match association).
  - `bulk_ingest` without column_mapping → `BulkIngestPlaceholder` (shows the
    persisted mapping for sanity-check while config is incomplete).
- **`/perfil/[id]/eventos/nuevo`** — per-player event creator.
  Three scopes: Solo este jugador / Toda la categoría / Algunos jugadores
  (with search-filterable checkbox picker). Department dropdown defaults to
  the first one the player's category opted into.
- **`/partidos`** — the matches manager. Sidebar entry under "Configuraciones
  → Partidos". Default view is **Calendar** (custom 6×7 month grid, Lunes-first,
  prev/Hoy/next nav, type-coded chips with cyan dot when result_count > 0).
  Toggle to **Tabla** (filterable Todos/Próximos/Pasados, sortable columns
  including `# convocados`, `# datos` linked, edit + delete actions).
- **`/partidos/nuevo`** + **`/partidos/[id]/editar`** — thin wrappers around
  shared `MatchForm`. Form covers: category, department, title, date,
  start/end times, location, "Datos del partido" fieldset (opponent,
  competition, Local/Visita radio, goals propios + goals rival relabeled
  smartly, duration_min), notes. Edit mode shows a Delete button with an
  inline confirm overlay; warns when results are linked.

### 3.7 Visualization registry (`frontend/src/components/visualizations/`)

The `ComponentRegistry` from PROJECT.md is implemented:

```ts
// Registry.tsx
const ComponentRegistry: Record<string, React.ComponentType<VisualizerProps>> = {
  stat_card: StatCard,
  line: LineChart,
  body_map: BodyMap,
};
```

`LineChart` and `BodyMap` are lazy-loaded so the bundle stays small. To add a
new viz, create one component, register one line — admin sets `chart_type:
"<key>"` and the platform picks it up. **Body map is a placeholder** (list of
zones recorded over time); the interactive anatomical figure is its own slice.

### 3.8 Configurable dashboards (`backend/dashboards/`)

Per-`(department, category)` visualization layouts the platform admin composes
in Django Admin — no code change needed to add or rearrange charts on a player
profile. **For step-by-step admin instructions and developer extension recipes,
see [`DASHBOARDS.md`](./DASHBOARDS.md).**

**Composition tree:**

```
DepartmentLayout (department, category)
  └── LayoutSection (title, collapsible)
        └── Widget (chart_type, title, column_span, display_config)
              └── WidgetDataSource (template, field_keys, aggregation)
```

**`chart_type` registry (V1):** `comparison_table`, `line_with_selector`,
`multi_line`, `donut_per_result`, `grouped_bar`, and **`body_map_heatmap`**
(human silhouette colored by counts per body region — see DASHBOARDS.md
§4b) are fully implemented end-to-end. Three more slots are reserved in
the enum: `reference_card`, `goals_list`, `cross_exam_line`. Configuring
them today gets you an "Unsupported renderer" placeholder (intentional —
admin can wire data sources before frontend shipping). The frontend
widget registry lives at
`frontend/src/components/dashboards/widgets/index.tsx`.

**Aggregation modes** on each `WidgetDataSource`:

- `latest` — only the most recent result.
- `last_n` — last N results, chronologically. `aggregation_param` = N.
- `all` — every result the player has for that template, time-ordered.

**Server-side resolution** lives in `backend/dashboards/aggregation.py`. The
`/players/{id}/views` endpoint walks the layout tree, runs each widget's
aggregation against the player's results, and returns a chart-ready payload
keyed by `chart_type`. The frontend stays a dumb client — no data shaping in
React.

**Fallback:** when no `DepartmentLayout` exists for the player's
`(department, category)` pair, `/views` returns `{"layout": null}` and the
frontend renders the legacy `DepartmentCard` grid. Layouts ship incrementally
— configure the ones you care about, leave others alone.

**Cross-exam composition** (medical chart pulling from physical + medical +
nutritional templates) uses one widget with multiple `WidgetDataSource` rows
pointing at different `ExamTemplate`s. Validation in `WidgetDataSource.clean()`
allows mixed departments only on `chart_type='cross_exam_line'`.

**Admin UX:** three nested entry points so non-tech users only click dropdowns:

1. **Department layouts** → add a section inline, drill into it.
2. **Layout sections** → add a widget inline, drill into it.
3. **Widgets** → fill in `chart_type` + `data_sources` inline.

Field-key validation runs on `clean()`: typos surface as form errors with the
list of valid keys for the chosen template.

### 3.10 Input modes (`ExamTemplate.input_config`)

Every template carries an `input_config` JSONB blob that controls how staff
submit data:

```json
{
  "input_modes": ["single", "bulk_ingest"],
  "default_input_mode": "single",
  "modifiers": { "prefill_from_last": false },
  "allow_event_link": true,
  "column_mapping": {
    "player_lookup": { "column": "Players", "kind": "alias" },
    "session_label": { "column": "Sessions" },
    "segment": {
      "column": "Tasks",
      "values": { "Primer Tiempo": "p1", "Segundo Tiempo": "p2" }
    },
    "field_map": {
      "Tot Dist (m)":   { "template_key_pattern": "tot_dist_{segment}" },
      "Max Vel (km/h)": { "template_key": "max_vel", "reduce": "max" }
    }
  }
}
```

- **`input_modes`**: which modes are enabled. Currently implemented:
  `single`, `bulk_ingest`, and **`team_table`** (roster-style entry: one
  row per active player, with optional shared fields like `fecha` lifted
  to the top). `quick_list` is reserved for future iterations.
- **`default_input_mode`**: which one to render by default when the
  registrar page loads.
- **`allow_event_link`**: legacy JSON flag — kept in sync with the
  `ExamTemplate.link_to_match` boolean on save. Prefer the **admin checkbox**
  ("Asociar partido" section in the template form): non-tech editors flip
  it without touching JSON. The flag controls match-selector visibility on
  single, bulk-ingest, **and** team-table forms (currently single + bulk).
  Used today by `Rendimiento de partido` (Táctico, single) and
  `GPS – Rendimiento físico de partido` (Físico, bulk).
- **`team_table`**: only meaningful when `team_table` is in `input_modes`.
  ```json
  "team_table": {
    "shared_fields": ["fecha"],
    "row_fields":   ["valor", "nota"],
    "include_inactive": false
  }
  ```
  - `shared_fields` are asked once at the top of the form. Calculated
    fields are rejected here (they're computed, not entered).
  - `row_fields` become one column per — one row per active player.
    Defaults to "all non-shared, non-calculated keys in declared order"
    when omitted.
  - Submission goes to `POST /api/results/team` with body
    `{template_id, category_id, recorded_at, shared_data, rows: [{player_id, result_data}]}`.
    The endpoint merges shared_data into each row, runs the formula
    engine per row, skips fully-blank rows silently, and creates one
    `ExamResult` per matched player in a single transaction.
  - The frontend exposes it via a "Capturar todos" button on every
    department card whose template enables team_table, and via the
    URL override `?mode=team_table` on the registrar route.
- **`column_mapping`**: only meaningful when `bulk_ingest` is enabled.
  See §3.11 for the full schema.

`ExamTemplate.clean()` validates the structure: rejects unknown modes,
mismatched defaults, malformed column_mapping (missing player_lookup,
both/neither of `template_key_pattern` and `template_key` set, etc.).

### 3.11 Bulk ingest pipeline (`backend/exams/bulk_ingest.py`)

Four-step pure-Python pipeline used by `POST /api/results/bulk`:

1. **`parse_xlsx(file_bytes)`** — `openpyxl.load_workbook`, strips header
   whitespace, skips blank rows, returns `ParsedFile(headers, rows)`.
2. **`match_rows(parsed, mapping, category)`** — builds two normalized lookups
   (`PlayerAlias.value` + `first_name + last_name`, both diacritics-stripped
   and case-folded), resolves each row's player. Returns `ResolvedRow` with
   match strategy ("alias" | "name" | None) and per-row issues.
3. **`transform_rows(resolved, mapping)`** — groups rows by player and applies
   `field_map`. Pattern fields (`{segment}`-substituted) become per-segment
   keys; reduce fields collapse via `sum / max / min / avg / last`. Returns
   `{player_id: PlayerPayload}`.
4. **`run_ingest(...)`** — orchestrates, runs the formula engine on each
   payload, returns preview JSON. With `dry_run=False` also creates one
   `ExamResult` per matched player linked to the Event (when supplied).

**Dry-run-then-confirm** is a single endpoint with a `dry_run` form field —
no server-side state. The frontend round-trips the file twice (~6 KB for the
GPS sample, fine for any practical session export).

**Frontend** (`BulkIngestForm`):
- File picker (.xlsx/.xls)
- Optional **"Asociar partido"** dropdown — fetches `GET /api/events?event_type=match`,
  shows date · title · score. When selected, the date input auto-fills and
  locks; submit sends `event_id` and the server overrides `recorded_at`.
- "Cargar y previsualizar" → POST with `dry_run=true` → preview screen with
  summary tiles (rows / matched / unmatched), per-player table with totals,
  unmatched chips with hint to seed aliases.
- "Guardar N registros" → POST with `dry_run=false` → navigates back.

### 3.12 Events (`backend/events/`)

Calendar events scheduled for one or more players. Used for matches,
training sessions, medical checkups, team speeches, etc.

**Scope mechanics:**
- `scope=individual` → 1 player on the participants M2M
- `scope=category` → category set, all active players from that category
  added to participants (eagerly expanded — players who join later are NOT
  retroactively invited)
- `scope=custom` → arbitrary subset; admins pick via the search-filterable
  checkbox picker on the per-player event creator
- The full participants snapshot lives in the M2M; `category` is metadata
  for "this was a team-wide event" semantics

**Match metadata** lives in `event.metadata`:
```json
{
  "opponent": "Universidad Católica",
  "competition": "Liga 2026 - Fecha 8",
  "is_home": true,
  "score": { "home": 2, "away": 1 },
  "duration_min": 95
}
```

**Linking exam results to events**:
- `ExamResult.event` is a nullable FK with `on_delete=SET_NULL` — deleting
  an event preserves the historical results but null-clears the link
- Both `POST /api/results` (single) and `POST /api/results/bulk` accept an
  optional `event_id`. When provided:
  - The event is scope-checked against membership
  - Club-match validation: `event.club == player.category.club`
  - **`recorded_at` is overridden to `event.starts_at`** — the event is the
    authoritative timestamp. A typo in the date input can't drift away from
    the match's true start.
  - The FK is stored on every created result
- `EventOut.result_count` is annotated via `Count("exam_results")` in
  `list_events` so the matches manager can show the cyan "datos cargados"
  chip without N+1 queries.

### 3.13 Structured authoring tool — `TemplateField` rows

Non-technical staff edit `config_schema['fields']` through Django Admin's
inline form, NOT raw JSON. Storage architecture:

- The runtime canonical source is still `template.config_schema` (JSONB).
  Formula engine, frontend rendering, bulk ingest — none of them changed.
- `TemplateField` is a separate table that mirrors each field as a row.
  Saving in admin regenerates `config_schema` from the rows via
  `ExamTemplate.regenerate_config_schema_from_fields()` (called from
  `ExamTemplateAdmin.save_related`).
- The reverse direction — `rebuild_template_fields()` — backfills rows
  from JSON. Used by the data migration (`exams.0006_backfill_template_fields`)
  and by `python manage.py sync_template_fields`.

**Workflow for new templates:**
1. Run a seed command (e.g. `seed_match_performance`) — writes JSON.
2. Run `python manage.py sync_template_fields --name "<template>"` — populates rows.
3. Open admin → edit fields visually → save → JSON is rewritten from rows.

**Validators on `TemplateField.clean()`:**
- categorical → must have at least one option
- calculated → must have a formula
- multiline → only valid on text fields

The admin change view also renders a read-only `config_schema_preview`
panel (formatted JSON in monospace) so admins can verify the generated
output if they're curious.

**Note on `input_config`** — still raw JSON in admin for now. The form
fields (input_modes, default, modifiers, allow_event_link, column_mapping)
could get the same treatment in a follow-up; most authors don't need to
touch it day-to-day since seed commands handle bulk_ingest config.

### 3.15 Goals + Alerts engine (`backend/goals/`)

A doctor sets a goal: "for player X, the value of `(template, field_key)`
must satisfy `operator target_value` by `due_date`." The evaluator engine
walks active goals, transitions status, and fires alerts on misses.

**Model layer:**
- `Goal` — first-class, mutable record. Status: `active → met / missed / cancelled`.
  `warn_days_before` (default 7, nullable / 0 disables) controls the
  pre-deadline warning window — see "Pre-deadline warnings" below.
- `Alert` — generic notification with polymorphic `(source_type, source_id)`
  pointer. Source types in use today: `goal` (deadline miss),
  `goal_warning` (pre-deadline / off-track), `threshold` (§3.17).

**Evaluation paths (both share `goals.evaluator.evaluate_goal`):**

1. **Daily Celery tick** — `goals.tasks.evaluate_due_goals` (Beat schedule:
   05:00). Walks `Goal.objects.filter(status=active, due_date__lte=today)`,
   transitions to met/missed, fires an `Alert` on every miss (idempotent —
   re-running won't duplicate active alerts for the same goal).
2. **Sync re-evaluation on result save** — `post_save` on `ExamResult` calls
   `sync_evaluate_for_result(result)` which flips active goals to MET when
   a freshly-saved reading satisfies the operator. **Only the daily tick
   transitions to MISSED** — a single bad reading pre-deadline shouldn't
   close a goal; the doctor still has time to follow up.

**"Current value" definition:** the most recent `ExamResult` on
`(player, template)` whose `result_data[field_key]` is numeric and non-null.
No reading at the deadline = MISSED with `last_value=None` and a "Sin datos
en el período" alert message.

**Pre-deadline warnings** (`source_type='goal_warning'`):
- Per-goal `warn_days_before` (default 7, nullable / 0 disables) defines
  the "off-track" window. The same daily Celery tick that runs
  `apply_due_goals()` also calls `evaluate_goal_warnings()`.
- Fires when **all** of: goal is `active`, `today` falls inside
  `[due_date - warn_days_before, due_date]`, and the latest reading does
  NOT yet satisfy the operator.
- Distinct `source_type` so a warning and a deadline-miss alert can
  coexist for the same goal without colliding on the
  `(source_type, source_id)` uniqueness key.
- Self-dismissing: if a later reading flips the goal to MET (sync
  evaluator) or the doctor cancels / deletes the goal, any active
  `goal_warning` alert is dismissed automatically. Re-firing after a
  reading regresses works the same way as goal alerts.

**Email notifications:**
- `goals.tasks.send_alert_email` — Celery task fired from `_upsert_alert`
  on **alert creation only** (not re-fires, to avoid spam). Recipients are
  resolved via `_department_for_alert()` (Goal → template.department,
  AlertRule → template.department) intersected with `StaffMembership`
  scoping (department + category access). Platform admins (`is_superuser`
  with no membership) are excluded — only staff with concrete scope to the
  player's department + category get the mail.
- HTML + plaintext bodies; the link in the message points at
  `${FRONTEND_BASE_URL}/perfil/{player_id}?tab=objetivos`. Default
  `EMAIL_BACKEND` is the console backend in dev so emails print to the
  worker logs without needing SMTP.

**API:**
- `GET /api/players/{id}/goals` — list scoped goals, active first.
- `POST /api/goals` — create. Validates `field_key` is numeric/calculated
  on the template, template applies to the player's category. Accepts
  `warn_days_before` (default 7).
- `PATCH /api/goals/{id}` — partial update. `status` may only transition
  to `cancelled` via API (met/missed are evaluator-driven). On close,
  active `goal_warning` alerts pointing at the goal are dismissed.
- `DELETE /api/goals/{id}` — hard delete; also dismisses any active alerts
  (both `goal` and `goal_warning`) pointing at the goal.
- `GET /api/players/{id}/alerts?status=…` — list scoped alerts for one
  player.
- `GET /api/alerts?status=active&limit=50` — **cross-player** alert feed
  for the navbar bell. Returns `AlertWithPlayer` rows with
  `player_first_name` / `player_last_name` / `player_category_name`
  embedded so the dropdown can render without re-fetching each player.
  Filtered by `StaffMembership` scoping like every other endpoint.
- `PATCH /api/alerts/{id}` — `status='dismissed' | 'resolved'`.

**Frontend:**
- New **Objetivos** tab on the player profile (between Eventos and the
  department tabs). Card grid with status pills, target vs current with
  red/green coloring, "Cancelar" action on active goals.
- "Crear objetivo" inline form: template picker (scoped) → field picker
  (numeric/calculated only) → operator dropdown → target → due date →
  **avisar días antes** (default 7, 0/blank disables) → notes.
- Active alerts surface as a banner at the top of the same tab with
  per-alert "Descartar".
- Red badge on the player avatar (in `ProfileHeader`) when active alerts
  exist for the player.
- **Navbar bell** (`components/layout/Navbar.tsx`) — polls
  `GET /api/alerts?status=active&limit=20` every 30s, shows red count
  badge on the bell icon, click toggles a 380px dropdown listing alerts
  with severity bar (info/warning/critical), source-type tag
  (Objetivo / Aviso / Umbral), player name + category, relative time,
  "Ver" link to the player's Objetivos tab, and "Descartar" button (PATCH
  `/alerts/{id}` with optimistic remove). Click-outside closes the panel.

**Tests:** `backend/goals/tests.py` — 47 cases covering operators, missing
readings, null values, non-numeric values, due-date transitions,
sync-evaluator behavior, alert idempotence, and pre-deadline warnings
(window enforcement, dismissal on goal close, opt-out via
`warn_days_before=None`).

### 3.16 File attachments (`backend/attachments/`)

Generic file uploads with a polymorphic source pointer. Same mental model
as `Alert` — one table, plug-into-anything, two columns (`source_type`,
`source_id`) replace what would otherwise be many specific FKs.

**Storage backend.** `django-storages[s3]` + `boto3`. The compose file
ships a **MinIO** service for local dev (S3-compatible, runs in
`minio:9000`, web console at `localhost:9001`). Production points the
same env vars at AWS S3 — no code change needed.

| Env var                       | Dev default              | Prod                              |
| ----------------------------- | ------------------------ | --------------------------------- |
| `AWS_STORAGE_BUCKET_NAME`     | `slab-attachments`       | your bucket                       |
| `AWS_S3_REGION_NAME`          | `us-east-1`              | your region                       |
| `AWS_S3_ENDPOINT_URL`         | `http://minio:9000`      | leave unset for AWS               |
| `AWS_S3_PUBLIC_ENDPOINT_URL`  | `http://localhost:9000`  | leave unset for AWS               |
| `AWS_ACCESS_KEY_ID`           | `slabminio`              | IAM key                           |
| `AWS_SECRET_ACCESS_KEY`       | `slabminio-secret`       | IAM secret                        |

**Path layout in the bucket:**
`attachments/<source_type>/<YYYY-MM>/<attachment_id>__<filename>`.

**Validation on upload:**
- 25 MB hard cap (`FILE_UPLOAD_MAX_MEMORY_SIZE` + `MAX_UPLOAD_SIZE`).
- Mime allowlist: PDF, common image formats (jpeg/png/webp/heic),
  Office docs (doc/docx/xls/xlsx), txt, csv. Rejected with 415.
- `field_key` required when `source_type='exam_field'`, forbidden otherwise.

**Download flow (signed URLs, not Django streaming):**
1. Browser hits `GET /api/attachments/{id}/download` with the JWT.
2. Server scope-checks the source row (via the same scoping that gates
   the source's domain — contracts gate by club, exams by template
   department, etc.).
3. Server asks `django-storages` for a signed S3 URL (5 min TTL by
   default).
4. The internal `minio:9000` hostname is rewritten to the public
   `localhost:9000` so the browser can follow the redirect from outside
   the Docker network. In prod the rewrite is a no-op.
5. Server returns `302 Location: <signed URL>`.

**Front-end.** A reusable `AttachmentList` component
(`frontend/src/components/ui/AttachmentList/`) handles drag-and-drop +
file picker + per-file delete + signed-URL "Ver" link. It's plugged into:
- `ContractsPanel` — each contract row gets an "Archivos" expander
  that renders the list with `source_type='contract'`.
- `DynamicUploader` — when an exam template has fields with
  `type='file'`, the form first saves the result, then switches to a
  post-save view where each file field renders an `AttachmentList` with
  `source_type='exam_field'` + `field_key`. The user clicks **Listo** to
  finish the flow. Calculated/file fields are excluded from `result_data`
  serialization on submit.

**Adding `file` to a template:** Django Admin → Exam template → Template
fields inline → add a row with type **"Archivo (uno o varios)"**.

### 3.17 Threshold-based alerts (`AlertRule` + threshold evaluator)

Every time an `ExamResult` is saved, `goals.signals` fires the threshold
evaluator alongside the goal evaluator. The evaluator walks every active
`AlertRule` for that `(template, player.category)` and either fires or
refreshes an `Alert`.

**Two rule kinds, one table:**

```python
# Bound — fixed upper / lower thresholds (either side optional).
config = {"upper": 1500.0, "lower": null}

# Variation — change vs. a moving baseline. Window is either last-N
# readings or last-X-days; direction filters increase / decrease / any.
# At least one of threshold_pct / threshold_units required; both fire
# independently (logical OR).
config = {
  "window": {"kind": "last_n", "n": 4},
  # OR     {"kind": "timedelta", "days": 30}
  "threshold_pct": 5,        # 5% change vs. baseline mean
  "threshold_units": 2.0,    # OR 2.0 absolute units of change
  "direction": "any"
}
```

**Re-fire behavior** (option `a` from the design discussion):
- One **active** alert row per `(rule, player)`. Re-firing on a new
  qualifying result refreshes `last_fired_at`, increments `trigger_count`,
  and updates `message` to reflect the latest reading — instead of
  spamming a new row per reading.
- Once dismissed, a new violation **does** create a fresh alert (counter
  resets). Dismissals are intentional acknowledgments.
- Frontend's `AlertList` shows `(× N)` next to alerts with `trigger_count > 1`.

**Variation evaluator semantics:**
- Pulls the player's prior `(template, field_key)` readings into the
  configured window (excluding the current result).
- Empty history → skip silently.
- `threshold_pct` requires non-zero baseline (can't compute %); when
  baseline=0 only `threshold_units` is evaluated.
- When **both** thresholds are set, the rule fires when **either** is
  exceeded (e.g. "weight changed > 5% **or** > 3 kg, whichever first").
  Useful for fields where percentages mislead at small values.
- `direction='increase'` only fires on positive deltas ≥ threshold;
  `'decrease'` only on negative deltas ≤ -threshold; `'any'` uses
  absolute magnitude.
- Message placeholders include `{value}`, `{baseline}`, `{pct_change}`,
  `{delta}` (signed absolute change), `{direction}`, `{window_desc}`.

**Admin UX:**
- Top-level `Dashboards / Alerts → Alert rules` for cross-template
  searching + filtering.
- `AlertRuleInline` on the `ExamTemplate` change page so admins set rules
  next to the field definitions they apply to (same pattern as
  `WidgetDataSource` inline on dashboards).

**No new endpoints needed** — the existing `GET /api/players/{id}/alerts`
returns both goal and threshold alerts indistinguishably to the frontend.
The frontend just renders by severity color.

### 3.18 Episodic templates + Player.status

A way to model **longitudinal clinical concerns** (injuries, surgeries,
concussion protocols, chronic conditions) as a sequence of linked
`ExamResult`s, on top of the existing JSONB-driven exam template engine.

**Episodic template authoring:**

1. Set `ExamTemplate.is_episodic=True` and fill `episode_config`:
   ```json
   {
     "stage_field": "stage",
     "open_stages": ["injured", "recovery", "reintegration"],
     "closed_stage": "closed",
     "title_template": "{type} — {body_part}"
   }
   ```
   - `stage_field` is the field key in the schema whose value carries the
     current stage (must be `categorical` or `text`).
   - `open_stages` is ordered **worst → best** — used to rank stages
     across episodes.
   - `closed_stage` must NOT appear in `open_stages`. When the latest
     result's stage equals this, the episode auto-closes
     (`status='closed'`, `ended_at=recorded_at`).
   - `title_template` is a `str.format()`-style template rendered from
     the latest result's data.

2. Run `seed_lesiones --create-if-missing --club <name> --all-applicable-categories`
   to install the standard injury template (slug `lesiones`).

**Lifecycle:**

- New diagnosis: doctor opens the registrar, picks "Nueva lesión" → POST
  `/api/results` without `episode_id` → server opens a new `Episode` and
  links the result to it.
- Stage update: doctor picks "Continuar lesión X" → POST `/api/results`
  with `episode_id=X` → result is linked; the Episode's `stage`/`status`/
  `title`/`ended_at` are recomputed from the latest linked result.
- Player.status cache: after every Episode update, the post-save signal
  walks the player's open episodes and caches the **worst stage** on
  `Player.status` (`Player.STATUS_RANK` ranks injured < recovery <
  reintegration < available; lower rank = worse).

**Multi-episode behavior:**

A player can have several open episodes simultaneously (e.g. hamstring +
concussion). `Player.status` reflects the worst stage across all of them.
Closing the worst one drops the status to whatever the next-worst is.
The frontend Lesiones tab and the `ProfileHeader` badge show all open
episodes individually; the count chip on the badge surfaces multiplicity.

**Stage vocabulary (v1):**

For now all episodic templates share the canonical vocabulary
(`injured` / `recovery` / `reintegration` / `closed`) so the worst-stage
ranking is unambiguous. If a future protocol genuinely needs a different
clinical vocabulary, we'll add a `severity_level` mapping field on
`episode_config`. Today's `Lesiones` template fits cleanly.

**Multi-mode constraint:**

Episodic templates are restricted to `single` input mode. `bulk_ingest`
and `team_table` are rejected at the API layer because they don't have a
natural "which episode does this row belong to?" semantic.

**Frontend surfaces:**

- New **Lesiones tab** on the player profile: open episodes (with
  "Actualizar etapa" button) + closed history.
- **Episode picker** on the registrar: when the template is episodic and
  the player has open episodes, the form prompts "Nueva lesión" vs
  "Continuar <título>" before showing the field inputs.
- **ProfileHeader badge**: color-coded status pill next to the category
  tag, with a count chip when multiple open episodes exist.
- **`/equipo` roster filter**: status chips at the top of the player
  list filter to "Disponibles / Reintegración / Recuperación / Lesionados",
  with counts.

**Future work:**

- `BodyPart` model + `body_part` field type + SVG figure highlighting
  affected regions (deferred per design discussion).
- Cross-template episodes (a single concussion sharing data across
  Lesiones + a dedicated post-concussion protocol template).
- Episode-level AlertRules (e.g. "open injury > 30 days without
  progression").

### 3.14 Typography

- **Roboto** — content (body, headings, tables, sparkline labels). Loaded via
  `next/font/google` with weights 300/400/500/700.
- **Audiowide** — brand only. Used by `.slabLogo` (Navbar) and `.logoText`
  (login). Both opt in explicitly with `font-family: var(--font-audiowide)`.
- Configured in `frontend/src/app/layout.tsx` (font loaders) and
  `frontend/src/app/globals.css` (body default).

### 3.19 Team reports system (`backend/dashboards/team_aggregation.py` + `frontend/src/components/reports/`)

A **parallel** widget system to the per-player dashboards (§3.8). Lives in
the same `dashboards` Django app + same frontend folder convention but
answers a different question — "how is the squad doing on this metric?"
vs. the per-player "how is this athlete doing?".

**Models** (`backend/dashboards/models.py`):
- `TeamReportLayout` — one per `(department, category)` pair, like
  `DepartmentLayout`. Cross-club still rejected; cross-department within a
  club is allowed (e.g. Nutricional report can include GPS data from
  Performance).
- `TeamReportSection` — visual grouping with collapsible header.
- `TeamReportWidget` — single chart on a section. Carries `chart_type`,
  `column_span`, `chart_height`, `display_config` (JSONField for
  chart-specific knobs).
- `TeamReportWidgetDataSource` — child rows mirroring `WidgetDataSource`
  exactly (template autocomplete + field_keys array picker + aggregation +
  N param). Multiple sources per widget are supported and combined into
  one selectable series list.

**Admin separation:** verbose names prefix model entries so the same
"Dashboards" admin section is visually grouped:
```
Dashboards
├── Player profile — Layouts / Sections / Widgets / Widget data sources
└── Team report —    Layouts / Sections / Widgets / Widget data sources
```

**Six chart types** (all in `team_aggregation.py`):

| `chart_type`                  | What it shows                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------ |
| `team_horizontal_comparison`  | Per-player horizontal bar groups, one bar per recent reading. Multi-source supported (each (source × field_key) is a selectable series with template-disambiguated label). |
| `team_roster_matrix`          | Rows = players, columns = field keys. Latest value per cell. Optional `vs_team_range` heat coloring + variation deltas (`absolute` / `percent`) vs the previous numeric reading on the same field. Multi-source supported (synthetic keys `{source_pk}__{field_key}` when 2+ sources). |
| `team_status_counts`          | Squad availability snapshot for episodic templates (typically Lesiones). Big "X / Y disponibles" headline + segmented bar + drillable chips with player names per stage. |
| `team_trend_line`             | Multi-series line chart of team averages over time. `display_config.bucket_size` ∈ {`week`, `month`} (default week, ISO-week aligned to Monday). Field selector dropdown for multi-field configs. |
| `team_distribution`           | Histogram of latest values across the roster for one metric. Returns stats (n / mean / median / min / max) + players per bin (hover to reveal). `display_config.bin_count` (default 8, clamped 3–30). |
| `team_active_records`         | Date-range filtered table — for each player, latest record where `start_field ≤ as_of AND (end_field ≥ as_of OR null)`. Useful for non-episodic templates that still have an "active" notion (medication, contracts). `display_config` keys: `start_field` (default `fecha_inicio`), `end_field` (default `fecha_fin`), `as_of` (default today). |

**Multi-source synthetic keys** — when a widget has 2+ data sources,
field keys become `{source_pk}__{field_key}` to avoid collisions when
two templates share a field name (e.g. both have `peso`). Single-source
widgets keep raw `field_key` for cleaner payloads. Frontend treats keys
as opaque strings, so this transformation is invisible to consumers.

**Cross-cutting position filter:** `resolve_team_widget(widget, category,
*, position_id=None)` accepts an optional position UUID via the
shared `_roster_query(category, position_id)` helper. The
`/api/reports/{department_slug}` endpoint passes it through from the
report page's "Posición" dropdown — applied uniformly across every
widget on the layout.

**API:** `GET /api/reports/{department_slug}?category_id=X&position_id=Y`
returns `{layout: {...sections, widgets[].data}} | {layout: null}`.
Server-side resolution: every widget's `data` is computed before the
response, so the frontend renders without secondary fetches.

**Frontend:**
- Page: `app/(dashboard)/reportes/[deptSlug]/page.tsx` — pulls the
  layout, applies category from `useCategoryContext()` (§3.22), local
  position picker.
- Components: `components/reports/TeamReportDashboard.tsx`,
  `TeamReportSection.tsx`, `widgets/index.tsx` registry, one component
  per chart_type (`TeamHorizontalComparison.tsx`, `TeamRosterMatrix.tsx`,
  `TeamStatusCounts.tsx`, `TeamTrendLine.tsx`, `TeamDistribution.tsx`,
  `TeamActiveRecords.tsx`, `Unsupported.tsx`).
- Sidebar Reportes group is dynamically populated from the user's
  `membership.departments` — non-admins see only the department slugs
  they have access to.

**Authoring flow** (Django Admin):
1. **Team report — Layouts** → Add → pick department + category.
2. Add **Team report — Section**(s) inline.
3. Each section gets one or more **Team report — Widget** rows
   (chart_type, title, column_span). Drill into a widget to add its
   **Data sources** (template + field_keys + aggregation + N).

**Tests:** `backend/dashboards/tests.py` covers each resolver:
multi-source disambiguation, cross-source collision safety, position
filter propagation, variation indicator (off / absolute / percent) +
prior-value detection, status-counts bucketing + closed-episodes
exclusion, distribution binning + stats, active-records date-range
edge cases (open-ended / expired / future), trend-line bucketing
(week / month / invalid fallback). 68 dashboards tests in this app.

### 3.20 Player CRUD — `/configuraciones/jugadores`

Roster management surface separate from the read-only `/equipo` view.
Lives at **Sidebar → Configuraciones → Jugadores**.

**Backend** (`backend/api/routers.py`):
- `GET /api/players?include_inactive=true` — admin variant. Default
  excludes inactive players to preserve existing roster-only consumers.
- `POST /api/players` — create. Validates `category_id` is in user's
  scope; `position_id` (optional) must belong to the same club.
- `PATCH /api/players/{id}` — partial update. Re-checks scope when
  category changes. `status` is **not** writable (auto-derived from
  open episodes).
- `DELETE /api/players/{id}` — hard-delete; surfaces a 409 with a
  Spanish error message when `ProtectedError` fires (telling the admin
  to deactivate instead, to preserve history).

**Frontend** (`frontend/src/app/(dashboard)/configuraciones/jugadores/page.tsx`):
- Table view with category filter, "Incluir inactivos" toggle
  (default on), live count.
- Inline status pill click toggles active / inactive instantly.
- Pencil opens a modal with `Modal` + form; trash confirms + DELETEs.
- Defaults the form's category to whatever's selected in the navbar
  (via `useCategoryContext()`), but the page itself shows ALL accessible
  categories so admins manage every category they have access to without
  switching the navbar filter.

### 3.21 Medication template + WADA alerts (`exams/management/commands/seed_medicacion_template.py` + `exams/signals.py::medication_wada_alert_on_result_save`)

A non-episodic Médico template loaded from `data/medicamentos.csv`
(61 medicines, 19 categorías, 17 WADA-flagged: 4 PROHIBIDO + 13
CONDICIONAL). Each prescription is a flat `ExamResult` — start date
+ optional end date + dose + indication. Editing happens via the
Médico department card's history table.

**`option_groups` cascading dropdown** — the `medicamento` field uses a
generic UI affordance: `option_groups: { medicineKey: groupLabel }` on
any categorical field triggers a two-step picker (Tipo → specific
option) rendered by `GroupedCategoricalField` in `DynamicUploader.tsx`.
Reusable beyond medication.

**WADA alert signal — config-driven, not slug-keyed.** The signal fires
on every `ExamResult` save; it gates on the presence of a `medicamento`
field with `option_risk: { optionKey: "PROHIBIDO" | "CONDICIONAL" |
"PERMITIDO" }` on the template config. PROHIBIDO → critical Alert,
CONDICIONAL → warning, PERMITIDO → silent. Routes through
`goals.evaluator._upsert_alert` so emails go out + the navbar bell
picks the alert up.

- New `AlertSource.MEDICATION` enum value.
- Alert message format: `"WADA — {medicine}: {RISK} · {nota_medica} ·
  Acción: {accion_requerida}"`.
- Auxiliary metadata maps on the field config: `option_notes`,
  `option_actions` (per-medicine WADA notes + required actions).

**Why not episodic:** originally seeded as episodic mirroring Lesiones,
but the registrar's "¿continuás un episodio?" picker doesn't fit the
prescribe-once UX. Reverted to flat results. Lesiones-tab + InjuryPanel
already filter via `template_slug=lesiones` so they were never going to
include medication anyway.

**Re-seed**:
```bash
docker compose exec backend python manage.py seed_medicacion_template \
  --create-if-missing --department-slug medico \
  --all-applicable-categories --club "Universidad de Chile" --unlock
```

### 3.22 Global category context + responsive layout

**`CategoryProvider`** (`frontend/src/context/CategoryContext.tsx`)
wraps everything inside `(dashboard)/layout.tsx`. Fetches the user's
scoped categories on auth, persists the active pick to
`localStorage["slab.selectedCategoryId"]`, and exposes
`{ categories, categoryId, setCategoryId, loading }` via
`useCategoryContext()`.

The picker is rendered in the **navbar** (replacing what used to be a
per-page picker on `/equipo`, `/partidos`, `/reportes/[deptSlug]`).
Hidden for platform admins (no membership).

Pages that consume the context: `/equipo` (filters `/players`),
`/partidos` (filters `/events?event_type=match`), `/reportes/[deptSlug]`
(passes to the team-report endpoint). Forms with a parent-supplied
category (MatchForm, BulkIngestForm, TeamTableForm, registrar) keep
prop-passed category — they're scoped to a specific match or player.

**Responsive layout** (`(dashboard)/layout.tsx` + `Navbar.tsx` +
`Sidebar.tsx`):
- ≤ 1024px: sidebar becomes `position: fixed` overlay; navbar shows a
  hamburger toggle + dark backdrop. Sidebar links auto-close the drawer
  on click. ≤ 640px: hides team-title text and category-picker hint.
- Widget grid (per-player dashboards + team reports both):
  - Desktop (>1024px): respects each widget's `column_span`.
  - Tablet (641–1024px): `--tablet-col-span` = 6 if column_span ≤ 6,
    else 12 → max 2 widgets per row.
  - Mobile (≤640px): always 12 (full width).
  Computed in TSX from `widget.column_span`, applied via CSS media
  queries on `--col-span` / `--tablet-col-span` custom props.

### 3.23 Edit-in-place results + history surfaces

**`PATCH /api/results/{id}`** — already shipped before this session.
Re-runs the formula engine + refreshes inputs_snapshot; for episode-
linked results, refreshes Episode derived state + `Player.status`.

**`DELETE /api/results/{id}`** — added this session. Hard-deletes the
result and **cascades to Attachments** pinned to it (FileField.delete()
also purges S3 objects). For episodic results, refreshes the linked
Episode + recomputes `Player.status`.

**Frontend surfaces** with row-level edit + delete:
- `DepartmentCard` (player profile, per-template card) — pencil + trash
  on each row of the history table. Pencil opens a modal with
  `DynamicUploader` in edit mode (PATCH); trash confirms + DELETEs.
- `ResultsHistoryPanel` (registrar page) — collapsible `<details>`
  panel below the form showing past entries for the same (player,
  template). Lets the doctor review history without leaving the
  data-entry view. Same pencil + trash affordances.

**Inline file uploads** (`DeferredFilePicker.tsx` +
`DynamicUploader.tsx`): file fields no longer require a second screen
post-save. The form holds picked files in state and uploads in a
two-phase POST after `/results` returns the new id. Partial-failure
surfaces a non-blocking warning and the missing files can be added
via the Lesiones-tab `AttachmentList` afterwards.

### 3.24 Bulk match performance entry (`/partidos/[id]/editar`)

The matches editor now embeds a **per-roster table-style entry** for
the `Rendimiento de partido` template below the existing match form —
one row per convocado, columns for minutes/cards/goals/assists/etc.
Saves all rows in a single POST to `/api/results/team`.

Mechanism:
- `TeamResultsIn.event_id` (optional) — when set, the backend overrides
  `recorded_at` to the event's `starts_at` and links every created
  `ExamResult` to that event. Same behavior as the per-player
  registrar's `link_to_match`.
- `TeamTableForm` accepts optional `eventId` + `participantIds` props.
  When `participantIds` is set, the loaded roster is narrowed to those
  IDs (the match's participants), so the table doesn't surface players
  who didn't make the squad.
- `seed_match_performance.py` was updated to enable `team_table` input
  mode on the template (default for the bulk surface; `single` mode
  remains for per-player back-fills).

### 3.25 Player Resumen tab — real data (`GET /api/players/{id}/summary`)

Replaced the static demo content with a live aggregator endpoint:
- **Estadísticas de Juego** — sums + averages from
  `rendimiento_de_partido` results (matches played, minutes total,
  goals/assists, yellow/red cards, rating average).
- **Rendimiento Físico** — averages from
  `gps_rendimiento_fisico_de_partido` (distance/match,
  max velocity, HIAA, HMLD, accelerations).
- **Reporte Médico** — last 3 Episodes from `lesiones` (title,
  stage, started_at, ended_at, ACTIVO / ALTA badge).

Each section degrades gracefully to "Sin datos" when no results /
episodes exist or the conventional template slug isn't seeded for
the club. Slugs are conventional (matching seed commands) — admins
who re-slug their templates would need to update the endpoint to
add aliases.

### 3.26 Episode template-slug filtering

**`GET /api/players/{id}/episodes?template_slug=lesiones`** —
`template_slug` query param added so the Lesiones tab and the
`InjuryPanel` (rendered inside the Lesiones registrar form) only see
injury episodes, never medication / future episodic templates.

Frontend filters: `ProfileEpisodes.tsx` and `InjuryPanel.tsx` both
hit `?template_slug=lesiones` and pick `templates.find((t) => t.slug
=== "lesiones")` for the "+ Nueva lesión" button. Other episodic
templates (if any) surface only through their department's
`DepartmentCard` like normal exam templates.

---

## 4. Management commands

All under `backend/exams/management/commands/`. Run via
`docker compose exec backend python manage.py <name>`.

| Command                    | Lives in                              | Purpose                                                                 |
| -------------------------- | ------------------------------------- | ----------------------------------------------------------------------- |
| `seed_pentacompartimental` | `exams/management/commands/`          | Create / overwrite the 5-component anthropometry template's schema.    |
| ~~`seed_metas`~~           | `exams/management/commands/`          | **Deprecated.** Structured goals are first-class via the Goal model now (§3.15). The command file is kept for archival; do not run it. |
| `seed_daily_notes`         | `exams/management/commands/`          | Create `Notas diarias <Department>` daily-notes templates.             |
| `seed_gps_match`           | `exams/management/commands/`          | Create the GPS match-physical-performance template (48 fields, 16 metrics × 2 segments + cross-field rate totals; uses `template_builders.build_segmented_fields()`). Sets `input_modes: ["bulk_ingest"]` + a complete `column_mapping` for the sample GPS export. |
| `seed_match_performance`   | `exams/management/commands/`          | Create the per-player match performance template in Táctico (minutes, cards, goals, etc.). `allow_event_link: true`. |
| `seed_lesiones`            | `exams/management/commands/`          | Create the standard "Lesiones" episodic template in Médico (diagnosis fields + stage progression injured→recovery→reintegration→closed + file attachments for imaging). Drives `Player.status`. |
| `seed_medicacion_template` | `exams/management/commands/`          | Create the Medicación template loaded from `data/medicamentos.csv` (61 medicines, 19 categorías, 17 WADA-flagged). Non-episodic. Field config carries `option_groups` (cascading dropdown) + `option_risk` / `option_notes` / `option_actions` (consumed by the WADA alert signal). |
| `seed_gps_training`        | `exams/management/commands/`          | Create the `GPS Entrenamiento` template — flat (no P1/P2 split) per-training-day totals. team_table input mode for roster-style entry. |
| `seed_fake_exams`          | `exams/management/commands/`          | Generate fake historical results for every player × every template.    |
| `sync_template_fields`     | `exams/management/commands/`          | Rebuild `TemplateField` rows from `config_schema['fields']`. Run after a seed command so the template becomes inline-editable in admin. `--all` or `--name <template>` (repeatable). |
| `seed_uchile_2026`         | `core/management/commands/`           | Create the Universidad de Chile 2026 first-team roster (30 players, 3 GK / 9 DEF / 11 MID / 7 FWD). Idempotent. Auto-creates the `POR` position. Seeds 30 squad-number aliases + 14 nickname aliases for the GPS export's player codes (`AguArc → Agustín Arce`, etc.). |
| `seed_nutricional_layout`  | `dashboards/management/commands/`     | Bootstrap the default Nutricional dashboard layout (table + line + donut + bar) per category. **Superseded by `seed_demo_layouts` for the demo flow** — kept for ad-hoc Nutricional-only refreshes. |
| `seed_demo_layouts`        | `dashboards/management/commands/`     | One-shot: per-player + team-report layouts for all 4 demo departments (Médico / Físico / Táctico / Nutricional) on a single (club, category). Idempotent. Defaults to `Universidad de Chile / Primer Equipo`. |
| **`seed_demo`**            | `core/management/commands/`           | **Umbrella runner.** Calls every other seed in the right order: roster → templates (penta + lesiones + medicación + GPS partido + GPS entrenamiento + rendimiento + daily notes) → `sync_template_fields --all` → `seed_fake_exams` → `seed_demo_layouts`. Use this on a fresh database to bootstrap the full demo. Pass `--skip-fake-exams` to keep existing results, or `--reset-fake-exams` to wipe + regenerate. |

Common flags across the seed-template commands:

- `--create-if-missing` — create the shell template if not found.
- `--club "Name"` — required when multiple clubs exist.
- `--department-slug nutricional` — scope to one department; without it,
  `seed_daily_notes` iterates every department in the club.
- `--all-applicable-categories` — when creating, attach to every category that
  has the target department.
- `--unlock` — clear `is_locked` if a result already exists. Use with care.

`seed_fake_exams` flags:

- `--count N` (default 6) — historical results per (player × template).
- `--weeks W` (default 12) — time window over which results are spread.
- `--reset` — delete all `ExamResult` rows in scope first.

---

## 5. Doctor's workflow

1. Sign in at `http://localhost:3000/login` with email + password.
2. Open the team page, click any player.
3. Scoped to their membership, the doctor sees:
   - **Resumen** — live aggregator: match stats, GPS averages, last 3
     injuries (see §3.25).
   - **Línea de tiempo** — every result they can access, newest first
     (sorted by `result_data.fecha` when present, else `recorded_at`),
     compact 2-line cards.
   - **Eventos** — events involving this player, with edit (matches
     only) + delete affordances per card.
   - **Objetivos / Lesiones** — per §3.15 / §3.18.
   - **One tab per department** they have access to.
4. In a department tab, each template is a card with sparkline trends and a
   paginated table. Click `+ Agregar` to open the auto-generated form.
5. Submit. Calculated fields are computed server-side and rendered as
   sparkline cards on the next render. New entries appear at the top of the
   timeline.

The Pentacompartimental template ships with 8 calculated fields: IMC,
Σ 4 pliegues, % Grasa Faulkner, Masa Piel, Masa Ósea, Masa Adiposa, Masa
Residual, Masa Muscular. Formulas live in
`backend/exams/management/commands/seed_pentacompartimental.py` and reference
each other in dependency order.

> ⚠️ Anthropometric formulas (Pentacompartimental, etc.) should be cross-checked
> against the user's reference texts (Rocha 1975, Drinkwater & Ross 1980,
> Kerr 1988, Würch 1974). The implementation prefers `humero` for bone mass
> per user direction; some sources use `biestiloideo` instead. See conversation
> history for the full validation pass.

---

## 5b. Match-day workflow (GPS + per-player performance)

1. **Schedule the match** — Sidebar → **Configuraciones → Partidos → +
   Nuevo partido**. Fill category, opponent, date, score (post-match),
   competition, location.
2. **Upload GPS data** — Open any First Team player → **Físico** tab → "+
   Agregar" on the GPS template card. The registrar dispatches to
   `BulkIngestForm` because the template is configured for `bulk_ingest`.
   Pick the .xls/.xlsx file, optionally pick the match from the dropdown
   (locks the date), preview, confirm.
3. **Enter per-player match performance** — Open any player → **Táctico**
   tab. The "Rendimiento de partido" card is a `MatchHistoryTable` (totals
   + per-match rows). "+ Agregar" navigates to the registrar's single-mode
   form, which shows the "Asociar partido" picker because
   `input_config.allow_event_link === true`. Pick the match, fill stats,
   save. The result is FK-linked to the event.
4. **See data linked to a match** — On `/partidos`, the cyan chip in the
   "Datos" column shows how many results are FK-linked to each match.

**Player matching for bulk ingest** uses (in order): exact PlayerAlias
value (any kind, case-insensitive) → exact name match (diacritics-stripped,
case-folded) → unmatched. Unmatched player codes show as warning chips on
the preview screen. Seed aliases via Django Admin (PlayerAdmin → Player
aliases inline) or by extending the `seed_uchile_2026` command's
`GPS_NICKNAMES` map.

---

## 6. What's deferred (TODO)

### 6.1 Feature work

Roughly ordered by clinical value:

| Feature                                          | What it'd take                                                                                          |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| **Goal vs. Current** card on Metas               | Server-side helper to resolve a goal's `metrica_relacionada` against the player's latest matching result. New `chart_type: "goal_card"`. |
| ~~**`ProfileSummary` from real data**~~          | ✅ Shipped. `GET /api/players/{id}/summary` aggregates from `rendimiento_de_partido`, `gps_rendimiento_fisico_de_partido`, and last 3 `lesiones` episodes. See §3.25. |
| ~~**Sort timeline & lists by `fecha`**~~         | ✅ Shipped. `ProfileTimeline.tsx` uses an `effectiveDate(result)` helper — prefers `result_data.fecha` when present, falls back to `recorded_at`. |
| ~~**Edit-in-place results**~~                    | ✅ Shipped. `PATCH /api/results/{id}` (formula re-run + Episode refresh + Player.status recompute) + `DELETE /api/results/{id}` (cascades to Attachments + S3). Pencil/trash on `DepartmentCard` rows + `ResultsHistoryPanel` on the registrar. See §3.23. |
| **Template versioning**                          | Auto-fork on schema edit when `is_locked=True`, store `version+1`, preserve historical results pointing at v1. PRD calls this out as required. |
| ~~**Threshold rules + alarms**~~                 | ✅ Shipped. `AlertRule` model with `bound` + `variation` kinds, evaluator wired into the same post-save signal as goals, per-category overrides via nullable FK, idempotent re-fire with `trigger_count`. See §3.15 (Goal) + §3.17 (threshold). |
| **Real interactive `BodyMap`**                   | SVG anatomical figure with clickable zones. Currently a placeholder list. (Note: `body_map_heatmap` widget DOES render an SVG figure with region-counts heatmap — this remaining item is the *clickable* version.) |
| ~~**Player contract / agreement**~~              | ✅ Shipped. `Contract` model with full UChile-style schema (Inicio/Fin/Porcentaje/Total Bruto + free-text bonos/cláusulas), multiple-per-player history, `PlayerDetail.current_contract` embed, ProfileHeader real block + ContractsPanel with create/edit/delete. Salary fields redacted for non-staff. |
| ~~**Notifications (in-app + email)**~~          | ✅ Shipped. Email dispatch via `goals.tasks.send_alert_email` — recipients resolved through `StaffMembership` department + category scoping. In-app surface is the navbar bell with 30s polling + drillable dropdown. Still deferred: per-user opt-out, multi-channel router (Slack / Teams), digest email, and a generic `Notification`/`NotificationChannel` model so non-Alert events route through the same plumbing. |
| **Logout UI affordance**                         | `AuthContext.logout()` exists but no button is wired anywhere visible. Add to navbar / sidebar profile section. |
| ~~**Team reports system**~~                      | ✅ Shipped. Parallel to per-player dashboards. 6 chart types, multi-source, cross-cutting position filter. See §3.19. Authoring under Django Admin → "Team report — Layouts/Sections/Widgets/Widget data sources". |
| ~~**Player CRUD (configuraciones)**~~            | ✅ Shipped. `/configuraciones/jugadores` with create/edit/toggle-active/delete. POST/PATCH/DELETE `/api/players` endpoints. See §3.20. |
| ~~**Medication template + WADA alerts**~~        | ✅ Shipped. 61 medicines from CSV, 17 WADA-flagged, cascading dropdown via `option_groups`, post-save signal that fires alerts via `option_risk` field-config map. See §3.21. |
| ~~**Tablet / mobile responsive layout**~~        | ✅ Shipped. Sidebar slide-in with backdrop ≤1024px; widget grid 3-tier (12-col desktop / max-2-per-row tablet / always-12 mobile). See §3.22. |
| ~~**Global category context**~~                  | ✅ Shipped. `CategoryProvider` in dashboard layout, picker in navbar, `useCategoryContext()` consumed by `/equipo`, `/partidos`, `/reportes/[deptSlug]`. See §3.22. |
| ~~**Inline file uploads**~~                      | ✅ Shipped. `DeferredFilePicker` + two-phase save in `DynamicUploader`. See §3.23. |
| ~~**`MatchPerformanceForm` — bulk per-roster entry**~~ | ✅ Shipped. `TeamResultsIn.event_id` extension + embedded `TeamTableForm` on `/partidos/[id]/editar`. See §3.24. |
| ~~**Edit / delete events from `/perfil/[id]/eventos`**~~ | ✅ Shipped. Pencil (matches only) + trash (all event types) on each event card; matches link to `/partidos/[id]/editar`. See §3.6 + ProfileEvents.tsx. |
| **Bicompartimental & Tetracompartimental templates** | Sibling seed commands to `seed_pentacompartimental`. The engine handles them out of the box once schemas are written. |
| **Cross-player comparative analytics**           | Out of MVP per PRD. (`team_distribution` + `team_roster_matrix` cover most use cases now.) |
| **Third-party API integrations (Catapult / Wimu)** | Out of MVP per PRD. The PlayerAlias model with `kind=external_id` + `source` is already provisioned. |
| **Test suite (frontend)**                        | Backend: 145 tests across `goals` + `exams` + `dashboards`. Frontend: still no `vitest` setup. Highest-value: `lib/api.ts` token handling, `BulkIngestForm` state machine, the team-widget renderers. |
| **Edit GPS column_mapping in admin**             | `column_mapping` is still authored as raw JSON in the `input_config` field. A nested form (similar to `TemplateField` inline) would let non-tech users author bulk_ingest configs. |
| **`input_config` structured admin form**         | Multi-select for `input_modes`, dropdown for default, checkboxes for modifiers, leave column_mapping textarea. Same pattern as the new `TemplateField` inline. |
| **Recurring events**                             | `event.recurrence_rule` JSONField + an `EventSeries` model. RFC 5545/rrule library. |
| **Type-specific event fields**                   | `match.metadata` already has shape; could promote to typed admin form. Medical_checkup → linked ExamTemplate; training → planned drills; etc. |
| **Goals timeline on Event**                      | `event.metadata.goals[]` array (minute, scorer_id, kind). Surfaced as a sub-table on `/partidos/[id]/editar`. |
| **More team widgets**                            | From the original ranked palette: `team_activity_coverage` (overdue evaluations), `team_goal_progress`, `team_leaderboard`, `team_scatter`. Patterns established by the 6 shipped widgets. |
| **Direction-of-good colors for variation deltas**| Currently neutral blue/orange in roster_matrix. Add `direction_of_good` per field config to map up/down to good/bad → green/red. |

### 6.2 Tech debt / cleanup

Things that work today but should be tidied before they confuse the next contributor:

| Item                                               | Why                                                                                       |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| ~~Delete `TrendsPanel.tsx`~~                       | ✅ Done. File + index re-export removed. |
| ~~Rationalize `Sidebar.tsx` nav items~~            | ✅ Done. Dead `#` entries removed; sidebar now shows Equipo / Perfil / Reportes (dynamic) / Configuraciones. |
| ~~Delete legacy `5c-v{1,2,3}/` pages~~             | ✅ Done. All three directories removed. |
| Decide on `frontend/src/app/(dashboard)/perfil/page.tsx` | Currently an empty-state stub pointing to `/equipo`. Either make it useful (e.g. redirect to last-viewed player) or remove the route + sidebar link. |
| ~~Remove unused `Profile{Statistics,Performance,Medical,Nutritional}`~~ | ✅ Done. All four directories removed. |
| ~~Fake players (`Jugador Unila`, `Jugador Dorila`)~~ | ✅ Already cleaned in DB (30 real First Team players). |
| ~~Lint / TS cleanup~~                              | ✅ Done. Lint went 24 → 0; pre-existing TS errors in `BulkIngestForm` and `LineWithSelector` fixed. Canonical patterns documented in agent memory. |
| Auto-sync `TemplateField` rows on seed-command writes | Currently requires `python manage.py sync_template_fields` after each seed. A post_save signal on `ExamTemplate` could detect JSON↔rows divergence and auto-rebuild rows. Risk: bidirectional-sync infinite loop without careful guards. |
| "Sin partido" rows in `MatchHistoryTable` empty state | Today only the empty-state copy mentions orphans; rows without an event linked are silently dropped from the history table. Consider showing them with a "(sin partido)" label so doctors notice unlinked entries. |

---

## 7. Known caveats

- **`recorded_at` vs `fecha` vs `event.starts_at`** — three timestamps coexist:
  1. `recorded_at` is the column on `ExamResult` and what the platform sorts by.
  2. `result_data.fecha` is whatever the doctor typed in the form.
  3. `event.starts_at` (when an event is linked) **overrides `recorded_at`**
     server-side, so a result linked to a match always carries the match's
     timestamp regardless of what the form sent.
- **JSON has no comments** — `config_schema` written by hand can't
  contain `// or /* */`. Use the `TemplateField` inline (§3.13) instead of
  raw JSON for new authoring.
- **Templates lock on first result** — to change a schema after that, run the
  relevant seed command with `--unlock`, or unlock manually in admin. Note:
  this destroys the historical-data integrity guarantee until proper
  versioning ships. Both `POST /api/results` and `POST /api/results/bulk`
  auto-lock the template on first commit.
- **Formula engine = Python AST**, not JavaScript:
  - Use `a if cond else b`, **not** `cond ? a : b`.
  - Variables use `[name]` brackets *or* bare identifiers.
  - **`coalesce(a, b, …)`** returns the first non-null arg; raises if all
    are null/missing. Use it whenever a formula sums values that may be
    absent (e.g. a substitute who only played P2).
  - Failed formulas store `null` for that field — the save still succeeds; the
    UI shows `—` for that calculated value so the gap is visible.
- **Bulk ingest assumes XLSX** (.xlsx / OOXML format). True legacy `.xls`
  binary files (pre-2007) would need `xlrd<2`. The sample GPS file in the
  repo (`1777329541243.xls`) is OOXML despite the extension — `openpyxl`
  reads it fine.
- **Player matching is alias-then-name**, both diacritics-stripped and
  case-folded. New player codes from a GPS export need a corresponding
  `PlayerAlias` row to match — otherwise they show as warnings on the
  preview screen and their data is dropped on commit.
- **`event_id` overrides `recorded_at`** — both single (`POST /api/results`)
  and bulk endpoints. Frontend forms display this as a read-only date when
  a match is selected. Don't try to "fix" the timestamp by editing it.
- **Body map / `chart_type: "body_map"`** renders a placeholder zone list, not
  a real anatomical figure.
- **Frontend forms have no edit / delete** for existing results. The audit
  trail is append-only by design (until edit-in-place ships — see §6.1).
  Matches CAN be edited / deleted via `/partidos`.
- **`TemplateField` rows are not auto-created** when a seed command writes
  `config_schema`. Run `python manage.py sync_template_fields --name "<n>"`
  after a seed to rebuild rows so the template becomes inline-editable.

---

## 8. Environment variables

Defined in `.env.example`, consumed by `docker-compose.yml` and
`backend/config/settings.py`.

| Var                       | Default                          | Purpose                                |
| ------------------------- | -------------------------------- | -------------------------------------- |
| `POSTGRES_DB`             | `slab`                           |                                        |
| `POSTGRES_USER`           | `slab`                           |                                        |
| `POSTGRES_PASSWORD`       | `slab`                           |                                        |
| `DEBUG`                   | `true`                           |                                        |
| `DJANGO_SECRET_KEY`       | `dev-insecure-change-me`         | **Change for non-dev.**                |
| `DJANGO_ALLOWED_HOSTS`    | `*`                              |                                        |
| `CORS_ALLOWED_ORIGINS`    | `http://localhost:3000`          | Frontend origin                        |
| `JWT_SECRET`              | `dev-jwt-secret-change-me`       | Falls back to `DJANGO_SECRET_KEY`      |
| `JWT_LIFETIME_HOURS`      | `12`                             |                                        |
| `NEXT_PUBLIC_API_URL`     | `http://localhost:8000/api`      | Read at build time by `lib/api.ts`     |
| `EMAIL_BACKEND`           | `django.core.mail.backends.console.EmailBackend` | Console in dev (prints to worker logs); `django.core.mail.backends.smtp.EmailBackend` in prod |
| `EMAIL_HOST`              | `localhost`                      | SMTP host (prod only)                  |
| `EMAIL_PORT`              | `587`                            | SMTP port                              |
| `EMAIL_HOST_USER`         | _(empty)_                        | SMTP auth user                         |
| `EMAIL_HOST_PASSWORD`     | _(empty)_                        | SMTP auth password                     |
| `EMAIL_USE_TLS`           | `true`                           |                                        |
| `DEFAULT_FROM_EMAIL`      | `alerts@s-lab.cl`                | `From:` header on alert emails         |
| `FRONTEND_BASE_URL`       | `http://localhost:3000`          | Used in alert email "Ver" link         |

---

## 9. Building from here — recommended next slices

Pick whatever delivers the most clinical value next; recommended order:

### Quick polish (under 1h each)
1. **Sort by `fecha`** in `ProfileTimeline` and `DepartmentCard` table — prefer
   `result_data.fecha`, fall back to `recorded_at`.
2. **Logout UI** in the navbar/sidebar — `AuthContext.logout()` already exists,
   just needs a button.
3. **Sidebar cleanup** — most entries point to `#`; either wire them or delete.
4. **Drop the 2 fake test players** (`Jugador Unila`, `Jugador Dorila`) and
   their 60 fake exam results each — `seed_uchile_2026` left them in place.
5. **Auto-sync `TemplateField` from seed commands** — small wrapper helper
   that every seed command calls after writing `config_schema`, so admins
   don't need to remember `sync_template_fields`.

### Authoring polish
6. **Structured `input_config` admin form** — multi-select for `input_modes`,
   dropdown for `default_input_mode`, checkboxes for `modifiers` /
   `allow_event_link`. The same `TemplateField`-style improvement applied
   to `input_config`. `column_mapping` can stay JSON for now.
7. **Bicompartimental + Tetracompartimental seed commands** — sibling to
   `seed_pentacompartimental` using `template_builders.build_segmented_fields`
   if appropriate, or hand-written if the metric set is fully distinct.

### Match-day completeness
8. **Per-roster bulk match-performance entry** on `/partidos/[id]/editar` —
   table view with one row per participant, columns for minutes / cards /
   goals. Single POST creates all the linked ExamResults at once. Saves
   30 form submits per match.
9. **Show "Sin partido" results** in `MatchHistoryTable` — currently dropped
   silently; surface them as orphan rows so doctors can re-link them.
10. **Goals timeline on Event** — `event.metadata.goals[]` (minute, scorer_id,
    kind), with a sub-table on the match edit page.

### Bigger initiatives
11. **Real `ProfileSummary`** — aggregator endpoint
    `/api/players/{id}/summary` returning per-department highlights.
12. **Goal-vs-Current card** — joins `Metas` template with live data; high
    demo value.
13. **Test suite** — `pytest` for `exams/calculations.py` (formula engine +
    coalesce edge cases), `exams/bulk_ingest.py` (parse/match/transform),
    `api/scoping.py` (access control). Frontend `vitest` for `lib/api.ts`
    token handling and the BulkIngestForm state machine.
14. **Player contract** — `Contract` model FK to `Player`. Surface in
    `ProfileHeader` (currently a `—` placeholder).
15. ~~**Threshold alarms + notifications**~~ — ✅ Shipped. `AlertRule` model
    + `goals.evaluator` (sync + Celery beat), goal pre-deadline warnings,
    email dispatch via Celery, navbar bell with live dropdown. See §3.15
    + §3.17. What's left: per-user opt-out, multi-channel router (Slack /
    Teams), digest email.
16. **Template versioning** — auto-fork on schema edit when locked, preserve
    historical results pointing at v1. PRD-required.
17. **Real interactive `BodyMap`** — SVG anatomical figure with clickable zones.
18. **Recurring events** — `recurrence_rule` JSONB or `EventSeries` model.
19. **Catapult / Wimu integrations** — pulls data automatically. The
    `PlayerAlias.kind=external_id` + `source` slot is already provisioned
    for the matching layer.

---

## 9b. Production deployment plan

### Client preview: Railway (recommended for now)

For a client-review deployment we use Railway — managed Postgres + Redis
+ Docker-based services, no infra to provision. The S3 / endpoint
defaults in `backend/config/settings.py` were updated this session to
treat empty/missing `AWS_S3_ENDPOINT_URL` as None, so simply omitting
the MinIO-specific vars on Railway makes boto3 hit real AWS S3 cleanly.

**Walkthrough:** see [`RAILWAY_DEPLOY.md`](./RAILWAY_DEPLOY.md) — covers
S3 bucket + IAM setup, Railway service creation (backend / worker /
beat / frontend), env-var mapping (`POSTGRES_HOST=${{Postgres.PGHOST}}`
etc.), first-deploy migrations + seeds, custom domain, and the
gotchas around `NEXT_PUBLIC_API_URL` being a build-time var.

**Cost:** ~$25–35/mo always-on; lower with sleep-on-idle for the web
services (worker + beat must stay always-on for the daily evaluator).

### Long-term: AWS (Path 1 — single EC2 mirror of dev)

Discussion in progress, paused before scaffolding. Decisions captured here so
they aren't relitigated later. **Nothing in the repo is wired for prod yet.**

#### Hosting target
**Single AWS EC2 box ("Path 1" — closest mirror of dev).** Lift-and-shift
the existing `docker-compose.yml` to a single host, swap MinIO for real S3
and the postgres container for RDS. Path 2 (App Runner + ECS Fargate +
ElastiCache) is the migration target once traffic justifies HA, and the
image-build pipeline transfers without rewrites.

| Resource                          | Spec                          | Cost (rough) |
| --------------------------------- | ----------------------------- | ------------ |
| EC2 `t4g.small` (Ubuntu 24.04 ARM) | 2 vCPU, 2 GB                 | ~$13/mo      |
| Elastic IP (attached)             | static                        | $0           |
| RDS Postgres `db.t4g.micro`       | 1 vCPU, 1 GB, 20 GB gp3       | ~$13/mo      |
| S3 bucket `s-lab-cl-attachments`  | private                       | <$1/mo       |
| ECR repo for backend image        | 1 repo                        | <$1/mo       |
| Route 53 hosted zone (existing)   | `s-lab.cl`                    | $0.50/mo     |
| **Total**                         |                               | **~$28–30/mo** |

### DNS / TLS
- `s-lab.cl` → A record → EC2 EIP → **Caddy** → Next.js frontend (port 3000)
- `api.s-lab.cl` → A record → same EC2 EIP → **Caddy** → Django backend (port 8000)
- Caddy handles automatic Let's Encrypt cert issuance + renewal for both names.

### CI/CD
GitHub Actions, OIDC-authenticated against AWS (no long-lived keys).

- `.github/workflows/ci.yml` — runs on every PR: backend `manage.py test` + frontend lint.
- `.github/workflows/deploy.yml` — runs on merge to `main`: builds backend +
  frontend images, tags with commit SHA, pushes to ECR, then
  `docker compose pull && up -d` over SSH (or via SSM run-command).

### Files to scaffold (when we resume)
```
deploy/
  docker-compose.prod.yml      # overlay: real env vars, no MinIO/minio-init
  Dockerfile.prod              # multi-stage backend image (gunicorn, no dev deps)
  frontend.Dockerfile.prod     # multi-stage Next.js standalone build
  Caddyfile                    # auto-TLS for s-lab.cl + api.s-lab.cl
  bootstrap.sh                 # one-shot init for the EC2 box
.github/workflows/
  ci.yml
  deploy.yml
DEPLOY.md                       # step-by-step provisioning + first deploy
```

### Open scoping questions (asked but not yet answered)
1. **AWS region** — recommendation `sa-east-1` (São Paulo, lowest LatAm
   latency for Chilean users) vs `us-east-1` (cheaper, broader feature set,
   ~+150 ms latency).
2. **Subdomain layout** — confirmed shape `s-lab.cl` (frontend) +
   `api.s-lab.cl` (backend) recommended over single-domain `/api/...`
   proxying because of cleaner CORS + admin separation.

### What's already prod-friendly in the repo
- S3 storage backend (`django-storages[s3]`) is already wired. Switching
  from MinIO to real S3 is purely env-var: drop `AWS_S3_ENDPOINT_URL` and
  `AWS_S3_PUBLIC_ENDPOINT_URL`, set the real bucket + IAM keys.
- Celery + Beat services + Redis already in compose; just need the prod
  overlay to use a real REDIS URL (managed or in-container, both work).
- All app data lives in Postgres + S3 — the EC2 box is genuinely
  stateless and replaceable.

---

## 10. Useful commands cheat-sheet

```bash
# Bring everything up:
docker compose up --build

# Apply schema changes:
docker compose exec backend python manage.py makemigrations core exams dashboards events
docker compose exec backend python manage.py migrate

# Wipe and reseed dev data:
docker compose down -v
docker compose up -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser

# Roster + GPS aliases (run BEFORE GPS-related templates so matching works):
docker compose exec backend python manage.py seed_uchile_2026

# Templates (each writes config_schema JSON):
docker compose exec backend python manage.py seed_pentacompartimental \
    --create-if-missing --department-slug nutricional --all-applicable-categories
docker compose exec backend python manage.py seed_metas \
    --create-if-missing --all-applicable-categories
docker compose exec backend python manage.py seed_daily_notes \
    --create-if-missing --all-applicable-categories
docker compose exec backend python manage.py seed_gps_match \
    --create-if-missing --department-slug fisico --all-applicable-categories
docker compose exec backend python manage.py seed_match_performance \
    --create-if-missing --department-slug tactico --all-applicable-categories

# After ANY seed command writes config_schema, rebuild TemplateField rows so
# the template becomes inline-editable in Django Admin:
docker compose exec backend python manage.py sync_template_fields --all

# Fake history + dashboard layouts:
docker compose exec backend python manage.py seed_fake_exams --reset
docker compose exec backend python manage.py seed_nutricional_layout \
    --all-applicable-categories

# Backend Python shell:
docker compose exec backend python manage.py shell

# Frontend lint:
docker compose exec frontend npm run lint

# Tail logs:
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f worker beat   # Celery

# Run goal/alert tests:
docker compose exec backend python manage.py test goals -v 2

# Manually trigger the daily goal evaluator (without waiting for 05:00):
docker compose exec backend python manage.py shell -c \
  "from goals.evaluator import apply_due_goals; print(apply_due_goals())"

# Or queue it via the worker (round-trips through Redis):
docker compose exec backend python manage.py shell -c \
  "from goals.tasks import evaluate_due_goals; r=evaluate_due_goals.delay(); print(r.get(timeout=10))"
```

---

*Last updated 2026-04-29 — end of session that added: events app + match
metadata, GPS bulk ingest, PlayerAlias matching, segmented template builders
+ `coalesce` formula function, the `/partidos` matches manager (calendar +
table), the per-player Eventos tab, the Táctico `MatchHistoryTable`, and the
`TemplateField` structured authoring tool. When in doubt, read the file paths
above — the code is the source of truth.*
