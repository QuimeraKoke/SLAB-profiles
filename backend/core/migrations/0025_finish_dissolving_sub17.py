"""Finish 0024: the two things that (correctly) blocked the shell's deletion.

0024 moved the players and detached the national-team fixtures, then refused to
delete `SUB-17` because two relations still pointed at it. That refusal was the
guard doing its job — but neither leftover is real data, and both describe a team
that never existed:

* **Two `PlayerTeamMembership` spells.** Written by the backfill with
  `reason="carga inicial (fecha del primer partido)"` and
  `since=2025-03-27` — which is the date of the **Sudamericano opener**, not the
  day either boy joined a squad. Neither player has a spell at his real serie, so
  these are re-POINTED rather than closed: Renato was always a 2008 and Andher
  always a 2009, and closing a spell at a fictional team then opening another
  would record a transfer that never happened.

* **One `TeamSeason`** (2026 → Sub 18) with `derived=True`, i.e. computed by the
  backfill, not declared by anyone. With no team to describe it says nothing.
  Only `derived=True` rows are removed — a human's correction is never touched,
  the same rule `backfill_cohorts` follows.

Then the shell goes through 0023's emptiness check again, unchanged: one
definition of "holds nothing", applied from three different migrations.
"""
from __future__ import annotations

import importlib

from django.db import migrations

_0024 = importlib.import_module("core.migrations.0024_dissolve_sub17")
_0023 = importlib.import_module("core.migrations.0023_delete_empty_categories")


def forward(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    Membership = apps.get_model("core", "PlayerTeamMembership")
    TeamSeason = apps.get_model("core", "TeamSeason")

    shell = Category.objects.filter(pk=_0024.SOURCE_CATEGORY).first()
    if shell is None:
        return                                  # already gone

    for m in Membership.objects.filter(team=shell).select_related(
        "player", "player__category",
    ):
        home = m.player.category
        if home is None or home.pk == shell.pk:
            # The player never moved, so the spell is still the best record
            # there is. Leave it and let the shell survive.
            print(f"  pertenencia de {m.player_id} sin re-apuntar: sigue en el cajón")
            continue
        if home.cohort_year is None:
            print(f"  pertenencia de {m.player_id} sin re-apuntar: {home.name} no es serie")
            continue
        if m.player.date_of_birth and home.cohort_year != m.player.date_of_birth.year:
            print(f"  pertenencia de {m.player_id} sin re-apuntar: cohorte no coincide")
            continue
        m.team = home
        m.save(update_fields=["team"])
        print(f"  pertenencia de {m.player.last_name} → {home.name}")

    derived = TeamSeason.objects.filter(team=shell, derived=True).delete()[0]
    kept = TeamSeason.objects.filter(team=shell).count()
    if derived:
        print(f"  {derived} temporada(s) derivada(s) borrada(s)")
    if kept:
        print(f"  {kept} temporada(s) declarada(s) a mano intactas — el cajón se queda")

    related = [
        r for r in Category._meta.related_objects
        if getattr(r, "related_model", None) is not None
    ]
    shell.refresh_from_db()
    blockers = _0023._blockers(shell, related)
    if blockers:
        print(f"  {shell.name} NO se borra, todavía tiene: {', '.join(blockers)}")
    else:
        print(f"  borrando el cajón vacío: {shell.name}")
        shell.delete()


def backward(apps, schema_editor):
    """Not reversible — the shell and its id are gone. See 0024."""
    pass


class Migration(migrations.Migration):

    dependencies = [("core", "0024_dissolve_sub17")]

    operations = [migrations.RunPython(forward, backward)]
