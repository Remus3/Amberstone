"""
scripts/discover_champion_codes.py
Discovers Set 17 champion team_planner_codes by probing the LCU API.
Uses dynamic team_id from previous-context (no hardcoding).
"""
import json
import ssl
import base64
import urllib.request
import time
import sys
from pathlib import Path

PROJECT  = Path(__file__).parent.parent
META_DIR = PROJECT / "data" / "meta"

lockfiles = [
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"C:\Riot Games\League of Legends\lockfile"),
]
lf = next((p for p in lockfiles if p.exists()), None)
if not lf:
    print("NO_LOCKFILE — launch League client first"); sys.exit(1)

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
        with urllib.request.urlopen(r, context=ctx, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        if not silent: pass
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return 0, str(e)

# --- Get dynamic team_id ---
s, b = lcu("GET", "/lol-tft-team-planner/v1/previous-context")
if s != 200:
    print(f"Cannot get previous-context: HTTP {s}"); sys.exit(1)
prev = json.loads(b)
TEAM_ID = prev.get("optionalTeamId", "")
SET_ID  = prev.get("setId", "TFTSet17")
print(f"Using team_id={TEAM_ID}  set={SET_ID}")

def get_code():
    s, b = lcu("POST", f"/lol-tft-team-planner/v1/sets/{SET_ID}/team-code/{TEAM_ID}")
    if s == 200:
        return b.strip().strip('"')
    return None

def clear_team():
    lcu("DELETE", f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{TEAM_ID}/champions")
    time.sleep(0.2)

# --- Champions to discover ---
CHAMPIONS = [
    "Aatrox","Caitlyn","Talon","Twisted Fate","Poppy","Veigar",
    "Chogath","Lissandra","Leona","Teemo","Nasus",
    "Akali","Jax","Gnar","Meepsie","Mordekaiser","Shen","Ezreal","Diana",
    "Maokai","Lulu","Fizz","Illaoi","KaiSa","MissFortune","Ornn",
    "Urgot","Nami","Viktor","Rhaast",
    "Kindred","Nunu","Xayah","Corki","Rammus","Karma","Riven",
    "AurelionSol","TheMightyMech","Pantheon","Sona","TahmKench",
    "Samira","Morgana","LeBlanc",
    "Bard","Jhin","Fiora","Graves","Blitzcrank","MasterYi","Pyke","Aurora",
    "BelVeth","Briar","Jinx","Gragas","Gwen","Ekko","RekSai",
    "TwistedFate","Meepsie",
]
DISPLAY = {
    "Chogath":"Cho'Gath","KaiSa":"Kai'Sa","MissFortune":"Miss Fortune",
    "AurelionSol":"Aurelion Sol","TheMightyMech":"The Mighty Mech",
    "TahmKench":"Tahm Kench","MasterYi":"Master Yi",
    "BelVeth":"Bel'Veth","RekSai":"Rek'Sai","TwistedFate":"Twisted Fate",
}

clear_team()
baseline = get_code()
if not baseline:
    print("ERROR: Cannot get baseline code — is the client in a game?")
    sys.exit(1)
print(f"Baseline: {baseline}")

results = {}
# Load existing codes so we don't re-probe already-known ones
codes_file = META_DIR / "tft_set17_champion_codes.json"
if codes_file.exists():
    results = json.loads(codes_file.read_text(encoding="utf-8"))
    print(f"Loaded {len(results)} existing codes\n")

seen = set()
for clean in CHAMPIONS:
    if clean in seen:
        continue
    seen.add(clean)
    display = DISPLAY.get(clean, clean)
    if display in results:
        continue  # already known

    clear_team()
    found = False
    for fmt in [f"TFT17_{clean}", f"TFT17_{clean.replace('The','')}", clean]:
        s, b = lcu("POST",
            f"/lol-tft-team-planner/v1/sets/{SET_ID}/teams/{TEAM_ID}/champions/{fmt}",
            silent=True)
        if s in (200, 201, 204):
            time.sleep(0.15)
            code = get_code()
            if code and len(code) > 5:
                prefix = code[2:5]
                if prefix != "000":
                    num = int(prefix, 16)
                    results[display] = num
                    print(f"  {display}: {num} (0x{prefix})")
                    found = True
                    break
        time.sleep(0.06)
    if not found:
        print(f"  {display}: NOT FOUND")

out = META_DIR / "tft_set17_champion_codes.json"
out.write_text(json.dumps(results, indent=2, sort_keys=True))
print(f"\nWrote {len(results)} codes to {out}")
