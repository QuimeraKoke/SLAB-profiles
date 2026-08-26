"""Rename age-group teams to their cohort: `SUB-11` → `Serie 2014`.

Why
---
A stored name cannot describe an age-group team. The group climbs a rung every
January while the name sits still, so the label is wrong within a year of being
written — and on 2026-08-25 the club's were a full season stale: the squad
called `SUB-11` was competing in Sub 12, with 239 of 239 appearances in that
competition being 2014-born.

The cohort is the only invariant. They were born in 2014 forever.

Order matters, and it is the inverse of the obvious one
------------------------------------------------------
This runs AFTER `Category.season_label()` and the frontend `label` field, not
before. Renaming first would have every screen suddenly read "Serie 2014" to
staff who say "Sub 12" — correct data, unusable app. With the derived label
already shipped, the screens show "Sub 12 · Serie 2014" and this migration is
invisible to a user. (Same lesson as decoupling before renaming, learned earlier
in this migration.)

Safe now for a second reason: nothing in the code reads digits out of the name
any more. It used to — `re.search(r"(\\d{1,2})")` on the category name, which
reads "Serie 2014" as **20** and would have filed the 2014 kids' matches under
Sub 20 with no error at all. `_category_index` now reads `TeamSeason`, and
`exams/test_category_index.py::test_a_cohort_name_does_not_poison_the_mapping`
exists to keep it that way.

Scope: only teams WITH a `cohort_year` — 7 of this club's 16. That is not an
exception list, it is the same rule applied: a team is named after whatever is
invariant about it. Sub 20 and the first team recycle their players every
season, so the stored name IS their invariant. Sub 20 has no cohort for a real
reason — its 2026 appearances are 2006, 2007 and 2008, a genuinely mixed squad
rather than missing data.

`unique_together = ("club", "name")` is why this checks for collisions instead
of assuming: two teams of one club cannot share a name, and a half-migrated club
could already hold the target name.
"""
from __future__ import annotations

import re

from django.db import migrations

PREFIX = "Serie "
# What the old labels looked like, so `backward` can rebuild one. The stored
# name is a season label, so the only faithful inverse is the bracket the team
# competed in at the time — recovered from TeamSeason, not from arithmetic.
_SUB_NAME = re.compile(r"^SUB-\d{1,2}$", re.IGNORECASE)


def forward(apps, schema_editor):
    Category = apps.get_model("core", "Category")

    taken = set()
    for club_id, name in Category.objects.values_list("club_id", "name"):
        taken.add((club_id, name))

    for cat in Category.objects.filter(cohort_year__isnull=False):
        if cat.is_senior:
            continue                       # atemporal: no cohort arithmetic
        target = f"{PREFIX}{cat.cohort_year}"
        if cat.name == target:
            continue
        if (cat.club_id, target) in taken:
            # Already used by another team of this club. Leave the name alone
            # rather than raise: an un-renamed team still reads correctly
            # through `season_label`, a failed migration blocks the deploy.
            continue
        taken.discard((cat.club_id, cat.name))
        taken.add((cat.club_id, target))
        cat.name = target
        cat.save(update_fields=["name"])


def backward(apps, schema_editor):
    """Rebuild a `SUB-NN` name from the team's declared bracket.

    Not exact by construction — the old names were a stale 2025 snapshot, so the
    honest inverse reproduces the CURRENT competition rather than the historical
    typo. Reversing then re-applying is stable, which is what matters.
    """
    Category = apps.get_model("core", "Category")
    TeamSeason = apps.get_model("core", "TeamSeason")

    for cat in Category.objects.filter(cohort_year__isnull=False):
        if not cat.name.startswith(PREFIX):
            continue
        ts = (
            TeamSeason.objects.filter(team=cat, bracket__age__isnull=False)
            .select_related("bracket")
            .order_by("-season")
            .first()
        )
        if ts is None:
            continue
        candidate = f"SUB-{ts.bracket.age}"
        if Category.objects.filter(
            club_id=cat.club_id, name=candidate,
        ).exclude(pk=cat.pk).exists():
            continue
        cat.name = candidate
        cat.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [("core", "0021_seed_is_senior")]

    operations = [migrations.RunPython(forward, backward)]
