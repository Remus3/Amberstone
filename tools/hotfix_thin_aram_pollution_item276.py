"""Hotfix item 276 - thin ARAM bruiser/assassin SECONDARY paths.

TARGET 1 - 17 thin n=4 bruiser/assassin SECONDARY paths in aram-collapsed variants.
  Item 275 documented these as OUT-OF-SCOPE (intentional auto-seed) but item 276
  now sweeps them. Each path has only 4 items - rebuilt to coherent clash-free
  6-item sets matching the path archetype label, distinct from sibling paths.
  Per item 213 / 274 / 275 conventions:
    - No unique-passive-family clash within or across a champion's paths
    - No over-bespoke - use archetype-appropriate standard sets
    - Rebuild rather than remove (they are 3rd paths between 2 existing valid paths)

  Champions + paths rebuilt:
    Bruiser (aram-bruiser key): Aatrox, Fiora, Garen, Illaoi, Jayce, Lillia,
                                 Mordekaiser, Nasus, Sett, Udyr, Yorick
    Assassin (aram-assassin key): Akali, Ekko, Elise, Fizz, Katarina, Shaco

Zaahen NOT swept - verify-before-declare-broken: Zaahen is a REAL champion
  (The Unsundered, Fighter/Assassin, key 904, added 16.11.1), NOT a junk fixture.
  Its aram-collapsed build carries all-Doran's placeholder items because the
  champion_id is None (an unresolved autogen stub), but removing a real champion's
  loadout entry would leave RC with NO build for it. The placeholder is preserved
  as-is; a real curated/autogen build is a separate DS-batch task. Do NOT remove it.

Idempotent + atomic (tmp.write_text + os.replace). Touches items + label only;
runes + summoners + keys preserved. Mirrors tools/hotfix_thin_aram_adc_item275.py.

Usage:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/hotfix_thin_aram_pollution_item276.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Rebuilt bruiser paths - 6 coherent items each, clash-free with sibling paths.
# Family constraints per tests/test_champion_loadouts_no_unique_clash.py:
#   spellblade: trinity_force, essence_reaver, lich_bane, iceborg_gauntlet,
#               divine_sunderer, sheen, bloodsong, dusk_and_dawn
#   lifeline: steraks_gage, maw, immortal_shieldbow, seraphs, hexdrinker
#   immolate: sunfire_aegis, void_immolation, hollow_radiance, bami_cinder
#   hydra_cleave: stridebreaker, titanic, ravenous, profane_hydra
#
# For each champion: verify no clash with any item in their other 2 ARAM paths.
#
# Black Cleaver bruiser core is safe for most - BC has no unique passive family.
# Sundered Sky is spellblade-free (it is NOT in spellblade family in RC's registry).
_BRUISER_6 = (
    "Bruiser",
    [
        "Black Cleaver",
        "Plated Steelcaps",
        "Sterak's Gage",
        "Death's Dance",
        "Spirit Visage",
        "Gargoyle Stoneplate",
    ],
)

# Champion-specific overrides where the default 6 would clash with sibling items.
# Each tuple: (label, [6 items])
_BRUISER_OVERRIDES: dict[str, tuple[str, list[str]]] = {
    # Fiora primary=duelist has Trinity Force + Sterak's; lethality has no Sterak.
    # Use DD / Sundered Sky / Black Cleaver set; avoid Sterak's (in duelist primary).
    "Fiora": (
        "Bruiser",
        [
            "Black Cleaver",
            "Plated Steelcaps",
            "Death's Dance",
            "Sundered Sky",
            "Maw of Malmortius",
            "Gargoyle Stoneplate",
        ],
    ),
    # Garen primary=tank-aram has Sterak's-free tank set; bruiser sibling has Sterak's.
    # Default 6 uses Sterak's - that would clash with bruiser sibling at idx=2.
    # Use a distinct set: swap Sterak's for Overlord's Bloodmail.
    "Garen": (
        "Bruiser",
        [
            "Black Cleaver",
            "Plated Steelcaps",
            "Overlord's Bloodmail",
            "Death's Dance",
            "Spirit Visage",
            "Gargoyle Stoneplate",
        ],
    ),
    # Illaoi bruiser primary has Trinity Force + Sterak's + Titanic (hydra_cleave).
    # Avoid Sterak's (in primary) + Titanic (hydra family clash with primary).
    "Illaoi": (
        "Bruiser",
        [
            "Black Cleaver",
            "Plated Steelcaps",
            "Death's Dance",
            "Sundered Sky",
            "Gargoyle Stoneplate",
            "Overlord's Bloodmail",
        ],
    ),
    # Jayce lethality-poke primary already has Trinity Force (spellblade).
    # bruiser sibling at idx=2 has Sterak's.
    # Use: no TF (already in lethality), no Sterak's (in sibling bruiser).
    "Jayce": (
        "Bruiser",
        [
            "Black Cleaver",
            "Mercury's Treads",
            "Death's Dance",
            "Sundered Sky",
            "Maw of Malmortius",
            "Gargoyle Stoneplate",
        ],
    ),
    # Lillia ap-jg primary is full AP; ap-tank is AP tank. aram-bruiser should be AD.
    # No spellblade issue. Use BC set with Overlord instead of Spirit Visage
    # to differentiate from ap-tank's Spirit Visage.
    "Lillia": (
        "Bruiser",
        [
            "Black Cleaver",
            "Plated Steelcaps",
            "Sterak's Gage",
            "Death's Dance",
            "Sundered Sky",
            "Gargoyle Stoneplate",
        ],
    ),
    # Mordekaiser ap-bruiser + ap-tank are both AP. aram-bruiser = AD bruiser.
    # No special constraint beyond the default.
    "Mordekaiser": _BRUISER_6,
    # Nasus tank-top has Sterak's + Jak'Sho; ap-bruiser is AP. aram-bruiser = AD.
    # Avoid Sterak's (in tank-top primary).
    "Nasus": (
        "Bruiser",
        [
            "Black Cleaver",
            "Plated Steelcaps",
            "Death's Dance",
            "Overlord's Bloodmail",
            "Spirit Visage",
            "Gargoyle Stoneplate",
        ],
    ),
    # Sett tank-aram has Sterak's + Sundered Sky; bruiser sibling has TF + Sterak's.
    # Avoid Sterak's (in both siblings).
    "Sett": (
        "Bruiser",
        [
            "Black Cleaver",
            "Plated Steelcaps",
            "Death's Dance",
            "Overlord's Bloodmail",
            "Spirit Visage",
            "Gargoyle Stoneplate",
        ],
    ),
    # Udyr bruiser primary has Sterak's + Sundered Sky; tank-aram has Sunfire.
    # Avoid Sterak's (in bruiser primary) + Sunfire (immolate, in tank-aram).
    "Udyr": (
        "Bruiser",
        [
            "Black Cleaver",
            "Mercury's Treads",
            "Death's Dance",
            "Sundered Sky",
            "Maw of Malmortius",
            "Gargoyle Stoneplate",
        ],
    ),
    # Yorick splitpush has Trinity Force (spellblade) + Sterak's + BorK.
    # tank-aram has Sunfire (immolate) + Sterak's.
    # Avoid Trinity Force (spellblade clash with splitpush) + Sterak's (in both).
    "Yorick": (
        "Bruiser",
        [
            "Black Cleaver",
            "Plated Steelcaps",
            "Death's Dance",
            "Overlord's Bloodmail",
            "Spirit Visage",
            "Gargoyle Stoneplate",
        ],
    ),
}

# Rebuilt assassin paths - lethality/AD-bruiser style for ARAM AP assassins.
# These champs all have AP primary + AP bruiser secondaries already.
# aram-assassin = AD/lethality alternative, different playstyle.
# All 5 AP assassins use same family-safe set.
# Akali/Ekko/Elise/Fizz/Katarina: siblings are AP (Void Staff, Lich Bane, Riftmaker).
# Family constraints: Sterak's Gage + Maw of Malmortius both lifeline -> can't both appear.
# Use Sterak's (lifeline) + Gargoyle Stoneplate (no family) instead of Maw.
# Lich Bane is spellblade - must avoid (Akali/Fizz/Kata already have it in siblings).
_ASSASSIN_6 = (
    "Assassin",
    [
        "Eclipse",
        "Plated Steelcaps",
        "Black Cleaver",
        "Sterak's Gage",
        "Death's Dance",
        "Gargoyle Stoneplate",
    ],
)

# Shaco is AD anyway (lethality primary + AP burst secondary).
# aram-assassin for Shaco - a tankier lethality option.
# Lethality primary has Trinity Force (spellblade). Avoid TF.
# Sterak's + Serylda's + DD + Eclipse is lifeline-safe (only Sterak's in lifeline).
_SHACO_ASSASSIN = (
    "Assassin",
    [
        "Eclipse",
        "Plated Steelcaps",
        "Serylda's Grudge",
        "Sterak's Gage",
        "Death's Dance",
        "Gargoyle Stoneplate",
    ],
)


def _choose_bruiser(champ: str) -> tuple[str, list[str]]:
    return _BRUISER_OVERRIDES.get(champ, _BRUISER_6)


def _choose_assassin(champ: str) -> tuple[str, list[str]]:
    if champ == "Shaco":
        return _SHACO_ASSASSIN
    return _ASSASSIN_6


def _resync_variant(var: dict) -> None:
    """Copy the primary path's items/runes/summoners up to the variant
    level (back-compat for non-path-aware callers). Mirrors item 269."""
    paths = var.get("build_paths") or []
    if not paths:
        return
    prim = next((p for p in paths if p.get("_is_primary")), paths[0])
    var["items"] = list(prim.get("items", []))
    if prim.get("runes"):
        var["runes"] = dict(prim["runes"])
    if prim.get("summoners"):
        var["summoners"] = list(prim["summoners"])


def apply(data: dict) -> int:
    champs = data["champions"]
    touched = 0

    # TARGET 1: rebuild thin bruiser/assassin secondary paths
    for champ_name, champ_data in list(champs.items()):
        if champ_name == "Zaahen":
            continue
        aram_coll = champ_data.get("variants", {}).get("aram-collapsed")
        if not aram_coll:
            continue
        build_paths = aram_coll.get("build_paths", [])
        for bp in build_paths:
            is_primary = bp.get("_is_primary", False)
            if is_primary:
                continue
            key = bp.get("key", "")
            items = bp.get("items", [])
            if "aram-bruiser" in key and len(items) < 5:
                new_label, new_items = _choose_bruiser(champ_name)
                if list(items) == new_items and bp.get("label") == new_label:
                    break  # idempotent no-op
                bp["items"] = list(new_items)
                bp["label"] = new_label
                _resync_variant(aram_coll)
                touched += 1
                break
            if "aram-assassin" in key and len(items) < 5:
                new_label, new_items = _choose_assassin(champ_name)
                if list(items) == new_items and bp.get("label") == new_label:
                    break  # idempotent no-op
                bp["items"] = list(new_items)
                bp["label"] = new_label
                _resync_variant(aram_coll)
                touched += 1
                break

    # Zaahen intentionally NOT touched - it is a real champion (see module docstring).

    return touched


def run(dry_run: bool = False) -> int:
    data = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
    n = apply(data)
    print(f"=== item 276 thin-ARAM-pollution: {n} change(s) ===")
    if dry_run:
        print("(dry-run; no write)")
        return 0
    if not n:
        print("no changes; data already clean (idempotent no-op)")
        return 0
    text = json.dumps(data, indent=2, ensure_ascii=True) + "\n"
    tmp = _LOADOUTS.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(_LOADOUTS))
    print(f"wrote {_LOADOUTS}")
    return 0


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(
        description="item 276 thin-ARAM-bruiser/assassin hotfix"
    )
    p.add_argument("--dry-run", action="store_true", help="report only, no write")
    args = p.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
