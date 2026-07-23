"""Tests for the ``reference`` target-profile block in core.player_gpi.

The GPI radar draws the operator's recent-form polygon. The reference block is
the SECOND polygon drawn behind it: the same 8 axes scored over the operator's
own WINNING games, so the radar answers "what does my game look like when I
win" without any external cohort.

Ground truth (probed 2026-07-23): rewind_history.db is tracked-player-only for
longitudinal purposes - 23441 distinct puuids over 30928 participant rows, only
20 puuids with >= 20 games (the operator plus a handful of premades). A global
better-win-rate cohort is NOT derivable, so the reference is the operator's own
wins by construction, not by convenience.

Scoring parity with the player polygon is the whole point:
  - the percentile baseline stays the FULL filtered history (same as ``axes``),
  - the reference "recent" set is the most recent ``window`` WINS, so the two
    window-shape axes (versatility / consistency) compare at equal n and are
    not biased by the log(n) entropy normalization.

Hermetic: reuses ``_Builder`` from tests.test_player_gpi (in-memory rewind DB)
and the disk-DB route harness from tests.test_routes_player_profile - imported,
never edited.
"""
from __future__ import annotations

import json
import unittest

from core import player_gpi
from dashboard import routes_player_profile
from tests.test_player_gpi import _Builder
from tests.test_routes_player_profile import _RewindDbFixture, _RouteHarness


class ReferenceShapeTests(unittest.TestCase):
    """12 losses (low output) + 12 wins (high output) -> the reference polygon
    must sit clearly ABOVE the all-games player polygon on the output axes."""

    @classmethod
    def setUpClass(cls):
        b = _Builder()
        # 12 losing games: low damage / gold / cs, many deaths.
        for _ in range(12):
            b.add(champ=22, dmg=9000, deaths=12, cs=120, vis=12, gold=9000,
                  obj=0, kills=2, assists=4, win=0)
        # 12 winning games: high damage / gold / cs, few deaths.
        for _ in range(12):
            b.add(champ=22, dmg=27000, deaths=3, cs=240, vis=42, gold=18000,
                  obj=4, kills=9, assists=7, win=1)
        cls.b = b
        # window 24 == the whole history, so the player polygon is the mean of
        # wins AND losses while the reference is wins only.
        cls.res = player_gpi.compute_gpi(mode="sr", window=24, conn=b.conn)

    @classmethod
    def tearDownClass(cls):
        cls.b.close()

    def test_block_present_with_kind_and_n(self):
        ref = self.res["reference"]
        self.assertIsNotNone(ref)
        self.assertEqual(ref["kind"], "own_wins")
        self.assertEqual(ref["n"], 12)
        self.assertEqual(ref["min_games"], player_gpi.MIN_REFERENCE_GAMES)

    def test_axes_positionally_mirror_payload_axes(self):
        ref_keys = [a["key"] for a in self.res["reference"]["axes"]]
        payload_keys = [a["key"] for a in self.res["axes"]]
        self.assertEqual(len(ref_keys), 8)
        self.assertEqual(ref_keys, payload_keys)

    def test_axis_entries_carry_only_key_and_score(self):
        for a in self.res["reference"]["axes"]:
            self.assertEqual(set(a.keys()), {"key", "score"})

    def test_every_axis_score_is_a_number_in_range(self):
        for a in self.res["reference"]["axes"]:
            self.assertIsInstance(a["score"], float, a["key"])
            self.assertGreaterEqual(a["score"], 0.0, a["key"])
            self.assertLessEqual(a["score"], 100.0, a["key"])

    def test_wins_outrank_the_all_games_polygon_on_output_axes(self):
        player = {a["key"]: a["score"] for a in self.res["axes"]}
        ref = {a["key"]: a["score"] for a in self.res["reference"]["axes"]}
        for key in ("aggression", "farming", "vision", "objectives", "tempo"):
            self.assertGreater(ref[key], player[key], key)

    def test_survival_axis_inverts_for_the_reference_too(self):
        # Winning games have FEWER deaths -> the lower-is-better survival axis
        # must still score HIGHER for the reference (sign handling shared).
        player = {a["key"]: a["score"] for a in self.res["axes"]}
        ref = {a["key"]: a["score"] for a in self.res["reference"]["axes"]}
        self.assertGreater(ref["survival"], player["survival"])


