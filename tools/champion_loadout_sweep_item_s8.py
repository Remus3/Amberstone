"""tools/champion_loadout_sweep_item_s8.py

Item s8 (2026-06-10) - 6-axis full-roster loadout pollution + length
sweep over data/champion_loadouts.json.

Operator directive (verbatim intent): "run a 6 axis / all champion
loadout pollution sweep, where it should also always be 7 items in the
builds for SR and 6 items in the builds for aram & arena. there are many
champion loadouts that are truncated or wrong."

Two passes per build_path row (every champion x sr/aram/arena x every
path), then the variant-level ``items`` mirror is resynced to the
primary path:

1. AXIS PASS - strip unambiguous off-class items per the conservative
   per-archetype rules in tools/champion_loadout_invariants.classify_row
   (carry range gate incl. Divine Sunderer; marksman-class items on
   AP-majority mage/enchanter rows; pure-offense crit on tank rows;
   heal/shield-power on assassin rows; stat-stick tank items on
   enchanter rows). Ambiguous candidates (e.g. coherent AD builds whose
   key token-maps to "mage" - Ashe lethal-poke) are REPORTED, never
   touched. Operator pins (Corki SR "ad" Trinity Force) are exempt.

2. LENGTH PASS - every row is shaped to the exact per-mode build length
   (TARGET_LEN: SR 7 / ARAM 6 / Arena 6) via the shared item-213
   Cleaner: boots reseated at index 1 on SR/ARAM (none on Arena /
   bootsless champs), short rows refilled from the deepened per-
   archetype pools (offline, unique-family-clash aware, carry-gate skip
   names honored), overlong rows tail-trimmed. If a refill converges on
   a sibling path's item set, the tail is diversified with the next
   eligible pool entry (the item-213 no-duplicate-paths pin).

Root-cause companions (same change set): the producers were patched so
a regen keeps both rules - champion_loadout_autogen.build_variant shapes
through the same Cleaner.enforce_length, champion_loadout_align plans
SR at 7 slots and length-enforces ARAM/Arena dedup output, and the
item-213 cleanup itself now refills to TARGET_LEN instead of 4.

Usage::

    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/champion_loadout_sweep_item_s8.py [--dry-run] [--no-backup]

Atomic write (tmp + replace) with a timestamped .bak. Idempotent.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_LOADOUTS_PATH = _ROOT / "data" / "champion_loadouts.json"

from core.daemon_slayer_client import (  # noqa: E402
    CARRY_RANGED_ATTACKRANGE_FLOOR,
    CARRY_RANGED_OFFCLASS_ITEM_NAMES,
    champion_attackrange,
)
from tools.champion_loadout_align import _detect_archetype  # noqa: E402
from tools.champion_loadout_cleanup_pollution_item213 import (  # noqa: E402
    _BACKFILL_ARAM,
    _BACKFILL_ARENA,
    _BACKFILL_SR,
    _norm,
    _on_map,
    Cleaner,
    ITEM208_OPERATOR_PINNED_CARRY_ROWS,
)
from tools.champion_loadout_invariants import (  # noqa: E402
    TARGET_LEN,
    classify_row,
)

_MODE_POOLS = {
    "sr": _BACKFILL_SR, "aram": _BACKFILL_ARAM, "arena": _BACKFILL_ARENA,
}


def _mode_of(variant_key: str) -> str:
    for m in ("sr", "aram", "arena"):
        if m in variant_key:
            return m
    return ""


class Sweep:
    def __init__(self) -> None:
        self.cleaner = Cleaner()
        self.rows_scanned = 0
        self.refilled = 0
        self.trimmed = 0
        self.stripped_by_axis: dict[str, int] = {}
        self.skipped_pinned = 0
        self.ambiguous: list[str] = []
        self.diversified = 0
        self.mirrors_resynced = 0
        self.failed_target: list[str] = []

    def _diversify(
        self, items: list[str], mode: str, archetype: str,
        sibling_sets: set[frozenset], skip_names: frozenset,
    ) -> list[str]:
        """Swap the tail item for the next eligible pool entry while the
        shaped row duplicates a sibling path (item-213 test_b pin)."""
        pool = (
            _MODE_POOLS[mode].get(archetype)
            or _MODE_POOLS[mode].get("carry") or []
        )
        for cand in pool:
            if frozenset(_norm(i) for i in items) not in sibling_sets:
                break
            if cand in skip_names:
                continue
            cn = _norm(cand)
            if cn in {_norm(i) for i in items}:
                continue
            if not _on_map(self.cleaner.item_idx, cand, mode):
                continue
            fam = self.cleaner.fam.get(
                cn.replace(" ", "").replace("'", "").replace("-", "")
            )
            if fam and fam in self.cleaner._families_in(items[:-1]):
                continue
            items = items[:-1] + [cand]
            self.diversified += 1
        return items

    def sweep_variant(self, champ: str, vk: str, v: dict) -> None:
        mode = _mode_of(vk)
        if mode not in TARGET_LEN:
            return
        target = TARGET_LEN[mode]
        rng = champion_attackrange(champ)
        paths = [p for p in (v.get("build_paths") or []) if isinstance(p, dict)]
        seen_sets: set[frozenset] = set()
        for p in paths:
            pk = str(p.get("key") or "")
            arch = _detect_archetype(pk, p)
            pinned = (champ, vk, pk) in ITEM208_OPERATOR_PINNED_CARRY_ROWS
            items = [str(i) for i in (p.get("items") or [])]
            self.rows_scanned += 1
            before_len = len(items)

            gate_carry = (
                arch == "carry"
                and rng >= CARRY_RANGED_ATTACKRANGE_FLOOR
            )
            skip = (
                CARRY_RANGED_OFFCLASS_ITEM_NAMES if gate_carry
                else frozenset()
            )

            # Strip + shape to FIXPOINT inside one run: a refill can tip
            # a mage row into AP-majority, making a stray that was
            # ambiguous before the refill unambiguous after it. Without
            # the loop those strays would only fall on a SECOND sweep
            # run (non-idempotent) and the guard would fail post-sweep.
            n_stripped = 0
            for _ in range(5):
                violations = classify_row(
                    champ, mode, arch, items,
                    attackrange=rng, pinned=pinned,
                )
                strip_names = {
                    x.item for x in violations if x.action == "strip"
                }
                if strip_names:
                    items = [i for i in items if i not in strip_names]
                    for x in violations:
                        if x.action == "strip":
                            self.stripped_by_axis[x.axis] = (
                                self.stripped_by_axis.get(x.axis, 0) + 1
                            )
                            n_stripped += 1
                shaped = self.cleaner.enforce_length(
                    champ, mode, arch, items, skip,
                )
                if shaped == items and not strip_names:
                    break
                items = shaped

            # Report ambiguous candidates on the FINAL row state only.
            final_violations = classify_row(
                champ, mode, arch, items, attackrange=rng, pinned=pinned,
            )
            for x in final_violations:
                if x.action == "report":
                    self.ambiguous.append(
                        f"{champ}|{mode}|{pk}|{x.item} [{x.axis}] {x.reason}"
                    )
            if pinned and any(
                x.action == "report" for x in final_violations
            ):
                self.skipped_pinned += 1

            shaped = self._diversify(items, mode, arch, seen_sets, skip)
            seen_sets.add(frozenset(_norm(i) for i in shaped))

            if len(shaped) > max(before_len - n_stripped, 0):
                self.refilled += 1
            elif len(shaped) < before_len - n_stripped:
                self.trimmed += 1
            if len(shaped) != target:
                self.failed_target.append(
                    f"{champ}|{mode}|{pk}: {len(shaped)} != {target}"
                )
            if shaped != p.get("items"):
                p["items"] = shaped

        # The collapsed entry's own items mirror the primary path.
        if paths:
            prim = list(paths[0].get("items") or [])
            if list(v.get("items") or []) != prim:
                v["items"] = prim
                self.mirrors_resynced += 1

    def run(self, payload: dict) -> dict:
        for champ, entry in (payload.get("champions") or {}).items():
            if not isinstance(entry, dict):
                continue
            for vk, v in (entry.get("variants") or {}).items():
                if isinstance(v, dict) and v.get("_collapsed"):
                    self.sweep_variant(champ, vk, v)
        return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    payload = json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))
    sweep = Sweep()
    payload = sweep.run(payload)

    print(f"rows scanned:            {sweep.rows_scanned}")
    print(f"truncated-refilled:      {sweep.refilled}")
    print(f"overlong-trimmed:        {sweep.trimmed}")
    print(f"pollution-stripped/axis: {sweep.stripped_by_axis or '{}'}")
    print(f"skipped-pinned:          {sweep.skipped_pinned}")
    print(f"diversified-tails:       {sweep.diversified}")
    print(f"mirrors-resynced:        {sweep.mirrors_resynced}")
    print(f"ambiguous-reported:      {len(sweep.ambiguous)}")
    for a in sweep.ambiguous:
        print(f"    {a}")
    if sweep.failed_target:
        print(f"FAILED-TARGET rows ({len(sweep.failed_target)}):")
        for f in sweep.failed_target:
            print(f"    {f}")

    if args.dry_run:
        print("[dry-run] no write")
        return 1 if sweep.failed_target else 0

    if not args.no_backup:
        ts = time.strftime("%Y%m%d-%H%M%S")
        bak = _LOADOUTS_PATH.with_name(
            f"{_LOADOUTS_PATH.name}.bak-items8-{ts}"
        )
        shutil.copy2(_LOADOUTS_PATH, bak)
        print(f"backup: {bak.name}")

    # Atomic write per the repo hard rule - overlays poll mid-write.
    tmp = _LOADOUTS_PATH.with_suffix(".json.tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=False)
    tmp.write_text(text + "\n", encoding="utf-8", newline="\n")
    tmp.replace(_LOADOUTS_PATH)
    print(f"wrote: {_LOADOUTS_PATH}")
    return 1 if sweep.failed_target else 0


if __name__ == "__main__":
    raise SystemExit(main())
