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
  4. LIVE BUILD (RM-839) - steps 2-3 are blind to a rebuild: chunk names are
     content hashes, a rebuild publishes NEW names, and the old files stay on
     the CDN answering 200 with their old, unchanged bytes. So GET <origin>/
     and walk the live chunk reference graph (the extractor's two reference
     shapes, bounded by LIVE_CRAWL_MAX_FETCH / LIVE_CRAWL_MAX_DEPTH). Every
     chunk URL the manifest records (data blocks, and every other recorded
     chunk under the same directory) that the live build no longer references
     is MOVED, with the live chunk now carrying the block's anchor (read from
     the extractor's _DATA_BLOCKS table by AST, never by import) as its new
     name. The walk stops as soon as every recorded name is seen. A capped or
     partial walk reports UNVERIFIED instead of guessing; an unreadable root
     says so instead of printing "MOVED: none".

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
import ast
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

# The pre-existing manifest key written by tools/daemon_slayer_extract.py is
# found by its suffix, so this file never spells the external source's name
# (directive hard rule 3: provenance is "external reference L" only).
DATA_BLOCKS_SUFFIX = "_data_blocks"


def data_blocks_key(src) -> Optional[str]:
    """The single `sources` key ending in DATA_BLOCKS_SUFFIX, else None."""
    if not isinstance(src, dict):
        return None
    keys = [k for k in src if isinstance(k, str) and k.endswith(DATA_BLOCKS_SUFFIX)]
    return keys[0] if len(keys) == 1 else None
# New sibling key: per-block body hash recorded beside each URL.
HASHES_KEY = "data_block_body_md5"
CHANGELOG_PATH = "/info/changelog/"
WATCH_FILE = _TOOLS / "ds_feed_watch.json"
USER_AGENT = "Amberstone/DaemonSlayer-feed-watch/1.0"
TIMEOUT_S = 30
# The extractor that owns the block -> anchor table. Read by AST only: an
# import configures logging and opens its log file at module load.
EXTRACTOR = _TOOLS / "daemon_slayer_extract.py"
DATA_BLOCKS_TABLE = "_DATA_BLOCKS"
# Bounds on the live chunk-graph walk (measured 2026-10-24: 294 chunks, 4
# levels deep). Reaching either one reports "capped", never a guess.
LIVE_CRAWL_MAX_FETCH = 600
LIVE_CRAWL_MAX_DEPTH = 6
# The bare loader-call reference shape (`"<id>.js"`), as the extractor reads it.
_BARE_CHUNK_RE = re.compile(r"\"([A-Za-z0-9_\-]{8,20}\.js)\"")

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
    key = data_blocks_key(src)
    blocks = src.get(key) if key else None
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


# -- live build discovery (RM-839) ----------------------------------------------


