"""Dissolve the `SUB-17` bucket: it was never a team.

What it actually held, on Universidad de Chile:

* **Two players** whose home team had been set to it — Renato Nuñez (2008) and
  Andher Gonzalez (2009), both active, with 33 and 23 appearances and ~40 exams
  each.
* **Six matches of the Chilean national team's Sudamericano Sub-17 2025** —
  "Brasil vs Chile (Semifinal)", "Chile vs Argentina", "Venezuela vs Chile".

So it was a holding pen for a national-team call-up, and the model already
supported doing it properly: a THIRD player in those same six matches, Benjamín
Díaz, kept his real home team (SUB-20) and simply appears as an
`EventParticipant`. That is how it should have been done for the other two.

Because it mixed a 2008 with a 2009 it could not be given a `cohort_year`
(50/50, under the 70% threshold), so the picker rendered it as a bare "Sub 18" —
sitting beside "Serie 2008 — Sub 18" and "Serie 2009 — Sub 18", which are both
legitimate, since the ANFP runs no Sub 17 and the 2009s go up a rung.

Three steps: move the two players to their cohort, detach the six national-team
matches, then let 0023's emptiness rule remove the shell.

Why this targets IDs instead of a rule
--------------------------------------
The obvious generalisation — "move each player to the Serie matching their birth
year" — is dangerous here, and the database says so:

    SUB-20                43 players, born 2004–2009   ← a real bracket squad
    PEF - Femenino        20 players
    SUB-19 F - Femenino   16 players
    SUB-16 F - Femenino    1 player,  born 2009        ← would move into Serie 2009

`SUB-16 F` holds a single player born in 2009, so that rule would have moved a
**female player into a male team**. Same class of mistake as the cross-sex
suggestion caught earlier in this migration. And SUB-20 would have been
dismantled into six series, destroying a real squad.

So this is a one-off correction recorded as data, which is what a migration is
for. The guards make it safe rather than trusting the ids: every move re-checks
the fact that justifies it, and skips silently if it no longer holds. Prod is the
source of truth and may not match local.
"""
from __future__ import annotations

from django.db import migrations

# Verified on 2026-08-26 against the real rows. (player id, birth year → cohort).
MOVES = [
    ("3f58be6c-d8ca-4186-a295-906124d7d706", 2009),   # Andher Gonzalez
    ("15116efc-8472-4ec5-a689-ffb267b6b0c7", 2008),   # Renato Nuñez
]
# The shell itself, so its national-team fixtures can be detached.
SOURCE_CATEGORY = "bce01ca0-6aa3-4e8d-a8b2-50a3d0fc2d9e"


def move_player(player, destination) -> str:
    """Re-home `player`, or say why not. Every guard is a fact re-checked.

    Returns "" on success, otherwise the reason it was skipped.
    """
    if player.date_of_birth is None:
        return "sin fecha de nacimiento"
    if destination is None:
        return "no existe la serie destino"
    if destination.cohort_year != player.date_of_birth.year:
        # The justification for the whole move. Without it this is just a
        # reassignment of someone to a team they don't belong to.
        return (
            f"el año de nacimiento ({player.date_of_birth.year}) no coincide "
            f"con la cohorte destino ({destination.cohort_year})"
        )
    if destination.club_id != player.category.club_id:
        return "la serie destino es de otro club"
    # Sex guard: not needed for these two ids, kept because it is the exact
    # accident a generic version of this migration would have caused, and a
    # future edit to MOVES should hit a wall rather than a female player
    # landing in a male squad.
    others = destination.players.exclude(pk=player.pk).exclude(sex="")
    sexes = {p.sex for p in others}
    if sexes and player.sex and player.sex not in sexes:
        return f"sexo {player.sex} no coincide con la serie destino ({sexes})"

    player.category = destination
    player.save(update_fields=["category"])
    return ""


def forward(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    Player = apps.get_model("core", "Player")
    Event = apps.get_model("events", "Event")

    source = Category.objects.filter(pk=SOURCE_CATEGORY).first()

    for player_id, cohort in MOVES:
        player = Player.objects.filter(pk=player_id).select_related("category").first()
        if player is None:
            print(f"  jugador {player_id} no existe, se omite")
            continue
        if source is not None and player.category_id != source.pk:
            print(f"  {player_id} ya no está en el cajón, se omite")
            continue
        destination = Category.objects.filter(
            club_id=player.category.club_id, cohort_year=cohort, is_senior=False,
        ).first()
        why = move_player(player, destination)
        if why:
            print(f"  NO se movió {player_id}: {why}")
        else:
            print(f"  {player.first_name} {player.last_name} → {destination.name}")

    if source is None:
        return

    # The national-team fixtures. Detached, not deleted: they are real matches,
    # and nobody loses them — a player's calendar and /desarrollo resolve through
    # participation, never through `Event.category`. Benjamín Díaz already proves
    # that path works, since he only ever appeared in them as a participant.
    detached = Event.objects.filter(category=source).update(category=None)
    if detached:
        print(f"  {detached} partidos de selección desprendidos de {source.name}")

    # Hand the shell to 0023's rule rather than deleting it here: same guard,
    # one definition of "holds nothing".
    import importlib

    rule = importlib.import_module("core.migrations.0023_delete_empty_categories")
    related = [
        r for r in Category._meta.related_objects
        if getattr(r, "related_model", None) is not None
    ]
    source.refresh_from_db()
    blockers = rule._blockers(source, related)
    if blockers:
        print(f"  {source.name} NO se borra, todavía tiene: {', '.join(blockers)}")
    else:
        print(f"  borrando el cajón vacío: {source.name}")
        source.delete()


def backward(apps, schema_editor):
    """Not reversible: the shell is gone and its id with it.

    Moving the two players back would need a category that no longer exists. The
    players themselves are untouched by this being irreversible — they keep every
    exam and appearance, which hang off the player, not the team.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_delete_empty_categories"),
        ("events", "0007_event_bracket"),
    ]

    operations = [migrations.RunPython(forward, backward)]
