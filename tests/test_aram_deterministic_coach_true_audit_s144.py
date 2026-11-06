# s144 true-audit of core/aram_deterministic_coach.py (lane 8, one file).
#
# build_block documents that each field degrades INDEPENDENTLY and that it
# never raises. Measured before this fix: one >1e308 int hp_pct or
# owned_item_count, an inf gold or a 5000-digit gold raised out of a helper
# that sat outside its own try and blanked EVERY field of the block; a bool or
# a str was read as a number (False tower HP read "Enemy tower down - push to
# their base", "2" low enemies promoted ALL-IN); out-of-range values were
# banded (hp -5 read FALL BACK, a -5 tower read destroyed, 2.9 low enemies read
# 2); and the reasons map copied any value through to the shadow jsonl (a NaN
# wrote a bare NaN token, an object made json.dumps raise and lost the record).
from __future__ import annotations

import json
import math

from core.aram_deterministic_coach import build_block

_CC = "Enemy CC threats: Leona 2.0s stun (R)"


def _rich(**over):
    """A block with every non-target field populated, so a test can see that
    one junk input degrades only its own field."""
    kw = dict(
        hp_pct=50.0,
        cc_threat_line=_CC,
        item_build="Eclipse",
        next_item_name="Kraken Slayer",
        next_item_remaining_gold=1400,
        owned_item_count=3,
        my_tower_hp=90,
        enemy_tower_hp=80,
    )
    kw.update(over)
    return build_block(**kw)


def _assert_others_intact(block, *, skip=()):
    if "action" not in skip:
        assert block["action"] == "HOLD"
    assert "Leona" in block["fight_rule"]
    assert block["item_build"] == "Eclipse"
    if "reset_item" not in skip:
        assert block["reset_item"].startswith("No fountain trips; save toward Kraken Slayer")
    if "item_extra" not in skip:
        assert block["item_extra"] == "omit"
    if "objective" not in skip:
        assert block["objective"] != ""


# --- F1: a huge int / non-finite secondary input blanks only its own field ---


def test_f1_huge_int_hp_pct_blanks_only_action() -> None:
    block = _rich(hp_pct=10**400)
    assert block["action"] == ""
    _assert_others_intact(block, skip=("action",))


def test_f1_huge_int_owned_item_count_blanks_only_item_extra() -> None:
    block = _rich(owned_item_count=10**400)
    assert block["item_extra"] == ""
    _assert_others_intact(block, skip=("item_extra",))


def test_f1_huge_int_wave_pct_is_no_shift_not_no_action() -> None:
    assert _rich(wave_pct=10**400)["action"] == "HOLD"


def test_f1_inf_low_enemy_count_is_zero_not_no_action() -> None:
    assert _rich(hp_pct=90.0, low_enemy_count=math.inf)["action"] == "POKE"
    assert _rich(hp_pct=90.0, low_enemy_count=10**400)["action"] == "POKE"


def test_f1_huge_int_tower_hp_is_no_reading() -> None:
    block = _rich(my_tower_hp=10**400, enemy_tower_hp=None)
    assert block["objective"] == ""


# --- F2: a bool or a str is not a number ---


def test_f2_bool_and_str_hp_pct_are_no_reading() -> None:
    assert _rich(hp_pct=True)["action"] == ""
    assert _rich(hp_pct=False)["action"] == ""
    assert _rich(hp_pct="55")["action"] == ""
    assert _rich(hp_pct=" 5e1 ")["action"] == ""


def test_f2_str_and_bool_wave_pct_do_not_shift() -> None:
    assert _rich(wave_pct="70")["action"] == "HOLD"
    assert _rich(wave_pct=True)["action"] == "HOLD"
    # characterization: a real wave number still shifts
    assert _rich(wave_pct=70)["action"] == "POKE"
    assert _rich(wave_pct=20.0)["action"] == "DISENGAGE"


def test_f2_str_bool_or_fractional_low_enemy_count_cannot_promote() -> None:
    for junk in ("2", "3", 2.9, True, [2]):
        assert _rich(hp_pct=90.0, low_enemy_count=junk)["action"] == "POKE", junk
    # characterization: a real integral count promotes
    assert _rich(hp_pct=90.0, low_enemy_count=2)["action"] == "ALL-IN"
    assert _rich(hp_pct=90.0, low_enemy_count=2.0)["action"] == "ALL-IN"


