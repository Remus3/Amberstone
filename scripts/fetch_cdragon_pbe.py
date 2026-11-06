"""Fetch Set 17 data from CommunityDragon PBE and extract champion codes + traits.

Run as `python scripts/fetch_cdragon_pbe.py`. It fetches two CommunityDragon
PBE files and rewrites files under data/meta/, so nothing runs at import:
main() does the work (RM-1174).

Both GETs open through lib.wiki_consent.open_consented, so a url to the
League wiki host, or a CommunityDragon redirect into it, is refused before a
wiki socket opens unless a consent record exists (ruling 51, RM-1441). A
refusal is one section's FAILED line, like any other fetch failure: nothing
is written and main still runs the other section.
"""
import json
import sys
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
# Run as `python scripts/fetch_cdragon_pbe.py`, sys.path[0] is scripts/; the
# repo root makes `core` importable (same as probe_missing_codes.py).
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

# RM-1174: the merged code map is TRACKED and read by
# tft/tft_live_analysis.py, so every write goes through core.polled_json
# (per-writer scratch, fsync, WinError 5 retry, no scratch left on a failed
# rename) instead of an in-place write.
from core.polled_json import atomic_write_bytes  # noqa: E402
from core.tls_policy import client_context_verified  # noqa: E402
from lib.wiki_consent import open_consented  # noqa: E402

META_DIR = PROJECT / "data" / "meta"
TEAMPLANNER_URL = ("https://raw.communitydragon.org/pbe/plugins/"
                   "rcp-be-lol-game-data/global/default/v1/"
                   "tftchampions-teamplanner.json")
TFT_EN_US_URL = "https://raw.communitydragon.org/pbe/cdragon/tft/en_us.json"
TEAMPLANNER_RAW = META_DIR / "cdragon_teamplanner_pbe.json"
TFT_RAW = META_DIR / "cdragon_tft_pbe.json"
CODES_FILE = META_DIR / "tft_set17_champion_codes.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _ssl_context():
    # RM-1175: raw.communitydragon.org is a public CDN with a CA-signed
    # certificate and this download feeds a TRACKED file, so the peer is
    # verified (chain + hostname, RM-752 protocol floor).
    return client_context_verified()


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    # RM-1441: every hop is consent-checked, so a redirect into the wiki
    # host raises WikiFetchRefused (caught by the caller's section handler).
    with open_consented(req, timeout=30, context=_ssl_context()) as r:
        return r.read().decode("utf-8", "replace")


def set17_codes(data):
    """Return {display_name: team_planner_code} for the Set 17 planner rows."""
    codes = {}
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                cid = entry.get("character_id", "")
                name = entry.get("display_name", "")
                code = entry.get("team_planner_code")
                if cid.startswith(("TFT17_", "TFT_Set17_")) and name and code is not None:
                    codes[name] = code
    return codes


def merge_codes(path, codes):
    """Overlay CODES on the map at PATH, write it atomically, return it."""
    existing = (json.loads(path.read_text(encoding="utf-8"))
                if path.exists() else {})
    merged = {**existing, **codes}
    atomic_write_bytes(
        path, json.dumps(merged, indent=2, sort_keys=True).encode("utf-8"))
    return merged


def sync_team_planner():
    """Team planner codes (real Set 17 IDs)."""
    print("Fetching team planner data...")
    try:
        raw = fetch(TEAMPLANNER_URL)
        # Save raw
        atomic_write_bytes(TEAMPLANNER_RAW, raw.encode("utf-8"))
        data = json.loads(raw)
        print(f"  Got {len(data) if isinstance(data,list) else 'dict'} entries")
        codes = set17_codes(data)
        for name, code in codes.items():
            print(f"  Set17: {name} -> {code}")
        if isinstance(data, dict):
            # Might be nested
            for k, v in data.items():
                print(f"  Key: {k} -> {str(v)[:100]}")

        if codes:
            merged = merge_codes(CODES_FILE, codes)
            print(f"\nMerged {len(codes)} CDragon codes into {len(merged)} total")
        else:
            print("  No Set17 champions found - checking structure...")
            if isinstance(data, list) and data:
                print(f"  First entry: {data[0]}")
            elif isinstance(data, dict):
                print(f"  Keys: {list(data.keys())[:10]}")

    except Exception as e:  # noqa: BLE001
        print(f"team planner FAILED: {e}")


def report_tft_en_us():
    """TFT en_us.json (champions, traits, items)."""
    print("\nFetching TFT en_us data...")
    try:
        raw2 = fetch(TFT_EN_US_URL)
        atomic_write_bytes(TFT_RAW, raw2.encode("utf-8"))
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
            if s17t:
                print("  Sample traits:", [t.get("name","?") for t in s17t[:10] if isinstance(t,dict)])
        if "items" in data2:
            print(f"  Items: {len(data2['items'])}")
    except Exception as e:  # noqa: BLE001
        print(f"TFT en_us FAILED: {e}")
        import traceback
        traceback.print_exc()


def main():
    sync_team_planner()
    report_tft_en_us()
    return 0


if __name__ == "__main__":
    sys.exit(main())
