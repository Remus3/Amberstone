"""Tests for ``dashboard/_adaptation_latch.py`` - game-time-latched CS metrics.

Covers:
  * Before 10:00: compute returns {} (no cs_at_10)
  * At/after 10:00: cs_at_10 latched; later ticks do NOT change it
  * New game_id resets the latch
  * game_time reset (lower than previous) resets the latch
  * csd_at_15 SR: two players same position, opposite teams, diff correct
  * csd_at_15 ARAM / no-position: unset
  * Malformed input ({}, None, missing keys) -> {} no exception

Latch keys:
  cs_at_10  - first observation where game_time_s >= 600, any mode
  csd_at_15 - first observation where game_time_s >= 900, SR only (opponent
              must share active player position, opposite team)
"""
from __future__ import annotations

import unittest

from dashboard import _adaptation_latch


def _summary(
    game_time_s: int,
    cs: int,
    game_id: str = "g1",
    players: list | None = None,
    my_position: str = "MIDDLE",
    my_team: str = "ORDER",
) -> dict:
    """Minimal liveclient_summary-shaped dict for latch tests."""
    base: dict = {
        "game_time_s": game_time_s,
        "cs": cs,
        "game_id": game_id,
    }
    if players is not None:
        base["players"] = players
    return base


def _player(position: str, team: str, creep_score: int,
            is_active: bool = False) -> dict:
    return {
        "position":    position,
        "team":        team,
        "creep_score": creep_score,
        "is_active":   is_active,
    }


class LatchBase(unittest.TestCase):
    def setUp(self):
        _adaptation_latch.reset()


# ---------------------------------------------------------------------------
# 1. Before 10:00 - no cs_at_10
# ---------------------------------------------------------------------------

class Before10Tests(LatchBase):
    def test_early_tick_returns_empty(self):
        result = _adaptation_latch.compute(_summary(game_time_s=300, cs=45))
        self.assertEqual(result, {})

    def test_at_599_returns_empty(self):
        result = _adaptation_latch.compute(_summary(game_time_s=599, cs=100))
        self.assertEqual(result, {})

    def test_zero_time_returns_empty(self):
        result = _adaptation_latch.compute(_summary(game_time_s=0, cs=0))
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# 2. At/after 10:00 - cs_at_10 latched; immutable thereafter
# ---------------------------------------------------------------------------

class At10Tests(LatchBase):
    def test_at_600_latches_cs(self):
        result = _adaptation_latch.compute(_summary(game_time_s=600, cs=78))
        self.assertEqual(result.get("cs_at_10"), 78)

    def test_after_600_latches_cs(self):
        result = _adaptation_latch.compute(_summary(game_time_s=650, cs=83))
        self.assertEqual(result.get("cs_at_10"), 83)

    def test_later_tick_higher_cs_does_not_change_latch(self):
        # First observation past 10:00 latches 78.
        _adaptation_latch.compute(_summary(game_time_s=600, cs=78))
        # Later tick with more CS must NOT update.
        result = _adaptation_latch.compute(_summary(game_time_s=700, cs=102))
        self.assertEqual(result.get("cs_at_10"), 78)

    def test_latch_value_is_integer(self):
        result = _adaptation_latch.compute(_summary(game_time_s=600, cs=55))
        self.assertIsInstance(result.get("cs_at_10"), int)


# ---------------------------------------------------------------------------
# 3. New game_id resets the latch
# ---------------------------------------------------------------------------

class NewGameResetTests(LatchBase):
    def test_new_game_id_resets_cs_at_10(self):
        _adaptation_latch.compute(_summary(game_time_s=600, cs=78, game_id="g1"))
        # New game - should re-latch at the new value.
        result = _adaptation_latch.compute(_summary(game_time_s=600, cs=55, game_id="g2"))
        self.assertEqual(result.get("cs_at_10"), 55)

    def test_new_game_id_before_600_is_empty(self):
        _adaptation_latch.compute(_summary(game_time_s=600, cs=78, game_id="g1"))
        # New game, still pre-10:00.
        result = _adaptation_latch.compute(_summary(game_time_s=200, cs=20, game_id="g2"))
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# 4. game_time reset (lower than previous) resets the latch
# ---------------------------------------------------------------------------

class GameTimeResetTests(LatchBase):
    def test_time_regression_resets_latch(self):
        _adaptation_latch.compute(_summary(game_time_s=600, cs=78))
        # game_time went backwards - same game_id but time < previous.
        # Should reset; pre-600 means no latch yet.
        result = _adaptation_latch.compute(_summary(game_time_s=100, cs=10))
        self.assertEqual(result, {})

    def test_time_regression_then_re_latch(self):
        _adaptation_latch.compute(_summary(game_time_s=600, cs=78))
        # Backwards.
        _adaptation_latch.compute(_summary(game_time_s=100, cs=10))
        # Forward again past 10:00 - should latch fresh value.
        result = _adaptation_latch.compute(_summary(game_time_s=610, cs=62))
        self.assertEqual(result.get("cs_at_10"), 62)


# ---------------------------------------------------------------------------
# 5. csd_at_15 SR mode
# ---------------------------------------------------------------------------

