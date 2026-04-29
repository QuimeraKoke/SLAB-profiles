# SLAB

Dynamic, headless CMS for soccer team data management. See [`PROJECT.md`](./PROJECT.md) for the full vision and architecture, [`STATUS.md`](./STATUS.md) for what's actually been built, and [`DASHBOARDS.md`](./DASHBOARDS.md) for the operator's guide to dashboards.

## Repository layout

```
.
├── frontend/   # Next.js 16 App Router app (player profiles, partidos, eventos)
├── backend/    # Django + Django Ninja API + PostgreSQL JSONB models
│   ├── core/        # Club, Department, Category, Position, Player, PlayerAlias, StaffMembership
│   ├── exams/       # ExamTemplate, TemplateField, ExamResult, calculations, bulk_ingest
│   ├── events/      # Event (calendar + match metadata)
│   ├── dashboards/  # DepartmentLayout, Widget, WidgetDataSource
│   └── api/         # Ninja routers, schemas, JWT auth, scoping
├── docker-compose.yml
├── PROJECT.md       # Vision + architecture
├── STATUS.md        # Implementation snapshot
└── DASHBOARDS.md    # Dashboard authoring guide
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

```bash
# Universidad de Chile 2026 roster + 14 GPS aliases for the sample export
docker compose exec backend python manage.py seed_uchile_2026

# Exam templates (each writes config_schema JSON):
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

# After seeding, rebuild TemplateField rows so templates become inline-editable in admin:
docker compose exec backend python manage.py sync_template_fields --all

# Optional: fake history + the default Nutricional dashboard layout
docker compose exec backend python manage.py seed_fake_exams --reset
docker compose exec backend python manage.py seed_nutricional_layout \
    --all-applicable-categories
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
  via Django Admin's `TemplateField` inline (no JSON typing).
- **Calculated fields** — safe AST formula engine with `coalesce()` for
  null-tolerant sums.
- **Multiple input modes per template** — single (auto-generated form),
  bulk_ingest (XLSX upload + preview + commit) — driven by `input_config`.
- **Player matching** — `PlayerAlias` (kind: nickname / squad_number /
  external_id) for matching uploaded files against the roster.
- **Calendar events** — match scheduling with metadata (opponent, score,
  competition); `ExamResult.event` FK links data captures to matches.
- **Matches manager** at `/partidos` — calendar view (default) + table view
  + create/edit/delete forms. Nested under sidebar **Configuraciones**.
- **Per-player events** — Eventos tab on player profile with three scopes
  (individual / category / custom subset with search picker).
- **Match performance** — `Rendimiento de partido` template in Táctico,
  results FK-linked to matches; `MatchHistoryTable` widget on the Táctico
  tab shows per-match performance with totals + W/D/L pills.
- **Configurable dashboards** — per-(department, category) layouts of
  reusable chart widgets (line, table, donut, grouped bar, etc.).

## Notes

- `frontend/` uses Next.js 16, which has breaking changes from older versions. Refer to `frontend/node_modules/next/dist/docs/` before working on Next-specific APIs.
- Celery + Redis are wired into the compose file but not yet used; the alarm/threshold engine will plug into them (see `STATUS.md` §6).
- Django's interactive API docs at <http://localhost:8000/api/docs>.
