"""RM-844 - the focus-board live adapter (core.focus_board_live).

Grounded before writing (file:line at main 4b0bc3ce4):

* WHICH LIST. ``dashboard/_liveclient.py:312`` ``out["players"]`` carries
  position / team / creep_score / is_active only - no level, no champion.
  ``out["allPlayers"]`` (``:374``) is ``_lean_roster`` (``:124``), which keeps
  ``championName`` / ``rawChampionName`` / ``team`` (``:145-147``),
  ``level`` (``:148``, ``_as_int``, so a missing level reads 0) and
  ``items`` as ``{"itemID", "slot"}`` (``:138-141``). ``out["activePlayer"]``
  (``:375-378``) carries ``summonerName`` / ``riotIdGameName``;
  ``out["level"]`` (``:216``) is the activePlayer level; ``out["champion"]``
  (``:259``) is my ``championName``.
* THE PAYLOAD. ``tests/fixtures/liveclient/allgamedata_synthetic_rm601.json``
  carries a per-player ``level`` at ``:22`` / ``:31`` / ``:40`` / ``:49``. It
  is SYNTHETIC (its own ``_comment``, ``:2``: "it is NOT a capture"); no
  recorded :2999 capture is tracked. It is fed through the REAL
  ``liveclient_summary()`` (``dashboard/_liveclient.py:178``), whose only
  input is ``core.liveclient_cache.get()`` (``:193-197``; ``Snapshot.data`` /
  ``age_s`` at ``core/liveclient_cache.py:68`` / ``:80``).
* THE ENGINE. ``agents/daemon_slayer/focus_board.py:475``
  ``compute_focus_board(snapshot, me, enemies, allies=(), mode="SR",
  apply_mode_modifiers=False)``; ``FocusBoard.to_dict`` (``:226-239``) keys
  ``me`` / ``kill_order`` / ``danger_order`` / ``rows`` / ``notes``;
  ``FocusRow.to_dict`` (``:184-202``). Unknown champion -> note + skip
  (``:314-316``); unknown item -> dropped with a note (``:338-341``);
  unresolvable me -> ``me == ""`` and no rows (``:523-524``).
* ``DataSnapshot.champions`` (``agents/daemon_slayer/data_loader.py:133``),
  each record carrying ``id`` / ``name``.
* ``core.daemon_slayer_resolver.NON_INVENTORY_IDS`` (``:247``) - the shared
  trinket / consumable set ``liveclient_summary`` filters with (``:277-282``).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.focus_board import compute_focus_board
from core import focus_board_live as fbl
from core import liveclient_cache

_FIXTURE = (Path(__file__).parent / "fixtures" / "liveclient"
            / "allgamedata_synthetic_rm601.json")


@pytest.fixture(scope="module")
def snapshot():
    return DataSnapshot.load()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(fbl.KILL_SWITCH_ENV, raising=False)
    fbl.reset_for_tests()
    yield
    fbl.reset_for_tests()


@pytest.fixture()
def real_engine(snapshot):
    fbl._set_engine_for_tests((snapshot, compute_focus_board))
    return snapshot


def _fixture_lc(monkeypatch) -> dict:
    """The RM-601 fixture through the REAL liveclient_summary()."""
    from dashboard._liveclient import liveclient_summary

    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    snap = liveclient_cache.Snapshot(data=data, ts=time.time(),
                                     fetched_at=time.time())
    monkeypatch.setattr(liveclient_cache, "get", lambda: snap)
    lc = liveclient_summary()
    assert lc, "liveclient_summary returned {} for the fixture"
    return lc


def _arena_lc() -> dict:
    """An Arena-shaped lean roster (team spellings as in
    web/data/ui_mock/active_match_arena.json), with display names that need
    canonicalising and a trinket / potion in my inventory."""
    def p(name, raw, team, level, items, summ):
        return {"summonerName": summ, "riotIdGameName": summ.split("#")[0],
                "championName": name, "rawChampionName": raw, "team": team,
                "level": level,
                "items": [{"itemID": i, "slot": n} for n, i in enumerate(items)],
                "scores": {"kills": 0, "deaths": 0, "assists": 0}}
    return {
        "champion": "Jinx",
        "level": 12,
        "activePlayer": {"summonerName": "Me#TST", "riotIdGameName": "Me"},
        "allPlayers": [
            p("Jinx", "game_character_displayname_Jinx", "100", 12,
              [3006, 3031, 3340, 2003], "Me#TST"),
            p("Karma", "game_character_displayname_Karma", "100", 12,
              [3504], "Duo#TST"),
            p("Wukong", "game_character_displayname_MonkeyKing", "200", 12,
              [3071], "FoeA#TST"),
            p("Dr. Mundo", "DrMundo", "200", 11, [3084], "FoeB#TST"),
            p("Kai'Sa", "", "300", 12, [], "FoeC#TST"),
        ],
    }


# -- the level finding -----------------------------------------------------------

def test_fixture_allplayers_carries_level_and_players_does_not(monkeypatch):
    lc = _fixture_lc(monkeypatch)
    assert [p["level"] for p in lc["allPlayers"]] == [7, 6, 7, 6]
    assert [p["championName"] for p in lc["allPlayers"]] == [
        "Ashe", "Leona", "Zed", "Lux"]
    # The list the RM-844 brief called blocked really has neither field.
    assert all("level" not in p and "championName" not in p
               for p in lc["players"])


# -- mapping ---------------------------------------------------------------------

def test_roster_from_fixture_lc(monkeypatch, snapshot):
    lc = _fixture_lc(monkeypatch)
    roster, notes = fbl.roster_from_lc(lc, snapshot.champions)
    assert roster is not None, notes
    assert roster.me == ("Ashe", 7, ("1055",))
    assert roster.allies == (("Leona", 6, ()),)
    assert roster.enemies == (("Zed", 7, ()), ("Lux", 6, ()))


def test_roster_canonicalises_names_and_drops_non_inventory(snapshot):
    roster, notes = fbl.roster_from_lc(_arena_lc(), snapshot.champions)
    assert roster is not None, notes
    # 3340 (trinket) and 2003 (potion) are NON_INVENTORY_IDS.
    assert roster.me == ("Jinx", 12, ("3006", "3031"))
    assert roster.allies == (("Karma", 12, ("3504",)),)
    assert roster.enemies == (
        ("MonkeyKing", 12, ("3071",)),
        ("DrMundo", 11, ("3084",)),
        ("Kaisa", 12, ()),
    )


def test_missing_level_is_none_and_my_level_prefers_active_player(snapshot):
    lc = _arena_lc()
    lc["allPlayers"][2]["level"] = 0          # _lean_roster's missing value
    lc["allPlayers"][0]["level"] = 0
    roster, _ = fbl.roster_from_lc(lc, snapshot.champions)
    assert roster.me[1] == 12                  # lc["level"], activePlayer
    assert roster.enemies[0][1] is None        # never a fabricated level 1


def test_unknown_champion_passes_through_for_the_board_to_name(snapshot):
    lc = _arena_lc()
    lc["allPlayers"][4]["championName"] = "Notachampion"
    roster, _ = fbl.roster_from_lc(lc, snapshot.champions)
    assert roster.enemies[2][0] == "Notachampion"


@pytest.mark.parametrize("lc", [
    None,
    "garbage",
    {},
    {"champion": "Jinx", "allPlayers": []},
    {"champion": "Jinx", "allPlayers": "not a list"},
])
def test_no_roster_never_raises_and_never_warms_the_engine(lc, monkeypatch):
    # A RECORDING spy, not a raising one: the warm thread is fail-soft and
    # would swallow an AssertionError (the RM-194 lesson).
    loads = []
    monkeypatch.setattr(fbl, "_load_engine", lambda: loads.append(1))
    out = fbl.board_for_lc(lc, "arena")
    fbl._join_warm_for_tests(5)
    assert loads == []
    assert out["status"] == fbl.STATUS_NO_ROSTER
    assert out["top_kill"] is None and out["kill_order"] == []
    assert out["notes"]


def test_me_not_found_is_no_roster(real_engine):
    lc = _arena_lc()
    lc["activePlayer"] = {"summonerName": "Stranger#X"}
    lc["champion"] = "Teemo"
    out = fbl.board_for_lc(lc, "arena")
    assert out["status"] == fbl.STATUS_NO_ROSTER
    assert any("not found" in n for n in out["notes"])


# -- the board -------------------------------------------------------------------

def test_board_for_fixture_lc_matches_direct_engine_call(monkeypatch, real_engine):
    lc = _fixture_lc(monkeypatch)
    out = fbl.board_for_lc(lc, "sr")
    assert out["status"] == fbl.STATUS_OK, out["notes"]
    direct = compute_focus_board(
        real_engine, ("Ashe", 7, ("1055",)),
        [("Zed", 7, ()), ("Lux", 6, ())], [("Leona", 6, ())], mode="SR",
    )
    assert out["kill_order"] == list(direct.kill_order)
    assert out["danger_order"] == list(direct.danger_order)
    assert out["top_kill"]["champion_id"] == direct.kill_order[0]
    assert out["me"] == "Ashe" and out["allies"] == ["Leona"]
    assert out["mode"] == "SR" and out["apply_mode_modifiers"] is False
    json.dumps(out, allow_nan=False)           # strict JSON for the jsonl


def test_arena_partner_is_the_one_ally(real_engine):
    out = fbl.board_for_lc(_arena_lc(), "arena")
    assert out["status"] == fbl.STATUS_OK, out["notes"]
    assert out["mode"] == "ARENA"
    assert out["allies"] == ["Karma"]
    assert sorted(out["kill_order"]) == ["DrMundo", "Kaisa", "MonkeyKing"]
    assert out["kill_order_names"][0] == out["top_kill"]["champion_name"]


def test_every_enemy_unknown_is_no_board_with_notes(real_engine):
    lc = _arena_lc()
    for p in lc["allPlayers"][2:]:
        p["championName"], p["rawChampionName"] = "Notachampion", ""
    out = fbl.board_for_lc(lc, "arena")
    assert out["status"] == fbl.STATUS_NO_BOARD
    assert out["top_kill"] is None
    assert any("unknown champion" in n for n in out["notes"])


def test_my_champion_unknown_is_no_board(real_engine):
    lc = _arena_lc()
    lc["allPlayers"][0]["championName"] = "Notachampion"
    lc["allPlayers"][0]["rawChampionName"] = ""
    out = fbl.board_for_lc(lc, "arena")
    assert out["status"] == fbl.STATUS_NO_BOARD
    assert out["top_kill"] is None


# -- DS failure ------------------------------------------------------------------

def test_ds_import_failure_is_unavailable_and_backs_off(monkeypatch):
    calls = []

    def broken():
        calls.append(1)
        raise ImportError("no module named agents.daemon_slayer")
    monkeypatch.setattr(fbl, "_load_engine", broken)
    out = fbl.board_for_lc(_arena_lc(), "arena", wait_engine=True)
    assert out["status"] == fbl.STATUS_UNAVAILABLE
    assert out["top_kill"] is None
    assert not any("agents.daemon_slayer" in n for n in out["notes"])
    # Inside the backoff window the loader is not retried every tick.
    again = fbl.board_for_lc(_arena_lc(), "arena", wait_engine=True)
    assert again["status"] == fbl.STATUS_UNAVAILABLE
    assert len(calls) == 1


def test_engine_raising_is_no_board_without_exception_text(snapshot):
    def raising(*_a, **_k):
        raise RuntimeError("SECRET-LEAK-MARKER")
    fbl._set_engine_for_tests((snapshot, raising))
    out = fbl.board_for_lc(_arena_lc(), "arena")
    assert out["status"] == fbl.STATUS_NO_BOARD
    assert any("RuntimeError" in n for n in out["notes"])
    assert "SECRET-LEAK-MARKER" not in json.dumps(out)


def test_warming_returns_at_once_without_blocking(monkeypatch, snapshot):
    gate = threading.Event()

    def slow():
        gate.wait(10)
        return snapshot, compute_focus_board
    monkeypatch.setattr(fbl, "_load_engine", slow)
    t0 = time.monotonic()
    out = fbl.board_for_lc(_arena_lc(), "arena")
    assert time.monotonic() - t0 < 0.5
    assert out["status"] == fbl.STATUS_WARMING
    gate.set()
    fbl._join_warm_for_tests(10)
    assert fbl.board_for_lc(_arena_lc(), "arena")["status"] == fbl.STATUS_OK


# -- cache + throttle ------------------------------------------------------------

def test_throttle_and_cache_hold(snapshot):
    calls = []

    def counting(*a, **k):
        calls.append(1)
        return compute_focus_board(*a, **k)
    fbl._set_engine_for_tests((snapshot, counting))

    lc = _arena_lc()
    first = fbl.board_for_lc(lc, "arena", now=100.0)
    for t in (100.1, 100.5, 101.0, 500.0):    # same roster -> cache, any time
        assert fbl.board_for_lc(lc, "arena", now=t) == first
    assert len(calls) == 1

    lc2 = _arena_lc()
    lc2["allPlayers"][2]["level"] = 13         # a level-up changes the roster
    within = fbl.board_for_lc(lc2, "arena", now=500.0 + 0.5)
    assert len(calls) == 2                     # 400 s since the last compute
    assert within["status"] == fbl.STATUS_OK

    lc3 = _arena_lc()
    lc3["allPlayers"][2]["level"] = 14
    throttled = fbl.board_for_lc(lc3, "arena", now=501.0)
    assert throttled["status"] == fbl.STATUS_THROTTLED
    assert throttled["top_kill"] is None
    assert len(calls) == 2
    later = fbl.board_for_lc(lc3, "arena",
                             now=500.5 + fbl.MIN_COMPUTE_INTERVAL_S)
    assert later["status"] == fbl.STATUS_OK
    assert len(calls) == 3


def test_returned_result_is_a_copy(real_engine):
    lc = _arena_lc()
    out = fbl.board_for_lc(lc, "arena")
    out["kill_order"].clear()
    assert fbl.board_for_lc(lc, "arena")["kill_order"]


def test_kill_switch(monkeypatch, real_engine):
    monkeypatch.setenv(fbl.KILL_SWITCH_ENV, "0")
    assert fbl.enabled() is False
    out = fbl.board_for_lc(_arena_lc(), "arena")
    assert out["status"] == fbl.STATUS_DISABLED and out["top_kill"] is None
