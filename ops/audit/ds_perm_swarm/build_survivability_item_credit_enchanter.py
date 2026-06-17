"""RF2 enchanter-template survivability item-credit table builder (offline).

The HPS / enchanter scorer (``hps.rank_items_by_hps``) defaults
``enchanter_only=True`` - it restricts the candidate pool to the curated
enchanter-throughput formula registry (Echoes of Helia / Ardent Censer / Staff of
Flowing Water / Locket / Knight's Vow / Redemption). So for an enchanter played
front-to-back as a TANK-support, the HP / tank survivability items the player base
actually wins ARAM on (Guardian's Horn / Warmog's Armor / Heartsteel / Fimbulwinter)
are not merely buried - they are EXCLUDED from the pool entirely (they add zero HPS
throughput, so they are not in the registry). The generic enchanter template tops
the list and the WIN-correlated tank items never appear - the DSP10 consolidated
report's "buried winners" for the enchanter (hps) scorer lane.

This builder distills, from the swarm's ground truth (``dsp10_consolidated.json``
buried-winners on the ``hps`` scorer lane + ``rewind_history.db`` WIN-rate), the
per-champion set of TERMINAL, non-boot SURVIVABILITY items the enchanter scorer
omits but the player base wins on - the enchanter survivability-credit set. The
output ``agents/daemon_slayer/survivability_item_credit_enchanter.json`` powers the
DEFAULT-OFF ``prefer_survivability_by_win`` seam in ``hps.rank_items_by_hps``: when
ON, those items are INJECTED into the candidate pool (the enchanter_only registry
would otherwise drop them) and floated above the generic enchanter template BY
WIN-TABLE MEMBERSHIP (NOT by the HPS delta - they contribute zero HPS, the whole
defect is that the throughput scorer cannot see them). The seam ships DEFAULT-OFF;
the live default-ON flip is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md) - do not flip
blind.

ROOT-CAUSE distinction from the sibling seams (verify-before-redo):
  * RF1 ``prefer_survivability_by_win`` (hybrid lane) - the bruiser scorer DOES
    consider survivability items but its alpha-weighted damage sort buries them;
    RF1 floats by membership. The enchanter (hps) scorer is WORSE: enchanter_only
    EXCLUDES them from the pool, so RF2 must ALSO inject them before floating.
  * DSP11 ``prefer_kit_axis_by_win`` - floats kit-axis items in the DPS/BURST
    rankers GATED ON ``delta_dps > 0``; survivability items add EHP/HP not DPS so a
    delta gate would never surface them.
  * Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM archetype divergence) is a
    SEPARATE, operator-gated policy decision and is deliberately NOT in this table.
    On the hps lane both Zilean and Seraphine surface AP/mage buried winners
    (Shadowflame / Rabadon's / Malignance) - those are the Cluster-A archetype
    matter, NOT the tank-support survivability defect, so they are excluded here.

Run:
    python ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py        # write
    python ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py --check # verify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report" / "dsp10_consolidated.json"
_DS_DIR = _ROOT / "data" / "daemon_slayer"
_OUT = _ROOT / "agents" / "daemon_slayer" / "survivability_item_credit_enchanter.json"

# The enchanter / hps scorer lane only (report scorer == "hps"). The bruiser/hybrid
# lane is RF1's; the DPS/burst lanes are DSP2/DSP11's.
_SCORER = "hps"

# Cluster A AP-in-ARAM set is operator-gated - never table these even if a future
# report run surfaces one on the hps lane (Zilean/Seraphine do, with AP buried
# winners - that is the Cluster-A archetype matter, NOT a survivability defect).
_EXCLUDE_CHAMPS = {"Zilean", "Shaco", "Kayle", "Seraphine"}

# HP / tank / resist / sustain TERMINAL survivability items the enchanter throughput
# scorer omits (enchanter_only registry has zero of these - they add no HPS). An item
# enters the table only if it is BOTH a buried winner in the WIN data AND on this
# survivability axis - this rejects the off-axis AP / mage items the raw report
# carries on the Cluster-A hps rows (Shadowflame / Rabadon's / Malignance) + boots +
# components. Deliberately EXCLUDES the enchanter-template items already ranked by the
# hps scorer (Locket / Knight's Vow / Redemption / Ardent / Helia / Staff) - the seam
# is for items the scorer cannot see, not a re-sort of ones it already has.
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
            "source": "RF2 build_survivability_item_credit_enchanter.py",
            "anchored_to": "ops/audit/ds_perm_swarm/report/dsp10_consolidated.json (enchanter/hps scorer lane)",
            "ds_patch": _ds_patch(),
            "min_rewind_n": _MIN_N,
            "scorer_lane": _SCORER,
            "note": "DEFAULT-OFF prefer_survivability_by_win seam input (hps/enchanter ranker). Tabled ids are INJECTED into the enchanter_only pool then floated. Cluster A excluded (operator-gated). Boots excluded.",
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
            print("DRIFT: survivability_item_credit_enchanter.json != fresh build", file=sys.stderr)
            return 2
        print("survivability_item_credit_enchanter.json in sync")
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
