"""Unit tests for the DEFAULT-OFF boot utility scorer (agents/daemon_slayer/boot_utility.py)."""
from __future__ import annotations

from agents.daemon_slayer import boot_utility as bu

NEUTRAL = dict(enemy_ad_share=0.5, enemy_ap_share=0.5, cc_proxy=0.0)


def _w(archetype, **over):
    ctx = {**NEUTRAL, **over}
    return bu.comp_weights(archetype, ctx["enemy_ad_share"], ctx["enemy_ap_share"], ctx["cc_proxy"])


def test_profile_covers_selectable_pool():
    for bid in bu.SELECTABLE_TIER2:
        assert bid in bu.BOOT_UTILITY_PROFILE, bid


def test_marksman_neutral_comp_keeps_berserkers():
    # DPS kit, no defensive signal -> archetype default (Berserker's 3006) holds.
    assert bu.select_boot(bu.SELECTABLE_TIER2, _w("marksman"), "3006") == "3006"


def test_marksman_high_ap_cc_flips_to_mercurys():
    w = _w("marksman", enemy_ad_share=0.2, enemy_ap_share=0.8, cc_proxy=0.9)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, "3006") == "3111"


def test_tank_vs_ad_keeps_steelcaps():
    # Defensive archetype vs an AD comp -> armor boots (Steelcaps 3047).
    w = _w("tank", enemy_ad_share=0.7, enemy_ap_share=0.3, cc_proxy=0.3)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, "3047") == "3047"


def test_tank_vs_ap_flips_to_mercurys():
    # Defensive archetype vs an AP comp -> MR + tenacity (Mercury's 3111),
    # NOT armor. This is the calibration the preview diff corrected.
    w = _w("tank", enemy_ad_share=0.3, enemy_ap_share=0.7, cc_proxy=0.7)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, "3047") == "3111"


def test_hysteresis_marginal_signal_holds_default():
    # A weak AD lean must NOT dislodge the archetype default (below switch margin).
    w = _w("marksman", enemy_ad_share=0.55, enemy_ap_share=0.45, cc_proxy=0.0)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, "3006") == "3006"


def test_failsoft_unknown_boot_scores_zero_and_empty_pool_returns_default():
    assert bu.score_boot("999999", _w("carry")) == 0.0
    assert bu.select_boot((), _w("carry"), "3006") == "3006"
