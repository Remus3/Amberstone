"""DS block_index candidate scanner (Phase 5.9.x batch tooling).

For a champion, prints every ability key's FILTERED damage blocks (the
index space the registry uses - `_select_blocks` strips
``attribute_kind != "damage"`` before indexing, so raw Meraki block N
is NOT registry index N when non-damage prefix blocks exist) plus the
ground-truth A/B: `compute_ability_dps` raw_damage_per_cast at level 11,
SR, vs 80 armor / 30 MR / 2000 HP, forced to each filtered index, with
the ratio vs filtered block 0.

A "candidate" is a key where some filtered block i>0 has a meaningfully
larger evaluated value than block 0 AND represents a realistic
single-target burst the operator commits to (full channel, all hits
focused, fully-charged, max-stack, sub-execute) - see
champion_block_index.json _meta for the documented pattern + skip list.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_block_scanner.py <Champion> [<Champion> ...]
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_block_scanner.py --slice Annie,Azir,Fiora     # comma list
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_block_scanner.py --uncovered                  # all not-yet-in-registry
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.daemon_slayer.abilities import load_default as load_abilities
from agents.daemon_slayer.ability_dps import (
    compute_ability_dps,
    get_block_index_for,
    reset_block_index_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot

LVL = 11
ARMOR, MR, HP = 80.0, 30.0, 2000.0


def _rank_for_level(key: str, level: int) -> int:
    """Same level->rank heuristic the engine uses for display only."""
    if key == "R":
        return min(2, max(0, (level - 6) // 5)) if level >= 6 else 0
    return min(4, max(0, (level - 1) // 2))


def scan(champion: str, snap: DataSnapshot) -> None:
    reset_block_index_cache()
    reg, src = get_block_index_for(champion)
    asnap = load_abilities()
    forms_by_key = asnap.champions.get(champion)
    print(f"\n{'='*78}\n{champion}   registry={reg or '{}'} (src={src})\n{'='*78}")
    if not forms_by_key:
        print("  !! not in abilities snapshot")
        return

    for key in ("Q", "W", "E", "R"):
        forms = forms_by_key.get(key) or ()
        for form in forms:
            dmg = form.damage_blocks_only()
            if len(dmg) < 2:
                # single damage block -> block 0 is correct, never a candidate
                if dmg:
                    tag = "" if len(dmg) == 1 else " (NO DAMAGE BLOCKS)"
                    print(f"  {key} form{form.form_index} '{form.name}': "
                          f"{len(dmg)} dmg block{tag} - block 0 canonical, skip")
                continue
            print(f"\n  {key} form{form.form_index} '{form.name}'  "
                  f"({form.damage_type})  {len(dmg)} filtered damage blocks:")
            rank = _rank_for_level("R" if key == "R" else key, LVL)
            for i, b in enumerate(dmg):
                base = b.base[rank] if b.base and rank < len(b.base) else None
                scal = []
                for fld in ("total_ad_pct", "bonus_ad_pct", "ap_pct",
                            "target_max_hp_pct", "target_missing_hp_pct",
                            "caster_max_hp_pct", "caster_bonus_hp_pct"):
                    v = getattr(b, fld, None)
                    if v and any(v):
                        sv = v[rank] if rank < len(v) else v[-1]
                        if sv:
                            scal.append(f"{fld}={sv}")
                print(f"     [{i}] '{b.attribute}'  base@r{rank}={base}  "
                      f"{' '.join(scal) or '(no parsed scaling)'}")

            # ground-truth A/B
            try:
                vals = []
                for i in range(len(dmg)):
                    out = compute_ability_dps(
                        snap, champion, level=LVL, item_ids=[], mode="SR",
                        target_armor=ARMOR, target_mr=MR, target_max_hp=HP,
                        block_index_overrides={key: i},
                    )
                    s = next((p for p in out.per_spell if p.key == key), None)
                    vals.append(s.raw_damage_per_cast if s else 0.0)
                b0 = vals[0] or 1e-9
                print("     A/B raw_damage_per_cast (forced each filtered idx):")
                for i, v in enumerate(vals):
                    flag = "  <== candidate" if v > b0 * 1.10 and i > 0 else ""
                    print(f"        idx {i}: {v:9.2f}   {v/b0:5.2f}x block0{flag}")
            except Exception as e:  # noqa: BLE001
                print(f"     A/B failed: {e}")


def main(argv: list[str]) -> int:
    snap = DataSnapshot.load()
    if argv and argv[0] == "--uncovered":
        asnap = load_abilities()
        reset_block_index_cache()
        import json
        from pathlib import Path
        reg = json.loads(
            (Path("agents/daemon_slayer/champion_block_index.json")).read_text()
        )["champions"]
        targets = sorted(set(asnap.champions) - set(reg))
    elif argv and argv[0] == "--slice":
        targets = [c.strip() for c in argv[1].split(",") if c.strip()]
    else:
        targets = argv
    if not targets:
        print(__doc__)
        return 1
    for c in targets:
        scan(c, snap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
