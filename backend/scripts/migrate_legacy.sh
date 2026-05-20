#!/usr/bin/env bash
# Wrapper for `manage.py migrate_legacy_data` with safer-by-default
# defaults + the recommended cutover workflow baked in.
#
# Usage (from inside the backend container OR from the host —
# autodetects):
#
#     bash scripts/migrate_legacy.sh dry-run    # plan only, no writes
#     bash scripts/migrate_legacy.sh smoke      # tiny real run (--limit=5)
#     bash scripts/migrate_legacy.sh run        # full real migration
#     bash scripts/migrate_legacy.sh phase 0    # only phase0 (real run)
#     bash scripts/migrate_legacy.sh phase 0 dry # only phase0, dry-run
#
# Required:
#     LEGACY_DB_PASSWORD      Read-only legacy DB password.
#
# Optional env overrides:
#     CLUB="Universidad de Chile"    Destination SLAB club
#     DATE_FROM="2025-01-01"         Scope start (inclusive)
#     DATE_TO="2026-12-31"           Scope end   (inclusive)
#     LIMIT=N                        Per-phase row cap (smoke mode default 5)
#     LEGACY_HOST="192.168.1.24"
#     LEGACY_PORT=5432
#     LEGACY_DB="uchile"
#     LEGACY_USER="slab_migration_ro"

set -u  # error on undefined vars; not -e — we want to print summary even on partial fail

# ----- defaults --------------------------------------------------------
CLUB="${CLUB:-Universidad de Chile}"
DATE_FROM="${DATE_FROM:-2025-01-01}"
DATE_TO="${DATE_TO:-2026-12-31}"
LIMIT="${LIMIT:-}"
LEGACY_HOST="${LEGACY_HOST:-192.168.1.24}"
LEGACY_PORT="${LEGACY_PORT:-5432}"
LEGACY_DB="${LEGACY_DB:-uchile}"
LEGACY_USER="${LEGACY_USER:-slab_migration_ro}"

MODE="${1:-}"
PHASE_ARG="${2:-}"
PHASE_MODE="${3:-real}"

# ----- pre-flight ------------------------------------------------------
# Show usage first if no mode given — easier to discover the script.
if [[ -z "$MODE" ]]; then
    cat >&2 <<EOF
Usage: bash scripts/migrate_legacy.sh <mode> [args]

Modes:
  dry-run             Plan + log everything, no writes. Safe to run anytime.
  smoke               Real run with --limit=5 (or \$LIMIT). For first verification.
  run                 Full real migration. ~19,500 rows, takes 5-15 min.
  phase <N> [dry]     Only run phaseN. Add 'dry' as the 3rd arg for a dry-run.

Audit logs land in migration_runs/run-YYYYMMDDTHHMM[-DRY].jsonl.
Required env: LEGACY_DB_PASSWORD
EOF
    exit 2
fi

if [[ -z "${LEGACY_DB_PASSWORD:-}" ]]; then
    echo "ERROR: LEGACY_DB_PASSWORD env var is not set."                  >&2
    echo "       Export the read-only password before running this:"     >&2
    echo "         export LEGACY_DB_PASSWORD='...'"                       >&2
    echo "         bash scripts/migrate_legacy.sh $MODE"                  >&2
    exit 2
fi

# ----- inside-container vs host autodetect -----------------------------
# When run from the host, transparently `docker compose exec` into the
# backend container; when run from inside the container, exec directly.
if [[ -f /app/manage.py ]]; then
    RUNNER=(python /app/manage.py)
else
    if ! command -v docker >/dev/null 2>&1; then
        echo "ERROR: docker CLI not found, and we're not in the container." >&2
        exit 2
    fi
    RUNNER=(docker compose exec -T \
        -e "LEGACY_DB_PASSWORD=$LEGACY_DB_PASSWORD" \
        backend python manage.py)
fi

# ----- common flags ----------------------------------------------------
COMMON_ARGS=(
    --club "$CLUB"
    --date-from "$DATE_FROM"
    --date-to "$DATE_TO"
    --legacy-host "$LEGACY_HOST"
    --legacy-port "$LEGACY_PORT"
    --legacy-db "$LEGACY_DB"
    --legacy-user "$LEGACY_USER"
)

print_header() {
    echo ""
    echo "================================================================"
    echo "  $*"
    echo "================================================================"
    echo "  club:     $CLUB"
    echo "  scope:    $DATE_FROM → $DATE_TO"
    echo "  legacy:   $LEGACY_USER@$LEGACY_HOST:$LEGACY_PORT/$LEGACY_DB"
    echo ""
}

# ----- mode dispatch ---------------------------------------------------
case "$MODE" in
    dry-run|dry)
        print_header "DRY RUN — no writes, full scope"
        "${RUNNER[@]}" migrate_legacy_data --dry-run "${COMMON_ARGS[@]}"
        ;;

    smoke)
        # Default smoke limit = 5 rows per phase.
        LIMIT="${LIMIT:-5}"
        print_header "SMOKE TEST — REAL writes, --limit=$LIMIT"
        echo "This WILL write to the SLAB database. Limited to $LIMIT rows per phase."
        echo "Press Ctrl-C within 5 seconds to abort..."
        sleep 5
        "${RUNNER[@]}" migrate_legacy_data --limit "$LIMIT" "${COMMON_ARGS[@]}"
        ;;

    run)
        print_header "FULL MIGRATION — REAL writes, full scope"
        echo "This WILL write ~19,500 rows to the SLAB database."
        echo "Estimated runtime: 5-15 minutes."
        echo "Press Ctrl-C within 10 seconds to abort..."
        sleep 10
        EXTRA=()
        if [[ -n "$LIMIT" ]]; then
            EXTRA+=(--limit "$LIMIT")
        fi
        # ${ARR[@]+"${ARR[@]}"} expands to nothing when ARR is empty —
        # portable workaround for `set -u` failing on empty arrays.
        "${RUNNER[@]}" migrate_legacy_data "${COMMON_ARGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"}
        ;;

    phase)
        if [[ -z "$PHASE_ARG" ]]; then
            echo "ERROR: 'phase' mode requires a phase number (0-6)." >&2
            echo "       Example: bash scripts/migrate_legacy.sh phase 0 dry" >&2
            exit 2
        fi
        ENTITY="phase${PHASE_ARG}"
        EXTRA=(--entities "$ENTITY")
        if [[ "$PHASE_MODE" == "dry" ]]; then
            EXTRA+=(--dry-run)
            print_header "PHASE $PHASE_ARG (DRY RUN)"
        else
            print_header "PHASE $PHASE_ARG (REAL writes)"
            echo "Press Ctrl-C within 3 seconds to abort..."
            sleep 3
        fi
        if [[ -n "$LIMIT" ]]; then
            EXTRA+=(--limit "$LIMIT")
        fi
        "${RUNNER[@]}" migrate_legacy_data "${COMMON_ARGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"}
        ;;

    *)
        echo "ERROR: unknown mode '$MODE'. Run with no args to see usage." >&2
        exit 2
        ;;
esac
