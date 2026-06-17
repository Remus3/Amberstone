"""DS comprehensive cross-eval - deterministic per-champion data harness.

ONE analysis unit per champion (never grouped). Emits un-fakeable scorer +
rewind_history.db data so the per-champion judge agent anchors its verdict on
ground truth, not eyeballed rankings (the seed lesson:
ops/audit/DS_BRUISER_DAMAGE_TYPE_2026-06-16.md).

Gate (Gemini-locked 2026-06-16):
  D1 report-first (nominate retunes, no blind change).
  D2 anchor = rewind WIN outcomes; owned-side(operator) n>=8 -> outcome_self,
     elif all-player n>=8 -> outcome_all, else synthetic.
  D3 self-rune procs only (burst/assassin); enemy/ally runes OUT (no scorer surface).
  RISK = isolate ARAM modifiers from SR: mode-SEGREGATED anchor + mode-matched
     scorer call (scorer applies ARAM mods when mode=ARAM).

Read-only. No engine change. ASCII only.

Usage: python tools/ds_cross_eval/probe_champion.py <Champion> [--out DIR]
Writes <out>/data/<canon>.json. Prints the JSON path.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"C:/Riot Commander")
sys.path.insert(0, str(ROOT))

from core.archetype_picks import canonical_champion_id, get_archetype_for  # noqa: E402
from core.daemon_slayer_client import rank_for_primary_archetype  # noqa: E402

DB = ROOT / "data" / "rewind_history.db"
DS_PATCH_FILE = ROOT / "data" / "daemon_slayer" / "current.txt"
OPERATOR = "SamplePlayer"  # owned-side; taglines Vayne(old)+Trist(new)

# scorer mode -> DB game_mode
MODE_DB = {"ARAM": "ARAM", "SR": "CLASSIC"}

# comp grid: (label, ad_share, ap_share, armor, mr, max_hp)
SQUISHY = dict(armor=60.0, mr=50.0, max_hp=1800.0)
TANKY = dict(armor=180.0, mr=150.0, max_hp=3500.0)
GRID = [
    ("ad_squishy", 0.85, 0.10, SQUISHY),
    ("bal_squishy", 0.50, 0.50, SQUISHY),
    ("ap_squishy", 0.10, 0.85, SQUISHY),
    ("ad_tanky", 0.85, 0.10, TANKY),
    ("ap_tanky", 0.10, 0.85, TANKY),
]
LEVEL = 13


def _ds_patch() -> str:
    try:
        return DS_PATCH_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _item_names() -> dict:
    patch = _ds_patch()
    for p in (
        ROOT / "data" / "meta_build" / "ddragon" / patch / "item.json",
        ROOT / "data" / "meta_build" / "ddragon" / "16.12.1" / "item.json",
    ):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            return {k: v.get("name", k) for k, v in j.get("data", {}).items()}
        except Exception:
            continue
    return {}


def _resolve_db_name(canon: str, db_names: set) -> str:
    if canon in db_names:
        return canon
    low = {n.lower(): n for n in db_names}
    return low.get(canon.lower(), canon)  # FiddleSticks vs Fiddlesticks


def _score_field(row: dict) -> float:
    for k in ("hybrid_delta_pct", "delta", "delta_dps"):
        if k in row and row[k] is not None:
            return float(row[k])
    return 0.0


def _rank_cell(canon: str, archetype: str, mode: str, ad: float, ap: float,
               prof: dict) -> list:
    r = rank_for_primary_archetype(
        canon, archetype, level=LEVEL, item_ids=[], mode=mode,
        target_armor=prof["armor"], target_mr=prof["mr"],
        target_max_hp=prof["max_hp"], target_bonus_hp=0.0,
        target_current_hp_pct=1.0,
        enemy_ad_share=ad, enemy_ap_share=ap, top=40,
    )
    if not r or not r.get("ok"):
        return [], None
    out = []
    for i, row in enumerate(r.get("ranked", [])):
        out.append({
            "rank": i + 1,
            "id": row.get("item_id"),
            "name": row.get("item_name"),
            "score": round(_score_field(row), 4),
            "d_ehp": round(float(row.get("delta_ehp", 0.0) or 0.0), 1),
            "d_dps": round(float(row.get("delta_dps", 0.0) or 0.0), 1),
            "gold": row.get("gold"),
        })
    return out, r.get("scorer")


def _responsiveness(cell_ad: list, cell_ap: list) -> dict:
    """Data-driven comp responsiveness: per-item rank shift ad_heavy->ap_heavy.

    Positive shift = item rose as AP share rose (MR-like). If the top mover's
    shift is small the scorer is comp-blind for this champ (the seed concern).
    """
    rank_ad = {c["name"]: c["rank"] for c in cell_ad}
    rank_ap = {c["name"]: c["rank"] for c in cell_ap}
    shifts = []
    for name in set(rank_ad) & set(rank_ap):
        shift = rank_ad[name] - rank_ap[name]  # +ve = rose when AP up
        shifts.append((shift, name))
    shifts.sort(reverse=True)
    risers = [{"name": n, "shift": s} for s, n in shifts[:5] if s > 0]
    fallers = [{"name": n, "shift": s} for s, n in shifts[-5:] if s < 0]
    max_shift = shifts[0][0] if shifts else 0
    return {
        "max_positive_shift": max_shift,
        "top_risers_when_ap": risers,
        "top_fallers_when_ap": list(reversed(fallers)),
        "comp_blind": max_shift < 3,  # heuristic flag for the judge
    }


def _empirical(db: sqlite3.Connection, db_name: str, names: dict) -> dict:
    c = db.cursor()
    out = {}
    for smode, gmode in MODE_DB.items():
        modeblk = {}
        for scope in ("self", "all"):
            where = "p.champion_name=? AND m.game_mode=?"
            params = [db_name, gmode]
            if scope == "self":
                where += " AND p.riot_id_game_name=?"
                params.append(OPERATOR)
            base = (
                "FROM participants p JOIN matches m ON m.match_id=p.match_id "
                "WHERE " + where
            )
            n, wsum = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(p.win),0) " + base, params
            ).fetchone()
            n = int(n or 0)
            wr = round(100.0 * wsum / n, 1) if n else None
            # item winrate: each completed item slot, n>=5
            items = []
            if n >= 1:
                for slot in range(6):  # item0..item5 (exclude trinket item6)
                    pass
                # single pass via UNION-like python aggregation
                rows = c.execute(
                    "SELECT p.item0,p.item1,p.item2,p.item3,p.item4,p.item5,p.win "
                    + base, params
                ).fetchall()
                agg = {}
                for r in rows:
                    win = r[6]
                    seen = set()
                    for it in r[:6]:
                        if it and it not in seen and int(it) > 0:
                            seen.add(it)
                            a = agg.setdefault(str(it), [0, 0])
                            a[0] += 1
                            a[1] += win
                for iid, (cnt, won) in agg.items():
                    if cnt >= 5:
                        items.append({
                            "id": iid, "name": names.get(iid, iid),
                            "n": cnt, "wr": round(100.0 * won / cnt, 1),
                        })
                items.sort(key=lambda x: x["n"], reverse=True)
                items = items[:10]
            modeblk[scope] = {"n": n, "wr": wr, "items": items}
        out[smode] = modeblk
    return out


def _evidence_tier(emp: dict) -> dict:
    tiers = {}
    for smode in ("ARAM", "SR"):
        m = emp.get(smode, {})
        if m.get("self", {}).get("n", 0) >= 8:
            tiers[smode] = "outcome_self"
        elif m.get("all", {}).get("n", 0) >= 8:
            tiers[smode] = "outcome_all"
        else:
            tiers[smode] = "synthetic"
    return tiers


def probe(champion: str) -> dict:
    canon = canonical_champion_id(champion) or champion
    arch = get_archetype_for(canon) or {}
    primary = arch.get("primary", "carry")
    secondary = arch.get("secondary")
    names = _item_names()
    db = sqlite3.connect(str(DB))
    db_names = set(r[0] for r in db.execute(
        "SELECT DISTINCT champion_name FROM participants"))
    db_name = _resolve_db_name(canon, db_names)
    emp = _empirical(db, db_name, names)
    tiers = _evidence_tier(emp)
    db.close()

    # comp grid on PRIMARY archetype, mode-matched to the richer anchor mode
    anchor_mode = "ARAM" if tiers.get("ARAM") != "synthetic" else "SR"
    grid_full = {}
    grid = {}
    scorer_name = None
    for label, ad, ap, prof in GRID:
        cell, sc = _rank_cell(canon, primary, anchor_mode, ad, ap, prof)
        scorer_name = sc or scorer_name
        grid_full[label] = cell          # full 40-deep (seed: movement at 14-60)
        grid[label] = cell[:12]          # display payload

    # comp axis depends on the scorer. EHP-bearing scorers (tank=ehp,
    # bruiser=hybrid) SHOULD respond to enemy DAMAGE TYPE. DPS/burst scorers
    # respond to TARGET RESIST (squishy vs tanky target), not enemy mix.
    ehp_bearing = scorer_name in ("ehp", "hybrid")
    dmg_type_resp = _responsiveness(
        grid_full.get("ad_squishy", []), grid_full.get("ap_squishy", []))
    target_resist_resp = _responsiveness(
        grid_full.get("ad_squishy", []), grid_full.get("ad_tanky", []))
    primary_axis = "enemy_damage_type" if ehp_bearing else "target_resist"
    primary_resp = dmg_type_resp if ehp_bearing else target_resist_resp
    resp = {
        "primary_axis": primary_axis,
        "comp_blind": primary_resp["comp_blind"],
        "enemy_damage_type": dmg_type_resp,
        "target_resist": target_resist_resp,
    }

    rune_relevant = scorer_name in ("burst",) or primary == "assassin"

    return {
        "champion": canon,
        "db_name": db_name,
        "archetype": {"primary": primary, "secondary": secondary,
                      "source": arch.get("source")},
        "scorer": scorer_name,
        "anchor_mode": anchor_mode,
        "evidence_tier": tiers,
        "comp_grid": grid,
        "responsiveness": resp,
        "rune_relevant": rune_relevant,
        "empirical": emp,
        "level": LEVEL,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("champion")
    ap.add_argument("--out", default=str(ROOT / "ops" / "audit" / "ds_cross_eval"))
    a = ap.parse_args()
    data = probe(a.champion)
    outdir = Path(a.out) / "data"
    outdir.mkdir(parents=True, exist_ok=True)
    fp = outdir / (data["champion"] + ".json")
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(fp)
    print(str(fp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
