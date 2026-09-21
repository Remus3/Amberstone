"""Item Ability-Haste registry drift-check (DDragon truth vs engine pin).

The engine's `_item_ability_haste._ITEM_ABILITY_HASTE` is hand-pinned (220
items) and has no committed regen tool. This probe re-derives the AH dict
from the live DDragon item.json (the current patch, resolved from
current.txt) using the documented parse (`<attention>N</attention> Ability
Haste` inside the leading `<stats>` block) and diffs it against the engine
pin, so drift surfaces as a concrete add/remove/change list.

Coverage is classified, never silently skipped. Every AH line in a `<stats>`
block lands in exactly one bucket:

  * buyable        - `<attention>N</attention> Ability Haste` on a non-Ornn
                     item; this is the set diffed against the pin.
  * ornn_excluded  - an Ornn masterwork (any `<ornnBonus>` tag in its
                     description, the same marker as
                     agents/daemon_slayer/rank.py `_is_ornn_masterwork`),
                     whose AH usually sits in `<ornnBonus>N</ornnBonus>`.
                     Masterworks are never purchasable, are excluded from
                     recommendations, and must NOT gain registry rows; they
                     are reported as EXCLUDED BY DESIGN. (The pre-fix parse
                     matched `<attention>` only, so these were invisible and
                     the IN SYNC verdict was blind to them.)
  * unparsed       - an AH line neither arm understands (a new tag shape);
                     this FAILS the check so a future format cannot hide.

Read-only. Exit 0 = in sync, exit 1 = drift or unparsed AH lines (prints the
diff).

    python ops/audit/item_ah_drift_check.py [<ddragon item.json path>]
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_CURRENT_TXT = ROOT / "data" / "daemon_slayer" / "current.txt"


def _default_item_json() -> Path:
    """The live-patch DDragon item.json, resolved from current.txt.

    Previously hardcoded to 16.12.1 - a blind default that false-reported
    IN SYNC because it never tracked the live patch, so the 226692 Eclipse
    Arena-mirror drift (introduced 16.13.1) went uncaught until the 16.14.1
    refresh audit. Resolving current.txt keeps the no-arg guard honest.
    """
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    return ROOT / "data" / "meta_build" / "ddragon" / patch / "item.json"


_STATS_BLOCK = re.compile(r"<stats>(.*?)</stats>", re.S)
_AH = re.compile(r"<attention>([0-9.]+)</attention>\s*Ability Haste")
_AH_ORNN = re.compile(r"<(?:ornnBonus|attention)>([0-9.]+)</(?:ornnBonus|attention)>\s*Ability Haste")
_AH_ANY = re.compile(r"Ability Haste")
_ORNN_MARKER = "<ornnBonus>"


@dataclass
class AhClassification:
    buyable: dict[str, float] = field(default_factory=dict)
    ornn_excluded: dict[str, float] = field(default_factory=dict)
    unparsed: list[str] = field(default_factory=list)


def classify_ddragon(item_json: Path) -> AhClassification:
    """Bucket every AH-bearing <stats> block: buyable / ornn_excluded / unparsed."""
    blob = json.loads(item_json.read_text(encoding="utf-8"))
    out = AhClassification()
    for iid, it in blob["data"].items():
        desc = it.get("description", "") or ""
        m = _STATS_BLOCK.search(desc)
        if not m or not _AH_ANY.search(m.group(1)):
            continue
        block = m.group(1)
        if _ORNN_MARKER in desc:
            ah = _AH_ORNN.search(block)
            if ah:
                out.ornn_excluded[iid] = float(ah.group(1))
                continue
        else:
            ah = _AH.search(block)
            if ah:
                out.buyable[iid] = float(ah.group(1))
                continue
        out.unparsed.append(iid)
    out.unparsed.sort(key=int)
    return out


def derive_from_ddragon(item_json: Path) -> dict[str, float]:
    """Flat AH of every BUYABLE (non-Ornn) item - the set the pin is diffed against."""
    return classify_ddragon(item_json).buyable


def _load_pin() -> dict[str, float]:
    sys.path.insert(0, str(ROOT / "agents" / "daemon_slayer"))
    from _item_ability_haste import _ITEM_ABILITY_HASTE  # type: ignore

    return dict(_ITEM_ABILITY_HASTE)


def main() -> int:
    item_json = Path(sys.argv[1]) if len(sys.argv) > 1 else _default_item_json()
    if not item_json.exists():
        print(f"NO DDragon item.json at {item_json}", file=sys.stderr)
        return 2

    pinned = _load_pin()
    cls = classify_ddragon(item_json)
    derived = cls.buyable
    blob = json.loads(item_json.read_text(encoding="utf-8"))
    names = {k: v.get("name", "?") for k, v in blob["data"].items()}

    pinned_ids = set(pinned)
    derived_ids = set(derived)

    added = sorted(derived_ids - pinned_ids, key=int)      # in DDragon, not in pin
    removed = sorted(pinned_ids - derived_ids, key=int)     # in pin, not in DDragon
    changed = sorted(
        (i for i in pinned_ids & derived_ids if pinned[i] != derived[i]), key=int
    )

    print(f"DDragon {blob.get('version')}: {len(derived)} buyable AH items "
          f"| engine pin: {len(pinned)} items "
          f"| Ornn masterwork AH items excluded by design: {len(cls.ornn_excluded)} "
          f"| unparsed AH lines: {len(cls.unparsed)}")
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
    if cls.ornn_excluded:
        print("\n-- EXCLUDED BY DESIGN (Ornn masterwork, never purchasable; no registry row) --")
        for i in sorted(cls.ornn_excluded, key=int):
            print(f"  {i:>7} {names.get(i,'?'):32} DDragon={cls.ornn_excluded[i]}")
    if cls.unparsed:
        print("\n-- UNPARSED (Ability Haste line neither arm understands) --")
        for i in cls.unparsed:
            print(f"  {i:>7} {names.get(i,'?')}")

    drift = bool(added or removed or changed or cls.unparsed)
    print("\nRESULT:", "DRIFT" if drift else "IN SYNC",
          f"({len(derived_ids & pinned_ids)}/{len(pinned)} buyable, "
          f"{len(cls.ornn_excluded)} Ornn excluded by design)")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
