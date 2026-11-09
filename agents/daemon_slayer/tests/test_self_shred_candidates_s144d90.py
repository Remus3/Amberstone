"""S144-D-90 - pin ``self_shred``'s block extraction and candidate collection.

``_extract_shred`` reads a modifier block's ``raw_modifiers``,
``_shred_at_rank`` picks the per-rank magnitude and ``_candidate_shreds``
walks a champion's ability map into ``(key, flat, pct, resist_kind)`` rows.
``test_self_shred.py`` only reaches them through real champions, so the skip
rules (non-modifier block, non-shred modifier, PvE shred, AD reduction, no
magnitude, zero or negative magnitude), the percent-to-fraction conversion,
the rank clamp and the non-tuple form wrap had no direct test.

``_extract_shred`` returns a 2-tuple ``(values, is_percent)``; its docstring
used to promise ``(flat_shred, pct_shred, label_suffix)``, fixed in the same
slice. Blocks and forms are synthetic ``SimpleNamespace`` stand-ins carrying
only the attributes the code reads (``attribute_kind``, ``attribute``,
``raw_modifiers``, ``damage_blocks``, ``damage_type``).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.daemon_slayer.self_shred import (
    RESIST_ARMOR,
    RESIST_MR,
    _candidate_shreds,
    _extract_shred,
    _shred_at_rank,
)


def _block(attribute="Armor Reduction", values=(10, 20, 30, 40, 50),
           units=("",), kind="modifier", raw=None):
    if raw is None:
        raw = ({"values": list(values), "units": list(units)},)
    return SimpleNamespace(attribute=attribute, attribute_kind=kind,
                           raw_modifiers=raw)


def _form(*blocks, damage_type="PHYSICAL"):
    return SimpleNamespace(damage_blocks=tuple(blocks), damage_type=damage_type)


# ---- _extract_shred ------------------------------------------------------

def test_extract_returns_values_and_percent_flag():
    assert _extract_shred(_block(values=(1, 2), units=("%",))) == ([1, 2], True)
    assert _extract_shred(_block(values=(1, 2), units=("",))) == ([1, 2], False)


def test_extract_missing_units_reads_as_flat():
    raw = ({"values": [5]},)
    assert _extract_shred(_block(raw=raw)) == ([5], False)


def test_extract_accepts_a_bare_dict_raw_modifiers():
    raw = {"values": [7, 8], "units": ["%"]}
    assert _extract_shred(_block(raw=raw)) == ([7, 8], True)


@pytest.mark.parametrize(
    "raw",
    [(), [], None, ("not a dict",), ({"values": []},), ({"units": ["%"]},)],
)
def test_extract_without_a_usable_magnitude_is_none(raw):
    assert _extract_shred(SimpleNamespace(raw_modifiers=raw)) is None


def test_extract_block_without_the_attribute_is_none():
    assert _extract_shred(SimpleNamespace()) is None


def test_extract_docstring_and_annotation_name_the_real_return_shape():
    doc = _extract_shred.__doc__ or ""
    assert "(values, is_percent)" in doc
    assert "label_suffix" not in doc
    # Module uses postponed annotations, so the return hint is a string.
    assert _extract_shred.__annotations__["return"] == "Optional[tuple[list, bool]]"


# ---- _shred_at_rank ------------------------------------------------------

def test_rank_reads_the_indexed_value():
    assert _shred_at_rank([10, 20, 30], 1) == 20.0


def test_rank_clamps_to_both_ends():
    assert _shred_at_rank([10, 20, 30], -3) == 10.0
    assert _shred_at_rank([10, 20, 30], 9) == 30.0


def test_rank_coerces_numeric_strings_and_zeroes_garbage():
    assert _shred_at_rank(["12.5"], 0) == 12.5
    assert _shred_at_rank(["n/a"], 0) == 0.0
    assert _shred_at_rank([None], 0) == 0.0


@pytest.mark.parametrize("values", [[], None, ()])
def test_rank_on_no_values_is_zero(values):
    assert _shred_at_rank(values, 0) == 0.0


# ---- _candidate_shreds ---------------------------------------------------

def test_percent_magnitude_lands_in_the_pct_slot_as_a_fraction():
    forms = {"E": (_form(_block(values=(30, 35, 40, 45, 50), units=("%",))),)}
    assert _candidate_shreds(forms, None, 4) == [("E", 0.0, 0.5, RESIST_ARMOR)]


def test_flat_magnitude_lands_in_the_flat_slot():
    forms = {"E": (_form(_block(values=(12, 14, 16, 18, 20), units=("",))),)}
    assert _candidate_shreds(forms, None, 0) == [("E", 12.0, 0.0, RESIST_ARMOR)]


def test_resist_kind_follows_the_form_damage_type():
    blk = _block(attribute="Resistances Reduction", values=(10,), units=("",))
    magic = {"Q": (_form(blk, damage_type="MAGIC"),)}
    phys = {"Q": (_form(blk, damage_type="PHYSICAL"),)}
    assert _candidate_shreds(magic, None, 0)[0][3] == RESIST_MR
    assert _candidate_shreds(phys, None, 0)[0][3] == RESIST_ARMOR


@pytest.mark.parametrize(
    "block",
    [
        _block(kind="damage"),                         # not a modifier block
        _block(attribute="Damage Reduction"),          # defensive_self
        _block(attribute="Monster Armor Reduction"),   # pve_only
        _block(attribute="Attack Damage Reduction"),   # no resist channel
        _block(values=(0, 0, 0)),                      # zero magnitude
        _block(values=(-5,)),                          # negative magnitude
        _block(raw=()),                                # no magnitude at all
    ],
)
def test_blocks_that_are_not_a_modelled_shred_are_skipped(block):
    assert _candidate_shreds({"Q": (_form(block),)}, None, 0) == []


def test_a_bare_form_is_wrapped_and_keys_are_stringified():
    forms = {1: _form(_block(values=(8,)))}
    assert _candidate_shreds(forms, None, 0) == [("1", 8.0, 0.0, RESIST_ARMOR)]


def test_every_qualifying_block_on_every_form_is_collected_in_order():
    forms = {
        "Q": (
            _form(_block(kind="damage"), _block(values=(4,))),
            _form(_block(attribute="Magic Resistance Reduction",
                         values=(20,), units=("%",)), damage_type="MAGIC"),
        ),
        "R": (_form(_block(values=(1, 2, 3))),),
    }
    assert _candidate_shreds(forms, None, 4) == [
        ("Q", 4.0, 0.0, RESIST_ARMOR),
        ("Q", 0.0, 0.2, RESIST_MR),
        ("R", 3.0, 0.0, RESIST_ARMOR),
    ]


def test_form_without_blocks_contributes_nothing():
    forms = {"W": (SimpleNamespace(damage_type="MAGIC"),)}
    assert _candidate_shreds(forms, None, 0) == []
