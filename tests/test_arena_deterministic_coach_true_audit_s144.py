"""s144 true-audit of core/arena_deterministic_coach.py (lane 8, one file).

build_block documents that each field degrades INDEPENDENTLY and that it
never raises. Measured before this fix: a bool or a str hp_pct was a reading
(True read "Your HP 1%" and KITE BACK, " 6e1 " read 60%); hp was not banded
(-50 read KITE BACK with "Your HP -50%", 1e300 printed a 300-digit HP line);
alive_teams took a str ("3"), truncated 2.7 to 2 and printed -5, 0 and
1000000 teams; a NaN, "false" or [0] camp_phase routed BUY ITEMS although the
producer only ever writes a bool (coaches/arena_coach.py vision schema); a
10**400 low-opponent count promoted ALL IN while an integral 2.0 did not; a
tuple build order was not an order and a head carrying a newline or 5000
chars was coached verbatim; and one raise inside the round_strategy or
anvil helper blanked EVERY field of the block.
"""
from __future__ import annotations

import json

from core.arena_deterministic_coach import build_block

_CC = "Enemy CC threats: Ashe 3.0s stun (R)"


def _rich(**over):
    """A block with every non-target field populated, so a test can see that
    one junk input degrades only its own field."""
    kw = dict(
        hp_pct=50.0,
        alive_teams=4,
        cc_threat_line=_CC,
        build_remaining=["Infinity Edge", "Bloodthirster"],
    )
    kw.update(over)
    return build_block(**kw)


# --- F1: a bool or a str is never an HP reading ---


def test_f1_bool_hp_is_no_reading() -> None:
    for hp in (True, False):
        block = build_block(hp_pct=hp)
        assert block["action"] == ""
        assert block["round_strategy"] == ""


def test_f1_str_hp_is_no_reading() -> None:
    for hp in ("60", " 6e1 ", "10"):
        block = build_block(hp_pct=hp)
        assert block["action"] == ""
        assert block["round_strategy"] == ""


def test_f1_number_hp_still_reads() -> None:
    assert build_block(hp_pct=10)["action"] == "KITE BACK"
    assert build_block(hp_pct=50.0)["round_strategy"] == (
        "Your HP 50% - trade efficiently and kite"
    )


# --- F2: hp is banded 0..150 and never displayed past 100% ---


def test_f2_negative_hp_is_no_reading() -> None:
    block = build_block(hp_pct=-50)
    assert block["action"] == ""
    assert block["round_strategy"] == ""


def test_f2_huge_hp_is_no_reading() -> None:
    for hp in (1e300, 151, 10**400):
        block = build_block(hp_pct=hp)
        assert block["action"] == ""
        assert block["round_strategy"] == ""


def test_f2_band_edges_read() -> None:
    assert build_block(hp_pct=0)["action"] == "KITE BACK"
    assert build_block(hp_pct=150)["action"] == "PLAY AGGRO"


def test_f2_over_max_hp_displays_full() -> None:
    # The producer (_hp_fraction) admits hp up to 1.5x max: that is full HP.
    line = build_block(hp_pct=150)["round_strategy"]
    assert line == "Your HP 100% - make plays, take risks"


# --- F3: alive_teams is a whole 1..8 ---


def test_f3_str_teams_omit_clause() -> None:
    line = build_block(hp_pct=50, alive_teams="3")["round_strategy"]
    assert line == "Your HP 50% - trade efficiently and kite"


def test_f3_fractional_teams_omit_clause() -> None:
    line = build_block(hp_pct=50, alive_teams=2.7)["round_strategy"]
    assert "teams left" not in line


def test_f3_out_of_range_teams_omit_clause() -> None:
    for teams in (-5, 0, 9, 10**6, 10**400, float("inf")):
        line = build_block(hp_pct=50, alive_teams=teams)["round_strategy"]
        assert line == "Your HP 50% - trade efficiently and kite", teams


def test_f3_valid_teams_render() -> None:
    assert "1 teams left" in build_block(hp_pct=50, alive_teams=1)["round_strategy"]
    assert "8 teams left" in build_block(hp_pct=50, alive_teams=8)["round_strategy"]
    assert "3 teams left" in build_block(hp_pct=50, alive_teams=3.0)["round_strategy"]


# --- F4: only a real True is a camp-phase signal ---


def test_f4_non_bool_camp_phase_is_no_signal() -> None:
    for camp in (float("nan"), "false", "True", [0], 1, {"x": 1}):
        block = build_block(camp_phase=camp)
        assert block["action"] == "", camp
        assert block["round_strategy"] == ""


def test_f4_non_bool_camp_phase_does_not_override_hp() -> None:
    assert build_block(hp_pct=10, camp_phase="false")["action"] == "KITE BACK"


def test_f4_true_camp_phase_still_wins() -> None:
    assert build_block(hp_pct=10, camp_phase=True)["action"] == "BUY ITEMS"
    assert build_block(hp_pct=10, camp_phase=False)["action"] == "KITE BACK"


