#!/usr/bin/env bash
# One-shot cutover: push the local SLAB database to a Railway Postgres.
#
# Flow (Option B from the design pitch):
#   1. Read DATABASE_URL from `.env.railway` (or shell env).
#   2. Run Django migrations against Railway so the schema + django_migrations
#      table are owned by the Django source-of-truth, not the dump.
#   3. Truncate every user-table on Railway (keep django_migrations).
#   4. Dump data-only from local Postgres.
#   5. Pipe the dump into Railway.
#   6. Spot-check row counts on both sides.
#
# Pre-requisites:
#   - Local Docker stack running (postgres + backend services up).
#   - `.env.railway` at the project root containing:
#         DATABASE_URL=postgres://user:pass@host:port/db
#   - Outbound network access from your laptop to Railway (Railway DBs
#     accept public TLS connections; the postgres container handles SSL
#     via PGSSLMODE=require below).
#
# Safety:
#   - Step 3 wipes Railway data — the script forces an interactive
#     "overwrite" confirmation. Use `--yes` to skip when scripting.
#   - The dump file lands in backend/backups/ so you can replay if needed.
#
# Run from the project root:
#   bash backend/scripts/push_to_railway.sh
#   bash backend/scripts/push_to_railway.sh --yes        # non-interactive
#   bash backend/scripts/push_to_railway.sh --skip-migrate  # if you've already migrated

set -eu

# ----- locate paths ---------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_DIR="$REPO_ROOT/backend/backups"
mkdir -p "$BACKUP_DIR"

# ----- flags ----------------------------------------------------------
AUTO_CONFIRM=0
SKIP_MIGRATE=0
SKIP_TRUNCATE=0
for arg in "$@"; do
    case "$arg" in
        --yes)            AUTO_CONFIRM=1 ;;
        --skip-migrate)   SKIP_MIGRATE=1 ;;
        --skip-truncate)  SKIP_TRUNCATE=1 ;;
        -h|--help)
            sed -n '2,/^set -eu$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

