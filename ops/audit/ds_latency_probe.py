# arch: DS build-opt latency probe | section=ops/audit | frozen=no
"""Measure-first gate (2026-06-30 deep-research critic recommendation).

Times the two live build-optimization paths in-process to decide whether ANY
warm-start / cache / surrogate work is justified BEFORE building it:
  - beam_search_build COLD (no seed, fills 6 slots) vs SEED3 (3 items pinned).
    The ONLY live beam consumer is SR champ-select (coaches/sr_draft_profile.py).
  - rank_items greedy single-slot - the path /api/ds-knobs + /api/ds-preview +
    coach-dispatch actually use (NOT the beam).

Decision rule: if p95 for every path is under an interactive budget (~100ms),
the "build-opt latency hurts" premise is false and no warm-start work is
warranted. Pure local, no :8893, no network.

Run: $env:LOCALAPPDATA/Programs/Python/Python314/python.exe ops/audit/ds_latency_probe.py
"""
from __future__ import annotations

import math
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: E402
from agents.daemon_slayer.beam import beam_search_build  # noqa: E402
from agents.daemon_slayer.rank import rank_items  # noqa: E402

CHAMPS = ["Caitlyn", "Jinx", "Aatrox", "Leona", "Syndra"]
LEVEL, ARMOR, MR = 11, 80.0, 50.0        # representative SR mid-game preset
SEED = ["3006", "3031", "3094"]          # boots + 2 legendary (depth-3 seed)


def _bench(fn, n):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a bad champ should not kill the probe
            print(f"  skip: {type(exc).__name__}: {exc}")
            continue
        out.append((time.perf_counter() - t) * 1000.0)
    return out


def _p(ts, pct):
    ss = sorted(ts)
    i = max(0, min(len(ss) - 1, int(math.ceil(pct / 100.0 * len(ss))) - 1))
    return ss[i]


def main():
    snap = DataSnapshot.load()
    rows = {"beam_cold": [], "beam_seed3": [], "rank_items": []}
    for c in CHAMPS:
        rows["beam_cold"] += _bench(
            lambda c=c: beam_search_build(
                snap, c, LEVEL, mode="SR",
                target_armor=ARMOR, target_mr=MR, top_n=1), 3)
        rows["beam_seed3"] += _bench(
            lambda c=c: beam_search_build(
                snap, c, LEVEL, current_item_ids=SEED, mode="SR",
                target_armor=ARMOR, target_mr=MR, top_n=1), 3)
        rows["rank_items"] += _bench(
            lambda c=c: rank_items(
                snap, c, LEVEL, current_item_ids=SEED[:2], mode="SR",
                target_armor=ARMOR, target_mr=MR, top_n=8), 5)
    print(f"champs={CHAMPS} level={LEVEL} armor={ARMOR} mr={MR}")
    for name, ts in rows.items():
        if not ts:
            print(f"{name}: no samples")
            continue
        print(f"{name}: n={len(ts)} p50={statistics.median(ts):.1f}ms "
              f"p95={_p(ts, 95):.1f}ms min={min(ts):.1f} max={max(ts):.1f}")


if __name__ == "__main__":
    main()
