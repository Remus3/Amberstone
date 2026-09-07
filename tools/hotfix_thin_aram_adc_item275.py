"""Hotfix item 275 - thin ARAM ADC carry residual + AP-on-hit label clarity.

Item 269/273 already swept the substantive SR + ARAM AP/AD sibling-
pollution mislabels (Corki / Jhin / Smolder / Gwen / Elise / Gragas + 8
ARAM-carry ADCs + Arena Mage relabels). The 2026-06-02 live-watch (LW)
"sibling pollution" carry that named those was a stale pre-269 snapshot;
verified live this session. The residual the named sweep missed:

  Thin n=4 ADC ARAM carry PRIMARY paths keyed by ARCHETYPE (not the
  'aram-carry'/'Carry' key item 269 swept), so item 269 skipped them.
  Each primary carries an incoherent <5-item set that does not match its
  own label (e.g. Jinx 'Crit' with zero crit items, Caitlyn 'Leth Poke'
  with Infinity Edge, Zeri 'On-Hit' with Heartsteel bruiser pollution).
  Rebuilt to coherent 6-item sets matching the path's archetype, mirroring
  the item-269/213-proven clean sets (no unique-passive-family clash), and
  distinct from each champion's sibling paths so no whole-path dup is
  introduced (the item-274 T4 dup trap).

  Lulu / Teemo ARAM 'on-hit' paths carry genuine AP-on-hit item sets
  (Nashor's Tooth / Lich Bane / Rabadon's / Wit's End / Guinsoo's) under a
  bare 'On-Hit' label that reads as AD on-hit. Relabeled to 'AP On-Hit'
  (label only; key 'on-hit' preserved to avoid touching the colon-resolve
  path key). Matches Teemo's SR 'ap-on-hit' = 'AP On-Hit' convention.

OUT OF SCOPE (flagged, NOT swept this pass, per operator decision):
  * 17 thin n=4 aram-bruiser / aram-assassin SECONDARY paths - intentional
    thin auto-seed (item 166); extending all of them risks the item-213
    "do not over-bespoke the auto-seeds" trap.
  * 'Zaahen' loadout entry - junk fixture (champion_id None, all-Doran's
    starter items, not a real champion). Separate cleanup, not pollution.

The item-167 root (rank.py auto-seed coverage gap + the align tool's
archetype routing) is UNCHANGED; this is the data-side hand-curate,
mirroring tools/hotfix_sibling_pollution_item269.py. Idempotent + atomic.
Touches items + label only; runes + summoners + keys are preserved.

Usage:
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/hotfix_thin_aram_adc_item275.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Thin n=4 ADC ARAM carry PRIMARY paths -> coherent 6-item set matching
# the path's existing archetype key. Each set is clash-free (no two items
# share a unique-passive family) and distinct from the champion's siblings.
_EXTEND = {
    # Jinx 'Crit' primary had BorK/Berserker's/LDR/Runaan's (0 crit) -> real
    # crit. Distinct from on-hit (BorK/Wit's/Guinsoo's) + aram-carry.
    ("Jinx", "adc-crit"): (
        "Crit",
        ["Yun Tal Wildarrows", "Berserker's Greaves", "Infinity Edge",
         "Rapid Firecannon", "Lord Dominik's Regards", "Runaan's Hurricane"]),
    # Zeri 'On-Hit' primary had Heartsteel bruiser pollution -> energized
    # on-hit. Distinct from crit (IE/PD/Bloodthirster) + aram-carry.
    ("Zeri", "on-hit"): (
        "On-Hit",
        ["Blade of The Ruined King", "Berserker's Greaves", "Statikk Shiv",
         "Rapid Firecannon", "Lord Dominik's Regards", "Phantom Dancer"]),
    # Caitlyn 'Leth Poke' primary had Infinity Edge (crit) -> real lethality.
    # Distinct from crit + aram-carry (both crit sets).
    ("Caitlyn", "lethality-poke"): (
        "Leth Poke",
        ["Youmuu's Ghostblade", "Berserker's Greaves", "Opportunity",
         "The Collector", "Serylda's Grudge", "Edge of Night"]),
    # Varus 'Lethality' primary had BorK (no lethality) -> real lethality.
    # Distinct from on-hit + aram-carry (crit).
    ("Varus", "lethality"): (
        "Lethality",
        ["Youmuu's Ghostblade", "Berserker's Greaves", "Opportunity",
         "The Collector", "Serylda's Grudge", "Edge of Night"]),
}

# AP-on-hit ARAM paths under a bare 'On-Hit' label -> 'AP On-Hit' (label
# only; items + key preserved).
_RELABEL_AP_ONHIT = [
    ("Lulu", "on-hit"),
    ("Teemo", "on-hit"),
]
_AP_ONHIT_LABEL = "AP On-Hit"


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
    for (champ, key), (label, items) in _EXTEND.items():
        var = champs.get(champ, {}).get("variants", {}).get("aram-collapsed")
        if not var:
            continue
        for bp in var.get("build_paths", []):
            if bp.get("key") != key:
                continue
            if list(bp.get("items") or []) == items and bp.get("label") == label:
                break  # idempotent no-op
            bp["items"] = list(items)
            bp["label"] = label
            _resync_variant(var)
            touched += 1
            break
    for champ, key in _RELABEL_AP_ONHIT:
        var = champs.get(champ, {}).get("variants", {}).get("aram-collapsed")
        if not var:
            continue
        for bp in var.get("build_paths", []):
            if bp.get("key") == key and bp.get("label") != _AP_ONHIT_LABEL:
                bp["label"] = _AP_ONHIT_LABEL
                touched += 1
                break
    return touched


def run(dry_run: bool = False) -> int:
    data = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
    n = apply(data)
    print(f"=== item 275 thin-ARAM-ADC + AP-on-hit label: {n} change(s) ===")
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
    p = argparse.ArgumentParser(description="item 275 thin-ARAM-ADC hotfix")
    p.add_argument("--dry-run", action="store_true", help="report only, no write")
    args = p.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
