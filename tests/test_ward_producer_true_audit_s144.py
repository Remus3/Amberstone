# arch: s144 true-audit - core/ward_producer.py hardening | section=tests | frozen=no
"""s144 lane 8 (true-audit) - `core/ward_producer.py` hardening.

`main.py` installs `tick_from_snapshot` as a `core.liveclient_cache`
listener, so `tick` runs on every 0.5 s relay snapshot of the Live Client
`allPlayers` list. Every defect below was measured on the pre-fix module by
calling the real `tick`:

  W1  `int(it.get("count", 1))` caught TypeError / ValueError only. A
      non-finite count (JSON has none, but the relay is a separate process
      and the producer is public) raised OverflowError out of `tick`, after
      the players before it had already been re-snapshotted, so the state
      was half-updated and the listener entered a failure streak.
  W2  The count had no magnitude bound: a control-ward count of 10**6
      dropping to 0 made 10**6 `record_ward` calls in one tick (10**12 would
      have tried to build a 10**12-element list), and a negative count
      (2 -> -5) reported 7 placements.
  W3  `bool(it.get("canUse", True))`: a JSON null or a 0 read as False, so
      a trinket that was usable and then reported an unusable canUse
      recorded a placement nobody made.
  W4  Two control-ward entries in one inventory were last-wins, so the same
      inventory listed in a different order (the Live Client does not
      promise an order) recorded a placement.
  W5  Players were keyed by bare summonerName. Two entries with the same
      name in one snapshot (a bot lobby, a custom game) diffed against each
      other and recorded the SAME false placements on every tick, for the
      rest of the game; two same-named players on opposite teams could
      never be told apart.
  W6  A non-finite / non-number / bool `ts` was passed straight to
      `ward_events.record_ward`, which drops such a ts: every placement of
      the tick was lost while `tick` still reported them as recorded.

Deliberate NON-changes, pinned below so a later reader does not over-read
the fix: an absent `count` is still 1 (single-stack items omit it on some
patches); a control ward going 2 -> absent is still 2 placements; a trinket
swapped away is still not a placement; an integral float count still reads
as its int; a real canUse True -> False is still one placement.
"""
from __future__ import annotations

import math
import time

import pytest

from core import ward_events, ward_producer


def _player(name="Alice", team="ORDER", items=None, position="MIDDLE"):
    return {"summonerName": name, "team": team, "position": position,
            "items": items if items is not None else []}


def _ward(item_id, **fields):
    entry = {"itemID": item_id, "slot": 6}
    entry.update(fields)
    return entry


@pytest.fixture(autouse=True)
def _clean():
    ward_events.reset()
    ward_producer.reset()
    yield
    ward_events.reset()
    ward_producer.reset()


def _ticks(*snapshots, start_ts=100.0):
    """Feed consecutive snapshots; return the per-tick record counts."""
    return [ward_producer.tick(s, ts=start_ts + i)
            for i, s in enumerate(snapshots)]


# W1 - a non-finite count never raises and never half-updates the state.

@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_w1_non_finite_count_does_not_raise(bad):
    first = [_player("A", items=[_ward(2055, count=2)]),
             _player("B", items=[_ward(2055, count=2)])]
    second = [_player("A", items=[_ward(2055, count=bad)]),
              _player("B", items=[_ward(2055, count=1)])]
    assert _ticks(first, second) == [0, 1]
    # B's decrement was recorded and A's junk tick placed nothing.
    assert ward_events.buffer_size() == 1


def test_w1_state_is_consistent_after_a_non_finite_count():
    # A precedes B: before the fix the raise on A left B un-snapshotted.
    a2, b2 = _ward(2055, count=2), _ward(2055, count=2)
    _ticks([_player("A", items=[a2]), _player("B", items=[b2])])
    ward_producer.tick([_player("A", items=[_ward(2055, count=math.inf)]),
                        _player("B", items=[_ward(2055, count=1)])], ts=101.0)
    # B is at 1 now; a further tick at 1 must be no placement.
    n = ward_producer.tick([_player("A", items=[_ward(2055, count=2)]),
                            _player("B", items=[_ward(2055, count=1)])],
                           ts=102.0)
    assert n == 0


