"""RM-1379 + RM-1378: lcu/lcu_rune_writer.py against DDragon runesReforged.

RM-1379: `_KEYSTONES` lagged DDragon 16.22.1 - Deathfire Touch (8992,
Sorcery) was missing and 8230 is "Stormraider's Surge", not "Phase Rush",
so a build naming either DDragon name never resolved. The drift test holds
EVERY slot-0 rune of the tracked data/meta/ddragon_runes.json to a
`_KEYSTONES` entry by its DDragon name, and every `_KEYSTONES` id (alias
names included) to a real slot-0 rune of the right tree.

RM-1378: `build_perk_ids` had no legality check, so a keystone outside its
primary tree (or a minor rune from the wrong tree) produced a page League
rejects - after `_write_page` had already deleted the RC pages.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lcu import lcu_rune_writer as w

_RUNES = Path(__file__).resolve().parent.parent / "data" / "meta" / "ddragon_runes.json"


def _doc():
    return json.loads(_RUNES.read_text(encoding="utf-8"))


def _keystone_rows():
    for tree in _doc():
        for rune in tree["slots"][0]["runes"]:
            yield tree["key"], rune["id"], rune["name"]


# -- RM-1379: keystone table drift -----------------------------------------

def test_every_ddragon_keystone_resolves_by_its_ddragon_name():
    missing = [(tree, rid, name) for tree, rid, name in _keystone_rows()
               if w._KEYSTONES.get(name) != rid]
    assert not missing, missing


def test_every_keystone_id_is_a_real_slot0_rune():
    real = {rid for _t, rid, _n in _keystone_rows()}
    stale = {name: rid for name, rid in w._KEYSTONES.items() if rid not in real}
    assert not stale, stale


def test_every_keystone_name_is_ddragon_or_a_declared_alias():
    ddragon_names = {name for _t, _rid, name in _keystone_rows()}
    undeclared = [n for n in w._KEYSTONES
                  if n not in ddragon_names and n not in w._KEYSTONE_ALIASES]
    assert not undeclared, undeclared
    # An alias must point at the same id as its DDragon name.
    for alias, canon in w._KEYSTONE_ALIASES.items():
        assert w._KEYSTONES[alias] == w._KEYSTONES[canon], alias


@pytest.mark.parametrize("keystone,expected", [
    ("Deathfire Touch", 8992),
    ("Stormraider's Surge", 8230),
    ("Phase Rush", 8230),   # legacy name, still used by champion_loadouts.json
])
def test_new_and_legacy_sorcery_keystones_build_a_page(keystone, expected):
    ids = w.build_perk_ids(keystone, "Sorcery", "Precision")
    assert ids is not None
    assert ids[0] == expected


def test_tree_ids_match_ddragon():
    assert {t["key"]: t["id"] for t in _doc()} == w._TREES


def test_default_minor_rows_are_legal_for_their_tree():
    table = {r["id"]: (t["key"], i) for t in _doc()
             for i, s in enumerate(t["slots"]) for r in s["runes"]}
    for tree, by_ks in w._PRIMARY_ROWS.items():
        for ks, rows in by_ks.items():
            assert [table[x] for x in rows] == [(tree, 1), (tree, 2), (tree, 3)], (tree, ks)
    for tree, picks in w._SECONDARY_PICKS.items():
        slots = [table[x] for x in picks]
        assert all(t == tree and i in (1, 2, 3) for t, i in slots), tree
        assert slots[0][1] != slots[1][1], tree


# -- RM-1378: legality ------------------------------------------------------

def test_keystone_outside_primary_tree_is_refused():
    assert w.build_perk_ids("Conqueror", "Sorcery", "Precision") is None
    assert w.build_perk_ids("Electrocute", "Precision", "Domination") is None


def test_legal_page_unchanged():
    ids = w.build_perk_ids("Conqueror", "Precision", "Resolve")
    assert ids == [8010, 9111, 9104, 8014, 8473, 8453, 5005, 5008, 5001]


@pytest.mark.parametrize("minor_primary", [
    ["Manaflow Band", "Legend: Haste", "Cut Down"],   # wrong tree
    ["Triumph", "Absorb Life", "Cut Down"],           # two from one slot
    ["Lethal Tempo", "Legend: Haste", "Cut Down"],    # a keystone
])
def test_illegal_resolved_primary_minors_are_refused(minor_primary):
    # Resolved-but-illegal is refused (same verdict as coaches/rune_pages),
    # never silently swapped for default minors the operator did not pick.
    assert w.build_perk_ids("Conqueror", "Precision", "Resolve",
                            minor_primary=minor_primary) is None


@pytest.mark.parametrize("minor_secondary", [
    ["Bone Plating", "Manaflow Band"],   # wrong tree
    ["Bone Plating", "Second Wind"],     # one slot twice
    ["Aftershock", "Revitalize"],        # a keystone
    ["Triumph", "Cut Down"],             # the primary tree
])
def test_illegal_resolved_secondary_minors_are_refused(minor_secondary):
    assert w.build_perk_ids("Conqueror", "Precision", "Resolve",
                            minor_secondary=minor_secondary) is None


def test_unresolved_minor_names_still_keep_defaults():
    ids = w.build_perk_ids("Conqueror", "Precision", "Resolve",
                           minor_primary=["Nope", "Legend: Haste", "Cut Down"])
    assert ids[1:4] == [9111, 9104, 8014]


def test_legal_minor_overrides_still_apply():
    ids = w.build_perk_ids("Lethal Tempo", "Precision", "Domination",
                           minor_primary=["Absorb Life", "Legend: Haste", "Cut Down"],
                           minor_secondary=["Taste of Blood", "Ultimate Hunter"])
    assert ids[:6] == [8008, 9101, 9105, 8017, 8139, 8106]


def test_unreadable_slot_table_keeps_prior_behaviour(monkeypatch, tmp_path):
    # Fail-soft: with no readable rune file the writer cannot judge
    # legality, so it behaves exactly as before (no new refusals).
    monkeypatch.setattr(w, "_APP_DIR", tmp_path)
    monkeypatch.setattr(w, "_SLOT_TABLE", None)
    monkeypatch.setattr(w, "_PERK_BY_NAME", None)
    ids = w.build_perk_ids("Conqueror", "Sorcery", "Precision")
    assert ids is not None and ids[0] == 8010
