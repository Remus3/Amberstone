"""
DDragon item icon coverage audit.

Scans every item id that actually appears in the history DB
(data/rewind_history.db: participants.item0..item6) and checks that
web/data/ddragon/<version>/img/item/<id>.png exists, where <version> and the
display names come from web/data/items_index.json. With no history DB there is
nothing to check and the audit passes.

Reports the ids whose icon file is missing on disk.

The old "fixtures" leg (item names parsed out of the repo-root dev-preview
sim fixtures) is gone: their only producer, scripts/rebuild_sim_fixtures.py,
was deleted as dead (RM-1177), so the leg always found 0 names (RM-1178).

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
from pathlib import Path
from urllib.request import Request
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# RM-1180: icons land in the tree the :8888 dashboard serves, so write via
# scratch file + fsync + rename (the RM-1130 helper cache_ddragon_assets uses).
from core.polled_json import atomic_write_bytes  # noqa: E402
# RM-1441 (ruling 51): the icon GET opens through the consent opener, so a
# Data Dragon or CommunityDragon url answering 3xx into the League wiki host
# is refused before a wiki socket opens (the stdlib default opener followed it
# with no consent record).
from lib.wiki_consent import WikiFetchRefused, open_consented  # noqa: E402
from itertools import starmap

# RM-1180: same set as lib/icons/downloader.py _IMAGE_MAGIC (RM-373), kept
# local so this script does not pull in lib.http; a test pins agreement.
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")

INDEX_PATH = ROOT / "web" / "data" / "items_index.json"
DB_PATH = ROOT / "data" / "rewind_history.db"
# Primary: DDragon standard catalog (covers most items).
CDN_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{id}.png"
# Fallback: CommunityDragon has every asset, including Ornn Forge 7xxx
# upgrades + retired items that DDragon trims out of its item.json.
CDN_CD_URL = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/item-icons/{id}.png"


def load_index():
    idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    version = idx.get("version", "")
    by_id = idx.get("byId", {})
    item_dir = ROOT / "web" / "data" / "ddragon" / version / "img" / "item"
    return version, by_id, item_dir


def collect_from_db() -> set[str]:
    """Every unique participants.itemN that shows up in rewind_history.db.
    Returns numeric ids as strings."""
    ids: set[str] = set()
    if not DB_PATH.exists():
        return ids
    conn = sqlite3.connect(DB_PATH)
    try:
        for slot in range(7):
            ids.update(
                starmap(str, conn.execute(f"SELECT DISTINCT item{slot} FROM participants WHERE item{slot}>0"))
            )
    finally:
        conn.close()
    return ids


def safe_icon_dest(item_dir: Path, iid: str) -> Path | None:
    """RM-379: `<iid>.png` under item_dir, or None when iid is not a plain
    item id (ids reach here from the history DB, two hops from the wire)."""
    iid = str(iid)
    if not iid.isdigit():
        return None
    return item_dir / f"{iid}.png"


def download_icon(version: str, iid: str, dest: Path) -> str | None:
    """Try DDragon first, then CommunityDragon. Returns the source name
    on success (`ddragon` or `cdragon`), or None if both fail.

    RM-1180: a 200 is not proof of an image (an error page or an
    interstitial would land as `<id>.png`), so the body must start with PNG
    or JPEG magic before anything is written, and the write is atomic.

    RM-1441: a source whose url, or any redirect hop, names the League wiki
    host without a consent record is refused before its socket opens (stderr
    "refused <url>: ..."), writes nothing, and is skipped like any other
    per-source failure, so the CommunityDragon fallback still runs."""
    for source, url in (
        ("ddragon", CDN_URL.format(version=version, id=iid)),
        ("cdragon", CDN_CD_URL.format(id=iid)),
    ):
        req = Request(url, headers={"User-Agent": "RC-Audit/1.0"})
        try:
            with open_consented(req, timeout=10) as resp:
                if resp.status != 200:
                    continue
                data = resp.read()
            if not data or len(data) < 64 or not data.startswith(_IMAGE_MAGIC):
                continue
            atomic_write_bytes(dest, data)  # creates dest.parent on demand
            return source
        except WikiFetchRefused as e:
            # A RuntimeError, outside the transport tuple below: caught here
            # so a refusal never aborts the run; not retried, nothing written.
            sys.stderr.write(f"refused {url}: {e}\n")
            continue
        except (URLError, HTTPError, TimeoutError, OSError):
            continue
    return None


def main(download: bool = False) -> int:
    version, by_id, item_dir = load_index()
    print(f"DDragon version: {version}")
    print(f"Item dir: {item_dir}")
    print(f"Currently on disk: {sum(1 for _ in item_dir.glob('*.png'))} icons")
    print()

    # 1) History DB ids (directly numeric)
    db_ids = collect_from_db()
    print(f"[history] {len(db_ids)} unique item ids in rewind_history.db")

    # 2) Check icon presence
    missing: list[str] = []
    for iid in sorted(db_ids, key=lambda x: int(x) if x.isdigit() else 0):
        png = item_dir / f"{iid}.png"
        if not png.is_file():
            missing.append(iid)
    if missing:
        print(f"  \u26a0 {len(missing)} missing icon file(s)")
        shown = missing[:30]
        for iid in shown:
            nm = by_id.get(iid, "<unknown>")
            print(f"    - {iid}  {nm}")
        if len(missing) > 30:
            print(f"    ... and {len(missing) - 30} more")
    else:
        print("  ok every id we care about has a png on disk")

    # 3) Optional download - tries DDragon then CommunityDragon fallback.
    # still_missing = the icons absent after this step; without a download it
    # is just `missing`.
    still_missing = missing
    if download and missing:
        print()
        print(f"Downloading {len(missing)} missing icons (DDragon -> CommunityDragon fallback)...")
        ok_dd = ok_cd = 0
        for iid in missing:
            dest = safe_icon_dest(item_dir, iid)
            if dest is None:  # RM-379
                print(f"  skip unsafe item id {iid!r}")
                continue
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
            print("  ok all pulled")

    # Exit 0 if no icon is missing at the end of the run (after any download),
    # 1 otherwise, so CI-style use is possible. RM-1179 (a): this used the
    # pre-download list, so a --download run that pulled every icon exited 1.
    return 0 if not still_missing else 1


if __name__ == "__main__":
    download = "--download" in sys.argv
    sys.exit(main(download=download))
