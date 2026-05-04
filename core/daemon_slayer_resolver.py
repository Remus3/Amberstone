"""Item name → ID resolver for Daemon Slayer wire-in.

Coach loops carry item NAMES (display strings: ``"Infinity Edge"``,
``"Berserker's Greaves"``); the engine speaks IDs. ``web/data/items_index.json``
already holds the mapping, normalized as ``byName[lower-no-punct] -> id``.

Lazy-loaded singleton with mtime-based refresh (cheap; the index file
changes only on patch refresh). ``resolve_many`` skips unknown names
silently — Phase 7 tolerates partial resolution rather than failing the
whole tick.

Phase 4 batch 19 wire-in (s73, 2026-05-04): also exposes
``bonus_hp_for_id`` / ``total_bonus_hp`` lazy-loaded from the
patch-current DDragon ``items.json``. Coach-side estimators
(arena_coach._estimate_target_bonus_hp) sum HP across the next
opponent's items to feed the engine's Giant Slayer amp deterministically.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("rc.core.daemon_slayer_resolver")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_INDEX_PATH = _PROJECT_ROOT / "web" / "data" / "items_index.json"
_DS_DATA_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"
_PATCH_FILE = _DS_DATA_DIR / "current.txt"

_lock = threading.Lock()
_cache: dict[str, str] = {}
_cache_mtime: float = 0.0

# Item HP lookup cache. Keyed by item id (str) → FlatHPPoolMod (float).
# Populated lazily from the patch-current DDragon items.json. mtime gate
# refreshes on patch bump.
_hp_lock = threading.Lock()
_hp_cache: dict[str, float] = {}
_hp_cache_mtime: float = 0.0
_hp_cache_patch: str = ""


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


def _current_patch() -> Optional[str]:
    try:
        return _PATCH_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _items_json_path() -> Optional[Path]:
    patch = _current_patch()
    if not patch:
        return None
    candidate = _DS_DATA_DIR / patch / "items.json"
    return candidate if candidate.exists() else None


def _load_hp_if_stale() -> None:
    """Populate ``_hp_cache`` from the patch-current DDragon items.json.

    Walks the ``data.<id>`` block, extracts ``stats.FlatHPPoolMod`` per
    entry. Items without an HP stat get 0.0 implicitly (missing key on
    .get). mtime-gated refresh, same shape as ``_load_if_stale`` for
    items_index.
    """
    global _hp_cache, _hp_cache_mtime, _hp_cache_patch
    path = _items_json_path()
    if path is None:
        logger.debug("items.json missing for current patch; HP cache empty")
        return
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return
    patch = _current_patch() or ""
    if (
        _hp_cache
        and mtime == _hp_cache_mtime
        and patch == _hp_cache_patch
    ):
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("DDragon items.json read failed: %s", e)
        return
    data = doc.get("data") or {}
    new_cache: dict[str, float] = {}
    for iid, rec in data.items():
        if not isinstance(rec, dict):
            continue
        stats = rec.get("stats") or {}
        hp = stats.get("FlatHPPoolMod")
        if hp is None:
            continue
        try:
            new_cache[str(iid)] = float(hp)
        except (TypeError, ValueError):
            continue
    with _hp_lock:
        _hp_cache = new_cache
        _hp_cache_mtime = mtime
        _hp_cache_patch = patch
    logger.debug(
        "DDragon HP cache refreshed: %d entries (patch %s)",
        len(new_cache), patch,
    )


def bonus_hp_for_id(item_id: str) -> float:
    """Bonus HP contribution from an item ID. 0.0 if unknown / no HP stat.

    "Bonus HP" in the LCU sense — the HP component the item adds on top
    of champion base. DDragon's ``FlatHPPoolMod`` is exactly this number
    (LCU's ``items[*].rawDescription`` tags it as bonus HP, not max HP
    overlap). Items without a ``FlatHPPoolMod`` return 0.0 (no signal).
    """
    if not item_id:
        return 0.0
    _load_hp_if_stale()
    return _hp_cache.get(str(item_id), 0.0)


def total_bonus_hp(item_ids: Iterable[str]) -> float:
    """Sum of ``bonus_hp_for_id`` across a list of IDs. Stable on empty."""
    return sum(bonus_hp_for_id(i) for i in (item_ids or []))
