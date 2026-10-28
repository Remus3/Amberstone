"""s144 true-audit: dashboard/_adaptation_latch.py never raises, never fakes a
latch and never lets one junk tick replace a true 10:00 / 15:00 value.

compute() is called unwrapped on the /api/state hot path
(dashboard/_state_builder.py, ``for k, v in _latch_compute(lc).items()``), and
its docstring promises "Malformed / missing input returns {} without raising".

Findings pinned here (each red at the pre-fix HEAD):

H1  A non-finite clock / cs / opponent creep_score raised OverflowError out
    of compute (``int(float('inf'))``), which ``except (TypeError,
    ValueError)`` does not catch.
H2  One unreadable-clock tick erased the latch. The producer
    (dashboard/_liveclient.py) reads a missing or out-of-range gameTime as 0,
    and 0 < the previous clock is a "time regression", so the latch reset and
    the NEXT tick re-latched cs_at_10 / csd_at_15 at the current, late clock
    (cs at 25:00 shown as cs_at_10) for the rest of the game.
H3  Junk numbers were latched: a bool cs read as 1, a negative cs or a
    negative opponent score was latched (csd 450), a 400-digit int reached
    /api/state, a fractional cs was truncated, "7_8" read as 78, a bool or
    400-digit clock was a clock, and a negative clock reset the latch.
H4  The lane opponent was guessed: any truthy is_active (the string "false")
    was the active player, the first of two active rows won, an enemy row
    with a blank team was an enemy, and two same-position enemies gave an
    arbitrary diff.
H5  A non-str / non-int game_id (a dict, True) was str()-ed into a game key,
    so a junk id flipping to "" reset a live latch mid-game.
"""
from __future__ import annotations

import math

import pytest

from dashboard import _adaptation_latch as latch


@pytest.fixture(autouse=True)
def _fresh():
    latch.reset()
    yield
    latch.reset()


def _s(t, cs, gid="g", players=None):
    out = {"game_time_s": t, "cs": cs, "game_id": gid}
    if players is not None:
        out["players"] = players
    return out


def _row(pos, team, cs, active=False):
    return {"position": pos, "team": team, "creep_score": cs,
            "is_active": active}


def _lane(me=130, opp=122):
    return [_row("MIDDLE", "ORDER", me, True), _row("MIDDLE", "CHAOS", opp),
            _row("TOP", "ORDER", 50), _row("TOP", "CHAOS", 45)]


# --------------------------------------------------------------------------
# H1 - never raises
# --------------------------------------------------------------------------

_NONFINITE = [math.inf, -math.inf, math.nan]


@pytest.mark.parametrize("bad", _NONFINITE, ids=["inf", "-inf", "nan"])
def test_h1_nonfinite_clock_does_not_raise(bad):
    assert latch.compute(_s(bad, 50)) == {}


@pytest.mark.parametrize("bad", _NONFINITE, ids=["inf", "-inf", "nan"])
def test_h1_nonfinite_cs_does_not_raise(bad):
    assert latch.compute(_s(650, bad)) == {}


@pytest.mark.parametrize("bad", _NONFINITE, ids=["inf", "-inf", "nan"])
def test_h1_nonfinite_opponent_score_does_not_raise(bad):
    assert latch.compute(_s(950, 130, players=_lane(130, bad))) == {
        "cs_at_10": 130}


# --------------------------------------------------------------------------
# H2 - one unreadable-clock tick never erases or re-dates the latch
# --------------------------------------------------------------------------

@pytest.mark.parametrize("gid", ["", "g"], ids=["no-id", "id"])
def test_h2_zero_clock_tick_keeps_cs_at_10(gid):
    assert latch.compute(_s(650, 78, gid)) == {"cs_at_10": 78}
    assert latch.compute(_s(0, 0, gid)) == {}
    # Before the fix: {"cs_at_10": 210}, the CS at 25:00.
    assert latch.compute(_s(1500, 210, gid)) == {"cs_at_10": 78}


def test_h2_zero_clock_tick_keeps_csd_at_15():
    assert latch.compute(_s(950, 130, players=_lane(130, 122))) == {
        "cs_at_10": 130, "csd_at_15": 8}
    assert latch.compute(_s(0, 131)) == {}
    assert latch.compute(_s(1500, 210, players=_lane(210, 150))) == {
        "cs_at_10": 130, "csd_at_15": 8}


