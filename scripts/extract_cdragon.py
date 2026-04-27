"""
Full Set 17 data extraction from CommunityDragon PBE.
Extracts: all champions with costs/traits, all traits, team planner codes.
Updates meta JSON unit_costs and champion list.
"""
import json
from pathlib import Path

PROJECT = Path(r"C:\Riot Commander")
META    = PROJECT / "data" / "meta"

# --- Load CDragon files ---
tp_data  = json.loads((META / "cdragon_teamplanner_pbe.json").read_text(encoding="utf-8"))
tft_data = json.loads((META / "cdragon_tft_pbe.json").read_text(encoding="utf-8"))

# --- Champion codes from team planner ---
s17_tp = tp_data.get("TFTSet17", [])
cdragon_codes = {}
for entry in s17_tp:
    if not isinstance(entry, dict): continue
    name = entry.get("display_name", "")
    code = entry.get("team_planner_code")
    if name and code is not None:
        cdragon_codes[name] = code

print(f"CDragon team planner codes: {len(cdragon_codes)}")
print(sorted(cdragon_codes.items())[:20])

# --- Champion data from en_us.json ---
set_data_list = tft_data.get("setData", tft_data.get("sets", []))
s17_data = None
for s in set_data_list:
    if isinstance(s, dict) and (s.get("number") == 17 or "Set17" in str(s.get("mutator", ""))):
        if len(s.get("champions", [])) > 60:  # prefer the richer one
            s17_data = s
            break

if not s17_data:
    # fallback: find biggest Set17
    s17_candidates = [s for s in set_data_list if isinstance(s,dict) and s.get("number")==17]
    s17_data = max(s17_candidates, key=lambda s: len(s.get("champions",[])), default=None)

if not s17_data:
    print("ERROR: No Set17 data found"); exit(1)

print(f"\nSet17 champions: {len(s17_data.get('champions',[]))}")
print(f"Set17 traits:    {len(s17_data.get('traits',[]))}")

# --- Extract champions ---
unit_costs = {}     # name -> cost (tier)
unit_traits = {}    # name -> [trait1, trait2, ...]
playable = []       # list of playable champion names

SKIP_TIERS = {8, 9, 10, 11}  # non-playable (anvils, chests, etc.)
for c in s17_data.get("champions", []):
    if not isinstance(c, dict): continue
    name  = c.get("name", "")
    cost  = c.get("cost", c.get("tier", 0))
    traits= c.get("traits", [])
    if not name or cost in SKIP_TIERS or not traits: continue
    unit_costs[name]  = cost
    unit_traits[name] = traits
    playable.append(name)

print(f"Playable champions: {len(playable)}")
for n in sorted(playable):
    print(f"  {n}: {unit_costs[n]}g  traits={unit_traits[n]}")

# --- Extract all traits ---
all_traits = set()
for t in s17_data.get("traits", []):
    if isinstance(t, dict) and t.get("name"):
        all_traits.add(t["name"])
print(f"\nAll traits ({len(all_traits)}): {sorted(all_traits)}")

# --- Merge team planner codes ---
existing_codes = json.loads((META / "tft_set17_champion_codes.json").read_text())
new_added = 0
for name, code in cdragon_codes.items():
    if name not in existing_codes:
        existing_codes[name] = code
        new_added += 1
        print(f"  NEW code: {name} -> {code}")
(META / "tft_set17_champion_codes.json").write_text(json.dumps(existing_codes, indent=2, sort_keys=True))
print(f"\nCodes: {len(existing_codes)} total ({new_added} new from CDragon)")

# --- Update meta JSON ---
meta_file = META / "tft_set17_meta.json"
meta = json.loads(meta_file.read_text(encoding="utf-8-sig"))

# Update unit_costs
meta["unit_costs"] = unit_costs
meta["unit_traits"] = unit_traits
meta["all_traits"] = sorted(all_traits)

# Update champion list in vision analysis (for validation)
meta["champions_set17"] = sorted(playable)

meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Meta updated: unit_costs={len(unit_costs)}, traits={len(all_traits)}, champions={len(playable)}")
