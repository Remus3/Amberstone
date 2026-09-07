"""DS max_priority coverage pre-filter (Phase 5.9.x batch tooling).

`champion_max_priority.json` overrides the spell-max order (default
Q->W->E) the ds.ability / ds.burst scorers use to resolve per-spell rank
at a given level. Wrong for champions whose primary damage spell is W
or E (Cassiopeia E, Karthus Q, Leblanc W, ...). Objective oracle: try all
6 (Q,W,E) orderings, compute total ability_dps at level 11; the order
that maximises total is the one that ranks the highest-marginal-DPS
spell first - i.e. the champion's real damage-max order. Flag every
champion NOT already in the registry whose best order beats the default
Q-W-E by >MARGIN AND whose best != default (so the registry omission is
materially mis-scoring it).

Judgment still required: confirm the numeric best matches the
champion's real in-game max order (most damage mages max their highest
spell first, but a few max utility/CD - don't blindly ship those).

Usage:  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_max_priority_prefilter.py [--margin 1.10]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.daemon_slayer.abilities import load_default as load_abilities
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    reset_block_index_cache,
    reset_form_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot

LVL = 11
ARMOR, MR, HP = 80.0, 30.0, 2000.0
_ORDERS = ["".join(p) for p in itertools.permutations("QWE")]


def _total(snap, champ, order):
    out = compute_ability_dps(
        snap, champ, level=LVL, item_ids=[], mode="SR",
        target_armor=ARMOR, target_mr=MR, target_max_hp=HP,
        max_priority=list(order),
    )
    return out.total_ability_dps if hasattr(out, "total_ability_dps") \
        else sum(s.dps for s in out.per_spell)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--margin", type=float, default=1.10)
    args = ap.parse_args()

    snap = DataSnapshot.load()
    reset_block_index_cache()
    reset_form_index_cache()
    reg = json.loads(
        Path("agents/daemon_slayer/champion_max_priority.json")
        .read_text(encoding="utf-8")
    )["champions"]
    asnap = load_abilities()

    rows = []
    for champ in sorted(asnap.champions):
        if champ in reg:
            continue
        # only meaningful when the champ has >=2 damage-bearing spell keys
        keys = asnap.champions[champ]
        dmg_keys = sum(
            1 for k in ("Q", "W", "E")
            if any(f.damage_blocks_only() for f in (keys.get(k) or ()))
        )
        if dmg_keys < 2:
            continue
        try:
            base = _total(snap, champ, "QWE")
            scores = {o: _total(snap, champ, o) for o in _ORDERS}
        except Exception as e:  # noqa: BLE001
            rows.append((champ, f"ERR {e}", "", 0))
            continue
        best = max(scores, key=scores.get)
        if best != "QWE" and base > 0 and scores[best] > base * args.margin:
            rows.append((champ, best, f"{scores[best]/base:.2f}x QWE",
                         scores[best]))

    rows.sort(key=lambda r: -float(r[2].split("x")[0]) if "x" in str(r[2]) else 0)
    print(f"max_priority candidates (best != QWE, >{args.margin}x): {len(rows)}")
    for champ, best, ratio, _ in rows:
        order = "-".join(best)
        print(f"  {champ}: max {order}  ({ratio} vs default Q-W-E)")
    print("\nCANDIDATES=" + ",".join(r[0] for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
