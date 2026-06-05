# arch: cs archetype pick storage + DDragon-tag default resolver | section=core | frozen=no
"""Phase 3 (s176, 2026-05-12) - champ-select scorer-picker storage layer.

The Daemon Slayer engine ships six scorer archetypes per
``NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md``:

* ``carry``     - auto-attack DPS         (ds.dps, shipped)
* ``bruiser``   - combined DPS + EHP      (ds.hybrid, s175)
* ``tank``      - Effective HP            (ds.ehp, s174)
* ``mage``      - ability DPS             (ds.ability, Phase 4 future)
* ``assassin``  - single-combo burst      (ds.burst, Phase 5 future)
* ``enchanter`` - heal/shield throughput  (ds.hps, Phase 6 future)

Each champion has a *primary* archetype (the scorer the coach reads each
tick) and a *secondary* archetype (the alt-view in the CS panel, frozen
between item-complete events). The operator can override the primary via
the CS picker UI; the dispatcher (``core.daemon_slayer_client``) routes
to the right scorer.

This module owns three things:

1. **DDragon-tag → archetype mapping** so a hovered champion produces a
   sensible default before the operator touches anything. Lulu tags
   ``["Support", "Mage"]`` → primary=enchanter, secondary=mage. Yasuo
   tags ``["Fighter", "Assassin"]`` → primary=bruiser, secondary=assassin.

2. **Per-champion pick persistence** in
   ``data/cs_archetype_picks.json``. Server-side single source of truth;
   the dashboard's localStorage ``rc-cs-archetype-<champion>`` mirrors it
   for instant first-paint after a page reload.

3. **Resolve helper** ``get_archetype_for(champion)`` that returns the
   merged view: explicit pick if set, otherwise DDragon-tag default,
   with ``source`` field telling the caller which one fired.

Phase 3 deliberately ships only the data layer + REST endpoint + picker
UI. Coach integration (each coach reading
``state.cs_archetype_pick.primary`` and dispatching to the matching
scorer) lands in a follow-up session - same shape as the s174 ``Phase 1
deferrals`` pattern.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.archetype_picks")

# Canonical archetype names. Order matters: UI renders left→right in
# this order. Keep stable - localStorage + the persisted JSON file key
# off these strings.
ARCHETYPES: tuple[str, ...] = (
    "carry", "bruiser", "tank", "mage", "assassin", "enchanter",
)
ARCHETYPE_SET = frozenset(ARCHETYPES)

# Archetypes with a real scorer wired today. s209 flipped to all 6 after
# verifying Phases 4-6 shipped (s179 mage→ds.ability, s180 assassin→ds.burst,
# s181 enchanter→ds.hps per CLAUDE.md priorities 34-36). The dispatcher
# routes each archetype to its dedicated scorer; none fall back to ds.dps.
IMPLEMENTED_SCORERS: frozenset[str] = frozenset({
    "carry", "bruiser", "tank", "mage", "assassin", "enchanter",
})

# DDragon tag → archetype mapping. Lowercase comparison; unknown tags
# fall through to carry as the safest default (still gives operator
# something to look at).
_TAG_TO_ARCHETYPE: dict[str, str] = {
    "fighter":   "bruiser",
    "mage":      "mage",
    "assassin":  "assassin",
    "marksman":  "carry",
    "tank":      "tank",
    "support":   "enchanter",
}

# Source enum for tracking how a pick was set. Stable strings; UI may
# style differently per source.
SOURCE_DEFAULT     = "default"      # DDragon-tag derived
SOURCE_USER_CS     = "user_cs"      # operator picked in champ-select
SOURCE_USER_INGAME = "user_ingame"  # operator switched mid-match
SOURCE_NUDGE       = "nudge"        # accepted first-purchase-mismatch toast

VALID_SOURCES: frozenset[str] = frozenset({
    SOURCE_DEFAULT, SOURCE_USER_CS, SOURCE_USER_INGAME, SOURCE_NUDGE,
})

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PICKS_PATH = _DATA_DIR / "cs_archetype_picks.json"
_CHAMPS_PATH = _DATA_DIR / "meta" / "ddragon_champions.json"

# Per-process cache for the DDragon tag lookup. Loaded once; the file
# rotates per patch but `cs_archetype_picks.json` is patch-independent.
_TAGS_CACHE: dict[str, list[str]] | None = None
_KEY_NAME_CACHE: dict[str, str] | None = None
_ID_CACHE: dict[str, str] | None = None
_TAGS_LOCK = threading.Lock()

# Per-process cache for the persisted picks. Reloaded on every write
# (atomic replace invalidates other readers).
_PICKS_CACHE: dict[str, dict] | None = None
_PICKS_LOCK = threading.Lock()


def tag_to_archetype(tag: str) -> str:
    """Map a single DDragon tag to the canonical archetype name.

    Returns "carry" for unknown tags - safest fallback (auto-attack DPS
    is the most-tested scorer). Callers that want strict behavior should
    check ``tag.lower() in _TAG_TO_ARCHETYPE`` first.
    """
    return _TAG_TO_ARCHETYPE.get((tag or "").strip().lower(), "carry")


def _load_champion_tags() -> dict[str, list[str]]:
    """Build champion-id → tags map from ``ddragon_champions.json``.

    Keys are DDragon IDs (``"Aatrox"``, ``"MonkeyKing"``) plus display
    names (``"Wukong"``) plus stripped variants (``"Kai'Sa"`` → also
    ``"KaiSa"``). Mirror of ``core.defensive_picks._load_champ_info`` so
    callers passing a display name from coaching_data.json resolve cleanly.
    """
    global _TAGS_CACHE
    with _TAGS_LOCK:
        if _TAGS_CACHE is not None:
            return _TAGS_CACHE
        out: dict[str, list[str]] = {}
        try:
            raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
            data = raw.get("data", raw)
            for entry in data.values():
                if not isinstance(entry, dict):
                    continue
                tags = list(entry.get("tags") or [])
                for key in (entry.get("name"), entry.get("id")):
                    if not key:
                        continue
                    out[key] = tags
                    out[key.replace("'", "")] = tags
                    out[key.replace(" ", "")] = tags
                    out[key.replace("'", "").replace(" ", "")] = tags
        except FileNotFoundError:
            _log.warning("archetype_picks: %s missing - defaults will use carry", _CHAMPS_PATH)
        except Exception as exc:
            _log.warning("archetype_picks: tags load failed: %s", exc)
        _TAGS_CACHE = out
        return out


def champion_name_by_key(key) -> str:
    """Resolve a numeric DDragon champion key (51 / "51") to its display
    name ("Caitlyn"). Returns "" on no-pick (0 / None / "") or load
    failure. Used by the state-builder to turn the champ-select
    ``my_champion`` (a numeric championId) into a name for archetype
    lookup (item 244 - the SR/draft payload carries no local_pick name).
    """
    global _KEY_NAME_CACHE
    if key in (None, "", 0, "0"):
        return ""
    with _TAGS_LOCK:
        if _KEY_NAME_CACHE is None:
            m: dict[str, str] = {}
            try:
                raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
                data = raw.get("data", raw)
                for entry in data.values():
                    if not isinstance(entry, dict):
                        continue
                    k = entry.get("key")
                    nm = entry.get("name") or entry.get("id")
                    if k is not None and nm:
                        m[str(k)] = str(nm)
            except FileNotFoundError:
                _log.warning(
                    "archetype_picks: %s missing - champion_name_by_key empty",
                    _CHAMPS_PATH,
                )
            except Exception as exc:  # noqa: BLE001 - fail-soft resolver
                _log.warning("archetype_picks: key->name load failed: %s", exc)
            _KEY_NAME_CACHE = m
        return _KEY_NAME_CACHE.get(str(key), "")


def canonical_champion_id(name: str) -> str:
    """Resolve any champion name-form to its canonical DDragon id.

    Accepts a Live Client display name ("Tahm Kench", "Nunu & Willump",
    "Wukong"), a canonical DDragon id ("TahmKench", "MonkeyKing"), or an
    apostrophe / space stripped variant ("KaiSa"); returns the canonical
    DDragon id ("TahmKench", "MonkeyKing", "Kaisa"). Returns the input
    unchanged when unknown, so a canonical id passes through and an
    unresolved name fail-softs to a 0.0 downstream score. Built from
    ``ddragon_champions.json`` (same loader pattern as
    ``_load_champion_tags``), cached per process. Used by the live
    ally-amplification peel consumer (routes_peel_priority) to bridge
    Live Client display names to the DS engine's canonical-id registries.
    """
    if not name:
        return ""
    global _ID_CACHE
    with _TAGS_LOCK:
        if _ID_CACHE is None:
            m: dict[str, str] = {}
            try:
                raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
                data = raw.get("data", raw)
                for entry in data.values():
                    if not isinstance(entry, dict):
                        continue
                    cid = entry.get("id")
                    if not cid:
                        continue
                    for key in (entry.get("name"), entry.get("id")):
                        if not key:
                            continue
                        m[key] = cid
                        m[key.replace("'", "")] = cid
                        m[key.replace(" ", "")] = cid
                        m[key.replace("'", "").replace(" ", "")] = cid
            except FileNotFoundError:
                _log.warning(
                    "archetype_picks: %s missing - canonical_champion_id "
                    "passthrough", _CHAMPS_PATH,
                )
            except Exception as exc:  # noqa: BLE001 - fail-soft resolver
                _log.warning("archetype_picks: id map load failed: %s", exc)
            _ID_CACHE = m
        return _ID_CACHE.get(name, name)


def default_for_champion(champion: str) -> tuple[str, str]:
    """Return ``(primary, secondary)`` from DDragon tags.

    ``primary`` comes from ``tags[0]``; ``secondary`` from ``tags[1]``
    if present and distinct, else from the next-most-likely archetype
    by simple heuristic (Fighter → Tank, Mage → Assassin, etc.).
    Unknown champion → ``("carry", "bruiser")``.
    """
    if not champion:
        return ("carry", "bruiser")
    tags = _load_champion_tags().get(champion) or []
    if not tags:
        return ("carry", "bruiser")
    primary = tag_to_archetype(tags[0])
    secondary: str
    if len(tags) >= 2:
        secondary = tag_to_archetype(tags[1])
        if secondary == primary:
            secondary = _fallback_secondary(primary)
    else:
        secondary = _fallback_secondary(primary)
    return (primary, secondary)


def _fallback_secondary(primary: str) -> str:
    """When DDragon gives only one tag, pick a sensible alt-view.

    Heuristic mappings - not load-bearing; operator overrides via UI.
    """
    return {
        "carry":     "bruiser",
        "bruiser":   "tank",
        "tank":      "bruiser",
        "mage":      "assassin",
        "assassin":  "mage",
        "enchanter": "mage",
    }.get(primary, "bruiser")


def _load_picks() -> dict[str, dict]:
    """Load the persisted per-champion pick map. ``{}`` on missing/error."""
    global _PICKS_CACHE
    with _PICKS_LOCK:
        if _PICKS_CACHE is not None:
            return _PICKS_CACHE
        try:
            if _PICKS_PATH.exists():
                data = json.loads(_PICKS_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _PICKS_CACHE = data
                    return _PICKS_CACHE
                _log.warning(
                    "archetype_picks: %s not a dict (%s) - ignoring",
                    _PICKS_PATH, type(data).__name__,
                )
        except Exception as exc:
            _log.warning("archetype_picks: load failed: %s", exc)
        _PICKS_CACHE = {}
        return _PICKS_CACHE


def _invalidate_picks_cache() -> None:
    """Drop the cache so the next read re-pulls from disk. Used by tests."""
    global _PICKS_CACHE
    with _PICKS_LOCK:
        _PICKS_CACHE = None


def _atomic_write_picks(picks: dict[str, dict]) -> None:
    """Atomic replace mirroring ``routes_lobby_aux._save_top8``."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".cs_archetype_picks.", suffix=".tmp", dir=str(_DATA_DIR),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(picks, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, str(_PICKS_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_archetype_pick(
    champion: str,
    primary: str,
    secondary: Optional[str] = None,
    source: str = SOURCE_USER_CS,
) -> dict:
    """Persist an operator-chosen pick. Returns the stored entry.

    Raises ``ValueError`` on invalid archetype/source. Caller is expected
    to validate ``champion`` is non-empty before calling - we don't store
    blank-key entries.
    """
    if not champion or not champion.strip():
        raise ValueError("champion must be a non-empty string")
    if primary not in ARCHETYPE_SET:
        raise ValueError(
            f"primary must be one of {sorted(ARCHETYPE_SET)}, got {primary!r}"
        )
    if secondary is not None and secondary not in ARCHETYPE_SET:
        raise ValueError(
            f"secondary must be one of {sorted(ARCHETYPE_SET)} or None, got {secondary!r}"
        )
    if source not in VALID_SOURCES:
        raise ValueError(
            f"source must be one of {sorted(VALID_SOURCES)}, got {source!r}"
        )

    # Resolve secondary if not provided - keep the default semantics.
    if secondary is None:
        _, default_secondary = default_for_champion(champion)
        secondary = default_secondary if default_secondary != primary else _fallback_secondary(primary)

    entry = {
        "champion":  champion,
        "primary":   primary,
        "secondary": secondary,
        "source":    source,
        "set_at":    _now_iso(),
    }

    with _PICKS_LOCK:
        # Reload to merge with any out-of-process updates.
        picks = _read_picks_locked()
        picks[champion] = entry
        _atomic_write_picks(picks)
        global _PICKS_CACHE
        _PICKS_CACHE = picks
    return entry


