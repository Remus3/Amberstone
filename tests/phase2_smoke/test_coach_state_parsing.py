"""
tests/phase2_smoke/test_coach_state_parsing.py
Phase 5 — Coach state-parsing smoke harness.

One test class per coach mode. Exercises the state-parsing layer
(raw → coaching dict) and the SR prompt builder without calling the
Anthropic API. All inputs are deterministic fixture dicts.

Structural contract: each coach's output must carry the minimal set of
keys required to render a useful prompt. When Phase 4.3 (coaching_payload.py
pydantic model) lands, replace the manual key assertions with schema
validation.
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from tests.fixtures.state_dicts import SR_STATE, ARAM_STATE, ARENA_STATE, BRAWL_STATE, TFT_STATE

# ── Minimal raw Riot API fixtures (activePlayer + gameData + allPlayers) ──────
# These mirror the shape of /liveclientdata/allgamedata — not the processed
# game_reader output. The _parse_* functions operate on this raw format.

_ARAM_RAW = {
    "activePlayer": {
        "summonerName": "TestPlayer",
        "championName": "Vayne",
        "championStats": {
            "currentHealth": 900, "maxHealth": 1100,
            "resourceValue": 200,  "resourceMax": 300,
        },
        "currentGold": 2200,
        "level": 10,
        "abilities": {},
        "fullRunes": {"generalRunes": [], "keystoneRune": {}},
    },
    "gameData": {"gameTime": 492.0, "gameMode": "ARAM"},
    "allPlayers": [
        {
            "summonerName": "TestPlayer", "championName": "Vayne", "team": "ORDER",
            "scores": {"kills": 4, "deaths": 1, "assists": 5},
            "items": [{"displayName": "BotRK"}, {"displayName": "Phantom Drive"}],
            "runes": {"keystone": {"displayName": "Lethal Tempo"}},
        },
        {"championName": "Garen", "team": "CHAOS",
         "scores": {"kills": 1, "deaths": 2, "assists": 0}, "items": []},
    ],
    "events": {"Events": []},
}

_ARENA_RAW = {
    "activePlayer": {
        "summonerName": "TestPlayer", "championName": "Garen",
        "championStats": {
            "currentHealth": 1800, "maxHealth": 2200,
            "resourceValue": 0, "resourceMax": 0,
        },
        "currentGold": 3100, "level": 12, "abilities": {},
        "fullRunes": {"generalRunes": [], "keystoneRune": {}},
    },
    "gameData": {"gameTime": 765.0, "gameMode": "CHERRY"},
    "allPlayers": [
        {
            "summonerName": "TestPlayer", "championName": "Garen",
            "team": "ORDER", "customData": {"augments": ["Perseverance"]},
            "scores": {"kills": 5, "deaths": 2, "assists": 3},
            "items": [{"displayName": "Sunfire Aegis"}],
        },
        {"championName": "Jinx", "team": "CHAOS",
         "scores": {"kills": 3, "deaths": 1, "assists": 0}, "items": []},
    ],
    "events": {"Events": []},
}

_BRAWL_RAW = {
    "activePlayer": {
        "summonerName": "TestPlayer", "championName": "Ahri",
        "championStats": {
            "currentHealth": 1000, "maxHealth": 1400,
            "resourceValue": 350, "resourceMax": 500,
        },
        "currentGold": 2500, "level": 9, "abilities": {},
        "fullRunes": {"generalRunes": [], "keystoneRune": {}},
    },
    "gameData": {"gameTime": 360.0, "gameMode": "NEXUSBLITZ"},
    "allPlayers": [
        {
            "summonerName": "TestPlayer", "championName": "Ahri",
            "team": "ORDER",
            "scores": {"kills": 3, "deaths": 1, "assists": 4},
            "items": [{"displayName": "Luden's Tempest"}],
        },
        {"championName": "Yasuo", "team": "CHAOS",
         "scores": {"kills": 2, "deaths": 0, "assists": 1}, "items": []},
    ],
    "events": {"Events": []},
}


# ─────────────────────────────────────────────────────────────────────────────
# SR — _build_user_prompt (coach_integration.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestSrCoachPromptBuilder(unittest.TestCase):
    """Smoke: _build_user_prompt produces a non-empty, structured string."""

    def setUp(self):
        from coach_integration import _build_user_prompt
        self._build = _build_user_prompt

    def test_returns_nonempty_string(self):
        out = self._build(SR_STATE, "pushing")
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 50)

    def test_contains_game_time(self):
        out = self._build(SR_STATE, "pushing")
        self.assertIn(SR_STATE["game_time"], out)

    def test_contains_gold(self):
        out = self._build(SR_STATE, "pushing")
        self.assertIn(str(SR_STATE["gold"]), out)

    def test_contains_ally_comp(self):
        out = self._build(SR_STATE, "pushing")
        self.assertIn(SR_STATE["ally_comp"][0], out)

    def test_empty_state_does_not_raise(self):
        out = self._build({}, "unknown")
        self.assertIsInstance(out, str)

    def test_wave_state_included(self):
        for wave in ("pushing", "freezing", "trading"):
            out = self._build(SR_STATE, wave)
            self.assertIn(wave, out)


# ─────────────────────────────────────────────────────────────────────────────
# ARAM — aram_coach._parse_state
# ─────────────────────────────────────────────────────────────────────────────

class TestAramCoachParsing(unittest.TestCase):
    """Smoke: _parse_state produces a dict with required keys."""

    _REQUIRED = {"champion", "items", "ally_comp", "enemy_comp",
                 "gold", "hp_pct", "level", "game_time", "kda"}

    def setUp(self):
        from coaches.aram_coach import _parse_state
        self._parse = _parse_state

    def test_empty_input_returns_dict(self):
        out = self._parse({})
        self.assertIsInstance(out, dict)

    def test_empty_input_has_required_keys(self):
        out = self._parse({})
        missing = self._REQUIRED - out.keys()
        self.assertFalse(missing, f"Missing keys: {missing}")

    def test_fixture_input_extracts_champion(self):
        out = self._parse(_ARAM_RAW)
        self.assertEqual(out["champion"], "Vayne")

    def test_fixture_input_extracts_gold(self):
        out = self._parse(_ARAM_RAW)
        self.assertEqual(out["gold"], 2200)

    def test_fixture_input_extracts_level(self):
        out = self._parse(_ARAM_RAW)
        self.assertEqual(out["level"], 10)

    def test_fixture_input_items_list(self):
        out = self._parse(_ARAM_RAW)
        self.assertIsInstance(out["items"], list)
        self.assertIn("BotRK", out["items"])

    def test_fixture_input_ally_comp_list(self):
        out = self._parse(_ARAM_RAW)
        self.assertIsInstance(out["ally_comp"], list)

    def test_fixture_input_enemy_comp_list(self):
        out = self._parse(_ARAM_RAW)
        self.assertIsInstance(out["enemy_comp"], list)
        self.assertIn("Garen", out["enemy_comp"])


# ─────────────────────────────────────────────────────────────────────────────
# Arena — arena_coach._parse_arena_state
# ─────────────────────────────────────────────────────────────────────────────

class TestArenaCoachParsing(unittest.TestCase):
    """Smoke: _parse_arena_state produces a dict with required keys."""

    _REQUIRED = {"champion", "items", "gold", "hp_pct", "level",
                 "kda", "round", "wins", "losses"}

    def setUp(self):
        from coaches.arena_coach import _parse_arena_state
        self._parse = _parse_arena_state

    def test_empty_input_returns_dict(self):
        out = self._parse({})
        self.assertIsInstance(out, dict)

    def test_empty_input_has_required_keys(self):
        out = self._parse({})
        missing = self._REQUIRED - out.keys()
        self.assertFalse(missing, f"Missing keys: {missing}")

    def test_fixture_input_extracts_champion(self):
        out = self._parse(_ARENA_RAW)
        self.assertEqual(out["champion"], "Garen")

    def test_fixture_input_gold(self):
        out = self._parse(_ARENA_RAW)
        self.assertEqual(out["gold"], 3100)

    def test_fixture_input_items_list(self):
        out = self._parse(_ARENA_RAW)
        self.assertIsInstance(out["items"], list)

    def test_fixture_input_hp_pct_range(self):
        out = self._parse(_ARENA_RAW)
        self.assertGreaterEqual(out["hp_pct"], 0)
        self.assertLessEqual(out["hp_pct"], 100)


# ─────────────────────────────────────────────────────────────────────────────
# Brawl — brawl_coach._parse_brawl_state
# ─────────────────────────────────────────────────────────────────────────────

class TestBrawlCoachParsing(unittest.TestCase):
    """Smoke: _parse_brawl_state produces a dict with required keys."""

    _REQUIRED = {"champion", "items", "ally_comp", "enemy_comp",
                 "gold", "hp_pct", "level", "game_time", "kda"}

    def setUp(self):
        from coaches.brawl_coach import _parse_brawl_state
        self._parse = _parse_brawl_state

    def test_empty_input_returns_dict(self):
        out = self._parse({})
        self.assertIsInstance(out, dict)

    def test_empty_input_has_required_keys(self):
        out = self._parse({})
        missing = self._REQUIRED - out.keys()
        self.assertFalse(missing, f"Missing keys: {missing}")

    def test_fixture_input_extracts_champion(self):
        out = self._parse(_BRAWL_RAW)
        self.assertEqual(out["champion"], "Ahri")

    def test_fixture_input_gold(self):
        out = self._parse(_BRAWL_RAW)
        self.assertEqual(out["gold"], 2500)

    def test_fixture_input_enemy_comp_list(self):
        out = self._parse(_BRAWL_RAW)
        self.assertIsInstance(out["enemy_comp"], list)
        self.assertIn("Yasuo", out["enemy_comp"])

    def test_fixture_input_game_mode(self):
        out = self._parse(_BRAWL_RAW)
        self.assertEqual(out["game_mode"], "NEXUSBLITZ")


# ─────────────────────────────────────────────────────────────────────────────
# TFT — tft_coach._coach_board_to_placement
# ─────────────────────────────────────────────────────────────────────────────

class TestTftCoachBoardPlacement(unittest.TestCase):
    """Smoke: _coach_board_to_placement returns comma-separated position string."""

    def setUp(self):
        from coaches.tft_coach import _coach_board_to_placement
        self._place = _coach_board_to_placement

    def test_returns_string(self):
        out = self._place("Jinx Caitlyn Lulu")
        self.assertIsInstance(out, str)

    def test_commas_separate_entries(self):
        out = self._place("Jinx Caitlyn Lulu")
        self.assertIn(",", out)

    def test_all_units_appear(self):
        out = self._place("Jinx Caitlyn Lulu")
        for name in ("Jinx", "Caitlyn", "Lulu"):
            self.assertIn(name, out)

    def test_empty_board_returns_string(self):
        out = self._place("")
        self.assertIsInstance(out, str)

    def test_single_unit(self):
        out = self._place("Jinx")
        self.assertIn("Jinx", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
