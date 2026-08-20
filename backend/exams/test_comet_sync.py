"""COMET sync — the pure derivation logic. No database.

The two things worth pinning down are the traps that produce plausible-but-wrong
numbers rather than errors:

  * minutes come from the lineup's `starting` flag plus substitution events, and
    the substitution minute must be read from `minuteFull` (the match minute).
    `minute` restarts each half, so a 64' change reads as 19 — the sync would
    silently record a starter as having played 19 minutes.
  * on a Substitution, `player` comes ON and `player2` goes OFF. Swapping them
    inverts every substitute's minutes.
"""
from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from events.models import EventParticipant
from exams.services import comet_sync as C


def _p(person_id, *, starting=False, captain=False, shirt=None, position=""):
    return {
        "personId": person_id, "starting": starting, "captain": captain,
        "shirtNumber": shirt, "position": position,
        "name": f"PLAYER {person_id}", "fifaId": f"F{person_id}",
    }


def _sub(minute_full, on_id, off_id, *, home=True, minute=None):
    return {
        "eventType": {"name": "Substitution", "fcdName": "SUBSTITUTION"},
        "matchPhase": {"fcdName": "SECOND_HALF"},
        "minute": minute if minute is not None else minute_full - 45,
        "minuteFull": minute_full,
        "player": _p(on_id), "player2": _p(off_id), "homeTeam": home,
    }


def _ev(name, minute_full, person_id, *, home=True, fcd=None, second=None):
    e = {
        "eventType": {"name": name, "fcdName": fcd or name.upper().replace(" ", "_")},
        "matchPhase": {"fcdName": "FIRST_HALF"},
        "minute": minute_full, "minuteFull": minute_full,
        "player": _p(person_id), "homeTeam": home,
    }
    if second is not None:
        e["player2"] = _p(second)
    return e


class MinutesTests(SimpleTestCase):
    def test_starter_who_finishes_plays_ninety(self):
        rows = C.build_player_rows([_p(1, starting=True)], [], is_home=True)
        self.assertEqual(rows[1]["minutos"], 90)
        self.assertEqual(rows[1]["min_ingreso"], 0)
        self.assertIsNone(rows[1]["min_salida"])

    def test_starter_replaced_plays_until_that_minute(self):
        rows = C.build_player_rows(
            [_p(1, starting=True), _p(2)], [_sub(64, on_id=2, off_id=1)], is_home=True,
        )
        self.assertEqual(rows[1]["minutos"], 64)
        self.assertEqual(rows[1]["min_salida"], 64)

    def test_substitute_plays_the_remainder(self):
        rows = C.build_player_rows(
            [_p(1, starting=True), _p(2)], [_sub(64, on_id=2, off_id=1)], is_home=True,
        )
        self.assertEqual(rows[2]["minutos"], 26)   # 90 − 64
        self.assertEqual(rows[2]["min_ingreso"], 64)

    def test_minutes_use_minuteFull_not_the_per_half_minute(self):
        # The trap: `minute` is 19 for a 64' second-half change. Reading it would
        # make the starter's day look like 19 minutes.
        rows = C.build_player_rows(
            [_p(1, starting=True), _p(2)],
            [_sub(64, on_id=2, off_id=1, minute=19)], is_home=True,
        )
        self.assertEqual(rows[1]["minutos"], 64)
        self.assertEqual(rows[2]["minutos"], 26)

    def test_unused_substitute_is_recorded_with_zero(self):
        # An official zero is information: available and not used.
        rows = C.build_player_rows([_p(9)], [], is_home=True)
        self.assertEqual(rows[9]["minutos"], 0)
        self.assertIsNone(rows[9]["min_ingreso"])
        self.assertFalse(rows[9]["titular"])

    def test_substitute_later_replaced_gets_the_window(self):
        rows = C.build_player_rows(
            [_p(1, starting=True), _p(2), _p(3)],
            [_sub(60, on_id=2, off_id=1), _sub(80, on_id=3, off_id=2)], is_home=True,
        )
        self.assertEqual(rows[2]["minutos"], 20)   # on 60, off 80
        self.assertEqual(rows[3]["minutos"], 10)

    def test_extra_time_extends_the_full_time_baseline(self):
        events = [{
            "eventType": {"name": "Yellow card", "fcdName": "YELLOW"},
            "matchPhase": {"fcdName": "FIRST_EXTRA_TIME"},
            "minute": 5, "minuteFull": 95, "player": _p(1), "homeTeam": True,
        }]
        rows = C.build_player_rows([_p(1, starting=True)], events, is_home=True)
        self.assertEqual(rows[1]["minutos"], 120)

    def test_the_other_team_events_are_ignored(self):
        # The payload carries both sides; an away substitution must not move our
        # player's minutes.
        rows = C.build_player_rows(
            [_p(1, starting=True)], [_sub(30, on_id=99, off_id=1, home=False)],
            is_home=True,
        )
        self.assertEqual(rows[1]["minutos"], 90)
        self.assertIsNone(rows[1]["min_salida"])


