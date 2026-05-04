# SLAB — Railway deployment guide (client preview)

A step-by-step for getting a working URL on Railway with PostgreSQL +
Redis + AWS S3 + the four backend services we run in docker-compose
(`backend`, `worker`, `beat`, `frontend`). Targets a **client preview**
deployment: real database, real S3, console-backend email (alerts
print to worker logs), no SMTP needed.

If you outgrow Railway later, the env-var-driven config makes migration
to AWS (`STATUS.md` §9b) mostly DNS + a different deploy target.

---

## 0. Prerequisites

- A Railway account (railway.app, free tier OK to start).
- A GitHub repo for this codebase, pushed up. Railway pulls from GitHub.
- An AWS account for the S3 bucket + an IAM user.
- 30–60 minutes the first time.

---

## 1. Create the AWS S3 bucket + IAM user

1. **Create the bucket** in the AWS console → S3 → Create bucket.
   - Name: e.g. `slab-attachments-prod` (must be globally unique).
   - Region: pick something close to your users — `us-east-1` is the
     cheapest, `sa-east-1` is closest for Chile. Note the region; you'll
     paste it into Railway env later.
   - Block all public access: **leave ON**. Files are served via signed
     URLs only.
   - Versioning, encryption: defaults are fine.

2. **Create an IAM user** for SLAB to upload/download:
   - IAM → Users → Create user → name `slab-app`. No console access.
   - Attach policy → **Create policy** → JSON tab, paste:

     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Action": [
             "s3:GetObject",
             "s3:PutObject",
             "s3:DeleteObject",
             "s3:ListBucket"
           ],
           "Resource": [
             "arn:aws:s3:::slab-attachments-prod",
             "arn:aws:s3:::slab-attachments-prod/*"
           ]
         }
       ]
     }
     ```

     Replace `slab-attachments-prod` with your bucket name. Save it as
     `slab-s3-rw`.

3. **Generate access keys** for the user → Security credentials → Create
   access key → "Application running outside AWS" → confirm. Copy the
   **Access key ID** and **Secret access key** somewhere safe (you'll
   paste them into Railway shortly; AWS won't show the secret again).

4. **(Optional) CORS on the bucket** — only needed if you want the
   frontend to upload files directly to S3, which we don't (uploads go
   through the backend). You can skip this.

---

## 2. Push to GitHub

If the code isn't on GitHub yet:

```bash
git remote add origin git@github.com:<you>/slab-profiles.git
git push -u origin main
```

Railway watches the branch you select; every push triggers a redeploy
of the affected services. For a client preview, work on a stable
branch (e.g. `main`).

---

## 3. Create the Railway project

1. Sign in at <https://railway.app> → **New Project** → **Deploy from
   GitHub repo** → pick `slab-profiles`.
2. Railway will offer to auto-detect a service. Cancel the auto-detect
   for now — we'll create the four services manually so they share
   environment variables cleanly.

You'll end up with one Railway project containing six things:

```
slab-preview/
├── Postgres        (managed plugin)
├── Redis           (managed plugin)
├── backend         (Django; serves /api/ + /admin/)
├── worker          (Celery worker; same image as backend)
├── beat            (Celery beat; same image as backend)
└── frontend        (Next.js)
```

---

## 4. Add Postgres + Redis plugins

In the project view:

1. **+ New** → **Database** → **Add PostgreSQL**. Wait ~30s for it to
   provision. Note the service name (default: `Postgres`).
2. **+ New** → **Database** → **Add Redis**. Default name: `Redis`.

Railway exposes connection strings + individual variables on each
plugin. We'll reference them from the backend services using
`${{ Postgres.PGHOST }}` syntax (set up in step 6).

---

## 5. Add the `backend` service

1. **+ New** → **GitHub Repo** → pick the `slab-profiles` repo.
2. **Service settings → Root directory** → `backend/` (so Railway uses
   `backend/Dockerfile`).
3. **Service settings → Networking** → **Generate Domain** → you get
   something like `slab-backend-production-abcd.up.railway.app`. Copy
   this URL — you'll need it for CORS + the frontend's API URL.
4. Don't deploy yet — env vars first.

---

## 6. Configure backend env vars

In the `backend` service → **Variables** tab → **Raw editor** → paste:

```ini
# Django core
DEBUG=false
DJANGO_SECRET_KEY=                    # paste a long random string (50+ chars)
JWT_SECRET=                           # paste another long random string
DJANGO_ALLOWED_HOSTS=slab-backend-production-abcd.up.railway.app
CORS_ALLOWED_ORIGINS=https://slab-frontend-production-wxyz.up.railway.app
# Required when DEBUG=false — Django rejects /admin/ POST submissions with
# "CSRF verification failed" unless the request's Origin is listed here.
# Include both backend and frontend Railway URLs (HTTPS).
CSRF_TRUSTED_ORIGINS=https://slab-backend-production-abcd.up.railway.app,https://slab-frontend-production-wxyz.up.railway.app

