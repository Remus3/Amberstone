"""Tests for core.arena_action_rule - the Stage 1 pure Arena action verdict.

decide_action encodes the operator's own Arena Haiku prompt rules
(coaches/arena_coach.py _SYSTEM_PROMPT: the ARENA PRIORITY DECISION TREE
block, the CAMP PHASE block and the OUTPUT FORMAT Action line) as a
deterministic ladder. It is pure, fail-soft
(never raises), and has no live wiring - these tests construct every
input directly.
"""
from __future__ import annotations

import math

from core.arena_action_rule import decide_action


def test_camp_phase_wins_over_any_hp() -> None:
    # Between rounds the only correct action is the shop/campfire - even
    # at critical HP the camp verdict wins outright.
    assert decide_action(5, True, None) == "BUY ITEMS"
    assert decide_action(100, True, None) == "BUY ITEMS"
    assert decide_action(None, True, None) == "BUY ITEMS"


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


# -- s144 true-audit: what counts as a reading ---------------------------------

_LABELS = {"BUY ITEMS", "KITE BACK", "ALL IN", "PLAY AGGRO", "FIGHT SMART"}


def test_camp_phase_is_a_signal_only_as_true() -> None:
    # The producer writes a bool (the arena vision schema), so a truthy
    # non-bool is junk, not a camp phase: each used to route BUY ITEMS over
    # any HP band. Deliberate tightening: the only live caller
    # (core/arena_deterministic_coach.py _in_camp) already passes `is True`.
    for junk in (1, "camp", "false", [0], math.nan, 1.0, object()):
        assert decide_action(90, junk, None) == "PLAY AGGRO", junk
        assert decide_action(10, junk, None) == "KITE BACK", junk
        assert decide_action(None, junk, None) == "FIGHT SMART", junk


def test_bool_hp_is_no_reading() -> None:
    # A bool is a flag, not a measurement: True read 1% and coached KITE BACK.
    assert decide_action(True, False, None) == "FIGHT SMART"
    assert decide_action(False, False, None) == "FIGHT SMART"


def test_string_hp_is_no_reading() -> None:
    # A str used to be float()-parsed: " 9e1 " read 90% and "1_000" 1000%.
    assert decide_action(" 9e1 ", False, None) == "FIGHT SMART"
    assert decide_action("1_000", False, 1) == "FIGHT SMART"
    assert decide_action("10", False, None) == "FIGHT SMART"


def test_hp_outside_band_is_no_reading() -> None:
    # hp_pct is a reading only in 0..150 (the producer admits 1.5x max).
    assert decide_action(-50, False, None) == "FIGHT SMART"
    assert decide_action(-0.1, False, None) == "FIGHT SMART"
    assert decide_action(150.1, False, None) == "FIGHT SMART"
    assert decide_action(1e300, False, None) == "FIGHT SMART"
    assert decide_action(200, False, 1) == "FIGHT SMART"
    assert decide_action(10**400, False, 1) == "FIGHT SMART"
    # The band edges are readings.
    assert decide_action(0, False, None) == "KITE BACK"
    assert decide_action(150, False, None) == "PLAY AGGRO"
    assert decide_action(150, False, 1) == "ALL IN"


def test_number_subclasses_are_readings() -> None:
    class _I(int):
        pass

    class _F(float):
        pass

    assert decide_action(_I(90), False, _I(1)) == "ALL IN"
    assert decide_action(_F(10.0), False, None) == "KITE BACK"


def test_low_opp_count_is_a_whole_number_in_band() -> None:
    # Arena fields eight teams of two, so at most 14 opponents can be low.
    assert decide_action(90, False, 14) == "ALL IN"
    assert decide_action(90, False, 2.0) == "ALL IN"  # integral float is a count
    assert decide_action(90, False, 15) == "PLAY AGGRO"
    assert decide_action(90, False, 10**400) == "PLAY AGGRO"
    assert decide_action(90, False, -1) == "PLAY AGGRO"
    assert decide_action(90, False, True) == "PLAY AGGRO"
    assert decide_action(90, False, "2") == "PLAY AGGRO"
    assert decide_action(90, False, math.inf) == "PLAY AGGRO"
    assert decide_action(90, False, math.nan) == "PLAY AGGRO"


def test_hostile_inputs_never_raise() -> None:
    # An object whose __class__ lookup raises makes isinstance raise; the
    # low-count isinstance used to sit outside any try, so this raised
    # RuntimeError out of a function documented "never raises".
    class _Hostile:
        @property
        def __class__(self):
            raise RuntimeError("boom")

    class _BadFloat(float):
        def __float__(self):
            raise RuntimeError("boom")

    class _BadInt(int):
        def __float__(self):
            raise RuntimeError("boom")

    for hp in (90, 10, 50, None, _Hostile(), _BadFloat(90.0), _BadInt(90)):
        for camp in (False, True, _Hostile()):
            for low in (None, 1, _Hostile(), _BadFloat(1.0), _BadInt(1)):
                out = decide_action(hp, camp, low)
                assert out in _LABELS
    assert decide_action(90, False, _Hostile()) == "PLAY AGGRO"
    assert decide_action(_Hostile(), False, None) == "FIGHT SMART"
    assert decide_action(_BadFloat(90.0), False, None) == "FIGHT SMART"
    assert decide_action(90, False, _BadInt(1)) == "PLAY AGGRO"


def test_rule_cites_prompt_blocks_not_line_numbers() -> None:
    # The prompt moved (the tree sat at :137-142 when cited, now :151+), so
    # the module cites the named prompt blocks, which must exist.
    import pathlib

    import core.arena_action_rule as rule

    doc = rule.__doc__ or ""
    assert "arena_coach.py:1" not in doc
    prompt = (pathlib.Path(__file__).resolve().parents[1]
              / "coaches" / "arena_coach.py").read_text(encoding="utf-8")
    for block in ("=== ARENA PRIORITY DECISION TREE ===", "=== CAMP PHASE ==="):
        assert block in prompt
        assert block in doc