class EventTallyTests(SimpleTestCase):
    def test_goals_cards_and_own_goals_are_counted(self):
        rows = C.build_player_rows(
            [_p(1, starting=True), _p(2, starting=True)],
            [
                _ev("Goal", 22, 1, fcd="GOAL"),
                _ev("Goal", 70, 1, fcd="GOAL"),
                _ev("Yellow card", 33, 2, fcd="YELLOW"),
                _ev("Own goal", 80, 2, fcd="OWN_GOAL"),
            ],
            is_home=True,
        )
        self.assertEqual(rows[1]["goles"], 2)
        self.assertEqual(rows[2]["amarillas"], 1)
        self.assertEqual(rows[2]["autogoles"], 1)
        self.assertEqual(rows[2]["goles"], 0, "an own goal is not a goal for us")

    def test_assist_is_credited_to_player2_on_a_goal(self):
        rows = C.build_player_rows(
            [_p(1, starting=True), _p(2, starting=True)],
            [_ev("Goal", 55, 1, fcd="GOAL", second=2)], is_home=True,
        )
        self.assertEqual(rows[1]["goles"], 1)
        self.assertEqual(rows[2]["asistencias"], 1)

    def test_penalty_counts_as_a_goal_and_a_penalty(self):
        rows = C.build_player_rows(
            [_p(1, starting=True)],
            [_ev("Goal from penalty", 60, 1, fcd="PENALTY_GOAL")], is_home=True,
        )
        self.assertEqual(rows[1]["goles"], 1)
        self.assertEqual(rows[1]["penales"], 1)

    def test_events_for_someone_not_in_the_lineup_are_dropped(self):
        rows = C.build_player_rows(
            [_p(1, starting=True)], [_ev("Goal", 10, 404, fcd="GOAL")], is_home=True,
        )
        self.assertNotIn(404, rows)
        self.assertEqual(rows[1]["goles"], 0)


class CategoryResolutionTests(SimpleTestCase):
    def test_age_token_is_found_in_the_competition_name(self):
        self.assertEqual(C._category_from_names("Sub 15 Nacional Clausura 2026"), 15)
        self.assertEqual(C._category_from_names("Grupo Centro 1 - Sub 13"), 13)

    def test_age_token_is_found_in_the_parent_when_the_name_is_a_phase(self):
        # "Grupo 2" alone appears under BOTH Sub 11 and Sub 12 parents, so the
        # parent has to be consulted or matches get misfiled.
        self.assertEqual(C._category_from_names("Grupo 2", "Sub 12 Apertura 2025"), 12)
        self.assertEqual(C._category_from_names("Grupo 2", "Sub 11 Apertura 2025"), 11)

    def test_senior_competitions_have_no_age_token(self):
        for name in ("Primera División 2026", "COPA CHILE COCA COLA ZERO AZUCAR 2026",
                     "CONMEBOL Sudamericana 2026", "Semifinales"):
            self.assertIsNone(C._category_from_names(name), name)

    def test_a_year_is_not_mistaken_for_an_age(self):
        self.assertIsNone(C._category_from_names("Primera División 2026"))