def extractor_anchors(path: Optional[Path] = None) -> dict:
    """block -> anchor from the extractor's _DATA_BLOCKS table, read by AST.

    Each entry is ("block", ANCHOR_NAME) or ("block", "literal"); a name is
    resolved against the module-level string constants. Returns {} when the
    file or the table cannot be read, so discovery still reports renamed files,
    only without naming their replacement.
    """
    try:
        tree = ast.parse(Path(path or EXTRACTOR).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return {}
    consts, table = {}, None
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name, value = node.targets[0].id, node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            consts[name] = value.value
        elif name == DATA_BLOCKS_TABLE:
            table = value
    out = {}
    for elt in getattr(table, "elts", None) or []:
        if not (isinstance(elt, ast.Tuple) and len(elt.elts) == 2):
            continue
        key_node, anchor_node = elt.elts
        key = key_node.value if isinstance(key_node, ast.Constant) else None
        if isinstance(anchor_node, ast.Constant):
            anchor = anchor_node.value
        elif isinstance(anchor_node, ast.Name):
            anchor = consts.get(anchor_node.id)
        else:
            anchor = None
        if isinstance(key, str) and isinstance(anchor, str) and anchor:
            out[key] = anchor
    return out


def chunk_dir_of(urls: Iterable[str]) -> Optional[str]:
    """The one directory URL (trailing slash) every chunk URL sits in."""
    dirs = {u.rsplit("/", 1)[0] + "/" for u in urls if "/" in u}
    if len(dirs) != 1:
        return None
    d = dirs.pop()
    return d if origin_of([d]) else None


def _walk_urls(value, label: str):
    if isinstance(value, str):
        yield label, value
    elif isinstance(value, dict):
        for k in sorted(value, key=str):
            yield from _walk_urls(value[k], f"{label}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk_urls(v, f"{label}[{i}]")


def watched_chunks(manifest: dict) -> dict:
    """label -> URL for every chunk the manifest records.

    The data blocks (by block name), then every other recorded URL in the same
    chunk directory that is not already a block's URL. Labels are the sources
    key path with the extractor's own key prefix stripped, so the external
    source is never spelled here.
    """
    blocks = dict(sorted(block_urls(manifest).items()))
    src = manifest.get("sources") if isinstance(manifest, dict) else None
    key = data_blocks_key(src)
    cdir = chunk_dir_of(blocks.values())
    if not key or not cdir:
        return blocks
    prefix = key[: -len(DATA_BLOCKS_SUFFIX)] + "_"
    taken = set(blocks.values())
    extra = {}
    for k, v in src.items():
        if not isinstance(k, str) or k in (key, HASHES_KEY):
            continue
        label = k[len(prefix):] if k.startswith(prefix) else k
        for sub, url in _walk_urls(v, label):
            name = url[len(cdir):] if url.startswith(cdir) else ""
            if name and "/" not in name and url not in taken:
                extra[sub] = url
    blocks.update(sorted(extra.items()))
    return blocks


def _chunk_refs(text: str, cdir_path: str) -> list:
    """Chunk names a page or chunk body references, in first-seen order.

    The two shapes the extractor crawls: `<last two dir segments>/<id>.js`
    (root script tags and worker manifests) and a bare `"<id>.js"` loader
    argument. The directory comes from the manifest's own URLs.
    """
    segs = [s for s in cdir_path.split("/") if s]
    tail = "/".join(segs[-2:]) + "/" if segs else ""
    pats = [_BARE_CHUNK_RE]
    if tail:
        pats.insert(0, re.compile(re.escape(tail) + r"([A-Za-z0-9_\-.]+\.js)"))
    seen, out = set(), []
    for rx in pats:
        for name in rx.findall(text):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def live_chunk_graph(root_url: str, cdir: str, http, want=(),
                     anchors: Optional[dict] = None):
    """Walk the live build's chunk graph from its root page. Never raises.

    Returns (summary, seen, candidates): summary.status is "ok" (every name in
    `want` is referenced; the walk stopped early), "complete" (graph
    exhausted), "partial" (exhausted, but a chunk failed to fetch), "capped"
    (a bound was hit) or "failed" (root page unreadable). `seen` is every
    chunk name referenced; `candidates` maps block -> live chunk names that
    carry its anchor, most hits first.
    """
    anchors = anchors or {}
    want = set(want)
    summary = {"root": root_url, "root_status": None, "status": "failed",
               "referenced": 0, "fetched": 0, "fetch_errors": 0}
    seen: set = set()
    hits: dict = {b: [] for b in anchors}
    try:
        st, body = http.get(root_url)
        summary["root_status"] = st
    except Exception:
        return summary, seen, {}
    if st != 200 or not body:
        return summary, seen, {}
    cdir_path = urlsplit(cdir).path

    def note(text: str) -> list:
        fresh = [n for n in _chunk_refs(text, cdir_path) if n not in seen]
        seen.update(fresh)
        return fresh

    frontier = note(bytes(body).decode("utf-8", "replace"))
    status, depth = None, 0
    while frontier and not want <= seen:
        if depth >= LIVE_CRAWL_MAX_DEPTH:
            status = "capped"
            break
        nxt = []
        for name in frontier:
            if want <= seen:
                break
            if summary["fetched"] >= LIVE_CRAWL_MAX_FETCH:
                status = "capped"
                break
            summary["fetched"] += 1
            try:
                cst, cbody = http.get(cdir + name)
            except Exception:
                cst, cbody = None, b""
            if cst != 200 or not cbody:
                summary["fetch_errors"] += 1
                continue
            text = bytes(cbody).decode("utf-8", "replace")
            for block, anchor in anchors.items():
                n = text.count(anchor)
                if n:
                    hits[block].append((n, name))
            nxt.extend(note(text))
        if status:
            break
        frontier, depth = nxt, depth + 1
    if want <= seen:
        status = "ok"
    elif status is None:
        status = "partial" if summary["fetch_errors"] else "complete"
    summary["status"] = status
    summary["referenced"] = len(seen)
    candidates = {b: [n for _, n in sorted(v, key=lambda t: (-t[0], t[1]))]
                  for b, v in hits.items() if v}
    return summary, seen, candidates


def check_live(manifest: dict, http, anchors: Optional[dict] = None):
    """Compare every recorded chunk URL against the live build's chunk set.

    Returns (summary, relocated, unverified). relocated maps label ->
    {old, new, candidates}: the recorded file is no longer referenced by the
    live build, and `new` is the live chunk now carrying the block's anchor
    (None when no anchor is known or none was found). A label not seen on a
    capped or partial walk, with no anchor match elsewhere, is unverified.
    """
    blocks = block_urls(manifest)
    cdir = chunk_dir_of(blocks.values())
    origin = origin_of(blocks.values())
    if not cdir or not origin:
        return ({"root": None, "root_status": None, "status": "failed",
                 "referenced": 0, "fetched": 0, "fetch_errors": 0}, {}, [])
    watched = watched_chunks(manifest)
    if anchors is None:
        anchors = extractor_anchors()
    anchors = {b: a for b, a in anchors.items() if b in blocks}
    want = {u[len(cdir):] for u in watched.values()}
    summary, seen, cands = live_chunk_graph(origin + "/", cdir, http, want,
                                            anchors)
    relocated, unverified = {}, []
    if summary["status"] == "failed":
        return summary, relocated, unverified
    certain = summary["status"] in ("ok", "complete")
    for label, url in watched.items():
        if url[len(cdir):] in seen:
            continue
        names = cands.get(label, [])
        if names or certain:
            relocated[label] = {"old": url,
                                "new": cdir + names[0] if names else None,
                                "candidates": [cdir + n for n in names]}
        else:
            unverified.append(label)
    return summary, relocated, sorted(unverified)


def watch(manifest: dict, high_water: str, http,
          now_iso: Optional[str] = None,
          anchors: Optional[dict] = None) -> dict:
    blocks = check_blocks(manifest, http, now_iso)
    prior = (manifest.get("sources") or {}).get(HASHES_KEY) or {}
    rehashed = {
        b for b, row in blocks.items()
        if row["body_md5"] and isinstance(prior.get(b), dict)
        and prior[b].get("body_md5") and prior[b]["body_md5"] != row["body_md5"]
    }
    live, relocated, unverified = check_live(manifest, http, anchors)
    moved = sorted(rehashed | set(relocated))
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
    return {"changelog": changelog, "blocks": blocks, "live": live,
            "relocated": relocated, "moved": moved, "unverified": unverified,
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
    lv = rep.get("live") or {}
    if lv.get("status") == "failed":
        lines.append(f"live build {lv.get('root')} status=FAILED"
                     f" root_status={lv.get('root_status')} - files rebuilt"
                     " under new names cannot be seen this run")
    else:
        lines.append(f"live build {lv.get('root')} status={lv.get('status')}"
                     f" referenced={lv.get('referenced')}"
                     f" fetched={lv.get('fetched')}"
                     f" fetch_errors={lv.get('fetch_errors')}")
    lines.append(f"MOVED: {', '.join(rep['moved']) or 'none'}")
    relocated = rep.get("relocated") or {}
    for label in rep["moved"]:
        r = relocated.get(label)
        if r is None:
            lines.append(f"  {label:<30} body hash changed at the same URL")
            continue
        new = r["new"].rsplit("/", 1)[-1] if r["new"] else "not in the live build"
        lines.append(f"  {label:<30} {r['old'].rsplit('/', 1)[-1]} -> {new}")
    lines.append(f"UNVERIFIED: {', '.join(rep.get('unverified') or []) or 'none'}")
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
