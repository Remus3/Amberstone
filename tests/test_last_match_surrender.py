"""Tests for the s220 carried surrender-tag slice - `_enrich_from_lcu`
surfacing `ended_in_surrender` / `ended_in_early_surrender`.

The LCU /lol-match-history/v1/games/{gameId} payload already carries
`gameEndedInSurrender` + `gameEndedInEarlySurrender` on every
participant's stats block (same value game-wide). Surfacing-only - no
new fetch - so the Post Game Review hero can distinguish an FF'd loss
from a played-out one and badge a remake. Backward-compat: pre-existing
ingested matches lack the keys -> both flags must default False (never
KeyError, never None).

Synthetic-only - no DB, no live LCU.
"""
from __future__ import annotations

import unittest

from dashboard.builders import _enrich_from_lcu

_PUUID = "op-puuid-xyz"


def _detail(*, surrender=None, early=None, win=True):
    """Minimal 2-player LCU detail; the operator is participant 1.

    ``surrender`` / ``early`` left as None means the stats key is
    omitted entirely (the pre-s220-ingest backward-compat case).
    """
    stats = {"win": win, "champLevel": 11}
    if surrender is not None:
        stats["gameEndedInSurrender"] = surrender
    if early is not None:
        stats["gameEndedInEarlySurrender"] = early
    return {
        "gameId": 555,
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": _PUUID,
                                            "gameName": "Op"}},
            {"participantId": 2, "player": {"puuid": "other",
                                            "gameName": "Foe"}},
        ],
        "participants": [
            {"participantId": 1, "championId": 67, "teamId": 100,
             "spell1Id": 4, "spell2Id": 32, "stats": stats},
            {"participantId": 2, "championId": 84, "teamId": 200,
             "stats": {"win": not win}},
        ],
        "teams": [{"teamId": 100, "win": "Win" if win else "Fail"},
                  {"teamId": 200, "win": "Fail" if win else "Win"}],
    }


class SurrenderFlagTests(unittest.TestCase):
    def test_surrender_loss_flagged(self):
        out = _enrich_from_lcu(_detail(surrender=True, win=False), _PUUID)
        self.assertTrue(out["ended_in_surrender"])
        self.assertFalse(out["ended_in_early_surrender"])

    def test_early_surrender_remake_flagged(self):
        out = _enrich_from_lcu(
            _detail(surrender=True, early=True, win=False), _PUUID)
        self.assertTrue(out["ended_in_surrender"])
        self.assertTrue(out["ended_in_early_surrender"])

    def test_played_out_game_not_flagged(self):
        out = _enrich_from_lcu(_detail(surrender=False, win=True), _PUUID)
        self.assertFalse(out["ended_in_surrender"])
        self.assertFalse(out["ended_in_early_surrender"])

    def test_missing_keys_default_false_backward_compat(self):
        # Pre-s220 ingested rows have no surrender keys at all.
        out = _enrich_from_lcu(_detail(), _PUUID)
        self.assertIn("ended_in_surrender", out)
        self.assertIn("ended_in_early_surrender", out)
        self.assertFalse(out["ended_in_surrender"])
        self.assertFalse(out["ended_in_early_surrender"])

    def test_flags_are_real_bools(self):
        out = _enrich_from_lcu(_detail(surrender=1, early=0), _PUUID)
        self.assertIs(out["ended_in_surrender"], True)
        self.assertIs(out["ended_in_early_surrender"], False)


if __name__ == "__main__":
    unittest.main()
