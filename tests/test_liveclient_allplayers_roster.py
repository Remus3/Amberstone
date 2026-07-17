"""Tests for the raw ``allPlayers`` + ``activePlayer`` roster surfaced by
``dashboard/_liveclient.py`` :: ``liveclient_summary`` (RM-02 counter-hint
live-plumbing fix, 2026-07-17).

Background
----------
The in-game BUILD panel's counter-hint chips (C2 antiheal / C6 tenacity /
C3 fed / R102 enemy-profile / R103 situational counter-build) are driven by
``web/js/panels/active_match.js``. Those consumers key on ``lc.allPlayers``:

  * ``_resolveMyTeam(lc)``       - needs ``lc.activePlayer.summonerName`` (or
                                    ``riotIdGameName``) + each player's
                                    ``team`` + ``summonerName``/``riotIdGameName``
                                    to split allies from enemies.
  * ``_extractBpEnemies``        - reads enemy ``championName`` + ``items[].itemID``.
  * ``_extractBpAllyItems``      - reads MY-team ``items[].itemID`` (C2 de-dup).
  * ``_extractBpEnemyStats``     - reads enemy ``scores{kills,deaths,assists}``
                                    + ``level`` (C3 fed).

The summary derived ``enemy_team`` / ``enemy_item_ids`` / ``players`` but never
surfaced the raw ``allPlayers`` roster, so in LIVE games ``_hasRoster`` was
always false and the chips rendered only under ``?ui_mock=1``. This suite pins
the contract: ``liveclient_summary()`` must emit a lean ``allPlayers`` list (a
faithful superset of the ui_mock fixture shape - it adds the live-only
``scores`` + ``level`` fields the C3 fed path needs) plus an ``activePlayer``
identity block.

Harness mirrors ``test_liveclient_kp.py``: the shared ``core.liveclient_cache``
Snapshot is seeded (``mock.patch`` on ``liveclient_cache.get``) with a realistic
``allgamedata`` frame; ``ts=time.time()`` passes the 5 s freshness gate.
"""
from __future__ import annotations

import contextlib
import io
import time
import unittest
from unittest import mock

from dashboard import _liveclient


def _player(name: str, team: str, champ: str | None = None,
            kills: int = 0, deaths: int = 0, assists: int = 0,
            level: int = 1, item_ids: list | None = None) -> dict:
    """A single raw Live Client allPlayers entry.

    Mirrors the /allgamedata shape: championName + rawChampionName + team +
    summonerName, a per-player scores block, an items list of {itemID, slot}
    dicts, and a per-player level (all present on the real frame).
    """
    champ = champ or name
    items = [{"itemID": iid, "slot": i}
             for i, iid in enumerate(item_ids or [])]
    return {
        "summonerName": name,
        "riotIdGameName": name,
        "championName": champ,
        "rawChampionName": champ,
        "team": team,
        "level": level,
        "items": items,
        "scores": {
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "creepScore": 0,
            "wardScore": 0.0,
        },
    }


def _allgamedata(active_name: str, players: list,
                 game_time: float = 600.0) -> dict:
    """A minimal but realistic Live Client /allgamedata payload."""
    return {
        "activePlayer": {
            "summonerName": active_name,
            "riotIdGameName": active_name,
            "level": 9,
            "currentGold": 1200,
            "championStats": {
                "currentHealth": 800,
                "maxHealth": 1000,
                "resourceValue": 200,
                "resourceMax": 300,
            },
        },
        "allPlayers": players,
        "gameData": {
            "gameTime": game_time,
            "gameMode": "CLASSIC",
        },
    }


@contextlib.contextmanager
def _patched(allgamedata, ts=None):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=allgamedata, ts=time.time() if ts is None else ts)
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        yield


def _summary(allgamedata, ts=None) -> dict:
    with _patched(allgamedata, ts=ts):
        return _liveclient.liveclient_summary()


# A full 10-player roster: active player (Ashe) on ORDER, 5 CHAOS enemies
# carrying items + scores + levels so every consumer path has real data.
def _full_roster() -> list:
    return [
        _player("Ashe", "ORDER", kills=3, deaths=1, assists=5, level=11,
                item_ids=[3006, 3031]),
        _player("Leona", "ORDER", kills=1, deaths=2, assists=9, level=10,
                item_ids=[3047, 3190]),
        _player("Garen", "ORDER", kills=4, deaths=1, assists=2, level=12,
                item_ids=[3071]),
        _player("Lux", "ORDER", kills=2, deaths=3, assists=6, level=11,
                item_ids=[6653]),
        _player("Lee Sin", "ORDER", kills=5, deaths=2, assists=4, level=12,
                item_ids=[3078]),
        _player("Zed", "CHAOS", champ="Zed", kills=8, deaths=1, assists=2,
                level=13, item_ids=[3142, 6691]),
        _player("Vayne", "CHAOS", kills=6, deaths=3, assists=1, level=11,
                item_ids=[3153, 3006]),
        _player("Thresh", "CHAOS", kills=0, deaths=4, assists=10, level=9,
                item_ids=[3190]),
        _player("Syndra", "CHAOS", kills=4, deaths=2, assists=5, level=12,
                item_ids=[6653, 3020]),
        _player("Mundo", "CHAOS", champ="DrMundo", kills=2, deaths=5,
                assists=3, level=11, item_ids=[3075, 3742]),
    ]


def _my_team(out: dict):
    """Replicate active_match.js::_resolveMyTeam against the summary output."""
    ap = out.get("activePlayer") or {}
    me = ap.get("summonerName") or ap.get("riotIdGameName") or ""
    if not me:
        return None
    for p in out.get("allPlayers") or []:
        rid = p.get("riotIdGameName") or p.get("summonerName") or ""
        if rid == me or me.startswith(rid + "#") or rid == me.split("#", 1)[0]:
            return p.get("team")
    return None


