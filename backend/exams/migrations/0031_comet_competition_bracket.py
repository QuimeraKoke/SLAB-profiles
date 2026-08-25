"""Store the FACT (bracket), not the JOIN (team), on a COMET competition.

`CometCompetitionLink.category` held "which team plays this competition", which
is `bracket ⋈ TeamSeason(season)` — a join whose left side never changes and
whose right side changes every January. Caching it meant a correction to either
input left the stored answer stale, silently. See the model docstring.

Three moves, in this order because each needs the previous one's state:

1. add `bracket`, and fill it from the competition's own name;
2. `category` → `category_override`, keeping ONLY the values a human set;
3. drop `auto_resolved`, whose only job was telling those two apart.

The regex is inlined rather than imported from `comet_sync`: a data migration
has to keep behaving the way it did the day it ran, and app code moves.
"""
from __future__ import annotations

import re

from django.db import migrations, models
import django.db.models.deletion

_SUB_RE = re.compile(r"\bsub\s*\.?\s*(\d{1,2})\b", re.IGNORECASE)


def _age_from_names(*names: str) -> int | None:
    """The `Sub NN` number in any of these strings. Frozen copy of the resolver."""
    for name in names:
        if not name:
            continue
        m = _SUB_RE.search(name)
        if m:
            return int(m.group(1))
    return None


def forward(apps, schema_editor):
    Link = apps.get_model("exams", "CometCompetitionLink")
    Bracket = apps.get_model("core", "Bracket")

    rungs = sorted(
        (b for b in Bracket.objects.all() if b.age is not None),
        key=lambda b: b.age,
    )
    senior = (
        Bracket.objects.filter(age__isnull=True).order_by("-order").first()
    )

    for link in Link.objects.all():
        age = _age_from_names(link.competition_name, link.parent_name)
        if age is None:
            # No age token → a senior competition (Primera, Copa, CONMEBOL).
            link.bracket = senior
        else:
            # First rung that admits the age: the ANFP ladder has no Sub 17, so
            # a "Sub 17" competition belongs to Sub 18. Same rule as everywhere.
            link.bracket = next((b for b in rungs if b.age >= age), senior)

        # `category` was a machine-written cache of the join whenever
        # auto_resolved — exactly the stale value this migration exists to stop
        # trusting. Only a human's pin survives as an override.
        if link.auto_resolved:
            link.category = None

        link.save(update_fields=["bracket", "category"])


def backward(apps, schema_editor):
    """Re-derive the cached category so the old code has something to read."""
    Link = apps.get_model("exams", "CometCompetitionLink")
    TeamSeason = apps.get_model("core", "TeamSeason")
    Category = apps.get_model("core", "Category")

    for link in Link.objects.select_related("bracket", "integration").all():
        if link.category_id or link.bracket_id is None:
            continue
        club_id = link.integration.club_id
        if link.bracket.age is None:
            link.category = Category.objects.filter(
                club_id=club_id, is_senior=True).first()
        else:
            ts = (
                TeamSeason.objects
                .filter(team__club_id=club_id, bracket=link.bracket)
                .select_related("team")
                .order_by("-season", "team__cohort_year")
                .first()
            )
            link.category = ts.team if ts else None
        link.auto_resolved = bool(link.category_id)
        link.save(update_fields=["category", "auto_resolved"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_seed_is_senior"),
        ("exams", "0030_cometintegration_cometcompetitionlink_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="cometcompetitionlink",
            name="bracket",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="comet_competition_links",
                to="core.bracket",
                help_text=(
                    "Categoría de competencia de la federación. Vacío = sin "
                    "resolver: los partidos se omiten y la competencia queda en "
                    "la cola de revisión."
                ),
            ),
        ),
        migrations.RunPython(forward, backward),
        migrations.RenameField(
            model_name="cometcompetitionlink",
            old_name="category",
            new_name="category_override",
        ),
        migrations.AlterField(
            model_name="cometcompetitionlink",
            name="category_override",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="comet_competition_links",
                to="core.category",
                help_text=(
                    "Sólo para excepciones: fija el equipo a mano cuando el "
                    "bracket tiene más de uno del club. Vacío = se calcula por "
                    "temporada."
                ),
            ),
        ),
        migrations.RemoveField(
            model_name="cometcompetitionlink",
            name="auto_resolved",
        ),
    ]
