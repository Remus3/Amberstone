#!/usr/bin/env python3
"""G2 low-overlap RE-MEASURE (P6 item 425). In-repo paths, post-G1/G4 build_orders.

Re-runs the gen_md.py pairing at the CURRENT engine build to see how the G1 axis
fix (item 421) + G4 boots refresh (item 423) redistributed the low-overlap set.
Prints the G1 residual + the G2 low-overlap set + a per-champ axis/overlap dump.
Tier-0 diagnosis only; reads static tables, no engine change.

Usage: python g2_remeasure_probe.py [PATCH]
"""
import collections
import json
import sys

ROOT = r"C:/Riot Commander"
PATCH = sys.argv[1] if len(sys.argv) > 1 else "16.12.1"
HERE = f"{ROOT}/ops/audit/lolmath_ds_sweep"
SWEEP = f"{HERE}/lolmath_sweep.json"
ULT = f"{HERE}/ultimate_sweep.json"

itemj = json.load(open(f"{ROOT}/data/meta_build/ddragon/{PATCH}/item.json", encoding="utf-8"))["data"]
champj = json.load(open(f"{ROOT}/data/daemon_slayer/{PATCH}/champions.json", encoding="utf-8"))["data"]
dsraw = json.load(open(f"{ROOT}/data/daemon_slayer/build_orders/{PATCH}/build_orders_sr.json", encoding="utf-8"))
ds_engine = dsraw.get("engine_version"); dsbo = dsraw["build_orders"]
sweep = json.load(open(SWEEP, encoding="utf-8"))
ult = json.load(open(ULT, encoding="utf-8"))

name2id = {v.get("name", "").lower(): k for k, v in itemj.items()}
def iname(i): return itemj.get(str(i), {}).get("name", str(i))
def itags(name):
    iid = name2id.get(name.lower()); return set(itemj.get(str(iid), {}).get("tags", [])) if iid else set()
BOOTS = {"Boots","Berserker's Greaves","Plated Steelcaps","Mercury's Treads","Ionian Boots of Lucidity",
 "Boots of Swiftness","Sorcerer's Shoes","Gluttonous Greaves","Swiftmarch","Spellslinger's Shoes",
 "Armored Advance","Crimson Lucidity","Chainlaced Crushers","Forever Forward","Synchronized Souls","Boots of Mobility"}
def dmgclass(name):
    if name in BOOTS or name == "No Item": return "n"
    t = itags(name)
    if "SpellDamage" in t: return "ap"
    if "Damage" in t or "CriticalStrike" in t or "AttackSpeed" in t: return "ad"
    return "n"
def counts(items):
    c = collections.Counter(dmgclass(i) for i in items); return c.get("ap",0), c.get("ad",0)
def bdmg(items):
    ap, ad = counts(items); return "AP" if ap > ad else ("AD" if ad > ap else "-")

def norm(s): return "".join(ch for ch in s.lower() if ch.isalnum())
ALIAS = {"wukong":"MonkeyKing","nunuandwillump":"Nunu","nunu":"Nunu","renataglasc":"Renata","renata":"Renata"}
id_norm = {norm(k): k for k in dsbo}
def slug2id(slug):
    n = norm(slug); return ALIAS.get(n) or id_norm.get(n)

lm_norm = {}; lm_ult = {}
for r in sweep["results"]:
    cid = slug2id(r["slug"])
    if cid: lm_norm[cid] = r["build_order"]
for r in ult["results"]:
    cid = slug2id(r["slug"])
    if cid: lm_ult[cid] = {"ultimate": r.get("ultimate", []), "current": r.get("current", [])}

mism, lowov, nocov, ok = [], [], [], []
lowov_detail = []
for cid in sorted(dsbo):
    ds_mixed = [iname(x) for x in dsbo[cid]["mixed"]["order"]]
    dd = champj.get(cid, {}).get("lolmath", {}).get("damage_distribution", {})
    kit = "AP" if dd.get("magical",0) > dd.get("physical",0) else "AD"
    nb = lm_norm.get(cid, []); ub = (lm_ult.get(cid) or {}).get("ultimate", [])
    lm_best = ub if len(ub) >= 5 else nb
    if len(lm_best) < 4:
        nocov.append(cid); continue
    lm_ap, lm_ad = counts(lm_best); ds_ap, ds_ad = counts(ds_mixed)
    overlap = sorted(set(lm_best) & set(ds_mixed) - BOOTS - {"No Item"})
    flags = []
    if lm_ap >= 2 and ds_ap == 0: flags.append("DS_AD_vs_LM_AP")
    if ds_ap >= 2 and lm_ap == 0: flags.append("DS_AP_vs_LM_AD")
    if flags:
        mism.append(cid)
    elif len(overlap) <= 1:
        lowov.append(cid)
        lowov_detail.append((cid, kit, len(overlap), ", ".join(overlap) or "-"))
    else:
        ok.append(cid)

covered = len(mism) + len(lowov) + len(ok)
print(f"=== G2 RE-MEASURE @ ENGINE {ds_engine} / patch {PATCH} ===")
print(f"covered={covered}  ok={len(ok)}  G1_residual={len(mism)}  G2_lowov={len(lowov)}  nodata={len(nocov)}")
print(f"\nG1 residual ({len(mism)}): {', '.join(mism) or 'none'}")
print(f"\nG2 low-overlap ({len(lowov)}):")
for cid, kit, n, ov in lowov_detail:
    print(f"  {cid:18} kit={kit} overlap={n}  [{ov}]")
print(f"\nnodata ({len(nocov)}): {', '.join(nocov) or 'none'}")