def test_w1_listener_path_does_not_raise():
    class Snap:
        ts = 100.0
        data = {"allPlayers": [_player("A", items=[_ward(2055, count=2)])]}

    assert ward_producer.tick_from_snapshot(Snap) == 0
    Snap.data = {"allPlayers": [
        _player("A", items=[_ward(2055, count=math.inf)])]}
    assert ward_producer.tick_from_snapshot(Snap) == 0


# W2 - the count is bounded; junk magnitudes never fan out.

def test_w2_huge_count_drop_is_bounded():
    counts = _ticks([_player(items=[_ward(2055, count=2)])],
                    [_player(items=[_ward(2055, count=10**6)])],
                    [_player(items=[_ward(2055, count=0)])])
    # The junk tick is unknown (carries 2), so the drop to 0 is 2 placements.
    assert counts == [0, 0, 2]


def test_w2_huge_first_sighting_is_not_a_baseline():
    counts = _ticks([_player(items=[_ward(2055, count=10**12)])],
                    [_player(items=[_ward(2055, count=0)])])
    assert counts == [0, 0]
    assert ward_events.buffer_size() == 0


def test_w2_negative_count_is_not_a_placement_burst():
    counts = _ticks([_player(items=[_ward(2055, count=2)])],
                    [_player(items=[_ward(2055, count=-5)])],
                    [_player(items=[_ward(2055, count=2)])])
    assert counts == [0, 0, 0]


@pytest.mark.parametrize("bad", [True, False, 1.5, "2", None, [2], {"n": 2}])
def test_w2_unusable_count_carries_the_previous_count(bad):
    counts = _ticks([_player(items=[_ward(2055, count=2)])],
                    [_player(items=[_ward(2055, count=bad)])],
                    [_player(items=[_ward(2055, count=1)])])
    assert counts == [0, 0, 1]


# W3 - only a real bool canUse is a signal.

@pytest.mark.parametrize("bad", [None, 0, 1, "false", "true", [], {}])
def test_w3_unusable_can_use_is_not_a_placement(bad):
    counts = _ticks([_player(items=[_ward(3340, count=1, canUse=True)])],
                    [_player(items=[_ward(3340, count=1, canUse=bad)])])
    assert counts == [0, 0]


def test_w3_unusable_can_use_does_not_reopen_a_cooldown():
    # On cooldown (False); a junk tick must not read as usable, or the next
    # real False would record a placement nobody made.
    counts = _ticks([_player(items=[_ward(3340, count=1, canUse=False)])],
                    [_player(items=[_ward(3340, count=1, canUse=None)])],
                    [_player(items=[_ward(3340, count=1, canUse=False)])])
    assert counts == [0, 0, 0]


def test_w3_absent_can_use_does_not_reopen_a_cooldown():
    counts = _ticks([_player(items=[_ward(3340, count=1, canUse=False)])],
                    [_player(items=[_ward(3340, count=1)])],
                    [_player(items=[_ward(3340, count=1, canUse=False)])])
    assert counts == [0, 0, 0]


def test_w3_absent_can_use_on_first_sighting_is_not_usable():
    # No previous value: not known usable, so a later real False is no edge.
    counts = _ticks([_player(items=[_ward(3340, count=1)])],
                    [_player(items=[_ward(3340, count=1, canUse=False)])])
    assert counts == [0, 0]


def test_w3_real_edge_after_a_junk_tick_still_counts():
    counts = _ticks([_player(items=[_ward(3340, count=1, canUse=True)])],
                    [_player(items=[_ward(3340, count=1, canUse=None)])],
                    [_player(items=[_ward(3340, count=1, canUse=False)])])
    assert counts == [0, 0, 1]


# W4 - duplicate ward entries are order-independent.

def test_w4_reordered_duplicate_control_wards_are_no_placement():
    counts = _ticks(
        [_player(items=[_ward(2055, count=1), _ward(2055, count=2)])],
        [_player(items=[_ward(2055, count=2), _ward(2055, count=1)])])
    assert counts == [0, 0]


def test_w4_duplicate_control_wards_are_summed():
    counts = _ticks(
        [_player(items=[_ward(2055, count=1), _ward(2055, count=1)])],
        [_player(items=[_ward(2055, count=1)])])
    assert counts == [0, 1]