# ----- 1) load DATABASE_URL -------------------------------------------
if [[ -f "$REPO_ROOT/.env.railway" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env.railway"
    set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
    cat >&2 <<EOF
ERROR: DATABASE_URL is not set.

Either export it in your shell, or create a .env.railway file at the
project root with a single line:

    DATABASE_URL=postgres://user:pass@host:port/db

You can copy the value from the Railway dashboard → Postgres service →
Variables → DATABASE_URL.
EOF
    exit 2
fi

# ----- 2) parse DATABASE_URL into discrete components -----------------
# Expected shape: postgres://USER:PASS@HOST:PORT/DB[?query]
proto_stripped="${DATABASE_URL#*://}"
userpass="${proto_stripped%@*}"
hostportdb="${proto_stripped#*@}"
PG_USER="${userpass%%:*}"
PG_PASS="${userpass#*:}"
hostport="${hostportdb%%/*}"
dbraw="${hostportdb#*/}"
PG_DB="${dbraw%%\?*}"
PG_HOST="${hostport%%:*}"
PG_PORT="${hostport##*:}"
[[ "$PG_HOST" == "$PG_PORT" ]] && PG_PORT=5432

if [[ -z "$PG_HOST" || -z "$PG_DB" || -z "$PG_USER" ]]; then
    echo "ERROR: couldn't parse DATABASE_URL — check format" >&2
    exit 2
fi

# ----- 3) confirm destructive operation -------------------------------
echo ""
echo "================================================================"
echo "  Pushing local SLAB → Railway"
echo "================================================================"
echo "  Target host:  $PG_HOST:$PG_PORT"
echo "  Target db:    $PG_DB"
echo "  Target user:  $PG_USER"
echo ""
echo "This will OVERWRITE every user table on the Railway database."
echo "django_migrations will be preserved (Django owns the schema)."
echo ""
if [[ "$AUTO_CONFIRM" != "1" ]]; then
    read -r -p "Type 'overwrite' to continue: " confirm
    if [[ "$confirm" != "overwrite" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# ----- helpers --------------------------------------------------------
# Run a psql command against Railway from the local postgres container.
# Using the container's psql avoids needing libpq installed on the host.
railway_psql() {
    docker compose exec -T \
        -e PGPASSWORD="$PG_PASS" \
        -e PGSSLMODE=require \
        postgres psql \
            -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
            -v ON_ERROR_STOP=1 "$@"
}

# Run Django manage.py against Railway by overriding the POSTGRES_* env
# vars on the backend container. Django settings read these directly,
# so no settings change is needed.
django_railway() {
    docker compose exec -T \
        -e POSTGRES_HOST="$PG_HOST" \
        -e POSTGRES_PORT="$PG_PORT" \
        -e POSTGRES_USER="$PG_USER" \
        -e POSTGRES_PASSWORD="$PG_PASS" \
        -e POSTGRES_DB="$PG_DB" \
        -e PGSSLMODE=require \
        backend python manage.py "$@"
}

# ----- 4) verify connectivity ----------------------------------------
echo ""
echo "→ Checking Railway connectivity..."
RAILWAY_VER=$(railway_psql -tA -c "SHOW server_version;" | tr -d '[:space:]')
echo "  Railway Postgres version: $RAILWAY_VER"

LOCAL_VER=$(docker compose exec -T postgres psql -U slab -d slab -tA -c "SHOW server_version;" | tr -d '[:space:]')
echo "  Local Postgres version:   $LOCAL_VER"

# Compare major versions only (e.g. "16.2" vs "16.0" is fine; "14" vs "16" is not).
RAILWAY_MAJOR="${RAILWAY_VER%%.*}"
LOCAL_MAJOR="${LOCAL_VER%%.*}"
if [[ "$RAILWAY_MAJOR" != "$LOCAL_MAJOR" ]]; then
    echo ""
    echo "WARNING: Postgres major versions differ ($LOCAL_MAJOR vs $RAILWAY_MAJOR)."
    echo "Restore may fail. Bump the Railway service to Postgres $LOCAL_MAJOR first."
    if [[ "$AUTO_CONFIRM" != "1" ]]; then
        read -r -p "Continue anyway? [y/N] " yn
        [[ "$yn" =~ ^[Yy] ]] || exit 1
    fi
fi

# ----- 5) apply Django migrations on Railway --------------------------
if [[ "$SKIP_MIGRATE" == "1" ]]; then
    echo ""
    echo "→ Skipping Django migrations (--skip-migrate)."
else
    echo ""
    echo "→ Applying Django migrations on Railway..."
    django_railway migrate --no-input
fi

# ----- 6) truncate Railway user tables --------------------------------
if [[ "$SKIP_TRUNCATE" == "1" ]]; then
    echo ""
    echo "→ Skipping Railway truncate (--skip-truncate)."
else
    echo ""
    echo "→ Truncating Railway tables (keeping django_migrations)..."
    railway_psql <<'SQL'
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
         WHERE schemaname = 'public'
           AND tablename != 'django_migrations'
    LOOP
        EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename)
                || ' RESTART IDENTITY CASCADE';
    END LOOP;
END $$;
SQL
fi

# ----- 7) dump local data -------------------------------------------
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
DUMP_FILE="$BACKUP_DIR/railway-push-$TIMESTAMP.sql.gz"

echo ""
echo "→ Dumping local data (data-only)..."
docker compose exec -T postgres pg_dump \
    -U slab -d slab \
    --data-only \
    --disable-triggers \
    --no-owner \
    --no-privileges \
    --exclude-table=django_migrations \
    | gzip > "$DUMP_FILE"
DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
echo "  Wrote: $DUMP_FILE ($DUMP_SIZE)"

# ----- 8) restore into Railway --------------------------------------
echo ""
echo "→ Loading data into Railway..."
gunzip -c "$DUMP_FILE" | railway_psql

# ----- 9) sanity check row counts -----------------------------------
echo ""
echo "→ Comparing row counts (sample)..."
SAMPLE_TABLES=(
    core_club
    core_category
    core_player
    core_staffmembership
    events_event
    events_eventparticipant
    exams_examtemplate
    exams_examresult
    exams_episode
)
mismatch=0
for tbl in "${SAMPLE_TABLES[@]}"; do
    L=$(docker compose exec -T postgres psql -U slab -d slab -tA \
        -c "SELECT count(*) FROM $tbl" 2>/dev/null || echo "n/a")
    R=$(railway_psql -tA -c "SELECT count(*) FROM $tbl" 2>/dev/null | tr -d '[:space:]')
    if [[ "$L" == "$R" ]]; then
        printf "  %-30s local=%-8s railway=%-8s ✓\n" "$tbl" "$L" "$R"
    else
        printf "  %-30s local=%-8s railway=%-8s ✗\n" "$tbl" "$L" "$R"
        mismatch=1
    fi
done

echo ""
if [[ "$mismatch" == "1" ]]; then
    echo "WARNING: row counts differ on at least one table."
    echo "         Inspect $DUMP_FILE and re-run with --skip-migrate to retry."
    exit 1
fi

echo "Done. Local snapshot kept at: $DUMP_FILE"
echo ""
echo "Next steps:"
echo "  - Set the rest of the Railway env vars (DJANGO_SECRET_KEY, etc.)."
echo "  - Sync MinIO files separately (exam attachments + player photos)."
echo "  - Deploy the Django app on Railway and point it at this DB."
