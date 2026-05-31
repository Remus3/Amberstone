"""item 238 (2026-05-31) - null-damage-type ability correction registry.

Validates the score-time overrides applied at ``AbilitiesSnapshot.load``:
1. mis-mitigated null-type abilities get the correct ``damage_type``;
2. phantom self-buff / shield blocks are re-labeled out of the damage sum;
3. genuinely-magic null-type abilities are left untouched (MAGIC default).
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
    _apply_ability_overrides,
)
from agents.daemon_slayer._ability_overrides import (
    DAMAGE_TYPE_OVERRIDES,
    NON_DAMAGE_BLOCKS,
)
from agents.daemon_slayer.ability_dps import _mitigation_factor


@pytest.fixture(scope="module")
def snap() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load()  # current patch (16.11.1)


# --- damage_type overrides (mitigation correctness) -------------------------

@pytest.mark.parametrize("champ,key,fi,expect", [
    ("Camille", "Q", 0, "PHYSICAL"),
    ("Sett", "W", 0, "PHYSICAL"),
    ("Smolder", "Q", 0, "PHYSICAL"),
    ("Udyr", "Q", 0, "PHYSICAL"),
    ("Urgot", "R", 0, "PHYSICAL"),
    ("Yone", "W", 0, "MIXED"),
    ("Yone", "R", 0, "MIXED"),
])
def test_damage_type_override_applied(snap, champ, key, fi, expect):
    assert snap.get_ability(champ, key, fi).damage_type == expect


def test_physical_override_is_armor_sensitive(snap):
    form = snap.get_ability("Smolder", "Q", 0)
    hi_armor = _mitigation_factor(form.damage_type, 100.0, 0.0)
    hi_mr = _mitigation_factor(form.damage_type, 0.0, 100.0)
    assert hi_armor < 1.0                       # armor reduces physical
    assert hi_mr == pytest.approx(1.0)          # MR does not touch physical


def test_mixed_override_splits_armor_and_mr(snap):
    form = snap.get_ability("Yone", "W", 0)
    only_armor = _mitigation_factor(form.damage_type, 100.0, 0.0)
    only_mr = _mitigation_factor(form.damage_type, 0.0, 100.0)
    assert only_armor < 1.0 and only_mr < 1.0   # both resists bite a MIXED block


# --- phantom block exclusion (no fake damage) ------------------------------

@pytest.mark.parametrize("champ,key,fi,attr", [
    ("Aatrox", "R", 0, "Bonus Attack Damage"),
    ("Aphelios", "P", 0, "Bonus Attack Damage"),
    ("Janna", "E", 0, "Bonus Attack Damage"),
    ("Olaf", "R", 0, "Bonus Attack Damage"),
    ("Sona", "W", 0, "Minimum Damage Mitigated"),
    ("Tryndamere", "Q", 0, "Bonus Attack Damage"),
    ("Vayne", "R", 0, "Bonus Attack Damage"),
])
def test_phantom_block_relabelled(snap, champ, key, fi, attr):
    form = snap.get_ability(champ, key, fi)
    matches = [b for b in form.damage_blocks if b.attribute == attr]
    assert matches, f"{champ} {key}.{fi} block {attr!r} not present"
    for b in matches:
        assert b.attribute_kind == "other", (
            f"{champ} {key}.{fi} {attr!r} still attribute_kind={b.attribute_kind!r}"
        )


@pytest.mark.parametrize("champ,key,fi", [
    ("Aatrox", "R", 0), ("Olaf", "R", 0), ("Vayne", "R", 0),
    ("Tryndamere", "Q", 0), ("Janna", "E", 0), ("Aphelios", "P", 0),
    ("Sona", "W", 0),
])
def test_phantom_form_has_no_real_damage_blocks(snap, champ, key, fi):
    # The flagged buff/shield block was the ONLY damage-kind block on these
    # forms; after the override they expose zero real damage blocks.
    assert snap.get_ability(champ, key, fi).damage_blocks_only() == ()


# --- regression: genuinely-magic null-type abilities untouched -------------

@pytest.mark.parametrize("champ,key,fi", [
    ("Skarner", "W", 0), ("Zeri", "E", 0), ("Zeri", "R", 0),
    ("Nunu", "Q", 0), ("Yunara", "Q", 0),
])
def test_untouched_null_type_stays_none_and_keeps_damage(snap, champ, key, fi):
    form = snap.get_ability(champ, key, fi)
    assert form.damage_type is None                 # still MAGIC by default
    assert form.damage_blocks_only(), "real damage blocks must remain"


# --- helper / registry hygiene ---------------------------------------------

def test_apply_overrides_is_noop_for_unregistered():
    blk = DamageBlock(attribute="X", attribute_kind="damage", base=(10.0,))
    form = AbilityForm(
        key="Q", name="x", form_index=0, icon=None, cooldown=None, cost=None,
        damage_type=None, targeting=None, affects=None, resource=None,
        is_aoe=False, damage_blocks=(blk,), raw_effects_count=0,
        raw_leveling_count=0, parse_status="ok", parse_notes=(),
    )
    assert _apply_ability_overrides("Nobody", "Q", form) is form


def test_registries_well_formed():
    for k, v in DAMAGE_TYPE_OVERRIDES.items():
        assert isinstance(k, tuple) and len(k) == 3
        assert v in {"PHYSICAL", "MAGIC", "TRUE", "MIXED"}
    for k, v in NON_DAMAGE_BLOCKS.items():
        assert isinstance(k, tuple) and len(k) == 3
        assert isinstance(v, frozenset) and v


def test_overrides_module_is_ascii():
    import agents.daemon_slayer._ability_overrides as m
    src = open(m.__file__, encoding="utf-8").read()
    assert all(ord(c) < 128 for c in src)
