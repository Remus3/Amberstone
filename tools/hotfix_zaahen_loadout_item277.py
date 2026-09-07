"""Hotfix item 277 - real curated Zaahen loadout (the deferred DS-batch task).

Zaahen (The Unsundered, key 904, ddragon tags Fighter/Assassin) was carried in
champion_loadouts.json with an all-Doran's PLACEHOLDER primary path ("ap-burst" /
"Burst", AP) on its sr-collapsed + aram-collapsed variants - the unresolved
autogen stub (champion_id None). Item 276 preserved the entry but deferred the
real build (verify-before-declare-broken). This is that build.

Zaahen is NOT in the DS ability catalog (171 champs; Zaahen absent), so the DS
archetype scorer cannot autogen a Zaahen-specific build - this is TAG-DRIVEN
hand-curation from the ddragon Fighter/Assassin tags, mirroring the Kayn
(Fighter/Assassin) sr-collapsed shape: an AD Bruiser primary + an AD lethality
Assassin secondary. If a future patch adds Zaahen's abilities to the DS catalog,
proper enemy-comp autogen becomes possible and can supersede this.

Scope:
  - sr-collapsed   -> rebuilt: [Bruiser (primary), Assassin] (drops the
                     all-Doran's "ap-burst" placeholder + the odd Runaan's-on-a-
                     bruiser auto-seed).
  - aram-collapsed -> rebuilt: [Bruiser (primary), Assassin] (drops the
                     all-Doran's "ap-burst" placeholder + the full-AP "ap-poke"
                     + thin "aram-bruiser" auto-seeds - Zaahen is Fighter/Assassin,
                     AD).
  - arena-collapsed -> LEFT UNTOUCHED: it already carries real (non-placeholder)
                      arena-bruiser + carry paths; no over-bespoke (item 213).

Every rebuilt path is a coherent clash-free 6-item set per
tests/test_champion_loadouts_no_unique_clash.py (one lifeline item max, no
spellblade/immolate/hydra double). Idempotent + atomic (tmp.write_text +
os.replace). Mirrors tools/hotfix_thin_aram_pollution_item276.py.

Usage:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/hotfix_zaahen_loadout_item277.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Bruiser primary (Fighter): Sundered Sky sustain opener + Black Cleaver/Death's
# Dance core (item 276 bruiser core) + Sterak's (lone lifeline) + Guardian Angel.
# Assassin secondary (Assassin): Eclipse lethality + Edge of Night/Serylda's +
# Death's Dance + Maw (lone lifeline). Mirrors Kayn jg-bruiser / jg-assassin.
# Item s8 (2026-06-10): SR rows carry the operator-set 7-entry length
# (7th = Shojin / Youmuu's per the s8 sweep pool refill); ARAM stays 6.
_SR_BRUISER = [
    "Sundered Sky", "Plated Steelcaps", "Black Cleaver",
    "Death's Dance", "Sterak's Gage", "Guardian Angel",
    "Spear of Shojin",
]
_SR_ASSASSIN = [
    "Eclipse", "Mercury's Treads", "Edge of Night",
    "Serylda's Grudge", "Death's Dance", "Maw of Malmortius",
    "Youmuu's Ghostblade",
]
# ARAM bruiser leans sustain (Spirit Visage over GA); assassin mirrors the
# SR AD set minus the s8 7th slot (ARAM target is 6).
_ARAM_BRUISER = [
    "Sundered Sky", "Plated Steelcaps", "Black Cleaver",
    "Death's Dance", "Sterak's Gage", "Spirit Visage",
]
_ARAM_ASSASSIN = list(_SR_ASSASSIN[:6])

_BRUISER_RUNES = {"keystone": "Conqueror", "primary": "Precision", "secondary": "Resolve"}
_ASSASSIN_RUNES = {"keystone": "Electrocute", "primary": "Domination", "secondary": "Precision"}


def _path(key: str, label: str, items: list, runes: dict, summoners: list, primary: bool) -> dict:
    return {
        "key": key,
        "label": label,
        "items": list(items),
        "runes": dict(runes),
        "summoners": list(summoners),
        "_source_variant_key": key,
        "_is_primary": primary,
    }


def _build_variant(label: str, mode: str, summoners: list,
                   bruiser_items: list, assassin_items: list) -> dict:
    paths = [
        _path(f"{mode}-bruiser", "Bruiser", bruiser_items, _BRUISER_RUNES, summoners, True),
        _path(f"{mode}-assassin", "Assassin", assassin_items, _ASSASSIN_RUNES, summoners, False),
    ]
    prim = paths[0]
    return {
        "label": label,
        "modes": [mode],
        "runes": dict(prim["runes"]),
        "summoners": list(summoners),
        "items": list(prim["items"]),
        "_collapsed": True,
        "build_paths": paths,
    }


def _curated_sr() -> dict:
    return _build_variant("Builds for Zaahen", "sr", [4, 14], _SR_BRUISER, _SR_ASSASSIN)


def _curated_aram() -> dict:
    return _build_variant("Builds for Zaahen", "aram", [4, 32], _ARAM_BRUISER, _ARAM_ASSASSIN)


def _matches(existing: dict, target: dict) -> bool:
    """True when the existing variant already equals the curated target
    (build_paths items + labels + primary flags) - idempotent guard."""
    ep = existing.get("build_paths") or []
    tp = target["build_paths"]
    if len(ep) != len(tp):
        return False
    for a, b in zip(ep, tp):
        if a.get("items") != b["items"] or a.get("label") != b["label"]:
            return False
        if bool(a.get("_is_primary")) != b["_is_primary"]:
            return False
    return True


def apply(data: dict) -> int:
    champs = data["champions"]
    z = champs.get("Zaahen")
    if not z:
        # Zaahen must stay present (ZaahenPreservedTests); never create from nothing.
        print("WARNING: Zaahen entry absent - nothing to curate (not creating)")
        return 0
    variants = z.setdefault("variants", {})
    touched = 0
    for mode, builder in (("sr", _curated_sr), ("aram", _curated_aram)):
        key = f"{mode}-collapsed"
        target = builder()
        existing = variants.get(key)
        if existing and _matches(existing, target):
            continue  # idempotent no-op
        variants[key] = target
        touched += 1
    # arena-collapsed intentionally left untouched (already real; see docstring).
    return touched


def run(dry_run: bool = False) -> int:
    data = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
    n = apply(data)
    print(f"=== item 277 Zaahen curated loadout: {n} variant(s) rebuilt ===")
    if dry_run:
        print("(dry-run; no write)")
        return 0
    if not n:
        print("no changes; Zaahen already curated (idempotent no-op)")
        return 0
    text = json.dumps(data, indent=2, ensure_ascii=True) + "\n"
    tmp = _LOADOUTS.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(_LOADOUTS))
    print(f"wrote {_LOADOUTS}")
    return 0


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="item 277 Zaahen curated-loadout hotfix")
    p.add_argument("--dry-run", action="store_true", help="report only, no write")
    args = p.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
