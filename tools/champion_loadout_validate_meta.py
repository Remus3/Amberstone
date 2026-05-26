"""Validate + fix item builds in data/champion_loadouts.json per meta conventions.

Item-200 Slice A migration tool. Sister to ``tools/champion_loadout_align.py``
(item 167) which regenerates SR via the DS engine, and to
``tools/migrate_carry_summoners_flash_barrier.py`` (item 169) which flipped
SR carry [4,7] -> [4,21].

Invariants enforced (one per ``build_path``):

  SR + ARAM (non-bootsless):
    * exactly ONE boots item present
    * boots at ``items[1]`` (after the first core item, mirrors the DS engine
      injector at ``core.build_order._select_boots`` post-engine_call_i==1)

  Arena (all champions):
    * NO boots (Cherry mode has no boot shop)

  Bootsless champions (Yuumi, Cassiopeia, per
  ``core.build_order._BOOTSLESS_CHAMPS``):
    * NO boots in any mode

Drift action: leftmost ``BOOTS`` token moved to ``items[1]`` by index swap; for
bootsless drift, every boots token is removed.

Atomic write: tmp.write_text + tmp.replace; backup at
``data/champion_loadouts.json.bak-slice-a-<UTC-stamp>`` BEFORE edit.

Re-running on already-conformant data is a no-op (return code 0, "0 fixes").
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Display names that resolve to one of the 8 boots IDs in
# ``core.build_order._BOOTS_IDS`` ({3006,3009,3010,3020,3047,3111,3117,3158}).
# Kept as display-name strings because ``data/champion_loadouts.json``
# build_paths use display names (per items 178/179 collapse). The list also
# includes a few mythic-tier boot upgrades (Symbiotic Soles / Synchronized
# Souls / Slightly Magical Footwear) that resolve via the same loadout_resolver
# normalizer; harmless if absent.
_BOOTS_DISPLAY_NAMES: frozenset[str] = frozenset({
    "Berserker's Greaves",
    "Boots of Swiftness",
    "Plated Steelcaps",
    "Mercury's Treads",
    "Sorcerer's Shoes",
    "Ionian Boots of Lucidity",
    "Mobility Boots",
    "Symbiotic Soles",
    "Synchronized Souls",
    "Slightly Magical Footwear",
})

# Champions that never buy boots (Yuumi rides her bonded ally; Cassiopeia
# passive gains MS in lieu of boots). Pinned in
# ``core.build_order._BOOTSLESS_CHAMPS``.
_BOOTSLESS_CHAMPS: frozenset[str] = frozenset({"Yuumi", "Cassiopeia"})

_MODE_VARIANT_KEYS: tuple[str, ...] = (
    "sr-collapsed",
    "aram-collapsed",
    "arena-collapsed",
)


def _norm(name: str) -> str:
    """Strip to lowercase alphanumeric. Mirrors
    ``coaches.loadout_resolver._norm`` so name comparisons match the same
    fuzzy contract the resolver uses to map display names to ddragon IDs."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


_BOOTS_NORM: frozenset[str] = frozenset(_norm(n) for n in _BOOTS_DISPLAY_NAMES)


def _scan_drift(loadouts: dict) -> list[dict]:
    """Walk every champion x mode_variant x build_path. Return list of drift
    records with shape ``{champion, mode, path_key, kind, boots_positions,
    items_before, items_after}``. ``items_after`` is the proposed fix.

    Drift kinds:
      ``BOOTS_AT_INDEX_N``  - boots present but NOT at items[1] (only for
                              SR/ARAM non-bootsless paths)
      ``NO_BOOTS``          - SR/ARAM non-bootsless path missing boots
      ``MULTIPLE_BOOTS``    - more than one boots token in the same path
      ``BOOTSLESS_HAS_BOOTS`` - Yuumi/Cassiopeia path carrying boots
      ``ARENA_HAS_BOOTS``   - Arena path carrying boots (Cherry has no shop)
    """
    drift: list[dict] = []
    champs = (loadouts or {}).get("champions") or {}
    for cname, cdef in sorted(champs.items()):
        variants = (cdef or {}).get("variants") or {}
        is_bootsless = cname in _BOOTSLESS_CHAMPS
        for mode_var in _MODE_VARIANT_KEYS:
            v = variants.get(mode_var)
            if not v:
                continue
            is_arena = (mode_var == "arena-collapsed")
            for p in v.get("build_paths") or []:
                items = list(p.get("items") or [])
                key = p.get("key", "?")
                items_norm = [_norm(x) for x in items]
                boots_positions = [
                    i for i, n in enumerate(items_norm) if n in _BOOTS_NORM
                ]
                rec_base = {
                    "champion": cname,
                    "mode": mode_var,
                    "path_key": key,
                    "boots_positions": boots_positions,
                    "items_before": list(items),
                }
                if is_arena:
                    if boots_positions:
                        rec_base["kind"] = "ARENA_HAS_BOOTS"
                        rec_base["items_after"] = [
                            it for i, it in enumerate(items)
                            if i not in boots_positions
                        ]
                        drift.append(rec_base)
                elif is_bootsless:
                    if boots_positions:
                        rec_base["kind"] = "BOOTSLESS_HAS_BOOTS"
                        rec_base["items_after"] = [
                            it for i, it in enumerate(items)
                            if i not in boots_positions
                        ]
                        drift.append(rec_base)
                else:
                    # SR / ARAM non-bootsless: boots required at items[1]
                    if not boots_positions:
                        rec_base["kind"] = "NO_BOOTS"
                        rec_base["items_after"] = list(items)  # cannot auto-add
                        drift.append(rec_base)
                    elif boots_positions[0] != 1:
                        bp = boots_positions[0]
                        new_items = list(items)
                        new_items[1], new_items[bp] = new_items[bp], new_items[1]
                        rec_base["kind"] = f"BOOTS_AT_INDEX_{bp}"
                        rec_base["items_after"] = new_items
                        drift.append(rec_base)
                    elif len(boots_positions) > 1:
                        rec_base["kind"] = "MULTIPLE_BOOTS"
                        # Keep only first boots
                        new_items = [
                            it for i, it in enumerate(items)
                            if i == boots_positions[0]
                            or i not in boots_positions
                        ]
                        rec_base["items_after"] = new_items
                        drift.append(rec_base)
    return drift


