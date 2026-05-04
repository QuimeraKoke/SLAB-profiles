# SLAB

Dynamic, headless CMS for soccer team data management. See [`PROJECT.md`](./PROJECT.md) for the full vision and architecture, [`STATUS.md`](./STATUS.md) for what's actually been built, and [`DASHBOARDS.md`](./DASHBOARDS.md) for the operator's guide to dashboards.

## Repository layout

```
.
├── frontend/   # Next.js 16 App Router (player profiles, partidos, eventos, reportes, configuraciones)
├── backend/    # Django + Django Ninja API + PostgreSQL JSONB models
│   ├── core/        # Club, Department, Category, Position, Player, PlayerAlias, StaffMembership
│   ├── exams/       # ExamTemplate, TemplateField, ExamResult, Episode, calculations, bulk_ingest, signals
│   ├── events/      # Event (calendar + match metadata)
│   ├── goals/       # Goal, Alert, AlertRule + evaluator + Celery tasks (email + warnings)
│   ├── dashboards/  # PER-PLAYER + TEAM REPORT layouts, widgets, aggregation engines
│   ├── attachments/ # Polymorphic Attachment model (S3/MinIO storage)
│   └── api/         # Ninja routers, schemas, JWT auth, scoping
├── docker-compose.yml
├── PROJECT.md          # Vision + architecture
├── STATUS.md           # Implementation snapshot (read this before changes)
├── DASHBOARDS.md       # Dashboard authoring guide
└── RAILWAY_DEPLOY.md   # Step-by-step Railway deployment for client preview
```

## Local development

Prerequisites: Docker + Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Services:

| Service  | URL                         |
| -------- | --------------------------- |
| Frontend | http://localhost:3000       |
| API      | http://localhost:8000/api   |
| Admin    | http://localhost:8000/admin |
| Postgres | localhost:5432              |
| Redis    | localhost:6379              |

### First-time backend setup

After the stack is up:

```bash
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

### Seeding demo data

For a one-command demo bootstrap:

```bash
docker compose exec backend python manage.py seed_demo
```

This runs the full pipeline against `Universidad de Chile / Primer
Equipo`:
1. Roster (30 players + positions + aliases)
2. Templates: Pentacompartimental, Lesiones, Medicación (with WADA
   alerts), GPS Partido, GPS Entrenamiento, Rendimiento de partido,
   daily-notes per department
3. `sync_template_fields --all` (admin inline rows)
4. `seed_fake_exams` (skip via `--skip-fake-exams`, wipe via
   `--reset-fake-exams`)
5. Per-player + team-report layouts for **all 4 demo departments**
   (Médico / Físico / Táctico / Nutricional)

Pass `--club <name>` and `--category <name>` to scope to a different
team.

To run individual seeds (e.g. when adding a new template later):

```bash
docker compose exec backend python manage.py seed_pentacompartimental \
    --create-if-missing --department-slug nutricional --all-applicable-categories
docker compose exec backend python manage.py seed_lesiones \
    --create-if-missing --department-slug medico --all-applicable-categories
docker compose exec backend python manage.py seed_medicacion_template \
    --create-if-missing --department-slug medico --all-applicable-categories \
    --club "Universidad de Chile"
docker compose exec backend python manage.py seed_gps_match \
    --create-if-missing --department-slug fisico --all-applicable-categories
docker compose exec backend python manage.py seed_gps_training \
    --create-if-missing --department-slug fisico --all-applicable-categories \
    --club "Universidad de Chile"
docker compose exec backend python manage.py seed_match_performance \
    --create-if-missing --department-slug tactico --all-applicable-categories
docker compose exec backend python manage.py seed_demo_layouts
docker compose exec backend python manage.py sync_template_fields --all
```

### Useful commands

```bash
# Backend shell
docker compose exec backend python manage.py shell

# Frontend lint
docker compose exec frontend npm run lint

# Stop everything
docker compose down

# Reset the database (destroys data)
docker compose down -v
```

## Key features at a glance

- **Configurable exams** — JSONB `config_schema` per template; admins author
  via Django Admin's `TemplateField` inline (no JSON typing). Cascading
  group → option dropdowns via `option_groups` for long lists like
  medicines.
- **Calculated fields** — safe AST formula engine with `coalesce()` for
  null-tolerant sums; cross-template references via dot notation
  (`<slug>.<field_key>`).
- **Multiple input modes per template** — single (auto-generated form),
  bulk_ingest (XLSX upload + preview + commit), team_table (roster-style
  bulk entry; supports event linking) — driven by `input_config`.
- **Episodic templates** — Lesiones (injuries), with stage progression,
  auto-derived `Player.status`, body-map heatmap widget, and a dedicated
  Lesiones tab filtered to `template_slug=lesiones`.
- **Goals & Alerts** — per-player Goal model with daily Celery evaluator,
  pre-deadline warnings, threshold-based AlertRule, email dispatch (via
  Celery worker + StaffMembership scoping), navbar bell with live polling
  + drillable dropdown.
- **WADA medication tracking** — Medicación template loaded from CSV (61
  meds, 19 categorías, 17 WADA-flagged); auto-fires PROHIBIDO=critical /
  CONDICIONAL=warning alerts on save via a config-driven signal.
- **Calendar events** — match scheduling with metadata; `ExamResult.event`
  FK links data captures to matches. Per-player Eventos tab with full
  CRUD.
- **Matches manager** at `/partidos` — calendar view + table + create/edit
  /delete + bulk per-roster performance entry on the editor.
- **Configurable dashboards** — per-(department, category) layouts of
  reusable chart widgets. Two parallel systems:
  - **Per-player** at `/perfil/[id]?tab=<dept>` — line, table, donut,
    grouped bar, multi-line, body-map heatmap.
  - **Team reports** at `/reportes/[deptSlug]` — horizontal comparison,
    roster matrix, squad availability, trend line, distribution
    histogram, active records (date-range).
- **Player CRUD** at `/configuraciones/jugadores` — admin surface for
  roster management, with active/inactive toggle and full personal-info
  edit.
- **Responsive** — sidebar slides into a drawer on tablet/mobile; widget
  grid scales 12→6→12 columns by viewport.
- **Global category context** — picker in the navbar drives equipo,
  partidos, and reportes; persists across navigation.

## Notes

- `frontend/` uses Next.js 16, which has breaking changes from older versions. Refer to `frontend/node_modules/next/dist/docs/` before working on Next-specific APIs.
- Celery + Redis power the goals evaluator (daily tick), alert email
  dispatch (per-creation), and the threshold-rule evaluator. Worker +
  beat services are in `docker-compose.yml`.
- Django's interactive API docs at <http://localhost:8000/api/docs>.
- Backend tests: `docker compose exec backend python manage.py test
  goals exams dashboards` (145 tests at last count).