def test_w4_summed_count_is_bounded_too():
    many = [_ward(2055, count=2) for _ in range(6)]  # sums to 12
    counts = _ticks([_player(items=[_ward(2055, count=2)])],
                    [_player(items=many)],
                    [_player(items=[_ward(2055, count=1)])])
    # The over-cap sum is unknown and carries 2, so 2 -> 1 is one placement.
    assert counts == [0, 0, 1]


def test_w4_duplicate_trinket_any_usable_is_usable():
    counts = _ticks(
        [_player(items=[_ward(3340, canUse=False), _ward(3340, canUse=True)])],
        [_player(items=[_ward(3340, canUse=True), _ward(3340, canUse=False)])])
    assert counts == [0, 0]


# W5 - duplicate player keys are skipped; teams keep same names apart.

def test_w5_duplicate_name_same_team_never_floods():
    snap = [_player("A", "ORDER", [_ward(2055, count=2)]),
            _player("A", "ORDER", [])]
    assert _ticks(snap, snap, snap, snap) == [0, 0, 0, 0]
    assert ward_events.buffer_size() == 0


def test_w5_same_name_on_opposite_teams_is_two_players():
    first = [_player("A", "ORDER", [_ward(2055, count=2)]),
             _player("A", "CHAOS", [])]
    second = [_player("A", "ORDER", [_ward(2055, count=2)]),
              _player("A", "CHAOS", [])]
    third = [_player("A", "ORDER", [_ward(2055, count=1)]),
             _player("A", "CHAOS", [])]
    assert _ticks(first, second, third) == [0, 0, 1]
    assert list(ward_events._buffer)[0]["side"] == "ally"


def test_w5_key_that_went_ambiguous_resumes_as_a_baseline():
    # The name multiset stays ("A", "A"), so the roster signature never
    # changes and only the dropped state stops a diff against stale data.
    first = [_player("A", "ORDER", [_ward(2055, count=2)]),
             _player("A", "CHAOS", [])]
    dup = [_player("A", "ORDER", []), _player("A", "ORDER", [])]
    third = [_player("A", "ORDER", [_ward(2055, count=0)]),
             _player("A", "CHAOS", [])]
    assert _ticks(first, dup, third) == [0, 0, 0]


# W6 - an unusable ts falls back to the clock; the count is honest.

@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "x", True,
                                 [1.0]])
def test_w6_unusable_ts_still_records(bad):
    ward_producer.tick([_player(items=[_ward(2055, count=2)])], ts=bad)
    n = ward_producer.tick([_player(items=[_ward(2055, count=1)])], ts=bad)
    assert n == 1
    assert ward_events.buffer_size() == 1
    # The clock, not 1.0 (a bool read as a time) - that ward would sit
    # outside every recent-wards window.
    assert abs(list(ward_events._buffer)[0]["ts"] - time.time()) < 60.0


def test_w6_real_ts_is_kept():
    _ticks([_player(items=[_ward(2055, count=2)])],
           [_player(items=[_ward(2055, count=1)])], start_ts=500.0)
    assert list(ward_events._buffer)[0]["ts"] == 501.0


# Non-changes.

def test_keep_absent_count_is_one():
    counts = _ticks([_player(items=[_ward(2055)])],
                    [_player(items=[])])
    assert counts == [0, 1]


def test_keep_control_ward_two_to_absent_is_two():
    counts = _ticks([_player(items=[_ward(2055, count=2)])],
                    [_player(items=[])])
    assert counts == [0, 2]


def test_keep_integral_float_count():
    counts = _ticks([_player(items=[_ward(2055, count=2.0)])],
                    [_player(items=[_ward(2055, count=1.0)])])
    assert counts == [0, 1]


def test_keep_trinket_swapped_away_is_not_a_placement():
    counts = _ticks([_player(items=[_ward(3340, canUse=True)])],
                    [_player(items=[_ward(3364, canUse=False)])])
    assert counts == [0, 0]


def test_keep_real_trinket_edge_is_one_placement():
    counts = _ticks([_player(items=[_ward(3340, canUse=True)])],
                    [_player(items=[_ward(3340, canUse=False)])])
    assert counts == [0, 1]
