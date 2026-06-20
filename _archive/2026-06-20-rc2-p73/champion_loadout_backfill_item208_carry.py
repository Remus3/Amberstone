"""tools/champion_loadout_backfill_item208_carry.py

Item 208 carry (2026-06-10) - one-shot backfill for the ranged-ADC
carry-path pollution that predates the carry-branch ranged gate in
core.daemon_slayer_client.rank_for_primary_archetype.

The gate stops FUTURE regens from emitting Trinity Force /
Bastionbreaker / Heartsteel / Umbral Glaive on carry rows of ranged
(attackrange >= 350) champions; this tool recovers the rows already
written to data/champion_loadouts.json (Data Fixes rule: a pollution fix
is not done until corrupted rows are backfilled). Removal is surgical -
regenerating via the live engine would rewrite far more than the
polluted rows and depends on engine availability - and rows that drop
below 4 items are refilled offline from the item-213 per-archetype
pools (with the four polluters excluded) so the item-213 thinness pin
(tests/test_loadout_pollution_cleanup_item213.py test_c) keeps holding.

Scope mirrors the guard test exactly: carry-context rows only (resolved
via tools.champion_loadout_align._detect_archetype so tool, test and
regen pipeline share one archetype mapping), ranged champions only.
Melee carries (Nilah 225) and Pantheon's operator-pinned Sup Roam
Umbral Glaive (175) are untouched by construction of the range gate;
bruiser/assassin rows of ranged champs (Kalista/Twitch arena bruiser,
Lucian/Samira sr-assassin) are out of scope - melee items are
archetype-legitimate there.

Usage::

    C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/champion_loadout_backfill_item208_carry.py [--dry-run]
        [--no-backup]
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

_MODE_POOLS = {"sr": _BACKFILL_SR, "aram": _BACKFILL_ARAM, "arena": _BACKFILL_ARENA}

# Operator-pinned rows the backfill must not touch (single source:
# ITEM208_OPERATOR_PINNED_CARRY_ROWS in the item-213 tool). Corki's SR
# "ad" path was hand-fixed by item 269 with Trinity Force deliberately
# at the core slot and that state is test-pinned
# (tests/test_loadout_fix_sibling_pollution_item269.py). A hand-curation
# is not generated pollution; same principle as Pantheon's Sup Roam
# Umbral Glaive pin. The guard test carries the matching exemption.
OPERATOR_PINNED_ROWS: frozenset = ITEM208_OPERATOR_PINNED_CARRY_ROWS


def _mode_of(variant_key: str, v: dict) -> str:
    for m in ("sr", "aram", "arena"):
        if variant_key.startswith(m) or m in [
            str(x).lower() for x in (v.get("modes") or [])
        ]:
            return m
    return ""


class _Refiller:
    """Offline refill that rides the item-213 Cleaner pools/filters so the
    recovered rows stay coherent with the established cleanup pass."""

    def __init__(self) -> None:
        self._cleaner = Cleaner()

    def refill(self, items: list[str], mode: str,
               sibling_sets: set[frozenset]) -> list[str]:
        if mode not in _MODE_POOLS:
            return items
        items = self._cleaner._backfill(
            list(items), mode, "carry",
            skip_names=CARRY_RANGED_OFFCLASS_ITEM_NAMES,
        )
        # The item-213 dedup pin (test_b) forbids two identical item lists
        # within one variant - diversify with the next eligible pool entry
        # when the refill happens to converge on a sibling path.
        pool = _MODE_POOLS[mode].get("carry") or []
        for cand in pool:
            if frozenset(_norm(i) for i in items) not in sibling_sets:
                break
            if cand in CARRY_RANGED_OFFCLASS_ITEM_NAMES:
                continue
            cn = _norm(cand)
            if cn in {_norm(i) for i in items}:
                continue
            if not _on_map(self._cleaner.item_idx, cand, mode):
                continue
            fam = self._cleaner.fam.get(
                cn.replace(" ", "").replace("'", "").replace("-", "")
            )
            if fam and fam in self._cleaner._families_in(items):
                continue
            items.append(cand)
        return items

    def reseat_boots(self, champ: str, mode: str, items: list[str]) -> list[str]:
        return self._cleaner._reseat_boots(champ, mode, items, "carry")


def _clean(items: list) -> tuple[list, list]:
    kept = [i for i in items if i not in CARRY_RANGED_OFFCLASS_ITEM_NAMES]
    removed = [i for i in items if i in CARRY_RANGED_OFFCLASS_ITEM_NAMES]
    return kept, removed


def backfill(payload: dict) -> tuple[dict, list[tuple[str, str, list, int]]]:
    """Return (payload, changes). Each change is
    (champion, row_key, removed_items, items_after). Mutates in place."""
    refiller = _Refiller()
    changes: list[tuple[str, str, list, int]] = []
    for champ, entry in (payload.get("champions") or {}).items():
        if not isinstance(entry, dict):
            continue
        if champion_attackrange(champ) < CARRY_RANGED_ATTACKRANGE_FLOOR:
            continue
        for vk, v in (entry.get("variants") or {}).items():
            if not isinstance(v, dict):
                continue
            mode = _mode_of(vk, v)
            if v.get("_collapsed"):
                paths = [p for p in (v.get("build_paths") or [])
                         if isinstance(p, dict)]
                primary_carry_cleaned = False
                for i, p in enumerate(paths):
                    pk = str(p.get("key") or "")
                    if (champ, vk, pk) in OPERATOR_PINNED_ROWS:
                        continue
                    if _detect_archetype(pk, p) != "carry":
                        continue
                    kept, removed = _clean(list(p.get("items") or []))
                    if not removed:
                        continue
                    if len(kept) < 4:
                        siblings = {
                            frozenset(_norm(x) for x in (q.get("items") or []))
                            for q in paths if q is not p
                        }
                        kept = refiller.refill(kept, mode, siblings)
                    if mode in ("sr", "aram"):
                        # Removing a slot-0 polluter shifts boots to the
                        # head - the meta-conformance pin wants boots at
                        # the canonical index 1.
                        kept = refiller.reseat_boots(champ, mode, kept)
                    p["items"] = kept
                    changes.append((champ, f"{vk}/{pk}", removed, len(kept)))
                    if i == 0:
                        primary_carry_cleaned = True
                # The collapsed entry's own items mirror the primary path -
                # re-sync the mirror when the primary was recovered.
                if primary_carry_cleaned:
                    old = list(v.get("items") or [])
                    new = list(paths[0].get("items") or [])
                    if old != new:
                        v["items"] = new
                        removed = [
                            x for x in old
                            if x in CARRY_RANGED_OFFCLASS_ITEM_NAMES
                        ]
                        changes.append(
                            (champ, f"{vk}(items)", removed, len(new))
                        )
            else:
                if _detect_archetype(vk, v) != "carry":
                    continue
                kept, removed = _clean(list(v.get("items") or []))
                if not removed:
                    continue
                if len(kept) < 4:
                    kept = refiller.refill(kept, mode, set())
                if mode in ("sr", "aram"):
                    kept = refiller.reseat_boots(champ, mode, kept)
                v["items"] = kept
                changes.append((champ, vk, removed, len(kept)))
    return payload, changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report removals without writing.")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip the .bak-item208carry-<ts> snapshot.")
    args = parser.parse_args(argv)

    if not _LOADOUTS_PATH.exists():
        print(f"ERROR: {_LOADOUTS_PATH} not found", file=sys.stderr)
        return 2

    payload = json.loads(_LOADOUTS_PATH.read_text(encoding="utf-8"))
    payload, changes = backfill(payload)

    for champ, row, removed, after in changes:
        print(f"  {champ:<14} {row:<44} -{removed} ({after} after)")
    champs_touched = len({c for c, _, _, _ in changes})
    thin = [(c, r, n) for c, r, _, n in changes if n < 4]
    print(f"rows recovered: {len(changes)}  champions touched: {champs_touched}")
    if thin:
        print(f"rows still under 4 items ({len(thin)}): {thin}")

    if args.dry_run:
        print("(dry-run; no write)")
        return 0
    if not changes:
        print("nothing to do")
        return 0

    if not args.no_backup:
        ts = time.strftime("%Y%m%d-%H%M%S")
        bak = _LOADOUTS_PATH.with_name(
            f"{_LOADOUTS_PATH.name}.bak-item208carry-{ts}"
        )
        shutil.copy2(_LOADOUTS_PATH, bak)
        print(f"backup written: {bak.name}")

    # Atomic write per the repo hard rule - overlays poll mid-write.
    tmp = _LOADOUTS_PATH.with_suffix(".json.tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=False)
    tmp.write_text(text + "\n", encoding="utf-8", newline="\n")
    tmp.replace(_LOADOUTS_PATH)
    print(f"wrote: {_LOADOUTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
