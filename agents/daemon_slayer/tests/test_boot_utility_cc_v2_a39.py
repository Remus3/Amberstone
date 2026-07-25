"""A-39: real per-champion enemy CC replaces the v1 AP-share cc_proxy.

The v1 boot-utility ON path fed its tenacity axis from ``enemy_ap_share``
(``core/build_order.py`` ``_select_boots_utility``), which structurally
under-credits an AD-dominant hard-CC frontline. v2 reads
``boot_utility.comp_cc_signal`` -> ``cc_output.compute_cc_output`` per enemy
champion instead. The new input is DEFAULT-OFF: ``enemy_champions=None`` (every
pre-A-39 caller) keeps the v1 proxy verbatim.

Measured at ENGINE 1.246.0 over the 161-champion cc_output registry:
median total_lockdown_score 1.400, p90 2.790, max 7.125.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer import boot_utility as bu
from core.build_order import _select_boots, _select_boots_utility

# Comp-mean total_lockdown_score 3.650 -> saturates the axis (signal 1.0).
HEAVY_CC_COMP = ("Nautilus", "Amumu", "Leona", "Sejuani", "Malphite")
# Comp-mean total_lockdown_score 0.130 -> signal 0.043.
NO_CC_COMP = ("Kaisa", "Vayne", "Talon", "Zed", "Naafiri")

# A deliberately BALANCED damage split so the AP share alone cannot explain any
# flip: v1 would read cc_proxy = 0.5 for BOTH comps above.
BALANCED = dict(enemy_ad_share=0.5, enemy_ap_share=0.5)

# A COHERENT comp that is genuinely AP-dominant AND genuinely low-CC. This is
# the case the v1 proxy gets structurally wrong in the OTHER direction: it reads
# cc_proxy = 0.80 off the AP share when the real signal is 0.073.
AP_HEAVY_LOW_CC_COMP = ("Kassadin", "Akali", "Katarina", "Vladimir", "Kayle")
AP_HEAVY = dict(enemy_ad_share=0.2, enemy_ap_share=0.8)


# --- the signal itself -----------------------------------------------------

def test_comp_cc_signal_separates_lockdown_from_no_cc():
    heavy = bu.comp_cc_signal(HEAVY_CC_COMP)
    none_cc = bu.comp_cc_signal(NO_CC_COMP)
    assert heavy == pytest.approx(1.0)
    assert none_cc == pytest.approx(0.130 / 3.0, abs=1e-3)
    # The whole point: the two comps are separated by the CC axis, and the
    # separation is large - not a rounding-scale difference.
    assert heavy - none_cc > 0.9


def test_comp_cc_signal_is_clamped_to_unit_interval():
    # Mordekaiser alone scores 7.125, well past the 3.0 reference.
    assert bu.comp_cc_signal(("Mordekaiser",)) == pytest.approx(1.0)
    assert 0.0 <= bu.comp_cc_signal(("Jinx", "Caitlyn")) <= 1.0


def test_comp_cc_signal_returns_none_not_zero_when_unavailable():
    # None (not 0.0) is what lets the caller fall back to the v1 proxy.
    assert bu.comp_cc_signal(None) is None
    assert bu.comp_cc_signal(()) is None
    assert bu.comp_cc_signal(("", "   ")) is None
    assert bu.comp_cc_signal(HEAVY_CC_COMP, lockdown_ref=0.0) is None


def test_comp_cc_signal_unregistered_champion_contributes_zero_not_raise():
    # Fail-soft direction is UNDER-crediting, never an exception.
    assert bu.comp_cc_signal(("NotAChampion",)) == pytest.approx(0.0)


# --- OFF parity: the new kwarg must be inert -------------------------------

def test_new_kwarg_is_byte_identical_on_the_off_path():
    for comp in (None, HEAVY_CC_COMP, NO_CC_COMP):
        for arch, armor, mr, expected in (
            ("marksman", 0.0, 70.0, "3006"),
            ("bruiser", 0.0, 70.0, "3111"),
            ("tank", 120.0, 0.0, "3047"),
            ("mage", 120.0, 0.0, "3020"),
        ):
            iid, _ = _select_boots(
                arch, armor, mr, mode="SR", **BALANCED,
                assume_boot_utility=False, enemy_champions=comp,
            )
            assert iid == expected, (arch, comp, iid)


def test_on_path_with_none_roster_reproduces_v1_exactly():
    # Every pre-A-39 caller passes nothing; the v1 AP-share proxy must survive.
    for arch, default in (("marksman", "3006"), ("tank", "3047"),
                          ("bruiser", "3047"), ("mage", "3020")):
        v1 = _select_boots_utility(arch, 0.5, 0.5)
        explicit_none = _select_boots_utility(arch, 0.5, 0.5, enemy_champions=None)
        assert v1 == explicit_none, arch
        assert v1 == default, (arch, v1)


# --- the behaviour delta: heavy CC flips, no-CC control does not -----------

def test_heavy_cc_comp_flips_tank_to_mercurys_and_control_does_not():
    heavy, _ = _select_boots(
        "tank", 0.0, 0.0, mode="SR", **BALANCED,
        assume_boot_utility=True, enemy_champions=HEAVY_CC_COMP,
    )
    control, _ = _select_boots(
        "tank", 0.0, 0.0, mode="SR", **BALANCED,
        assume_boot_utility=True, enemy_champions=NO_CC_COMP,
    )
    v1, _ = _select_boots(
        "tank", 0.0, 0.0, mode="SR", **BALANCED,
        assume_boot_utility=True, enemy_champions=None,
    )
    # Steelcaps (3047) is the tank default and holds under v1 and vs no CC;
    # only the real lockdown comp buys Mercury's tenacity.
    assert v1 == "3047"
    assert control == "3047"
    assert heavy == "3111"


def test_bruiser_shows_the_same_delta():
    heavy, _ = _select_boots(
        "bruiser", 0.0, 0.0, mode="SR", **BALANCED,
        assume_boot_utility=True, enemy_champions=HEAVY_CC_COMP,
    )
    control, _ = _select_boots(
        "bruiser", 0.0, 0.0, mode="SR", **BALANCED,
        assume_boot_utility=True, enemy_champions=NO_CC_COMP,
    )
    assert (control, heavy) == ("3047", "3111")


def test_v2_removes_the_false_flip_the_ap_proxy_manufactured():
    """The proxy is wrong in BOTH directions, and this is the more valuable half.

    Facing a coherent AP-dominant but CC-less comp, v1 infers cc_proxy = 0.80
    purely from the AP share and hands a marksman Mercury's tenacity it cannot
    use. v2 reads the real signal (0.073) and keeps Berserker's. The tank in the
    same matchup still takes Mercury's - correctly, because its MR value is real
    and independent of CC - which proves v2 removed a tenacity artifact rather
    than just globally suppressing Mercury's.
    """
    assert bu.comp_cc_signal(AP_HEAVY_LOW_CC_COMP) == pytest.approx(0.0733, abs=1e-3)

    mk_v1, _ = _select_boots("marksman", 0.0, 0.0, mode="SR", **AP_HEAVY,
                             assume_boot_utility=True, enemy_champions=None)
    mk_v2, _ = _select_boots("marksman", 0.0, 0.0, mode="SR", **AP_HEAVY,
                             assume_boot_utility=True,
                             enemy_champions=AP_HEAVY_LOW_CC_COMP)
    tk_v2, _ = _select_boots("tank", 0.0, 0.0, mode="SR", **AP_HEAVY,
                             assume_boot_utility=True,
                             enemy_champions=AP_HEAVY_LOW_CC_COMP)
    assert mk_v1 == "3111"
    assert mk_v2 == "3006"
    assert tk_v2 == "3111"


def test_arena_mirror_still_applied_to_the_v2_pick():
    iid, _ = _select_boots(
        "tank", 0.0, 0.0, mode="CHERRY", **BALANCED,
        assume_boot_utility=True, enemy_champions=HEAVY_CC_COMP,
    )
    assert iid == "223111"


# --- kwargs spy: the delta provably comes from the NEW path ----------------

def test_spy_proves_cc_proxy_is_the_only_changed_input(monkeypatch):
    seen: list[tuple] = []
    real = bu.comp_weights

    def spy(archetype, enemy_ad_share, enemy_ap_share, cc_proxy):
        seen.append((archetype, enemy_ad_share, enemy_ap_share, cc_proxy))
        return real(archetype, enemy_ad_share, enemy_ap_share, cc_proxy)

    monkeypatch.setattr(bu, "comp_weights", spy)

    _select_boots_utility("tank", 0.5, 0.5, enemy_champions=None)
    _select_boots_utility("tank", 0.5, 0.5, enemy_champions=HEAVY_CC_COMP)
    _select_boots_utility("tank", 0.5, 0.5, enemy_champions=NO_CC_COMP)

    assert len(seen) == 3
    v1, heavy, control = seen
    # Archetype + both damage shares are IDENTICAL across all three calls, so
    # cc_proxy is the sole degree of freedom that moved.
    assert v1[:3] == heavy[:3] == control[:3] == ("tank", 0.5, 0.5)
    assert v1[3] == pytest.approx(0.5)          # v1 == enemy_ap_share
    assert heavy[3] == pytest.approx(1.0)       # real lockdown, saturated
    assert control[3] == pytest.approx(0.130 / 3.0, abs=1e-3)
    # And the v1 value is NOT reachable from either real comp - the proxy was
    # not merely coincident with the truth.
    assert heavy[3] != pytest.approx(v1[3])
    assert control[3] != pytest.approx(v1[3])


# --- mutation checks: the pins above are not vacuous ----------------------

def test_mutation_zeroing_cc_output_collapses_the_flip(monkeypatch):
    """If compute_cc_output stops reporting real lockdown, the flip must die.

    Proves test_heavy_cc_comp_flips_tank_to_mercurys_and_control_does_not is
    reading the cc_output registry and not some incidental constant.
    """
    from agents.daemon_slayer import cc_output

    def zeroed(champion, mode="SR"):
        return cc_output._empty_result(champion, mode)

    monkeypatch.setattr(cc_output, "compute_cc_output", zeroed)
    iid, _ = _select_boots(
        "tank", 0.0, 0.0, mode="SR", **BALANCED,
        assume_boot_utility=True, enemy_champions=HEAVY_CC_COMP,
    )
    assert iid == "3047", "flip survived a zeroed CC registry - pin is vacuous"


def test_mutation_raising_lockdown_ref_collapses_the_flip(monkeypatch):
    """Saturating requires the calibrated 3.0 reference, not any reference."""
    monkeypatch.setattr(bu, "_CC_LOCKDOWN_REF", 100.0)
    assert bu.comp_cc_signal(HEAVY_CC_COMP) == pytest.approx(3.650 / 100.0, abs=1e-3)


def test_mutation_forcing_the_signal_high_flips_the_no_cc_control(monkeypatch):
    """The control holds because its CC is genuinely low, not because the
    control comp is inert to the new path."""
    monkeypatch.setattr(bu, "comp_cc_signal", lambda *_a, **_k: 1.0)
    iid, _ = _select_boots(
        "tank", 0.0, 0.0, mode="SR", **BALANCED,
        assume_boot_utility=True, enemy_champions=NO_CC_COMP,
    )
    assert iid == "3111", "control is inert to cc_proxy - pin is vacuous"
