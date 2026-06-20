"""HZ-C1 - core.precomputed_laning_coach reader characterization tests.

Pins the live-state -> table-key mapping, the A/B choice shaping from one
precomputed laning cell, enemy coverage resolution, and the fail-soft empties.
Pure - operates on a synthetic in-memory payload (no table file, no network).
"""
from __future__ import annotations

import pytest

from core.coach_choices import CoachChoice
from core import precomputed_laning_coach as plc


# --------------------------------------------------------------------------- #
# Synthetic HZ-A payload (matches laning_scenarios/v3 leaf shape)
# --------------------------------------------------------------------------- #
def _cell(verdict, swing, recall, *, my_rm=0.3, en_rm=0.6, spike="first_item",
          gold=1300.0):
    return {
        "verdict": verdict,
        "net_swing": swing,
        "pct_my_removed": my_rm,
        "pct_enemy_removed": en_rm,
        "economy": {
            "recall": recall,
            "next_spike": spike,
            "gold_at_band": gold,
        },
    }


def _payload():
    return {
        "schema": "laning_scenarios/v3",
        "scenarios": {
            "Annie": {
                "Caitlyn": {
                    "L6": {
                        # all_in cell: kill-level scalars (enemy fully removed,
                        # I survive) so the recalibrated laning_band agrees with
                        # the labeled "all_in" verdict (RC2 WS1: the served chip
                        # is the band reclass of the scalars, not the raw label).
                        "full": {"all_up": _cell(
                            "all_in", 0.25, "recall_now", my_rm=0.30, en_rm=1.0)},
                        "low": {"all_up": _cell("back_off", -0.3, "hold")},
                    },
                    "L11": {
                        "full": {"no_ult": _cell("even", 0.0, "back_soon")},
                    },
                },
            },
        },
    }


# --------------------------------------------------------------------------- #
# band_for_level
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("level,band", [
    (1, "L2"), (2, "L2"), (3, "L2"),
    (4, "L6"), (6, "L6"), (8, "L6"),
    (9, "L11"), (11, "L11"), (13, "L11"),
    (14, "L16"), (16, "L16"), (18, "L16"),
    (None, "L2"), ("garbage", "L2"),
])
def test_band_for_level(level, band):
    assert plc.band_for_level(level) == band


# --------------------------------------------------------------------------- #
# mana_state_for / cd_state_for
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("frac,state", [
    (None, "full"), (1.0, "full"), (0.6, "full"), (0.5, "full"),
    (0.49, "low"), (0.0, "low"), ("nope", "full"),
])
def test_mana_state_for(frac, state):
    assert plc.mana_state_for(frac) == state


@pytest.mark.parametrize("ult,state", [
    (None, "all_up"), (True, "all_up"), (False, "no_ult"),
])
def test_cd_state_for(ult, state):
    assert plc.cd_state_for(ult) == state


# --------------------------------------------------------------------------- #
# precomputed_choices - covered cell shapes 2 A/B choices
# --------------------------------------------------------------------------- #
def test_covered_cell_returns_two_choices():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert len(out) == 2
    assert all(isinstance(c, CoachChoice) for c in out)
    assert out[0].key == "A" and out[1].key == "B"
    assert all(c.source_tag == plc.SOURCE_TAG for c in out)


def test_all_in_verdict_labels_combat_a():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert "All-in" in out[0].label
    assert "Caitlyn" in out[0].label
    # net_swing 0.25 -> high confidence band
    assert out[0].confidence == "high"
    # combat outcome carries the DS-backed swing + removal percents
    assert "net swing" in out[0].expected_outcome
    assert "100%" in out[0].expected_outcome  # pct_enemy_removed 1.0 (kill)


def test_recall_now_economy_drives_choice_b():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert out[1].label == "Recall now"


def test_next_item_folds_into_recall_outcome():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(), next_item=("Luden's Companion", 2900),
    )
    assert "Luden's Companion" in out[1].expected_outcome
    assert "2900" in out[1].expected_outcome


def test_low_mana_routes_to_low_cell():
    # mana_fraction 0.2 -> "low" state -> back_off verdict cell.
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=0.2, ult_up=True,
        payload=_payload(),
    )
    assert "Back off" in out[0].label
    # hold recall (not recall_now/back_soon) -> B is the prudent combat alt
    assert out[1].label == "Force a short trade"


def test_no_ult_routes_to_no_ult_cell():
    # L11 only has a no_ult cell; ult_up=False selects it.
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 11, mana_fraction=1.0, ult_up=False,
        payload=_payload(),
    )
    assert len(out) == 2
    assert out[1].label == "Back soon"  # economy back_soon


# --------------------------------------------------------------------------- #
# fail-soft empties
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("champ,enemy,level", [
    ("Annie", "Zed", 6),       # enemy not in table
    ("Yasuo", "Caitlyn", 6),   # champ not in table
    ("", "Caitlyn", 6),        # empty champ
    ("Annie", "", 6),          # empty enemy
])
def test_uncovered_or_empty_returns_empty(champ, enemy, level):
    out = plc.precomputed_choices(
        champ, enemy, level, payload=_payload(),
    )
    assert out == []


