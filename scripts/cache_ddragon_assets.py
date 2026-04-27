"""Pull item + champion icons from DDragon CDN into web/data/ddragon/<ver>/
so the dashboard never depends on the CDN during a live match.

Run idempotently: files already present are skipped. Total download is
~5-10 MB on a cold run.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parent.parent
VERSION_DIR = ROOT / "data" / "meta_build" / "ddragon"

def latest_version() -> str:
    idx = json.loads((VERSION_DIR / "_index.json").read_text(encoding="utf-8"))
    return idx["latest_pulled"]

def fetch(url: str, dest: Path, *, retries: int = 2, timeout: float = 6.0) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return False
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "riot-commander-asset-cache/1"})
            with urlopen(req, timeout=timeout) as r:
                body = r.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(dest)
            return True
        except (URLError, HTTPError, TimeoutError) as e:
            if attempt == retries:
                sys.stderr.write(f"fail {url}: {e}\n")
                return False
            time.sleep(0.5 * (attempt + 1))

def main():
    version = latest_version()
    src_dir = VERSION_DIR / version
    dst_root = ROOT / "web" / "data" / "ddragon" / version
    items = json.loads((src_dir / "item.json").read_text(encoding="utf-8"))["data"]
    champs = json.loads((src_dir / "champion.json").read_text(encoding="utf-8"))["data"]

    base = f"https://ddragon.leagueoflegends.com/cdn/{version}/img"
    stats = {"item": [0, 0], "champion": [0, 0], "splash": [0, 0]}

    # Items
    for iid, info in items.items():
        img = (info.get("image") or {}).get("full") or f"{iid}.png"
        dst = dst_root / "img" / "item" / img
        did = fetch(f"{base}/item/{img}", dst)
        stats["item"][0] += 1; stats["item"][1] += int(did)

    # Champion square portraits
    for key, info in champs.items():
        img = (info.get("image") or {}).get("full") or f"{key}.png"
        dst = dst_root / "img" / "champion" / img
        did = fetch(f"{base}/champion/{img}", dst)
        stats["champion"][0] += 1; stats["champion"][1] += int(did)

    print(f"version={version}")
    for k, (total, new) in stats.items():
        print(f"  {k:10} total={total:4}  new={new}")

if __name__ == "__main__":
    main()
