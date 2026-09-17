"""RM-461 (1) + (2) - ``liveclient_summary`` fields RM-456 did not reach.

(1) ``out["cs"]`` (``scores.creepScore`` of the active player) and
``out["level"]`` (``activePlayer.level``) were forwarded RAW. A float NaN
leaf serialises as the bare token ``NaN`` (not JSON), a "nan" string renders
the text "nan" in the stats panel, and a list / dict reached the panel as
``String([1])``.

DEGRADE VALUE = what a MISSING leaf already produced, the RM-456 precedent:
  * ``cs``: missing -> 0 (``s.get("creepScore", 0)``), so a bad value -> 0
    through the module's ``_int_or_zero`` seam, the SAME seam the sibling
    ``players[].creep_score`` read of the very same leaf already uses.
  * ``level``: missing -> None (``ap.get("level")``), and
    ``web/js/panels/stats_panel.js`` renders ``lc.level == null`` as "-",
    so a bad value -> None, never a fabricated 0.
BOOL follows this module's recorded RM-456 decision for ``_int_or_zero``
(``int(True) == 1``, pinned by test_rm456_liveclient_numeric), not the
lcu ``_as_int`` refusal; one bool policy per summary.

(2) Kill participation summed ``int(scores.kills)`` inside one try, so a
single None / junk ``kills`` (or the operator's own ``assists``) dropped the
WHOLE percentage. Each read now goes through ``_int_or_zero``, so that one
value degrades to 0 - the default a MISSING ``kills`` key already produced.

JS consumer census (web/js, grepped first): stats_panel.js renders
``lc.level`` / ``lc.cs`` with a ``== null`` "-" guard and ``String()``;
coach_choices.js reads ``lc.level || ...`` / ``... || lc.cs || 0``;
stats_panel.js ``_kpPct`` parses the "N%" string with ``isFinite``.
"""
from __future__ import annotations

import math
import time
from unittest import mock

import pytest

from dashboard import _liveclient

_BAD = [None, "nan", float("nan"), float("inf"), -math.inf, "abc", [1], {"v": 1}]
_BAD_IDS = ["None", "strnan", "floatnan", "inf", "neginf", "abc", "list", "dict"]


def _player(name, team, kills=1, assists=1, creep=50):
    return {"summonerName": name, "championName": name, "team": team,
            "position": "MIDDLE", "level": 9, "items": [],
            "scores": {"kills": kills, "deaths": 0, "assists": assists,
                       "creepScore": creep}}


def _frame():
    return {
        "activePlayer": {"summonerName": "Me", "level": 9, "currentGold": 1200,
                         "championStats": {"currentHealth": 800, "maxHealth": 1000}},
        "allPlayers": [_player("Me", "ORDER", kills=3, assists=5, creep=77),
                       _player("Ally", "ORDER", kills=5, assists=0),
                       _player("Zed", "CHAOS", kills=9, assists=0)],
        "gameData": {"gameTime": 600.0, "gameMode": "CLASSIC"},
    }


def _summary(frame):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=frame, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        return _liveclient.liveclient_summary()


def _assert_rest_intact(out):
    assert out, "one bad field blanked the whole summary"
    assert out.get("champion") == "Me"
    assert out.get("enemy_team") == ["Zed"]
    assert out.get("gold") == 1200


# --- (1) cs -------------------------------------------------------------

@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_cs_bad_degrades_to_zero_that_field_only(bad):
    f = _frame()
    f["allPlayers"][0]["scores"]["creepScore"] = bad
    out = _summary(f)
    _assert_rest_intact(out)
    assert out["cs"] == 0
    assert type(out["cs"]) is int
    assert out["level"] == 9
    assert out["kill_participation_pct"] == "100%"


def test_cs_missing_stays_zero():
    f = _frame()
    del f["allPlayers"][0]["scores"]["creepScore"]
    assert _summary(f)["cs"] == 0


@pytest.mark.parametrize("v,expect", [(0, 0), (77, 77), ("12", 12), (True, 1)],
                         ids=["zero", "int", "numeric-str", "bool-as-module"])
def test_cs_coercible_values(v, expect):
    f = _frame()
    f["allPlayers"][0]["scores"]["creepScore"] = v
    out = _summary(f)
    assert out["cs"] == expect
    assert type(out["cs"]) is int


# --- (1) level ----------------------------------------------------------

@pytest.mark.parametrize("bad", [b for b in _BAD if b is not None],
                         ids=[i for i in _BAD_IDS if i != "None"])
def test_level_bad_degrades_to_none_that_field_only(bad):
    f = _frame()
    f["activePlayer"]["level"] = bad
    out = _summary(f)
    _assert_rest_intact(out)
    assert out["level"] is None
    assert out["cs"] == 77


@pytest.mark.parametrize("present", [False, True], ids=["absent", "null"])
def test_level_missing_or_null_stays_none(present):
    f = _frame()
    if present:
        f["activePlayer"]["level"] = None
    else:
        del f["activePlayer"]["level"]
    assert _summary(f)["level"] is None


@pytest.mark.parametrize("v,expect", [(1, 1), (18, 18), ("7", 7), (True, 1)],
                         ids=["one", "eighteen", "numeric-str", "bool-as-module"])
def test_level_coercible_values(v, expect):
    f = _frame()
    f["activePlayer"]["level"] = v
    out = _summary(f)
    assert out["level"] == expect
    assert type(out["level"]) is int


def test_nan_leaves_never_reach_json_as_bare_nan():
    import json
    f = _frame()
    f["activePlayer"]["level"] = float("nan")
    f["allPlayers"][0]["scores"]["creepScore"] = float("nan")
    out = _summary(f)
    json.dumps({"level": out["level"], "cs": out["cs"]}, allow_nan=False)


# --- (2) kill participation ----------------------------------------------

@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_kp_teammate_bad_kills_degrades_that_value_only(bad):
    f = _frame()
    f["allPlayers"][1]["scores"]["kills"] = bad
    f["allPlayers"][0]["scores"]["kills"] = 3
    f["allPlayers"][0]["scores"]["assists"] = 0
    out = _summary(f)
    _assert_rest_intact(out)
    # Ally kills degrade to 0 -> team kills 3, involvement 3 -> 100%.
    assert out["kill_participation_pct"] == "100%"


@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_kp_own_bad_assists_degrades_that_value_only(bad):
    f = _frame()
    f["allPlayers"][0]["scores"]["assists"] = bad
    out = _summary(f)
    # team kills 3 + 5 = 8, involvement 3 + 0 -> round(37.5) == 38.
    assert out["kill_participation_pct"] == f"{round(100 * 3 / 8)}%"


@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_kp_own_bad_kills_degrades_that_value_only(bad):
    f = _frame()
    f["allPlayers"][0]["scores"]["kills"] = bad
    out = _summary(f)
    # team kills 0 + 5 = 5, involvement 0 + 5 -> 100%.
    assert out["kill_participation_pct"] == "100%"


def test_kp_all_team_kills_bad_omits_key():
    f = _frame()
    f["allPlayers"][0]["scores"]["kills"] = None
    f["allPlayers"][1]["scores"]["kills"] = "nan"
    assert "kill_participation_pct" not in _summary(f)


def test_well_formed_frame_unchanged():
    out = _summary(_frame())
    assert out["cs"] == 77
    assert out["level"] == 9
    # team kills 3 + 5 = 8, involvement 3 + 5 = 8 -> 100%.
    assert out["kill_participation_pct"] == "100%"
    assert out["kda"] == "3/0/5"
