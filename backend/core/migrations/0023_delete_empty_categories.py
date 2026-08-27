"""Delete categories that hold nothing at all.

On Universidad de Chile that is `SUB-8`, `SUB-9` and `SUB-10`: no players (not
even inactive), no call-ups, no memberships, no declared seasons, no events. They
came from the legacy migration or were made by hand — no seed creates them.

Why they are worth removing rather than tolerating:

* The ANFP ladder starts at **Sub 11**. Below it no competition exists, so the
  COMET feed will never carry anything for them.
* They took 3 of 16 slots in the global picker and were indistinguishable from a
  real team until you clicked into an empty screen.
* Under the cohort model a real team arrives as `Serie YYYY` carrying its birth
  year. These have no `cohort_year`, so they could not even host the 2015 squad
  the club still owes us.
* The briefing job was running over them. Each had five `BriefingSnapshot` rows
  naming `claude-opus-4-8` with `items: []` — an Opus call per category per run,
  for squads with zero players.

Selected by VALUE, never by name. Checked first: across every club in the
database exactly three categories match, so the rule needs no name list and
cannot single out one club's naming habit.

FAIL-SAFE by construction
-------------------------
The blocking check walks `Category._meta.related_objects` and treats **any**
relation it does not explicitly recognise as blocking. So if someone adds a new
`Category` FK next year and forgets this file, a category with rows in it stops
being deletable instead of being silently cascaded away. The alternative — a
hardcoded list of things to check — goes stale in exactly the direction that
loses data.

Three relations are accepted as collateral, and nothing else:

* `StaffMembership.categories` (M2M) — a user's access scope. Losing a link to a
  category that no longer exists costs nothing.
* `ExamTemplate.applicable_categories` (M2M) — same.
* `BriefingSnapshot` — an LLM response cache keyed by a data hash. It
  regenerates, and for these rows it holds nothing anyway.

Everything else with rows aborts that category's deletion and says so. Prod is
the source of truth and may not look like local, which is the whole reason this
is a guard rather than a delete statement.
"""
from __future__ import annotations

from django.db import migrations

# Relations whose rows do NOT justify keeping a category alive. Anything absent
# from this set blocks deletion — see the module docstring.
ACCEPTABLE = {
    "core.StaffMembership.categories",
    "exams.ExamTemplate.applicable_categories",
    "dashboards.BriefingSnapshot.category",
}


def _blockers(category, related) -> list[str]:
    """Relations holding rows that mean this category is still in use."""
    found = []
    for rel in related:
        model = rel.related_model
        field = rel.field.name
        key = f"{model._meta.label}.{field}"
        try:
            n = model.objects.filter(**{field: category}).count()
        except Exception:                      # noqa: BLE001
            # An unqueryable relation is not a licence to delete.
            found.append(f"{key} (no verificable)")
            continue
        if n and key not in ACCEPTABLE:
            found.append(f"{key}={n}")
    return found


def forward(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    related = [
        r for r in Category._meta.related_objects
        if getattr(r, "related_model", None) is not None
    ]

    for category in Category.objects.all():
        if category.is_senior:
            continue                           # the first team is never a shell
        blockers = _blockers(category, related)
        if blockers:
            continue
        print(f"  borrando categoría vacía: {category.name} (club {category.club_id})")
        category.delete()


def backward(apps, schema_editor):
    """Deliberately not reversible.

    Re-creating the rows would invent new UUIDs, which is not the same thing as
    undoing this — anything that referenced the old ids would still be broken.
    The JSON backup taken before the run is the real undo, and re-creating a team
    is a few seconds in the admin.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [("core", "0022_rename_cohort_teams")]

    operations = [migrations.RunPython(forward, backward)]
