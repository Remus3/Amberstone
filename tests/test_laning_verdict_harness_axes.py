"""Tests for the axis-sweep options on tools/replay_laning_verdict_validate.py.

The gate historically scored ONE cell per lane pair - the ``full`` / ``all_up``
unknown-state baseline with ``item_state`` left at its ``lookup`` default. That
silently collapsed the cd_state axis (``all_up`` / ``no_ult``, both present in
every shipped table) and the v4 ``item_state`` axis, so a whole family of cells
was never measured and a flip decision rested on a single slice.

These tests pin the NEW ``--cd-state`` / ``--item-state`` sweep plumbing and,
critically, pin that the DEFAULT axes are unchanged - the 2026-06 baseline
number is only comparable if an un-flagged run still resolves the exact same
cell it always did.

Everything here is pure: hand-built payload dicts through the real ``lookup``,
and accumulator objects. No 1.8GB replay DB and no 67MB shipped table is
touched, so the corpus can drift without breaking the suite.

ASCII only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"
for _p in (str(_ROOT), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_mod():
    """Import the tool module by path (tools/ is not a package)."""
    path = _TOOLS / "replay_laning_verdict_validate.py"
    spec = importlib.util.spec_from_file_location("replay_laning_verdict_validate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_mod()


# --------------------------------------------------------------------- fixtures
def _cell(verdict: str, swing: float) -> dict:
    return {"verdict": verdict, "net_swing": swing}


def _v4_payload() -> dict:
    """A v4 payload whose every axis cell carries a DISTINCT verdict, so a test
    that resolves the wrong cell cannot accidentally pass."""
    return {
        "schema": "laning_scenarios/v4",
        "scenarios": {
            "Aatrox": {
                "Darius": {
                    "L6": {
                        "full": {
                            "all_up": {
                                "none": _cell("trade", 0.10),
                                "first_item": _cell("all_in", 0.40),
                                "two_item": _cell("back_off", -0.30),
                            },
                            "no_ult": {
                                "none": _cell("back_off", -0.20),
                                "first_item": _cell("trade", 0.15),
                            },
                        },
                        "low": {
                            "all_up": {"none": _cell("back_off", -0.50)},
                        },
                    },
                },
            },
        },
    }


def _v3_payload() -> dict:
    """A v3 payload - the cd node IS the leaf cell. Every shipped table on disk
    is still this shape, so the sweep must not break it."""
    return {
        "schema": "laning_scenarios/v3",
        "scenarios": {
            "Aatrox": {
                "Darius": {
                    "L6": {
                        "full": {
                            "all_up": _cell("trade", 0.10),
                            "no_ult": _cell("back_off", -0.20),
                        },
                    },
                },
            },
        },
    }


# ------------------------------------------------- default axes must not move
def test_make_verdict_fn_default_axes_match_the_june_baseline_cell():
    """An un-flagged run must resolve full/all_up/none - the exact cell the
    2026-06 baseline scored. A changed default silently invalidates the diff."""
    fn = MOD.make_verdict_fn(_v4_payload())
    assert fn("Aatrox", "Darius", 6) == ("trade", 0.10)


def test_module_axis_defaults_are_the_documented_unknown_state_baseline():
    assert MOD._DEFAULT_MANA_STATE == "full"
    assert MOD._DEFAULT_CD_STATE == "all_up"
    assert MOD._DEFAULT_ITEM_STATE == "none"


# ----------------------------------------------------------------- axis descent
def test_make_verdict_fn_honors_cd_state():
    fn = MOD.make_verdict_fn(_v4_payload(), cd_state="no_ult")
    assert fn("Aatrox", "Darius", 6) == ("back_off", -0.20)


def test_make_verdict_fn_honors_item_state():
    fn = MOD.make_verdict_fn(_v4_payload(), item_state="two_item")
    assert fn("Aatrox", "Darius", 6) == ("back_off", -0.30)


def test_make_verdict_fn_honors_both_axes_together():
    fn = MOD.make_verdict_fn(_v4_payload(), cd_state="no_ult", item_state="first_item")
    assert fn("Aatrox", "Darius", 6) == ("trade", 0.15)


def test_make_verdict_fn_honors_mana_state():
    fn = MOD.make_verdict_fn(_v4_payload(), mana_state="low")
    assert fn("Aatrox", "Darius", 6) == ("back_off", -0.50)


def test_item_state_absent_falls_back_to_none_cell():
    """The reader's descend-only fallback: an item_state the table does not
    carry resolves the ``none`` cell rather than reporting uncovered."""
    fn = MOD.make_verdict_fn(_v4_payload(), item_state="three_item")
    assert fn("Aatrox", "Darius", 6) == ("trade", 0.10)


def test_v3_payload_ignores_item_state_but_still_honors_cd_state():
    """v3 has no item_state axis at all, so sweeping it is a no-op there - but
    cd_state is real in every shipped v3 table and must still move the cell."""
    payload = _v3_payload()
    assert MOD.make_verdict_fn(payload, item_state="two_item")(
        "Aatrox", "Darius", 6) == ("trade", 0.10)
    assert MOD.make_verdict_fn(payload, cd_state="no_ult")(
        "Aatrox", "Darius", 6) == ("back_off", -0.20)


def test_missing_cd_state_is_uncovered_not_a_crash():
    fn = MOD.make_verdict_fn(_v4_payload(), cd_state="does_not_exist")
    assert fn("Aatrox", "Darius", 6) == (None, None)


# ------------------------------------------------------------------ csv parsing
def test_parse_states_splits_and_strips():
    assert MOD._parse_states("all_up, no_ult ", "all_up") == ["all_up", "no_ult"]


def test_parse_states_dedupes_preserving_order():
    assert MOD._parse_states("b,a,b", "z") == ["b", "a"]


def test_parse_states_empty_falls_back_to_the_default_state():
    assert MOD._parse_states("", "all_up") == ["all_up"]
    assert MOD._parse_states(None, "none") == ["none"]
    assert MOD._parse_states(" , ", "none") == ["none"]


# ------------------------------------------------------------ combo enumeration
def test_sweep_axis_combos_is_the_cartesian_product_cd_major():
    assert MOD.sweep_axis_combos(["all_up", "no_ult"], ["none", "two_item"]) == [
        ("all_up", "none"),
        ("all_up", "two_item"),
        ("no_ult", "none"),
        ("no_ult", "two_item"),
    ]


def test_sweep_axis_combos_single_axis_is_one_column():
    assert MOD.sweep_axis_combos(["all_up"], ["none"]) == [("all_up", "none")]


# ------------------------------------------------------------------------- CLI
def test_cli_defaults_leave_the_sweep_flags_unset():
    """Absent flags must parse to None - that is what keeps an un-flagged run
    byte-comparable with the June baseline."""
    args = MOD.build_arg_parser().parse_args([])
    assert args.cd_state is None
    assert args.item_state is None


def test_cli_accepts_the_sweep_flags():
    args = MOD.build_arg_parser().parse_args(
        ["--cd-state", "all_up,no_ult", "--item-state", "none,two_item"])
    assert args.cd_state == "all_up,no_ult"
    assert args.item_state == "none,two_item"


# --------------------------------------------------------------- base-rate math
def test_label_base_rate_reports_predictor_and_label_balance():
    """The interpretation guard: ~0.50 agreement is only evidence against the
    VERDICT if both the predictor and the label actually vary. A degenerate
    predictor or a one-sided label would make the number meaningless."""
    br = MOD._LabelBaseRate()
    for fav_a, gold_a, gold_b in (
        (True, 100, 50),
        (True, 50, 100),
        (False, 100, 50),
        (False, 50, 100),
    ):
        br.record(fav_a, gold_a, gold_b)
    out = br.to_dict()
    assert out["n"] == 4
    assert out["predictor_favors_a_rate"] == 0.5
    assert out["label_favors_a_rate"] == 0.5
    assert out["label_ties"] == 0


def test_label_base_rate_excludes_ties_from_the_label_rate():
    br = MOD._LabelBaseRate()
    br.record(True, 100, 100)
    br.record(True, 100, 50)
    out = br.to_dict()
    assert out["label_ties"] == 1
    assert out["label_favors_a_rate"] == 1.0
    assert out["predictor_favors_a_rate"] == 1.0


def test_label_base_rate_empty_is_none_not_a_zero_division():
    out = MOD._LabelBaseRate().to_dict()
    assert out["n"] == 0
    assert out["predictor_favors_a_rate"] is None
    assert out["label_favors_a_rate"] is None