# Postgres — referenced from the Postgres plugin
POSTGRES_HOST=${{ Postgres.PGHOST }}
POSTGRES_PORT=${{ Postgres.PGPORT }}
POSTGRES_DB=${{ Postgres.PGDATABASE }}
POSTGRES_USER=${{ Postgres.PGUSER }}
POSTGRES_PASSWORD=${{ Postgres.PGPASSWORD }}

# Celery — referenced from the Redis plugin
CELERY_BROKER_URL=${{ Redis.REDIS_URL }}
CELERY_RESULT_BACKEND=${{ Redis.REDIS_URL }}

# AWS S3 — replace with your real values from step 1
AWS_STORAGE_BUCKET_NAME=slab-attachments-prod
AWS_S3_REGION_NAME=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
# Leave AWS_S3_ENDPOINT_URL / AWS_S3_PUBLIC_ENDPOINT_URL /
# AWS_S3_ADDRESSING_STYLE / AWS_S3_URL_PROTOCOL UNSET — settings.py
# treats them as None and boto3 picks the canonical AWS endpoint.

# Email — console backend prints alerts to worker stdout; safe for demo.
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=alerts@example.com

# Used in alert email "Ver" links (still rendered into the message body
# even though emails go to stdout — useful when reading worker logs).
FRONTEND_BASE_URL=https://slab-frontend-production-wxyz.up.railway.app
```

Notes:
- Replace `slab-backend-production-abcd` and
  `slab-frontend-production-wxyz` with the actual generated URLs.
- `DJANGO_SECRET_KEY` and `JWT_SECRET` should be different long random
  strings. Generate via `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
- The settings.py code treats empty strings as None for the S3 endpoint
  vars, so it's fine to omit them entirely on Railway.

Hit **Deploy** on the backend service. Wait for the build to succeed.

---

## 7. Run the first migration + create a superuser

Railway has a one-shot command runner under each service.

