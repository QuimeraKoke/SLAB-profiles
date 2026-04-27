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
```

Log in at http://localhost:3000/login. Open any player → switch tabs.

---

## 2. Repository layout

```
slab-profiles/
├── PROJECT.md              # Product vision + architecture spec (the "why")
├── STATUS.md               # This file
├── README.md               # Operator-facing quick reference
├── AGENTS.md               # Reminder: Next 16 has breaking changes
├── docker-compose.yml      # postgres + redis + backend + frontend
├── .env.example
│
├── backend/                # Django + Django Ninja
│   ├── manage.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── config/             # settings, urls, wsgi/asgi
│   ├── core/               # Club, Department, Category, Position, Player,
│   │                       # StaffMembership models + admin
│   ├── exams/              # ExamTemplate, ExamResult, calculations.py,
│   │                       # management/commands/seed_*.py
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
        │       └── perfil/[id]/page.tsx         # Dynamic player profile
        ├── components/
        │   ├── equipo/
        │   ├── forms/DynamicUploader.tsx        # config-driven form renderer
        │   ├── perfil/
        │   │   ├── ProfileHeader/
        │   │   ├── ProfileTabs/                 # generic, takes tabs[]
        │   │   ├── ProfileSummary/              # Resumen tab (still hardcoded)
        │   │   ├── ProfileTimeline/             # Línea de tiempo tab
        │   │   ├── ProfileDepartment/           # one tab per department
        │   │   └── DepartmentCard/              # one card per template
        │   └── visualizations/                  # ComponentRegistry pattern
        │       ├── Registry.tsx
        │       ├── StatCard.tsx
        │       ├── LineChart.tsx
        │       ├── BodyMap.tsx (placeholder)
        │       ├── TrendsPanel.tsx (legacy, unused after card refactor)
        │       └── types.ts
        ├── context/AuthContext.tsx              # JWT + /auth/me hydration
        └── lib/
            ├── api.ts                           # fetch wrapper
            └── types.ts                         # mirrors backend schemas
```

---

## 3. What's been built

### 3.1 Data model (`backend/core/models.py` + `backend/exams/models.py`)

Strict-relational core, JSONB-driven exams.

| Model              | Key fields                                                     | Notes                                                                                              |
| ------------------ | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `Club`             | `id (UUID)`, `name`                                            |                                                                                                    |
| `Department`       | `id`, `club FK`, `name`, `slug`                                | Per-club. Slug auto-derived from name. `(club, name)` and `(club, slug)` unique-together.          |
| `Category`         | `id`, `club FK`, `name`, `departments M2M`                     | Categories opt in to which departments they run.                                                   |
| `Position`         | `id`, `club FK`, `name`, `abbreviation`, `role`, `sort_order`  | Per-club soccer positions.                                                                         |
| `Player`           | `id`, `category FK`, `position FK`, `nationality`, …           | `position` is nullable. Admin filters position picker to the player's club.                        |
| `StaffMembership`  | `id`, `user OneToOne`, `club FK`, `all_categories`, `categories M2M`, `all_departments`, `departments M2M` | One club per user. "All" flag bypasses the M2M list.                                  |
| `ExamTemplate`     | `id`, `name`, `department FK`, `applicable_categories M2M`, `config_schema JSONB`, `version`, `is_locked` | Locks after first result.                                                                          |
| `ExamResult`       | `id`, `player FK`, `template FK`, `recorded_at`, `result_data JSONB` | GIN-indexed on `result_data`. Calculated outputs computed server-side.                             |

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
  `ln`, `exp`, `pow`
- constants `pi`, `e`

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
| GET    | `/api/categories/{id}`                           | Scoped; embeds allowed departments                                   |
| GET    | `/api/players?category_id=…`                     | Scoped                                                               |
| GET    | `/api/players/{id}`                              | Scoped; rich `PlayerDetailOut` (club + category + position embedded) |
| GET    | `/api/players/{id}/templates?department=…`       | Scoped to player's category + user's departments                     |
| GET    | `/api/players/{id}/results?department=…`         | Filter by department slug                                            |
| GET    | `/api/templates/{id}`                            | Scoped                                                               |
| POST   | `/api/results`                                   | Runs formula engine on submit; merges calculated outputs             |

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
- Mutations (POST `/results`) check that the target template's department is
  one the user can access — silent 404 otherwise (no information leakage).
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
  Resumen | Línea de tiempo | <category.departments>
  ```
- **Resumen** = `ProfileSummary` (still hardcoded — see §6 TODO).
- **Línea de tiempo** = `ProfileTimeline` — newest-first chronological list
  across all results in all accessible departments.
- **Department tabs** = `ProfileDepartment` → grid of `DepartmentCard`, one
  per template applicable to the player's category. Each card has:
  - Header (template name + record count)
  - Mini visualizations (sparklines per `chart_type: "line"` field, with
    hover tooltip; or stat strip per `chart_type: "stat_card"`)
  - Paginated 4-row table (date + 3 smart-picked columns)
  - `+ Agregar` → expands the card into `DynamicUploader` inline

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

### 3.8 Typography

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

