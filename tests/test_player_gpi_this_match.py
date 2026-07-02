"""Tests for the ``this_match`` per-axis block in core.player_gpi (OQ15 A).

Every sufficient-history payload carries ``this_match`` - the NEWEST filtered
game scored per relative axis (midrank percentile vs the FULL history) so the
radar can overlay "this game" on the longitudinal profile. The two window-shape
axes (versatility / consistency) have no single-game meaning and ride along
with score/value None to keep the overlay index-aligned with ``axes``.

Hermetic: reuses ``_Builder`` from tests.test_player_gpi (in-memory rewind DB)
and ``_RewindDbFixture`` / ``_RouteHarness`` from tests.test_routes_player_profile
(disk DB + RC_REWIND_DB env dance) - imported, never edited.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from core import player_gpi
from dashboard import routes_player_profile
from tests.test_player_gpi import _Builder
from tests.test_routes_player_profile import _RewindDbFixture, _RouteHarness


class ThisMatchShapeTests(unittest.TestCase):
    """12 games, newest on a distinct champion - block identity + axis order."""

    @classmethod
    def setUpClass(cls):
        b = _Builder()
        for _ in range(11):
            b.add(champ=22, dmg=9000)
        b.add(champ=64, dmg=27000)
        cls.b = b
        cls.res = player_gpi.compute_gpi(mode="sr", conn=b.conn)

    @classmethod
    def tearDownClass(cls):
        cls.b.close()

    def test_block_identity_fields_from_newest_game(self):
        tm = self.res["this_match"]
        self.assertIsNotNone(tm)
        # _Builder mids are M1..M12 with game_creation_ts 1..12; newest = last add.
        self.assertEqual(tm["match_id"], "M12")
        self.assertEqual(tm["champion_id"], 64)
        self.assertEqual(tm["game_creation_ts"], 12)

    def test_axes_positionally_mirror_payload_axes(self):
        tm_keys = [a["key"] for a in self.res["this_match"]["axes"]]
        payload_keys = [a["key"] for a in self.res["axes"]]
        self.assertEqual(len(tm_keys), 8)
        self.assertEqual(tm_keys, payload_keys)

    def test_axis_entries_carry_only_key_score_value(self):
        for a in self.res["this_match"]["axes"]:
            self.assertEqual(set(a.keys()), {"key", "score", "value"})

    def test_shape_axes_score_and_value_are_none(self):
        by = {a["key"]: a for a in self.res["this_match"]["axes"]}
        for key in ("versatility", "consistency"):
            self.assertIsNone(by[key]["score"])
            self.assertIsNone(by[key]["value"])


class ThisMatchPercentileTests(unittest.TestCase):
    def test_hand_computed_midrank_percentile(self):
        # 11 games at 9000 dmg / 30 min = 300 dpm, newest 27000 -> 900 dpm.
        # Midrank of the unique max in n=12: (11 + 12) / (2 * 12) -> 95.8.
        b = _Builder()
        for _ in range(11):
            b.add(dmg=9000, dur_s=1800)
        b.add(dmg=27000, dur_s=1800)
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        by = {a["key"]: a for a in res["this_match"]["axes"]}
        self.assertEqual(by["aggression"]["score"], 95.8)
        self.assertEqual(by["aggression"]["value"], 900.0)
        b.close()

    def test_all_ties_score_fifty(self):
        # 12 identical games: every relative-axis midrank collapses to 0.5.
        b = _Builder()
        for _ in range(12):
            b.add()
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        for a in res["this_match"]["axes"]:
            if a["key"] in ("versatility", "consistency"):
                continue
            self.assertEqual(a["score"], 50.0, a["key"])
        b.close()

    def test_survival_inverts_deaths_direction(self):
        # Newest game has the FEWEST deaths -> best (highest) survival score,
        # even though the raw metric (deaths/min) is the lowest.
        b = _Builder()
        for _ in range(11):
            b.add(deaths=12)
        b.add(deaths=1)
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        by = {a["key"]: a for a in res["this_match"]["axes"]}
        self.assertGreater(by["survival"]["score"], 90)
        b.close()


class ThisMatchInsufficientTests(unittest.TestCase):
    def test_below_min_games_is_none(self):
        b = _Builder()
        for _ in range(player_gpi.MIN_GAMES - 1):
            b.add()
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        self.assertEqual(res["confidence"], "insufficient")
        self.assertIsNone(res["this_match"])
        b.close()


class ThisMatchChampionFilterTests(unittest.TestCase):
    def test_champion_filter_scopes_newest_game(self):
        # Champ-22 games are OLDER (added first); the champion=22 drilldown must
        # surface the newest champ-22 game, not the newest game overall.
        b = _Builder()
        for _ in range(12):
            b.add(champ=22)
        for _ in range(12):
            b.add(champ=64)
        res = player_gpi.compute_gpi(mode="sr", champion=22, conn=b.conn)
        tm = res["this_match"]
        self.assertEqual(tm["match_id"], "M12")
        self.assertEqual(tm["champion_id"], 22)
        b.close()


class ThisMatchRouteTests(unittest.TestCase):
    """this_match passes through /api/player-profile untouched, cache included."""

    @classmethod
    def setUpClass(cls):
        cls._fix = _RewindDbFixture(sr_games=12, champ=22)
        cls._fix.start()

    @classmethod
    def tearDownClass(cls):
        cls._fix.stop()

    def setUp(self):
        routes_player_profile._reset_caches()

    def test_route_pass_through_and_cache(self):
        h1 = _RouteHarness("")
        routes_player_profile._serve_player_profile(h1)
        self.assertEqual(h1.sent_status, 200)
        p1 = json.loads(h1.sent_body)
        self.assertFalse(p1["cached"])

        h2 = _RouteHarness("")
        routes_player_profile._serve_player_profile(h2)
        self.assertEqual(h2.sent_status, 200)
        p2 = json.loads(h2.sent_body)
        self.assertTrue(p2["cached"])

        self.assertIsNotNone(p1["this_match"])
        self.assertEqual(p1["this_match"], p2["this_match"])


class AsciiHygieneTests(unittest.TestCase):
    def test_touched_files_are_pure_ascii(self):
        # Repo hard rule: authored content stays 7-bit ASCII (no em/en dashes,
        # no smart quotes). Byte-level check catches any drift.
        root = Path(__file__).resolve().parents[1]
        for target in (Path(__file__).resolve(),
                       root / "core" / "player_gpi.py"):
            data = target.read_bytes()
            bad = sorted({b for b in data if b > 0x7F})
            self.assertEqual(bad, [], f"non-ASCII bytes {bad} in {target}")


if __name__ == "__main__":
    unittest.main()
