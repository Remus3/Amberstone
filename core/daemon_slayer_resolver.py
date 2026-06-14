"""Item name → ID resolver for Daemon Slayer wire-in.

Coach loops carry item NAMES (display strings: ``"Infinity Edge"``,
``"Berserker's Greaves"``); the engine speaks IDs. ``web/data/items_index.json``
already holds the mapping, normalized as ``byName[lower-no-punct] -> id``.

Lazy-loaded singleton with mtime-based refresh (cheap; the index file
changes only on patch refresh). ``resolve_many`` skips unknown names
silently - Phase 7 tolerates partial resolution rather than failing the
whole tick.

Phase 4 batch 19 wire-in (s73, 2026-05-04): also exposes
``bonus_hp_for_id`` / ``total_bonus_hp`` lazy-loaded from the
patch-current DDragon ``items.json``. Coach-side estimators
(arena_coach._estimate_target_bonus_hp) sum HP across the next
opponent's items to feed the engine's Giant Slayer amp deterministically.

s74 (2026-05-04) - mode-aware lookup. ``items_index.json``'s ``byName``
picks the 22XXXX-prefixed Arena alias (e.g. ``Heartsteel`` → ``223084``)
because of a ``setdefault`` first-seen-wins quirk during pipeline build
(see ``reference_items_index_alias_ids``). For Arena coach this is
silently correct; for SR / ARAM / Brawl coaches it would return Arena HP
(700) instead of base HP (900). ``name_to_id(name, mode=...)`` uses the
DDragon ``maps`` field as the canonical filter:

==========  ===  ==========================
mode str    map  notes
==========  ===  ==========================
"sr"         11  Summoner's Rift
"aram"       12  Howling Abyss
"arena"      30  Arena (uses 22XXXX aliases)
"brawl"      35  Brawl / Swiftplay
==========  ===  ==========================

``mode=None`` resolves via ``items_index.json`` byName. As of commit 41c87bc
that index sorts by ID length so canonical 4-digit IDs win over 22XXXX Arena
aliases - the legacy alias quirk is gone; mode=None now returns base IDs.
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

# Item HP lookup cache. Keyed by item id (str) -> FlatHPPoolMod (float).
# Populated lazily from the patch-current DDragon items.json. mtime gate
# refreshes on patch bump.
_hp_lock = threading.Lock()
_hp_cache: dict[str, float] = {}
_hp_cache_mtime: float = 0.0
_hp_cache_patch: str = ""

# s74 - mode-aware byName cache. Keyed by mode short name -> normalized-name
# -> item id. Populated in the same pass as ``_hp_cache`` (one load of the
# patch-current DDragon items.json builds both). Map IDs from DDragon's
# ``maps`` field per item.
_MODE_TO_DDRAGON_MAP_ID: dict[str, str] = {
    "sr":    "11",
    "aram":  "12",
    "arena": "30",
    "brawl": "35",
}
_byname_by_mode: dict[str, dict[str, str]] = {}


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


def name_to_id(name: str, mode: Optional[str] = None) -> Optional[str]:
    """Resolve display name to item ID. None if unknown.

    ``mode`` (optional, s74) selects a map-aware byName index built from
    DDragon's ``maps`` field. Accepts ``"sr" | "aram" | "arena" | "brawl"``
    (case-insensitive). When omitted, falls back to the legacy
    ``items_index.json`` byName. Post-commit 41c87bc that index returns
    canonical 4-digit IDs (the old Arena-alias leakage quirk is fixed).
    """
    if not name:
        return None
    if mode:
        key = mode.strip().lower()
        if key in _MODE_TO_DDRAGON_MAP_ID:
            _load_hp_if_stale()  # also populates _byname_by_mode
            mode_idx = _byname_by_mode.get(key) or {}
            hit = mode_idx.get(_normalize(name))
            if hit:
                return hit
            # No mode hit - fall through to legacy index. Items missing a
            # ``maps`` block in DDragon (rare) still resolve via the
            # patch-build mapping; preserves prior coverage.
    _load_if_stale()
    return _cache.get(_normalize(name))


def resolve_many(names: Iterable[str], mode: Optional[str] = None) -> list[str]:
    """Resolve a list of names; unknowns dropped silently. Order preserved.

    ``mode`` is forwarded to ``name_to_id``; see that docstring for semantics.
    """
    out: list[str] = []
    for n in names or []:
        iid = name_to_id(n, mode=mode)
        if iid:
            out.append(iid)
    return out


# 2026-05-09 (s156): items that occupy non-inventory slots (trinket/consumable
# row) and therefore must NOT count against the 6-slot DS engine budget.
# Live-Client API serializes them inline with shop items, so resolvers see
# all 7+ together. Without this filter, /rank rejects the call once the
# user buys their 5th component+trinket combo with
#   "current_item_ids has 6 items; slot_count=6 leaves no room for a new item"
# and the SR coach silently drops daemon_slayer_picks -> dashboard #ds-pill
# stays hidden mid-game.
NON_INVENTORY_IDS = frozenset({
    # Trinkets (yellow/blue/red row, 1 slot reserved separately by client)
    "3340",  # Stealth Ward (default)
    "3363",  # Farsight Alteration (blue)
    "3364",  # Oracle Lens (red)
    # Consumables (potion/biscuit/refillable rows; not equipped)
    "2003",  # Health Potion
    "2031",  # Refillable Potion
    "2055",  # Control Ward
    "2138",  # Elixir of Iron
    "2139",  # Elixir of Sorcery
    "2140",  # Elixir of Wrath
})


def resolve_inventory(names: Iterable[str], mode: Optional[str] = None) -> list[str]:
    """Like ``resolve_many`` but drops trinkets and consumables - items
    that don't compete for the 6 inventory slots the DS engine ranks.

    Use this from coach loops that feed ``current_item_ids`` to
    ``daemon_slayer_client.rank_for`` / ``dps_for``. ``resolve_many``
    stays untouched for callers that need the full set (calibration
    snapshots, raw-id mirrors, etc).
    """
    out: list[str] = []
    for n in names or []:
        iid = name_to_id(n, mode=mode)
        if iid and iid not in NON_INVENTORY_IDS:
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
    """Populate ``_hp_cache`` + ``_byname_by_mode`` from the patch-current
    DDragon items.json.

    Single pass over the ``data.<id>`` block. Per entry: extract
    ``stats.FlatHPPoolMod`` for the HP cache, ``maps`` for the per-mode
    byName index. Items without an HP stat are skipped from ``_hp_cache``
    but still indexed in ``_byname_by_mode``. mtime-gated refresh; same
    shape as ``_load_if_stale``.
    """
    global _hp_cache, _hp_cache_mtime, _hp_cache_patch, _byname_by_mode
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
    new_hp: dict[str, float] = {}
    new_byname: dict[str, dict[str, str]] = {m: {} for m in _MODE_TO_DDRAGON_MAP_ID}
    for iid, rec in data.items():
        if not isinstance(rec, dict):
            continue
        stats = rec.get("stats") or {}
        hp = stats.get("FlatHPPoolMod")
        if hp is not None:
            try:
                new_hp[str(iid)] = float(hp)
            except (TypeError, ValueError):
                pass
        # Per-mode byName index. ``maps`` is ``{ "11": True, "12": False, ... }``.
        # Skip purchasable=False; those are recipe-only / unbuyable shells
        # (e.g. starter quests) and shouldn't shadow the real legendary.
        if rec.get("purchasable") is False:
            continue
        name = rec.get("name") or ""
        if not name:
            continue
        norm = _normalize(name)
        if not norm:
            continue
        maps = rec.get("maps") or {}
        for mode, ddragon_map_id in _MODE_TO_DDRAGON_MAP_ID.items():
            if maps.get(ddragon_map_id) is True:
                # First-write-wins per mode. DDragon should not have name+map
                # collisions for real legendaries; if it ever does, the first
                # entry alphabetically wins. Logged at debug if we hit one.
                if norm not in new_byname[mode]:
                    new_byname[mode][norm] = str(iid)
                else:
                    logger.debug(
                        "byName mode collision: %s on %s already=%s, skipping %s",
                        norm, mode, new_byname[mode][norm], iid,
                    )
    with _hp_lock:
        _hp_cache = new_hp
        _hp_cache_mtime = mtime
        _hp_cache_patch = patch
        _byname_by_mode = new_byname
    logger.debug(
        "DDragon HP cache refreshed: %d entries (patch %s); per-mode byName: %s",
        len(new_hp), patch,
        {m: len(v) for m, v in new_byname.items()},
    )


def bonus_hp_for_id(item_id: str) -> float:
    """Bonus HP contribution from an item ID. 0.0 if unknown / no HP stat.

    "Bonus HP" in the LCU sense - the HP component the item adds on top
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
