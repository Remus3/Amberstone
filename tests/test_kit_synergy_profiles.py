"""WP-C1 characterization tests for core.build_planner.kit_synergy (TDD RED).

This module does NOT exist yet - WP-C1 creates core/build_planner/__init__.py
plus core/build_planner/kit_synergy.py. These tests are written FIRST and must
fail at import time (ModuleNotFoundError) until the implementer lands the module.

Tier-1 scope: this module's own tests only - no DS suite, no restart.

All assertions are ordinal / bounded (inequalities, ordering of synergy_score
across items for a champ) rather than fragile exact floats, per the operator's
"prefer assertions on computed quantities" rule. Item / champ ids are real and
were re-verified against data/daemon_slayer/16.13.1/items.json and
champions.json this run. ASCII only - use " - " for clause breaks.

Cited ids (16.13.1):
  3031 Infinity Edge   {FlatCritChanceMod 0.25, FlatPhysicalDamageMod 75}
  6672 Kraken Slayer   {FlatPhysicalDamageMod 45, PercentAttackSpeedMod 0.4, OnHit tag}
  3153 BoRK            {AD 40, AS 0.25, PercentLifeStealMod 0.1, OnHit tag}
  3089 Rabadon's       {FlatMagicDamageMod 130} - pure AP
  6655 Luden's Echo    {FlatMagicDamageMod 100, AbilityHaste tag}
  3078 Trinity Force   {HP 333, AD 36, AS 0.3, OnHit + AbilityHaste tags, Spellblade}
  3084 Heartsteel      {FlatHPPoolMod 900} - pure HP
"""
from __future__ import annotations

import pytest

# The import itself is the RED proof for the un-built module. Keep it at module
# scope so collection of this whole file fails until kit_synergy exists.
from core.build_planner.kit_synergy import (  # noqa: E402
    AXES,
    anti_synergy_penalty,
    effect_synergy,
    item_vector,
    kit_weights,
    synergy_score,
)

# Real, re-verified item ids.
IE = "3031"           # Infinity Edge - crit + AD
KRAKEN = "6672"       # Kraken Slayer - AD + AS + on-hit
BORK = "3153"         # Blade of the Ruined King - AD + AS + lifesteal + on-hit + %maxHP family
RABADON = "3089"      # Rabadon's Deathcap - pure AP
LUDEN = "6655"        # Luden's Echo - AP + AH
TRINITY = "3078"      # Trinity Force - spellblade + on-hit + AH
HEARTSTEEL = "3084"   # Heartsteel - pure HP

MF = "Miss Fortune"
YASUO = "Yasuo"
YONE = "Yone"
KOG = "Kog'Maw"
ORNN = "Ornn"
SION = "Sion"


# --- 14. dense vector keys (run first as a structural sanity gate) ------------

def test_dense_vector_keys():
    """Both item_vector and kit_weights are dense over the canonical 10-axis
    set so dot() is well-defined."""
    assert set(item_vector(IE).keys()) == set(AXES)
    assert set(kit_weights(MF).keys()) == set(AXES)
    assert len(AXES) == 10


# --- 1. MF crit-marksman weights ---------------------------------------------

def test_mf_crit_marksman_weights():
    """Crit marksman weights AD / AS / crit high, AH ~0."""
    w = kit_weights(MF)
    assert w["AD"] >= 0.9
    assert w["AS"] >= 0.9
    assert w["crit"] >= 0.9
    assert w["AH"] <= 0.15


# --- 2. MF: Infinity Edge over Rabadon's -------------------------------------

def test_mf_ie_over_rabadon():
    """Infinity Edge (crit + AD, fits an AD carry) outranks Rabadon's (pure AP)
    for an AD marksman."""
    assert synergy_score(IE, MF) > synergy_score(RABADON, MF)


# --- 3. Yasuo double-crit gate -----------------------------------------------

def test_yasuo_double_crit():
    """Double-crit gate makes Yasuo value crit ~2x a non-double crit champ."""
    yasuo_crit = kit_weights(YASUO)["crit"]
    kog_crit = kit_weights(KOG)["crit"]
    assert kog_crit > 0  # guard against a divide-by-zero / null baseline
    assert yasuo_crit >= 1.9 * kog_crit


