"""User-curated additive build store for Phase 8 SR Draft Theatre.

Operator-additive invariant: builds saved here APPEND to the 3
engine-generated profiles in the SR-draft chooser. They are NEVER
overwritten or auto-edited by the engine, and the engine generator
in `sr_draft_profile.py` does not read or write this store. Merging
happens at the route layer.

Storage: `data/daemon_slayer/user_builds.json`. Single JSON file,
mtime-cached so hand-edits land without RC restart, atomic-written
(`tmp.write_text -> tmp.replace`) per the project default.

Schema (per build, keyed under `champions[<DisplayName>]`):

  {
    "id":           "<8-char hex>",            # generated on add()
    "label":        "off-meta lethality",      # required, free-form
    "mode":         "sr",                      # always "sr" today
    "role":         "BOTTOM",                  # optional
    "runes": {
      "keystone":   "Hail of Blades",
      "primary":    "Domination",
      "secondary":  "Precision"
    },
    "summoner_spells": [4, 7],                 # [d, f] LCU IDs
    "items":        ["Opportunity", "Edge of Night", ...],
    "notes":        "lethality 3-item rush",   # optional
    "created_at":   1746345600,                # unix seconds
    "updated_at":   1746345600
  }

Top-level file shape:

  {
    "champions": {
      "Tristana": [ {build1}, {build2} ],
      "Jhin":     [ {...} ]
    },
    "_schema_version": 1
  }

API:
  list_for(champion)              -> list of stored builds (raw shape)
  add(champion, build)            -> str (new id)
  update(champion, id, patch)     -> bool (False if id not found)
  delete(champion, id)            -> bool
  format_for_display(build, ...)  -> dict in engine-profile shape, kind="user"
"""
from __future__ import annotations

import copy
import json
import logging
import os
import secrets
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional

_log = logging.getLogger("rc.sr_user_builds")

_PROJECT_ROOT  = Path(__file__).resolve().parent.parent
_STORE_PATH    = _PROJECT_ROOT / "data" / "daemon_slayer" / "user_builds.json"
_SCHEMA_VERSION = 1

# Module-level cache + lock. ThreadingHTTPServer serves multiple GETs
# concurrently; the write path serializes via _STORE_LOCK.
_STORE_LOCK = Lock()
_CACHE: Optional[dict[str, Any]] = None
_CACHE_MTIME: Optional[int] = None


# -- Public API -------------------------------------------------------


def list_for(champion: str) -> list[dict[str, Any]]:
    """Return all user-curated builds for `champion`. Empty list if none."""
    if not champion:
        return []
    store = _load()
    builds = (store.get("champions") or {}).get(champion) or []
    # Deep defensive copy so callers can't mutate the cache - a shallow
    # dict() still aliases the nested runes dict + items list.
    return [copy.deepcopy(b) for b in builds if isinstance(b, dict)]


def add(champion: str, build: dict[str, Any]) -> str:
    """Append a new build under `champion`. Returns the generated id.

    `build` must be a dict; missing fields fall back to safe defaults.
    Raises ValueError when `champion` is empty or `build.label` missing.
    """
    if not champion:
        raise ValueError("champion required")
    if not isinstance(build, dict):
        raise ValueError("build must be a dict")
    label = (build.get("label") or "").strip()
    if not label:
        raise ValueError("build.label required")

    new_id = _gen_id()
    now = int(time.time())
    record = _normalize_record(build, build_id=new_id, now=now, created=True)

    with _STORE_LOCK:
        store = _load()
        champs = store.setdefault("champions", {})
        existing = champs.setdefault(champion, [])
        existing.append(record)
        _save(store)
    return new_id


def update(champion: str, build_id: str, patch: dict[str, Any]) -> bool:
    """Merge `patch` fields into the build with `build_id`. Returns
    True if the build existed and was updated. The id, created_at,
    and mode fields are immutable; updated_at is bumped automatically."""
    if not champion or not build_id or not isinstance(patch, dict):
        return False
    now = int(time.time())
    with _STORE_LOCK:
        store = _load()
        builds = (store.get("champions") or {}).get(champion) or []
        for i, b in enumerate(builds):
            if isinstance(b, dict) and b.get("id") == build_id:
                merged = {**b, **patch}
                merged["id"] = build_id  # immutable
                merged["created_at"] = b.get("created_at") or now
                merged["mode"] = "sr"
                merged["updated_at"] = now
                builds[i] = _normalize_record(merged, build_id=build_id, now=now, created=False)
                _save(store)
                return True
    return False


