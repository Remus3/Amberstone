"""Tests for liveclient_summary enemy_spells + stats fields (overlay slices 4 / 4b,
2026-06-28).

enemy_spells: per-enemy {champion, spells:[name,name]} from allPlayers[].
summonerSpells - the manual spell tap-tracker's roster (the API exposes spell
NAMES but no live cooldown, so the overlay tracker is tap-driven).

stats: the API-backed championStats the overlay stats mini-panel renders (a HUD
replacement is impossible - no live cooldowns/buffs/wards in the API).

Same cache-seed harness as test_liveclient_kp.py (HOT-02, 2026-07-09:
liveclient_summary reads the shared core.liveclient_cache Snapshot).
"""
from __future__ import annotations

import contextlib
import time
import unittest
from unittest import mock

from dashboard import _liveclient


def _player(name: str, team: str, spell1: str = "", spell2: str = "") -> dict:
    return {
        "summonerName": name,
        "championName": name,
        "team": team,
        "items": [],
        "scores": {"kills": 0, "deaths": 0, "assists": 0,
                   "creepScore": 0, "wardScore": 0.0},
        "summonerSpells": {
            "summonerSpellOne": {"displayName": spell1},
            "summonerSpellTwo": {"displayName": spell2},
        },
    }


def _agd(active: str, players: list, stats: dict | None = None) -> dict:
    cstats = {"currentHealth": 800, "maxHealth": 1000,
              "resourceValue": 200, "resourceMax": 300}
    cstats.update(stats or {})
    return {
        "activePlayer": {
            "summonerName": active, "level": 9, "currentGold": 1200,
            "championStats": cstats,
        },
        "allPlayers": players,
        "gameData": {"gameTime": 600.0, "gameMode": "CLASSIC"},
    }


@contextlib.contextmanager
def _patched(agd):
    # HOT-02 (2026-07-09): seed the shared liveclient cache Snapshot the summary
    # now reads, instead of mocking a per-call urlopen.
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=agd, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        yield


def _summary(agd) -> dict:
    with _patched(agd):
        return _liveclient.liveclient_summary()


class EnemySpellsTests(unittest.TestCase):
    def test_only_enemies_with_spell_names(self):
        players = [
            _player("Ashe", "ORDER", "Flash", "Heal"),   # active (ally)
            _player("Zed", "CHAOS", "Flash", "Ignite"),
            _player("Lux", "CHAOS", "Flash", "Barrier"),
        ]
        es = _summary(_agd("Ashe", players)).get("enemy_spells")
        self.assertEqual(len(es), 2, "only the 2 enemies, not the ally")
        self.assertEqual({e["champion"] for e in es}, {"Zed", "Lux"})
        zed = next(e for e in es if e["champion"] == "Zed")
        self.assertEqual(zed["spells"], ["Flash", "Ignite"])

    def test_empty_when_active_unresolvable(self):
        players = [_player("Lux", "CHAOS", "Flash", "Barrier")]
        out = _summary(_agd("GhostName", players))
        self.assertEqual(out.get("enemy_spells"), [])

    def test_missing_summonerspells_degrades_to_blank(self):
        p = _player("Zed", "CHAOS")
        del p["summonerSpells"]
        players = [_player("Ashe", "ORDER", "Flash", "Heal"), p]
        es = _summary(_agd("Ashe", players)).get("enemy_spells")
        self.assertEqual(es[0]["spells"], ["", ""])  # blank, no raise


class StatsTests(unittest.TestCase):
    def test_stats_from_championstats(self):
        players = [_player("Ashe", "ORDER", "Flash", "Heal")]
        st = _summary(_agd("Ashe", players, stats={
            "abilityHaste": 25, "moveSpeed": 345, "armor": 80,
            "magicResist": 52, "attackDamage": 210, "abilityPower": 0,
            "resourceType": "MANA",
        })).get("stats")
        self.assertEqual(st["ability_haste"], 25)
        self.assertEqual(st["move_speed"], 345)
        self.assertEqual(st["armor"], 80)
        self.assertEqual(st["magic_resist"], 52)
        self.assertEqual(st["resource_type"], "MANA")

    def test_stats_default_zero_when_absent(self):
        players = [_player("Ashe", "ORDER", "Flash", "Heal")]
        st = _summary(_agd("Ashe", players)).get("stats")
        self.assertEqual(st["ability_haste"], 0)
        self.assertEqual(st["move_speed"], 0)


class AsciiHygieneTests(unittest.TestCase):
    def test_self_is_ascii(self):
        from pathlib import Path
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