class ReferenceThinHistoryTests(unittest.TestCase):
    """Below MIN_REFERENCE_GAMES wins -> reference is None, never a partial or
    degenerate polygon; the rest of the payload is untouched."""

    def test_too_few_wins_yields_none(self):
        b = _Builder()
        for _ in range(14):
            b.add(champ=22, win=0)
        for _ in range(player_gpi.MIN_REFERENCE_GAMES - 1):
            b.add(champ=22, win=1)
        try:
            res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
            self.assertTrue(res["ok"])
            self.assertIsNone(res["reference"])
            self.assertEqual(len(res["axes"]), 8)
        finally:
            b.close()

    def test_exactly_min_wins_yields_a_block(self):
        b = _Builder()
        for _ in range(14):
            b.add(champ=22, win=0)
        for _ in range(player_gpi.MIN_REFERENCE_GAMES):
            b.add(champ=22, win=1)
        try:
            res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
            self.assertIsNotNone(res["reference"])
            self.assertEqual(res["reference"]["n"],
                             player_gpi.MIN_REFERENCE_GAMES)
        finally:
            b.close()

    def test_zero_wins_yields_none(self):
        b = _Builder()
        for _ in range(14):
            b.add(champ=22, win=0)
        try:
            self.assertIsNone(player_gpi.compute_gpi(mode="sr",
                                                     conn=b.conn)["reference"])
        finally:
            b.close()

    def test_insufficient_history_payload_carries_the_key_as_none(self):
        b = _Builder()
        for _ in range(3):
            b.add(champ=22, win=1)
        try:
            res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
            self.assertEqual(res["confidence"], "insufficient")
            self.assertIn("reference", res)
            self.assertIsNone(res["reference"])
        finally:
            b.close()


class ReferenceWindowTests(unittest.TestCase):
    """The reference "recent" set is capped at ``window`` wins so the shape
    axes compare at equal n against the player polygon."""

    def test_n_is_capped_at_window(self):
        b = _Builder()
        for _ in range(30):
            b.add(champ=22, win=1)
        try:
            res = player_gpi.compute_gpi(mode="sr", window=10, conn=b.conn)
            self.assertEqual(res["reference"]["n"], 10)
        finally:
            b.close()

    def test_all_wins_history_matches_the_player_polygon(self):
        # Every game is a win and window covers them all -> the reference set
        # IS the player window, so all eight axes must agree exactly.
        b = _Builder()
        for i in range(12):
            b.add(champ=(20 + i % 3), dmg=9000 + 500 * i, win=1)
        try:
            res = player_gpi.compute_gpi(mode="sr", window=12, conn=b.conn)
            player = {a["key"]: a["score"] for a in res["axes"]}
            ref = {a["key"]: a["score"] for a in res["reference"]["axes"]}
            self.assertEqual(player, ref)
        finally:
            b.close()


class ReferenceRouteTests(unittest.TestCase):
    """/api/player-profile passes the block through untouched, cache included.

    ``_build_db`` behind _RewindDbFixture writes wins (the _Builder default),
    so the served payload exercises the populated-reference path end to end.
    """

    @classmethod
    def setUpClass(cls):
        cls._fix = _RewindDbFixture(sr_games=20, champ=22)
        cls._fix.start()

    @classmethod
    def tearDownClass(cls):
        cls._fix.stop()

    def setUp(self):
        routes_player_profile._reset_caches()

    def test_route_payload_carries_reference(self):
        h = _RouteHarness("mode=sr")
        routes_player_profile._serve_player_profile(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body.decode("utf-8"))
        self.assertIn("reference", payload)
        self.assertIsNotNone(payload["reference"])
        self.assertEqual(payload["reference"]["kind"], "own_wins")
        self.assertEqual(len(payload["reference"]["axes"]), 8)
        ref_keys = [a["key"] for a in payload["reference"]["axes"]]
        self.assertEqual(ref_keys, [a["key"] for a in payload["axes"]])

    def test_cached_serve_keeps_the_block(self):
        h1 = _RouteHarness("mode=sr")
        routes_player_profile._serve_player_profile(h1)
        first = json.loads(h1.sent_body.decode("utf-8"))
        h2 = _RouteHarness("mode=sr")
        routes_player_profile._serve_player_profile(h2)
        second = json.loads(h2.sent_body.decode("utf-8"))
        self.assertTrue(second["cached"])
        self.assertEqual(second["reference"], first["reference"])


if __name__ == "__main__":
    unittest.main()
