#!/usr/bin/env bash
# One-shot bootstrap for the deployed backend container.
#
# Runs migrations, every seed command in dependency order, generates
# realistic historical exam results, and verifies the row counts at
# the end so you immediately know whether anything is missing.
#
# Usage (from inside the container — Railway shell, docker compose
# exec, etc.):
#
#     bash scripts/seed_all.sh
#
# Optional env-var overrides:
#
#     CLUB="Universidad de Chile"   # club to scope template seeds to
#     CATEGORY="Primer Equipo"      # category for layouts
#     RESET_RESULTS=1               # wipe + regenerate fake results
#     SKIP_MIGRATE=1                # skip the migrate step
#
# The script is intentionally tolerant: individual seed steps that
# fail print a warning but don't abort the run, so you always get a
# verification summary at the end.

set -u  # error on undefined vars; do NOT use -e — we want partial seeds to land

CLUB="${CLUB:-Universidad de Chile}"
CATEGORY="${CATEGORY:-Primer Equipo}"
RESET_RESULTS="${RESET_RESULTS:-1}"
SKIP_MIGRATE="${SKIP_MIGRATE:-0}"

cd "$(dirname "$0")/.."

bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m! %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$1"; }

run() {
    # run "<label>" python manage.py <command> [args...]
    local label="$1"; shift
    bold "→ ${label}"
    if "$@"; then
        ok "${label}"
    else
        warn "${label} failed (continuing)"
    fi
}

if [[ "$SKIP_MIGRATE" != "1" ]]; then
    run "migrate" python manage.py migrate --noinput
fi

# 1. Skeletons (clubs + departments + categories + positions)
run "seed_uchile_skeleton" python manage.py seed_uchile_skeleton
run "seed_slab_skeleton"   python manage.py seed_slab_skeleton

# 2. Roster
run "seed_uchile_2026" python manage.py seed_uchile_2026

# 3. Templates (every one scoped to --club to avoid cross-club writes)
TEMPLATE_FLAGS=(--create-if-missing --all-applicable-categories --club "$CLUB" --unlock)

run "seed_pentacompartimental" python manage.py seed_pentacompartimental \
    --department-slug nutricional "${TEMPLATE_FLAGS[@]}"

run "seed_lesiones" python manage.py seed_lesiones \
    --department-slug medico "${TEMPLATE_FLAGS[@]}"

run "seed_medicacion_template" python manage.py seed_medicacion_template \
    --department-slug medico "${TEMPLATE_FLAGS[@]}"

run "seed_medico_indicators" python manage.py seed_medico_indicators \
    --department-slug medico "${TEMPLATE_FLAGS[@]}"

run "seed_gps_match" python manage.py seed_gps_match \
    --department-slug fisico "${TEMPLATE_FLAGS[@]}"

run "seed_gps_training" python manage.py seed_gps_training \
    --department-slug fisico "${TEMPLATE_FLAGS[@]}"

run "seed_match_performance" python manage.py seed_match_performance \
    --department-slug tactico "${TEMPLATE_FLAGS[@]}"

# Daily-notes covers all departments — no --department-slug.
run "seed_daily_notes" python manage.py seed_daily_notes \
    --create-if-missing --all-applicable-categories --club "$CLUB" --unlock

# 4. Inline-row schema rebuild for the admin
run "sync_template_fields" python manage.py sync_template_fields --all

# 5. Historical exam results — the part that was missing.
FAKE_FLAGS=(--club "$CLUB")
if [[ "$RESET_RESULTS" == "1" ]]; then
    FAKE_FLAGS+=(--reset)
fi
run "seed_fake_exams" python manage.py seed_fake_exams "${FAKE_FLAGS[@]}"

# 6. Per-player + team-report layouts
run "seed_demo_layouts" python manage.py seed_demo_layouts \
    --club "$CLUB" --category "$CATEGORY"

# ---------------------------------------------------------------
# Verification — counts the rows seed_fake_exams should have created.
# If you see 0 results, the most common causes are:
#   - templates didn't seed (check earlier warnings above)
#   - the club name in CLUB doesn't match what's in the DB
#   - a template's schema changed and the generator skipped it
# ---------------------------------------------------------------
bold "→ verification"
python manage.py shell <<'PY'
from collections import Counter
from core.models import Player
from exams.models import ExamResult, ExamTemplate, Episode

players = Player.objects.count()
templates = ExamTemplate.objects.count()
results = ExamResult.objects.count()
episodes = Episode.objects.count()

print(f"  players:    {players}")
print(f"  templates:  {templates}")
print(f"  episodes:   {episodes}")
print(f"  results:    {results}")
print()
print("  results by template:")
counter = Counter(
    ExamResult.objects.values_list("template__slug", flat=True)
)
if not counter:
    print("    (none — seed_fake_exams produced no rows)")
else:
    for slug, n in sorted(counter.items(), key=lambda kv: -kv[1]):
        print(f"    {slug:30s} {n}")
PY

bold "✓ done"
