#!/usr/bin/env bash
# Snapshot / restore the SLAB Postgres database.
#
# Designed for the pre-migration safety net — take a snapshot before
# running `migrate_legacy.sh run`, restore it if anything looks wrong.
#
# Usage (from the project root):
#
#     bash scripts/backup_slab_db.sh backup                     # take a fresh snapshot
#     bash scripts/backup_slab_db.sh backup --tag pre-migration # custom label in filename
#     bash scripts/backup_slab_db.sh list                       # show available snapshots
#     bash scripts/backup_slab_db.sh restore <file>             # restore from a snapshot
#
# Snapshots land in `backend/backups/slab-<timestamp>[-<tag>].sql.gz`.
#
# NOTE: This only covers the Postgres data. File attachments (S3 / MinIO)
# are stored separately — back those up via `mc mirror` if you care
# about them. For the typical "migration broke something, roll back the
# schema + table contents" scenario, the dump alone is enough.

set -eu

# ----- locate where we are --------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/../backups"
mkdir -p "$BACKUP_DIR"

# Resolve Postgres params from docker-compose env (with sane defaults).
POSTGRES_DB="${POSTGRES_DB:-slab}"
POSTGRES_USER="${POSTGRES_USER:-slab}"

ACTION="${1:-}"

usage() {
    cat >&2 <<EOF
Usage: bash scripts/backup_slab_db.sh <action> [args]

Actions:
  backup [--tag LABEL]   Take a fresh snapshot. Saves to:
                         backend/backups/slab-YYYYMMDDTHHMMSS[-LABEL].sql.gz
  list                   Show all snapshots, newest first.
  restore <file>         Wipe the current DB and restore from <file>.
                         WARNING: destroys all current SLAB data.

Env overrides:
  POSTGRES_DB     (default: slab)
  POSTGRES_USER   (default: slab)
EOF
    exit 2
}

# ----- helpers --------------------------------------------------------
backup() {
    local tag=""
    if [[ "${1:-}" == "--tag" && -n "${2:-}" ]]; then
        tag="-${2//[^A-Za-z0-9_-]/-}"   # sanitize: only [A-Za-z0-9_-]
    fi
    local ts
    ts="$(date +%Y%m%dT%H%M%S)"
    local out="$BACKUP_DIR/slab-${ts}${tag}.sql.gz"

    echo "Snapshot target: $out"
    echo "  database: $POSTGRES_DB · user: $POSTGRES_USER"
    echo "Dumping..."

    # pg_dump from inside the postgres container, gzip on the host so we
    # don't depend on the container having gzip in PATH.
    docker compose exec -T postgres \
        pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --no-owner --no-privileges --clean --if-exists \
        | gzip > "$out"

    local size
    size="$(du -h "$out" | cut -f1)"
    echo ""
    echo "✓ Snapshot ready: $out ($size)"
    echo ""
    echo "To restore later:"
    echo "    bash scripts/backup_slab_db.sh restore $out"
}

list_snapshots() {
    if ! ls "$BACKUP_DIR"/slab-*.sql.gz >/dev/null 2>&1; then
        echo "No snapshots in $BACKUP_DIR"
        return
    fi
    echo "Snapshots in $BACKUP_DIR (newest first):"
    # macOS `ls` doesn't have --time-style; use `stat`-friendly listing.
    ls -lhrt "$BACKUP_DIR"/slab-*.sql.gz | awk '{print "  " $9 "   " $5 "   " $6, $7, $8}'
}

restore() {
    local file="${1:-}"
    if [[ -z "$file" ]]; then
        echo "ERROR: restore needs a snapshot path." >&2
        usage
    fi
    if [[ ! -f "$file" ]]; then
        echo "ERROR: snapshot file not found: $file" >&2
        exit 2
    fi

    echo "================================================================"
    echo "  ⚠️  DESTRUCTIVE RESTORE ABOUT TO RUN"
    echo "================================================================"
    echo "  Target DB: $POSTGRES_DB (user $POSTGRES_USER)"
    echo "  Source:    $file"
    echo ""
    echo "This will WIPE the current SLAB database and restore the snapshot."
    echo "Type 'restore' to confirm, anything else to abort:"
    read -r confirmation
    if [[ "$confirmation" != "restore" ]]; then
        echo "Aborted."
        exit 1
    fi

    echo "Restoring..."
    # The dump uses --clean --if-exists, so it drops existing objects
    # before recreating. We feed the gzipped dump into psql via stdin.
    gunzip -c "$file" | docker compose exec -T postgres \
        psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" --quiet \
        --set ON_ERROR_STOP=on \
        > /tmp/slab_restore.log 2>&1 \
        && echo "✓ Restore complete." \
        || { echo "✗ Restore failed — see /tmp/slab_restore.log"; tail -20 /tmp/slab_restore.log; exit 1; }
}

# ----- dispatch --------------------------------------------------------
case "$ACTION" in
    backup)
        shift
        backup "$@"
        ;;
    list)
        list_snapshots
        ;;
    restore)
        shift
        restore "$@"
        ;;
    "" | -h | --help)
        usage
        ;;
    *)
        echo "Unknown action: $ACTION" >&2
        usage
        ;;
esac
