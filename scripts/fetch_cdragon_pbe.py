"""Fetch Set 17 data from CommunityDragon PBE and extract champion codes + traits."""
import urllib.request
import json
import ssl
import sys
from pathlib import Path

PROJECT = Path(r"C:\Riot Commander")
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
hdrs = {"User-Agent": "Mozilla/5.0"}

def fetch(url):
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

# --- Team planner codes (real Set 17 IDs) ---
print("Fetching team planner data...")
try:
    raw = fetch("https://raw.communitydragon.org/pbe/plugins/rcp-be-lol-game-data/global/default/v1/tftchampions-teamplanner.json")
    # Save raw
    (PROJECT / "data" / "meta" / "cdragon_teamplanner_pbe.json").write_text(raw, encoding="utf-8")
    data = json.loads(raw)
    print(f"  Got {len(data) if isinstance(data,list) else 'dict'} entries")
    # Extract Set 17 champions
    codes = {}
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                cid = entry.get("character_id", "")
                name = entry.get("display_name", "")
                code = entry.get("team_planner_code")
                if cid.startswith("TFT17_") or cid.startswith("TFT_Set17_"):
                    if name and code is not None:
                        codes[name] = code
                        print(f"  Set17: {name} -> {code}")
    elif isinstance(data, dict):
        # Might be nested
        for k, v in (data.items() if isinstance(data, dict) else []):
            print(f"  Key: {k} -> {str(v)[:100]}")
    
    if codes:
        # Merge with existing codes
        existing_file = PROJECT / "data" / "meta" / "tft_set17_champion_codes.json"
        existing = json.loads(existing_file.read_text()) if existing_file.exists() else {}
        merged = {**existing, **codes}
        existing_file.write_text(json.dumps(merged, indent=2, sort_keys=True))
        print(f"\nMerged {len(codes)} CDragon codes into {len(merged)} total")
    else:
        print("  No Set17 champions found - checking structure...")
        if isinstance(data, list) and data:
            print(f"  First entry: {data[0]}")
        elif isinstance(data, dict):
            print(f"  Keys: {list(data.keys())[:10]}")

except Exception as e:  # noqa: BLE001
    print(f"team planner FAILED: {e}")

# --- TFT en_us.json (champions, traits, items) ---
print("\nFetching TFT en_us data...")
try:
    raw2 = fetch("https://raw.communitydragon.org/pbe/cdragon/tft/en_us.json")
    (PROJECT / "data" / "meta" / "cdragon_tft_pbe.json").write_text(raw2, encoding="utf-8")
    data2 = json.loads(raw2)
    print(f"  Keys: {list(data2.keys())[:15]}")
    # Look for champions
    if "champions" in data2:
        champs = data2["champions"]
        print(f"  Champions: {len(champs)}")
        # Find Set 17 champions
        s17 = [c for c in champs if isinstance(c, dict) and ("TFT17" in str(c.get("characterName","")) or "set17" in str(c.get("setId","")).lower())]
        print(f"  Set 17 champs: {len(s17)}")
        if s17:
            print("  Sample:", json.dumps(s17[0], indent=2)[:400])
    if "traits" in data2:
        traits = data2["traits"]
        s17t = [t for t in (traits if isinstance(traits, list) else []) if "TFT17" in str(t)]
        print(f"  Set 17 traits: {len(s17t)}")
        if s17t: print("  Sample traits:", [t.get("name","?") for t in s17t[:10] if isinstance(t,dict)])
    if "items" in data2:
        print(f"  Items: {len(data2['items'])}")
except Exception as e:  # noqa: BLE001
    print(f"TFT en_us FAILED: {e}")
    import traceback; traceback.print_exc()
