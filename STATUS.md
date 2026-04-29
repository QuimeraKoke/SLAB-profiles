# SLAB — Project Status & Handoff

> **Snapshot at:** end of build session — pivot from Next.js-only mock to a working
> Django + PostgreSQL backend + dynamic Next.js frontend with the
> configuration-driven exam engine described in `PROJECT.md`.
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
| Redis    | localhost:6379                 | Wired in compose, **not yet used** |

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

# Goals + daily notes templates per department:
docker compose exec backend python manage.py seed_metas \
    --create-if-missing --all-applicable-categories
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
│   │                       # ExamResult (with event FK), calculations.py,
│   │                       # bulk_ingest.py, template_builders.py,
│   │                       # management/commands/seed_*.py
│   ├── dashboards/         # DepartmentLayout, LayoutSection, Widget,
│   │                       # WidgetDataSource + aggregation engine
│   ├── events/             # Event model + admin (calendar + match metadata)
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
        │       ├── equipo/page.tsx              # Roster / pitch view
        │       ├── perfil/[id]/page.tsx         # Dynamic player profile
        │       ├── perfil/[id]/registrar/[templateId]/  # Mode-dispatching form
        │       ├── perfil/[id]/eventos/nuevo/   # Per-player event creator
        │       ├── partidos/page.tsx            # Matches manager (calendar + table)
        │       ├── partidos/nuevo/              # Create match form
        │       └── partidos/[id]/editar/        # Edit match form
        ├── components/
        │   ├── equipo/
        │   ├── forms/
        │   │   ├── DynamicUploader.tsx          # single-mode form, optional match link
        │   │   ├── BulkIngestForm.tsx           # file picker + preview/confirm
        │   │   └── BulkIngestPlaceholder.tsx    # fallback when no column_mapping yet
        │   ├── partidos/
        │   │   ├── MatchForm.tsx                # shared create + edit form
        │   │   └── MatchesCalendar.tsx          # month-grid view
        │   ├── perfil/
        │   │   ├── ProfileHeader/
        │   │   ├── ProfileTabs/                 # generic, takes tabs[]
        │   │   ├── ProfileSummary/              # Resumen tab (still hardcoded)
        │   │   ├── ProfileTimeline/             # Línea de tiempo tab
        │   │   ├── ProfileEvents/               # Eventos tab (player events)
        │   │   ├── MatchHistoryTable/           # Táctico-tab match performance view
        │   │   ├── ProfileDepartment/           # fetches layout + falls back
        │   │   │   └── DashboardEntryPanel/     # template-pick (links to registrar)
        │   │   └── DepartmentCard/              # legacy fallback grid
        │   ├── dashboards/                      # configurable layout renderer
        │   │   ├── DepartmentDashboard.tsx
        │   │   ├── SectionGroup.tsx
        │   │   └── widgets/                     # chart_type → component map
        │   │       ├── index.tsx                # renderWidget()
        │   │       ├── ComparisonTable.tsx
        │   │       ├── LineWithSelector.tsx
        │   │       ├── MultiLine.tsx
        │   │       ├── DonutPerResult.tsx
        │   │       ├── GroupedBar.tsx
        │   │       └── Unsupported.tsx
        │   └── visualizations/                  # legacy registry (per-field chart_type)
        │       ├── Registry.tsx
        │       ├── StatCard.tsx
        │       ├── LineChart.tsx
        │       ├── BodyMap.tsx (placeholder)
        │       └── types.ts
        ├── context/AuthContext.tsx              # JWT + /auth/me hydration
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
| `Player`           | `id`, `category FK`, `position FK`, `nationality`, …           | `position` is nullable. Admin filters position picker to the player's club.                        |
| `PlayerAlias`      | `id`, `player FK`, `kind`, `source`, `value`                   | Alternate identifiers for matching: `nickname` / `squad_number` / `external_id` (with `source`: catapult, wimu, manual). External-IDs uniqueness validated per club via `clean()`. Inline on PlayerAdmin. |
| `StaffMembership`  | `id`, `user OneToOne`, `club FK`, `all_categories`, `categories M2M`, `all_departments`, `departments M2M` | One club per user. "All" flag bypasses the M2M list.                                  |
| `ExamTemplate`     | `id`, `name`, `department FK`, `applicable_categories M2M`, `config_schema JSONB`, `input_config JSONB`, `version`, `is_locked` | Locks after first result. `input_config` controls input modes (single / bulk_ingest / etc.) — see §3.10. |
| `TemplateField`    | `id`, `template FK`, `sort_order`, `key`, `label`, `type`, `unit`, `group`, `options JSONB`, `formula`, `chart_type`, `required`, `multiline`, `rows`, `placeholder` | Authoring abstraction over `config_schema['fields']`. Saving in admin regenerates the JSON. See §3.13. |
| `ExamResult`       | `id`, `player FK`, `template FK`, `recorded_at`, `result_data JSONB`, `event FK (nullable)` | GIN-indexed on `result_data`. `event` FK links results to a calendar event (e.g. GPS upload from a match). Calculated outputs computed server-side. |
| `Event`            | `id`, `club FK`, `department FK`, `event_type`, `title`, `description`, `starts_at`, `ends_at`, `location`, `scope` (individual/category/custom), `category FK (nullable)`, `participants M2M Player`, `metadata JSONB`, `created_by FK User` | Calendar events: matches, training, medical_checkup, physical_test, team_speech, nutrition, other. Match-specific data (opponent, score, competition, is_home, duration_min) lives in `metadata`. |
| `DepartmentLayout` | `id`, `department FK`, `category FK`, `name`, `is_active`            | One layout per `(department, category)`. `clean()` enforces same club + category opt-in. |
| `LayoutSection`    | `id`, `layout FK`, `title`, `is_collapsible`, `default_collapsed`, `sort_order` | Visual grouping inside a layout.                                                          |
| `Widget`           | `id`, `section FK`, `chart_type`, `title`, `description`, `column_span`, `display_config JSONB`, `sort_order` | One chart card. `chart_type` is a TextChoices registry — see §3.9. |
| `WidgetDataSource` | `id`, `widget FK`, `template FK`, `field_keys text[]`, `aggregation`, `aggregation_param`, `label`, `color`, `sort_order` | Bound data feed. `clean()` validates field_keys against the template schema. |

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
| GET    | `/api/players/{id}`                              | Scoped; rich `PlayerDetailOut` (club + category + position embedded) |
| GET    | `/api/players/{id}/templates?department=…`       | Scoped to player's category + user's departments                     |
| GET    | `/api/players/{id}/results?department=…`         | Filter by department slug. Each result embeds optional `event` brief (id, type, title, starts_at, metadata). |
| GET    | `/api/players/{id}/views?department=…`           | Returns `{layout: …}` — server-aggregated dashboard payload, or `{layout: null}` for fallback |
| GET    | `/api/templates/{id}`                            | Scoped; includes `input_config`                                      |
| POST   | `/api/results`                                   | Runs formula engine on submit. Optional `event_id` links the result and overrides `recorded_at` to the event's start. |
| POST   | `/api/results/bulk`                              | `multipart/form-data`. Parse → match (PlayerAlias + name) → transform (segment-aware) → preview/commit. See §3.11. |
| GET    | `/api/events?event_type=…&player_id=…&category_id=…&department=…&starts_after=…&starts_before=…` | List events visible to user, filterable. Annotated with `result_count` (linked ExamResult rows). |
| GET    | `/api/events/{id}`                               | Detail; full participants list                                       |
| POST   | `/api/events`                                    | Create. Resolves participants through `scope_players()`.             |
| PATCH  | `/api/events/{id}`                               | Full update with participant resync.                                 |
| DELETE | `/api/events/{id}`                               | Delete (linked ExamResults are preserved with `event=null`).         |

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
`donut_per_result`, `grouped_bar` are fully implemented end-to-end. Three more
slots are reserved in the enum for V2: `reference_card`, `goals_list`,
`cross_exam_line`. Configuring them today gets you an "Unsupported renderer"
placeholder (intentional — admin can wire data sources before frontend
shipping). The frontend widget registry lives at
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
  `single` (fully working) and `bulk_ingest` (fully working).
  `team_table` and `quick_list` are reserved for future iterations.