# --- F5: the low-opponent count is a whole 0..14 ---


def test_f5_huge_low_count_does_not_promote() -> None:
    for low in (10**400, 15, 10**6):
        assert build_block(hp_pct=90, low_opp_count=low)["action"] == "PLAY AGGRO", low


def test_f5_integral_float_low_count_promotes() -> None:
    assert build_block(hp_pct=90, low_opp_count=2.0)["action"] == "ALL IN"
    assert build_block(hp_pct=90, low_opp_count=14)["action"] == "ALL IN"


def test_f5_junk_low_count_does_not_promote() -> None:
    for low in (True, "2", 1.5, -3, float("nan"), float("inf")):
        assert build_block(hp_pct=90, low_opp_count=low)["action"] == "PLAY AGGRO", low


# --- F6: the anvil head is a clean, bounded item name; a tuple is an order ---


def test_f6_tuple_build_is_an_order() -> None:
    block = build_block(build_remaining=("Infinity Edge", "Bloodthirster"))
    assert block["anvil_advice"] == "Build toward Infinity Edge next."


def test_f6_head_whitespace_is_collapsed() -> None:
    block = build_block(build_remaining=["Infinity\nEdge\t "])
    assert block["anvil_advice"] == "Build toward Infinity Edge next."


def test_f6_overlong_head_is_no_item() -> None:
    assert build_block(build_remaining=["x" * 65])["anvil_advice"] == ""
    assert build_block(build_remaining=["x" * 64])["anvil_advice"] == (
        "Build toward " + "x" * 64 + " next."
    )


# --- F7: one raising helper blanks only its own field ---


class _BadStr(str):
    __slots__ = ()

    def strip(self, *args):
        raise RuntimeError("boom")

    def split(self, *args, **kwargs):
        raise RuntimeError("boom")


def test_f7_raising_build_head_blanks_only_anvil() -> None:
    block = _rich(build_remaining=[_BadStr("Infinity Edge")])
    assert block["anvil_advice"] == ""
    assert block["action"] == "FIGHT SMART"
    assert block["round_strategy"] == "Your HP 50%; 4 teams left - trade efficiently and kite"
    assert "Ashe" in block["fight_rule"]
    assert "Ashe" in block["risk"]
    assert len(block["choices"]) == 2


def test_f7_raising_round_strategy_blanks_only_its_field(monkeypatch) -> None:
    import core.arena_deterministic_coach as mod

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "_clamp_words", _boom)
    block = _rich()
    assert block["round_strategy"] == ""
    assert block["action"] == "FIGHT SMART"
    assert block["anvil_advice"] == "Build toward Infinity Edge next."
    assert "Ashe" in block["fight_rule"]
    assert len(block["choices"]) == 2


def test_f7_wrong_typed_helper_result_degrades_only_its_field(monkeypatch) -> None:
    import core.arena_deterministic_coach as mod

    monkeypatch.setattr(mod, "_anvil_line", lambda *args: None)
    monkeypatch.setattr(mod, "_safe_choices", lambda *args: "not a list")
    block = _rich()
    assert block["anvil_advice"] == ""
    assert block["choices"] == []
    assert block["action"] == "FIGHT SMART"


class _RaisingFloat(float):
    def __float__(self):
        raise RuntimeError("boom")


class _RaisingInt(int):
    def __float__(self):
        raise ValueError("boom")


def test_f7_number_subclass_with_raising_float_is_no_reading() -> None:
    # hp is read once, before the per-field guards; a number subclass whose
    # __float__ raises must be no reading, never an exception out of
    # build_block (verifier finding on the first draft of this fix).
    for value in (_RaisingFloat(50.0), _RaisingInt(50)):
        block = _rich(hp_pct=value, alive_teams=value, low_opp_count=value)
        assert block["action"] == ""
        assert block["round_strategy"] == ""
        assert block["anvil_advice"] == "Build toward Infinity Edge next."
        assert "Ashe" in block["fight_rule"]


class _RaisingClass:
    @property
    def __class__(self):
        raise RuntimeError("boom")


def test_f7_raising_type_lookup_is_no_reading() -> None:
    # isinstance() consults __class__; a raise there must be no reading, never
    # an exception out of build_block (second verifier finding).
    block = _rich(hp_pct=_RaisingClass(), alive_teams=_RaisingClass())
    assert block["action"] == ""
    assert block["anvil_advice"] == "Build toward Infinity Edge next."
    assert "Ashe" in block["fight_rule"]


# --- the block stays strict JSON and str-typed across junk inputs ---


def test_block_is_strict_json_under_junk() -> None:
    junk = (None, True, "x", float("nan"), float("inf"), -1, 10**400, [], {}, object())
    for value in junk:
        block = build_block(
            hp_pct=value,
            camp_phase=value,
            low_opp_count=value,
            alive_teams=value,
            build_remaining=value,
        )
        json.dumps(block, allow_nan=False)
        for key, field in block.items():
            if key != "choices":
                assert isinstance(field, str)
