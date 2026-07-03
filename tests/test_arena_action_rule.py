# Tests for core.arena_action_rule - the Stage 1 pure Arena action verdict.
#
# decide_action encodes the operator's own Arena Haiku prompt rules
# (coaches/arena_coach.py:137-142 priority tree, 151-156 camp phase, 168
# label vocabulary) as a deterministic ladder. It is pure, fail-soft
# (never raises), and has no live wiring - these tests construct every
# input directly.
from __future__ import annotations

import math

from core.arena_action_rule import decide_action


def test_camp_phase_wins_over_any_hp() -> None:
    # Between rounds the only correct action is the shop/campfire - even
    # at critical HP the camp verdict wins outright.
    assert decide_action(5, True, None) == "BUY ITEMS"
    assert decide_action(100, True, None) == "BUY ITEMS"
    assert decide_action(50, 1, None) == "BUY ITEMS"
    assert decide_action(None, "camp", None) == "BUY ITEMS"


def test_low_hp_kites_back() -> None:
    # Prompt rule: NEVER all-in below 25 - survive to next camp phase.
    assert decide_action(24.9, False, None) == "KITE BACK"
    assert decide_action(0, None, None) == "KITE BACK"
    assert decide_action(10, 0, None) == "KITE BACK"


def test_high_hp_plays_aggro() -> None:
    assert decide_action(70.1, False, None) == "PLAY AGGRO"
    assert decide_action(100, None, None) == "PLAY AGGRO"
    # No low-opponent signal (0 / None) -> no ALL IN promotion.
    assert decide_action(90, False, 0) == "PLAY AGGRO"


def test_high_hp_with_low_opponent_promotes_all_in() -> None:
    assert decide_action(90, False, 1) == "ALL IN"
    assert decide_action(71, None, 2) == "ALL IN"


def test_all_in_requires_high_hp() -> None:
    # A low opponent alone never promotes below the aggro band.
    assert decide_action(50, False, 2) == "FIGHT SMART"
    assert decide_action(20, False, 2) == "KITE BACK"


def test_mid_band_fights_smart() -> None:
    assert decide_action(50, False, None) == "FIGHT SMART"
    assert decide_action(30, None, None) == "FIGHT SMART"
    assert decide_action(69, False, None) == "FIGHT SMART"


def test_band_edges_are_exclusive() -> None:
    # Strict < 25 and > 70 comparisons: both edges sit in the mid band.
    assert decide_action(25, False, None) == "FIGHT SMART"
    assert decide_action(70, False, None) == "FIGHT SMART"
    assert decide_action(70, False, 3) == "FIGHT SMART"


def test_unusable_hp_neutral_defaults() -> None:
    # No usable HP signal -> neutral FIGHT SMART (the Arena mirror of
    # ARAM's HOLD default), never a raise.
    assert decide_action(None, False, None) == "FIGHT SMART"
    assert decide_action(math.nan, False, None) == "FIGHT SMART"
    assert decide_action(math.inf, False, None) == "FIGHT SMART"
    assert decide_action(-math.inf, False, None) == "FIGHT SMART"
    assert decide_action("garbage", False, None) == "FIGHT SMART"
    assert decide_action(object(), False, None) == "FIGHT SMART"


def test_garbage_low_opp_count_never_promotes() -> None:
    # Only a clean int is a count; anything else (incl. a float like 1.5)
    # is garbage and cannot promote to ALL IN.
    assert decide_action(90, False, "x") == "PLAY AGGRO"
    assert decide_action(90, False, None) == "PLAY AGGRO"
    assert decide_action(90, False, 1.5) == "PLAY AGGRO"
    assert decide_action(90, False, [1]) == "PLAY AGGRO"


def test_never_raises_on_garbage() -> None:
    class _Nasty:
        def __bool__(self):
            raise RuntimeError("boom")

        def __float__(self):
            raise RuntimeError("boom")

        def __int__(self):
            raise RuntimeError("boom")

    garbage = (None, "x", math.nan, [1, 2], {"a": 1}, object(), _Nasty())
    for hp in garbage:
        for camp in garbage:
            for low in garbage:
                out = decide_action(hp, camp, low)
                assert isinstance(out, str)
                assert out in {
                    "BUY ITEMS",
                    "KITE BACK",
                    "ALL IN",
                    "PLAY AGGRO",
                    "FIGHT SMART",
                }
