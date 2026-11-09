"""Static-asset support helpers for dashboard routes.

Slice 2C (2026-05-01): pulled out of web_dashboard.py alongside
`dashboard.routes_static`. These helpers serve cached bytes for
the legacy index/manifest/icon files, compute the asset hash that
fingerprints css+js+html for cache-busting, and resolve paths under
the icon directory while blocking traversal attempts.
"""
import hashlib
import logging
import os
import re
import time
from pathlib import Path

from dashboard._context import APP_DIR

log = logging.getLogger("rc.web_dashboard")


# Cache for the asset hash so back-to-back index requests don't re-stat
# every file. 2 s TTL - same window /api/ui-version uses. "at" is a
# time.monotonic() stamp (s144 true-audit cycle 175, F2): the wall clock it
# used before can step backwards, and a negative age passed the "< TTL" test,
# freezing the reload signal for as long as the step lasted. An empty "hash"
# always forces a recompute, which is what the tests reset.
_ASSET_HASH_TTL_S = 2.0
_ASSET_HASH_CACHE: dict = {"hash": "", "at": 0.0}

# Y-11 (external reference L2): the ONE fileset behind every reload signal
# (the ?v= rewrite, /api/ui-version and /api/asset-stamp). It is a glob of the
# served trees, not a hand list: the hand lists that came before it missed the
# stylesheets dashboard.css @imports from the css/ root (tokens.css,
# themes.css, hextech.css), so a design-token edit never reloaded the browser
# or the overlay. ADR-008 still holds; this only widens its key.
_ASSET_TREES = (("css", ".css"), ("js", ".js"))
# Pruned explicitly at directory level (os.walk; rglob never prunes). js/test
# holds the node --test harness, which the page never loads. Dot-directories
# are pruned too. tests/test_asset_fileset_y11.py pins this set.
ASSET_PRUNE_DIRS = frozenset({"test", "node_modules", "__pycache__"})


def asset_fileset(web_root: Path | None = None) -> list[tuple[str, Path]]:
    """Every served dashboard asset as (relative posix path, absolute Path):
    web/index.html + web/css/**/*.css + web/js/**/*.js, sorted by the
    relative path. Missing trees contribute nothing (never raises on them)."""
    root = Path(web_root) if web_root is not None else APP_DIR / "web"
    out: list[tuple[str, Path]] = []
    index = root / "index.html"
    if index.is_file():
        out.append(("index.html", index))
    for sub, ext in _ASSET_TREES:
        base = root / sub
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d not in ASSET_PRUNE_DIRS and not d.startswith(".")]
            for name in filenames:
                if name.endswith(ext):
                    full = Path(dirpath) / name
                    out.append((full.relative_to(root).as_posix(), full))
    out.sort(key=lambda item: item[0])
    return out


def compute_asset_hash() -> str:
    """AUDIT 2026-04-28 (3.1): hash the css+js+html mtimes the dashboard
    serves out of web/. Cached for 2 s so repeated index requests don't
    re-stat. The same files drive /api/ui-version and /api/asset-stamp
    (all three go through asset_fileset(), Y-11) so reload behaviour stays
    consistent.

    Each file is keyed on st_mtime_ns AND st_size (s144 true-audit cycle 175,
    F1): the whole-second int(st_mtime) it used before left the hash unchanged
    for a second save inside the same second, so that edit never reloaded the
    page or the overlay. A file that vanishes between the walk and the stat
    hashes as `rel:0:0`, which still differs from its live key."""
    now = time.monotonic()
    cached = _ASSET_HASH_CACHE.get("hash")
    age = now - _ASSET_HASH_CACHE.get("at", 0.0)
    if cached and 0.0 <= age < _ASSET_HASH_TTL_S:
        return cached
    parts = []
    for rel, p in asset_fileset():
        try:
            st = p.stat()
        except OSError:
            parts.append(f"{rel}:0:0")
            continue
        parts.append(f"{rel}:{st.st_mtime_ns}:{st.st_size}")
    h = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    # One update call: a concurrent reader never pairs a new hash with an
    # old stamp from a half-written cache.
    _ASSET_HASH_CACHE.update({"hash": h, "at": now})
    return h


# The `?v=` value stops at the attribute's quote, a following query
# parameter, a fragment, whitespace or the tag end (F3: the old `[^"']+`
# tail swallowed `&theme=dark` and anything after it).
_ASSET_QUERY_RE = re.compile(r"(\.(?:css|js))\?v=[^\"'&#\s>]+")


def inject_asset_hash(html: bytes) -> bytes:
    """Rewrite hardcoded `?v=YYYYMMDDNN` cache-bust queries on css/js refs
    in index.html with a freshly computed asset hash. Touches only the
    `v` value of refs that already carry a `?v=...`, so other query
    parameters and unrelated query strings aren't disturbed."""
    h = compute_asset_hash()
    text = html.decode("utf-8", errors="replace")
    text = _ASSET_QUERY_RE.sub(lambda m: f"{m.group(1)}?v={h}", text)
    return text.encode("utf-8")


def resolve_safe_icon(root: Path, rel: str) -> Path | None:
    # 2026-04-27 audit: defense-in-depth for /icons/* endpoints. The
    # original substring checks ("/" in rel or ".." in rel) miss
    # backslashes on Windows and symlink targets. This helper canonicalises
    # both paths and returns None unless the resolved file is a regular
    # file inside `root`.
    if not rel or "/" in rel or "\\" in rel or ".." in rel or not rel.endswith(".png"):
        return None
    try:
        candidate = (root / rel).resolve()
        root_resolved = root.resolve()
    except (OSError, ValueError, RuntimeError):
        # What resolve really raises: an OS refusal, a bad name (embedded
        # null), a symlink loop. Anything else is a bug and reaches the
        # route's logged 500 instead of a silent 404 (cycle 175, F4).
        return None
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


# Cached bytes of the three fixed static responses, keyed by path and
# re-read whenever the file's (st_mtime_ns, st_size) changes (cycle 175, F5):
# the process-lifetime cache this replaced never served an edit to the
# fallback UI, the manifest or the icon until RC restarted. A missing file
# raises FileNotFoundError on every call, as before; a failure is never
# cached. A stat-then-read race at worst caches new bytes under the old key,
# and the next call's stat re-reads them.
_FILE_CACHE: dict[Path, tuple[tuple[int, int], bytes]] = {}


def _read_cached(path: Path) -> bytes:
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    hit = _FILE_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    data = path.read_bytes()
    _FILE_CACHE[path] = (key, data)
    return data


_LEGACY_INDEX_PATH = APP_DIR / "web" / "legacy_index.html"


def legacy_index_html() -> bytes:
    return _read_cached(_LEGACY_INDEX_PATH)


_MANIFEST_PATH = APP_DIR / "web" / "manifest.json"


def manifest_bytes() -> bytes:
    return _read_cached(_MANIFEST_PATH)


_ICON_SVG_PATH = APP_DIR / "web" / "icon.svg"


def icon_svg_bytes() -> bytes:
    return _read_cached(_ICON_SVG_PATH)