def delete(champion: str, build_id: str) -> bool:
    """Remove the build by id. Returns True if it existed."""
    if not champion or not build_id:
        return False
    with _STORE_LOCK:
        store = _load()
        builds = (store.get("champions") or {}).get(champion) or []
        for i, b in enumerate(builds):
            if isinstance(b, dict) and b.get("id") == build_id:
                builds.pop(i)
                # Drop the champion entry entirely if it's now empty so the
                # JSON file stays tidy.
                if not builds:
                    store["champions"].pop(champion, None)
                _save(store)
                return True
    return False


def format_for_display(
    build: dict[str, Any],
    *,
    skeleton_split: Optional[dict[str, list[int]]] = None,
) -> Optional[dict[str, Any]]:
    """Convert a stored build -> the same shape as engine-generated profiles
    (kind="user"). Returns None on a malformed record so the caller can
    skip without crashing the chooser.

    Resolves item display names to ddragon IDs via the existing
    loadout_resolver helper; missing items just don't appear in `item_ids`."""
    if not isinstance(build, dict):
        return None
    label = build.get("label")
    items: list[str] = list(build.get("items") or [])
    if not label or not items:
        return None
    runes = build.get("runes") or {}
    keystone = runes.get("keystone") or ""
    spells = build.get("summoner_spells") or [4, 14]
    try:
        spells_pair = [int(spells[0]), int(spells[1])]
    except (ValueError, IndexError, TypeError):
        spells_pair = [4, 14]

    # Lazy import to avoid circular dependency (loadout_resolver imports
    # lcu_rune_writer, which has heavy module-load side effects).
    try:
        from coaches.loadout_resolver import _resolve_item_ids
        item_ids = _resolve_item_ids(items)
    except Exception as exc:
        _log.debug("user-build item-id resolve failed: %s", exc)
        item_ids = []

    skel = _split_skeleton(items, item_ids, skeleton_split)

    return {
        "kind":            "user",
        "key":             build.get("id") or "",
        "label":           label,
        "description":     build.get("notes") or "",
        "champion":        build.get("_champion") or "",
        "keystone":        keystone,
        "runes": {
            "keystone":  keystone,
            "primary":   runes.get("primary") or "",
            "secondary": runes.get("secondary") or "",
            "minor_primary":   list(runes.get("minor_primary") or []),
            "minor_secondary": list(runes.get("minor_secondary") or []),
        },
        "summoner_spells": spells_pair,
        "item_skeleton":   skel,
        "build_path":      list(items),
        "item_ids":        item_ids,
        "engine":          None,
        "user": {
            "id":         build.get("id") or "",
            "role":       build.get("role"),
            "created_at": build.get("created_at"),
            "updated_at": build.get("updated_at"),
            "notes":      build.get("notes") or "",
        },
    }


def clear_cache() -> None:
    """Test hook: drop the in-process cache so the next read re-loads from disk."""
    global _CACHE, _CACHE_MTIME
    with _STORE_LOCK:
        _CACHE = None
        _CACHE_MTIME = None


# -- Internals --------------------------------------------------------


def _gen_id() -> str:
    """8-char hex token - short enough for URLs, big enough to avoid
    collisions in practice (~16M unique). Operator never sees these."""
    return secrets.token_hex(4)


