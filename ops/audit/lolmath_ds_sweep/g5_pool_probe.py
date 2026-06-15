"""G5 pool-gap diagnosis (v2, alias-aware).

The DDragon item.json carries DUPLICATE records per item: a canonical short
id (map 11 = SR-legal) AND one or more 6-digit "22.."/"12.." Arena/alias ids
(map 11 = False). v1 mis-indexed names to the alias and falsely reported
items as out-of-pool. v2 collects ALL ids per name and asks: does ANY id for
this name pass the _filter_candidates gates (purchasable + terminal + map11)?
If yes -> in pool (so a no-show is scorer valuation, not a pool gap). If no
id is map11-legal -> a real pool gap.

Also resolves what DS actually recommends from the HZ-B1 precompute table the
sweep used: data/daemon_slayer/build_orders/<patch>/build_orders_sr.json.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\Riot Commander")
DS_DATA = ROOT / "data" / "daemon_slayer"
PATCH = (DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
ITEMS = json.loads((DS_DATA / PATCH / "items.json").read_text(encoding="utf-8"))["data"]

LOLMATH_FAVORED = [
    "Hubris", "The Collector", "Serylda's Grudge", "Profane Hydra",
    "Youmuu's Ghostblade", "Voltaic Cyclosword", "Axiom Arc", "Umbral Glaive",
    "Bastionbreaker", "Black Cleaver", "Death's Dance", "Spear of Shojin",
    "Ravenous Hydra", "Experimental Hexplate", "Manamune", "Guardian Angel",
    "Nashor's Tooth", "Riftmaker", "Guinsoo's Rageblade", "Lich Bane",
    "Liandry's Torment", "Blackfire Torch", "Cosmic Drive", "Cryptbloom",
    "Hextech Gunblade", "Archangel's Staff", "Zhonya's Hourglass",
    "Rabadon's Deathcap", "Shadowflame", "Stormsurge", "Void Staff",
    "Titanic Hydra", "Hollow Radiance", "Dead Man's Plate", "Sunfire Aegis",
    "Heartsteel", "Warmog's Armor", "Spirit Visage", "Kaenic Rookern",
    "Unending Despair", "Force of Nature", "Banshee's Veil",
    "Solstice Sleigh", "Bloodsong", "Dream Maker", "Celestial Opposition",
    "Locket of the Iron Solari", "Dawncore",
]

MODE_MAP_ID = {"SR": "11", "ARAM": "12", "ARENA": "30"}


def _purchasable(rec):
    g = rec.get("gold") or {}
    return bool(g.get("purchasable")) and int(g.get("total", 0) or 0) > 0


def _terminal(rec):
    return not rec.get("into")


def _legal(rec, mode):
    return bool((rec.get("maps") or {}).get(MODE_MAP_ID[mode]))


def _in_pool(rec, mode="SR"):
    return _purchasable(rec) and _terminal(rec) and _legal(rec, mode)


# name -> [ids]
ids_by_name = defaultdict(list)
for iid, rec in ITEMS.items():
    ids_by_name[rec.get("name")].append(iid)

# what DS recommends in the HZ-B1 sweep table (all variants, all champs)
bo = json.loads(
    (DS_DATA / "build_orders" / PATCH / "build_orders_sr.json").read_text(encoding="utf-8")
)["build_orders"]
ds_recd_ids = set()
for champ, variants in bo.items():
    for variant, cell in variants.items():
        ds_recd_ids.update(str(i) for i in (cell.get("order") or []))
ds_recd_names = {ITEMS[i]["name"] for i in ds_recd_ids if i in ITEMS}

print(f"PATCH={PATCH}  items={len(ITEMS)}  ds_distinct_recd_ids={len(ds_recd_ids)} "
      f"names={len(ds_recd_names)}")
print(f"{'item':28} {'pool-id':9} {'mode-legal':10} {'recd?':6} note")
print("-" * 80)
real_gap = []
in_pool_unrec = []
for nm in LOLMATH_FAVORED:
    ids = ids_by_name.get(nm, [])
    if not ids:
        print(f"{nm:28} {'--':9} {'MISSING':10}")
        continue
    pool_ids = [i for i in ids if _in_pool(ITEMS[i], "SR")]
    legal_modes = [m for m in ("SR", "ARAM", "ARENA")
                   if any(_in_pool(ITEMS[i], m) for i in ids)]
    recd = nm in ds_recd_names
    if pool_ids:
        pid = pool_ids[0]
        note = "" if recd else "<- in SR pool, NEVER recommended"
        print(f"{nm:28} {pid:9} {'/'.join(legal_modes):10} {('Y' if recd else 'n'):6} {note}")
        if not recd:
            in_pool_unrec.append(nm)
    else:
        note = f"all {len(ids)} ids map11=False; legal in {legal_modes or 'NONE'}"
        print(f"{nm:28} {'NONE':9} {'/'.join(legal_modes) or '-':10} {'-':6} {note}")
        real_gap.append((nm, legal_modes))

print("\n=== SUMMARY ===")
print(f"REAL SR pool gap (no map11 id exists): {len(real_gap)}")
for nm, lm in real_gap:
    print(f"  {nm}  (legal in {lm or 'NONE'})")
print(f"\nin SR pool but NEVER recommended (scorer valuation): {len(in_pool_unrec)}")
print("  " + ", ".join(in_pool_unrec))