| Command                    | Purpose                                                                 |
| -------------------------- | ----------------------------------------------------------------------- |
| `seed_pentacompartimental` | Create / overwrite the 5-component anthropometry template's schema.    |
| `seed_metas`               | Create `Metas <Department>` goals templates (per department or all).   |
| `seed_daily_notes`         | Create `Notas diarias <Department>` daily-notes templates.             |
| `seed_fake_exams`          | Generate fake historical results for every player × every template.    |

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
| **Bulk CSV / GPS import**                        | Out of MVP per PRD; placeholder. |
| **Cross-player comparative analytics**           | Out of MVP per PRD. |
| **Third-party integrations (Catapult, Wimu)**    | Out of MVP per PRD. |
| **Test suite**                                   | No tests exist yet. Highest-value first: `pytest` for `exams/calculations.py` (formula engine — security-critical) and `api/scoping.py` (access control — security-critical). Frontend `vitest` for `lib/api.ts` token handling. |

### 6.2 Tech debt / cleanup

Things that work today but should be tidied before they confuse the next contributor:

| Item                                               | Why                                                                                       |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Delete `frontend/src/components/visualizations/TrendsPanel.tsx` and its CSS | Superseded by per-template visualizations inside `DepartmentCard`. Currently dead code, but exported via `index.ts` and looks like an active component. |
| Rationalize `Sidebar.tsx` nav items                | Most entries (`Panel`, `Estadísticas`, `Desempeño`, `Médico`, `Psicosocial`, `Técnica`, `Tareas`, `Organización`) point to `#`. Either wire them up or delete; current state misleads. |
| Delete legacy `frontend/src/app/(dashboard)/nutricional/5c-v{1,2,3}/` pages | Pre-pivot static demos hardcoded in the original codebase. Replaced by the dynamic `Pentacompartimental` template; still reachable from the sidebar's `Nutricional` dropdown. |
| Decide on `frontend/src/app/(dashboard)/perfil/page.tsx` | Currently an empty-state stub pointing to `/equipo`. Either make it useful (e.g. redirect to last-viewed player) or remove the route + sidebar link. |
| Remove unused `ProfileStatistics`, `ProfilePerformance`, `ProfileMedical`, `ProfileNutritional` components | Original profile-tab-per-department components, no longer referenced after the dynamic-tabs refactor. |

---

## 7. Known caveats

- **`recorded_at` vs `fecha`** — the platform sorts results by their upload
  timestamp (`recorded_at`), which is set at submit time. If a doctor backfills
  yesterday's daily note, it sorts as "today" because that's when it was
  uploaded. The `fecha` field inside `result_data` is what the doctor *typed*.
  Easy fix when wanted (see TODO).
- **JSON has no comments** — `config_schema` written by hand in admin can't
  contain `// or /* */`. Strip them before pasting.
- **Templates lock on first result** — to change a schema after that, run the
  relevant seed command with `--unlock`, or unlock manually in admin. Note:
  this destroys the historical-data integrity guarantee until proper
  versioning ships.
- **Formula engine = Python AST**, not JavaScript:
  - Use `a if cond else b`, **not** `cond ? a : b`.
  - Variables use `[name]` brackets *or* bare identifiers.
  - Failed formulas store `null` for that field — the save still succeeds; the
    UI shows `—` for that calculated value so the gap is visible.
- **Body map / `chart_type: "body_map"`** renders a placeholder zone list, not
  a real anatomical figure.
- **Frontend forms have no edit / delete** for existing results. The audit
  trail is append-only by design (until edit-in-place ships — see §6.1).
- **I (the assistant) did not run the stack end-to-end** during the build
  session. If something blows up on first launch, suspect missing migrations
  (`makemigrations` then `migrate`) or stale browser tokens after schema
  changes (clear `localStorage` or click *Logout*).

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

Pick whatever delivers the most clinical value next; my recommended order:

1. **Sort by `fecha`** — small, polishes UX immediately.
2. **Logout UI + sidebar cleanup** — also small, removes confusion.
3. **Real `ProfileSummary`** — aggregates per-department highlights so the
   landing tab on each player profile is meaningful.
4. **Goal-vs-Current card** — joins the goals system with live data; high
   demo value.
5. **Test suite (formula engine + scoping)** — before more features stack
   on top. These two modules are security-critical.
6. **Bicompartimental + Tetracompartimental seed commands** — cheap once
   the schemas are written; rounds out the anthropometry suite.
7. **Player contract** — completes the `ProfileHeader` placeholder.
8. **Alarms engine + Celery + Notifications** — the biggest infra step;
   PRD-required for "automated intelligence". Notifications layer fits
   naturally on top.
9. **Template versioning** — needed before users actually start changing
   schemas in production.
10. **Real `BodyMap`** — clinical UX win for the medical team.

---

## 10. Useful commands cheat-sheet

```bash
# Bring everything up:
docker compose up --build

# Apply schema changes:
docker compose exec backend python manage.py makemigrations core exams
docker compose exec backend python manage.py migrate

# Wipe and reseed dev data:
docker compose down -v
docker compose up -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py seed_pentacompartimental \
    --create-if-missing --department-slug nutricional --all-applicable-categories
docker compose exec backend python manage.py seed_metas \
    --create-if-missing --all-applicable-categories
docker compose exec backend python manage.py seed_daily_notes \
    --create-if-missing --all-applicable-categories
docker compose exec backend python manage.py seed_fake_exams --reset

# Backend Python shell:
docker compose exec backend python manage.py shell

# Frontend lint:
docker compose exec frontend npm run lint

# Tail logs:
docker compose logs -f backend
docker compose logs -f frontend
```

---

*Last updated end of build session. When in doubt, read the file paths above —
the code is the source of truth.*
