"""s144 true-audit (S144-T-683): input hardening for agents/daemon_slayer/boot_utility.py.

The scorer is pure and DEFAULT-OFF (core.build_order's assume_boot_utility ON
path), so every fix here is pinned two ways: the bad input now has a defined
answer, and every in-range input still gets exactly the old float back.

Findings pinned:
  F1 score_boot walked the WEIGHTS, so a non-finite weight on an axis a boot
     does not carry poisoned that boot too (0.0 * inf = nan) - one bad axis
     turned every boot's score into nan.
  F2 comp_weights passed shares / cc_proxy through unclamped: a percent (70)
     or an inf share outweighed every kit prior, a nan share made nan weights.
  F3 comp_weights read a whitespace-only archetype as "no archetype" (no kit
     prior) while core.build_order reads blank as "carry".
  F4 select_boot scaled a NEGATIVE default score by (1 + margin), which LOWERS
     the bar, so a challenger scoring WORSE than the default won; a negative or
     non-finite switch_margin was taken silently.
  F5 a bare string pool / roster was iterated per CHARACTER: comp_cc_signal
     ("Leona") read 0.0 ("no CC") instead of Leona's lockdown, and that 0.0
     overrode the v1 proxy fallback.
  F6 comp_cc_signal clamped with min(1.0, nan) == 1.0, so a nan per-champion
     score or a nan lockdown_ref SATURATED the CC axis; an inf ref read 0.0.
"""
from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import boot_utility as bu

INF = float("inf")
NAN = float("nan")


def _finite(x: float) -> bool:
    return isinstance(x, float) and math.isfinite(x)


# --- F1 ----------------------------------------------------------------------

def test_f1_nonfinite_weight_on_a_foreign_axis_does_not_poison_a_boot():
    # Berserker's carries only as_dps; an inf / nan on armor must not touch it.
    for bad in (INF, NAN, -INF):
        w = {"as_dps": 1.0, "armor_survival": bad}
        assert bu.score_boot(bu.BERSERKERS, w) == 1.0


def test_f1_nonfinite_weight_on_the_boots_own_axis_scores_zero_not_nan():
    for bad in (INF, NAN, -INF):
        s = bu.score_boot(bu.STEELCAPS, {"armor_survival": bad})
        assert s == 0.0


def test_f1_finite_weights_score_is_unchanged():
    w = {"armor_survival": 0.25, "mr_survival": 0.75, "tenacity": 0.3,
         "move_speed": 0.35, "as_dps": 1.0}
    assert bu.score_boot(bu.MERCURYS, w) == 0.75 * 1.0 + 0.3 * 1.0
    assert bu.score_boot(bu.SYMBIOTIC, w) == 0.7 * 0.35
    assert bu.score_boot("999999", w) == 0.0


# --- F2 ----------------------------------------------------------------------

def test_f2_out_of_range_shares_are_clamped_to_unit_interval():
    w = bu.comp_weights("tank", 70.0, -3.0, 5.0)
    assert w["armor_survival"] == 1.0
    assert w["mr_survival"] == 0.0
    assert w["tenacity"] == bu._TEN * 1.0


def test_f2_nonfinite_shares_give_finite_weights():
    for bad in (INF, -INF, NAN):
        w = bu.comp_weights("carry", bad, bad, bad)
        assert all(_finite(v) for v in w.values()), (bad, w)


def test_f2_nan_share_is_no_signal():
    w = bu.comp_weights("tank", NAN, 0.5, NAN)
    assert w["armor_survival"] == 0.0
    assert w["tenacity"] == 0.0


def test_f2_percent_share_no_longer_flips_a_carry_off_its_kit_boot():
    # 70 (a percent, not a fraction) used to give armor weight 70 -> Steelcaps.
    w = bu.comp_weights("carry", 70.0, 0.3, 0.0)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, bu.BERSERKERS) == bu.BERSERKERS


def test_f2_in_range_weights_are_byte_identical():
    w = bu.comp_weights("marksman", 0.2, 0.8, 0.9)
    assert w == {
        "armor_survival": bu._DEF * 0.2,
        "mr_survival": bu._DEF * 0.8,
        "tenacity": bu._TEN * 0.9,
        "move_speed": bu._MS,
        "as_dps": bu._KIT,
    }


def test_f2_non_numeric_share_is_still_a_loud_error():
    with pytest.raises((TypeError, ValueError)):
        bu.comp_weights("carry", "lots", 0.5, 0.0)


# --- F3 ----------------------------------------------------------------------

def test_f3_whitespace_archetype_reads_as_carry_like_build_order():
    assert bu.comp_weights("   ", 0.5, 0.5, 0.0) == bu.comp_weights("carry", 0.5, 0.5, 0.0)
    assert bu.comp_weights("", 0.5, 0.5, 0.0) == bu.comp_weights("carry", 0.5, 0.5, 0.0)
    assert bu.comp_weights(None, 0.5, 0.5, 0.0) == bu.comp_weights("carry", 0.5, 0.5, 0.0)


def test_f3_non_string_archetype_is_a_named_type_error():
    with pytest.raises(TypeError, match="archetype"):
        bu.comp_weights(5, 0.5, 0.5, 0.0)


