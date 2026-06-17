"""RF3 tank-template survivability item-credit table builder (offline).

The EHP / tank scorer (``ehp.rank_items_by_ehp``) pools EVERY purchasable
mode-legal terminal item and sorts PURELY by ``delta_ehp`` (or
``ehp_per_1k_gold`` in efficiency mode) - it is blind to win-rate. The
WIN-correlated mid-tier resist / HP items the player base actually wins ARAM on
(KSante: Thornmail / Iceborn Gauntlet; Rell: Fimbulwinter) ARE in the candidate
pool and DO earn a positive EHP delta, but the maximal raw-EHP stackers (Warmog's
/ Sunfire / raw armor + MR) add MORE absolute EHP, so the win-correlated items
sink below them - the DSP10 consolidated report's "buried winners" on the ``ehp``
scorer lane.

This builder distills, from the swarm's ground truth (``dsp10_consolidated.json``
buried-winners on the ``ehp`` scorer lane + ``rewind_history.db`` WIN-rate), the
per-champion set of TERMINAL, non-boot SURVIVABILITY items the tank scorer buries
but the player base wins on - the tank survivability-credit set. The output
``agents/daemon_slayer/survivability_item_credit_tank.json`` powers the DEFAULT-OFF
``prefer_survivability_by_win`` seam in ``ehp.rank_items_by_ehp``: when ON, those
already-pooled items are FLOATED above the generic max-EHP ordering BY WIN-TABLE
MEMBERSHIP (NOT by the EHP delta - the whole defect is that the delta sort already
buries them). The seam ships DEFAULT-OFF; the live default-ON flip is EXCLUDED
(docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.

ROOT-CAUSE distinction from the sibling seams (verify-before-redo):
  * RF1 ``prefer_survivability_by_win`` (hybrid lane) - the bruiser scorer's
    alpha-weighted damage sort buries pooled survivability items; RF1 floats by
    membership. RF3 is the SAME float defect in the EHP scorer: the items are
    pooled (the tank scorer's whole job is resist/HP), the raw-EHP-max sort just
    buries the win-correlated mid-tier ones. RF3 floats, no injection needed.
  * RF2 ``prefer_survivability_by_win`` (hps/enchanter lane) - the enchanter_only
    pool EXCLUDES HP/tank items, so RF2 INJECTS then floats. The EHP scorer pools
    them already, so RF3 does NOT inject.
  * DSP6 (enemy-runes seam) / DSP8 (burst-target preset) alter the ENEMY damage
    profile inputs (shares / pen) feeding ``compute_ehp`` - they change every
    item's EHP MAGNITUDE under the same enemy context, so the relative SELF order
    of mid-tier-resist vs max-EHP is unchanged: the win items stay buried under
    any preset. RF3 is the SELF ranking-order float, orthogonal to those.
  * Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM archetype divergence) is a
    SEPARATE, operator-gated policy decision and is deliberately NOT in this table
    (none surface on the ehp lane anyway).

Run:
    python ops/audit/ds_perm_swarm/build_survivability_item_credit_tank.py        # write
    python ops/audit/ds_perm_swarm/build_survivability_item_credit_tank.py --check # verify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report" / "dsp10_consolidated.json"
_DS_DIR = _ROOT / "data" / "daemon_slayer"
_OUT = _ROOT / "agents" / "daemon_slayer" / "survivability_item_credit_tank.json"

# The EHP / tank scorer lane only (report scorer == "ehp"). The bruiser/hybrid
# lane is RF1's; the enchanter lane is RF2's; the DPS/burst lanes are DSP2/DSP11's.
_SCORER = "ehp"

# Cluster A AP-in-ARAM set is operator-gated - never table these even if a future
# report run surfaces one on the ehp lane (it does not today).
_EXCLUDE_CHAMPS = {"Zilean", "Shaco", "Kayle", "Seraphine"}

# HP / tank / resist / sustain TERMINAL survivability items the tank scorer buries.
# An item enters the table only if it is BOTH a buried winner in the WIN data AND
# on this survivability axis - this rejects components (Giant's Belt / Negatron
# Cloak build INTO terminal items - dropped by the terminal filter below AND absent
# from this name set) + boots (Plated Steelcaps - dropped by the boots filter). The
# shared name allowlist mirrors the RF1/RF2 survivability axis exactly so the three
# seams stay one consistent definition of "survivability item".
_SURVIVABILITY_NAMES: set[str] = {
    # HP / health-stacking
    "Guardian's Horn",
    "Warmog's Armor",
    "Heartsteel",
    "Overlord's Bloodmail",
    "Titanic Hydra",
    "Sunfire Aegis",
    "Hollow Radiance",
    # mana-HP / frostfire
    "Fimbulwinter",
    "Iceborn Gauntlet",
    "Winter's Approach",
    # armor / MR resist tanks + sustain
    "Thornmail",
    "Randuin's Omen",
    "Frozen Heart",
    "Dead Man's Plate",
    "Spirit Visage",
    "Force of Nature",
    "Kaenic Rookern",
    "Abyssal Mask",
    "Jak'Sho, The Protean",
    "Sterak's Gage",
    "Death's Dance",
}

_MIN_N = 5           # rewind games the item was built in (matches report min_item_n)
_MIN_LIFT = 0.0      # win-rate lift over the champ baseline (>0)


def _ds_patch() -> str:
    return (_DS_DIR / "current.txt").read_text(encoding="utf-8").strip()


def _items_index() -> dict:
    raw = json.loads((_DS_DIR / _ds_patch() / "items.json").read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _is_terminal(rec: dict) -> bool:
    return not (rec.get("into") or [])


def _is_boots(rec: dict) -> bool:
    return "Boots" in (rec.get("tags") or [])


def _report_rows() -> list[dict]:
    raw = json.loads(_REPORT.read_text(encoding="utf-8"))
    return list(raw.get("worst", []))


def build() -> dict:
    items = _items_index()
    champs: dict[str, dict] = {}
    for row in _report_rows():
        if str(row.get("scorer") or "").strip().lower() != _SCORER:
            continue
        champ = str(row.get("champion") or "")
        if not champ or champ in _EXCLUDE_CHAMPS:
            continue
        picked: list[dict] = []
        for b in row.get("buried_winners", []) or []:
            name = str(b.get("name") or "")
            if name not in _SURVIVABILITY_NAMES:
                continue
            if int(b.get("n") or 0) < _MIN_N:
                continue
            if float(b.get("lift_over_baseline") or 0.0) <= _MIN_LIFT:
                continue
            iid = str(b.get("id"))
            rec = items.get(iid)
            if rec is None or not _is_terminal(rec) or _is_boots(rec):
                continue
            picked.append({
                "id": iid,
                "name": rec.get("name", iid),
                "rewind_n": int(b.get("n") or 0),
                "rewind_wr": float(b.get("wr") or 0.0),
                "lift": round(float(b.get("lift_over_baseline") or 0.0), 1),
            })
        if picked:
            picked.sort(key=lambda x: x["rewind_n"], reverse=True)
            champs[champ] = {"axis": "survivability", "items": picked}
    return {
        "_meta": {
            "source": "RF3 build_survivability_item_credit_tank.py",
            "anchored_to": "ops/audit/ds_perm_swarm/report/dsp10_consolidated.json (tank/ehp scorer lane)",
            "ds_patch": _ds_patch(),
            "min_rewind_n": _MIN_N,
            "scorer_lane": _SCORER,
            "note": "DEFAULT-OFF prefer_survivability_by_win seam input (ehp/tank ranker). Tabled ids are already POOLED by the EHP scorer; the seam FLOATS them above the max-EHP ordering by win-table membership. Cluster A excluded (operator-gated). Components + boots excluded.",
        },
        "champions": champs,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed JSON matches a fresh build")
    args = ap.parse_args()
    built = build()
    text = json.dumps(built, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.check:
        cur = _OUT.read_text(encoding="utf-8") if _OUT.exists() else ""
        if cur != text:
            print("DRIFT: survivability_item_credit_tank.json != fresh build", file=sys.stderr)
            return 2
        print("survivability_item_credit_tank.json in sync")
        return 0
    _OUT.write_text(text, encoding="utf-8")
    n_items = sum(len(v["items"]) for v in built["champions"].values())
    print(f"wrote {_OUT} - {len(built['champions'])} champs / {n_items} items")
    for champ, v in sorted(built["champions"].items()):
        names = ", ".join(i["name"] for i in v["items"])
        print(f"  {champ} [{v['axis']}]: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
