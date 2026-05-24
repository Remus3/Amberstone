"""merge_refresh_builds.py - merge Phase 1+2 refresh data into canonical build files.

Reads from `data/meta_build/refresh_2026-05-02/{sr,aram,arena}_{top30,next30}.json`
and writes back to:
- `data/meta_build/aram_champion_builds.json` (existing - overwrite per-champ)
- `data/meta_build/sr_champion_builds.json` (existing 18 entries - expand)
- `data/meta_build/arena_champion_builds.json` (NEW)

Strategy:
- For each champion present in refresh files, replace the entry in canonical.
- Preserve fields from existing canonical that aren't in refresh (kit_notes /
  aram_specific carry forward if not in new data).
- Set _note + _refresh_metadata on each canonical file with patch + provenance.
- Don't touch champions absent from refresh (Phase 3 tier-only handles those).

Usage:
    python scripts/merge_refresh_builds.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
REFRESH_DIR = ROOT / "data" / "meta_build" / "refresh_2026-05-02"
META_BUILD = ROOT / "data" / "meta_build"

PATCH = "26.9"
TODAY = "2026-05-03"


def load_refresh(phase_file: str) -> dict:
    p = REFRESH_DIR / phase_file
    if not p.exists():
        return {"champions": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def merge_champ(existing: dict, refresh: dict) -> dict:
    """Merge new refresh entry over existing. Refresh wins on overlap;
    existing fills in any keys not present in refresh."""
    if not isinstance(existing, dict):
        return refresh
    merged = dict(existing)
    merged.update(refresh)
    # Carry forward kit_notes if refresh has none
    for carry in ("kit_notes", "aram_specific", "build_note"):
        if not merged.get(carry) and existing.get(carry):
            merged[carry] = existing[carry]
    return merged


def merge_aram(dry_run: bool = False) -> tuple[int, int]:
    canonical_path = META_BUILD / "aram_champion_builds.json"
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    new_count = updated_count = 0
    for phase in ("aram_top30.json", "aram_next30.json", "aram_tail.json"):
        ref = load_refresh(phase)
        for name, entry in (ref.get("champions") or {}).items():
            if name in canonical:
                canonical[name] = merge_champ(canonical[name], entry)
                updated_count += 1
            else:
                canonical[name] = entry
                new_count += 1
    canonical["_note"] = (
        f"ARAM builds for full champion roster. Patch {PATCH} / Season 16. "
        f"Updated {TODAY} (s33 phase merge - {updated_count + new_count} "
        f"champions refreshed via aggregator K + aggregator A primary sources)."
    )
    canonical["_refresh_metadata"] = {
        "patch": PATCH, "merged_at": TODAY,
        "phases_merged": ["top30", "next30"],
        "updated": updated_count, "new": new_count,
    }
    if not dry_run:
        canonical_path.write_text(
            json.dumps(canonical, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return updated_count, new_count


def merge_sr(dry_run: bool = False) -> tuple[int, int]:
    canonical_path = META_BUILD / "sr_champion_builds.json"
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    new_count = updated_count = 0
    for phase in ("sr_top30.json", "sr_next30.json", "sr_tail.json"):
        ref = load_refresh(phase)
        for name, entry in (ref.get("champions") or {}).items():
            if name in canonical:
                canonical[name] = merge_champ(canonical[name], entry)
                updated_count += 1
            else:
                canonical[name] = entry
                new_count += 1
    canonical["_note"] = (
        f"SR builds. Patch {PATCH} / Season 16. Updated {TODAY} "
        f"(s33 phase merge - {updated_count + new_count} champions refreshed "
        f"via aggregator A primary)."
    )
    canonical["_refresh_metadata"] = {
        "patch": PATCH, "merged_at": TODAY,
        "phases_merged": ["top30", "next30"],
        "updated": updated_count, "new": new_count,
    }
    if not dry_run:
        canonical_path.write_text(
            json.dumps(canonical, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return updated_count, new_count


def merge_arena(dry_run: bool = False) -> tuple[int, int]:
    """Arena gets a NEW canonical file - no existing data to preserve.
    Builds from refresh data only."""
    canonical_path = META_BUILD / "arena_champion_builds.json"
    canonical: dict = {}
    new_count = 0
    for phase in ("arena_top30.json", "arena_next30.json", "arena_tail.json"):
        ref = load_refresh(phase)
        for name, entry in (ref.get("champions") or {}).items():
            if name not in canonical:
                canonical[name] = entry
                new_count += 1
            else:
                # Phase 1 wins on overlap (Phase 2 was retries - Phase 1
                # had multi-source verification)
                pass
    canonical["_note"] = (
        f"Arena (2v2v2v2 / Cherry mode) builds. Patch {PATCH} / Arena Season 2. "
        f"Authored {TODAY} (s33). Schema differs from SR/ARAM: uses "
        f"ideal_core_priority + prismatic_priority instead of full_build "
        f"because anvil RNG dictates acquisition. {new_count} champions captured."
    )
    canonical["_refresh_metadata"] = {
        "patch": PATCH, "season": "Arena Season 2",
        "merged_at": TODAY,
        "phases_merged": ["top30", "next30"],
        "new": new_count,
        "schema_note": (
            "Arena uses ideal_core_priority + prismatic_priority + "
            "build_changing_augments + best_duos + arena_meta. No linear "
            "full_build because anvils are random. Arena-only items "
            "(Hexoptics C44, Reaper's Toll, Goliath, Mystic Punch, etc.) "
            "are valid here."
        ),
    }
    if not dry_run:
        canonical_path.write_text(
            json.dumps(canonical, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return 0, new_count


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    print(f"=== merge_refresh_builds.py (dry_run={dry_run}) ===")
    print()

    aram_u, aram_n = merge_aram(dry_run)
    print(f"ARAM: {aram_u} updated, {aram_n} new")

    sr_u, sr_n = merge_sr(dry_run)
    print(f"SR:   {sr_u} updated, {sr_n} new")

    arena_u, arena_n = merge_arena(dry_run)
    print(f"Arena: {arena_u} updated, {arena_n} new (NEW canonical file)")

    print()
    print("Done." if not dry_run else "Dry-run complete; no files written.")


if __name__ == "__main__":
    main()
