"""Tests for the DS cross-patch snapshot diff.

All fixtures are synthetic and written to tmp_path. `tests/test_ds_fixture_policy.py`
forbids minting new permanent snapshot dirs under data/daemon_slayer, so nothing
here touches the real patch dirs.
"""

from __future__ import annotations

import json

import pytest

from tools import ds_patch_diff as dpd


def _write(root, patch, name, obj):
    d = root / patch
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj), encoding="utf-8")
    return d


def _items(gold_total, extra=None):
    data = {
        "1001": {
            "name": "Boots",
            "gold": {"base": 300, "total": gold_total, "sell": 210},
            "stats": {"FlatMovementSpeedMod": 25},
            "into": ["3005"],
            "tags": ["Boots"],
        }
    }
    if extra:
        data.update(extra)
    return {"version": "x", "data": data}


# -- items ---------------------------------------------------------------

def test_item_gold_change_is_reported():
    rep = dpd.diff_items(_items(300), _items(350))
    assert rep["added"] == [] and rep["removed"] == []
    (chg,) = rep["changed"]
    assert chg["id"] == "1001"
    assert chg["name"] == "Boots"
    assert chg["fields"]["gold.total"] == [300, 350]


def test_item_added_and_removed():
    new = _items(300, extra={"9999": {"name": "Test Blade", "gold": {"total": 1}}})
    rep = dpd.diff_items(_items(300), new)
    assert [a["id"] for a in rep["added"]] == ["9999"]
    assert rep["removed"] == []
    rep_back = dpd.diff_items(new, _items(300))
    assert [r["id"] for r in rep_back["removed"]] == ["9999"]


def test_item_stat_and_list_fields_tracked():
    old = _items(300)
    new = json.loads(json.dumps(old))
    new["data"]["1001"]["stats"]["FlatMovementSpeedMod"] = 30
    new["data"]["1001"]["into"] = ["3005", "3006"]
    rep = dpd.diff_items(old, new)
    fields = rep["changed"][0]["fields"]
    assert fields["stats.FlatMovementSpeedMod"] == [25, 30]
    assert fields["into"] == [["3005"], ["3005", "3006"]]


def test_min_pct_filters_small_numeric_moves():
    rep = dpd.diff_items(_items(300), _items(303), min_pct=5.0)
    assert rep["changed"] == []
    rep2 = dpd.diff_items(_items(300), _items(303), min_pct=0.5)
    assert rep2["changed"]


def test_min_pct_never_filters_non_numeric():
    old = _items(300)
    new = json.loads(json.dumps(old))
    new["data"]["1001"]["name"] = "Renamed"
    rep = dpd.diff_items(old, new, min_pct=99.0)
    assert rep["changed"][0]["fields"]["name"] == ["Boots", "Renamed"]


# -- champions -----------------------------------------------------------

def _champs(hp):
    return {
        "version": "x",
        "data": {
            "Aatrox": {
                "id": "Aatrox",
                "name": "Aatrox",
                "tags": ["Fighter"],
                "partype": "Blood Well",
                "stats": {"hp": hp, "armor": 38},
            }
        },
    }


def test_champion_stat_change():
    rep = dpd.diff_champions(_champs(650), _champs(670))
    assert rep["changed"][0]["fields"]["stats.hp"] == [650, 670]


def test_champion_roster_add_remove():
    new = _champs(650)
    new["data"]["Zzz"] = {"id": "Zzz", "name": "Zzz", "stats": {}}
    rep = dpd.diff_champions(_champs(650), new)
    assert [a["id"] for a in rep["added"]] == ["Zzz"]


# -- abilities (the nested-registry trap) --------------------------------

def _abilities(base_q, forms=1, cooldown=14.0):
    def form(i):
        return {
            "key": "Q",
            "name": f"Form {i}",
            "form_index": i,
            "cooldown": [cooldown],
            "cost": [0],
            "damage_type": "PHYSICAL",
            "damage_blocks": [
                {
                    "attribute": "First Cast Damage",
                    "attribute_kind": "damage",
                    "base": [base_q + i],
                    "total_ad_pct": [60.0],
                }
            ],
        }

    return {
        "version": "x",
        "count": 1,
        "coverage": {"total_forms": forms, "multiform_keys": 0},
        "data": {"Aatrox": {"Q": [form(i) for i in range(forms)]}},
    }