def test_h2_new_game_after_zero_tick_still_resets():
    # An id-less game: the next game's first readable clock is a regression.
    assert latch.compute(_s(1500, 210, "")) == {"cs_at_10": 210}
    assert latch.compute(_s(0, 0, "")) == {}
    assert latch.compute(_s(5, 0, "")) == {}
    assert latch.compute(_s(640, 70, "")) == {"cs_at_10": 70}


def test_h2_new_game_id_on_zero_tick_resets():
    assert latch.compute(_s(1500, 210, "g1")) == {"cs_at_10": 210}
    assert latch.compute(_s(0, 0, "g2")) == {}
    assert latch.compute(_s(640, 70, "g2")) == {"cs_at_10": 70}


def test_h2_characterization_same_id_regression_still_resets():
    # Kept as designed (tests/test_adaptation_latch.py pins it): a READABLE
    # clock that runs backwards is a reconnect / restart signal.
    latch.compute(_s(650, 78))
    assert latch.compute(_s(100, 10)) == {}
    assert latch.compute(_s(610, 62)) == {"cs_at_10": 62}


# --------------------------------------------------------------------------
# H3 - junk numbers are never latched
# --------------------------------------------------------------------------

_BAD_COUNTS = [True, False, -5, 10 ** 400, 78.9, "7_8", "+78", " 78", "",
               chr(0x667) + chr(0x668), [78], {"cs": 78}, b"78", "9" * 5000]
_BAD_COUNT_IDS = ["true", "false", "neg", "huge", "frac", "underscore",
                  "plus", "space", "empty", "arabic-digits", "list", "dict",
                  "bytes", "5000-digit-str"]


@pytest.mark.parametrize("bad", _BAD_COUNTS, ids=_BAD_COUNT_IDS)
def test_h3_junk_cs_is_not_latched(bad):
    assert latch.compute(_s(650, bad)) == {}
    assert latch.compute(_s(655, 80)) == {"cs_at_10": 80}


@pytest.mark.parametrize("ok,want", [(78, 78), (78.0, 78), ("78", 78),
                                     (0, 0)],
                         ids=["int", "integral-float", "digits", "zero"])
def test_h3_valid_cs_vocabulary_unchanged(ok, want):
    assert latch.compute(_s(650, ok)) == {"cs_at_10": want}


@pytest.mark.parametrize("bad", _BAD_COUNTS, ids=_BAD_COUNT_IDS)
def test_h3_junk_opponent_score_is_not_latched(bad):
    assert latch.compute(_s(950, 130, players=_lane(130, bad))) == {
        "cs_at_10": 130}
    assert latch.compute(_s(955, 131, players=_lane(131, 120))) == {
        "cs_at_10": 130, "csd_at_15": 11}


_BAD_CLOCKS = [True, False, -5, -0.5, 10 ** 400, 10 ** 6 + 1, "6_50",
               "650.0", [650], None, "9" * 5000, 1e308]
_BAD_CLOCK_IDS = ["true", "false", "neg", "neg-float", "huge", "over-max",
                  "underscore", "float-str", "list", "none", "5000-digit-str",
                  "float-huge"]


@pytest.mark.parametrize("bad", _BAD_CLOCKS, ids=_BAD_CLOCK_IDS)
def test_h3_junk_clock_is_no_reading(bad):
    assert latch.compute(_s(650, 78)) == {"cs_at_10": 78}
    # A junk clock neither latches, nor resets, nor moves the clock.
    assert latch.compute(_s(bad, 3)) == {}
    assert latch.compute(_s(700, 99)) == {"cs_at_10": 78}


def test_h3_negative_fraction_clock_is_not_a_zero_tick():
    # int(-0.5) is 0: a floored negative must not pass as the zero tick that
    # still honours a game_id change.
    assert latch.compute(_s(650, 78, "g1")) == {"cs_at_10": 78}
    assert latch.compute(_s(-0.5, 3, "g2")) == {}
    assert latch.compute(_s(700, 99, "g1")) == {"cs_at_10": 78}


def test_h3_huge_clock_does_not_latch_early():
    assert latch.compute(_s(10 ** 400, 3)) == {}
    assert latch.compute(_s(300, 30)) == {}


@pytest.mark.parametrize("ok,want", [(650, 78), (650.9, 78), ("650", 78),
                                     (10 ** 6, 78)],
                         ids=["int", "float-floor", "digits", "max"])
