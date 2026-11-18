FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# postgresql-client-18 (PGDG repo) for the daily backup (audit/backup.py):
# pg_dump must be at least the server's major version (prod runs 18).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev postgresql-common ca-certificates curl \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Collect static assets at build time so whitenoise can serve /static/
# in production (Django Admin CSS/JS, ninja docs, etc.). The image bakes
# the resulting `staticfiles/` directory in, so prod containers don't
# need to run collectstatic at startup. settings.py defaults cover
# every env var collectstatic reads, so this works without an .env.
RUN python manage.py collectstatic --no-input

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