def test_l16_falls_back_to_l11_but_empty_when_l11_cell_absent():
    # L16 is not generated (item 370); precomputed_choices falls back to the
    # highest generated band L11. Annie/Caitlyn L11 only has a full/no_ult
    # cell, so a full/all_up L16 read finds no matching L11 cell either -> [].
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 16, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert out == []


def test_l16_falls_back_to_l11_when_cell_present():
    # ARAM ticks at lvl>=14 map to L16, which item 370 does not generate. The
    # reader falls back to L11 (highest generated band) so the live tick
    # accrues coverage for the flip gate instead of being silently dropped.
    payload = {
        "schema": "laning_scenarios/v3",
        "scenarios": {
            "Annie": {
                "Caitlyn": {
                    "L11": {"full": {"all_up": _cell("trade", 0.15, "hold")}},
                },
            },
        },
    }
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 18, mana_fraction=1.0, ult_up=True,
        payload=payload,
    )
    assert len(out) == 2
    assert "Trade" in out[0].label and "Caitlyn" in out[0].label


def test_l16_fallback_does_not_invent_uncovered_pair():
    # The band fallback rescues only the level axis; an uncovered (champ,enemy)
    # pair still yields [] (no lower-band data to fall back to).
    out = plc.precomputed_choices(
        "Annie", "Zed", 18, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert out == []


def test_generated_band_miss_does_not_fall_back():
    # A miss INSIDE a generated band (L6 low/no_ult absent here) must NOT
    # trigger the L16->L11 fallback - only non-generated bands fall back.
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=0.2, ult_up=False,
        payload=_payload(),
    )
    assert out == []


# --------------------------------------------------------------------------- #
# resolve_enemy - coverage-first lane-opponent pick
# --------------------------------------------------------------------------- #
def test_resolve_enemy_first_covered():
    enemy = plc.resolve_enemy(
        "Annie", ["Zed", "Caitlyn", "Lux"], payload=_payload(),
    )
    assert enemy == "Caitlyn"


def test_resolve_enemy_none_when_uncovered():
    assert plc.resolve_enemy(
        "Annie", ["Zed", "Yorick"], payload=_payload(),
    ) is None


def test_resolve_enemy_empty_inputs():
    assert plc.resolve_enemy("Annie", [], payload=_payload()) is None
    assert plc.resolve_enemy("", ["Caitlyn"], payload=_payload()) is None


# --------------------------------------------------------------------------- #
# RC2 WS1 step 1 - hold/farm verdict band + even relabel (calibration)
#
# Grounded in ops/audit/HZ_HAIKU_CALL_INVENTORY.md:49-108 and
# docs/research/RC2_COACHING_SPEC.md WS1 1.3 / 1.3a. The precompute verdict
# vocabulary had NO hold/farm band and was back_off-biased; Haiku said "hold"
# on 28% of ticks. These tests pin the new 5-band classifier and the even->hold
# A-chip relabel BEFORE the implementation (TDD failing-first).
#
# The shadow report (tools/hz_shadow_report.classify_verdict) buckets the
# A-label TEXT into a coarse verdict by ordered phrase match (first hit wins),
# so the labels here are asserted to classify as "hold" rather than "trade" /
# "even" / "back_off". We import that exact classifier to lock the contract.
# --------------------------------------------------------------------------- #
from tools.hz_shadow_report import classify_verdict  # noqa: E402


# laning_band: pure 5-band reclassifier over the cell scalars (no engine call).
# Bands (spec 1.3): all_in / trade / even / hold / back_off.
@pytest.mark.parametrize("swing,my_rm,en_rm,expected", [
    # enemy fully removed, I survive -> all_in (highest precedence)
    (0.40, 0.30, 1.0, "all_in"),
    # I am the one who dies -> back_off (regardless of swing sign)
    (0.05, 1.0, 0.50, "back_off"),
    # firmly favored swing -> trade
    (0.20, 0.20, 0.60, "trade"),
    (0.10, 0.25, 0.55, "trade"),
    # NEW hold band: mildly negative swing, not a hard back-off
    (-0.05, 0.45, 0.30, "hold"),
    (-0.12, 0.50, 0.25, "hold"),
    (-0.17, 0.55, 0.20, "hold"),
    # firmly negative -> back_off
    (-0.18, 0.60, 0.15, "back_off"),
    (-0.40, 0.80, 0.05, "back_off"),
    # dead-zone small swing -> even
    (0.00, 0.30, 0.30, "even"),
    (0.04, 0.30, 0.28, "even"),
    (-0.04, 0.30, 0.32, "even"),
])
def test_laning_band_five_band_classifier(swing, my_rm, en_rm, expected):
    cell = _cell("ignored", swing, "hold", my_rm=my_rm, en_rm=en_rm)
    assert plc.laning_band(cell) == expected


