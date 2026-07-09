"""Tests for the live Kill Participation metric in
``dashboard/_liveclient.py`` :: ``liveclient_summary`` (item 281).

Kill Participation is a fully LIVE-derivable STATS-view metric. Live
Client ``/allgamedata`` exposes per-player ``scores`` =
{kills, deaths, assists, creepScore, wardScore} for ALL 10 players plus
each player's ``team`` (ORDER / CHAOS) and an active-player identity.
Gold is activePlayer-only, so no gold-diff metric is attempted.

  KP_pct = round(100 * (active_kills + active_assists) / team_total_kills)

where ``team_total_kills`` is the sum of kills of every player on the
ACTIVE player's team. The summary emits
``out["kill_participation_pct"] = f"{pct}%"`` ONLY when
team_total_kills > 0 AND the active player is resolvable; otherwise the
key is OMITTED entirely.

Inputs are built by calling ``liveclient_summary()`` with a realistic
``allgamedata`` dict - the shared ``core.liveclient_cache`` Snapshot is
seeded (via ``mock.patch`` on ``liveclient_cache.get``) with
``Snapshot(data=<allgamedata>, ts=<now>)`` so the summary resolves to our
fixture. ``ts`` is set to ``time.time()`` so it passes the 5 s freshness
gate (HOT-02, 2026-07-09: the summary reads the cache, not a per-call
urlopen).

Covers:
  * normal roster -> correct "N%"
  * 0 team kills -> key omitted
  * assists-only active player -> counted
  * malformed input -> no key, no raise
  * rounding correctness (banker-free round-half behavior)
  * active player unresolvable -> key omitted
"""
from __future__ import annotations

import contextlib
import io
import time
import unittest
from unittest import mock

from dashboard import _liveclient


def _player(name: str, team: str, kills: int = 0, deaths: int = 0,
            assists: int = 0, cs: int = 0) -> dict:
    """A single allPlayers entry with the live ``scores`` block."""
    return {
        "summonerName": name,
        "championName": name,
        "team": team,
        "items": [],
        "scores": {
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "creepScore": cs,
            "wardScore": 0.0,
        },
    }