def _normalize_record(
    build: dict[str, Any],
    *,
    build_id: str,
    now: int,
    created: bool,
) -> dict[str, Any]:
    """Coerce a build to the canonical schema. Trusts caller for label."""
    runes_in = build.get("runes") or {}
    spells_in = build.get("summoner_spells") or [4, 14]
    try:
        d_spell, f_spell = int(spells_in[0]), int(spells_in[1])
    except (ValueError, IndexError, TypeError):
        d_spell, f_spell = 4, 14
    items_in = build.get("items") or []
    items = [str(x) for x in items_in if x]
    role = build.get("role")
    if isinstance(role, str):
        role = role.strip().upper() or None
    else:
        role = None
    notes = build.get("notes")
    notes = str(notes).strip() if isinstance(notes, str) else ""
    minor_primary_in   = runes_in.get("minor_primary")   or []
    minor_secondary_in = runes_in.get("minor_secondary") or []
    minor_primary   = [str(x).strip() for x in minor_primary_in   if isinstance(x, str) and x.strip()]
    minor_secondary = [str(x).strip() for x in minor_secondary_in if isinstance(x, str) and x.strip()]
    return {
        "id":              build_id,
        "label":           str(build.get("label") or "").strip(),
        "mode":            "sr",
        "role":            role,
        "runes": {
            "keystone":        str(runes_in.get("keystone")  or ""),
            "primary":         str(runes_in.get("primary")   or ""),
            "secondary":       str(runes_in.get("secondary") or ""),
            "minor_primary":   minor_primary,
            "minor_secondary": minor_secondary,
        },
        "summoner_spells": [d_spell, f_spell],
        "items":           items,
        "notes":           notes,
        "created_at":      int(build.get("created_at") or now) if not created else now,
        "updated_at":      now,
    }


def _split_skeleton(
    names: list[str],
    ids: list[str],
    cuts: Optional[dict[str, list[int]]],
) -> dict[str, list[dict[str, str]]]:
    """Mirrors sr_draft_profile._split_skeleton. Duplicated rather than
    imported to keep this module independent (tests + circular-import safety)."""
    cuts = cuts or {"start": [0, 2], "core": [2, 4], "final": [4, 6]}
    out: dict[str, list[dict[str, str]]] = {}
    for slot in ("start", "core", "final"):
        rng = cuts.get(slot) or [0, 0]
        try:
            lo, hi = int(rng[0]), int(rng[1])
        except (ValueError, IndexError, TypeError):
            lo, hi = 0, 0
        slice_names = names[lo:hi]
        slice_ids   = ids[lo:hi]
        out[slot] = [
            {"name": n, "id": (slice_ids[i] if i < len(slice_ids) else "")}
            for i, n in enumerate(slice_names)
        ]
    return out


def _load() -> dict[str, Any]:
    """mtime-aware loader. Holds the lock briefly to swap the cache."""
    global _CACHE, _CACHE_MTIME
    if not _STORE_PATH.exists():
        return {"champions": {}, "_schema_version": _SCHEMA_VERSION}
    try:
        mt = _STORE_PATH.stat().st_mtime_ns
    except OSError:
        mt = None
    if _CACHE is not None and _CACHE_MTIME == mt:
        return _CACHE
    try:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("user_builds.json top-level must be an object")
        raw.setdefault("champions", {})
        raw.setdefault("_schema_version", _SCHEMA_VERSION)
    except Exception as exc:
        _log.warning("user_builds load failed: %s", exc)
        raw = {"champions": {}, "_schema_version": _SCHEMA_VERSION}
    _CACHE = raw
    _CACHE_MTIME = mt
    return raw


def _save(store: dict[str, Any]) -> None:
    """Atomic write: tmp.write_text -> tmp.replace. Bumps in-memory
    mtime cache to the post-replace mtime so the next _load() doesn't
    re-parse what we just wrote."""
    global _CACHE, _CACHE_MTIME
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    payload = json.dumps(store, indent=2, ensure_ascii=False)
    tmp.write_text(payload, encoding="utf-8")
    # core.atomic_write_json's WinError 5 retry pattern (memory:
    # reference_os_replace_winerror5). Brief retry covers the case
    # where a concurrent reader has the destination open.
    for delay_ms in (0, 25, 50, 200):
        if delay_ms:
            time.sleep(delay_ms / 1000.0)
        try:
            os.replace(tmp, _STORE_PATH)
            break
        except PermissionError as exc:
            if delay_ms == 200:
                _log.warning("user_builds save retry exhausted: %s", exc)
                raise
    _CACHE = store
    try:
        _CACHE_MTIME = _STORE_PATH.stat().st_mtime_ns
    except OSError:
        _CACHE_MTIME = None
