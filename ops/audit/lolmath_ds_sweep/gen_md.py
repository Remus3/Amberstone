#!/usr/bin/env python3
"""Pair lolmath (normal + ultimate) vs DS build_orders, emit Desktop gap-analysis MD."""
import collections
import json
from pathlib import Path

ROOT = r"C:/Riot Commander"
PATCH = "16.12.1"
# Desktop scratch inputs, resolved under THIS account's home rather than baked
# in: a probe naming another account's home silently finds nothing.
_DESKTOP = Path.home() / "Desktop"
SWEEP = str(_DESKTOP / "lolmath_ds_sweep" / "lolmath_sweep.json")
ULT = str(_DESKTOP / "lolmath_ds_sweep" / "ultimate_sweep.json")
OUT = str(_DESKTOP / "LOLMATH_VS_DS_SWEEP.md")

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

rows, mism, lowov, ult_diff, boot_lm, boot_ds, nocov = [], [], [], [], collections.Counter(), collections.Counter(), []
for cid in sorted(dsbo):
    ds_mixed = [iname(x) for x in dsbo[cid]["mixed"]["order"]]
    for b in ds_mixed:
        if b in BOOTS: boot_ds[b] += 1
    dd = champj.get(cid, {}).get("lolmath", {}).get("damage_distribution", {})
    kit = "AP" if dd.get("magical",0) > dd.get("physical",0) else "AD"
    nb = lm_norm.get(cid, []); ub = (lm_ult.get(cid) or {}).get("ultimate", [])
    # prefer ultimate as lolmath's canonical best-6; fall back to normal if ult missing
    lm_best = ub if len(ub) >= 5 else nb
    if len(lm_best) < 4:
        nocov.append(cid)
        rows.append((cid, kit, [], [], ds_mixed, "?", bdmg(ds_mixed), "-", "LOLMATH_NODATA", False)); continue
    for b in lm_best:
        if b in BOOTS: boot_lm[b] += 1
    lm_ap, lm_ad = counts(lm_best); ds_ap, ds_ad = counts(ds_mixed)
    overlap = sorted(set(lm_best) & set(ds_mixed) - BOOTS - {"No Item"})
    flags = []
    if lm_ap >= 2 and ds_ap == 0: flags.append("DS_AD_vs_LM_AP")
    if ds_ap >= 2 and lm_ap == 0: flags.append("DS_AP_vs_LM_AD")
    if len(overlap) <= 1 and not flags: lowov.append(cid)
    fl = ",".join(flags) if flags else "ok"
    if flags: mism.append(cid)
    cur = (lm_ult.get(cid) or {}).get("current", [])
    gold_changes = bool(cur and ub and len(ub) >= 5 and len(cur) >= 5
        and (set(x for x in ub if x not in BOOTS) != set(x for x in cur if x not in BOOTS)))
    if gold_changes: ult_diff.append(cid)
    rows.append((cid, kit, nb, ub, ds_mixed, bdmg(lm_best), bdmg(ds_mixed), "; ".join(overlap) or "-", fl, gold_changes))

nyi = ""
for r in sweep["results"]:
    if r.get("nyi"): nyi = r["nyi"].split("Stat Preference")[0].strip(); break

def sh(items):
    if not items: return "_(no data)_"
    return ", ".join(i.replace("'s","").replace("Lord Dominik Regards","LDR").replace("Blade of The Ruined King","BORK")
        .replace("Runaan Hurricane","Runaan").replace("Infinity Edge","IE").replace("Phantom Dancer","PD") for i in items)

