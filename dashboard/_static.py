"""Static-asset support helpers for dashboard routes.

Slice 2C (2026-05-01): pulled out of web_dashboard.py alongside
`dashboard.routes_static`. These helpers serve cached bytes for
the legacy index/manifest/icon files, compute the asset hash that
fingerprints css+js+html for cache-busting, and resolve paths under
the icon directory while blocking traversal attempts.
"""
import logging
import time
from pathlib import Path

from dashboard._context import APP_DIR

log = logging.getLogger("rc.web_dashboard")


# Cache for the asset hash so back-to-back index requests don't re-stat
# every file. 2 s TTL — same window /api/ui-version uses.
_ASSET_HASH_CACHE: dict = {"hash": "", "mtime": 0.0}


def compute_asset_hash() -> str:
    """AUDIT 2026-04-28 (3.1): hash the css+js+html mtimes the dashboard
    serves out of web/. Cached for 2 s so repeated index requests don't
    re-stat. The same files drive /api/ui-version so reload behaviour
    stays consistent."""
    import hashlib as _hashlib
    now = time.time()
    if _ASSET_HASH_CACHE.get("hash") and (now - _ASSET_HASH_CACHE["mtime"]) < 2.0:
        return _ASSET_HASH_CACHE["hash"]
    web_root = APP_DIR / "web"
    parts = []
    # s171.8: include js/main.js so edits to the s133 ESM entrypoint
    # also bust browser caches. Without this, view-router / handler
    # changes are invisible until a hard-reload. Also walk the panels/
    # subdirs so edits to per-panel ESM modules and per-panel CSS bust
    # the cache too — they're loaded through main.js / dashboard.css
    # imports, so without this any edit to a panel went unnoticed by
    # browsers until manual cache-clear.
    for rel in ("index.html", "css/dashboard.css", "js/dashboard.js",
                "js/main.js", "js/ws_client.js"):
        p = web_root / rel
        try:
            parts.append(f"{rel}:{int(p.stat().st_mtime)}")
        except OSError:
            parts.append(f"{rel}:0")
    for subdir, exts in (("css/panels", (".css",)),
                         ("js/panels", (".js",)),
                         ("js/lib", (".js",))):
        d = web_root / subdir
        try:
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix in exts:
                    parts.append(f"{subdir}/{f.name}:{int(f.stat().st_mtime)}")
        except OSError:
            pass
    h = _hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
    _ASSET_HASH_CACHE["hash"] = h
    _ASSET_HASH_CACHE["mtime"] = now
    return h


def inject_asset_hash(html: bytes) -> bytes:
    """Rewrite hardcoded `?v=YYYYMMDDNN` cache-bust queries on css/js refs
    in index.html with a freshly computed asset hash. Touches only the
    href/src attributes that already carry a `?v=…` so unrelated query
    strings aren't disturbed."""
    import re as _re
    h = compute_asset_hash()
    text = html.decode("utf-8", errors="replace")
    text = _re.sub(r'(\.(?:css|js))\?v=[^"\']+',
                   lambda m: f"{m.group(1)}?v={h}",
                   text)
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
    except Exception:
        return None
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


_LEGACY_INDEX_PATH = APP_DIR / "web" / "legacy_index.html"
_LEGACY_INDEX_CACHE: bytes | None = None


def legacy_index_html() -> bytes:
    global _LEGACY_INDEX_CACHE
    if _LEGACY_INDEX_CACHE is None:
        _LEGACY_INDEX_CACHE = _LEGACY_INDEX_PATH.read_bytes()
    return _LEGACY_INDEX_CACHE


_MANIFEST_PATH = APP_DIR / "web" / "manifest.json"
_MANIFEST_CACHE: bytes | None = None


def manifest_bytes() -> bytes:
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is None:
        _MANIFEST_CACHE = _MANIFEST_PATH.read_bytes()
    return _MANIFEST_CACHE


_ICON_SVG_PATH = APP_DIR / "web" / "icon.svg"
_ICON_SVG_CACHE: bytes | None = None


def icon_svg_bytes() -> bytes:
    global _ICON_SVG_CACHE
    if _ICON_SVG_CACHE is None:
        _ICON_SVG_CACHE = _ICON_SVG_PATH.read_bytes()
    return _ICON_SVG_CACHE
