"""Tests for ``core/ward_producer.py`` - the allPlayers inventory-delta
producer that feeds ``core.ward_events.record_ward``.

Covers:
  * First tick after reset: 0 records, state initialized
  * Control ward count decrement -> 1 record per delta
  * Control ward 2 -> 0 -> 2 records in one tick
  * Yellow trinket canUse True -> False -> 1 record
  * Farsight (blue trinket) canUse True -> False -> 1 record
  * Sweeper (3364) does NOT register (excluded; not a ward)
  * No change tick -> 0 records
  * Game shape change (different allPlayers) -> state cleared, 0 records
  * Lane mapping: position TOP/MIDDLE/BOTTOM/UTILITY/JUNGLE -> top/mid/bot/bot/jg
  * Side resolution with explicit active_summoner -> proper ally/enemy split
  * Side fallback ORDER=ally / CHAOS=enemy when no active_summoner
  * canUse False -> True (cooldown finish) is ignored
  * Multi-player tick: each player's deltas counted independently
  * Reset clears state; subsequent tick is a fresh baseline
  * Malformed input (None, non-list, non-dict players) doesn't crash
"""
from __future__ import annotations

import unittest

from core import ward_events, ward_producer


def _player(name: str, team: str = "ORDER", position: str = "MIDDLE",
            items: list | None = None) -> dict:
    return {
        "summonerName": name,
        "team":         team,
        "position":     position,
        "items":        items or [],
    }


def _ward_item(item_id: int, count: int = 1, can_use: bool = True) -> dict:
    return {"itemID": item_id, "count": count, "canUse": can_use, "slot": 6}


class ProducerBase(unittest.TestCase):
    def setUp(self):
        ward_events.reset()
        ward_producer.reset()


class FirstTickTests(ProducerBase):
    def test_first_tick_no_records(self):
        players = [_player("Alice", items=[_ward_item(3340)])]
        n = ward_producer.tick(players, ts=100.0)
        self.assertEqual(n, 0)
        # State is seeded - subsequent tick is the diff baseline.
        self.assertEqual(ward_producer.snapshot_size(), 1)

    def test_first_tick_empty_buffer(self):
        ward_producer.tick([_player("Alice", items=[_ward_item(3340)])], ts=100.0)
        self.assertEqual(ward_events.buffer_size(), 0)


class ControlWardTests(ProducerBase):
    def test_control_ward_decrement(self):
        # Tick 1: Alice has 2 control wards.
        players_t1 = [_player("Alice", items=[_ward_item(2055, count=2)])]
        ward_producer.tick(players_t1, ts=100.0)
        # Tick 2: down to 1 control ward.
        players_t2 = [_player("Alice", items=[_ward_item(2055, count=1)])]
        n = ward_producer.tick(players_t2, ts=101.0)
        self.assertEqual(n, 1)
        snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["ward_type"], "control")

    def test_control_ward_two_to_zero(self):
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(2055, count=2)])],
            ts=100.0,
        )
        # 2 -> 0 -> 2 placements detected in one tick.
        n = ward_producer.tick(
            [_player("Alice", items=[])],
            ts=101.0,
        )
        self.assertEqual(n, 2)
        snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
        self.assertEqual(len(snap), 2)
        self.assertTrue(all(e["ward_type"] == "control" for e in snap))

    def test_control_ward_no_change(self):
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(2055, count=2)])],
            ts=100.0,
        )
        n = ward_producer.tick(
            [_player("Alice", items=[_ward_item(2055, count=2)])],
            ts=101.0,
        )
        self.assertEqual(n, 0)


class YellowTrinketTests(ProducerBase):
    def test_yellow_trinket_cast(self):
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340, can_use=True)])],
            ts=100.0,
        )
        n = ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340, can_use=False)])],
            ts=101.0,
        )
        self.assertEqual(n, 1)
        snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
        self.assertEqual(snap[0]["ward_type"], "yellow")

    def test_yellow_trinket_cooldown_finish_ignored(self):
        # Trinket goes from "on cooldown" to "ready" - that's NOT a placement.
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340, can_use=False)])],
            ts=100.0,
        )
        n = ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340, can_use=True)])],
            ts=101.0,
        )
        self.assertEqual(n, 0)


