"""
scripts/team_planner_sync.py

Pre-loads ALL S/A-tier comps into the Riot client Team Planner with matching names.
Run once while in the client lobby (not mid-game).

Import format discovered: POST /sets/{set}/teams/{team}/import
Body: plain JSON array of champion ID strings e.g. ["TFT17_Jhin","TFT17_Gnar",...]
"""
import json
import ssl
import base64
import urllib.request
import time
import sys
import uuid
from pathlib import Path

PROJECT  = Path(__file__).parent.parent
META_DIR = PROJECT / "data" / "meta"

lockfiles = [
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"C:\Riot Games\League of Legends\lockfile"),
]
lf = next((p for p in lockfiles if p.exists()), None)
if not lf:
    print("NO_LOCKFILE - launch League client first"); sys.exit(1)

parts    = lf.read_text().strip().split(":")
port, pw = parts[2], parts[3]
auth     = base64.b64encode(f"riot:{pw}".encode()).decode()
ctx      = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode    = ssl.CERT_NONE
hdrs = {"Authorization": f"Basic {auth}", "Accept": "application/json", "Content-Type": "application/json"}
BASE = f"https://192.168.8.237:{port}"

def lcu(method, ep, body=None, silent=False):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{ep}", data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(r, context=ctx, timeout=8) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:200]
        if not silent: print(f"  HTTP {e.code}: {msg}")
        return e.code, msg
    except Exception as e:
        if not silent: print(f"  ERR: {e}")
        return 0, str(e)

def champ_to_lcu_id(name: str) -> str:
    """Convert display name to LCU TFT17_ format."""
    clean = name.replace("'", "").replace(" ", "").replace(".", "")
    return f"TFT17_{clean}"

# Load meta
meta_file = META_DIR / "tft_set17_meta.json"
if not meta_file.exists():
    print("Meta file not found"); sys.exit(1)
meta = json.loads(meta_file.read_text(encoding="utf-8-sig"))

SET_ID = "TFTSet17"

# Collect S/A tier comps
tier_list = meta.get("tier_list", {})
comps_db  = meta.get("comps", {})
target_comps = []
for tier in ("S", "A"):
    for cd in tier_list.get(tier, []):
        name = cd.get("name", "?") if isinstance(cd, dict) else str(cd)
        if name in comps_db:
            target_comps.append((name, tier))

if not target_comps:
    print("No S/A tier comps found in meta"); sys.exit(1)

print(f"Syncing {len(target_comps)} comps to Team Planner ({SET_ID})...\n")

created = 0
failed  = 0
created_uuids = []  # track for capacity rotation

for comp_name, tier in target_comps:
    comp_data = comps_db[comp_name]
    lv9 = comp_data.get("lv9") or comp_data.get("core_units", []) + comp_data.get("flex_units", [])

    # Stable UUID per comp name
    team_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"riot-commander.{comp_name}"))

    # Step 1: Create team slot (idempotent - 409 if exists)
    lcu("POST", f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{team_uuid}", silent=True)

    # Step 2: Clear existing champions
    lcu("DELETE", f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{team_uuid}/champions", silent=True)
    time.sleep(0.05)

    # Step 3: Import champions as string array (correct format)
    champ_ids = [champ_to_lcu_id(u) for u in lv9[:10]]
    s, b = lcu("POST",
               f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{team_uuid}/import",
               champ_ids)
    # If at capacity, delete oldest created team and retry once
    if s == 400 and "capacity" in b.lower():
        oldest = created_uuids[0] if created_uuids else None
        if oldest and oldest != team_uuid:
            lcu("DELETE", f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{oldest}", silent=True)
            created_uuids.pop(0)
            s, b = lcu("POST",
                       f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{team_uuid}/import",
                       champ_ids, silent=True)
    if s in (200, 201, 204):
        created_uuids.append(team_uuid)
        # Step 4: Set team name
        lcu("PATCH",
            f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{team_uuid}/name",
            {"name": comp_name[:24]},
            silent=True)
        print(f"  [{tier}] {comp_name}: * import OK ({len(champ_ids)} units)")
        created += 1
    else:
        # Fallback: individual adds
        ok = 0
        for cid in champ_ids:
            sc, _ = lcu("POST",
                f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{team_uuid}/champions/{cid}",
                silent=True)
            if sc in (200, 201, 204):
                ok += 1
        lcu("PATCH",
            f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{team_uuid}/name",
            {"name": comp_name[:24]},
            silent=True)
        if ok > 0:
            print(f"  [{tier}] {comp_name}: * individual adds ({ok}/{len(champ_ids)})")
            created += 1
        else:
            print(f"  [{tier}] {comp_name}: * FAILED")
            failed += 1

    time.sleep(0.15)

print(f"\nDone: {created} synced, {failed} failed")
print("Open Team Planner in the client to see all comps!")