- **`default_input_mode`**: which one to render by default when the
  registrar page loads.
- **`allow_event_link`**: when `true`, the single-mode form shows an
  "Asociar partido" dropdown that lets the user attach the result to a
  match Event. Used by the Táctico "Rendimiento de partido" template.
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

### 3.14 Typography

- **Roboto** — content (body, headings, tables, sparkline labels). Loaded via
  `next/font/google` with weights 300/400/500/700.
- **Audiowide** — brand only. Used by `.slabLogo` (Navbar) and `.logoText`
  (login). Both opt in explicitly with `font-family: var(--font-audiowide)`.
- Configured in `frontend/src/app/layout.tsx` (font loaders) and
  `frontend/src/app/globals.css` (body default).

---

## 4. Management commands

All under `backend/exams/management/commands/`. Run via
`docker compose exec backend python manage.py <name>`.

| Command                    | Lives in                              | Purpose                                                                 |
| -------------------------- | ------------------------------------- | ----------------------------------------------------------------------- |
| `seed_pentacompartimental` | `exams/management/commands/`          | Create / overwrite the 5-component anthropometry template's schema.    |
| `seed_metas`               | `exams/management/commands/`          | Create `Metas <Department>` goals templates (per department or all).   |
| `seed_daily_notes`         | `exams/management/commands/`          | Create `Notas diarias <Department>` daily-notes templates.             |
| `seed_gps_match`           | `exams/management/commands/`          | Create the GPS match-physical-performance template (48 fields, 16 metrics × 2 segments + cross-field rate totals; uses `template_builders.build_segmented_fields()`). Sets `input_modes: ["bulk_ingest"]` + a complete `column_mapping` for the sample GPS export. |
| `seed_match_performance`   | `exams/management/commands/`          | Create the per-player match performance template in Táctico (minutes, cards, goals, etc.). `allow_event_link: true`. |
| `seed_fake_exams`          | `exams/management/commands/`          | Generate fake historical results for every player × every template.    |
| `sync_template_fields`     | `exams/management/commands/`          | Rebuild `TemplateField` rows from `config_schema['fields']`. Run after a seed command so the template becomes inline-editable in admin. `--all` or `--name <template>` (repeatable). |
| `seed_uchile_2026`         | `core/management/commands/`           | Create the Universidad de Chile 2026 first-team roster (30 players, 3 GK / 9 DEF / 11 MID / 7 FWD). Idempotent. Auto-creates the `POR` position. Seeds 30 squad-number aliases + 14 nickname aliases for the GPS export's player codes (`AguArc → Agustín Arce`, etc.). |
| `seed_nutricional_layout`  | `dashboards/management/commands/`     | Bootstrap the default Nutricional dashboard layout (table + line + donut + bar) per category. |