# --- 4. Yone ranks a crit item over an AP+AH item ----------------------------

def test_yone_crit_item_high():
    """Yone (double_crit) ranks Infinity Edge above Luden's Echo (AP + AH) -
    crit double-valued, AP off-axis."""
    assert synergy_score(IE, YONE) > synergy_score(LUDEN, YONE)


# --- 5. Kog'Maw AS-cap collapse ----------------------------------------------

def test_kog_as_cap_collapse():
    """AS-cap gate - Kraken's AS axis stops counting once current_as >= 2.5,
    lowering its synergy past the cap."""
    below = synergy_score(KRAKEN, KOG, current_as=0.8)
    above = synergy_score(KRAKEN, KOG, current_as=2.6)
    assert below > above


# --- 6. Kog over-values AS early ---------------------------------------------

def test_kog_overvalues_as_early():
    """Kog over-values AS (weight 1.8) versus a normal carry (1.0) until the
    cap engages."""
    kog_as = kit_weights(KOG, current_as=None)["AS"]
    mf_as = kit_weights(MF)["AS"]
    assert kog_as > mf_as


# --- 7. Ornn HP is offense ---------------------------------------------------

def test_ornn_hp_is_offense():
    """HP-scaling tank treats HP as offense - HP weight high vs a marksman whose
    HP weight is ~0."""
    ornn_hp = kit_weights(ORNN)["HP-scaling"]
    mf_hp = kit_weights(MF)["HP-scaling"]
    assert ornn_hp > mf_hp
    assert ornn_hp >= 1.0


# --- 8. Sion ranks HP over a crit item ---------------------------------------

def test_sion_hp_over_crit_item():
    """Sion (hp_offense) values Heartsteel (HP) over Infinity Edge (crit on a
    0-crit-scaling champ, anti-synergy penalized)."""
    assert synergy_score(HEARTSTEEL, SION) > synergy_score(IE, SION)


# --- 9. anti-synergy: crit on a 0-crit champ ---------------------------------

def test_anti_crit_on_zero_crit():
    """Pure-crit Infinity Edge on 0-crit-scaling Ornn incurs the crit-on-0-crit
    penalty - net synergy far below the marksman case."""
    assert anti_synergy_penalty(IE, ORNN) > 0
    assert synergy_score(IE, ORNN) < synergy_score(IE, MF)


# --- 10. anti-synergy: lifesteal on a no-auto context ------------------------

def test_anti_lifesteal_no_auto():
    """BoRK lifesteal is penalized when has_autos=False (ability-only context)
    versus an auto-attacker."""
    no_auto = synergy_score(BORK, KOG, has_autos=False)
    with_auto = synergy_score(BORK, KOG, has_autos=True)
    assert no_auto < with_auto


# --- 11. anti-synergy: AH overstack on a no-AH champ -------------------------

def test_anti_ah_overstack():
    """An AH item (Luden's) on MF (AH weight ~0.05) draws the no-AH-scaling
    penalty - Yasuo (AH weight ~0.2) is penalized less or not at all."""
    mf_pen = anti_synergy_penalty(LUDEN, MF)
    yasuo_pen = anti_synergy_penalty(LUDEN, YASUO)
    assert mf_pen > yasuo_pen


# --- 12. spellblade cadence: user vs pure-auto -------------------------------

def test_spellblade_cadence_user():
    """Trinity Force spellblade cadence bonus is full for a spellblade-user kit
    (Yasuo) and reduced for a pure-auto MF."""
    assert effect_synergy(TRINITY, YASUO) > effect_synergy(TRINITY, MF)


# --- 13. %maxHP-on-hit scales with attack speed ------------------------------

def test_maxhp_onhit_scales_with_as():
    """BoRK %maxHP-on-hit gate rewards high-AS Kog (on-hit %HP scales with AS)
    over a low-AS tank (Ornn)."""
    assert effect_synergy(BORK, KOG) > effect_synergy(BORK, ORNN)


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    raise SystemExit(pytest.main([__file__, "-q"]))
