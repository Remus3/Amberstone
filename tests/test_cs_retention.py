"""Tests for dashboard._cs_retention.apply_cs_retention.

Pins the contract that the dashboard holds the last non-empty
champ_select across the fast no-draft (ARAM / ARAM Mayhem / Arena)
champ-select -> game transition, where the Game-PC agent push goes
briefly stale or the LCU champ-select session 404s the instant the
game starts. Without retention the operator saw the champ-select
bench / quick-swap view blank for these modes (no ban/pick draft
phase to keep the window open long enough for the snapshot path's
~5s latency budget).

Pure function over an injected clock + module cache -> deterministic.
"""
from __future__ import annotations

import unittest

from dashboard import _cs_retention
from dashboard._cs_retention import apply_cs_retention, reset_cs_retention


def _cs(queue_id=450, **extra):
    base = {"queue_id": queue_id, "is_aram": True,
            "bench": [1, 2, 3], "phase": "BENCH"}
    base.update(extra)
    return base


class CacheAndPassthroughTests(unittest.TestCase):
    def setUp(self):
        reset_cs_retention()

    def test_fresh_cs_is_cached_and_passed_through(self):
        snap = {"phase": "ChampSelect", "champ_select": _cs(2400)}
        out = apply_cs_retention(snap, now=1000.0)
        # Unmodified passthrough when a real champ_select is present.
        self.assertEqual(out["champ_select"]["queue_id"], 2400)
        self.assertNotIn("_retained", out["champ_select"])
        self.assertEqual(_cs_retention._STATE["cs"]["queue_id"], 2400)

    def test_no_cache_no_cs_returns_input_unchanged(self):
        snap = {"phase": "InProgress"}
        out = apply_cs_retention(snap, now=1000.0)
        self.assertIs(out, snap)
        self.assertNotIn("champ_select", out)

    def test_none_input_safe(self):
        self.assertIsNone(apply_cs_retention(None, now=1.0))

    def test_empty_cs_dict_not_cached(self):
        # Agent stamps champ_select:{} on some cycles - that's "no
        # champ-select", must not poison the cache.
        apply_cs_retention({"phase": "InProgress", "champ_select": {}},
                           now=1000.0)
        self.assertEqual(_cs_retention._STATE["cs"], None)


class RetentionWindowTests(unittest.TestCase):
    def setUp(self):
        reset_cs_retention()
        apply_cs_retention(
            {"phase": "ChampSelect", "champ_select": _cs(2400)},
            now=1000.0)

    def test_cs_respliced_when_lost_during_transition(self):
        # Game flipped: champ_select gone, phase advanced. Within the
        # retention window the dashboard keeps the bench view alive.
        out = apply_cs_retention({"phase": "GameStart"}, now=1002.0)
        self.assertEqual(out["champ_select"]["queue_id"], 2400)
        self.assertTrue(out["champ_select"]["_retained"])
        self.assertEqual(out["phase"], "GameStart")

    def test_cs_respliced_when_snapshot_stale_empty(self):
        # lcu_summary() returns {} on >5s agent staleness - phase is
        # absent entirely. That IS the transient window: retain.
        out = apply_cs_retention({}, now=1003.0)
        self.assertEqual(out["champ_select"]["queue_id"], 2400)
        self.assertTrue(out["champ_select"]["_retained"])

    def test_cs_respliced_when_phase_still_champselect_but_cs_empty(self):
        # Highest-value case: phase IS ChampSelect but the agent's
        # capture cycle raced and pushed champ_select:{}. Fill it back.
        out = apply_cs_retention(
            {"phase": "ChampSelect", "champ_select": {}}, now=1004.0)
        self.assertEqual(out["champ_select"]["queue_id"], 2400)
        self.assertTrue(out["champ_select"]["_retained"])

    def test_fresh_cs_overrides_and_refreshes_cache(self):
        out = apply_cs_retention(
            {"phase": "ChampSelect", "champ_select": _cs(1700)},
            now=1005.0)
        self.assertEqual(out["champ_select"]["queue_id"], 1700)
        self.assertNotIn("_retained", out["champ_select"])
        # Subsequent loss retains the NEW one, not the stale 2400.
        out2 = apply_cs_retention({"phase": "GameStart"}, now=1006.0)
        self.assertEqual(out2["champ_select"]["queue_id"], 1700)


class ClearTests(unittest.TestCase):
    def setUp(self):
        reset_cs_retention()
        apply_cs_retention(
            {"phase": "ChampSelect", "champ_select": _cs(2400)},
            now=1000.0)

    def test_ttl_expiry_clears_and_stops_retaining(self):
        out = apply_cs_retention({"phase": "GameStart"}, now=1000.0 + 121.0)
        self.assertNotIn("champ_select", out)
        self.assertEqual(_cs_retention._STATE["cs"], None)

    def test_lobby_phase_clears_retention(self):
        # Operator dodged / backed out: LCU explicitly says Lobby.
        out = apply_cs_retention({"phase": "Lobby"}, now=1002.0)
        self.assertNotIn("champ_select", out)
        self.assertEqual(_cs_retention._STATE["cs"], None)

    def test_endofgame_phase_clears_retention(self):
        out = apply_cs_retention({"phase": "EndOfGame"}, now=1002.0)
        self.assertNotIn("champ_select", out)

    def test_string_none_phase_clears_retention(self):
        # gameflow-phase serializes to the literal string "None" when
        # no flow is active - that's a clear signal (distinct from a
        # Python-None phase which means stale snapshot -> retain).
        out = apply_cs_retention({"phase": "None"}, now=1002.0)
        self.assertNotIn("champ_select", out)

    def test_readycheck_phase_clears_retention(self):
        # Next queue popped -> previous champ-select is stale.
        out = apply_cs_retention({"phase": "ReadyCheck"}, now=1002.0)
        self.assertNotIn("champ_select", out)

    def test_post_clear_fresh_cs_recaches(self):
        apply_cs_retention({"phase": "Lobby"}, now=1002.0)
        out = apply_cs_retention(
            {"phase": "ChampSelect", "champ_select": _cs(450)},
            now=1003.0)
        self.assertEqual(out["champ_select"]["queue_id"], 450)
        out2 = apply_cs_retention({"phase": "GameStart"}, now=1004.0)
        self.assertEqual(out2["champ_select"]["queue_id"], 450)


class IsolationTests(unittest.TestCase):
    def setUp(self):
        reset_cs_retention()

    def test_retained_cs_is_deep_copied(self):
        src = _cs(2400)
        apply_cs_retention({"phase": "ChampSelect", "champ_select": src},
                           now=1000.0)
        out = apply_cs_retention({"phase": "GameStart"}, now=1001.0)
        out["champ_select"]["bench"].append(999)
        # Mutating the returned snapshot must not corrupt the cache.
        out2 = apply_cs_retention({"phase": "GameStart"}, now=1002.0)
        self.assertEqual(out2["champ_select"]["bench"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
