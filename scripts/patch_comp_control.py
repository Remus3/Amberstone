"""Patch comp_control.py: fix _lcu_import_team_code and _do_import."""
from pathlib import Path

f = Path(r"C:\Riot Commander\tft\comp_control.py")
content = f.read_text(encoding="utf-8")

# --- Patch 1: replace import function ---
old_fn_start = 'def _lcu_import_team_code(code: str, team_id: str'
old_fn_end = '        return False\n\ndef _lcu_get_team_id'

if old_fn_start in content:
    i = content.index(old_fn_start)
    j = content.index(old_fn_end, i)
    old_block = content[i:j]
    new_block = '''def _lcu_import_units(units: list, team_id: str, set_id: str = "TFTSet17") -> bool:
    """Import units into LCU team planner using correct string-array format."""
    import ssl, base64, urllib.request as _ur
    lockfiles = [
        Path(r"C:\\Riot Games\\League of Legends (PBE)\\lockfile"),
        Path(r"C:\\Riot Games\\League of Legends\\lockfile"),
    ]
    lf = next((p for p in lockfiles if p.exists()), None)
    if not lf:
        return False
    try:
        parts = lf.read_text().strip().split(":")
        port, pw = parts[2], parts[3]
        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
        sctx = ssl.create_default_context()
        sctx.check_hostname = False
        sctx.verify_mode    = ssl.CERT_NONE
        hdrs = {"Authorization": f"Basic {auth}", "Content-Type": "application/json", "Accept": "application/json"}
        champ_ids = [
            "TFT17_" + str(u).replace("'", "").replace(" ", "").replace(".", "")
            for u in units[:10]
        ]
        body = json.dumps(champ_ids).encode()
        ep   = f"https://192.168.8.237:{port}/lol-tft-team-planner/v1/sets/{set_id}/teams/{team_id}/import"
        req  = _ur.Request(ep, data=body, headers=hdrs, method="POST")
        with _ur.urlopen(req, context=sctx, timeout=5) as r:
            _log.info("LCU import: %d units HTTP %d", len(champ_ids), r.status)
            return r.status in (200, 201, 204)
    except Exception as e:
        _log.debug("LCU import failed: %s", e)
        return False

_lcu_import_team_code = _lcu_import_units  # backwards compat alias

'''
    content = content[:i] + new_block + content[j:]
    print("Patch 1 applied: import function replaced")
else:
    print("Patch 1 SKIP: function not found (may already be patched)")

# --- Patch 2: fix _do_import closure to pass lv9 list ---
OLD_DO = (
    "        # Try LCU direct import first, then clipboard fallback\n"
    "        def _do_import():\n"
    "            team_id = _lcu_get_team_id()\n"
    "            if team_id:\n"
    "                ok = _lcu_import_team_code(code, team_id)\n"
)
NEW_DO = (
    "        # LCU direct import (string array), then clipboard fallback\n"
    "        _lv9_import = list(lv9)\n"
    "        def _do_import(_u=_lv9_import, _n=name):\n"
    "            team_id = _lcu_get_team_id()\n"
    "            if team_id:\n"
    "                ok = _lcu_import_units(_u, team_id)\n"
)
if OLD_DO in content:
    content = content.replace(OLD_DO, NEW_DO, 1)
    print("Patch 2 applied: _do_import updated")
else:
    print("Patch 2 SKIP: _do_import pattern not found")
    # Show context
    idx = content.find("_do_import")
    if idx >= 0:
        print("  Found _do_import at:", idx)
        print("  Context:", repr(content[idx-100:idx+200]))

f.write_text(content, encoding="utf-8")
print("Done.")
