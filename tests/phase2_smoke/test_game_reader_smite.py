"""Tests for GameReader._has_smite — Smite-based jungler detection."""
import unittest
from game_reader import GameReader


def _player(spell1="Flash", spell2="Ignite"):
    return {
        "championName": "TestChamp",
        "summonerSpells": {
            "summonerSpellOne": {"displayName": spell1},
            "summonerSpellTwo": {"displayName": spell2},
        },
    }


class TestHasSmite(unittest.TestCase):
    def test_smite_in_slot_one(self):
        self.assertTrue(GameReader._has_smite(_player("Smite", "Flash")))

    def test_smite_in_slot_two(self):
        self.assertTrue(GameReader._has_smite(_player("Flash", "Smite")))

    def test_no_smite(self):
        self.assertFalse(GameReader._has_smite(_player("Flash", "Ignite")))

    def test_empty_player(self):
        self.assertFalse(GameReader._has_smite({}))

    def test_missing_summoner_spells(self):
        self.assertFalse(GameReader._has_smite({"championName": "X"}))

    def test_non_dict_summoner_spells(self):
        self.assertFalse(GameReader._has_smite({"summonerSpells": None}))

    def test_partial_spell_entry(self):
        # summonerSpellTwo is missing; should not crash
        p = {"summonerSpells": {"summonerSpellOne": {"displayName": "Smite"}}}
        self.assertTrue(GameReader._has_smite(p))

    def test_smite_substring_match(self):
        # Handles hypothetical "Chilling Smite" / "Challenging Smite" variants
        self.assertTrue(GameReader._has_smite(_player("Flash", "Chilling Smite")))


if __name__ == "__main__":
    unittest.main()
