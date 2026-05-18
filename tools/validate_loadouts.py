"""
tools/validate_loadouts.py - sanity-check data/champion_loadouts.json.

Walks every champion+variant, runs the resolver, and reports:
  - rune misses (unknown keystone/tree)
  - item name misses (ddragon resolver dropped the name)
  - summoner ID issues
  - mode coverage gaps (champion has no variant for ARAM, no variant for SR)

Run:  python tools/validate_loadouts.py
Exit code 0 = clean, 1 = at least one issue.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Run from project root or anywhere
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from coaches.loadout_resolver import (
    _load_loadouts, _load_items_by_name, _load_champ_id_by_name,
    _norm, resolve, list_variants,
)


def main() -> int:
    loadouts = _load_loadouts().get("champions", {}) or {}
    items_by_name = _load_items_by_name()
    champs_by_name = _load_champ_id_by_name()
    issues = 0
    coverage_gaps = []

    print(f"Validating {len(loadouts)} champions…")
    print("-" * 64)

    for champ, info in sorted(loadouts.items()):
        if champ.startswith("_"):
            continue
        # Champion existence
        if champ not in champs_by_name:
            print(f"  [WARN] {champ}: not in ddragon_champions.json (typo?)")
            issues += 1
        variants = info.get("variants") or {}
        if not variants:
            print(f"  [WARN] {champ}: no variants defined")
            issues += 1
            continue
        # Coverage check
        modes_covered = set()
        for v in variants.values():
            for m in (v.get("modes") or []):
                modes_covered.add(str(m).lower())
        if "aram" not in modes_covered:
            coverage_gaps.append(f"{champ} (no aram variant)")
        if "sr" not in modes_covered:
            coverage_gaps.append(f"{champ} (no sr variant)")

        # Per-variant deep check via resolve()
        for vkey, v in variants.items():
            for mode_key in (v.get("modes") or []):
                resolved = resolve(champ, vkey, str(mode_key))
                if not resolved.get("ok"):
                    print(f"  [FAIL] {champ}/{vkey}/{mode_key}: {resolved.get('err')}")
                    issues += 1
                    continue
                # Rune check
                rune_cmd = resolved.get("rune_cmd")
                if not rune_cmd:
                    print(f"  [FAIL] {champ}/{vkey}/{mode_key}: rune resolution failed "
                          f"(keystone={v.get('runes',{}).get('keystone')!r})")
                    issues += 1
                # Item check - count name misses
                raw = v.get("items") or []
                resolved_ids = []
                for blk in (resolved.get("item_cmd") or {}).get("blocks", []):
                    for it in blk.get("items", []):
                        resolved_ids.append(it.get("id"))
                if len(resolved_ids) < len(raw):
                    misses = [n for n in raw if _norm(n) not in items_by_name]
                    print(f"  [WARN] {champ}/{vkey}/{mode_key}: {len(misses)} item miss(es): "
                          f"{misses}")
                    issues += 1
                # Summoners
                summ = v.get("summoners") or []
                if len(summ) != 2:
                    print(f"  [WARN] {champ}/{vkey}: summoners list != 2: {summ}")
                    issues += 1

    print("-" * 64)
    if coverage_gaps:
        print("Coverage gaps:")
        for g in coverage_gaps:
            print(f"  - {g}")
    print(f"Done. {issues} issue(s).")
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
