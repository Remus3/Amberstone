"""Characterization tests for `dashboard.builders._enrich_from_lcu`
(AUTONOMOUS_AUDIT finding #13 / spec 4.E).

`_enrich_from_lcu` parses an external/untrusted LCU
/lol-match-history/v1/games/{gameId} payload into the Post Game Review
shape. It has many branches and (pre-this-file) no dedicated parse-shape
coverage - the existing `test_last_match_surrender.py` only pins the two
surrender flags, `test_last_match_timeline.py` only the timeline helper.

This file pins the full parse contract so the builders.py payload-boundary
split (spec 4.C) is provably behavior-preserving. The high-signal anchors
are the subtle invariants a refactor could silently break:

  - guard clauses return ``{}`` (a dict, never ``None``)
  - ``items`` is exactly 7 ints (item0..item6)
  - ``arena_augments`` / roster ``augments`` are 6 ints from the
    1-indexed ``playerAugment1..6`` fields
  - roster ``cs`` == totalMinionsKilled + neutralMinionsKilled
  - ``support.heal_plus_shield`` == heals + shields on teammates
  - ``teams[].first_dragon`` is sourced from the LCU typo key
    ``firstDargon`` (a well-meaning "fix" to ``firstDragon`` would
    silently break dragon detection)
  - ``teams[].win`` is True only when the string value lowercases to
    "win"
  - exactly one roster entry is ``is_me`` and it is the tracked puuid's
  - numeric fields coerce None / "5" / missing without crashing

Synthetic-only - no DB, no live LCU.
"""
from __future__ import annotations

import unittest

from dashboard.builders import _enrich_from_lcu

_PUUID = "op-puuid-xyz"


def _stats(**over) -> dict:
    """A stats block with realistic defaults; override any field."""
    base = {
        "win": True,
        "champLevel": 11,
        "kills": 5, "deaths": 3, "assists": 7,
        "totalMinionsKilled": 120, "neutralMinionsKilled": 30,
        "goldEarned": 11000,
        "totalDamageDealtToChampions": 22000,
        "physicalDamageDealtToChampions": 15000,
        "magicDamageDealtToChampions": 6000,
        "trueDamageDealtToChampions": 1000,
        "totalDamageTaken": 18000,
        "damageSelfMitigated": 9000,
        "damageDealtToObjectives": 4000,
        "damageDealtToTurrets": 1200,
        "totalHeal": 2500,
        "totalHealsOnTeammates": 800,
        "totalDamageShieldedOnTeammates": 400,
        "totalUnitsHealed": 3,
        "visionScore": 22,
        "wardsPlaced": 10,
        "wardsKilled": 4,
        "visionWardsBoughtInGame": 2,
        "perk0": 8005, "perkPrimaryStyle": 8000, "perkSubStyle": 8200,
        "perk1": 9111, "perk2": 9104, "perk3": 8014,
        "perk4": 8210, "perk5": 8237,
    }
    for i in range(7):
        base[f"item{i}"] = 1000 + i
    base.update(over)
    return base


def _detail(*, mode="sr", augments_filled=False, n_players=10,
            teams=None, drop_teams=False):
    """Build a representative LCU game detail.

    ``mode`` only varies metadata + whether augment fields are filled
    (the parser itself has no mode branch - that is the point of
    asserting cross-mode invariance). The operator is participant 1 on
    team 100.
    """
    mode_meta = {
        "sr":     {"gameMode": "CLASSIC", "queueId": 420, "mapId": 11},
        "mayhem": {"gameMode": "KIWI",    "queueId": 2400, "mapId": 12},
        "arena":  {"gameMode": "CHERRY",  "queueId": 1700, "mapId": 30},
    }[mode]

    idents, parts = [], []
    for pid in range(1, n_players + 1):
        puuid = _PUUID if pid == 1 else f"other-{pid}"
        team = 100 if pid <= n_players // 2 else 200
        idents.append({
            "participantId": pid,
            "player": {"puuid": puuid, "gameName": f"P{pid}",
                       "tagLine": "NA1"},
        })
        st = _stats(win=(team == 100))
        if augments_filled:
            for a in range(1, 7):
                st[f"playerAugment{a}"] = 7000 + pid * 10 + a
        parts.append({
            "participantId": pid, "championId": 60 + pid, "teamId": team,
            "spell1Id": 4, "spell2Id": 14, "stats": st,
        })

    detail = {
        "gameId": 9001,
        "gameDuration": 1734,
        "gameCreation": 1_700_000_000_000,
        "gameCreationDate": "2026-05-18T10:00:00Z",
        "gameVersion": "16.10.1",
        "endOfGameResult": "GameComplete",
        "participantIdentities": idents,
        "participants": parts,
        **mode_meta,
    }
    if not drop_teams:
        detail["teams"] = teams if teams is not None else [
            {"teamId": 100, "win": "Win", "firstBlood": True,
             "firstTower": True, "firstBaron": False, "firstDargon": True,
             "firstInhibitor": True, "baronKills": 1, "dragonKills": 3,
             "towerKills": 8, "inhibitorKills": 1, "riftHeraldKills": 1,
             "hordeKills": 4, "bans": [{"championId": 1}]},
            {"teamId": 200, "win": "Fail", "firstBlood": False,
             "firstTower": False, "firstBaron": True, "firstDargon": False,
             "firstInhibitor": False, "baronKills": 1, "dragonKills": 1,
             "towerKills": 2, "inhibitorKills": 0, "riftHeraldKills": 0,
             "hordeKills": 0, "bans": []},
        ]
    return detail


