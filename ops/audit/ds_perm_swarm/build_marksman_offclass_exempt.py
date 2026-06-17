"""DSP2 - build the per-marksman off-class WIN-exemption table.

Cluster B (DS permutation swarm, ops/audit/ds_perm_swarm): the item-213
ranged-marksman off-class deny-set (rank.OFFCLASS_MARKSMAN_ITEM_NAMES) strips
Sheen-line / on-hit-caster items (Trinity Force, Spear of Shojin, ...) from
EVERY ranged marksman. That is correct for a pure crit ADC (Caitlyn / Jinx /
Sivir) but WRONG for an ability / Sheen caster-marksman (Ezreal, Corki,
Smolder, Senna) whose actual winning build IS those items - the DSP1
WIN-anchor surfaced Ezreal SR -39 as the worst outcome-divergent champ-mode
precisely because Trinity Force (his most-built item, ARAM n=219) was hard
excluded from the candidate pool.

There is NO clean kit-data axis for "wants Sheen" (lolmath.damage_distribution
is AD/AP only - it cannot separate Ezreal's ability-physical damage from
Caitlyn's auto-physical). So we anchor on the swarm's ground truth instead:
the rewind WIN + USAGE data, already distilled per champion into the
ops/audit/ds_cross_eval/data/<Champ>.json ``empirical`` block (per-item n + wr
from data/rewind_history.db). An off-class item is EXEMPTED for a ranged
marksman when the player base genuinely builds it on that champ:

    n >= MIN_USAGE   AND   wr >= mode_baseline_wr - WR_MARGIN

USAGE (n) is the primary signal - it says "this is a real build for this
champ"; the loose WR band only rejects an outright trap pick. A pure crit ADC
never clears the usage gate on a bruiser/Sheen item, so the table stays empty
for them (verified: Caitlyn / Jinx / Ashe / Sivir / Yunara / Twitch / Aphelios
/ MissFortune all clean).

Output: ``agents/daemon_slayer/marksman_offclass_exempt.json`` - consumed by
``rank.rank_items(exempt_offclass_by_win=True)`` (the DEFAULT-OFF DSP2 seam;
the live default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md). Re-run
this builder after a cross-eval refresh to keep the table current.

Hermetic: reads only the small per-champ cross-eval JSONs + the DS snapshot's
champion records (tags / attackrange for the ranged-marksman gate). The 1.8GB
rewind_history.db is NEVER opened here.
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    OFFCLASS_MARKSMAN_ITEM_NAMES,
    _is_ranged_marksman,
)

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CROSS_EVAL_DIR = _ROOT / "ops" / "audit" / "ds_cross_eval" / "data"
_OUT_PATH = _ROOT / "agents" / "daemon_slayer" / "marksman_offclass_exempt.json"

# An off-class item is a real build for this champ when the player base buys it
# this often (primary signal) and it is not an outright trap (loose WR band).
MIN_USAGE = 30
WR_MARGIN = 3.0
# Modes whose empirical "all" block we mine (ARAM + SR carry the marksman data).
_MODES = ("ARAM", "SR")


def build_table(
    snapshot: DataSnapshot | None = None,
    cross_eval_dir: Path = _CROSS_EVAL_DIR,
    min_usage: int = MIN_USAGE,
    wr_margin: float = WR_MARGIN,
) -> dict:
    """Return the exemption table dict (does not write to disk)."""
    snap = snapshot if snapshot is not None else DataSnapshot.load()
    champions: dict[str, list[str]] = {}
    considered = 0
    for fp in sorted(glob.glob(str(cross_eval_dir / "*.json"))):
        data = json.loads(Path(fp).read_text(encoding="utf-8"))
        champ = data.get("champion")
        if not champ:
            continue
        rec = snap.champions.get(str(champ))
        if rec is None or not _is_ranged_marksman(rec):
            continue
        considered += 1
        emp = data.get("empirical") or {}
        exempt: set[str] = set()
        for mode in _MODES:
            blk = (emp.get(mode) or {}).get("all") or {}
            base = blk.get("wr")
            if base is None:
                continue
            for it in blk.get("items") or []:
                name = it.get("name")
                n = it.get("n") or 0
                wr = it.get("wr")
                if (
                    name in OFFCLASS_MARKSMAN_ITEM_NAMES
                    and n >= min_usage
                    and wr is not None
                    and wr >= base - wr_margin
                ):
                    exempt.add(name)
        if exempt:
            champions[str(champ)] = sorted(exempt)
    patch = ""
    try:
        patch = (_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        patch = ""
    return {
        "_comment": (
            "DSP2 Cluster-B: per-ranged-marksman off-class WIN-exemption table. "
            "Consumed by rank.rank_items(exempt_offclass_by_win=True) (DEFAULT-OFF "
            "seam). Built by ops/audit/ds_perm_swarm/build_marksman_offclass_exempt.py "
            "from the cross-eval empirical (rewind WIN+usage) data. ASCII only."
        ),
        "patch": patch,
        "generated_from": "ops/audit/ds_cross_eval/data",
        "min_usage": min_usage,
        "wr_margin": wr_margin,
        "ranged_marksmen_considered": considered,
        "champions": dict(sorted(champions.items())),
    }


def main() -> None:
    table = build_table()
    text = json.dumps(table, indent=2, ensure_ascii=True, sort_keys=False)
    # Atomic write, LF line endings (repo EOL guard).
    tmp = _OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(text + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, _OUT_PATH)
    champs = table["champions"]
    print(f"wrote {_OUT_PATH}")
    print(
        f"ranged_marksmen_considered={table['ranged_marksmen_considered']} "
        f"exempted_champs={len(champs)}"
    )
    for c, names in champs.items():
        print(f"  {c}: {names}")


if __name__ == "__main__":
    main()