class EventMetadataTests(SimpleTestCase):
    MATCH = {
        "id": 341833578,
        "homeTeam": {"id": 40003, "name": "AUDAX ITALIANO"},
        "awayTeam": {"id": 40017, "name": "UNIVERSIDAD DE CHILE"},
        "homeTeamResult": {"current": 1, "half": 0},
        "awayTeamResult": {"current": 2, "half": 1},
        "liveStatus": "PLAYED", "round": "16", "roundOrder": 16, "matchNumber": 124,
        "competition": {"id": 341832333, "name": "Primera División 2026",
                        "parentName": "Primera División 2026"},
        "facility": {"name": "BICENTENARIO DE LA FLORIDA"},
    }
    OFFICIALS = [
        {"role": "Referee", "name": "GARAY CRISTIAN"},
        {"role": "VAR", "name": "ARAOS MIGUEL"},
    ]
    # What `lineups[side]["officials"]` actually holds: OUR coaching staff.
    TEAM_STAFF = [
        {"role": "Head Coach", "name": "GAGO FERNANDO"},
        {"role": "Doctor", "name": "MARAMBIO HUGO"},
    ]

    def test_away_match_is_flagged_and_the_opponent_is_the_home_team(self):
        md = C.build_event_metadata(self.MATCH, self.OFFICIALS, 40017)
        self.assertFalse(md["is_home"])
        self.assertEqual(md["opponent"], "AUDAX ITALIANO")

    def test_score_keeps_the_fixtures_sync_key_shape(self):
        # Same keys api_football wrote, so consumers read one shape.
        md = C.build_event_metadata(self.MATCH, self.OFFICIALS, 40017)
        self.assertEqual(md["score"], {"home": 1, "away": 2})
        self.assertEqual(md["score_half_time"], {"home": 0, "away": 1})

    def test_referee_and_official_match_id_are_carried(self):
        md = C.build_event_metadata(self.MATCH, self.OFFICIALS, 40017)
        self.assertEqual(md["referee"], "GARAY CRISTIAN")
        self.assertEqual(md["comet_match_id"], 341833578)
        self.assertEqual(md["venue"], "BICENTENARIO DE LA FLORIDA")

    def test_team_staff_is_kept_apart_from_match_officials(self):
        # The bug this guards: passing the lineup's coaching staff as officials
        # leaves `referee` null and mislabels our doctor as a match official.
        md = C.build_event_metadata(
            self.MATCH, self.OFFICIALS, 40017, team_staff=self.TEAM_STAFF,
        )
        self.assertEqual(md["referee"], "GARAY CRISTIAN")
        self.assertEqual([o["name"] for o in md["match_officials"]],
                         ["GARAY CRISTIAN", "ARAOS MIGUEL"])
        self.assertEqual([o["name"] for o in md["team_staff"]],
                         ["GAGO FERNANDO", "MARAMBIO HUGO"])

    def test_referee_is_none_when_only_staff_is_supplied(self):
        md = C.build_event_metadata(self.MATCH, self.TEAM_STAFF, 40017)
        self.assertIsNone(md["referee"])

    def test_status_long_agrees_with_status(self):
        md = C.build_event_metadata(self.MATCH, self.OFFICIALS, 40017)
        self.assertEqual(md["status"], "PLAYED")
        self.assertEqual(md["status_long"], "Jugado")

    def test_home_match_flips_the_side(self):
        md = C.build_event_metadata(self.MATCH, self.OFFICIALS, 40003)
        self.assertTrue(md["is_home"])
        self.assertEqual(md["opponent"], "UNIVERSIDAD DE CHILE")


class MatchRoleTests(SimpleTestCase):
    """`match_role` decides whether a player's match data is visible at all.

    `api.triage` suppresses the whole performance block — GPS included — when
    the role is NULL, so a substitute who came on used to read as never called
    up. These pin the mapping from COMET's own squad list.
    """

    def test_starter_is_titular(self):
        self.assertEqual(
            C.match_role_for({"titular": True, "minutos": 90}),
            EventParticipant.MatchRole.TITULAR,
        )

    def test_substitute_who_came_on_is_suplente_ingresa(self):
        # The real case: Nicolás Fernández vs Limache — on at 79', 11 official
        # minutes. Reported as "no GPS data" purely because the role was unset.
        self.assertEqual(
            C.match_role_for({"titular": False, "minutos": 11, "min_ingreso": 79}),
            EventParticipant.MatchRole.SUPLENTE_INGRESA,
        )

    def test_unused_substitute_is_still_a_called_up_player(self):
        self.assertEqual(
            C.match_role_for({"titular": False, "minutos": 0}),
            EventParticipant.MatchRole.SUPLENTE_NO_INGRESA,
        )

    def test_a_starter_sent_off_at_zero_is_not_demoted_to_the_bench(self):
        # `titular` wins over the minute count: COMET reports the flag
        # independently, and a red card in the opening seconds still means he
        # started the match.
        self.assertEqual(
            C.match_role_for({"titular": True, "minutos": 0}),
            EventParticipant.MatchRole.TITULAR,
        )

    def test_missing_minutes_key_does_not_crash(self):
        self.assertEqual(
            C.match_role_for({"titular": False}),
            EventParticipant.MatchRole.SUPLENTE_NO_INGRESA,
        )


