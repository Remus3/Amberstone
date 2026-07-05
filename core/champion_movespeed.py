"""Champion movement-speed primitives (spec E-pre, ZOI/district program).

Pure, lazy-loading lookups for the future MIA-reachability consumer:

  - base_ms(champion)          -> base movement speed from the DDragon mirror
  - item_ms(items)             -> {"flat": F, "pct": P} movement-speed stats
  - est_ms(champion, items)    -> (base + flat) * (1 + pct)
  - distance_frac_per_s(ms)    -> map-units/s converted to box-fraction/s

Data sources (local mirrors, read lazily on first call, cached):
  - data/meta/ddragon_champions.json  {"data": {<DDragonId>: {"id", "name",
    "stats": {"movespeed": <int>}}}}. Champion lookup accepts the DDragon id
    ("MissFortune"), the display name ("Miss Fortune"), apostrophe/space/dot
    stripped variants and any casing - the same multi-key index pattern as
    core/defensive_picks.py:83-88.
  - data/meta/ddragon_items.json  {"data": {<id-str>: {"name", "stats": {...}}}}
    using the DS movement-speed stat vocabulary (agents/daemon_slayer/
    stats.py:107-108): FlatMovementSpeedMod (flat units) and
    PercentMovementSpeedMod (unit-fraction, 0.04 == +4%).

Fallbacks (documented, conservative):
  - Unknown / None / non-string champion -> 345.0 (the most common base MS;
    conservative for reachability - most roaming champs are 335-355).
  - Unknown item / missing or corrupt data file -> zero MS contribution.
  - distance_frac_per_s on bad input -> 0.0 (an MIA ring that never grows is
    the safe degrade; SR map extent ~14800 units per core/vision_tracker.py:55).

Design: 100% pure plain python, no DS-engine imports, no I/O at module import
time (JSON mirrors load lazily inside the accessors, cached at module level).
Fail-soft, NEVER raises - mirrors core/zoi_influence.py. ASCII only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger("rc.champion_movespeed")

_META_DIR = Path(__file__).resolve().parent.parent / "data" / "meta"
_CHAMPS_PATH = _META_DIR / "ddragon_champions.json"
_ITEMS_PATH = _META_DIR / "ddragon_items.json"

# Conservative default when the champion is unknown (see module docstring).
_FALLBACK_MS = 345.0

# SR map extent in game units (core/vision_tracker.py:55).
_SR_MAP_EXTENT = 14800.0

# DS movement-speed stat vocabulary (agents/daemon_slayer/stats.py:107-108).
_MS_FLAT_KEY = "FlatMovementSpeedMod"
_MS_PCT_KEY = "PercentMovementSpeedMod"

# Lazy module-level caches. None == not loaded yet; {} == load failed/empty
# (both are cheap re-checks; a failed load caches the empty dict so we do not
# re-stat a missing file on every call).
_CHAMP_MS: dict[str, float] | None = None
_ITEM_MS: dict[str, tuple[float, float]] | None = None


def _reset_caches() -> None:
    """Test seam: drop the lazy caches (mirrors the reset-seam habit in
    dashboard/_deterministic_coaching.py)."""
    global _CHAMP_MS, _ITEM_MS
    _CHAMP_MS = None
    _ITEM_MS = None


def _num(v):
    """Coerce to a finite float, or None (same guard as core/zoi_influence.py)."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _name_keys(raw: str):
    """All lookup keys for one champion string: casefolded exact plus
    apostrophe / space / dot / ampersand stripped variants."""
    base = raw.casefold().strip()
    if not base:
        return
    yield base
    stripped = base
    for ch in ("'", " ", ".", "&"):
        stripped = stripped.replace(ch, "")
    if stripped and stripped != base:
        yield stripped


def _champ_index() -> dict[str, float]:
    """normalized champion key -> base movespeed. Empty dict on any failure."""
    global _CHAMP_MS
    if _CHAMP_MS is not None:
        return _CHAMP_MS
    out: dict[str, float] = {}
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            ms = _num((entry.get("stats") or {}).get("movespeed"))
            if ms is None or ms <= 0.0:
                continue
            for form in (key, entry.get("id"), entry.get("name")):
                if not isinstance(form, str):
                    continue
                for k in _name_keys(form):
                    out.setdefault(k, ms)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.warning("champion_movespeed: champ index load failed: %s", exc)
        out = {}
    _CHAMP_MS = out
    return out