def test_f2_false_or_str_zero_tower_is_not_a_destroyed_tower() -> None:
    assert build_block(enemy_tower_hp=False)["objective"] == ""
    assert build_block(enemy_tower_hp="0")["objective"] == ""
    assert build_block(my_tower_hp=False)["objective"] == ""
    assert build_block(my_tower_hp=True, enemy_tower_hp=None)["objective"] == ""
    # with a real enemy reading, a bool own tower drops out of the routing
    block = build_block(my_tower_hp=False, enemy_tower_hp=80)
    assert "chase" in block["objective"].lower()


def test_f2_bool_or_str_owned_item_count_is_no_signal() -> None:
    assert _rich(owned_item_count=True)["item_extra"] == ""
    assert _rich(owned_item_count="3")["item_extra"] == ""


def test_f2_bool_or_str_gold_is_no_gold() -> None:
    assert _rich(next_item_remaining_gold=True)["reset_item"] == (
        "No fountain trips; save toward Kraken Slayer."
    )
    assert _rich(next_item_remaining_gold="1400")["reset_item"] == (
        "No fountain trips; save toward Kraken Slayer."
    )
    # characterization: a real gold number is named
    assert _rich()["reset_item"] == (
        "No fountain trips; save toward Kraken Slayer (1400g remaining)."
    )
    assert "(900g remaining)" in _rich(next_item_remaining_gold=900.0)["reset_item"]


# --- F3: out-of-range readings are no reading ---


def test_f3_hp_pct_outside_the_producer_band_is_no_reading() -> None:
    assert _rich(hp_pct=-5)["action"] == ""
    assert _rich(hp_pct=151)["action"] == ""
    # the producer allows hp up to 1.5x max (dashboard _hp_fraction); a
    # transient over-max reading is full HP, not junk
    assert _rich(hp_pct=120.0)["action"] == "POKE"
    assert _rich(hp_pct=0)["action"] == "FALL BACK"
    assert _rich(hp_pct=100)["action"] == "POKE"


def test_f3_wave_pct_outside_0_100_does_not_shift() -> None:
    assert _rich(wave_pct=150)["action"] == "HOLD"
    assert _rich(wave_pct=-10)["action"] == "HOLD"


def test_f3_low_enemy_count_outside_0_5_cannot_promote() -> None:
    assert _rich(hp_pct=90.0, low_enemy_count=6)["action"] == "POKE"
    assert _rich(hp_pct=90.0, low_enemy_count=5)["action"] == "ALL-IN"


def test_f3_tower_hp_outside_0_100_is_no_reading() -> None:
    assert build_block(enemy_tower_hp=-5)["objective"] == ""
    assert build_block(my_tower_hp=-5)["objective"] == ""
    assert build_block(enemy_tower_hp=101)["objective"] == ""
    assert "their base" in build_block(enemy_tower_hp=0)["objective"].lower()
    assert "chase" in build_block(enemy_tower_hp=100)["objective"].lower()


def test_f3_negative_fractional_or_huge_owned_count_is_no_signal() -> None:
    for junk in (-0.5, 2.7, 65, 10**6):
        assert _rich(owned_item_count=junk)["item_extra"] == "", junk
    assert _rich(owned_item_count=0)["item_extra"] == "omit"
    assert _rich(owned_item_count=7.0)["item_extra"] == "omit"


# --- F4: junk gold never raises out of the reset line or blanks the block ---


def test_f4_inf_gold_names_no_gold_and_keeps_every_field() -> None:
    block = _rich(next_item_remaining_gold=math.inf)
    assert block["reset_item"] == "No fountain trips; save toward Kraken Slayer."
    _assert_others_intact(block)


def test_f4_5000_digit_gold_names_no_gold_and_keeps_every_field() -> None:
    block = _rich(next_item_remaining_gold=10**5000)
    assert block["reset_item"] == "No fountain trips; save toward Kraken Slayer."
    _assert_others_intact(block)


