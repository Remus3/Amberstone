"""RF1 generic-bruiser-template survivability item-credit table builder (offline).

The hybrid/bruiser scorer (``hybrid.rank_items_by_hybrid``) emits a near-fixed
generic AD-DPS template for every bruiser - Void Immolation / Blade of The Ruined
King / Trinity Force / Heartsteel / Essence Reaver / Runaan's Hurricane - because
its sort key ``hybrid_delta_pct = alpha*dps_pct + beta*ehp_pct`` is alpha-weighted
toward damage and its default mixed-damage target preset under-credits the pure
resist / sustain axis. So the WIN-correlated survivability items the player base
actually wins ARAM on (Spirit Visage / Jak'Sho / Sterak's Gage / Death's Dance /
Black Cleaver / Force of Nature / Randuin's Omen / Thornmail / Titanic Hydra /
Fimbulwinter) sink below the generic template - the DSP10 consolidated report's
"buried winners".

This builder distills, from the swarm's ground truth (``dsp10_consolidated.json``
buried-winners + ``rewind_history.db`` WIN-rate), the per-champion set of TERMINAL,
non-boot SURVIVABILITY items DS buries on hybrid/bruiser champs but the player base
wins on - the survivability-credit set. The output
``agents/daemon_slayer/survivability_item_credit.json`` powers the DEFAULT-OFF
``prefer_survivability_by_win`` seam in ``hybrid.rank_items_by_hybrid``: when ON,
those items are floated above the generic template BY WIN-TABLE MEMBERSHIP (NOT by
the hybrid delta - the whole defect is that the scorer rates them low). The seam
ships DEFAULT-OFF; the live default-ON flip is EXCLUDED
(docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.

ROOT-CAUSE distinction from the sibling seams (verify-before-redo):
  * DSP2 ``exempt_offclass_by_win`` - un-strips off-class items from the
    ranged-MARKSMAN deny set; bruisers are not marksmen, so it never fires here.
  * DSP11 ``prefer_kit_axis_by_win`` - floats kit-axis items in the DPS/BURST
    rankers GATED ON ``delta_dps > 0``; survivability items add EHP not DPS so
    their delta is ~0/negative and would never float there. RF1 lives in the
    HYBRID ranker and floats by table membership.
  * Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM archetype divergence) is a
    SEPARATE, operator-gated policy decision and is deliberately NOT in this table.

Run:
    python ops/audit/ds_perm_swarm/build_survivability_item_credit.py        # write
    python ops/audit/ds_perm_swarm/build_survivability_item_credit.py --check # verify
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report" / "dsp10_consolidated.json"
_DS_DIR = _ROOT / "data" / "daemon_slayer"
_OUT = _ROOT / "agents" / "daemon_slayer" / "survivability_item_credit.json"

# The hybrid/bruiser scorer lane only (report scorer == "hybrid"). The DPS/burst
# lanes are DSP2/DSP11's; the AP-mage / enchanter / tank lanes are RF2/RF3.
_SCORER = "hybrid"

# Cluster A AP-in-ARAM set is operator-gated - never table these even if a future
# report run mislabels one as hybrid.
_EXCLUDE_CHAMPS = {"Zilean", "Shaco", "Kayle", "Seraphine"}

# Survivability / sustain / bruiser-defensive TERMINAL items the pure-damage-biased
# hybrid sort under-credits. An item enters the table only if it is BOTH a buried
# winner in the WIN data AND on this survivability axis - this rejects the off-axis
# DPS items (IE / Guinsoo's on MasterYi) + boots + components the raw report carries
# (those are a DSP11 / within-axis / noise matter, not the survivability defect).
_SURVIVABILITY_NAMES: set[str] = {
    "Force of Nature",
    "Spirit Visage",
    "Jak'Sho, The Protean",
    "Sterak's Gage",
    "Death's Dance",
    "Black Cleaver",
    "Randuin's Omen",
    "Thornmail",
    "Titanic Hydra",
    "Fimbulwinter",
    "Sundered Sky",
    "Stridebreaker",
    "Iceborn Gauntlet",
    "Overlord's Bloodmail",
    "Wit's End",
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
            "source": "RF1 build_survivability_item_credit.py",
            "anchored_to": "ops/audit/ds_perm_swarm/report/dsp10_consolidated.json (hybrid/bruiser scorer lane)",
            "ds_patch": _ds_patch(),
            "min_rewind_n": _MIN_N,
            "scorer_lane": _SCORER,
            "note": "DEFAULT-OFF prefer_survivability_by_win seam input (hybrid ranker). Cluster A excluded (operator-gated).",
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
            print("DRIFT: survivability_item_credit.json != fresh build", file=sys.stderr)
            return 2
        print("survivability_item_credit.json in sync")
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