def _apply_fixes(loadouts: dict, drift: list[dict]) -> int:
    """Apply each drift record's ``items_after`` into the in-place loadouts
    dict. Returns count of paths mutated."""
    n = 0
    champs = loadouts["champions"]
    for rec in drift:
        cname = rec["champion"]
        mode = rec["mode"]
        path_key = rec["path_key"]
        kind = rec["kind"]
        if kind == "NO_BOOTS":
            # Cannot auto-fix: do not mutate. The drift guard surfaces it for
            # operator action.
            continue
        v = champs[cname]["variants"][mode]
        for p in v["build_paths"]:
            if p.get("key") == path_key:
                p["items"] = list(rec["items_after"])
                n += 1
                break
    return n


def _atomic_write(target: Path, payload: dict) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    txt = json.dumps(payload, indent=2, ensure_ascii=True)
    tmp.write_text(txt + "\n", encoding="ascii")
    tmp.replace(target)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Scan + report; do not write the JSON or backup.",
    )
    ap.add_argument(
        "--no-backup", action="store_true",
        help="Skip the .bak-slice-a-<stamp> backup before atomic write.",
    )
    args = ap.parse_args()

    with _LOADOUTS.open("r", encoding="utf-8") as f:
        loadouts = json.load(f)

    drift = _scan_drift(loadouts)
    if not drift:
        print("0 drift sites; no fixes needed.")
        return 0

    # Print summary table
    from collections import Counter
    by_mode = Counter(r["mode"] for r in drift)
    by_kind = Counter(r["kind"] for r in drift)
    print(f"Drift sites: {len(drift)}")
    print(f"  by mode:  {dict(by_mode)}")
    print(f"  by kind:  {dict(by_kind)}")
    print()
    # First 5 examples
    for r in drift[:5]:
        print(
            f"  {r['champion']} {r['mode']}/{r['path_key']} {r['kind']}"
        )
        print(f"    OLD: {r['items_before']}")
        print(f"    NEW: {r['items_after']}")
    if len(drift) > 5:
        print(f"  ... {len(drift) - 5} more")
    print()

    if args.dry_run:
        print("dry-run: not writing.")
        return 0

    # Backup
    if not args.no_backup:
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = _LOADOUTS.with_suffix(f".json.bak-slice-a-{stamp}")
        bak.write_text(
            json.dumps(loadouts, indent=2, ensure_ascii=True) + "\n",
            encoding="ascii",
        )
        print(f"Backup: {bak.name}")

    n = _apply_fixes(loadouts, drift)
    _atomic_write(_LOADOUTS, loadouts)
    print(f"Applied {n} fixes. Wrote {_LOADOUTS.name}.")

    # Re-scan to confirm
    with _LOADOUTS.open("r", encoding="utf-8") as f:
        after = json.load(f)
    residual = _scan_drift(after)
    if residual:
        # Surface any non-NO_BOOTS residual (NO_BOOTS is operator-action drift)
        non_no_boots = [r for r in residual if r["kind"] != "NO_BOOTS"]
        if non_no_boots:
            print(f"WARNING: {len(non_no_boots)} residual drift sites post-fix:")
            for r in non_no_boots[:3]:
                print(f"  {r['champion']} {r['mode']}/{r['path_key']} {r['kind']}")
            return 2
        print(
            f"Residual (operator-action): {len(residual)} NO_BOOTS sites "
            "(cannot auto-add)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