def test_f4_fractional_or_absurd_gold_is_not_truncated_or_named() -> None:
    assert "(12g" not in _rich(next_item_remaining_gold=12.9)["reset_item"]
    assert _rich(next_item_remaining_gold=12.9)["reset_item"].endswith("Slayer.")
    assert _rich(next_item_remaining_gold=10**6)["reset_item"].endswith("Slayer.")
    assert _rich(next_item_remaining_gold=math.nan)["reset_item"].endswith("Slayer.")
    # characterization: zero gold remaining names no gold (never "(0g")
    assert _rich(next_item_remaining_gold=0)["reset_item"].endswith("Slayer.")
    assert "(1g remaining)" in _rich(next_item_remaining_gold=1)["reset_item"]


# --- F5: the reasons map carries only non-blank str -> str entries ---


class _BadStr:
    def __str__(self):
        raise RuntimeError("boom")


def test_f5_non_str_or_blank_reason_values_are_dropped() -> None:
    block = build_block(item_build_reasons={
        "Kraken Slayer": "  spear proc  ",
        "NaN Item": math.nan,
        "Obj Item": object(),
        "Set Item": {1, 2},
        "Blank": "   ",
        "Num": 5,
    })
    assert block["item_build_reasons"] == {"Kraken Slayer": "spear proc"}


def test_f5_non_str_or_blank_keys_are_dropped_not_stringified() -> None:
    block = _rich(item_build_reasons={
        None: "x", 3078: "y", _BadStr(): "z", "  ": "w", " Eclipse ": "burst",
    })
    assert block["item_build_reasons"] == {"Eclipse": "burst"}
    _assert_others_intact(block)


def test_f5_block_is_strict_json_on_junk_reasons() -> None:
    block = _rich(item_build_reasons={"a": math.nan, "b": math.inf, "c": object()})
    json.dumps(block, allow_nan=False)


def test_f5_hints_still_ride_in_and_base_dict_is_not_mutated() -> None:
    base = {"Kraken Slayer": "core"}
    block = build_block(
        item_build_reasons=base,
        antitank_hint=" vs tanks: Lord Dominik's ",
        heal_threat_line="Heal threat: buy Grievous Wounds",
    )
    assert base == {"Kraken Slayer": "core"}
    assert block["item_build_reasons"] == {
        "Kraken Slayer": "core",
        "anti-tank": "vs tanks: Lord Dominik's",
        "anti-heal": "Heal threat: buy Grievous Wounds",
    }


# --- F6: a tuple build order is an order ---


def test_f6_tuple_build_order_is_joined() -> None:
    block = build_block(build_order=("Eclipse", "", "Edge of Night"))
    assert block["item_build"] == "Eclipse, Edge of Night"


# --- F7: a raise inside one field helper blanks only that field ---


class _BadStrip(str):
    __slots__ = ()

    def strip(self, *args):
        raise RuntimeError("boom")


def test_f7_raising_next_item_name_blanks_only_reset_item() -> None:
    block = _rich(next_item_name=_BadStrip("Kraken Slayer"))
    assert block["reset_item"] == ""
    _assert_others_intact(block, skip=("reset_item",))


def test_f7_raising_build_order_entry_blanks_only_item_build() -> None:
    block = _rich(item_build=None, build_order=[_BadStrip("Eclipse")])
    assert block["item_build"] == ""
    assert block["action"] == "HOLD"
    assert block["reset_item"].startswith("No fountain trips")
    assert block["objective"] != ""


def test_f7_raising_reason_key_blanks_only_reasons() -> None:
    block = _rich(item_build_reasons={_BadStrip("Eclipse"): "burst"})
    assert block["item_build_reasons"] == {}
    _assert_others_intact(block)


# --- block-wide: junk everywhere is strict JSON with every key ---


def test_block_is_strict_json_under_junk_everywhere() -> None:
    junk = (math.nan, math.inf, -math.inf, 10**400, True, "7", -1, object(), [])
    for v in junk:
        block = build_block(
            hp_pct=v, wave_pct=v, low_enemy_count=v, cc_threat_line=v,
            item_build=v, build_order=v, item_build_reasons={"k": v},
            next_item_name=v, next_item_remaining_gold=v, antitank_hint=v,
            heal_threat_line=v, owned_item_count=v, my_tower_hp=v,
            enemy_tower_hp=v,
        )
        json.dumps(block, allow_nan=False)
        assert len(block) == 9
