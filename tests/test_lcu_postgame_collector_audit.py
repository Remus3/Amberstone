"""Lane 8 deep audit of ``lcu/lcu_postgame_collector.py`` - the LCU end-of-game
ingest path.

Selected by risk criterion 1 (it parses LCU payloads RC does not author),
criterion 3 (it writes SQLite from a background thread) and criterion 5
(repeat offender - LEDGER items 348, 404, 965, 971 all landed here).

Two weaknesses, both MEASURED against the real module on 2026-08-03 before a
line was changed:

1. ``_save_eog`` builds its team-comp map at the top of the function, OUTSIDE
   the ``try`` that guards the database block, and calls ``team.get(...)`` /
   ``p.get(...)`` with no shape check. A single non-dict entry anywhere in
   ``teams`` or in a team's ``players`` raises ``AttributeError`` out of the
   whole function::

       teams=["nope"]                                -> AttributeError
       teams=[{"players": ["nope"]}]                 -> AttributeError
       teams=[{"players": {"a": 1}}]                 -> AttributeError

   Same root cause as LEDGER item 1176 (``core/rofl_archive.py`` crashed the
   whole extract loop on ONE wrong-shape ``statsJson``): a per-entry shape
   assumption inside a loop over payload data, with the guard placed around
   the wrong block.

2. That escaping exception is not survivable on the sync path.
   ``_run`` calls ``_capture_after_trigger`` with NO ``try``, while its async
   twin ``_run_async`` wraps the identical call. Measured: the collector
   thread is DEAD after one raising capture, and a second ``trigger()`` never
   reaches ``_capture_after_trigger`` at all - so every later game in that
   process silently records nothing. Nothing revives it: ``start()`` WOULD
   build a fresh thread (its guard is ``.is_alive()``, not mere existence -
   measured, after an early draft of this note claimed otherwise), but nothing
   calls it twice. ``init_collector`` is one-shot behind ``if _collector is
   None`` and the per-game path only calls ``trigger()``.

The asymmetry is the tell: two loops doing the same job, one guarded and one
not.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest


def _rows(db, table):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(f"SELECT match_id FROM {table}").fetchall()
    finally:
        conn.close()


@pytest.fixture()
def pgc(tmp_path, monkeypatch):
    import lcu.lcu_postgame_collector as mod
    monkeypatch.setattr(mod, "_DB_PATH", tmp_path / "pg.db")
    mod._ensure_schema()
    return mod


class TestMalformedTeamsShape:
    """A wrong-shape entry must cost that entry, never the whole match."""

    def test_non_dict_team_entry_does_not_raise(self, pgc, tmp_path):
        eog = {
            "gameId": "M-badteam",
            "teams": [
                "not-a-dict",
                {"teamId": 200, "win": "Win", "players": [
                    {"championName": "Jinx", "stats": {}}]},
            ],
        }
        pgc._save_eog(eog, "CLASSIC", {}, {})
        assert _rows(tmp_path / "pg.db", "sr_matches") == [("M-badteam",)], \
            "a non-dict team entry must not prevent the match being saved"
        assert len(_rows(tmp_path / "pg.db", "sr_player_stats")) == 1, \
            "the well-formed team's player must still be recorded"

    def test_non_dict_player_entry_is_skipped(self, pgc, tmp_path):
        eog = {
            "gameId": "M-badplayer",
            "teams": [{"teamId": 100, "win": "Win", "players": [
                "not-a-dict",
                {"championName": "Ashe", "stats": {}},
            ]}],
        }
        pgc._save_eog(eog, "CLASSIC", {}, {})
        assert len(_rows(tmp_path / "pg.db", "sr_player_stats")) == 1, \
            "the well-formed player must survive its malformed sibling"

    def test_non_list_players_value_does_not_raise(self, pgc, tmp_path):
        """A dict where a list was expected iterates to its KEYS - strings."""
        eog = {
            "gameId": "M-badplayers",
            "teams": [{"teamId": 100, "win": "Win", "players": {"a": 1}}],
        }
        pgc._save_eog(eog, "CLASSIC", {}, {})
        assert _rows(tmp_path / "pg.db", "sr_matches") == [("M-badplayers",)]

    def test_a_well_formed_payload_is_unchanged(self, pgc, tmp_path):
        """Positive control - the guard must not cost the normal path."""
        eog = {
            "gameId": "M-good",
            "teams": [
                {"teamId": 100, "win": "Win", "players": [
                    {"championName": "Jinx", "stats": {}},
                    {"championName": "Lulu", "stats": {}}]},
                {"teamId": 200, "win": "Fail", "players": [
                    {"championName": "Ashe", "stats": {}}]},
            ],
        }
        pgc._save_eog(eog, "CLASSIC", {}, {})
        assert len(_rows(tmp_path / "pg.db", "sr_player_stats")) == 3


class TestAdaptMatchHistorySiblings:
    """Same root cause, three more loops over payload lists.

    Here the AttributeError was CONTAINED - ``_capture_via_history`` wraps the
    call - but it discarded the entire history fallback for one bad member and
    logged at DEBUG only, which is the quieter half of the same defect.
    """

    def _adapt(self, pgc, game):
        c = pgc.PostgameCollector.__new__(pgc.PostgameCollector)
        return c._adapt_match_history(game)

    def test_malformed_members_do_not_lose_the_whole_match(self, pgc):
        game = {
            "gameId": 4242,
            "gameMode": "ARAM",
            "participants": [
                "not-a-dict",
                {"participantId": 1, "teamId": 100, "stats": {}},
            ],
            "participantIdentities": [
                "not-a-dict",
                {"participantId": 1, "player": {"summonerName": "Moon"}},
            ],
            "teams": ["not-a-dict", {"teamId": 100, "win": "Win"}],
        }
        out = self._adapt(pgc, game)
        assert out is not None, "one bad member must not discard the match"
        assert out["gameId"] == 4242
        players = [p for t in out["teams"] for p in t["players"]]
        assert len(players) == 1, "the well-formed participant must survive"
        assert players[0]["summonerName"] == "Moon", \
            "identity join must still resolve past the malformed entry"

    def test_non_dict_player_info_is_tolerated(self, pgc):
        """``ident.get('player') or {}`` still raised on a truthy non-dict."""
        game = {
            "gameId": 7,
            "participants": [{"participantId": 1, "teamId": 100, "stats": {}}],
            "participantIdentities": [{"participantId": 1, "player": "oops"}],
            "teams": [{"teamId": 100, "win": "Win"}],
        }
        out = self._adapt(pgc, game)
        assert out is not None
        assert out["teams"][0]["players"][0]["summonerName"] == ""

    def test_non_list_collections_are_tolerated(self, pgc):
        """A dict where a list was expected iterates to its string keys."""
        game = {"gameId": 9, "participants": {"a": 1},
                "participantIdentities": {"b": 2}, "teams": {"c": 3}}
        out = self._adapt(pgc, game)
        assert out is not None
        assert out["teams"] == []


class TestRunLoopSurvivesCaptureFailure:
    """The sync loop must not die on one bad game, as its async twin does not."""

    def _collector(self, pgc):
        import lcu.lcu_postgame_collector as mod
        c = mod.PostgameCollector.__new__(mod.PostgameCollector)
        c._stop = threading.Event()
        c._trigger = threading.Event()
        c._game_mode_hint = "CLASSIC"
        return c

    def test_run_survives_a_raising_capture(self, pgc):
        c = self._collector(pgc)
        calls = []

        def boom(mode):
            calls.append(mode)
            raise AttributeError("'str' object has no attribute 'get'")

        c._capture_after_trigger = boom
        t = threading.Thread(target=c._run, daemon=True, name="rc.postgame.test")
        t.start()
        try:
            c._trigger.set()
            deadline = time.time() + 5.0
            while len(calls) < 1 and time.time() < deadline:
                time.sleep(0.02)
            assert calls == ["CLASSIC"], "first trigger never reached capture"

            c._trigger.set()
            deadline = time.time() + 5.0
            while len(calls) < 2 and time.time() < deadline:
                time.sleep(0.02)
            assert len(calls) == 2, (
                "the loop died on the first exception - every later game in "
                "this process is silently lost")
            assert t.is_alive(), "collector thread must still be running"
        finally:
            c._stop.set()
            c._trigger.set()
            t.join(timeout=5)

    def test_run_still_exits_on_stop(self, pgc):
        """Positive control - the guard must not make the loop unstoppable."""
        c = self._collector(pgc)
        c._capture_after_trigger = lambda mode: None
        t = threading.Thread(target=c._run, daemon=True, name="rc.postgame.test2")
        t.start()
        c._stop.set()
        c._trigger.set()
        t.join(timeout=5)
        assert not t.is_alive(), "stop() must still terminate the loop"