class Csd15SrTests(LatchBase):
    def _sr_summary(self, game_time_s: int, active_cs: int,
                    opponent_cs: int, game_id: str = "sr1") -> dict:
        """Build a summary with active player + lane opponent."""
        players = [
            _player("MIDDLE", "ORDER",  active_cs,   is_active=True),
            _player("MIDDLE", "CHAOS",  opponent_cs, is_active=False),
            _player("TOP",    "ORDER",  50,           is_active=False),
            _player("TOP",    "CHAOS",  45,           is_active=False),
        ]
        return {
            "game_time_s": game_time_s,
            "cs":          active_cs,
            "game_id":     game_id,
            "players":     players,
        }

    def test_at_900_latches_csd(self):
        result = _adaptation_latch.compute(
            self._sr_summary(game_time_s=900, active_cs=130, opponent_cs=122)
        )
        self.assertEqual(result.get("csd_at_15"), 8)

    def test_negative_csd(self):
        result = _adaptation_latch.compute(
            self._sr_summary(game_time_s=900, active_cs=110, opponent_cs=122)
        )
        self.assertEqual(result.get("csd_at_15"), -12)

    def test_csd_is_int(self):
        result = _adaptation_latch.compute(
            self._sr_summary(game_time_s=900, active_cs=100, opponent_cs=100)
        )
        self.assertIsInstance(result.get("csd_at_15"), int)

    def test_csd_not_updated_on_later_tick(self):
        self._sr_summary(game_time_s=900, active_cs=130, opponent_cs=122)
        _adaptation_latch.compute(
            self._sr_summary(game_time_s=900, active_cs=130, opponent_cs=122)
        )
        # Later tick; must not update csd_at_15.
        result = _adaptation_latch.compute(
            self._sr_summary(game_time_s=1000, active_cs=150, opponent_cs=140)
        )
        self.assertEqual(result.get("csd_at_15"), 8)

    def test_before_900_no_csd(self):
        result = _adaptation_latch.compute(
            self._sr_summary(game_time_s=600, active_cs=80, opponent_cs=70)
        )
        self.assertNotIn("csd_at_15", result)


# ---------------------------------------------------------------------------
# 5b. csd_at_15 unset for ARAM / no-position
# ---------------------------------------------------------------------------

class Csd15NoPositionTests(LatchBase):
    def test_aram_no_players_no_csd(self):
        # ARAM: no players list (positions unavailable).
        summary = {
            "game_time_s": 900,
            "cs":          80,
            "game_id":     "aram1",
        }
        result = _adaptation_latch.compute(summary)
        self.assertNotIn("csd_at_15", result)

    def test_no_matching_opponent_position_no_csd(self):
        # Players exist but active player has no positional opponent.
        players = [
            _player("",       "ORDER", 80, is_active=True),
            _player("JUNGLE", "CHAOS", 5,  is_active=False),
        ]
        summary = {
            "game_time_s": 900,
            "cs":          80,
            "game_id":     "g1",
            "players":     players,
        }
        result = _adaptation_latch.compute(summary)
        self.assertNotIn("csd_at_15", result)

    def test_empty_position_string_no_csd(self):
        # Active player has blank position.
        players = [
            _player("", "ORDER", 80, is_active=True),
            _player("", "CHAOS", 70, is_active=False),
        ]
        summary = {
            "game_time_s": 900,
            "cs":          80,
            "game_id":     "g1",
            "players":     players,
        }
        result = _adaptation_latch.compute(summary)
        self.assertNotIn("csd_at_15", result)


# ---------------------------------------------------------------------------
# 6. Malformed input -> {} no exception
# ---------------------------------------------------------------------------

class MalformedInputTests(LatchBase):
    def test_none_input(self):
        self.assertEqual(_adaptation_latch.compute(None), {})

    def test_empty_dict(self):
        self.assertEqual(_adaptation_latch.compute({}), {})

    def test_missing_game_time(self):
        self.assertEqual(_adaptation_latch.compute({"cs": 50, "game_id": "x"}), {})

    def test_missing_cs_key(self):
        # cs_at_10 should still work if cs key present - test missing entirely.
        result = _adaptation_latch.compute({"game_time_s": 600, "game_id": "x"})
        # Missing cs -> can't latch, should return {} or omit cs_at_10.
        self.assertNotIn("cs_at_10", result)

    def test_non_dict_players(self):
        summary = {"game_time_s": 900, "cs": 80, "game_id": "g", "players": "bad"}
        self.assertEqual(_adaptation_latch.compute(summary), {"cs_at_10": 80})

    def test_string_game_time(self):
        # Non-numeric game_time_s -> defensive, return {}.
        self.assertEqual(
            _adaptation_latch.compute({"game_time_s": "bad", "cs": 50, "game_id": "g"}),
            {},
        )


# ---------------------------------------------------------------------------
# Reset helper
# ---------------------------------------------------------------------------

class ResetTests(LatchBase):
    def test_reset_clears_latch(self):
        _adaptation_latch.compute(_summary(game_time_s=600, cs=78))
        _adaptation_latch.reset()
        # After reset, a fresh tick at 600 should re-latch.
        result = _adaptation_latch.compute(_summary(game_time_s=600, cs=55))
        self.assertEqual(result.get("cs_at_10"), 55)


if __name__ == "__main__":
    unittest.main()
