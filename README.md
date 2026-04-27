# SLAB

Dynamic, headless CMS for soccer team data management. See [`PROJECT.md`](./PROJECT.md) for the full vision and architecture.

## Repository layout

```
.
├── frontend/   # Next.js 16 App Router app (player profiles, dashboards)
├── backend/    # Django + Django Ninja API + PostgreSQL JSONB models
├── docker-compose.yml
└── PROJECT.md
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

## Notes

- `frontend/` uses Next.js 16, which has breaking changes from older versions. Refer to `frontend/node_modules/next/dist/docs/` before working on Next-specific APIs.
- Celery + Redis are wired into the compose file but not yet used; the alarm/formula evaluation engine will plug into them.