class GuardClauseTests(unittest.TestCase):
    """Every bail path returns an empty dict (never None, never raises)."""

    def test_non_dict_detail_returns_empty_dict(self):
        for bad in (None, [], "x", 5):
            out = _enrich_from_lcu(bad, _PUUID)
            self.assertEqual(out, {})
            self.assertIsInstance(out, dict)

    def test_blank_puuid_returns_empty_dict(self):
        self.assertEqual(_enrich_from_lcu(_detail(), ""), {})

    def test_missing_identities_returns_empty_dict(self):
        d = _detail()
        d["participantIdentities"] = []
        self.assertEqual(_enrich_from_lcu(d, _PUUID), {})

    def test_missing_participants_returns_empty_dict(self):
        d = _detail()
        d["participants"] = []
        self.assertEqual(_enrich_from_lcu(d, _PUUID), {})

    def test_puuid_not_in_lobby_returns_empty_dict(self):
        self.assertEqual(_enrich_from_lcu(_detail(), "ghost-puuid"), {})

    def test_identity_without_matching_participant_returns_empty(self):
        # me_pid resolves from identities, but no participant carries it.
        d = _detail(n_players=2)
        d["participants"] = [p for p in d["participants"]
                             if p["participantId"] != 1]
        self.assertEqual(_enrich_from_lcu(d, _PUUID), {})