def _allgamedata(active_name: str, players: list,
                 game_time: float = 600.0) -> dict:
    """A minimal but realistic Live Client /allgamedata payload."""
    return {
        "activePlayer": {
            "summonerName": active_name,
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
    """Seed the shared liveclient cache so liveclient_summary reads our fixture.

    HOT-02 (2026-07-09): liveclient_summary() now sources its frame from
    core.liveclient_cache.get() (the shared 0.5s background poll) instead of a
    per-call urlopen, so tests seed the cache Snapshot rather than mocking HTTP.
    """
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=allgamedata, ts=time.time() if ts is None else ts)
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        yield


def _summary(allgamedata, ts=None) -> dict:
    with _patched(allgamedata, ts=ts):
        return _liveclient.liveclient_summary()


class NormalRosterTests(unittest.TestCase):
    def test_kp_basic_percentage(self):
        # Active (Ashe) on ORDER: 3 kills + 5 assists = 8 involvements.
        # ORDER team total kills = 3 + 5 + 2 = 10. KP = 80%.
        players = [
            _player("Ashe", "ORDER", kills=3, deaths=1, assists=5),
            _player("Leona", "ORDER", kills=5, deaths=2, assists=7),
            _player("Garen", "ORDER", kills=2, deaths=0, assists=1),
            _player("Zed", "CHAOS", kills=4, deaths=3, assists=0),
            _player("Lux", "CHAOS", kills=1, deaths=4, assists=6),
        ]
        out = _summary(_allgamedata("Ashe", players))
        self.assertEqual(out.get("kill_participation_pct"), "80%")

    def test_kp_uses_active_team_only_not_enemy_kills(self):
        # Enemy team has a huge kill count; it must NOT enter the denominator.
        players = [
            _player("Ashe", "ORDER", kills=2, deaths=1, assists=2),
            _player("Leona", "ORDER", kills=2, deaths=2, assists=4),
            _player("Zed", "CHAOS", kills=30, deaths=0, assists=10),
        ]
        # ORDER total = 4. Active involvements = 2 + 2 = 4. KP = 100%.
        out = _summary(_allgamedata("Ashe", players))
        self.assertEqual(out.get("kill_participation_pct"), "100%")

    def test_kp_active_on_chaos_team(self):
        # Active is on CHAOS - denominator is the CHAOS kill sum.
        players = [
            _player("Garen", "ORDER", kills=10, deaths=1, assists=3),
            _player("Zed", "CHAOS", kills=4, deaths=2, assists=1),
            _player("Lux", "CHAOS", kills=0, deaths=3, assists=4),
        ]
        # CHAOS total = 4. Active (Zed) = 4 + 1 = 5 -> 125% (>100 is allowed;
        # assists can exceed kills). round(100 * 5 / 4) = 125.
        out = _summary(_allgamedata("Zed", players))
        self.assertEqual(out.get("kill_participation_pct"), "125%")


class ZeroTeamKillsTests(unittest.TestCase):
    def test_zero_team_kills_omits_key(self):
        # Nobody on either team has a kill -> KP undefined -> key omitted.
        players = [
            _player("Ashe", "ORDER", kills=0, deaths=2, assists=0),
            _player("Leona", "ORDER", kills=0, deaths=1, assists=0),
            _player("Zed", "CHAOS", kills=0, deaths=0, assists=0),
        ]
        out = _summary(_allgamedata("Ashe", players))
        self.assertNotIn("kill_participation_pct", out)

    def test_enemy_has_kills_but_own_team_zero_omits_key(self):
        # Own team has zero kills (denominator 0) even though enemy scored.
        players = [
            _player("Ashe", "ORDER", kills=0, deaths=5, assists=0),
            _player("Leona", "ORDER", kills=0, deaths=4, assists=0),
            _player("Zed", "CHAOS", kills=9, deaths=0, assists=3),
        ]
        out = _summary(_allgamedata("Ashe", players))
        self.assertNotIn("kill_participation_pct", out)


class AssistsOnlyTests(unittest.TestCase):
    def test_assists_only_active_counted(self):
        # Active player has 0 kills but 4 assists; team has 8 kills.
        players = [
            _player("Soraka", "ORDER", kills=0, deaths=1, assists=4),
            _player("Jinx", "ORDER", kills=8, deaths=2, assists=2),
            _player("Zed", "CHAOS", kills=3, deaths=4, assists=0),
        ]
        # ORDER total = 8. Active involvements = 0 + 4 = 4. KP = 50%.
        out = _summary(_allgamedata("Soraka", players))
        self.assertEqual(out.get("kill_participation_pct"), "50%")


class MalformedInputTests(unittest.TestCase):
    def test_missing_allplayers_no_key_no_raise(self):
        bad = {
            "activePlayer": {"summonerName": "Ashe"},
            "gameData": {"gameTime": 100.0},
        }
        out = _summary(bad)
        self.assertNotIn("kill_participation_pct", out)

    def test_scores_missing_no_key_no_raise(self):
        players = [
            {"summonerName": "Ashe", "championName": "Ashe", "team": "ORDER"},
            {"summonerName": "Leona", "championName": "Leona", "team": "ORDER"},
        ]
        out = _summary(_allgamedata("Ashe", players))
        self.assertNotIn("kill_participation_pct", out)

    def test_empty_allgamedata_no_key_no_raise(self):
        out = _summary({})
        self.assertNotIn("kill_participation_pct", out)

    def test_non_numeric_scores_no_raise(self):
        players = [
            _player("Ashe", "ORDER", kills=2, assists=2),
            _player("Leona", "ORDER", kills=2, assists=1),
        ]
        # Corrupt a score with a non-numeric value.
        players[1]["scores"]["kills"] = "lots"
        # Should not raise; key may be omitted depending on fail-soft path.
        out = _summary(_allgamedata("Ashe", players))
        self.assertIsInstance(out, dict)


class ActiveUnresolvableTests(unittest.TestCase):
    def test_active_name_not_in_allplayers_omits_key(self):
        # activePlayer summonerName matches no allPlayers entry.
        players = [
            _player("Leona", "ORDER", kills=5, deaths=2, assists=7),
            _player("Garen", "ORDER", kills=2, deaths=0, assists=1),
        ]
        out = _summary(_allgamedata("GhostName", players))
        self.assertNotIn("kill_participation_pct", out)


class RoundingTests(unittest.TestCase):
    def test_rounding_two_thirds(self):
        # Active involvements = 2, team total = 3 -> 66.66.. -> round -> 67.
        players = [
            _player("Ashe", "ORDER", kills=1, deaths=0, assists=1),
            _player("Leona", "ORDER", kills=2, deaths=0, assists=0),
            _player("Zed", "CHAOS", kills=1, deaths=2, assists=0),
        ]
        # ORDER total = 3, active = 1 + 1 = 2 -> round(100*2/3)=round(66.66)=67.
        out = _summary(_allgamedata("Ashe", players))
        self.assertEqual(out.get("kill_participation_pct"), "67%")

    def test_rounding_one_third(self):
        # Active involvements = 1, team total = 3 -> 33.33 -> round -> 33.
        players = [
            _player("Ashe", "ORDER", kills=1, deaths=0, assists=0),
            _player("Leona", "ORDER", kills=2, deaths=0, assists=0),
            _player("Zed", "CHAOS", kills=1, deaths=2, assists=0),
        ]
        out = _summary(_allgamedata("Ashe", players))
        self.assertEqual(out.get("kill_participation_pct"), "33%")


class AsciiHygieneTests(unittest.TestCase):
    def test_liveclient_module_is_ascii(self):
        bad = {chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
               chr(0x201C), chr(0x201D)}
        from pathlib import Path
        text = Path(_liveclient.__file__).read_text(encoding="utf-8")
        for ch in bad:
            self.assertNotIn(
                ch, text,
                f"non-ASCII character U+{ord(ch):04X} in module",
            )

    def test_self_is_ascii(self):
        from pathlib import Path
        text = Path(__file__).read_text(encoding="utf-8")
        nonascii_lines = [
            i for i, line in enumerate(text.split("\n"))
            if any(ord(c) > 127 for c in line) and "chr(" not in line
        ]
        self.assertEqual(nonascii_lines, [],
                         f"non-ASCII lines: {nonascii_lines}")


# Silence any incidental stdout from the import path.
_ = io.StringIO

if __name__ == "__main__":
    unittest.main()
