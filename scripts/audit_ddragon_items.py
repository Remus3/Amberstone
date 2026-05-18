"""
DDragon item icon coverage audit.

Scans every item name that actually appears in:
  - fixtures (data/sim/*.json): items_display, item_build
  - history DB (rewind_history.db): participants.item0..item6

For each, resolves to the numeric item id via web/data/items_index.json.
Then checks web/data/ddragon/<version>/img/item/<id>.png existence.

Reports:
  - Items that COULDN'T resolve to an id (name not in items_index)
  - Items that resolved but whose icon file is missing on disk

Optionally downloads missing icons from the DDragon CDN when --download
is passed. Without that flag the script is read-only (safe for headless).

This is queue item #7: "DDragon icon asset coverage audit" - verifies the
jungle-enchantment items (Stalker's Warrior etc.), consumables (Elixirs),
arena-specific items actually have images so the Item Build panel never
falls back to a placeholder '?' tile.
"""
from __future__ import annotations
import json
import sqlite3
import sys
import re
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "web" / "data" / "items_index.json"
DB_PATH = ROOT / "data" / "rewind_history.db"
SIM_DIR = ROOT / "data" / "sim"
# Primary: DDragon standard catalog (covers most items).
CDN_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{id}.png"
# Fallback: CommunityDragon has every asset, including Ornn Forge 7xxx
# upgrades + retired items that DDragon trims out of its item.json.
CDN_CD_URL = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/item-icons/{id}.png"


def load_index():
    idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    version = idx.get("version", "")
    by_name = idx.get("byName", {})
    by_id = idx.get("byId", {})
    item_dir = ROOT / "web" / "data" / "ddragon" / version / "img" / "item"
    return version, by_name, by_id, item_dir


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve(name: str, by_name: dict) -> str | None:
    """Look up a free-text item name against items_index.byName.
    Tries exact normalized match then substring match both ways."""
    if not name:
        return None
    n = norm(name)
    if not n:
        return None
    if n in by_name:
        return by_name[n]
    # Substring - try shorter coach forms against longer official names
    for k, v in by_name.items():
        if n == k or n in k or k in n:
            return v
    return None


def collect_from_fixtures() -> set[str]:
    names: set[str] = set()
    for p in SIM_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload = (d.get("state", {}) or {}).get("payload", {}) or {}
        for field in ("items_display", "item_build"):
            val = payload.get(field, "")
            if not val:
                continue
            # Split on comma, arrow, semicolon, and pipe
            for token in re.split(r"[,→|;]", val):
                t = token.strip()
                # Strip "+" prefix ("+ 7th item" convention)
                t = t.lstrip("+").strip()
                if t:
                    names.add(t)
    return names


def collect_from_db() -> set[str]:
    """Every unique participants.itemN that shows up in rewind_history.db.
    Returns numeric ids as strings."""
    ids: set[str] = set()
    if not DB_PATH.exists():
        return ids
    conn = sqlite3.connect(DB_PATH)
    try:
        for slot in range(7):
            for (iid,) in conn.execute(f"SELECT DISTINCT item{slot} FROM participants WHERE item{slot}>0"):
                ids.add(str(iid))
    finally:
        conn.close()
    return ids


def download_icon(version: str, iid: str, dest: Path) -> str | None:
    """Try DDragon first, then CommunityDragon. Returns the source name
    on success (`ddragon` or `cdragon`), or None if both fail."""
    for source, url in (
        ("ddragon", CDN_URL.format(version=version, id=iid)),
        ("cdragon", CDN_CD_URL.format(id=iid)),
    ):
        req = Request(url, headers={"User-Agent": "RC-Audit/1.0"})
        try:
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    continue
                data = resp.read()
            if not data or len(data) < 64:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return source
        except (URLError, HTTPError, TimeoutError, OSError):
            continue
    return None


def main(download: bool = False) -> int:
    version, by_name, by_id, item_dir = load_index()
    print(f"DDragon version: {version}")
    print(f"Item dir: {item_dir}")
    print(f"Currently on disk: {sum(1 for _ in item_dir.glob('*.png'))} icons")
    print()

    # 1) Fixture names → ids
    fix_names = collect_from_fixtures()
    print(f"[fixtures] {len(fix_names)} unique item names")
    fix_unresolved: list[str] = []
    fix_ids: set[str] = set()
    for n in sorted(fix_names):
        iid = resolve(n, by_name)
        if iid is None:
            fix_unresolved.append(n)
        else:
            fix_ids.add(iid)
    if fix_unresolved:
        print(f"  ⚠ {len(fix_unresolved)} name(s) didn't resolve to an id:")
        for n in fix_unresolved:
            print(f"    - {n}")
    else:
        print("  ✓ all fixture names resolve")

    # 2) History DB ids (directly numeric)
    db_ids = collect_from_db()
    print(f"[history] {len(db_ids)} unique item ids in rewind_history.db")

    # 3) Check icon presence for the union
    all_ids = fix_ids | db_ids
    print(f"[union] {len(all_ids)} unique ids needing icons")
    missing: list[str] = []
    for iid in sorted(all_ids, key=lambda x: int(x) if x.isdigit() else 0):
        png = item_dir / f"{iid}.png"
        if not png.is_file():
            missing.append(iid)
    if missing:
        print(f"  ⚠ {len(missing)} missing icon file(s)")
        shown = missing[:30]
        for iid in shown:
            nm = by_id.get(iid, "<unknown>")
            print(f"    - {iid}  {nm}")
        if len(missing) > 30:
            print(f"    ... and {len(missing) - 30} more")
    else:
        print("  ✓ every id we care about has a png on disk")

    # 4) Optional download - tries DDragon then CommunityDragon fallback.
    if download and missing:
        print()
        print(f"Downloading {len(missing)} missing icons (DDragon → CommunityDragon fallback)...")
        ok_dd = ok_cd = 0
        for iid in missing:
            dest = item_dir / f"{iid}.png"
            src = download_icon(version, iid, dest)
            if src == "ddragon":
                ok_dd += 1
            elif src == "cdragon":
                ok_cd += 1
        print(f"  {ok_dd} from DDragon + {ok_cd} from CommunityDragon = {ok_dd + ok_cd}/{len(missing)}")
        still_missing = [iid for iid in missing if not (item_dir / f"{iid}.png").is_file()]
        if still_missing:
            print(f"  {len(still_missing)} still missing after download attempt:")
            for iid in still_missing[:10]:
                print(f"    - {iid}")
        else:
            print("  ✓ all pulled")

    # Exit 0 if nothing missing, 1 otherwise (so CI-style use is possible)
    return 0 if not missing and not fix_unresolved else 1


if __name__ == "__main__":
    download = "--download" in sys.argv
    sys.exit(main(download=download))
