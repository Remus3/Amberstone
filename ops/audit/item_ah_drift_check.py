"""Item Ability-Haste registry drift-check (DDragon truth vs engine pin).

The engine's `_item_ability_haste._ITEM_ABILITY_HASTE` is hand-pinned at
patch 16.10.1 (220 items) and has no committed regen tool. Live patch is
16.12.1. This probe re-derives the AH dict from the live DDragon item.json
using the documented parse (`<attention>N</attention> Ability Haste` inside
the leading `<stats>` block) and diffs it against the engine pin, so a
two-patch drift surfaces as a concrete add/remove/change list.

Read-only. Exit 0 = in sync, exit 1 = drift found (prints the diff).

    python ops/audit/item_ah_drift_check.py [<ddragon item.json path>]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ITEM_JSON = ROOT / "data" / "meta_build" / "ddragon" / "16.12.1" / "item.json"

_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.S)
_AH = re.compile(r"<attention>([0-9.]+)</attention>\s*Ability Haste")


def derive_from_ddragon(item_json: Path) -> dict[str, float]:
    """Parse flat AH from the leading <stats> block of each DDragon item."""
    blob = json.loads(item_json.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for iid, it in blob["data"].items():
        desc = it.get("description", "") or ""
        m = _STATS_BLOCK.search(desc)
        if not m:
            continue
        ah = _AH.search(m.group(1))
        if ah:
            out[iid] = float(ah.group(1))
    return out


def main() -> int:
    item_json = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ITEM_JSON
    if not item_json.exists():
        print(f"NO DDragon item.json at {item_json}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(ROOT / "agents" / "daemon_slayer"))
    from _item_ability_haste import _ITEM_ABILITY_HASTE as pinned  # type: ignore

    derived = derive_from_ddragon(item_json)
    blob = json.loads(item_json.read_text(encoding="utf-8"))
    names = {k: v.get("name", "?") for k, v in blob["data"].items()}

    pinned_ids = set(pinned)
    derived_ids = set(derived)

    added = sorted(derived_ids - pinned_ids, key=int)      # in DDragon, not in pin
    removed = sorted(pinned_ids - derived_ids, key=int)     # in pin, not in DDragon
    changed = sorted(
        (i for i in pinned_ids & derived_ids if pinned[i] != derived[i]), key=int
    )

    print(f"DDragon {blob.get('version')}: {len(derived)} AH items "
          f"| engine pin: {len(pinned)} items")
    print(f"added={len(added)} removed={len(removed)} changed={len(changed)}")

    if added:
        print("\n-- ADDED (DDragon has AH, engine pin missing) --")
        for i in added:
            print(f"  {i:>7} {names.get(i,'?'):32} DDragon={derived[i]}")
    if removed:
        print("\n-- REMOVED (engine pin has AH, DDragon dropped) --")
        for i in removed:
            print(f"  {i:>7} {names.get(i,'?'):32} pin={pinned[i]}")
    if changed:
        print("\n-- CHANGED (value drift) --")
        for i in changed:
            print(f"  {i:>7} {names.get(i,'?'):32} pin={pinned[i]} -> DDragon={derived[i]}")

    drift = bool(added or removed or changed)
    print("\nRESULT:", "DRIFT" if drift else "IN SYNC")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