class FarsightTests(ProducerBase):
    def test_farsight_cast(self):
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(3363, can_use=True)])],
            ts=100.0,
        )
        n = ward_producer.tick(
            [_player("Alice", items=[_ward_item(3363, can_use=False)])],
            ts=101.0,
        )
        self.assertEqual(n, 1)
        snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
        self.assertEqual(snap[0]["ward_type"], "farsight")


class SweeperExcludedTests(ProducerBase):
    def test_sweeper_3364_not_a_ward(self):
        # Oracle Sweeper REVEALS, does not place. Must not register.
        ward_producer.tick(
            [_player("Alice", items=[{"itemID": 3364, "count": 1,
                                       "canUse": True, "slot": 6}])],
            ts=100.0,
        )
        n = ward_producer.tick(
            [_player("Alice", items=[{"itemID": 3364, "count": 1,
                                       "canUse": False, "slot": 6}])],
            ts=101.0,
        )
        self.assertEqual(n, 0)
        self.assertEqual(ward_events.buffer_size(), 0)


class GameShapeChangeTests(ProducerBase):
    def test_game_restart_clears_state(self):
        # Game 1 lobby
        ward_producer.tick(
            [_player("Alice"), _player("Bob")],
            ts=100.0,
        )
        self.assertEqual(ward_producer.snapshot_size(), 2)
        # Game 2 lobby - different roster -> state clears, this tick
        # becomes a new baseline and returns 0.
        n = ward_producer.tick(
            [_player("Carol"), _player("Dan")],
            ts=200.0,
        )
        self.assertEqual(n, 0)
        # After auto-reset + reseed the snapshot reflects the new roster.
        self.assertEqual(ward_producer.snapshot_size(), 2)


class LaneMappingTests(ProducerBase):
    def test_position_to_lane(self):
        positions = [
            ("TOP",     "top"),
            ("MIDDLE",  "mid"),
            ("BOTTOM",  "bot"),
            ("UTILITY", "bot"),
            ("JUNGLE",  "jg"),
            ("NONE",    "unknown"),
        ]
        for pos, expected_lane in positions:
            with self.subTest(position=pos):
                ward_events.reset()
                ward_producer.reset()
                ward_producer.tick(
                    [_player("X", position=pos,
                             items=[_ward_item(3340, can_use=True)])],
                    ts=100.0,
                )
                ward_producer.tick(
                    [_player("X", position=pos,
                             items=[_ward_item(3340, can_use=False)])],
                    ts=101.0,
                )
                snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
                self.assertEqual(len(snap), 1)
                self.assertEqual(snap[0]["lane"], expected_lane)


class SideResolutionTests(ProducerBase):
    def test_active_summoner_resolves_team(self):
        # Operator is on CHAOS. Operator's teammates -> ally, ORDER -> enemy.
        players_t1 = [
            _player("Me",  team="CHAOS", items=[_ward_item(3340, can_use=True)]),
            _player("Foe", team="ORDER", items=[_ward_item(3340, can_use=True)]),
        ]
        players_t2 = [
            _player("Me",  team="CHAOS", items=[_ward_item(3340, can_use=False)]),
            _player("Foe", team="ORDER", items=[_ward_item(3340, can_use=False)]),
        ]
        ward_producer.tick(players_t1, ts=100.0, active_summoner="Me")
        ward_producer.tick(players_t2, ts=101.0, active_summoner="Me")
        snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
        sides = sorted(e["side"] for e in snap)
        self.assertEqual(sides, ["ally", "enemy"])

    def test_no_active_summoner_falls_back(self):
        # No active_summoner -> ORDER=ally, CHAOS=enemy.
        players_t1 = [
            _player("A", team="ORDER", items=[_ward_item(2055, count=2)]),
            _player("B", team="CHAOS", items=[_ward_item(2055, count=2)]),
        ]
        players_t2 = [
            _player("A", team="ORDER", items=[_ward_item(2055, count=1)]),
            _player("B", team="CHAOS", items=[_ward_item(2055, count=1)]),
        ]
        ward_producer.tick(players_t1, ts=100.0)
        ward_producer.tick(players_t2, ts=101.0)
        snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
        by_name_side = {e["side"] for e in snap}
        self.assertEqual(by_name_side, {"ally", "enemy"})


