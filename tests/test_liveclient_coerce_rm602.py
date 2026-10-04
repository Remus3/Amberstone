"""RM-602 (directive X-02, external reference E): lenient Live Client list and
bool coercion.

Before this item, ``dashboard/_liveclient.py:109`` ``_as_list`` returned ``[]``
for anything that was not a JSON array, so a list field that arrived
OBJECT-SHAPED (``{"0": a, "1": b}``, seen on a Practice Tool game per external
reference E) was silently dropped. ``game_reader/snapshot_normalizer.py``
(:320-328 allPlayers / Events, :482 items, :1402-1406 runes) did the same with
inline ``isinstance(x, list)`` checks.

The shared rule now lives in ``core/liveclient_coerce.py``:
  - a list passes through unchanged (same object);
  - a dict whose keys are ALL integer-like yields its values in numeric key
    order, and the first coercion per field logs one WARNING;
  - None / missing / scalar / any other dict -> ``[]``.
``as_bool`` accepts real bools and "True"/"False" strings (case-insensitive),
else returns the caller's default.
"""
from __future__ import annotations

import logging

import pytest

from core import liveclient_coerce as lc
from dashboard import _liveclient


@pytest.fixture(autouse=True)
def _fresh_warn_state():
    lc._reset_warned_for_tests()
    yield
    lc._reset_warned_for_tests()


# -- as_list -----------------------------------------------------------------

def test_real_list_is_returned_unchanged():
    src = [{"a": 1}, {"b": 2}]
    assert lc.as_list(src, "Events") is src


def test_object_shaped_list_returns_values_in_numeric_key_order():
    # Keys deliberately out of insertion order and spanning a lexical/numeric
    # split ("10" sorts before "2" as text).
    src = {"2": "c", "0": "a", "10": "d", "1": "b"}
    assert lc.as_list(src, "Events") == ["a", "b", "c", "d"]


def test_int_keys_are_accepted_too():
    assert lc.as_list({1: "b", 0: "a"}, "items") == ["a", "b"]


@pytest.mark.parametrize("bad", [None, 7, 1.5, "abc", True,
                                 {"a": 1}, {"0": 1, "x": 2}, {True: 1}])
def test_non_coercible_values_read_as_empty(bad):
    assert lc.as_list(bad, "Events") == []


def test_first_coercion_per_field_logs_once(caplog):
    caplog.set_level(logging.WARNING, logger=lc._log.name)
    lc.as_list({"0": 1}, "Events")
    lc.as_list({"0": 1, "1": 2}, "Events")
    hits = [r for r in caplog.records if "Events" in r.getMessage()]
    assert len(hits) == 1
    # A different field still gets its own single warning.
    lc.as_list({"0": 1}, "items")
    hits = [r for r in caplog.records if "items" in r.getMessage()]
    assert len(hits) == 1


def test_real_list_never_logs(caplog):
    caplog.set_level(logging.WARNING, logger=lc._log.name)
    lc.as_list([1, 2], "Events")
    lc.as_list(None, "Events")
    assert caplog.records == []


# -- as_bool -----------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    (True, True), (False, False),
    ("True", True), ("False", False),
    ("true", True), ("FALSE", False), (" True ", True),
])
def test_as_bool_accepts_bools_and_bool_strings(raw, want):
    assert lc.as_bool(raw) is want


@pytest.mark.parametrize("raw", [None, "yes", "", 1, 0, "1", [], {}])
def test_as_bool_other_values_take_the_default(raw):
    assert lc.as_bool(raw) is False
    assert lc.as_bool(raw, default=True) is True


def test_stolen_false_string_is_false():
    assert lc.as_bool("False", default=True) is False


# -- dashboard/_liveclient seam ----------------------------------------------

def test_liveclient_as_list_uses_the_shared_rule():
    assert _liveclient._as_list({"1": "b", "0": "a"}, "Events") == ["a", "b"]
    src = [1]
    assert _liveclient._as_list(src) is src
    assert _liveclient._as_list("junk") == []


def test_liveclient_exports_as_bool():
    assert _liveclient.as_bool("True") is True


def test_liveclient_summary_reads_object_shaped_events():
    from tests.test_liveclient_objective_events import (
        _PLAYERS, _allgamedata, _summary,
    )
    events = {"1": {"EventName": "BaronKill", "EventTime": 1295.0,
                    "KillerName": "Leona"},
              "0": {"EventName": "DragonKill", "EventTime": 1290.0,
                    "KillerName": "Zed"}}
    gd = _allgamedata("Ashe", _PLAYERS, [])
    gd["events"] = {"Events": events}
    out = _summary(gd)
    names = [e["name"] for e in out["objective_events"]]
    assert names == ["dragon", "baron"]


# -- game_reader/snapshot_normalizer seam ------------------------------------

def _objectify(seq):
    return {str(i): v for i, v in enumerate(seq)}


def test_normalizer_object_shaped_lists_match_the_list_shaped_result():
    from tests.test_snapshot_normalizer_wire_coercion import _Host, _envelope

    base = _envelope()
    base["allPlayers"][0]["items"] = [
        {"displayName": "Doran's Ring", "itemID": 1056, "slot": 0}]
    base["events"]["Events"] = [
        {"EventName": "DragonKill", "EventTime": 400.0, "KillerName": "Zed"}]
    want = _Host()._process_game(base)

    obj = _envelope()
    obj["allPlayers"][0]["items"] = _objectify(
        [{"displayName": "Doran's Ring", "itemID": 1056, "slot": 0}])
    obj["events"]["Events"] = _objectify(
        [{"EventName": "DragonKill", "EventTime": 400.0, "KillerName": "Zed"}])
    obj["allPlayers"] = _objectify(obj["allPlayers"])
    got = _Host()._process_game(obj)

    assert want is not None and got is not None
    assert got["items"] == want["items"]
    assert "Doran's Ring" in str(want["items"])
    # The DragonKill at 400s must be seen in both shapes (else "Drake UP").
    assert got["objectives"] == want["objectives"]
    assert "Drake #2" in want["objectives"]
    assert got["obj_timers_dict"] == want["obj_timers_dict"]
    assert got["enemy_comp"] == want["enemy_comp"]
    assert want["enemy_comp"]
