"""DSP11 Cluster-B2 kit-axis item-credit table builder (offline, audit-only).

The dps/burst scorers emit a near-fixed generic AD template (BotRK / Kraken /
Stormrazor / Trinity / Essence Reaver for carry; Sundered Sky / IE / Trinity for
assassin) for EVERY AD carry/assassin, because ``compute_dps`` /
``compute_burst_damage`` model a generic auto-attack / single-combo rotation that
cannot encode a champion's kit win-axis (Pyke R executes scale with lethality,
Nilah doubles crit, Ezreal Q + Manamune ramp). So the engine ranks the generic
template above the items the player base actually WINS on - the DSP10 consolidated
report's "buried winners".

This builder distills, from the swarm's ground truth (``dsp10_consolidated.json``
buried-winners + ``rewind_history.db`` for the directive-named Ezreal who fell
outside the worst-40 anchor-matched window), the per-champion set of TERMINAL,
non-boot items DS buries but the player base wins on - the kit-axis credit set.
The output ``agents/daemon_slayer/kit_axis_item_credit.json`` powers the
DEFAULT-OFF ``prefer_kit_axis_by_win`` seam in rank.py + burst.py: when ON, those
items are un-stripped from the candidate pool (ranged-marksman off-class casters)
and floated above the generic template. The seam ships DEFAULT-OFF; the live
default-ON flip is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.

Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM archetype divergence) is a
SEPARATE, operator-gated policy decision and is deliberately NOT in this table.

Run:
    python ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py        # write
    python ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py --check # verify
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REPORT = _ROOT / "ops" / "audit" / "ds_perm_swarm" / "report" / "dsp10_consolidated.json"
_REWIND = _ROOT / "data" / "rewind_history.db"
_DS_DIR = _ROOT / "data" / "daemon_slayer"
_OUT = _ROOT / "agents" / "daemon_slayer" / "kit_axis_item_credit.json"

# Curated champ -> kit-axis label seed. The LABEL is operator intent (which axis
# the kit wins on); the ITEMS are pulled mechanically from the WIN data below so
# the table stays anchored to rewind reality, not a hand-typed wishlist. Only
# Cluster-B2 caster-ADC / lethality-assassin / crit-melee kits - NOT Cluster A.
_CHAMP_AXIS: dict[str, str] = {
    "Pyke": "lethality",
    "Naafiri": "lethality",
    "Senna": "lethality",
    "Nilah": "crit",
    "Quinn": "crit",
    "Ezreal": "manamune",
    "Corki": "manamune",
}

# Per-champion item allow-set (DDragon ids) by kit axis. An item enters the table
# only if it is BOTH a buried winner in the WIN data AND on the champ's kit axis -
# this rejects off-axis noise (a buried tank/boots item) the raw report carries.
_AXIS_ITEM_IDS: dict[str, set[str]] = {
    # lethality / armor-pen assassin core
    "lethality": {
        "6701",  # Opportunity
        "3142",  # Youmuu's Ghostblade
        "6696",  # Axiom Arc
        "6676",  # The Collector
        "126697",  # Hubris
        "3071",  # Black Cleaver (Senna soul-stack AD)
        "6694",  # Serylda's Grudge
        "3814",  # Edge of Night
    },
    # crit ADC core
    "crit": {
        "3031",  # Infinity Edge
        "6675",  # Navori Flickerblade
        "6673",  # Immortal Shieldbow
        "3036",  # Lord Dominik's Regards
        "3087",  # Statikk Shiv
        "6676",  # The Collector
        "3094",  # Rapid Firecannon
        "3033",  # Mortal Reminder
        "3072",  # Bloodthirster
    },
    # mana-stack / sheen caster-ADC core
    "manamune": {
        "3078",  # Trinity Force
        "3042",  # Muramana
        "3004",  # Manamune
        "3508",  # Essence Reaver
        "6676",  # The Collector
    },
}

_MIN_N = 15          # rewind games the item was built in
_MIN_LIFT = 0.0      # win-rate lift over the champ baseline (>0)
# Ezreal fell outside the worst-40 anchor window (an SR cross-mode artifact in
# DSP10), but the directive names him. Anchor him directly against rewind: his
# staple Trinity (n219, ~baseline - DS HARD-STRIPS it off-class) + the
# above-baseline Muramana + Essence Reaver. Trinity rides a looser band because
# the defect is exclusion, not burial (its wr ~= baseline by construction).
_EZREAL_MIN_N = 15
_EZREAL_BAND = 2.0   # include staple identity items within this wr band of base


def _ds_patch() -> str:
    return (_DS_DIR / "current.txt").read_text(encoding="utf-8").strip()


def _items_index() -> dict:
    raw = json.loads((_DS_DIR / _ds_patch() / "items.json").read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _is_terminal(rec: dict) -> bool:
    return not (rec.get("into") or [])


def _is_boots(rec: dict) -> bool:
    return "Boots" in (rec.get("tags") or [])


def _report_rows() -> dict[str, dict]:
    raw = json.loads(_REPORT.read_text(encoding="utf-8"))
    return {r["champion"]: r for r in raw.get("worst", [])}


def _ezreal_from_rewind(items: dict) -> list[dict]:
    """Direct rewind ARAM item win-rates for Ezreal (not in the worst-40)."""
    db = sqlite3.connect(str(_REWIND))
    try:
        c = db.cursor()
        base = (
            "FROM participants p JOIN matches m ON m.match_id=p.match_id "
            "WHERE p.champion_name='Ezreal' AND m.game_mode='ARAM'"
        )
        n, wsum = c.execute(
            "SELECT COUNT(*),COALESCE(SUM(p.win),0) " + base
        ).fetchone()
        n = int(n or 0)
        if not n:
            return []
        base_wr = 100.0 * wsum / n
        rows = c.execute(
            "SELECT p.item0,p.item1,p.item2,p.item3,p.item4,p.item5,p.win " + base
        ).fetchall()
        agg: dict[str, list[int]] = {}
        for r in rows:
            win = r[6]
            seen: set[str] = set()
            for it in r[:6]:
                if it and str(it) not in seen and int(it) > 0:
                    seen.add(str(it))
                    a = agg.setdefault(str(it), [0, 0])
                    a[0] += 1
                    a[1] += win
        allow = _AXIS_ITEM_IDS["manamune"]
        out: list[dict] = []
        for iid, (cnt, won) in agg.items():
            if iid not in allow or cnt < _EZREAL_MIN_N:
                continue
            wr = 100.0 * won / cnt
            if wr < base_wr - _EZREAL_BAND:
                continue
            rec = items.get(iid)
            if rec is None or not _is_terminal(rec) or _is_boots(rec):
                continue
            out.append({
                "id": iid, "name": rec.get("name", iid),
                "n": cnt, "wr": round(wr, 1),
                "lift_over_baseline": round(wr - base_wr, 1),
            })
        out.sort(key=lambda x: x["n"], reverse=True)
        return out
    finally:
        db.close()


def build() -> dict:
    items = _items_index()
    rows = _report_rows()
    champs: dict[str, dict] = {}
    for champ, axis in _CHAMP_AXIS.items():
        allow = _AXIS_ITEM_IDS[axis]
        picked: list[dict] = []
        if champ == "Ezreal":
            src = _ezreal_from_rewind(items)
        else:
            r = rows.get(champ)
            src = r.get("buried_winners", []) if r else []
        for b in src:
            iid = str(b.get("id"))
            if iid not in allow:
                continue
            if int(b.get("n") or 0) < _MIN_N:
                continue
            if float(b.get("lift_over_baseline") or 0.0) <= _MIN_LIFT and champ != "Ezreal":
                continue
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
            champs[champ] = {"axis": axis, "items": picked}
    return {
        "_meta": {
            "source": "DSP11 build_kit_axis_item_credit.py",
            "anchored_to": "ops/audit/ds_perm_swarm/report/dsp10_consolidated.json + rewind_history.db (Ezreal)",
            "ds_patch": _ds_patch(),
            "min_rewind_n": _MIN_N,
            "note": "DEFAULT-OFF prefer_kit_axis_by_win seam input. Cluster A excluded (operator-gated).",
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
            print("DRIFT: kit_axis_item_credit.json != fresh build", file=sys.stderr)
            return 2
        print("kit_axis_item_credit.json in sync")
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
