"""RM-456 (3) + (4) - ``lcu/champ_select_shape.py``.

(3) ``_as_int`` read ``True`` as 1 and ``False`` as 0 because bool is an int
subclass. DECISION: a bool is REFUSED and yields the caller's default. No
LCU champ-select id or cell is ever a JSON boolean, and accepting one is
actively harmful here: ``True`` as a cellId names cell 1 (a real player),
and ``True`` as a championId names champion 1 (Annie), so a retyped flag
would badge the wrong cell as ME or paint a pick nobody made. The default
path is the one a missing field already takes. Also: ``int(float("inf"))``
raises OverflowError, which ``_as_int`` did not catch (Python's json module
accepts ``Infinity``), so it now degrades to the default too.

(4) ``arena_teams`` forwarded member ``cellId`` verbatim. It now routes
through ``_as_int`` with default ``None`` - the RM-417 rule: cell 0 is a
real cell, so a missing / unparseable cellId must NOT become 0.

JS consumer census for arena member ``cellId`` (web/js, grepped before the
change): NO reader. ``champ_select.js`` ``_csvArenaPaneHtml`` and the Arena
enemies column read ``arena_teams[].cells[]`` for ``championId``,
``completed`` and ``summonerName`` only; every ``.cellId`` read in web/js
(champ_select.js role / cleanse / active-round, ds_matchup.js) is against
``my_team`` / ``their_team``, already coerced by RM-417. So the flip breaks
no render arm; it makes the field honest for any future reader.
"""
from __future__ import annotations

import pytest

from lcu.champ_select_shape import _as_int, _team_picks, arena_teams


@pytest.mark.parametrize("flag", [True, False])
def test_as_int_refuses_bool(flag):
    assert _as_int(flag, 7) == 7
    assert _as_int(flag, None) is None


@pytest.mark.parametrize("v", [float("inf"), float("-inf"), float("nan")])
def test_as_int_non_finite_float_degrades_to_default(v):
    assert _as_int(v, -1) == -1


@pytest.mark.parametrize("v,expect", [(0, 0), (5, 5), ("3", 3), (4.0, 4), (-1, -1)])
def test_as_int_valid_values_unchanged(v, expect):
    assert _as_int(v, 99) == expect


def test_bool_cell_id_in_team_picks_stays_none_not_cell_one():
    out = _team_picks([{"cellId": True, "championId": 67}], local_cell=1)
    assert out[0]["cellId"] is None


def test_bool_local_cell_does_not_claim_cell_one_in_arena():
    sess = {"localPlayerCellId": True, "additionalSubteamData": [
        {"subteamId": 1, "members": [{"cellId": 0, "championId": 1}]},
        {"subteamId": 2, "members": [{"cellId": 1, "championId": 2}]},
    ]}
    assert [t["is_me"] for t in arena_teams(sess)] == [False, False]


def test_bool_champion_id_is_not_annie():
    sess = {"localPlayerCellId": 0, "additionalSubteamData": [
        {"subteamId": 1, "members": [{"cellId": 0, "championId": True}]}]}
    assert arena_teams(sess)[0]["cells"][0]["championId"] == 0


def _arena(cells):
    return {"localPlayerCellId": 0, "additionalSubteamData": [
        {"subteamId": 1, "members": [{"cellId": c, "championId": 67} for c in cells]}]}


def _cells(out):
    return [c["cellId"] for t in out for c in t["cells"]]


def test_arena_string_cell_ids_emit_ints():
    out = _cells(arena_teams(_arena(["0", "1", "2"])))
    assert out == [0, 1, 2]
    assert all(type(c) is int for c in out)


@pytest.mark.parametrize("bad", [None, "", "nan", "abc", True, [1], {"c": 1}],
                         ids=["None", "empty", "nan", "abc", "bool", "list", "dict"])
def test_arena_unparseable_cell_id_is_none_not_zero(bad):
    assert _cells(arena_teams(_arena([bad, 1]))) == [None, 1]


def test_arena_absent_cell_id_stays_none():
    sess = _arena([0])
    del sess["additionalSubteamData"][0]["members"][0]["cellId"]
    assert _cells(arena_teams(sess)) == [None]


def test_arena_well_formed_cell_ids_unchanged_including_zero():
    assert _cells(arena_teams(_arena([0, 1, 2]))) == [0, 1, 2]
