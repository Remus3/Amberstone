"""S144-D-89 - pin the two pure classifiers of ``self_shred``.

``_resist_kind_for`` routes a target_shred modifier block to the armor or MR
channel (or to nothing, for an AD reduction); ``_is_percent`` decides whether
the block's magnitude is a percent of the target's resist or flat points.
``test_self_shred.py`` only reaches them through real champions (Nasus E,
Corki E, Evelynn W, Trundle Q), so the routing precedence, the generic
"Resistances" fallback by damage type, the blank / None inputs and the
first-unit-only read had no direct test.

The attribute strings below are the target_shred names present in the shipped
abilities snapshot when this file was written (Armor Reduction, Magic
Resistance Reduction, Enhanced Magic Resistance Reduction, Total MR Reduction,
Total Enhanced MR Reduction, Resistances Reduction, Resistances Reduction Per
Stack, Total Resistances Reduction, Attack Damage Reduction) plus a few
synthetic edge strings.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.self_shred import (
    RESIST_ARMOR,
    RESIST_MR,
    _is_percent,
    _resist_kind_for,
)


@pytest.mark.parametrize(
    "attribute",
    [
        "Magic Resistance Reduction",
        "Enhanced Magic Resistance Reduction",
        "Total MR Reduction",
        "Total Enhanced MR Reduction",
        "MR Reduction",
        "MAGIC RESISTANCE REDUCTION",
    ],
)
@pytest.mark.parametrize("damage_type", ["MAGIC", "PHYSICAL", None])
def test_mr_names_route_to_mr_whatever_the_damage_type(attribute, damage_type):
    assert _resist_kind_for(attribute, damage_type) == RESIST_MR


@pytest.mark.parametrize("attribute", ["Armor Reduction", "armor reduction"])
@pytest.mark.parametrize("damage_type", ["MAGIC", "PHYSICAL", None])
def test_armor_names_route_to_armor_whatever_the_damage_type(attribute, damage_type):
    # Real data carries Armor Reduction on MAGIC-typed spells too; the name
    # wins over the spell type.
    assert _resist_kind_for(attribute, damage_type) == RESIST_ARMOR


@pytest.mark.parametrize(
    "attribute",
    [
        "Resistances Reduction",
        "Resistances Reduction Per Stack",
        "Total Resistances Reduction",
        "Resistance Reduction",
    ],
)
def test_generic_resistance_routes_by_damage_type(attribute):
    assert _resist_kind_for(attribute, "MAGIC") == RESIST_MR
    # Damage type is case-folded before the compare.
    assert _resist_kind_for(attribute, "magic") == RESIST_MR
    for other in ("PHYSICAL", "MIXED", "TRUE", None, ""):
        assert _resist_kind_for(attribute, other) == RESIST_ARMOR


@pytest.mark.parametrize("damage_type", ["MAGIC", "PHYSICAL", None])
def test_attack_damage_reduction_has_no_resist_channel(damage_type):
    assert _resist_kind_for("Attack Damage Reduction", damage_type) is None


def test_attack_damage_check_runs_before_the_resist_checks():
    # An attribute naming both is still an outgoing-AD shred: no channel.
    assert _resist_kind_for("Armor and Attack Damage Reduction", "PHYSICAL") is None
    assert _resist_kind_for("Attack Damage and Resistances Reduction", "MAGIC") is None


def test_mr_check_runs_before_the_generic_resistance_fallback():
    # "Magic Resistance Reduction" contains "resistance"; on a PHYSICAL spell
    # the generic branch would say armor, the MR branch must win first.
    assert _resist_kind_for("Magic Resistance Reduction", "PHYSICAL") == RESIST_MR


@pytest.mark.parametrize("attribute", [None, "", "Slow", "Damage Reduction"])
def test_unrelated_or_blank_attribute_has_no_channel(attribute):
    assert _resist_kind_for(attribute, "MAGIC") is None


@pytest.mark.parametrize(
    "units",
    [["%"], ["% of target's armor"], ("%",), "%", "% of target's armor"],
)
def test_percent_units(units):
    assert _is_percent(units) is True


@pytest.mark.parametrize("units", [None, [], (), "", [""], [None], ["flat"]])
def test_flat_or_empty_units(units):
    assert _is_percent(units) is False


def test_only_the_first_unit_is_read():
    assert _is_percent(["", "%"]) is False
    assert _is_percent(["%", ""]) is True
