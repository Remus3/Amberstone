"""Probe remaining missing champion codes with more variants."""
import json
import ssl
import base64
import urllib.request
import time
from pathlib import Path

lockfiles = [
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"C:\Riot Games\League of Legends\lockfile"),
]
lf = next((p for p in lockfiles if p.exists()), None)
if not lf:
    print("NO_LOCKFILE"); exit()

parts = lf.read_text().strip().split(":")
port, pw = parts[2], parts[3]
auth = base64.b64encode(f"riot:{pw}".encode()).decode()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
hdrs = {"Authorization": f"Basic {auth}", "Accept": "application/json", "Content-Type": "application/json"}
BASE = f"https://192.168.8.237:{port}"

def lcu(m, ep, b=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(f"{BASE}{ep}", data=d, headers=hdrs, method=m)
    try:
        with urllib.request.urlopen(r, context=ctx, timeout=5) as resp: return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:200]

s, b = lcu("GET", "/lol-tft-team-planner/v1/previous-context")
d = json.loads(b); tid = d.get("optionalTeamId", ""); sid = d.get("setId", "TFTSet17")

def get_code():
    s, b = lcu("POST", f"/lol-tft-team-planner/v1/sets/{sid}/team-code/{tid}")
    return b.strip().strip('"') if s == 200 else None

def clr():
    lcu("DELETE", f"/lol-tft-team-planner/v1/sets/{sid}/teams/{tid}/champions")
    time.sleep(0.2)

codes_file = Path(r"C:\Riot Commander\data\meta\tft_set17_champion_codes.json")
results = json.loads(codes_file.read_text()) if codes_file.exists() else {}

# More variants + try known units for collision check
MISSING = {
    "Kai'Sa":         [
        "TFT17_KaiSa", "TFT17_Kaisa", "TFT17_KAISA",
        "TFT13_KaiSa",  # might use older set ID
        "TFT17_KaiSaSentinel",
    ],
    "The Mighty Mech":[
        "TFT17_GigaMech", "TFT17_MightyMechRobot",
        "TFT17_Mech_Preview", "TFT17_MechPrime",
        "TFT17_RiotMech",
    ],
    "Morgana":        [
        "TFT17_MorganaFallen", "TFT17_MorganaAngel",
        "TFT17_MorganaWings", "TFT13_Morgana",
    ],
    "LeBlanc":        [
        "TFT17_LeBlanc", "TFT17_LeBlancNew",
        "TFT17_LeBlanck", "TFT13_LeBlanc",
    ],
    "Bel'Veth":       [
        "TFT17_BelVeth", "TFT17_Belveth",
        "TFT17_BelVethVoid", "TFT12_BelVeth",
    ],
    "Ekko":           [
        "TFT17_Ekko", "TFT17_EkkoNew",
        "TFT17_EkkoArcane", "TFT_EKKO_Set17",
        "TFT17_EkkoTimewinder",
    ],
}

for display, fmts in MISSING.items():
    if display in results:
        print(f"{display}: already known ({results[display]})")
        continue
    clr()
    found = False
    for fmt in fmts:
        s2, b2 = lcu("POST", f"/lol-tft-team-planner/v1/sets/{sid}/teams/{tid}/champions/{fmt}")
        if s2 in (200, 201, 204):
            time.sleep(0.15)
            code = get_code()
            if code and len(code) > 5:
                prefix = code[2:5]
                if prefix != "000":
                    num = int(prefix, 16)
                    # Check for collision with known code
                    collision = [k for k, v in results.items() if v == num]
                    if collision:
                        print(f"  {display}: code {num} via {fmt} - COLLISION with {collision}")
                    else:
                        results[display] = num
                        print(f"  {display}: {num} (0x{prefix}) via {fmt}")
                    found = True
                    break
        time.sleep(0.06)
    if not found:
        print(f"  {display}: NOT FOUND in PBE catalog")

codes_file.write_text(json.dumps(results, indent=2, sort_keys=True))
print(f"\nWrote {len(results)} codes")
