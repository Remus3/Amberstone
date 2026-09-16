"""RM-415 - core/replay_seek.py envelope readers.

``sample_at`` read ``blob.get("gameData") or {}`` and
``blob.get("allPlayers") or []``, and ``_player_from`` read
``raw.get("scores") or {}`` / ``raw.get("items") or []`` and ran bare
``int()`` over scoreboard values. A retyped inner field raised
``AttributeError`` / ``TypeError`` / ``ValueError``.

Caller severity (measured): this is the MOST severe module of the four,
because nothing catches it. ``sample_series_lenient`` catches ONLY
``SeekError``, so one malformed frame escaped as an untyped exception and
aborted the whole sweep - the exact loss the lenient sampler exists to stop.

Contract after the fix:
  * a retyped INNER field degrades (empty roster / zero score / requested
    time) and the sample is still returned;
  * a non-dict TOP-LEVEL blob is a failed read and raises the module's own
    typed ``SeekError``, so the lenient sampler RECORDS it as failed rather
    than silently swallowing it.
"""
from __future__ import annotations

import pytest

from core import replay_seek as rs

_HOSTILE = [None, "", "nan", "12", True, 5, 1.5]
_HOSTILE_IDS = ["None", "empty", "nan", "strnum", "bool", "int", "float"]


def _player(**kw) -> dict:
    base = {"summonerName": "A", "championName": "Vi", "level": 11,
            "position": "JUNGLE", "team": "ORDER",
            "scores": {"kills": 3, "deaths": 1, "assists": 7, "creepScore": 112},
            "items": [{"itemID": 6692}, {"itemID": 3111}]}
    base.update(kw)
    return base


class _Client:
    def __init__(self, blob):
        self.blob = blob

    def post_playback(self, t_s):
        return None

    def get_allgamedata(self):
        return self.blob


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_game_data_retyped_falls_back_to_requested_time(bad):
    s = rs.sample_at(_Client({"gameData": bad, "allPlayers": [_player()]}), 300.0)
    assert s.t_s == 300.0
    assert len(s.players) == 1


@pytest.mark.parametrize("bad", ["", "nan", "abc", True, [1], {"x": 1}],
                         ids=["empty", "nan", "abc", "bool", "list", "dict"])
def test_game_time_non_numeric_falls_back_to_requested_time(bad):
    s = rs.sample_at(_Client({"gameData": {"gameTime": bad},
                              "allPlayers": []}), 300.0)
    assert s.t_s == 300.0


def test_game_time_string_number_is_read():
    s = rs.sample_at(_Client({"gameData": {"gameTime": "412.5"},
                              "allPlayers": []}), 300.0)
    assert s.t_s == 412.5


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_all_players_retyped_degrades_to_empty_roster(bad):
    s = rs.sample_at(_Client({"gameData": {"gameTime": 10.0}, "allPlayers": bad}), 10.0)
    assert s.players == []


def test_non_dict_player_entry_is_skipped():
    s = rs.sample_at(_Client({"gameData": {"gameTime": 10.0},
                              "allPlayers": ["x", 5, None, _player()]}), 10.0)
    assert [p.champion for p in s.players] == ["Vi"]


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_scores_retyped_degrades_to_zero(bad):
    p = rs._player_from(_player(scores=bad))
    assert (p.kills, p.deaths, p.assists, p.cs) == (0, 0, 0, 0)


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_items_retyped_degrades_to_no_items(bad):
    assert rs._player_from(_player(items=bad)).item_ids == []


@pytest.mark.parametrize("bad,want", [
    (None, 0), ("", 0), ("nan", 0), ("abc", 0), (True, 0), ([3], 0),
    ("12", 12), (12.0, 12),
], ids=["None", "empty", "nan", "abc", "bool", "list", "strnum", "float"])
def test_numeric_score_fields_coerce_without_raising(bad, want):
    p = rs._player_from(_player(level=bad, scores={"kills": bad, "deaths": bad,
                                                   "assists": bad, "creepScore": bad}))
    assert (p.level, p.kills, p.deaths, p.assists, p.cs) == (want,) * 5


@pytest.mark.parametrize("bad", ["abc", "nan", True, [1]],
                         ids=["abc", "nan", "bool", "list"])
def test_unparseable_item_id_is_skipped(bad):
    p = rs._player_from(_player(items=[{"itemID": bad}, {"itemID": "3111"}]))
    assert p.item_ids == [3111]


@pytest.mark.parametrize("bad", _HOSTILE[1:], ids=_HOSTILE_IDS[1:])
def test_non_dict_blob_is_a_typed_seek_error(bad):
    with pytest.raises(rs.SeekError):
        rs.sample_at(_Client(bad), 10.0)


def test_lenient_sweep_records_a_malformed_frame_and_keeps_going():
    good = {"gameData": {"gameTime": 20.0}, "allPlayers": [_player()]}
    blobs = iter(["garbage", good])

    class _Seq(_Client):
        def get_allgamedata(self):
            return next(blobs)

    samples, failed = rs.sample_series_lenient(_Seq(None), [10.0, 20.0])
    assert failed == [10.0]
    assert [s.t_s for s in samples] == [20.0]


def test_well_formed_player_unchanged():
    p = rs._player_from(_player())
    assert (p.champion, p.summoner, p.level, p.role, p.team) == (
        "Vi", "A", 11, "JUNGLE", "ORDER")
    assert (p.kills, p.deaths, p.assists, p.cs) == (3, 1, 7, 112)
    assert p.item_ids == [6692, 3111]