1. Backend service → **Deployments** → latest deployment → **⋯** menu →
   **Open Shell** (or `railway run` from the CLI if you've installed it).
2. Run:

   ```bash
   python manage.py migrate
   python manage.py createsuperuser   # use a real email — login uses email
   ```

3. **(Optional) Seed demo data** — if the client expects to see something
   on first login:

   ```bash
   python manage.py seed_uchile_2026
   python manage.py seed_pentacompartimental \
       --create-if-missing --department-slug nutricional --all-applicable-categories
   python manage.py seed_lesiones \
       --create-if-missing --department-slug medico --all-applicable-categories
   python manage.py seed_medicacion_template \
       --create-if-missing --department-slug medico --all-applicable-categories \
       --club "Universidad de Chile"
   python manage.py seed_match_performance \
       --create-if-missing --department-slug tactico --all-applicable-categories
   python manage.py seed_gps_match \
       --create-if-missing --department-slug fisico --all-applicable-categories
   python manage.py seed_daily_notes \
       --create-if-missing --all-applicable-categories
   python manage.py sync_template_fields --all
   ```

   Adjust slugs to match the `Department` records you create in admin
   first (or pre-seed those via the Django Admin UI before running these).

---

## 8. Add the `worker` service (Celery)

1. **+ New** → **GitHub Repo** → same `slab-profiles` repo.
2. **Service settings → Root directory** → `backend/`.
3. **Service settings → Service Settings → Custom Start Command**:

   ```
   celery -A config worker --loglevel=info
   ```

4. **Variables** → click **Reference Service** → backend → **Reference all
   variables**. This shares every backend env var with the worker.
5. Deploy.

The worker doesn't need its own URL.

---

## 9. Add the `beat` service (Celery beat / scheduled jobs)

Same as the worker, but with start command:

```
celery -A config beat --loglevel=info
```

Reference all backend variables. Deploy.

This is what runs the daily goal evaluator + pre-deadline warnings at
05:00 UTC.

---

## 10. Add the `frontend` service (Next.js)

1. **+ New** → **GitHub Repo** → same repo.
2. **Service settings → Root directory** → `frontend/`.
3. **Service settings → Networking** → **Generate Domain** → e.g.
   `slab-frontend-production-wxyz.up.railway.app`.
4. **Variables** → set:

   ```ini
   NEXT_PUBLIC_API_URL=https://slab-backend-production-abcd.up.railway.app/api
   ```

   ⚠️ **`NEXT_PUBLIC_API_URL` must be set BEFORE the first build** —
   Next.js bakes `NEXT_PUBLIC_*` vars into the static bundle at build
   time. If you edit this var later, Railway will redeploy and pick up
   the new value, but the existing bundle won't update until the build
   completes.

5. **(Recommended) Build args**: in some Railway setups, env vars need
   to be marked as build-time. Look for a "Build" or "Variables → Build
   args" toggle and ensure `NEXT_PUBLIC_API_URL` is included.

6. Deploy.

---

## 11. Update CORS to point at the frontend URL

Once the frontend has its real domain, go back to the **backend** service
→ Variables → update:

```ini
CORS_ALLOWED_ORIGINS=https://slab-frontend-production-wxyz.up.railway.app
FRONTEND_BASE_URL=https://slab-frontend-production-wxyz.up.railway.app
```

Backend redeploys automatically. The frontend can now make authenticated
requests.

---

## 12. Verify

1. Visit `https://slab-frontend-production-wxyz.up.railway.app`.
2. Log in with the superuser email + password.
3. Check:
   - Equipo loads the roster.
   - Open a player → tabs render.
   - Try creating a Goal → save → an Alert appears in the navbar bell
     after the next daily tick (or fire one manually via the registrar
     to test the post-save signal path).
   - Upload a file attachment on a Lesiones entry → the file should
     persist in your S3 bucket (verify in the AWS console).

If something breaks, the **Logs** tab on each service is your friend.
Common issues:
- **Blank API page / CORS error** → `CORS_ALLOWED_ORIGINS` doesn't
  include the exact frontend domain (check protocol + port).
- **S3 access denied** → IAM policy bucket ARN typo, or the keys are
  for the wrong region.
- **`SignatureDoesNotMatch`** on file downloads → `AWS_S3_ENDPOINT_URL`
  was set; unset it (settings.py coerces empty to None which is what
  boto3 needs).
- **Frontend hits localhost:8000** → `NEXT_PUBLIC_API_URL` wasn't set
  before the build; update + redeploy frontend.

---

## 13. Custom domain (optional)

When you're ready to put the preview behind `app.s-lab.cl` or similar:

1. In Railway → frontend service → **Networking** → **Custom Domain** →
   add the domain. Railway shows you a CNAME target.
2. In your DNS provider (Cloudflare, Route 53, etc.) → CNAME from
   `app.s-lab.cl` → the Railway target.
3. Wait for DNS + cert propagation (usually <5 min).
4. Update `CORS_ALLOWED_ORIGINS`, `DJANGO_ALLOWED_HOSTS`, and
   `NEXT_PUBLIC_API_URL` to the new hostnames.

Same drill for `api.s-lab.cl` → backend service.

---

## 14. Cost note

Always-on: backend + worker + beat + frontend + Postgres + Redis ≈
**$25–35/month** at small instance sizes.

To cut cost on a low-traffic preview, enable **sleep on idle** for the
backend + frontend services in Railway settings — they spin down after
~5 min of no traffic and cold-start on the next request (~10 second
delay). Worker/beat should stay always-on (otherwise scheduled jobs
don't run).

---

## What this guide does NOT cover

- **HTTPS-quality static files**: Django runserver serves admin static
  files automatically, fine for a preview. For a long-lived prod
  deploy, add `whitenoise` to MIDDLEWARE + run `collectstatic` in
  the Dockerfile build step.
- **Real SMTP email**: when ready, set `EMAIL_BACKEND=django.core.mail.
  backends.smtp.EmailBackend` + the `EMAIL_HOST`/`EMAIL_HOST_USER`/
  `EMAIL_HOST_PASSWORD`/`EMAIL_USE_TLS` env vars on the worker (where
  the alert send task runs). SendGrid, Postmark, AWS SES all work.
- **Database backups**: Railway's Postgres plugin includes daily
  snapshots on paid plans; verify retention before treating as
  production-grade.
- **Migration to AWS** (EC2 + RDS + S3, Path 1 in `STATUS.md` §9b): if
  the client signs off and you want VPC isolation or AWS-native cost
  control, the env-var driven config means migration is mostly DNS +
  re-pointing the database. Follow `STATUS.md` §9b when the time comes.
