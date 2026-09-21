"""RM-81 follow-up: the staleness detector must see RATIO-ONLY drift.

The detector compared cooldown endpoints and BASE endpoints only, cutting each
wiki damage line at its first ``{{as|`` wrapper - which is exactly where the
scaling terms live. A change that moves only a ratio therefore produced no row.

Regression fixture, verbatim from the live wiki at DS patch 16.18.1:

  * Poppy Q Hammer Shock - live ``(+ 75% bonus AD)``, stored ``bonus_ad_pct``
    100. Base 30..130 and cooldown 8..4 are UNCHANGED on both sides, so the
    pre-fix detector reported Poppy as current.

The stored block is the committed ``champion_abilities.json`` shape (Meraki
content patch 25.15), trimmed to the fields the detector reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_wiki_staleness_check as M  # noqa: E402

POPPY_Q_WIKI = (
    "|leveling = {{st|Physical Damage|{{ap|30 to 130}} {{as|(+ 75% '''bonus''' AD)}} "
    "{{as|(+ {{ap|7 to 9}}% of target's '''maximum''' health)}}}}\n"
    "|leveling2    = {{st|Slow|{{ap|20 to 32}}% {{as|(+ {{fd|0.8}}% per 100 "
    "'''Poppy's bonus''' health)}}}}\n"
    "|cooldown = {{ap|8 to 4}}\n"
)

POPPY_Q_STORED = {
    "key": "Q",
    "name": "Hammer Shock",
    "cooldown": [8.0, 7.0, 6.0, 5.0, 4.0],
    "damage_blocks": [
        {
            "attribute": "Physical Damage",
            "attribute_kind": "damage",
            "base": [30.0, 55.0, 80.0, 105.0, 130.0],
            "bonus_ad_pct": [100.0, 100.0, 100.0, 100.0, 100.0],
            "target_max_hp_pct": [9.0, 9.0, 9.0, 9.0, 9.0],
        },
        {
            "attribute": "Slow",
            "attribute_kind": "slow",
            "raw_modifiers": [{"values": [20, 25, 30, 35, 40], "units": ["%"] * 5}],
        },
    ],
}

# Thresh E Flay at 16.18.1: base 75 -> 65 AND ratio 70 -> 60 in one line.
THRESH_E_WIKI = (
    "|leveling2    = {{st|Magic Damage|{{ap|65 to 245}} {{as|(+ 60% AP)}}}}"
    "{{st|Slow|{{ap|20 to 40}}%}}\n|cooldown     = {{ap|13 to 10}}\n"
)
THRESH_E_STORED = {
    "key": "E",
    "name": "Flay",
    "cooldown": [13.0, 12.25, 11.5, 10.75, 10.0],
    "damage_blocks": [
        {
            "attribute": "Magic Damage",
            "attribute_kind": "damage",
            "base": [75.0, 120.0, 165.0, 210.0, 255.0],
            "ap_pct": [70.0, 70.0, 70.0, 70.0, 70.0],
        }
    ],
}


def _fields(rows):
    return {r["field"]: (r["meraki"], r["wiki"]) for r in rows}


# --------------------------------------------------------------------------- parser


def test_parse_leveling_ratios_reads_bonus_ad_and_target_max_hp():
    got = M.parse_leveling_ratios(POPPY_Q_WIKI)
    assert got["Physical Damage"]["bonus_ad_pct"] == (75.0, 75.0)
    assert got["Physical Damage"]["target_max_hp_pct"] == (7.0, 9.0)


def test_parse_leveling_ratios_skips_per_100_phrases():
    # "% per 100 Poppy's bonus health" is a different UNIT, never a ratio key.
    got = M.parse_leveling_ratios(POPPY_Q_WIKI)
    assert "Slow" not in got or not got["Slow"]


def test_parse_leveling_ratios_evaluates_summed_ap_term():
    wiki = "|leveling = {{st|Total Enhanced Damage|{{ap|20 to 120}} {{as|(+ {{ap|45+20}}% AP)}}}}\n"
    assert M.parse_leveling_ratios(wiki)["Total Enhanced Damage"]["ap_pct"] == (65.0, 65.0)


def test_parse_leveling_ratios_distinguishes_bonus_ad_from_total_ad():
    wiki = "|leveling = {{st|Physical Damage|{{ap|10 to 50}} {{as|(+ 110% AD)}}}}\n"
    got = M.parse_leveling_ratios(wiki)["Physical Damage"]
    assert got == {"total_ad_pct": (110.0, 110.0)}


def test_duplicate_ratio_key_on_one_label_is_dropped_as_ambiguous():
    wiki = "|leveling = {{st|Magic Damage|{{ap|10 to 50}} {{as|(+ 40% AP)}} {{as|(+ 20% AP)}}}}\n"
    assert "ap_pct" not in M.parse_leveling_ratios(wiki).get("Magic Damage", {})


def test_meraki_endpoints_carries_ratio_endpoints():
    mine = M.meraki_endpoints(POPPY_Q_STORED)
    assert mine["ratios"]["Physical Damage"]["bonus_ad_pct"] == (100.0, 100.0)


# --------------------------------------------------------------------------- detection


def test_poppy_q_ratio_only_drift_is_detected():
    rows = M.compare_ability("Poppy", "Q", POPPY_Q_STORED, POPPY_Q_WIKI)
    got = _fields(rows)
    assert got["ratio:Physical Damage:bonus_ad_pct"] == ([100.0, 100.0], [75.0, 75.0])
    # Base and cooldown are unchanged - the ratio row is the only evidence.
    assert not any(f.startswith("base:") or f == "cooldown" for f in got)


def test_ratio_row_is_marked_kind_ratio():
    rows = M.compare_ability("Poppy", "Q", POPPY_Q_STORED, POPPY_Q_WIKI)
    ratio = [r for r in rows if r["field"].startswith("ratio:")]
    assert ratio and all(r.get("kind") == "ratio" for r in ratio)


def test_thresh_e_base_and_ratio_both_reported():
    got = _fields(M.compare_ability("Thresh", "E", THRESH_E_STORED, THRESH_E_WIKI))
    assert got["base:Magic Damage"] == ([75.0, 255.0], [65.0, 245.0])
    assert got["ratio:Magic Damage:ap_pct"] == ([70.0, 70.0], [60.0, 60.0])


def test_matching_ratio_produces_no_row():
    stored = dict(THRESH_E_STORED)
    stored["damage_blocks"] = [
        dict(THRESH_E_STORED["damage_blocks"][0], base=[65.0, 245.0], ap_pct=[60.0] * 5)
    ]
    assert M.compare_ability("Thresh", "E", stored, THRESH_E_WIKI) == []


def test_ratio_present_on_one_side_only_is_not_a_finding():
    # Stored carries no ap_pct; the live page does. Absence is a representation
    # gap, not a measured disagreement, so the detector stays conservative.
    stored = dict(THRESH_E_STORED)
    blk = dict(THRESH_E_STORED["damage_blocks"][0], base=[65.0, 245.0])
    blk.pop("ap_pct")
    stored["damage_blocks"] = [blk]
    assert M.compare_ability("Thresh", "E", stored, THRESH_E_WIKI) == []


def test_run_names_poppy_stale_on_ratio_alone(monkeypatch):
    doc = {"meraki_content_patch": "25.15", "data": {"Poppy": {"Q": [POPPY_Q_STORED]}}}
    monkeypatch.setattr(M, "_load_abilities", lambda patch: doc)
    monkeypatch.setattr(M, "_load_champion_names", lambda patch: {})
    monkeypatch.setattr(
        M, "fetch_pages", lambda titles: {"Template:Data Poppy/Hammer Shock": POPPY_Q_WIKI}
    )
    monkeypatch.setattr(M, "_engine_ratio_lookup", lambda patch: None)
    report = M.run("16.18.1")
    assert report["stale_champions"] == ["Poppy"]
    assert report["_ratio_findings"] >= 1


def test_engine_effective_annotation_flags_uncorrected_ratio(monkeypatch):
    doc = {"meraki_content_patch": "25.15", "data": {"Poppy": {"Q": [POPPY_Q_STORED]}}}
    monkeypatch.setattr(M, "_load_abilities", lambda patch: doc)
    monkeypatch.setattr(M, "_load_champion_names", lambda patch: {})
    monkeypatch.setattr(
        M, "fetch_pages", lambda titles: {"Template:Data Poppy/Hammer Shock": POPPY_Q_WIKI}
    )

    def lookup(champ, slot, attr, key):
        return (100.0, 100.0) if key == "bonus_ad_pct" else (7.0, 9.0)

    monkeypatch.setattr(M, "_engine_ratio_lookup", lambda patch: lookup)
    rows = {r["field"]: r for r in M.run("16.18.1")["findings"]}
    ad = rows["ratio:Physical Damage:bonus_ad_pct"]
    assert ad["engine_effective"] == [100.0, 100.0]
    assert ad["engine_stale"] is True
    hp = rows["ratio:Physical Damage:target_max_hp_pct"]
    assert hp["engine_stale"] is False