class HappyPathShapeTests(unittest.TestCase):
    def setUp(self):
        self.out = _enrich_from_lcu(_detail(mode="sr"), _PUUID)

    def test_scalars(self):
        o = self.out
        self.assertEqual(o["champion_id"], 61)
        self.assertEqual(o["team_id"], 100)
        self.assertIs(o["win"], True)
        self.assertEqual(o["champ_level"], 11)
        self.assertEqual(o["spell1_id"], 4)
        self.assertEqual(o["spell2_id"], 14)

    def test_items_is_exactly_seven_ints(self):
        items = self.out["items"]
        self.assertEqual(len(items), 7)
        self.assertEqual(items, [1000, 1001, 1002, 1003, 1004, 1005, 1006])
        self.assertTrue(all(isinstance(x, int) for x in items))

    def test_runes_shape(self):
        r = self.out["runes"]
        self.assertEqual(r["keystone"], 8005)
        self.assertEqual(r["primary_style"], 8000)
        self.assertEqual(r["sub_style"], 8200)
        self.assertEqual(len(r["primary"]), 4)
        self.assertEqual(len(r["secondary"]), 2)
        self.assertEqual(r["primary"][0], 8005)
        self.assertEqual(r["secondary"], [8210, 8237])

    def test_damage_block(self):
        dmg = self.out["damage"]
        self.assertEqual(dmg["dealt_to_champs"], 22000)
        self.assertEqual(dmg["physical_to_champs"], 15000)
        self.assertEqual(dmg["magic_to_champs"], 6000)
        self.assertEqual(dmg["true_to_champs"], 1000)
        self.assertEqual(dmg["taken"], 18000)
        self.assertEqual(dmg["self_mitigated"], 9000)
        self.assertEqual(dmg["to_objectives"], 4000)
        self.assertEqual(dmg["to_turrets"], 1200)

    def test_support_heal_plus_shield_is_sum_invariant(self):
        sup = self.out["support"]
        self.assertEqual(sup["heal_on_teammates"], 800)
        self.assertEqual(sup["shield_on_teammates"], 400)
        self.assertEqual(sup["heal_plus_shield"], 1200)
        self.assertEqual(
            sup["heal_plus_shield"],
            sup["heal_on_teammates"] + sup["shield_on_teammates"])
        self.assertEqual(sup["total_heal"], 2500)
        self.assertEqual(sup["units_healed"], 3)

    def test_vision_block(self):
        v = self.out["vision"]
        self.assertEqual(v["score"], 22)
        self.assertEqual(v["wards_placed"], 10)
        self.assertEqual(v["wards_killed"], 4)
        self.assertEqual(v["control_wards"], 2)

    def test_metadata_passthrough(self):
        o = self.out
        self.assertEqual(o["game_id"], 9001)
        self.assertEqual(o["game_mode"], "CLASSIC")
        self.assertEqual(o["queue_id"], 420)
        self.assertEqual(o["map_id"], 11)
        self.assertEqual(o["game_duration_s"], 1734)
        self.assertEqual(o["game_creation_ts"], 1_700_000_000_000)
        self.assertEqual(o["game_creation_date"], "2026-05-18T10:00:00Z")
        self.assertEqual(o["game_version"], "16.10.1")
        self.assertEqual(o["end_of_game_result"], "GameComplete")


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.out = _enrich_from_lcu(_detail(mode="sr"), _PUUID)

    def test_roster_length_matches_participants(self):
        self.assertEqual(len(self.out["roster"]), 10)

    def test_exactly_one_is_me_and_it_is_the_operator(self):
        me = [r for r in self.out["roster"] if r["is_me"]]
        self.assertEqual(len(me), 1)
        self.assertEqual(me[0]["participant_id"], 1)
        self.assertEqual(me[0]["champion_id"], 61)
        self.assertEqual(me[0]["game_name"], "P1")
        self.assertEqual(me[0]["tag_line"], "NA1")

    def test_roster_cs_is_minions_plus_neutral(self):
        r0 = self.out["roster"][0]
        self.assertEqual(r0["cs"], 150)  # 120 + 30
        self.assertEqual(
            r0["cs"],
            120 + 30,
            "cs must stay totalMinionsKilled + neutralMinionsKilled")

    def test_roster_per_player_fields(self):
        r0 = self.out["roster"][0]
        self.assertEqual(r0["kills"], 5)
        self.assertEqual(r0["deaths"], 3)
        self.assertEqual(r0["assists"], 7)
        self.assertEqual(r0["gold"], 11000)
        self.assertEqual(r0["damage_to_champs"], 22000)
        self.assertEqual(r0["damage_taken"], 18000)
        self.assertEqual(r0["vision_score"], 22)
        self.assertEqual(r0["champ_level"], 11)
        self.assertEqual(len(r0["items"]), 7)
        self.assertEqual(r0["summoner1"], 4)
        self.assertEqual(r0["summoner2"], 14)
        self.assertIs(r0["win"], True)

    def test_team_split_is_100_200(self):
        teams = {r["team_id"] for r in self.out["roster"]}
        self.assertEqual(teams, {100, 200})


class TeamObjectiveTests(unittest.TestCase):
    def setUp(self):
        self.out = _enrich_from_lcu(_detail(mode="sr"), _PUUID)

    def test_first_dragon_reads_lcu_typo_key(self):
        # The LCU payload misspells it `firstDargon`. The parser must
        # keep reading that exact key - a "fix" to firstDragon would
        # silently null out dragon-first detection.
        blue = next(t for t in self.out["teams"] if t["team_id"] == 100)
        red = next(t for t in self.out["teams"] if t["team_id"] == 200)
        self.assertIs(blue["first_dragon"], True)
        self.assertIs(red["first_dragon"], False)

    def test_first_dragon_false_when_only_correct_spelling_present(self):
        d = _detail(teams=[
            {"teamId": 100, "win": "Win", "firstDragon": True},
            {"teamId": 200, "win": "Fail"},
        ])
        out = _enrich_from_lcu(d, _PUUID)
        blue = next(t for t in out["teams"] if t["team_id"] == 100)
        self.assertIs(blue["first_dragon"], False)

    def test_team_win_is_string_win_case_insensitive(self):
        d = _detail(teams=[
            {"teamId": 100, "win": "WIN"},
            {"teamId": 200, "win": None},
        ])
        out = _enrich_from_lcu(d, _PUUID)
        blue = next(t for t in out["teams"] if t["team_id"] == 100)
        red = next(t for t in out["teams"] if t["team_id"] == 200)
        self.assertIs(blue["win"], True)
        self.assertIs(red["win"], False)

    def test_objective_counts_and_bans(self):
        blue = next(t for t in self.out["teams"] if t["team_id"] == 100)
        self.assertEqual(blue["baron_kills"], 1)
        self.assertEqual(blue["dragon_kills"], 3)
        self.assertEqual(blue["tower_kills"], 8)
        self.assertEqual(blue["inhibitor_kills"], 1)
        self.assertEqual(blue["rift_herald_kills"], 1)
        self.assertEqual(blue["horde_kills"], 4)
        self.assertEqual(blue["bans"], [{"championId": 1}])
        self.assertIs(blue["first_blood"], True)
        self.assertIs(blue["first_tower"], True)
        self.assertIs(blue["first_inhibitor"], True)

    def test_missing_teams_yields_empty_list(self):
        out = _enrich_from_lcu(_detail(drop_teams=True), _PUUID)
        self.assertEqual(out["teams"], [])


