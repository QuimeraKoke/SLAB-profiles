#!/usr/bin/env bash
#
# Apply all SLAB seed data in the correct order.
#
# Usage:
#   ./seed-all.sh              # idempotent: keeps existing exam results
#   ./seed-all.sh --reset      # wipes existing ExamResult rows before seeding fakes
#
# Prereqs:
#   - docker compose stack is up (postgres, backend)
#   - migrations applied (the backend Dockerfile CMD does this on boot)
#   - a Django superuser exists if you want to log in to the frontend
#

set -euo pipefail

RESET_FAKES=""
for arg in "$@"; do
  case "$arg" in
    --reset) RESET_FAKES="--reset" ;;
    -h|--help)
      sed -n '2,11p' "$0"
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")"

if ! docker compose ps backend --status running --quiet | grep -q .; then
  echo "ERROR: backend container is not running. Start it with: docker compose up -d" >&2
  exit 1
fi

run() {
  echo
  echo ">>> $*"
  docker compose exec -T backend python manage.py "$@"
}

echo "=== 0/5  Bootstrap club / departments / category ==="
echo ">>> ensure Universidad de Chile + 5 departments + Primer Equipo (idempotent)"
docker compose exec -T backend python manage.py shell <<'PYEOF'
from core.models import Club, Department, Category

club, _ = Club.objects.get_or_create(name="Universidad de Chile")

DEPTS = [
    ("Médico",       "medico"),
    ("Físico",       "fisico"),
    ("Nutricional",  "nutricional"),
    ("Psicosocial",  "psicosocial"),
    ("Táctico",      "tactico"),
]
dept_objs = []
for name, slug in DEPTS:
    d, _ = Department.objects.get_or_create(club=club, slug=slug, defaults={"name": name})
    dept_objs.append(d)

category, _ = Category.objects.get_or_create(club=club, name="Primer Equipo")
category.departments.add(*dept_objs)

print(f"Club: {club.name} | Departments: {[d.slug for d in dept_objs]} | Category: {category.name}")
PYEOF

echo
echo "=== 1/5  Roster + GPS aliases ==="
run seed_uchile_2026

echo
echo "=== 2/5 Exam templates ==="
run seed_pentacompartimental --create-if-missing \
  --department-slug nutricional --all-applicable-categories
# `seed_metas` removed: structured goals are now first-class via the Goal
# model (§3.15 in STATUS.md). Narrative notes still live in `Notas diarias`.
run seed_daily_notes --create-if-missing --all-applicable-categories
run seed_gps_match --create-if-missing \
  --department-slug fisico --all-applicable-categories
run seed_match_performance --create-if-missing \
  --department-slug tactico --all-applicable-categories

echo
echo "=== 3/5 Sync TemplateField rows (admin inline editing) ==="
run sync_template_fields --all

echo
echo "=== 4/5 Optional demo data: fake history + Nutricional layout ==="
if [[ -n "$RESET_FAKES" ]]; then
  run seed_fake_exams --reset
else
  run seed_fake_exams
fi
run seed_nutricional_layout --all-applicable-categories

echo
echo "Done. Open http://localhost:3000 and log in."
