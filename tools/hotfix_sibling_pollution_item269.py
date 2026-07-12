"""Item 269 - sibling build-data pollution hand-curate (data-only, atomic).

Carry from item 263 + the 2026-06-02 live-watch. The item-167 auto-seed
coverage gap + the align tool routed off-class archetypes onto champions,
leaving paths in data/champion_loadouts.json whose LABEL contradicts their
items. Verified live before fixing:

  AP-labeled-0-AP (AP champion, "AP Bruiser"/"AP JG Brsr" label, 0 AP items):
    Gwen / Elise / Gragas (named in the item-263 carry) PLUS the identical-root
    siblings Mordekaiser / Rumble / Ryze / Swain / Sylas (all AP champions
    carrying the same auto-seeded AD bruiser/tank template). Fixed per-champion
    to real AP item sets so the label is honest.

  "Mage"-mislabeled AD (AD assassin/marksman, "Mage" label, AD items):
    Jhin / Smolder (named) PLUS the AD-assassin siblings Kha'Zix / Qiyana /
    Talon / Zed (same sr-mage mislabel). Rebuilt to the correct AD archetype
    (lethality for the assassins, crit for Smolder).

  Hybrid mislabel: Corki sr ap-hybrid relabeled honestly to AD (SR Corki is
    AD), aram ap-hybrid rebuilt to a genuine AP-hybrid set that earns the label.

  Thin 4-item ARAM "Carry" template across 9 ADCs (Ashe / Caitlyn / Draven /
    Kalista / Miss Fortune / Quinn / Twitch / Varus / Xayah): extended to
    coherent 6-item crit sets, mirroring the item-213-proven Kai'Sa adc-crit.

Senna's enchanter items are INTENTIONAL (support-marksman) - untouched.
Arena auto-flavor "Mage (sec/flav)" mislabels are a separate broad carry
(chaotic mode, lower value) - documented, not swept here.

The item-167 root (rank.py auto-seed coverage gap + the align tool archetype
routing) is UNCHANGED; this is the data-side hand-curate, mirroring
tools/hotfix_kaisa_aram_ashe_sr_item263.py. Idempotent + atomic. Touches
items + label + path key only; runes + summoners are preserved.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Real AP sets per AP champion (no two items share a unique-passive family).
_AP = {
    ("Gwen", "sr-collapsed", "ap-bruiser"): (
        "ap", "AP",
        ["Riftmaker", "Sorcerer's Shoes", "Nashor's Tooth",
         "Rabadon's Deathcap", "Void Staff", "Zhonya's Hourglass",
         "Shadowflame"]),
    ("Gwen", "aram-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Riftmaker", "Sorcerer's Shoes", "Nashor's Tooth",
         "Rabadon's Deathcap", "Cosmic Drive", "Zhonya's Hourglass"]),
    ("Elise", "sr-collapsed", "ap-jg-bruiser"): (
        "ap", "AP",
        ["Hextech Rocketbelt", "Sorcerer's Shoes", "Shadowflame",
         "Rabadon's Deathcap", "Zhonya's Hourglass", "Void Staff",
         "Stormsurge"]),
    ("Gragas", "sr-collapsed", "ap-jg-bruiser"): (
        "ap", "AP",
        ["Riftmaker", "Mercury's Treads", "Liandry's Torment",
         "Rabadon's Deathcap", "Cosmic Drive", "Zhonya's Hourglass",
         "Void Staff"]),
    ("Mordekaiser", "sr-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Riftmaker", "Mercury's Treads", "Liandry's Torment",
         "Rabadon's Deathcap", "Spirit Visage", "Zhonya's Hourglass",
         "Sterak's Gage"]),
    ("Mordekaiser", "aram-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Riftmaker", "Mercury's Treads", "Liandry's Torment",
         "Rabadon's Deathcap", "Spirit Visage", "Zhonya's Hourglass"]),
    ("Rumble", "sr-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Liandry's Torment", "Mercury's Treads", "Riftmaker",
         "Rabadon's Deathcap", "Cosmic Drive", "Zhonya's Hourglass",
         "Sterak's Gage"]),
    ("Rumble", "aram-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Liandry's Torment", "Mercury's Treads", "Riftmaker",
         "Rabadon's Deathcap", "Cosmic Drive", "Zhonya's Hourglass"]),
    ("Ryze", "sr-collapsed", "ap-bruiser"): (
        "ap", "AP",
        ["Archangel's Staff", "Sorcerer's Shoes", "Riftmaker",
         "Rabadon's Deathcap", "Void Staff", "Zhonya's Hourglass",
         "Shadowflame"]),
    ("Ryze", "aram-collapsed", "ap-bruiser"): (
        "ap", "AP",
        ["Archangel's Staff", "Sorcerer's Shoes", "Riftmaker",
         "Rabadon's Deathcap", "Void Staff", "Zhonya's Hourglass"]),
    ("Swain", "sr-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Liandry's Torment", "Sorcerer's Shoes", "Riftmaker",
         "Rabadon's Deathcap", "Spirit Visage", "Zhonya's Hourglass",
         "Sterak's Gage"]),
    ("Swain", "aram-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Liandry's Torment", "Sorcerer's Shoes", "Riftmaker",
         "Rabadon's Deathcap", "Spirit Visage", "Zhonya's Hourglass"]),
    ("Sylas", "sr-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Riftmaker", "Mercury's Treads", "Cosmic Drive",
         "Rabadon's Deathcap", "Zhonya's Hourglass", "Void Staff",
         "Sterak's Gage"]),
    ("Sylas", "aram-collapsed", "ap-bruiser"): (
        "ap-bruiser", "AP Bruiser",
        ["Riftmaker", "Mercury's Treads", "Cosmic Drive",
         "Rabadon's Deathcap", "Zhonya's Hourglass", "Void Staff"]),
}

# AD-assassin/marksman "Mage"-mislabeled SR paths -> correct AD archetype.
# Jhin / Smolder had NO clean AD second path, so the mislabeled sr-mage is
# renamed in place. Kha'Zix / Qiyana / Talon / Zed ALREADY carry a correct
# lethality primary, so their sr-mage is a redundant junk path - removed
# (see _REMOVE) rather than renamed (a rename would collide with lethality).
_AD = {
    ("Jhin", "sr-collapsed", "sr-mage"): (
        "lethality", "Lethality",
        ["Youmuu's Ghostblade", "Boots of Swiftness", "Opportunity",
         "The Collector", "Serylda's Grudge", "Edge of Night",
         "Axiom Arc"]),
    ("Smolder", "sr-collapsed", "sr-mage"): (
        "adc-crit", "Crit",
        ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
         "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane",
         "Bloodthirster"]),
}

# Redundant "Mage"-mislabeled paths on AD assassins that already have a clean
# lethality primary - drop entirely.
_REMOVE = [
    ("Kha'Zix", "sr-collapsed", "sr-mage"),
    ("Qiyana", "sr-collapsed", "sr-mage"),
    ("Talon", "sr-collapsed", "sr-mage"),
    ("Zed", "sr-collapsed", "sr-mage"),
]

# Corki hybrid: SR is honestly AD; ARAM gets a genuine AP-hybrid set.
_CORKI = {
    ("Corki", "sr-collapsed", "ap-hybrid"): (
        "ad", "AD",
        ["Trinity Force", "Berserker's Greaves", "Infinity Edge",
         "Rapid Firecannon", "Lord Dominik's Regards", "Yun Tal Wildarrows",
         "Runaan's Hurricane"]),
    ("Corki", "aram-collapsed", "ap-hybrid"): (
        "ap-hybrid", "AP Hybrid",
        ["Nashor's Tooth", "Sorcerer's Shoes", "Lich Bane",
         "Rabadon's Deathcap", "Shadowflame", "Hextech Gunblade"]),
}

# Thin 4-item ARAM "Carry" -> coherent 6-item crit sets (key/label kept).
_ARAM_CARRY = {
    "Ashe": ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
             "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
    "Caitlyn": ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
                "Rapid Firecannon", "Lord Dominik's Regards", "The Collector"],
    "Draven": ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
               "Bloodthirster", "Lord Dominik's Regards", "The Collector"],
    "Kalista": ["Yun Tal Wildarrows", "Berserker's Greaves", "Runaan's Hurricane",
                "Infinity Edge", "Lord Dominik's Regards", "Rapid Firecannon"],
    "Miss Fortune": ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
                     "Rapid Firecannon", "Lord Dominik's Regards", "The Collector"],
    "Quinn": ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "The Collector"],
    # Twitch intentionally omitted: its curated on-hit path (BotRK +
    # Runaan's) already IS its ARAM carry build, so a generic crit-carry
    # template collided 1:1 with on-hit (item 213 test_b duplicate guard).
    # Twitch is hand-served by on-hit + crit; no generic aram-carry path.
    "Varus": ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
    "Xayah": ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
              "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"],
}


def _apply_path_fix(paths, old_key, new_key, label, items):
    for bp in paths:
        if bp.get("key") in (old_key, new_key):
            bp["items"] = list(items)
            bp["label"] = label
            bp["key"] = new_key
            bp["_source_variant_key"] = new_key
            return True
    return False


def _resync_variant(var):
    paths = var.get("build_paths") or []
    if not paths:
        return
    prim = next((p for p in paths if p.get("_is_primary")), paths[0])
    var["items"] = list(prim.get("items", []))
    if prim.get("runes"):
        var["runes"] = dict(prim["runes"])
    if prim.get("summoners"):
        var["summoners"] = list(prim["summoners"])


def apply(data):
    champs = data["champions"]
    touched = 0
    for table in (_AP, _AD, _CORKI):
        for (champ, vk, old_key), (new_key, label, items) in table.items():
            var = champs.get(champ, {}).get("variants", {}).get(vk)
            if not var:
                continue
            if _apply_path_fix(var.get("build_paths", []), old_key, new_key, label, items):
                _resync_variant(var)
                touched += 1
    for champ, items in _ARAM_CARRY.items():
        var = champs.get(champ, {}).get("variants", {}).get("aram-collapsed")
        if not var:
            continue
        if _apply_path_fix(var.get("build_paths", []), "aram-carry", "aram-carry", "Carry", items):
            _resync_variant(var)
            touched += 1
    for champ, vk, key in _REMOVE:
        var = champs.get(champ, {}).get("variants", {}).get(vk)
        if not var:
            continue
        paths = var.get("build_paths", [])
        kept = [p for p in paths if p.get("key") != key]
        if len(kept) != len(paths):
            var["build_paths"] = kept
            _resync_variant(var)
            touched += 1
    return touched


def main():
    data = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
    n = apply(data)
    tmp = _LOADOUTS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(tmp, _LOADOUTS)
    print(f"item269 hotfix applied: {n} build_paths fixed")


if __name__ == "__main__":
    main()
