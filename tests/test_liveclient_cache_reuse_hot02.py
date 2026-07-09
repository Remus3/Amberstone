"""HOT-02 (2026-07-09): liveclient_summary reuses the shared cache frame.

``dashboard/_liveclient.py`` :: ``liveclient_summary`` used to do its own
``urlopen('.../latest-liveclient', timeout=1)`` on every /api/state build (~2/s)
while ``core.liveclient_cache`` already background-polls the SAME endpoint into
an immutable Snapshot. A stalled relay could hang the /api/state critical path
up to 1s despite a fresh cached frame.

The summary now sources the frame from ``core.liveclient_cache.get()``:
  * warm cache (data present, age <= 5s) -> parse it, NO per-build round-trip;
  * ``snap.data is None`` -> ``{}`` (no game / fetch failed);
  * stale (``age_s > 5``) -> ``{}`` (matches the old freshness contract).

This test proves parity when the cache is warm AND that urlopen is never hit on
that path (the redundant round-trip + 1s stall are gone).
"""
from __future__ import annotations

import time
import unittest
from unittest import mock

from core.liveclient_cache import Snapshot
from dashboard import _liveclient


def _agd(active="Ashe", game_time=725.0):
    """A realistic Live Client /allgamedata payload with the active player."""
    return {
        "activePlayer": {
            "summonerName": active,
            "level": 11,
            "currentGold": 1450,
            "championStats": {
                "currentHealth": 900, "maxHealth": 1200,
                "resourceValue": 250, "resourceMax": 400,
                "abilityHaste": 20, "moveSpeed": 330, "armor": 55,
                "magicResist": 40, "attackDamage": 180, "abilityPower": 0,
                "resourceType": "MANA",
            },
        },
        "allPlayers": [
            {
                "summonerName": active, "championName": active, "team": "ORDER",
                "items": [{"displayName": "Kraken Slayer", "itemID": 6672}],
                "scores": {"kills": 4, "deaths": 2, "assists": 6,
                           "creepScore": 142, "wardScore": 3.0},
            },
            {
                "summonerName": "Zed", "championName": "Zed", "team": "CHAOS",
                "items": [], "scores": {"kills": 3, "deaths": 4, "assists": 1,
                                        "creepScore": 120, "wardScore": 1.0},
            },
        ],
        "gameData": {"gameTime": game_time, "gameMode": "CLASSIC"},
    }


class WarmCacheParityTests(unittest.TestCase):
    def test_warm_cache_parses_frame(self) -> None:
        snap = Snapshot(data=_agd(), ts=time.time())
        with mock.patch("core.liveclient_cache.get", return_value=snap):
            out = _liveclient.liveclient_summary()
        self.assertEqual(out.get("game_time"), "12:05")
        self.assertEqual(out.get("game_time_s"), 725)
        self.assertEqual(out.get("level"), 11)
        self.assertEqual(out.get("gold"), 1450)
        self.assertEqual(out.get("hp"), 900)
        self.assertEqual(out.get("hp_max"), 1200)
        self.assertEqual(out.get("kda"), "4/2/6")
        self.assertEqual(out.get("cs"), 142)
        self.assertEqual(out.get("champion"), "Ashe")
        self.assertIn("Kraken Slayer", out.get("owned_items", []))

    def test_warm_cache_does_not_round_trip_urlopen(self) -> None:
        # The whole point of HOT-02: with a fresh cached frame the summary must
        # NOT open its own HTTP connection.
        snap = Snapshot(data=_agd(), ts=time.time())
        with mock.patch("core.liveclient_cache.get", return_value=snap), \
             mock.patch.object(_liveclient.urllib.request, "urlopen") as m_open:
            out = _liveclient.liveclient_summary()
        self.assertTrue(out, "warm cache should yield a non-empty summary")
        self.assertEqual(m_open.call_count, 0,
                         "liveclient_summary must not urlopen when cache is warm")


class ColdOrStaleCacheTests(unittest.TestCase):
    def test_no_data_returns_empty(self) -> None:
        snap = Snapshot(data=None, ts=0.0)
        with mock.patch("core.liveclient_cache.get", return_value=snap):
            self.assertEqual(_liveclient.liveclient_summary(), {})

    def test_stale_frame_returns_empty(self) -> None:
        # A frame older than 5s is treated as "not in a game", same as before.
        snap = Snapshot(data=_agd(), ts=time.time() - 10.0)
        with mock.patch("core.liveclient_cache.get", return_value=snap):
            self.assertEqual(_liveclient.liveclient_summary(), {})

    def test_stale_frame_does_not_round_trip(self) -> None:
        snap = Snapshot(data=_agd(), ts=time.time() - 10.0)
        with mock.patch("core.liveclient_cache.get", return_value=snap), \
             mock.patch.object(_liveclient.urllib.request, "urlopen") as m_open:
            _liveclient.liveclient_summary()
        self.assertEqual(m_open.call_count, 0)


class LcuSummaryUntouchedTests(unittest.TestCase):
    def test_lcu_summary_still_has_its_own_fetch(self) -> None:
        # HOT-02 must NOT touch lcu_summary (the cache does not poll /latest-lcu).
        # A cache-get patch that would break a cache-sourced call must leave
        # lcu_summary returning {} via its own (unmocked, unreachable) urlopen.
        with mock.patch.object(
            _liveclient.urllib.request, "urlopen", side_effect=OSError("no relay")
        ):
            self.assertEqual(_liveclient.lcu_summary(), {})


if __name__ == "__main__":
    unittest.main()