def test_h3_valid_clock_vocabulary(ok, want):
    assert latch.compute(_s(ok, 78)) == {"cs_at_10": want}


def test_h3_float_clock_floors_below_threshold():
    assert latch.compute(_s(599.99, 78)) == {}


# --------------------------------------------------------------------------
# H4 - the lane opponent is never guessed
# --------------------------------------------------------------------------

def test_h4_only_json_true_is_active():
    players = [_row("MIDDLE", "ORDER", 9, "false"),
               _row("MIDDLE", "CHAOS", 40),
               _row("TOP", "CHAOS", 4, True),
               _row("TOP", "ORDER", 30)]
    # The real active player is TOP / CHAOS; its opponent has 30.
    assert latch.compute(_s(950, 50, players=players)) == {
        "cs_at_10": 50, "csd_at_15": 20}


def test_h4_two_active_rows_is_unresolvable():
    players = [_row("MIDDLE", "ORDER", 9, True), _row("TOP", "CHAOS", 4, True),
               _row("MIDDLE", "CHAOS", 40), _row("TOP", "ORDER", 30)]
    assert latch.compute(_s(950, 50, players=players)) == {"cs_at_10": 50}


@pytest.mark.parametrize("team", ["", "   ", None, ["CHAOS"], 7],
                         ids=["blank", "spaces", "none", "list", "int"])
def test_h4_enemy_without_a_team_is_not_an_opponent(team):
    players = [_row("MIDDLE", "ORDER", 9, True), _row("MIDDLE", team, 3),
               _row("MIDDLE", "CHAOS", 40)]
    assert latch.compute(_s(950, 50, players=players)) == {
        "cs_at_10": 50, "csd_at_15": 10}


@pytest.mark.parametrize("team", ["", None, ["ORDER"]],
                         ids=["blank", "none", "list"])
def test_h4_active_without_a_team_is_unresolvable(team):
    players = [_row("MIDDLE", team, 9, True), _row("MIDDLE", "CHAOS", 40)]
    assert latch.compute(_s(950, 50, players=players)) == {"cs_at_10": 50}


def test_h4_two_same_position_enemies_is_unresolvable():
    players = [_row("MIDDLE", "ORDER", 9, True), _row("MIDDLE", "CHAOS", 3),
               _row("MIDDLE", "CHAOS", 40)]
    assert latch.compute(_s(950, 50, players=players)) == {"cs_at_10": 50}


@pytest.mark.parametrize("pos", [["MIDDLE"], 5, None],
                         ids=["list", "int", "none"])
def test_h4_non_str_position_is_unresolvable(pos):
    players = [_row(pos, "ORDER", 9, True), _row(pos, "CHAOS", 40)]
    assert latch.compute(_s(950, 50, players=players)) == {"cs_at_10": 50}


def test_h4_padded_position_still_matches():
    # Characterization: the pre-fix strip() of position is kept.
    players = [_row(" MIDDLE ", "ORDER", 9, True), _row("MIDDLE", "CHAOS", 40)]
    assert latch.compute(_s(950, 50, players=players)) == {
        "cs_at_10": 50, "csd_at_15": 10}


def test_h4_csd_stays_within_count_bounds():
    out = latch.compute(_s(950, 10 ** 5, players=_lane(10 ** 5, 0)))
    assert out == {"cs_at_10": 10 ** 5, "csd_at_15": 10 ** 5}


# --------------------------------------------------------------------------
# H5 - a junk game_id is the missing id, not a new game key
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [{"a": 1}, True, ["g"], 1.5, "x" * 200],
                         ids=["dict", "true", "list", "float", "long"])
def test_h5_junk_game_id_is_the_missing_id(bad):
    assert latch.compute(_s(650, 78, "")) == {"cs_at_10": 78}
    # Before the fix: a reset and {"cs_at_10": 99}.
    assert latch.compute(_s(700, 99, bad)) == {"cs_at_10": 78}


@pytest.mark.parametrize("gid", [12345, "12345", " 12345 "],
                         ids=["int", "str", "padded"])
def test_h5_valid_game_ids_are_one_game(gid):
    assert latch.compute(_s(650, 78, "12345")) == {"cs_at_10": 78}
    assert latch.compute(_s(700, 99, gid)) == {"cs_at_10": 78}