covered = len([r for r in rows if r[3] or r[2]])
L = []
L += ["# lolmath vs Daemon Slayer - all-champion build sweep\n",
 f"lolmath patch label **26.12** (= DDragon **{PATCH}**, same live patch). DS SR build_orders ENGINE **{ds_engine}**, patch **{PATCH}**. "
 f"Covered {covered}/{len(rows)} champs; lolmath-no-data: {', '.join(nocov) or 'none'}.\n",
 "## Methodology\n",
 "- **lolmath**, headless render, no live game -> lolmath's **constant default enemy comp = Jayce / Sejuani / Annie / Lucian / Thresh** "
 "(4 squishy + 1 tank). Two lolmath builds captured per champ:\n",
 "  - **normal** = `Primary BUILD ORDER` (gold/cost-efficient purchase path).\n",
 "  - **ULTIMATE** = `ULTIMATE BUILD (GLOBAL OPTIMIZATION)` on the RESULTS tab - lolmath's cost-IGNORING best-six-item set "
 "(global pass that re-tests replacing every item for hidden synergies). **This is the fairest analog to DS's 6-item recommendation** "
 "and is the primary lolmath column below.\n",
 "- **DS** = static `build_orders_sr.json` `mixed` variant (synthetic neutral target: armor 80 / 2400 HP / 50-50 AD-AP). DS also ships "
 "`poke`/`burst_heavy`/`frontline_heavy` variants; DS does NOT take lolmath's 5-champ comp (see G6/G7).\n",
 "- **kit** = champ intrinsic type (lolmath magical vs physical dmg share). **lm/ds** = each side's *item* skew.\n",
 "\n## lolmath 'Not Yet Implemented' (verbatim from site)\n", f"> {nyi}\n",
 "Gaps lolmath itself declares - a shared-frontier checklist. DS already models some (Grievous Wounds, ARAM/Arena tenacity contexts); "
 "neither models Dragon Soul buffs or Infernal Cinder.\n",
 "\n## Systematic gaps (DS work items)\n",
 f"- **G1 Build-philosophy mismatch AP-vs-AD** ({len(mism)}): {', '.join(mism) or 'none'}. One tool builds >=2 of a damage type, "
 "the other builds **zero**. Where DS is AD on an AP-scaling kit (Gwen, Teemo, Rumble, ...), that is a DS archetype/scorer correctness "
 "bug (AP champ in an AD pool). Per-row flag `DS_AD_vs_LM_AP` / `DS_AP_vs_LM_AD`. **Highest priority.**\n",
 f"- **G2 Low overlap** ({len(lowov)} more champs, dmg-axis agrees but <=1 shared item): driven by G3-G6, not noise.\n",
 "- **G3 Runes** (DSP4, ENGINE 1.130.0): DS now SCORES self-rune procs into item value via the "
 "`rune_procs` / `core/rune_wpa.py` completion-rune seam (Shield Bash 8401; DEFAULT-OFF, "
 "`score_completion_runes=True`). The remaining gap is the full rune-PAGE EMITTER (lolmath emits a "
 "rune page per champ+comp) - a champ-select surface, not a build-order parity item; tracked FUTURE/live.\n",
 f"- **G4 Boots pool drift**: lolmath uses current 16.x upgraded boots; DS uses legacy boots. "
 f"lolmath boots: {', '.join(f'{k}({v})' for k,v in boot_lm.most_common())}. "
 f"DS boots: {', '.join(f'{k}({v})' for k,v in boot_ds.most_common())}.\n",
 "- **G5 Item pools**: lolmath freely uses lethality (Hubris, Serylda's, Umbral, Collector), AP on-hit (Nashor's, Riftmaker, Guinsoo's), "
 "and current mythic-less items; audit DS's per-archetype pool for missing entries.\n",
 f"- **G6 Gold-efficiency mode**: lolmath has an `IGNORE ITEM COST` toggle + the ULTIMATE BUILD (cost-ignoring global opt). "
 f"For **{len(ult_diff)}/{covered}** champs the cost-ignoring ultimate differs from the gold-aware normal build by >=1 item "
 "(usually dropping boots or a gold-efficient item for a pricier raw-stat / power-spike item) - so gold-efficiency actively shapes "
 "lolmath's normal recommendation. DS has **no cost model at all**: its order is a fixed list, neither gold-aware nor a cost-ignoring "
 "optimum. Full per-champ normal-vs-ultimate diff in the appendix below. **DSP9 Gemini-consult verdict: "
 "leave as FUTURE/BACKLOG** - a raw gold cost model conflicts with DS's empirical-WIN-data anchoring and "
 "the do-not-blind-build directive; the G7 harness confirms this axis (not comp/runes) is the residual driver.\n",
 "- **G7 Comp-aware exact-match harness** (DSP9, IMPLEMENTED `g7_comp_harness.py`): classifies lolmath's "
 "fixed comp (Jayce/Sejuani/Annie/Lucian/Thresh = 4 squishy + 1 tank -> `burst_heavy`) and scores the "
 "lolmath-vs-DS item overlap against EACH of DS's four comp-archetype variants instead of the blind "
 "`mixed`. FINDING: comp-matching does NOT close the residual - vs lolmath-ULTIMATE the mean overlap is "
 "frontline_heavy 2.00 / poke 1.86 / mixed 1.84 / burst_heavy 1.49, so the comp-matched variant tracks "
 "WORST. lolmath-ULTIMATE is the cost-IGNORING raw-stat pile, which aligns with the pricier-item variants "
 "regardless of comp shape. The residual is the **G6 cost-model** axis, not comp-awareness (or runes). "
 "Per-champ overlap matrix in `g7_comp_parity.json`.\n",
 "\n## Per-champion table (lolmath ULTIMATE vs DS mixed)\n",
 "`(g)` = lolmath ultimate differs from its gold-aware normal build (gold-efficiency mattered).\n",
 "| Champ | kit | lm | ds | lolmath ULTIMATE | DS mixed | overlap | flag |",
 "|---|---|---|---|---|---|---|---|"]
for cid, kit, nb, ub, dsm, lmd, dsd, ov, fl, gc in rows:
    mark = " **!!**" if "DS_A" in fl else (" (g)" if gc else "")
    best = ub if len(ub) >= 5 else nb
    L.append(f"| {cid}{mark} | {kit} | {lmd} | {dsd} | {sh(best)} | {sh(dsm)} | {ov} | {fl} |")
L += ["\n## Appendix: lolmath normal (gold-aware) where it differs from ultimate\n",
 "| Champ | normal (gold-aware) | ULTIMATE (cost-ignore) |", "|---|---|---|"]
for cid, kit, nb, ub, dsm, lmd, dsd, ov, fl, gc in rows:
    if gc:
        cur = (lm_ult.get(cid) or {}).get("current", [])
        normal_disp = nb if len(nb) >= 5 else cur
        L.append(f"| {cid} | {sh(normal_disp)} | {sh(ub)} |")

open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("WROTE", OUT, "| rows", len(rows), "covered", covered)
print("G1", len(mism), mism)
print("ult!=normal", len(ult_diff), ult_diff[:20])
print("nodata", nocov)