def _item_index() -> dict[str, tuple[float, float]]:
    """item id-str AND casefolded item name -> (flat_ms, pct_ms).
    Empty dict on any failure."""
    global _ITEM_MS
    if _ITEM_MS is not None:
        return _ITEM_MS
    out: dict[str, tuple[float, float]] = {}
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        # Canonical short ids first: 6-digit "22"-prefixed ids are Arena/alias
        # mirrors of the same display name with different stats (e.g. 3009 vs
        # 223009 Boots of Swiftness), so name keys must setdefault to the
        # canonical entry (memory reference_items_index_alias_ids).
        for iid in sorted(data, key=lambda k: (len(str(k)), str(k))):
            entry = data[iid]
            if not isinstance(entry, dict):
                continue
            stats = entry.get("stats") or {}
            flat = _num(stats.get(_MS_FLAT_KEY)) or 0.0
            pct = _num(stats.get(_MS_PCT_KEY)) or 0.0
            if flat == 0.0 and pct == 0.0:
                continue
            pair = (flat, pct)
            out.setdefault(str(iid).strip(), pair)
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                out.setdefault(name.casefold().strip(), pair)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.warning("champion_movespeed: item index load failed: %s", exc)
        out = {}
    _ITEM_MS = out
    return out


def base_ms(champion) -> float:
    """Base movement speed for a champion. Accepts the DDragon id
    ("MissFortune"), the display name ("Miss Fortune"), apostrophe variants
    ("Kha'Zix" / "Khazix") and any casing. Unknown / None / non-string ->
    345.0 conservative fallback. Never raises."""
    try:
        if not isinstance(champion, str):
            return _FALLBACK_MS
        idx = _champ_index()
        for k in _name_keys(champion):
            ms = idx.get(k)
            if ms is not None:
                return ms
        return _FALLBACK_MS
    except Exception:  # noqa: BLE001 - fail-soft contract
        return _FALLBACK_MS


def _item_key(item) -> str | None:
    """One item spec -> a lookup key string, or None if unusable. Accepts an
    id (int or str), a name (str), or a Live Client item dict carrying
    itemID / displayName (dashboard/_liveclient.py:131,135)."""
    if isinstance(item, bool):
        return None
    if isinstance(item, int):
        return str(item)
    if isinstance(item, str):
        s = item.strip()
        return s.casefold() if s else None
    if isinstance(item, dict):
        iid = item.get("itemID")
        if isinstance(iid, int) and not isinstance(iid, bool):
            return str(iid)
        if isinstance(iid, str) and iid.strip():
            return iid.strip()
        name = item.get("displayName") or item.get("name")
        if isinstance(name, str) and name.strip():
            return name.casefold().strip()
    return None


def item_ms(item_ids_or_names) -> dict:
    """Summed movement-speed stats over a collection of items ->
    {"flat": <units>, "pct": <unit-fraction>}. Accepts item ids (int/str),
    item display names, Live Client item dicts, or a single bare id/name.
    Unknown items contribute zero. Never raises."""
    flat = 0.0
    pct = 0.0
    try:
        items = item_ids_or_names
        if items is None:
            items = []
        elif isinstance(items, (str, int, dict)):
            items = [items]
        idx = _item_index()
        for item in items:
            key = _item_key(item)
            if key is None:
                continue
            pair = idx.get(key)
            if pair is None and isinstance(item, str):
                # A bare string might be an id typed with spaces trimmed only.
                pair = idx.get(key.strip())
            if pair is None:
                continue
            flat += pair[0]
            pct += pair[1]
    except Exception:  # noqa: BLE001 - fail-soft contract
        return {"flat": 0.0, "pct": 0.0}
    return {"flat": flat, "pct": pct}


def est_ms(champion, items=None, level=None) -> float:
    """Estimated movement speed: (base + flat_item_ms) * (1 + pct_item_ms).

    ``level`` is accepted for signature stability with the future MIA
    consumer but ignored - base MS does not scale with level in League.
    Empty / None ``items`` == base_ms(champion). Never raises."""
    try:
        base = base_ms(champion)
        parts = item_ms(items)
        out = (base + parts["flat"]) * (1.0 + parts["pct"])
        checked = _num(out)
        if checked is None or checked <= 0.0:
            return base
        return checked
    except Exception:  # noqa: BLE001 - fail-soft contract
        return _FALLBACK_MS


def distance_frac_per_s(ms, map_extent=_SR_MAP_EXTENT) -> float:
    """Convert movement speed (map-units/s) to box-fraction/s of a square
    minimap covering ``map_extent`` game units (SR ~14800, see
    core/vision_tracker.py:55). Bad ms or extent -> 0.0 (an MIA ring that
    never grows is the safe degrade). Never raises."""
    try:
        speed = _num(ms)
        extent = _num(map_extent)
        if speed is None or speed <= 0.0:
            return 0.0
        if extent is None or extent <= 0.0:
            return 0.0
        return speed / extent
    except Exception:  # noqa: BLE001 - fail-soft contract
        return 0.0