# --- F4 ----------------------------------------------------------------------

def test_f4_negative_default_keeps_its_hysteresis_on_a_tie():
    # default -1.0, challenger -1.0 listed first: a TIE used to win (the bar
    # -1.0 * 1.15 = -1.15 sits BELOW the default), so the margin vanished.
    w = {"as_dps": -1.0, "move_speed": -1.0}
    pool = (bu.SWIFTNESS, bu.BERSERKERS)
    assert bu.select_boot(pool, w, bu.BERSERKERS) == bu.BERSERKERS


def test_f4_negative_default_keeps_its_hysteresis_on_a_marginal_lead():
    w = {"as_dps": -1.0, "move_speed": -0.95}
    pool = (bu.SWIFTNESS, bu.BERSERKERS)
    assert bu.select_boot(pool, w, bu.BERSERKERS) == bu.BERSERKERS


def test_f4_negative_default_still_yields_to_a_clearly_better_challenger():
    w = {"as_dps": -1.0, "move_speed": -0.5}
    pool = (bu.BERSERKERS, bu.SWIFTNESS)
    assert bu.select_boot(pool, w, bu.BERSERKERS) == bu.SWIFTNESS


@pytest.mark.parametrize("bad", [-0.1, NAN, INF, -INF])
def test_f4_bad_switch_margin_is_a_named_value_error(bad):
    with pytest.raises(ValueError, match="switch_margin"):
        bu.select_boot(bu.SELECTABLE_TIER2, bu.comp_weights("carry", 0.5, 0.5, 0.0),
                       bu.BERSERKERS, switch_margin=bad)


def test_f4_zero_margin_is_allowed():
    w = bu.comp_weights("carry", 0.5, 0.5, 0.0)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, bu.BERSERKERS, switch_margin=0.0) == bu.BERSERKERS


# --- F5 ----------------------------------------------------------------------

def test_f5_bare_string_pool_is_a_named_type_error():
    with pytest.raises(TypeError, match="pool"):
        bu.select_boot("3047", bu.comp_weights("tank", 0.9, 0.1, 0.0), bu.BERSERKERS)


def test_f5_bare_string_roster_is_a_named_type_error_not_a_zero_signal():
    # It used to read 0.0 ("no CC") off the letters L, e, o, n, a.
    with pytest.raises(TypeError, match="enemy_champions"):
        bu.comp_cc_signal("Leona")
    with pytest.raises(TypeError, match="enemy_champions"):
        bu.comp_cc_signal(b"Leona")


def test_f5_one_element_roster_still_reads_the_champion():
    assert bu.comp_cc_signal(["Leona"]) > 0.0


# --- F6 ----------------------------------------------------------------------

def test_f6_nan_lockdown_ref_is_unavailable_not_saturated():
    assert bu.comp_cc_signal(["Leona"], lockdown_ref=NAN) is None


def test_f6_inf_lockdown_ref_is_unavailable_not_zero():
    assert bu.comp_cc_signal(["Leona"], lockdown_ref=INF) is None


def test_f6_nan_per_champion_score_contributes_zero_not_saturation(monkeypatch):
    from agents.daemon_slayer import cc_output

    real = cc_output.compute_cc_output

    class _Bad:
        total_lockdown_score = NAN

    def fake(name, mode="SR"):
        if name == "Poisoned":
            return _Bad()
        return real(name, mode)

    monkeypatch.setattr(cc_output, "compute_cc_output", fake)
    # Jinx-only comp reads low; one nan member must not drive it to 1.0.
    clean = bu.comp_cc_signal(["Jinx", "Jinx"])
    mixed = bu.comp_cc_signal(["Jinx", "Poisoned"])
    assert clean < 1.0
    assert mixed == pytest.approx(clean / 2.0)


@pytest.mark.parametrize("bad", [-5.0, -INF, INF, NAN])
def test_f6_bad_member_does_not_drag_or_saturate_a_real_member(monkeypatch, bad):
    # A negative member used to cancel a real one (-5 + 1.3 -> clamped 0.0);
    # an inf / nan member used to saturate the comp to 1.0.
    from agents.daemon_slayer import cc_output

    real = cc_output.compute_cc_output

    class _Bad:
        total_lockdown_score = bad

    def fake(name, mode="SR"):
        return _Bad() if name == "Bad" else real(name, mode)

    monkeypatch.setattr(cc_output, "compute_cc_output", fake)
    alone = bu.comp_cc_signal(["Jinx"])
    assert 0.0 < alone < 1.0
    assert bu.comp_cc_signal(["Bad", "Jinx"]) == pytest.approx(alone / 2.0)


@pytest.mark.parametrize("bad", [INF, -INF, -2.0])
def test_f6_nonfinite_or_negative_per_champion_score_contributes_zero(monkeypatch, bad):
    from agents.daemon_slayer import cc_output

    class _Bad:
        total_lockdown_score = bad

    monkeypatch.setattr(cc_output, "compute_cc_output", lambda name, mode="SR": _Bad())
    assert bu.comp_cc_signal(["A", "B"]) == 0.0