class MultiPlayerTickTests(ProducerBase):
    def test_independent_per_player_deltas(self):
        # 4 players, 3 of them place wards in a single tick.
        players_t1 = [
            _player("A", items=[_ward_item(3340, can_use=True)]),
            _player("B", items=[_ward_item(2055, count=2)]),
            _player("C", items=[_ward_item(3363, can_use=True)]),
            _player("D", items=[_ward_item(3340, can_use=True)]),
        ]
        players_t2 = [
            _player("A", items=[_ward_item(3340, can_use=False)]),     # placed yellow
            _player("B", items=[_ward_item(2055, count=1)]),            # placed control
            _player("C", items=[_ward_item(3363, can_use=False)]),     # placed farsight
            _player("D", items=[_ward_item(3340, can_use=True)]),      # nothing
        ]
        ward_producer.tick(players_t1, ts=100.0)
        n = ward_producer.tick(players_t2, ts=101.0)
        self.assertEqual(n, 3)
        snap = ward_events.recent_wards(now_s=101.0, window_s=90.0)
        types = sorted(e["ward_type"] for e in snap)
        self.assertEqual(types, ["control", "farsight", "yellow"])


class ResetTests(ProducerBase):
    def test_reset_clears_state(self):
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340)])],
            ts=100.0,
        )
        self.assertEqual(ward_producer.snapshot_size(), 1)
        ward_producer.reset()
        self.assertEqual(ward_producer.snapshot_size(), 0)

    def test_after_reset_first_tick_is_baseline(self):
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340, can_use=True)])],
            ts=100.0,
        )
        ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340, can_use=False)])],
            ts=101.0,
        )
        # Confirm baseline behaviour: one record landed.
        self.assertEqual(ward_events.buffer_size(), 1)
        ward_producer.reset()
        # First tick post-reset is a baseline; no record even though the
        # canUse value matches a "False" state.
        n = ward_producer.tick(
            [_player("Alice", items=[_ward_item(3340, can_use=True)])],
            ts=102.0,
        )
        self.assertEqual(n, 0)


class MalformedInputTests(ProducerBase):
    def test_none_input(self):
        self.assertEqual(ward_producer.tick(None, ts=100.0), 0)

    def test_non_list_input(self):
        self.assertEqual(ward_producer.tick({"not": "a list"}, ts=100.0), 0)

    def test_non_dict_player_entries_skipped(self):
        n = ward_producer.tick(
            ["string", 42, None, _player("Alice", items=[_ward_item(3340)])],
            ts=100.0,
        )
        self.assertEqual(n, 0)
        self.assertEqual(ward_producer.snapshot_size(), 1)

    def test_missing_items_array(self):
        n = ward_producer.tick(
            [{"summonerName": "Alice", "team": "ORDER", "position": "MIDDLE"}],
            ts=100.0,
        )
        self.assertEqual(n, 0)

    def test_player_with_no_summoner_name_skipped(self):
        n = ward_producer.tick(
            [{"team": "ORDER", "items": [_ward_item(3340)]}],
            ts=100.0,
        )
        self.assertEqual(n, 0)
        self.assertEqual(ward_producer.snapshot_size(), 0)


if __name__ == "__main__":
    unittest.main()
