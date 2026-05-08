"""validate_build_data.py — cross-mode item contamination validator.

Scans a build JSON file (Phase 1/2 refresh format OR canonical format)
and reports champions that reference items that don't belong in the
declared mode.

Usage:
    python scripts/validate_build_data.py <path_to_json> [--mode sr|aram|arena|mayhem]

The mode is auto-detected from the file's _meta.scope field if --mode
is omitted; falls back to inferring from the filename.

Exits 0 on clean, 1 on any contamination found.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Items that are exclusive to specific modes — referencing them in a
# different mode's build is a data-integrity bug. Sourced from
# docs/{ARENA,SR,ARAM_MAYHEM}_*_2026-05-02.md research findings AND
# verified against data/meta/ddragon_items.json `maps` field.
#
# CAVEAT: DDragon has dual-ID items in 16.9.1+ (memory
# reference_items_index_alias_ids.md). Items like Hexoptics C44, Sundered
# Sky, Overlord's Bloodmail have both an SR/ARAM-available id (e.g. 2523,
# 6610, 2501) AND an arena-only id (22xxxx, 226610, 447111) under the
# same display name. We can NOT flag those by name — stats sites refer
# to the SR/ARAM variant in SR/ARAM builds. Only items that have NO
# SR/ARAM-available alias-id are listed below.
ARENA_ONLY = {
    "Reaper's Toll",          # id 443090 only — Arena=True, no SR/ARAM variant
    "Arcane Sweeper",         # arena anvil
    "Goliath",                # Prismatic upgrade
    "Mystic Punch",           # Prismatic upgrade
    "Shardblade",             # added 26.9 arena-only
    "Hemomancer's Helm",      # arena starter
    "Pyromancer's Cloak",     # arena
    "Hamstringer",            # arena
    "Reverberation",          # Prismatic
    "Moonflair Spellblade",   # Prismatic
    "Black Hole Gauntlet",    # Prismatic
    "Dragonheart",            # arena
    "Cloak of Starry Night",  # arena
    "Shield of Molten Stone", # arena
    "Demon King's Crown",     # arena
    "Diamond-Tipped Spear",   # arena
    "Runecarver",             # arena
}

MAYHEM_ONLY = {
    # Per data/meta/ddragon_items.json maps field, items below have NO
    # arena alias-id (only ARAM map 12 = True). Items like Atma's
    # Reckoning (id 223039) and Sword of Blossoming Dawn (id 4011) have
    # arena variants and are excluded from this set.
    "Rite of Ruin",   # only id 123430, ARAM=True only
}

# Items removed from SR but still valid in other modes (Arena retained
# Opportunity + Galeforce per DDragon dual-IDs). Used only for SR/ARAM
# validation; arena and mayhem don't enforce this list.
SR_REMOVED_ITEMS = {
    "Opportunity",        # aggregator A SR builds confirm removed from SR meta in 26.9
    "Trailblazer",        # removed in 26.9
    "Trailblade",         # alt spelling
    "Galeforce",          # removed from SR pre-26.9 (per project memory + aggregator A)
}


def detect_mode(data: dict, fallback_path: Path) -> str:
    scope = (data.get("_meta") or {}).get("scope", "").lower()
    if "arena" in scope:
        return "arena"
    if "mayhem" in scope:
        return "mayhem"
    if "aram" in scope:
        return "aram"
    if "sr" in scope or "summoner" in scope:
        return "sr"
    name = fallback_path.name.lower()
    for mode in ("arena", "mayhem", "aram", "sr"):
        if mode in name:
            return mode
    return "unknown"


def violations_for_mode(mode: str) -> dict[str, set[str]]:
    """Return {label: forbidden_items} for the given mode."""
    out: dict[str, set[str]] = {}
    if mode == "sr":
        out["SR-REMOVED"] = SR_REMOVED_ITEMS
        out["ARENA-ONLY"] = ARENA_ONLY
        out["MAYHEM-ONLY"] = MAYHEM_ONLY
    elif mode == "aram":
        out["SR-REMOVED"] = SR_REMOVED_ITEMS
        out["ARENA-ONLY"] = ARENA_ONLY
        out["MAYHEM-ONLY"] = MAYHEM_ONLY
    elif mode == "mayhem":
        out["ARENA-ONLY"] = ARENA_ONLY
        # Mayhem CAN use Mayhem-only items, so no MAYHEM-ONLY forbid.
    elif mode == "arena":
        out["MAYHEM-ONLY"] = MAYHEM_ONLY
        # Arena retained Opportunity + Galeforce + many other "SR-removed"
        # items per DDragon dual-IDs (e.g. Opportunity id 226701 has
        # Arena=True). No SR-removed enforcement.
        # Arena CAN use arena-only items.
    return out


def find_in_entry(entry: dict, item: str) -> list[str]:
    """Return list of field-paths where `item` appears in this entry's
    canonical build fields. Provenance comments in build_note/_filtered
    don't count."""
    hits: list[str] = []
    SKIP_FIELDS = {"build_note", "_sources", "_filtered_items", "kit_notes",
                   "aram_specific", "arena_meta"}
    for k, v in entry.items():
        if k in SKIP_FIELDS:
            continue
        if isinstance(v, str):
            if item.lower() in v.lower():
                hits.append(k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, str) and item.lower() in x.lower():
                    hits.append(f"{k}[{i}]")
                elif isinstance(x, dict):
                    blob = json.dumps(x, default=str)
                    if item.lower() in blob.lower():
                        hits.append(f"{k}[{i}](nested)")
    return hits


def main():
    if len(sys.argv) < 2:
        print("usage: validate_build_data.py <path> [--mode sr|aram|arena|mayhem]")
        sys.exit(2)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"file not found: {path}")
        sys.exit(2)

    data = json.loads(path.read_text(encoding="utf-8"))
    champs = data.get("champions") or {n: v for n, v in data.items()
                                        if not n.startswith("_") and isinstance(v, dict)}

    mode = None
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if not mode:
        mode = detect_mode(data, path)
    print(f"== validating {path.name} (mode={mode}, {len(champs)} champs) ==")

    if mode == "unknown":
        print("could not detect mode; specify --mode")
        sys.exit(2)

    forbid = violations_for_mode(mode)
    total_violations = 0
    for label, items in forbid.items():
        for item in items:
            for cname, entry in champs.items():
                if not isinstance(entry, dict):
                    continue
                hits = find_in_entry(entry, item)
                if hits:
                    print(f"  [{label}] {cname}: {item!r} in {hits}")
                    total_violations += 1

    if total_violations == 0:
        print("  ✓ clean — no cross-mode contamination")
        sys.exit(0)
    else:
        print(f"\n{total_violations} violation(s) — fix before merging into canonical build files")
        sys.exit(1)


if __name__ == "__main__":
    main()
