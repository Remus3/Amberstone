"""Item name → ID resolver for Daemon Slayer wire-in.

Coach loops carry item NAMES (display strings: ``"Infinity Edge"``,
``"Berserker's Greaves"``); the engine speaks IDs. ``web/data/items_index.json``
already holds the mapping, normalized as ``byName[lower-no-punct] -> id``.

Lazy-loaded singleton with mtime-based refresh (cheap; the index file
changes only on patch refresh). ``resolve_many`` skips unknown names
silently — Phase 7 tolerates partial resolution rather than failing the
whole tick.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("rc.core.daemon_slayer_resolver")

_INDEX_PATH = Path(__file__).resolve().parent.parent / "web" / "data" / "items_index.json"

_lock = threading.Lock()
_cache: dict[str, str] = {}
_cache_mtime: float = 0.0


def _normalize(name: str) -> str:
    return "".join(c.lower() for c in name if c.isalnum())


def _load_if_stale() -> None:
    global _cache, _cache_mtime
    try:
        mtime = _INDEX_PATH.stat().st_mtime
    except OSError as e:
        logger.debug("items_index missing: %s", e)
        return
    if mtime == _cache_mtime and _cache:
        return
    try:
        doc = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("items_index read failed: %s", e)
        return
    by_name = doc.get("byName") or {}
    new_cache: dict[str, str] = {str(k): str(v) for k, v in by_name.items() if v}
    with _lock:
        _cache = new_cache
        _cache_mtime = mtime
    logger.debug("items_index refreshed: %d entries", len(new_cache))


def name_to_id(name: str) -> Optional[str]:
    """Resolve display name to item ID. None if unknown."""
    if not name:
        return None
    _load_if_stale()
    return _cache.get(_normalize(name))


def resolve_many(names: Iterable[str]) -> list[str]:
    """Resolve a list of names; unknowns dropped silently. Order preserved."""
    out: list[str] = []
    for n in names or []:
        iid = name_to_id(n)
        if iid:
            out.append(iid)
    return out
