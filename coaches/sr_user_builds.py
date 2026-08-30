"""User-curated additive build store for Phase 8 SR Draft Theatre.

Operator-additive invariant: builds saved here APPEND to the 3
engine-generated profiles in the SR-draft chooser. They are NEVER
overwritten or auto-edited by the engine, and the engine generator
in `sr_draft_profile.py` does not read or write this store. Merging
happens at the route layer.

Storage: `data/daemon_slayer/user_builds.json`. Single JSON file,
mtime-cached so hand-edits land without RC restart, atomic-written via a
PER-WRITER scratch file (`<name>.<pid>.<token>.tmp`) and `os.replace` with
the Windows WinError 5 backoff. Three properties are load-bearing and each
was absent before the 2026-08-30 audit (lane 8 cycle 22):

  - the scratch name is unique per writer, so two writers cannot truncate
    each other's tmp and publish a torn document;
  - the tmp is unlinked on EVERY failure path, so an exhausted retry does
    not orphan it;
  - the in-memory cache is published ONLY after the replace lands, and the
    mutators work on a private deep copy, so a failed write can never leave
    a build visible that was never saved.

An unparseable store is QUARANTINED (renamed to
`user_builds.corrupt-<stamp>.json`), never overwritten - reads degrade to
empty so the panel still renders, but the operator's bytes survive.

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

`add` raises `BuildValidationError` (a ValueError) for every caller-facing
rejection. Its `public_message` is RC-authored and safe to return verbatim;
any OTHER exception must be scrubbed before it reaches an HTTP body.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import secrets
import time
from pathlib import Path
from threading import RLock
from typing import Any, Optional

_log = logging.getLogger("rc.sr_user_builds")

_PROJECT_ROOT  = Path(__file__).resolve().parent.parent
_STORE_PATH    = _PROJECT_ROOT / "data" / "daemon_slayer" / "user_builds.json"
_SCHEMA_VERSION = 1

# AUDIT 2026-08-30 (lane 8 cycle 22, W5): this store sits behind an
# UNAUTHENTICATED CRUD route (dashboard/routes_sr_user_builds.py, spliced into
# :8888 by dashboard/_dispatch.py:168 + :208). Nothing bounded the champion
# key, the label, the notes, the item list or the number of builds, so any
# caller on the interface the dashboard binds could grow user_builds.json
# without limit - and the whole file is re-serialized on every single write.
# Caps are generous enough that no honest operator ever meets one.
MAX_CHAMPION_LEN = 64
MAX_LABEL_LEN = 120
MAX_NOTES_LEN = 2000
MAX_ITEMS = 32
MAX_ITEM_NAME_LEN = 64
MAX_BUILDS_PER_CHAMPION = 100
MAX_CHAMPIONS = 500
MAX_MINOR_RUNES = 8
MAX_RUNE_NAME_LEN = 64


class BuildValidationError(ValueError):
    """A caller-facing rejection whose message is safe to return verbatim.

    AUDIT 2026-08-30 (lane 8 cycle 22, W4): the route used to answer 400 with
    ``json.dumps({"error": str(exc)})``, the exact un-scrubbed shape
    ``dashboard/_errors.py`` was written to end. Blanket-scrubbing every 400
    would have been worse for the caller though - "internal error" does not
    tell anyone WHICH field was wrong. So validation failures carry an
    explicitly RC-authored ``public_message``; anything else the store raises
    is treated as untrusted and scrubbed.

    Subclasses ValueError so existing ``except ValueError`` callers and tests
    keep working unchanged.
    """

    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


# Module-level cache + lock. ThreadingHTTPServer serves multiple GETs
# concurrently; the write path serializes via _STORE_LOCK.
#
# AUDIT 2026-08-30 (lane 8 cycle 22, W2): this was a plain Lock and readers
# did not take it at all. It is an RLock now because the read path legitimately
# nests (list_for -> _load), and a non-reentrant lock would deadlock there.
_STORE_LOCK = RLock()
_CACHE: Optional[dict[str, Any]] = None
_CACHE_MTIME: Optional[int] = None


# -- Public API -------------------------------------------------------


def list_for(champion: str) -> list[dict[str, Any]]:
    """Return all user-curated builds for `champion`. Empty list if none.

    AUDIT 2026-08-30 (lane 8 cycle 22, W2): this read the shared cache with no
    lock while add/update/delete mutated that exact list in place, so a
    concurrent GET could iterate a list another thread was popping from. The
    lock is held across the read AND the copy, so every snapshot corresponds to
    one committed state of the store.
    """
    if not champion:
        return []
    with _STORE_LOCK:
        store = _read_cached_locked()
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
        raise BuildValidationError("champion required")
    if len(champion) > MAX_CHAMPION_LEN:
        raise BuildValidationError(
            f"champion name too long (max {MAX_CHAMPION_LEN})")
    if not isinstance(build, dict):
        raise BuildValidationError("build must be a dict")
    label = (build.get("label") or "").strip()
    if not label:
        raise BuildValidationError("build.label required")

    now = int(time.time())

    with _STORE_LOCK:
        # W2/W7: mutate a PRIVATE copy. The pre-fix code appended straight into
        # the shared cache and only then called _save, so a failed write left a
        # phantom build that every reader could see - and that
        # coaches/rune_pages.py:142 would fold into a live rune page.
        store = _load()
        champs = store.setdefault("champions", {})
        if champion not in champs and len(champs) >= MAX_CHAMPIONS:
            raise BuildValidationError(
                f"too many champions stored (max {MAX_CHAMPIONS})")
        existing = champs.setdefault(champion, [])
        if len(existing) >= MAX_BUILDS_PER_CHAMPION:
            raise BuildValidationError(
                f"too many builds for {champion} (max {MAX_BUILDS_PER_CHAMPION})")
        new_id = _gen_unique_id(existing)
        existing.append(
            _normalize_record(build, build_id=new_id, now=now, created=True))
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
        # W7: private copy - a failed _save must not leave the edit in memory.
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
        # W7: private copy - a failed _save must not make a build that is
        # still on disk vanish from the in-memory view.
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
    except Exception as exc:  # noqa: BLE001
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
    collisions in practice. Operator never sees these.

    AUDIT 2026-08-30 (lane 8 cycle 22, W8): this docstring read "~16M unique",
    which is the figure for a 3-byte token. `secrets.token_hex(4)` is 4 bytes,
    so the space is 16**8 (about 4.3e9) - the code was fine, the claim was
    wrong by 256x.
    """
    return secrets.token_hex(4)


