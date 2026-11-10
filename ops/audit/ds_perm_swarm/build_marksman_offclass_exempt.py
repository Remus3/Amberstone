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
this builder after a cross-eval refresh to keep the table current; ``--check``
compares the committed table with a fresh build and writes nothing.

Hand-seeded rows (``_MANUAL_ENTRIES``, today Quinn, A-20 / RM-89) are unioned
in by ``with_manual_entries`` on every write and check. Before S144-D-240 a
regeneration silently dropped the Quinn row and its comment.

Hermetic: reads only the small per-champ cross-eval JSONs + the DS snapshot's
champion records (tags / attackrange for the ranged-marksman gate). The 1.8GB
rewind_history.db is NEVER opened here.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: E402
from agents.daemon_slayer.rank import (  # noqa: E402
    OFFCLASS_MARKSMAN_ITEM_NAMES,
    _is_ranged_marksman,
)
from core.polled_json import atomic_write_text  # noqa: E402
from ops.audit.ds_perm_swarm.credit_table_check import (  # noqa: E402
    committed_matches_patch,
    render_ascii,
)

_CROSS_EVAL_DIR = _ROOT / "ops" / "audit" / "ds_cross_eval" / "data"
_OUT_PATH = _ROOT / "agents" / "daemon_slayer" / "marksman_offclass_exempt.json"

# An off-class item is a real build for this champ when the player base buys it
# this often (primary signal) and it is not an outright trap (loose WR band).
MIN_USAGE = 30
WR_MARGIN = 3.0
# Modes whose empirical "all" block we mine (ARAM + SR carry the marksman data).
_MODES = ("ARAM", "SR")

# Hand-seeded rows the usage gate cannot reach (S144-D-240). Every name must be
# in OFFCLASS_MARKSMAN_ITEM_NAMES: a name the deny-set never strips would be a
# no-op row, so with_manual_entries refuses it.
_MANUAL_ENTRIES: dict[str, tuple[str, ...]] = {
    "Quinn": ("Profane Hydra", "Umbral Glaive"),
}
_MANUAL_ENTRIES_COMMENT = (
    "A-20 / RM-89 (2026-07-25) hand-seeded the Quinn row; "
    "build_marksman_offclass_exempt.py re-adds it from its _MANUAL_ENTRIES on "
    "every build (S144-D-240; before that a regeneration silently dropped it). "
    "Rationale: Quinn trips _is_ranged_marksman (Marksman tag, 525 attackrange), "
    "so OFFCLASS_MARKSMAN_ITEM_NAMES strips Profane Hydra and Umbral Glaive from "
    "her candidate pool entirely - yet her real meta is a ~85-90 pct lethality "
    "assassin whose second-most-picked item IS Profane Hydra (~12k games, behind "
    "only Hubris at ~22k), with Umbral Glaive a standard lethality rotation "
    "(docs/DS_SWEEP_TRACKER.md batch19). The class-wide "
    "rank.CARRY_POOL_WIDEN_ITEM_NAMES seam does not reach either name and must "
    "NOT be widened to: no crit ADC should be handed a bruiser hydra. "
    "Per-champion is the correct blast radius. Measured 2026-07-25: with the "
    "seam ON her SR carry pool goes 107 -> 109 and admits exactly these two ids "
    "(6698, 3179), while Jinx and Caitlyn stay byte-identical."
)


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


def with_manual_entries(table: dict) -> dict:
    """Return a copy of ``table`` with the hand-seeded rows unioned in.

    S144-D-240. ``build_table`` stays the computed half only. The comment that
    records why the rows exist goes right after ``_comment``, and the
    ``champions`` map stays sorted. Raises ValueError on a manual name the
    off-class deny-set does not strip (such a row would do nothing).
    """
    champions = {k: list(v) for k, v in (table.get("champions") or {}).items()}
    for champ, names in _MANUAL_ENTRIES.items():
        stray = sorted(set(names) - set(OFFCLASS_MARKSMAN_ITEM_NAMES))
        if stray:
            raise ValueError(
                f"{champ}: manual exemption {stray} is not in "
                "OFFCLASS_MARKSMAN_ITEM_NAMES, so the row would be a no-op"
            )
        champions[champ] = sorted(set(champions.get(champ, ())) | set(names))
    out: dict = {}
    for key, value in table.items():
        if key == "_manual_entries_comment":
            continue
        out[key] = value
        if key == "_comment":
            out["_manual_entries_comment"] = _MANUAL_ENTRIES_COMMENT
    out.setdefault("_manual_entries_comment", _MANUAL_ENTRIES_COMMENT)
    out["champions"] = dict(sorted(champions.items()))
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="verify the committed JSON matches a fresh build")
    args = parser.parse_args([] if argv is None else argv)
    table = with_manual_entries(build_table())
    if args.check:
        # S144-D-241: the committed top-level patch stamp is provenance, kept.
        if not committed_matches_patch(_OUT_PATH, table):
            print(f"DRIFT: {_OUT_PATH.name} != fresh build", file=sys.stderr)
            return 2
        print(f"{_OUT_PATH.name} in sync")
        return 0
    # Atomic, LF-only write (core.polled_json: per-writer scratch name).
    atomic_write_text(_OUT_PATH, render_ascii(table))
    champs = table["champions"]
    print(f"wrote {_OUT_PATH}")
    print(
        f"ranged_marksmen_considered={table['ranged_marksmen_considered']} "
        f"exempted_champs={len(champs)}"
    )
    for c, names in champs.items():
        print(f"  {c}: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