class AllPlayersEmittedTests(unittest.TestCase):
    def test_allplayers_present_with_all_rows(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        self.assertIn("allPlayers", out)
        self.assertIsInstance(out["allPlayers"], list)
        self.assertEqual(len(out["allPlayers"]), 10)

    def test_activeplayer_identity_emitted(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        self.assertIn("activePlayer", out)
        ap = out["activePlayer"]
        self.assertEqual(ap.get("summonerName"), "Ashe")
        # riotIdGameName carried so _resolveMyTeam's suffixed form also matches.
        self.assertEqual(ap.get("riotIdGameName"), "Ashe")

    def test_each_row_carries_team_and_identity(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        for p in out["allPlayers"]:
            self.assertTrue(p.get("team"), "team required for the ally/enemy split")
            self.assertTrue(
                p.get("summonerName") or p.get("riotIdGameName"),
                "identity required for _resolveMyTeam",
            )
            self.assertTrue(p.get("championName"))


class ResolveMyTeamContractTests(unittest.TestCase):
    def test_active_team_resolvable(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        self.assertEqual(_my_team(out), "ORDER")

    def test_enemy_split_is_five(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        my = _my_team(out)
        enemies = [p for p in out["allPlayers"] if p.get("team") != my]
        self.assertEqual(len(enemies), 5)


class EnemyCounterHintFieldsTests(unittest.TestCase):
    """The C3 fed + R102/R103 path: every enemy row must expose championName,
    item ids, scores{kills,deaths,assists} and level index-alignably."""

    def test_enemy_rows_have_champion_items_scores_level(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        my = _my_team(out)
        enemies = [p for p in out["allPlayers"] if p.get("team") != my]
        for e in enemies:
            self.assertTrue(e.get("championName"))
            # item ids (mirrors _extractBpEnemies: it.itemID)
            ids = [str((it or {}).get("itemID", "")) for it in (e.get("items") or [])]
            self.assertTrue(all(isinstance(x, str) for x in ids))
            sc = e.get("scores") or {}
            for k in ("kills", "deaths", "assists"):
                self.assertIn(k, sc)
                self.assertIsInstance(sc[k], int)
            self.assertIsInstance(e.get("level"), int)

    def test_zed_row_values_survive(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        zed = next(p for p in out["allPlayers"] if p.get("championName") == "Zed")
        self.assertEqual(zed["team"], "CHAOS")
        self.assertEqual(zed["scores"]["kills"], 8)
        self.assertEqual(zed["scores"]["deaths"], 1)
        self.assertEqual(zed["level"], 13)
        ids = [it.get("itemID") for it in zed["items"]]
        self.assertIn(3142, ids)
        self.assertIn(6691, ids)


class AllyItemsForC2Tests(unittest.TestCase):
    """C2 antiheal de-dup reads MY-team item ids off the same roster."""

    def test_ally_rows_expose_item_ids(self):
        out = _summary(_allgamedata("Ashe", _full_roster()))
        my = _my_team(out)
        ally_ids = [str((it or {}).get("itemID", ""))
                    for p in out["allPlayers"] if p.get("team") == my
                    for it in (p.get("items") or [])]
        # Ashe's 3006/3031 + teammates' items are present.
        self.assertIn("3031", ally_ids)
        self.assertIn("3047", ally_ids)


class MalformedInputTests(unittest.TestCase):
    def test_empty_allgamedata_no_raise(self):
        # A degenerate {} frame is truthy (not the None "no game" sentinel), so
        # the summary proceeds with defaults; the roster degrades to an empty
        # list (no allPlayers) rather than raising.
        out = _summary({})
        self.assertIsInstance(out, dict)
        self.assertEqual(out.get("allPlayers", []), [])

    def test_missing_allplayers_key_absent_or_empty(self):
        bad = {
            "activePlayer": {"summonerName": "Ashe", "riotIdGameName": "Ashe"},
            "gameData": {"gameTime": 100.0, "gameMode": "CLASSIC"},
        }
        out = _summary(bad)
        self.assertIsInstance(out, dict)
        # allPlayers must not raise; absent or empty list both acceptable.
        self.assertEqual(out.get("allPlayers", []), [])

    def test_non_numeric_score_and_level_no_raise(self):
        players = _full_roster()
        players[5]["scores"]["kills"] = "lots"
        players[5]["level"] = None
        out = _summary(_allgamedata("Ashe", players))
        self.assertIsInstance(out, dict)
        self.assertIn("allPlayers", out)

    def test_active_name_absent_still_emits_roster(self):
        # _resolveMyTeam handles a name miss itself; the roster must still ship
        # (allPlayers is emitted independent of the active-player match).
        out = _summary(_allgamedata("GhostName", _full_roster()))
        self.assertIn("allPlayers", out)
        self.assertEqual(len(out["allPlayers"]), 10)


class AsciiHygieneTests(unittest.TestCase):
    def test_liveclient_module_is_ascii(self):
        bad = {chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
               chr(0x201C), chr(0x201D)}
        from pathlib import Path
        text = Path(_liveclient.__file__).read_text(encoding="utf-8")
        for ch in bad:
            self.assertNotIn(
                ch, text, f"non-ASCII character U+{ord(ch):04X} in module")

    def test_self_is_ascii(self):
        from pathlib import Path
        text = Path(__file__).read_text(encoding="utf-8")
        nonascii_lines = [
            i for i, line in enumerate(text.split("\n"))
            if any(ord(c) > 127 for c in line) and "chr(" not in line
        ]
        self.assertEqual(nonascii_lines, [],
                         f"non-ASCII lines: {nonascii_lines}")


_ = io.StringIO

if __name__ == "__main__":
    unittest.main()