class _FakePlayer:
    def __init__(self, name, year):
        self.first_name, self.last_name = name.split(" ", 1)
        self.date_of_birth = date(year, 6, 1) if year else None

    def __repr__(self):  # keeps assertion output readable
        return f"{self.first_name} {self.last_name}"


class BracketTieBreakTests(SimpleTestCase):
    """The age bracket disambiguates namesakes — it never vetoes a lone match.

    Learned on 2026-08-20 by nearly shipping the opposite. A birth-YEAR filter
    applied to the roster up front looked right and would have suppressed 17
    real fichas: this club's 2026 Sub 16 fields a player born 2009-12-20, Sub 15
    one born 2010-12-21, Sub 14 one born 2011-10-23. All three are the only
    holder of their name in the club, so there was never any ambiguity to
    resolve — eligibility is a cutoff-DATE rule, not a birth-year one, and a
    suppressed row is indistinguishable from a player who didn't play.
    """

    @staticmethod
    def _person(name):
        return {"name": name}

    def test_lone_candidate_wins_even_when_apparently_overage(self):
        # Belmar, born 2009-12-20, in a 2026 Sub 16 match. No namesake, so the
        # bracket must not get a vote.
        roster = [_FakePlayer("Oscar Belmar", 2009)]
        player, method = C._resolve_player(
            self._person("BELMAR OSCAR"), roster, bracket_age=16, season_year=2026,
        )
        self.assertIsNotNone(player)
        self.assertEqual(method, C.CometPlayerLink.MATCH_NAME)

    def test_namesakes_are_split_by_the_bracket(self):
        # The Cofre shape: two humans, one name, cohorts far apart.
        roster = [_FakePlayer("Diego Cofre", 2008), _FakePlayer("Diego Cofre", 2014)]
        player, method = C._resolve_player(
            self._person("COFRE DIEGO"), roster, bracket_age=12, season_year=2026,
        )
        self.assertEqual(player.date_of_birth.year, 2014)
        self.assertEqual(method, C.CometPlayerLink.MATCH_NAME)

    def test_namesakes_in_the_same_cohort_stay_unresolved(self):
        # Age can't separate these, so it must abstain rather than guess.
        roster = [_FakePlayer("Diego Cofre", 2014), _FakePlayer("Diego Cofre", 2014)]
        player, method = C._resolve_player(
            self._person("COFRE DIEGO"), roster, bracket_age=12, season_year=2026,
        )
        self.assertIsNone(player)
        self.assertEqual(method, C.CometPlayerLink.MATCH_UNRESOLVED)

    def test_senior_match_never_uses_the_bracket(self):
        roster = [_FakePlayer("Diego Cofre", 2008), _FakePlayer("Diego Cofre", 2014)]
        player, _ = C._resolve_player(
            self._person("COFRE DIEGO"), roster, bracket_age=None, season_year=2026,
        )
        self.assertIsNone(player)  # still ambiguous, still abstains

    def test_no_match_stays_no_match(self):
        player, method = C._resolve_player(
            self._person("NADIE PERDIDO"), [_FakePlayer("Oscar Belmar", 2009)],
            bracket_age=16, season_year=2026,
        )
        self.assertIsNone(player)
        self.assertEqual(method, C.CometPlayerLink.MATCH_UNRESOLVED)


class BracketPlausibleTests(SimpleTestCase):
    ROSTER = [
        _FakePlayer("Kid Fifteen", 2015),
        _FakePlayer("Kid Fourteen", 2014),
        _FakePlayer("Old Six", 2006),
        _FakePlayer("Unknown Birth", None),
    ]

    def _names(self, out):
        return sorted(f"{p.first_name} {p.last_name}" for p in out)

    def test_senior_keeps_everyone(self):
        self.assertEqual(len(C.bracket_plausible(self.ROSTER, None, 2026)), 4)

    def test_a_year_of_slack_is_allowed_for_the_cutoff_rule(self):
        # Sub 15 in 2026 nominally wants 2011+; 2010 is kept on purpose.
        kept = self._names(C.bracket_plausible(
            [_FakePlayer("Vasco Marin", 2010)], 15, 2026,
        ))
        self.assertEqual(kept, ["Vasco Marin"])

    def test_clearly_overage_is_still_dropped(self):
        self.assertNotIn(
            "Old Six", self._names(C.bracket_plausible(self.ROSTER, 12, 2026)),
        )

    def test_unknown_birth_date_is_never_dropped(self):
        self.assertIn(
            "Unknown Birth", self._names(C.bracket_plausible(self.ROSTER, 11, 2026)),
        )