Common flags across the seed-template commands:

- `--create-if-missing` — create the shell template if not found.
- `--club "Name"` — required when multiple clubs exist.
- `--department-slug nutricional` — scope to one department; without it,
  `seed_metas` and `seed_daily_notes` iterate every department in the club.
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
   - **Resumen** (still hardcoded demo).
   - **Línea de tiempo** — every result they can access, newest first,
     compact 2-line cards.
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
| **`ProfileSummary` from real data**              | Aggregator endpoint `/api/players/{id}/summary` returning per-department highlights. Replace static demo. |
| **Sort timeline & lists by `fecha`**             | One-line frontend change in `ProfileTimeline.tsx` (and `DepartmentCard.tsx`'s table sort): prefer `result_data.fecha` if present, else `recorded_at`. |
| **Edit-in-place results**                        | New `PATCH /api/results/{id}` endpoint, opens DynamicUploader prefilled. Decision needed: edit destroys audit trail, or keep version history. |
| **Template versioning**                          | Auto-fork on schema edit when `is_locked=True`, store `version+1`, preserve historical results pointing at v1. PRD calls this out as required. |
| **Threshold rules + alarms**                     | New `Alarm` model (per-template + per-category thresholds), Celery worker that evaluates on result save. Compose already runs Redis. |
| **Real interactive `BodyMap`**                   | SVG anatomical figure with clickable zones. Currently a placeholder list. |
| **Player contract / agreement**                  | New `Contract` model FK to `Player` (`amount`, `currency`, `start_date`, `end_date`, …). Surface in `ProfileHeader`'s right column (currently a `—` placeholder). The screenshot shows "CONTRATO VIGENTE" — that block is deliberately stubbed today. |
| **Notifications**                                | Per-user `Notification` model + `NotificationChannel` (in-app, email). Integrate with the alarms engine so threshold breaches push to the right staff. |
| **Logout UI affordance**                         | `AuthContext.logout()` exists but no button is wired anywhere visible. Add to navbar / sidebar profile section. |
| **Bicompartimental & Tetracompartimental templates** | Sibling seed commands to `seed_pentacompartimental`. The screenshot shows them in the original system; the engine handles them out of the box once schemas are written. |
| **Cross-player comparative analytics**           | Out of MVP per PRD. |
| **Third-party API integrations (Catapult / Wimu)** | Out of MVP per PRD. The PlayerAlias model with `kind=external_id` + `source` is already provisioned for it — when ingestion ships, just store the system-specific IDs as aliases. |
| **Test suite**                                   | No tests exist yet. Highest-value first: `pytest` for `exams/calculations.py` (formula engine — security-critical, includes coalesce edge cases), `exams/bulk_ingest.py` (parse/match/transform), and `api/scoping.py` (access control). Frontend `vitest` for `lib/api.ts` token handling and the BulkIngestForm state machine. |
| **Edit GPS column_mapping in admin**             | `column_mapping` is still authored as raw JSON in the `input_config` field. A nested form (similar to `TemplateField` inline) would let non-tech users author bulk_ingest configs. |
| **`input_config` structured admin form**         | Multi-select for `input_modes`, dropdown for default, checkboxes for modifiers, leave column_mapping textarea. Same pattern as the new `TemplateField` inline. |
| **Recurring events**                             | `event.recurrence_rule` JSONField + an `EventSeries` model. RFC 5545/rrule library. |
| **Edit / delete events from `/perfil/[id]/eventos`** | Today only the matches manager has full CRUD. Per-player events are admin-only after creation. |
| **Type-specific event fields**                   | `match.metadata` already has shape; could promote to typed admin form. Medical_checkup → linked ExamTemplate; training → planned drills; etc. |
| **Goals timeline on Event**                      | `event.metadata.goals[]` array (minute, scorer_id, kind). Surfaced as a sub-table on `/partidos/[id]/editar`. |
| **`MatchPerformanceForm` — bulk per-roster entry** | Today the doctor enters performance one player at a time via the registrar's single mode. A dedicated table-style entry on `/partidos/[id]/editar` (one row per participant, columns for minutes/cards/goals) would save 30 form submits per match. |

### 6.2 Tech debt / cleanup

Things that work today but should be tidied before they confuse the next contributor:

| Item                                               | Why                                                                                       |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Delete `frontend/src/components/visualizations/TrendsPanel.tsx` and its CSS | Superseded by per-template visualizations inside `DepartmentCard`. Currently dead code, but exported via `index.ts` and looks like an active component. |
| Rationalize `Sidebar.tsx` nav items                | Most entries (`Panel`, `Estadísticas`, `Desempeño`, `Médico`, `Psicosocial`, `Técnica`, `Tareas`, `Organización`) point to `#`. Either wire them up or delete; current state misleads. The new "Configuraciones → Partidos" entry IS wired. |
| Delete legacy `frontend/src/app/(dashboard)/nutricional/5c-v{1,2,3}/` pages | Pre-pivot static demos hardcoded in the original codebase. Replaced by the dynamic `Pentacompartimental` template; still reachable from the sidebar's `Nutricional` dropdown. |
| Decide on `frontend/src/app/(dashboard)/perfil/page.tsx` | Currently an empty-state stub pointing to `/equipo`. Either make it useful (e.g. redirect to last-viewed player) or remove the route + sidebar link. |
| Remove unused `ProfileStatistics`, `ProfilePerformance`, `ProfileMedical`, `ProfileNutritional` components | Original profile-tab-per-department components, no longer referenced after the dynamic-tabs refactor. |
| Two fake players in Primer Equipo (`Jugador Unila`, `Jugador Dorila`) | 60 fake exam results each from `seed_fake_exams`. Left intact when `seed_uchile_2026` ran; delete in admin if the team only wants the real 30-player roster. |
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
15. **Threshold alarms + notifications** — biggest infra step. `Alarm` model,
    Celery worker, notification channels. PRD-required.
16. **Template versioning** — auto-fork on schema edit when locked, preserve
    historical results pointing at v1. PRD-required.
17. **Real interactive `BodyMap`** — SVG anatomical figure with clickable zones.
18. **Recurring events** — `recurrence_rule` JSONB or `EventSeries` model.
19. **Catapult / Wimu integrations** — pulls data automatically. The
    `PlayerAlias.kind=external_id` + `source` slot is already provisioned
    for the matching layer.

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
```

---

*Last updated 2026-04-29 — end of session that added: events app + match
metadata, GPS bulk ingest, PlayerAlias matching, segmented template builders
+ `coalesce` formula function, the `/partidos` matches manager (calendar +
table), the per-player Eventos tab, the Táctico `MatchHistoryTable`, and the
`TemplateField` structured authoring tool. When in doubt, read the file paths
above — the code is the source of truth.*
