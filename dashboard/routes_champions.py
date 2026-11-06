# arch: GET /api/champions | section=dashboard | frozen=no
"""GET /api/champions - DDragon championId -> {name, slug} map (cached).

Carved out of routes_bridge.py when the cross-Claude bridge was
decommissioned (2026-06-24). The map feeds the user-build champion datalist
(``web/js/main.js`` ``_ubChampionsList``); it has no bridge dependency.

Contract (true-audit s144 cycle 158, tests/test_routes_champions_true_audit_s144t158.py):

- Always HTTP 200 with a JSON object ``{"<id>": {"name", "slug"}}``; a missing
  or unreadable file degrades to the last good map, or ``{}`` before the first
  good read. The raw error goes to the log, never to the response.
- The cache is keyed on the file's (mtime_ns, size), so a DDragon patch refresh
  reaches the map without an RC restart, and a FAILED read is never cached: the
  next request tries again (RM-1935, RM-1936).
- Only a positive integer id is admitted: an int (never a bool) or a string of
  ASCII digits; floats, signs, padding, non-ASCII digits and absurd lengths are
  skipped, never coerced (RM-1937). A name that is not a non-blank string
  falls back to the slug (RM-1938).
- Only the expected read / parse failures degrade; any other exception is a
  bug and propagates to the dispatcher (RM-1939).
"""
from __future__ import annotations

import json
import logging
import re
import threading

from dashboard._context import APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.routes_champions")

# A DDragon champion key: ASCII digits only. Seven digits covers the live
# roster (1..950) and the throwback band (base + 60000) with room to spare,
# and bounds int() far below the interpreter's digit-count limit.
_KEY_RE = re.compile(r"[0-9]{1,7}")
_MAX_ID = 10 ** 7

# Expected failures of one read + parse: absent / locked / mid-replace file,
# bad UTF-8, bad JSON, or JSON nested past the decoder's recursion limit.
_READ_ERRORS = (OSError, ValueError, RecursionError)

# (signature, encoded body) of the last GOOD read, or None before the first
# one. Replaced whole under the lock, never mutated; nothing outside this
# module reads it.
_CACHE: tuple[tuple[int, int], bytes] | None = None
_LOCK = threading.Lock()


def _champions_path():
    return APP_DIR / "data" / "meta" / "ddragon_champions.json"


def _champion_id(raw) -> int | None:
    """The positive integer id in a DDragon ``key``, or None when it is junk."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        cid = raw
    elif isinstance(raw, str) and _KEY_RE.fullmatch(raw):
        cid = int(raw)
    else:
        return None
    return cid if 0 < cid < _MAX_ID else None


def _build_map(doc) -> dict:
    """{str(id): {name, slug}} from a parsed DDragon champion document."""
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        log.warning("api/champions: document has no 'data' object")
        return {}
    out: dict = {}
    skipped = 0
    for slug, entry in data.items():
        cid = _champion_id(entry.get("key")) if isinstance(entry, dict) else None
        if cid is None:
            skipped += 1
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            name = slug
        out[str(cid)] = {"name": name, "slug": slug}
    if skipped:
        log.warning("api/champions: skipped %d malformed entr%s",
                    skipped, "y" if skipped == 1 else "ies")
    return out


def _load() -> bytes:
    """The encoded map, re-read only when the file changed since the last
    good read. A failed read serves the last good body (or ``{}``) and is
    not cached, so the next request retries."""
    global _CACHE
    path = _champions_path()
    with _LOCK:
        cached = _CACHE
        try:
            st = path.stat()
            sig = (st.st_mtime_ns, st.st_size)
            if cached is not None and cached[0] == sig:
                return cached[1]
            doc = json.loads(path.read_text(encoding="utf-8"))
        except _READ_ERRORS as exc:
            log.warning("api/champions: read failed: %s", exc)
            return cached[1] if cached is not None else b"{}"
        body = json.dumps(_build_map(doc)).encode("ascii")
        _CACHE = (sig, body)
        return body


def _serve_champions(h) -> None:
    h._send(200, _load(), "application/json")


GET_ROUTES = [
    (equals("/api/champions"), _serve_champions),
]

POST_ROUTES: list = []
