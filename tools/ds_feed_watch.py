"""DS upstream feed watch - a READ-ONLY step of the DS batch checklist (RM-668).

Directive L-08, provenance "external reference L" (the upstream whose chunk
URLs the extractor already records in the current patch manifest). This is NOT
a poller: there is no scheduled task, no loop and no unattended caller. A human
runs it by hand once per DS batch (tools/ship-batch.md step 0), and at least
every 3-4 weeks, so upstream changelog entries cannot scroll off unseen.

What one run does (network: HEAD + GET only, never a write upstream):
  1. CHANGELOG - GET <origin>/info/changelog/ (origin derived from the
     manifest's own chunk URLs, never a literal here), pull every date out of
     the page and list the ones strictly after the tracked high-water date in
     tools/ds_feed_watch.json.
  2. HEAD each chunk URL in the manifest's data-block list. Non-200 = the
     chunk hash rotated or the block moved; the extractor must re-discover.
  3. GET each live chunk and hash its body with ds_feed_index.body_md5 (raw
     bytes, verbatim). A hash differing from the one recorded beside the URL
     is reported as MOVED.

Default is report-only. Writes happen only on explicit flags:
  --record      write {block: {url, status, body_md5, fetched_at}} under
                sources.data_block_body_md5 in the manifest, beside the URL
                list (atomic, LF). Then run `python tools/ds_feed_index.py
                --write`, because the manifest is itself an indexed feed.
  --ack DATE    advance the changelog high-water date after a human has
                reviewed the new entries. Touches nothing else.

Run:
    python tools/ds_feed_watch.py
    python tools/ds_feed_watch.py --json
    python tools/ds_feed_watch.py --record
    python tools/ds_feed_watch.py --ack 2026-10-04
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from ds_feed_index import _DATA, body_md5, live_patch  # noqa: E402

# Pre-existing manifest key written by tools/daemon_slayer_extract.py.
DATA_BLOCKS_KEY = "lolmath_data_blocks"
# New sibling key: per-block body hash recorded beside each URL.
HASHES_KEY = "data_block_body_md5"
CHANGELOG_PATH = "/info/changelog/"
WATCH_FILE = _TOOLS / "ds_feed_watch.json"
USER_AGENT = "Amberstone/DaemonSlayer-feed-watch/1.0"
TIMEOUT_S = 30

_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"))}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_ISO_RE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_MDY_RE = re.compile(_MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I)
_DMY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r",?\s+(20\d\d)\b",
                     re.I)


class UrllibHttp:
    """Real transport. HEAD and GET only."""

    def _req(self, url: str, method: str):
        import urllib.request
        return urllib.request.Request(
            url, method=method, headers={"User-Agent": USER_AGENT})

    def head(self, url: str) -> int:
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(self._req(url, "HEAD"),
                                        timeout=TIMEOUT_S) as r:
                return int(r.status)
        except urllib.error.HTTPError as e:
            return int(e.code)

    def get(self, url: str):
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(self._req(url, "GET"),
                                        timeout=TIMEOUT_S) as r:
                return int(r.status), r.read()
        except urllib.error.HTTPError as e:
            return int(e.code), b""


def manifest_path(patch: Optional[str] = None) -> Path:
    return _DATA / (patch or live_patch()) / "manifest.json"


def block_urls(manifest: dict) -> dict:
    src = manifest.get("sources") if isinstance(manifest, dict) else None
    blocks = src.get(DATA_BLOCKS_KEY) if isinstance(src, dict) else None
    if not isinstance(blocks, dict):
        return {}
    return {str(k): str(v) for k, v in blocks.items() if isinstance(v, str)}


def origin_of(urls: Iterable[str]) -> Optional[str]:
    origins = set()
    for u in urls:
        parts = urlsplit(u)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return None
        origins.add(f"{parts.scheme}://{parts.netloc}")
    return origins.pop() if len(origins) == 1 else None


def _safe_date(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def changelog_dates(text: str) -> list:
    found = set()
    for y, m, d in _ISO_RE.findall(text):
        found.add(_safe_date(int(y), int(m), int(d)))
    for mon, d, y in _MDY_RE.findall(text):
        found.add(_safe_date(int(y), _MONTHS[mon.lower()[:3]], int(d)))
    for d, mon, y in _DMY_RE.findall(text):
        found.add(_safe_date(int(y), _MONTHS[mon.lower()[:3]], int(d)))
    found.discard(None)
    return sorted(found)


def new_since(dates: Iterable[str], high_water: str) -> list:
    return [d for d in dates if d > high_water]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_blocks(manifest: dict, http, now_iso: Optional[str] = None) -> dict:
    """HEAD every data-block URL; GET + hash the live ones. Never raises."""
    stamp = now_iso or _now_iso()
    rows = {}
    for block, url in sorted(block_urls(manifest).items()):
        status, md5 = None, None
        try:
            status = http.head(url)
            if status == 200:
                st, body = http.get(url)
                status = st
                if st == 200 and body:
                    md5 = body_md5(bytes(body))
        except Exception:  # transport errors are reported, not raised
            status, md5 = None, None
        rows[block] = {"url": url, "status": status, "body_md5": md5,
                       "fetched_at": stamp}
    return rows


def watch(manifest: dict, high_water: str, http,
          now_iso: Optional[str] = None) -> dict:
    blocks = check_blocks(manifest, http, now_iso)
    prior = (manifest.get("sources") or {}).get(HASHES_KEY) or {}
    moved = sorted(
        b for b, row in blocks.items()
        if row["body_md5"] and isinstance(prior.get(b), dict)
        and prior[b].get("body_md5") and prior[b]["body_md5"] != row["body_md5"]
    )
    unreachable = sorted(b for b, row in blocks.items() if row["status"] != 200)

    origin = origin_of(block_urls(manifest).values())
    changelog = {"url": None, "status": None, "dates": [], "new_entries": [],
                 "high_water": high_water}
    if origin:
        url = origin + CHANGELOG_PATH
        changelog["url"] = url
        try:
            st, body = http.get(url)
            changelog["status"] = st
            if st == 200:
                dates = changelog_dates(bytes(body).decode("utf-8", "replace"))
                changelog["dates"] = dates
                changelog["new_entries"] = new_since(dates, high_water)
        except Exception:
            changelog["status"] = None
    return {"changelog": changelog, "blocks": blocks, "moved": moved,
            "unreachable": unreachable}


def _atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8",
                   newline="")
    tmp.replace(path)


def record(path: Path, rows: dict) -> None:
    """Write per-block hashes beside the URL list. Only that key changes."""
    path = Path(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    urls = block_urls(manifest)
    for block, row in rows.items():
        if urls.get(block) != row.get("url"):
            raise ValueError(f"{block}: url {row.get('url')!r} is not the one"
                             " in the manifest's data-block list")
    src = manifest.setdefault("sources", {})
    # Keep a prior hash for a block that was unreachable this run, but only
    # while its URL is unchanged - a rotated URL invalidates the old hash.
    prior = src.get(HASHES_KEY) if isinstance(src.get(HASHES_KEY), dict) else {}
    merged = {b: r for b, r in prior.items()
              if isinstance(r, dict) and urls.get(b) == r.get("url")}
    merged.update(rows)
    src[HASHES_KEY] = dict(sorted(merged.items()))
    _atomic_write_json(path, manifest)


def _read_high_water(watch_file: Path) -> str:
    doc = json.loads(Path(watch_file).read_text(encoding="utf-8"))
    return str(doc["changelog_high_water"])


def render(rep: dict) -> str:
    c = rep["changelog"]
    lines = [f"changelog {c['url']} status={c['status']}"
             f" high-water={c['high_water']}",
             f"  new entries: {', '.join(c['new_entries']) or 'none'}"]
    for b, row in rep["blocks"].items():
        lines.append(f"block {b:<22} status={row['status']}"
                     f" body_md5={row['body_md5']}  {row['url']}")
    lines.append(f"MOVED: {', '.join(rep['moved']) or 'none'}")
    lines.append(f"UNREACHABLE: {', '.join(rep['unreachable']) or 'none'}")
    return "\n".join(lines)


def run(argv=None, *, http=None, manifest: Optional[Path] = None,
        watch_file: Optional[Path] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--patch", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="write per-block hashes into the manifest")
    ap.add_argument("--ack", metavar="YYYY-MM-DD",
                    help="advance the changelog high-water date")
    args = ap.parse_args(list(argv) if argv is not None else None)
    wf = Path(watch_file or WATCH_FILE)

    if args.ack:
        try:
            date.fromisoformat(args.ack)
        except ValueError:
            ap.error(f"--ack wants YYYY-MM-DD, got {args.ack!r}")
        doc = json.loads(wf.read_text(encoding="utf-8"))
        doc["changelog_high_water"] = args.ack
        _atomic_write_json(wf, doc)
        print(f"high-water -> {args.ack}")
        return 0

    mp = Path(manifest or manifest_path(args.patch))
    m = json.loads(mp.read_text(encoding="utf-8"))
    rep = watch(m, _read_high_water(wf), http or UrllibHttp())
    print(json.dumps(rep, indent=2) if args.json else render(rep))
    if args.record:
        rows = {b: r for b, r in rep["blocks"].items() if r["body_md5"]}
        record(mp, rows)
        print(f"recorded {len(rows)} block hash(es) in {mp.name};"
              " now run: python tools/ds_feed_index.py --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