def _read_picks_locked() -> dict[str, dict]:
    """Pull picks from disk while holding ``_PICKS_LOCK``. Helper for
    save_archetype_pick - we can't call ``_load_picks`` recursively
    because it acquires the same lock."""
    try:
        if _PICKS_PATH.exists():
            data = json.loads(_PICKS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        _log.warning("archetype_picks: re-read failed: %s", exc)
    return {}


def _now_iso() -> str:
    """UTC timestamp in ISO-8601, trimmed to seconds. Used in the
    ``set_at`` field so the dashboard can age out stale picks if needed."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_archetype_for(champion: str) -> dict:
    """Return the merged pick for ``champion``.

    Shape:
        {
            "champion":  "Aatrox",
            "primary":   "bruiser",
            "secondary": "tank",
            "source":    "default" | "user_cs" | "user_ingame" | "nudge",
            "set_at":    "2026-05-12T14:30:00Z"  # only when source != default
        }

    Blank ``champion`` returns the safe fallback (carry/bruiser, default).
    """
    if not champion:
        return {
            "champion":  "",
            "primary":   "carry",
            "secondary": "bruiser",
            "source":    SOURCE_DEFAULT,
        }
    picks = _load_picks()
    if champion in picks:
        entry = dict(picks[champion])
        entry.setdefault("champion", champion)
        entry.setdefault("source", SOURCE_DEFAULT)
        return entry
    primary, secondary = default_for_champion(champion)
    return {
        "champion":  champion,
        "primary":   primary,
        "secondary": secondary,
        "source":    SOURCE_DEFAULT,
    }


def list_archetype_picks() -> dict[str, dict]:
    """Return a copy of the full persisted map. Read-only - callers
    that mutate this won't affect the persisted file (we re-read on save)."""
    return dict(_load_picks())


def clear_archetype_pick(champion: str) -> bool:
    """Delete the persisted pick for ``champion`` so the next read falls
    back to the DDragon-tag default. Returns True if a pick was removed.
    Useful for the UI's "reset to default" button + tests."""
    if not champion:
        return False
    with _PICKS_LOCK:
        picks = _read_picks_locked()
        if champion not in picks:
            return False
        del picks[champion]
        _atomic_write_picks(picks)
        global _PICKS_CACHE
        _PICKS_CACHE = picks
    return True