def test_ability_walks_forms_not_len():
    """171 champions but 927 forms - a flat count mis-parses."""
    rep = dpd.diff_abilities(_abilities(10.0, forms=3), _abilities(11.0, forms=3))
    assert len(rep["changed"]) == 3, "must report each form, not one per champion"
    keys = {c["form_index"] for c in rep["changed"]}
    assert keys == {0, 1, 2}


def test_ability_form_count_change_is_surfaced():
    rep = dpd.diff_abilities(_abilities(10.0, forms=1), _abilities(10.0, forms=2))
    assert rep["form_count"] == [1, 2]
    assert any(c.get("change") == "form_added" for c in rep["changed"])


def test_ability_ratio_and_cooldown_changes():
    old = _abilities(10.0, cooldown=14.0)
    new = _abilities(10.0, cooldown=12.0)
    rep = dpd.diff_abilities(old, new)
    assert rep["changed"][0]["fields"]["cooldown"] == [[14.0], [12.0]]

    new2 = json.loads(json.dumps(old))
    new2["data"]["Aatrox"]["Q"][0]["damage_blocks"][0]["total_ad_pct"] = [75.0]
    rep2 = dpd.diff_abilities(old, new2)
    fields = rep2["changed"][0]["fields"]
    assert fields["First Cast Damage.total_ad_pct"] == [[60.0], [75.0]]


def test_ability_unchanged_is_empty():
    assert dpd.diff_abilities(_abilities(10.0), _abilities(10.0))["changed"] == []


# -- builds --------------------------------------------------------------

def _builds(first="3006"):
    return {
        "mode": "sr",
        "version": "1",
        "build_orders": {"Aatrox": {"balanced": [first, "3078"], "ad_heavy": ["3078"]}},
    }


def test_build_order_change():
    rep = dpd.diff_builds(_builds(), _builds(first="3111"))
    (chg,) = rep["changed"]
    assert chg["champion"] == "Aatrox"
    assert chg["archetype"] == "balanced"
    assert chg["items"] == [["3006", "3078"], ["3111", "3078"]]


def test_build_unchanged_is_empty():
    assert dpd.diff_builds(_builds(), _builds())["changed"] == []


# -- end to end ----------------------------------------------------------

def test_diff_snapshots_reads_dirs_and_renders(tmp_path):
    _write(tmp_path, "1.0", "items.json", _items(300))
    _write(tmp_path, "2.0", "items.json", _items(350))
    _write(tmp_path, "1.0", "manifest.json", {"ddragon_version": "1.0"})
    _write(tmp_path, "2.0", "manifest.json", {"ddragon_version": "2.0"})

    rep = dpd.diff_snapshots(tmp_path / "1.0", tmp_path / "2.0", sections=["items"])
    assert rep["old_patch"] == "1.0" and rep["new_patch"] == "2.0"
    assert rep["sections"]["items"]["changed"][0]["fields"]["gold.total"] == [300, 350]

    text = dpd.render_text(rep)
    assert "Boots" in text and "300" in text and "350" in text


def test_missing_section_file_is_noted_not_fatal(tmp_path):
    _write(tmp_path, "1.0", "manifest.json", {})
    _write(tmp_path, "2.0", "manifest.json", {})
    rep = dpd.diff_snapshots(tmp_path / "1.0", tmp_path / "2.0", sections=["items"])
    assert rep["sections"]["items"]["error"]
    assert "items" in dpd.render_text(rep)


def test_unknown_section_rejected(tmp_path):
    _write(tmp_path, "1.0", "manifest.json", {})
    _write(tmp_path, "2.0", "manifest.json", {})
    with pytest.raises(ValueError):
        dpd.diff_snapshots(tmp_path / "1.0", tmp_path / "2.0", sections=["nope"])