class ModeInvarianceTests(unittest.TestCase):
    """The parser has no mode branch; SR/Mayhem/Arena differ only in
    metadata + whether augment fields are populated."""

    def test_sr_augments_all_zero(self):
        out = _enrich_from_lcu(_detail(mode="sr"), _PUUID)
        self.assertEqual(out["arena_augments"], [0, 0, 0, 0, 0, 0])
        self.assertEqual(out["roster"][0]["augments"], [0, 0, 0, 0, 0, 0])

    def test_mayhem_augments_are_six_ints_one_indexed(self):
        out = _enrich_from_lcu(
            _detail(mode="mayhem", augments_filled=True), _PUUID)
        self.assertEqual(out["game_mode"], "KIWI")
        self.assertEqual(out["queue_id"], 2400)
        # operator is pid 1: 7000 + 1*10 + a for a in 1..6
        self.assertEqual(out["arena_augments"],
                         [7011, 7012, 7013, 7014, 7015, 7016])
        self.assertEqual(len(out["roster"][0]["augments"]), 6)

    def test_arena_augments_populated(self):
        out = _enrich_from_lcu(
            _detail(mode="arena", augments_filled=True), _PUUID)
        self.assertEqual(out["game_mode"], "CHERRY")
        self.assertEqual(out["queue_id"], 1700)
        self.assertEqual(out["map_id"], 30)
        self.assertEqual(out["arena_augments"],
                         [7011, 7012, 7013, 7014, 7015, 7016])

    def test_roster_shape_identical_across_modes(self):
        keys = None
        for m in ("sr", "mayhem", "arena"):
            out = _enrich_from_lcu(
                _detail(mode=m, augments_filled=(m != "sr")), _PUUID)
            row_keys = set(out["roster"][0].keys())
            if keys is None:
                keys = row_keys
            self.assertEqual(row_keys, keys)


class OddFieldRobustnessTests(unittest.TestCase):
    """Untrusted LCU JSON: missing / None / string-numeric fields must
    coerce without raising."""

    def test_missing_stats_block_defaults_to_zero(self):
        d = _detail(n_players=2)
        d["participants"][1].pop("stats")  # the enemy has no stats
        out = _enrich_from_lcu(d, _PUUID)
        foe = next(r for r in out["roster"] if not r["is_me"])
        self.assertEqual(foe["kills"], 0)
        self.assertEqual(foe["cs"], 0)
        self.assertEqual(foe["gold"], 0)
        self.assertEqual(foe["items"], [0, 0, 0, 0, 0, 0, 0])
        self.assertIs(foe["win"], False)

    def test_none_and_string_numerics_coerce(self):
        d = _detail(n_players=2)
        st = d["participants"][0]["stats"]
        st["item0"] = None
        st["item1"] = "1234"
        st["kills"] = None
        st["totalMinionsKilled"] = "80"
        st["neutralMinionsKilled"] = None
        out = _enrich_from_lcu(d, _PUUID)
        self.assertEqual(out["items"][0], 0)
        self.assertEqual(out["items"][1], 1234)
        me = next(r for r in out["roster"] if r["is_me"])
        self.assertEqual(me["kills"], 0)
        self.assertEqual(me["cs"], 80)  # "80" + None -> 80 + 0

    def test_missing_item_keys_default_zero(self):
        d = _detail(n_players=2)
        st = d["participants"][0]["stats"]
        for i in range(7):
            st.pop(f"item{i}", None)
        out = _enrich_from_lcu(d, _PUUID)
        self.assertEqual(out["items"], [0, 0, 0, 0, 0, 0, 0])

    def test_win_is_real_bool_not_truthy_passthrough(self):
        d = _detail(n_players=2)
        d["participants"][0]["stats"]["win"] = 1
        out = _enrich_from_lcu(d, _PUUID)
        self.assertIs(out["win"], True)


if __name__ == "__main__":
    unittest.main()
