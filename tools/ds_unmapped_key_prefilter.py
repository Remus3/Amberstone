"""DS unmapped-key pre-filter (Phase 5.9.x batch tooling).

The s223 5-way scan proved the *uncovered-champion* block_index space is
saturated. This pre-filter targets the orthogonal space: ability KEYS on
already-COVERED champions that are NOT yet in that champion's registry
entry but still carry a multi-damage-block ability whose later filtered
block out-evaluates block 0.

For every covered champion x key-not-in-registry, runs the same
ground-truth A/B `compute_ability_dps` the scanner uses, at BOTH full HP
and 40% HP (the second pass catches missing/current-HP execute blocks
that are a no-op at full HP - the Kindred-E class). Emits only keys
where some filtered block i>0 exceeds block 0 by >MARGIN at either HP -
that shortlist is what parallel agents then judge against the documented
pattern/skip rules.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_unmapped_key_prefilter.py            # full shortlist
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_unmapped_key_prefilter.py --margin 1.25
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.daemon_slayer.abilities import load_default as load_abilities
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    reset_block_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot

LVL = 11
ARMOR, MR, HP = 80.0, 30.0, 2000.0


def _ab(snap, champ, key, idx, hp_pct):
    out = compute_ability_dps(
        snap, champ, level=LVL, item_ids=[], mode="SR",
        target_armor=ARMOR, target_mr=MR, target_max_hp=HP,
        target_current_hp_pct=hp_pct,
        block_index_overrides={key: idx},
    )
    s = next((p for p in out.per_spell if p.key == key), None)
    return s.raw_damage_per_cast if s else 0.0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--margin", type=float, default=1.15)
    args = ap.parse_args(argv)

    snap = DataSnapshot.load()
    reset_block_index_cache()
    reg = json.loads(
        Path("agents/daemon_slayer/champion_block_index.json")
        .read_text(encoding="utf-8")
    )["champions"]
    asnap = load_abilities()

    shortlist: list[tuple] = []
    for champ in sorted(reg):
        mapped = {k.upper() for k in reg[champ]}
        forms_by_key = asnap.champions.get(champ)
        if not forms_by_key:
            continue
        for key in ("Q", "W", "E", "R"):
            if key in mapped:
                continue
            for form in forms_by_key.get(key) or ():
                dmg = form.damage_blocks_only()
                if len(dmg) < 2:
                    continue
                for hp_pct, tag in ((1.0, "fullHP"), (0.4, "40%HP")):
                    try:
                        vals = [_ab(snap, champ, key, i, hp_pct)
                                for i in range(len(dmg))]
                    except Exception as e:  # noqa: BLE001
                        shortlist.append((champ, key, form.form_index,
                                          f"ERR {e}", "", ""))
                        break
                    b0 = vals[0] or 1e-9
                    best_i = max(range(len(vals)), key=lambda i: vals[i])
                    if best_i > 0 and vals[best_i] > b0 * args.margin:
                        attrs = " | ".join(
                            f"[{i}]{dmg[i].attribute}={vals[i]:.0f}"
                            for i in range(len(dmg))
                        )
                        shortlist.append((
                            champ, key, form.form_index, tag,
                            f"{vals[best_i]/b0:.2f}x@idx{best_i}", attrs,
                        ))
                        break  # one HP tag is enough to flag for agents

    print(f"COVERED champions: {len(reg)}  |  "
          f"unmapped-key candidates (>{args.margin}x): {len(shortlist)}")
    for c, k, fi, tag, ratio, attrs in shortlist:
        print(f"  {c}.{k} f{fi} [{tag}] {ratio}")
        print(f"      {attrs}")
    # machine-readable tail for the supervisor to partition
    print("\nSHORTLIST_KEYS=" + ",".join(
        f"{c}.{k}" for c, k, *_ in shortlist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