def test_laning_band_hold_is_distinct_from_back_off():
    # The whole point of the calibration: the mild-negative band that used to
    # collapse into back_off now resolves to a separate "hold" verdict.
    mild = _cell("x", -0.10, "hold", my_rm=0.45, en_rm=0.30)
    hard = _cell("x", -0.30, "hold", my_rm=0.70, en_rm=0.10)
    assert plc.laning_band(mild) == "hold"
    assert plc.laning_band(hard) == "back_off"
    assert plc.laning_band(mild) != plc.laning_band(hard)


def test_laning_band_fail_soft_on_garbage_cell():
    # Hot-path contract: never raises; a malformed cell falls back to "even".
    assert plc.laning_band({}) == "even"
    assert plc.laning_band({"net_swing": "nope"}) == "even"


# _VERDICT_LABELS now carries a distinct hold entry, and the even A-chip is
# relabeled so the shadow report buckets it as "hold" (the +57-tick audit win).
def test_verdict_labels_has_hold_entry():
    assert "hold" in plc._VERDICT_LABELS
    a_label, _b_label = plc._VERDICT_LABELS["hold"]
    # The A-label must classify as the coarse "hold" verdict, not trade/even.
    assert classify_verdict(a_label) == "hold"


def test_even_a_chip_relabeled_to_hold_bucket():
    # Before: even A-chip "Even trade on your cd window" classified as "even".
    # After the relabel it must classify as "hold" so it agrees with Haiku's
    # dominant "hold" call (HZ_HAIKU_CALL_INVENTORY.md:97-99).
    a_label, _b = plc._VERDICT_LABELS["even"]
    assert classify_verdict(a_label) == "hold"


def test_even_label_distinct_from_back_off_label():
    # even and back_off must remain semantically separate A-labels (the audit
    # warns the precompute was back_off-biased; even must not read as back_off).
    even_a = plc._VERDICT_LABELS["even"][0]
    back_a = plc._VERDICT_LABELS["back_off"][0]
    assert even_a != back_a
    assert classify_verdict(even_a) != classify_verdict(back_a)
    assert classify_verdict(back_a) == "back_off"


def test_hold_verdict_emits_hold_classifying_choice_a():
    # An end-to-end read of a cell whose verdict is "hold" yields an A-chip
    # whose label buckets as "hold" in the shadow report.
    payload = {
        "schema": "laning_scenarios/v3",
        "scenarios": {
            "Annie": {
                "Caitlyn": {
                    "L6": {"full": {"all_up": _cell("hold", -0.10, "hold")}},
                },
            },
        },
    }
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True, payload=payload,
    )
    assert len(out) == 2
    assert classify_verdict(out[0].label) == "hold"


# --------------------------------------------------------------------------- #
# RC2 5.3 - ABC choices specificity uplift: the trigger field
#
# Each chip now names the live CONDITION the option assumes (the lookup key),
# stamped onto CoachChoice.trigger. docs/research/RC2_COACHING_SPEC.md WS2 2.3:
# "The trigger is already KNOWN at cell-resolution time - it is the lookup key.
# Stamp it instead of discarding it." Rich (shadow precompute): enemy + mana +
# cd + lvl. Pure + fail-soft (never raises on the coach hot path).
# --------------------------------------------------------------------------- #
def test_laning_trigger_rich_all_keys():
    # Full key set -> "Caitlyn, full mana, ult up, lvl 6".
    t = plc.laning_trigger("Caitlyn", 6, mana_state="full", cd_state="all_up")
    assert t == "Caitlyn, full mana, ult up, lvl 6"


def test_laning_trigger_low_mana_no_ult():
    t = plc.laning_trigger("Zed", 11, mana_state="low", cd_state="no_ult")
    assert t == "Zed, low mana, ult down, lvl 11"


def test_laning_trigger_lean_level_only():
    # No mana/cd known (served matchup seam) -> "Caitlyn, lvl 6".
    t = plc.laning_trigger("Caitlyn", 6)
    assert t == "Caitlyn, lvl 6"


def test_laning_trigger_fail_soft_garbage_level():
    # Non-numeric level drops the lvl clause; never raises.
    assert plc.laning_trigger("Caitlyn", "nope") == "Caitlyn"
    assert plc.laning_trigger("", None) == "enemy"


def test_precomputed_choices_stamps_trigger_on_ab():
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=1.0, ult_up=True,
        payload=_payload(),
    )
    assert len(out) == 2
    # Both A and B carry the SAME resolved-condition trigger.
    assert out[0].trigger == "Caitlyn, full mana, ult up, lvl 6"
    assert out[1].trigger == out[0].trigger


def test_precomputed_choices_trigger_reflects_low_mana():
    # low mana routes to the L6 low/all_up back_off cell; trigger mirrors keys.
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 6, mana_fraction=0.2, ult_up=True,
        payload=_payload(),
    )
    assert out[0].trigger == "Caitlyn, low mana, ult up, lvl 6"


def test_precomputed_choices_trigger_reflects_no_ult():
    # L11 only has a full/no_ult cell; the trigger reads "ult down".
    out = plc.precomputed_choices(
        "Annie", "Caitlyn", 11, mana_fraction=1.0, ult_up=False,
        payload=_payload(),
    )
    assert out[0].trigger == "Caitlyn, full mana, ult down, lvl 11"