def _gen_unique_id(existing: list[Any]) -> str:
    """A fresh id that no build in `existing` already uses.

    AUDIT 2026-08-30 (lane 8 cycle 22, W9): `add` never checked. A collision is
    unlikely, but `update`/`delete` both act on the FIRST match, so a duplicate
    id silently edits or removes the wrong build - and nothing would have
    reported it.
    """
    taken = {b.get("id") for b in existing if isinstance(b, dict)}
    for _ in range(16):
        candidate = _gen_id()
        if candidate not in taken:
            return candidate
    raise RuntimeError("could not generate a unique build id")


def _normalize_record(
    build: dict[str, Any],
    *,
    build_id: str,
    now: int,
    created: bool,
) -> dict[str, Any]:
    """Coerce a build to the canonical schema. Trusts caller for label."""
    runes_in = build.get("runes") or {}
    if not isinstance(runes_in, dict):
        runes_in = {}
    spells_in = build.get("summoner_spells") or [4, 14]
    try:
        d_spell, f_spell = int(spells_in[0]), int(spells_in[1])
    except (ValueError, IndexError, TypeError):
        d_spell, f_spell = 4, 14
    items_in = build.get("items") or []
    if not isinstance(items_in, (list, tuple)):
        items_in = []
    # W5: bound every free-form field. Truncation rather than rejection for the
    # cosmetic ones - an over-long label is a client bug, not a reason to lose
    # the operator's build.
    items = [str(x)[:MAX_ITEM_NAME_LEN] for x in items_in if x][:MAX_ITEMS]
    role = build.get("role")
    if isinstance(role, str):
        role = role.strip().upper() or None
    else:
        role = None
    notes = build.get("notes")
    notes = str(notes).strip()[:MAX_NOTES_LEN] if isinstance(notes, str) else ""
    minor_primary_in   = runes_in.get("minor_primary")   or []
    minor_secondary_in = runes_in.get("minor_secondary") or []
    if not isinstance(minor_primary_in, (list, tuple)):
        minor_primary_in = []
    if not isinstance(minor_secondary_in, (list, tuple)):
        minor_secondary_in = []
    minor_primary   = [str(x).strip()[:MAX_RUNE_NAME_LEN] for x in minor_primary_in   if isinstance(x, str) and x.strip()][:MAX_MINOR_RUNES]
    minor_secondary = [str(x).strip()[:MAX_RUNE_NAME_LEN] for x in minor_secondary_in if isinstance(x, str) and x.strip()][:MAX_MINOR_RUNES]
    return {
        "id":              build_id,
        "label":           str(build.get("label") or "").strip()[:MAX_LABEL_LEN],
        "mode":            "sr",
        "role":            role,
        "runes": {
            "keystone":        str(runes_in.get("keystone")  or "")[:MAX_RUNE_NAME_LEN],
            "primary":         str(runes_in.get("primary")   or "")[:MAX_RUNE_NAME_LEN],
            "secondary":       str(runes_in.get("secondary") or "")[:MAX_RUNE_NAME_LEN],
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


def _empty_store() -> dict[str, Any]:
    return {"champions": {}, "_schema_version": _SCHEMA_VERSION}


def _quarantine_corrupt_store(cause: Exception) -> None:
    """Move an unparseable store aside instead of letting it be overwritten.

    AUDIT 2026-08-30 (lane 8 cycle 22, W1) - the measured chain this ends:
    `_load` swallowed the parse error, returned an EMPTY store, and the next
    `add()` wrote that empty store straight over the file. The operator's
    curated builds were destroyed permanently, and the only trace was a
    `log.warning`. Renaming rather than copying is deliberate: it preserves
    the original bytes exactly, and it makes the quarantine self-limiting,
    because the next `_load` then takes the does-not-exist branch instead of
    re-quarantining the same file on every read.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = _STORE_PATH.with_name(f"user_builds.corrupt-{stamp}.json")
    n = 0
    while target.exists() and n < 100:
        n += 1
        target = _STORE_PATH.with_name(
            f"user_builds.corrupt-{stamp}-{n}.json")
    try:
        os.replace(_STORE_PATH, target)
    except OSError as exc:
        # Could not move it aside - then it is NOT safe to overwrite either.
        _log.error("user_builds corrupt (%s) and quarantine failed: %s",
                   cause, exc)
        raise
    _log.error("user_builds.json was unparseable (%s); preserved as %s",
               cause, target.name)


def _read_cached_locked() -> dict[str, Any]:
    """Return the SHARED cache dict. Caller MUST hold _STORE_LOCK and must
    treat the result as read-only. Use `_load()` for anything that mutates."""
    global _CACHE, _CACHE_MTIME
    if not _STORE_PATH.exists():
        return _empty_store()
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
    except Exception as exc:  # noqa: BLE001
        # W1: preserve before degrading. Reads stay fail-soft (an empty store
        # keeps the panel rendering - feedback_no_reflow_on_data_absence) but
        # the bytes are no longer in the line of fire of the next write.
        _quarantine_corrupt_store(exc)
        raw = _empty_store()
        _CACHE, _CACHE_MTIME = None, None
        return raw
    _CACHE = raw
    _CACHE_MTIME = mt
    return raw


def _load() -> dict[str, Any]:
    """mtime-aware loader returning a PRIVATE deep copy of the store.

    AUDIT 2026-08-30 (lane 8 cycle 22, W2/W7): this used to hand back the
    shared `_CACHE` object and the shared per-champion lists. Mutators then
    edited the cache in place BEFORE the write was committed, so a failed
    `_save` left a phantom build visible to every reader (measured), and
    readers walked a list another thread was popping from. Callers now get a
    copy they own; `_save` is the only thing that publishes a new cache, and
    it does so only after the write has actually landed.
    """
    with _STORE_LOCK:
        return copy.deepcopy(_read_cached_locked())


def _save(store: dict[str, Any]) -> None:
    """Atomic write: tmp.write_text -> tmp.replace. Bumps in-memory
    mtime cache to the post-replace mtime so the next _load() doesn't
    re-parse what we just wrote."""
    global _CACHE, _CACHE_MTIME
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # W6: a per-writer scratch name. A single shared "<name>.json.tmp" is what
    # two concurrent writers would both open, the second truncating the first
    # mid-write - which defeats the atomicity the tmp+rename exists to give.
    tmp = _STORE_PATH.with_name(
        f"{_STORE_PATH.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    # Bytes, not write_text: Path.write_text rewrites LF as CRLF on Windows and
    # read_text hides it coming back (reference_windows_write_text_crlf_byte_count).
    payload = json.dumps(store, indent=2, ensure_ascii=False)
    try:
        tmp.write_bytes(payload.encode("utf-8"))
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
    except BaseException:
        # W6: the pre-fix code re-raised and orphaned the scratch file, so an
        # exhausted retry left a stale user_builds.json.tmp on disk forever.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    # Publish only after the write has actually landed.
    _CACHE = store
    try:
        _CACHE_MTIME = _STORE_PATH.stat().st_mtime_ns
    except OSError:
        _CACHE_MTIME = None
