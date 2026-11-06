"""Arena per-round item advisor.

Replaces the static champ-select item_build (frozen `full_build` joined,
written once at champ-select via item_advisor) with a per-round
recommendation derived from:

  - the curated `full_build` for this champion in aram_champion_builds.json
  - already-owned items (whole-word prefix dedup, see `_filter_owned`)
  - alive opponents' tank/healer counts -> anti-tank + anti-heal pivots

No Haiku call - pure rule-based, runs every coach tick. Defaults
chosen for s33 (operator-confirmed): healer threshold 2+, finished
items only, 6-item cap, `is_next_opponent` punted to a later pass
so we operate on all alive opponents (good proxy for the next 1-3
rounds since arena pairings rotate).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Mapping

_APP_DIR = Path(__file__).parent.parent
# Arena-specific builds (patch 26.9, Arena Season 2). Schema differs
# from ARAM/SR: uses ideal_core_priority + prismatic_priority instead
# of full_build because arena anvil RNG dictates acquisition.
_ARENA_BUILDS_PATH = _APP_DIR / "data" / "meta_build" / "arena_champion_builds.json"
# ARAM as fallback for champions missing from arena_champion_builds
# (we only have 63 arena entries; 100+ champions still rely on ARAM data
# as a stand-in until Phase 3 covers the tail).
_ARAM_BUILDS_PATH = _APP_DIR / "data" / "meta_build" / "aram_champion_builds.json"
_DDRAGON_PATH = _APP_DIR / "data" / "meta" / "ddragon_champions.json"

# Champions with sustained mid-fight heal (not just lifesteal). Targeted
# at arena 2v2v2v2 - these meaningfully sustain a fight; pure-lifesteal
# ADCs are excluded (their healing is already gated on damage they're
# dealing, which antiheal already counters via the standard anti-ADC kit).
_HEALERS = frozenset({
    "Aatrox", "Vladimir", "Dr. Mundo", "Warwick", "Volibear", "Olaf",
    "Soraka", "Yuumi", "Sona", "Nami", "Senna", "Briar", "Renekton",
    "Sett", "Yone", "Sylas", "Swain", "Camille", "Trundle", "Maokai",
})

# Substring matches in item names that mark them as anti-tank.
_ANTI_TANK = (
    "Lord Dominik", "Mortal Reminder", "Black Cleaver", "Liandry",
    "Demonic", "Void Staff", "Terminus", "Kraken",
)

# Substring matches that mark items as anti-heal (Grievous Wounds source).
_ANTI_HEAL = (
    "Mortal Reminder", "Executioner", "Chempunk", "Morellonomicon",
    "Oblivion Orb", "Bramble", "Thornmail",
)

# v2 substitution table - when a champion's full_build LACKS any
# anti-heal item but contains the LHS, swap to the RHS to get
# Grievous Wounds without losing the slot's role. Only items where
# the swap is universally favorable (same damage type, similar power
# curve) are listed here. Missing entries = no substitution attempted.
_HEAL_SUBSTITUTIONS = {
    # AD anti-armor -> AD anti-armor + antiheal. Free upgrade for any
    # champ whose build calls for LDR but is heading into a
    # heal-dominant lobby (Caitlyn et al).
    "Lord Dominik's Regards": "Mortal Reminder",
}

_arena_builds_cache: dict | None = None
_aram_builds_cache: dict | None = None
_tags_cache: dict[str, list[str]] | None = None

_log = logging.getLogger(__name__)

# Paths whose load failure has already been logged in this process. A failed
# load is deliberately NOT cached (the `is None` sentinels above would accept
# a cached {} as success and the advisor would run degraded for the process
# lifetime), so without this guard a persistently missing file would warn on
# every coach tick. Same shape as item_advisor._warn_load_once.
_WARNED_LOAD_PATHS: set = set()


def _warn_load_once(path, exc) -> None:
    key = str(path)
    if key in _WARNED_LOAD_PATHS:
        return
    _WARNED_LOAD_PATHS.add(key)
    _log.warning(
        "arena_item_advisor: could not load %s (%s: %s) - running degraded, "
        "will retry on next call", path, type(exc).__name__, exc,
    )


def _read_json_object(path: Path) -> dict | None:
    """Read a JSON object from `path`. Returns None (logged once, NOT cached
    by the caller) on a read / decode / parse error or a non-object
    document. Anything else is a bug and raises."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise TypeError(f"expected a JSON object, got {type(doc).__name__}")
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        # OSError: missing / locked file. ValueError: UnicodeDecodeError and
        # JSONDecodeError. RecursionError: a pathologically nested document.
        _warn_load_once(path, exc)
        return None
    return doc


def _load_arena_builds() -> dict:
    global _arena_builds_cache
    if _arena_builds_cache is None:
        doc = _read_json_object(_ARENA_BUILDS_PATH)
        if doc is None:
            return {}
        _arena_builds_cache = doc
    return _arena_builds_cache


def _load_aram_builds() -> dict:
    global _aram_builds_cache
    if _aram_builds_cache is None:
        doc = _read_json_object(_ARAM_BUILDS_PATH)
        if doc is None:
            return {}
        _aram_builds_cache = doc
    return _aram_builds_cache


def _clean_name(value) -> str:
    """A usable name: a str, stripped. Anything else (None, a number, a
    dict, a list) or a blank string is ''."""
    return value.strip() if isinstance(value, str) else ""


def _name_list(value) -> list[str]:
    """Caller-supplied names (owned items, opponents) as clean strings.

    A bare str is ONE name - iterating it would yield letters. A mapping,
    bytes or a non-iterable is no names. Non-str / blank members are
    dropped. Never raises."""
    if value is None:
        return []
    if isinstance(value, str):
        value = (value,)
    elif isinstance(value, (bytes, bytearray, Mapping)):
        return []
    try:
        members = list(value)
    except TypeError:
        return []
    return [n for n in (_clean_name(v) for v in members) if n]


def _words(name: str) -> tuple[str, ...]:
    """Case-folded whole words of an item name, edge punctuation stripped
    ("Jak'Sho, The Protean" -> ("jak'sho", "the", "protean"))."""
    return tuple(
        w for w in (t.strip(",.;:()[]") for t in name.casefold().split()) if w
    )


# Shortest letters-only form that may name a longer one by character prefix.
# Measured 2026-11-06 over the 862 distinct item names in the two build files
# plus ddragon_items.json: at 6 the character rule adds exactly the same-item
# spellings the word rule misses ("Storm Surge" / "Stormsurge", "Navori
# Flickerblade" / "...blades", "Lich Bane" / "Lichbane") and no other pair.
# It also pairs "Goredrink" with "Goredrinker", which the data treats as a
# stand-in ("Goredrinker (or Goredrink-augment proxy)"); the old first-word
# rule paired them one way (build "Goredrink", owned "Goredrinker") and this
# rule pairs both ways - a stand-in, not one item.
_MIN_COMPACT_PREFIX = 6


# Renamed items: the build files still carry the old name while the Live
# Client reports the new one (keys and values are `_words` joined by one
# space). The old first-word rule caught these by accident of the shared
# possessive; the whole-word rule needs them named.
_ITEM_ALIASES = {
    "liandry's anguish": "liandry's torment",
    "luden's echo": "luden's companion",
    "luden's tempest": "luden's companion",
}


def _item_key(name: str) -> tuple[tuple[str, ...], str]:
    """(whole words, letters-and-digits-only form) of an item name, with a
    renamed item mapped onto its current name."""
    words = _words(name)
    alias = _ITEM_ALIASES.get(" ".join(words))
    if alias is not None:
        words = tuple(alias.split())
    return words, "".join(ch for ch in "".join(words) if ch.isalnum())


def _same_item(a: tuple[tuple[str, ...], str],
               b: tuple[tuple[str, ...], str]) -> bool:
    """True when two `_item_key`s name the same item: one word tuple is a
    leading prefix of the other (the short form names the long form,
    "Zhonya's" / "Zhonya's Hourglass"), or one compact form of at least
    `_MIN_COMPACT_PREFIX` characters starts the other (a spelling variant,
    "Storm Surge" / "Stormsurge")."""
    (wa, ca), (wb, cb) = a, b
    if not wa or not wb:
        return False
    n = min(len(wa), len(wb))
    if wa[:n] == wb[:n]:
        return True
    short, long_ = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    return len(short) >= _MIN_COMPACT_PREFIX and long_.startswith(short)


def _build_list(raw) -> list[str]:
    """A curated build path from the data file as clean, de-duplicated names.

    Only a list / tuple is a path (a str would iterate by letter). Junk
    members are dropped. An entry naming the same item as an earlier one
    (`_same_item`: any case, a spelling variant, a parenthetical note) is
    dropped - five live arena entries carry an exact repeat (RM-1948).
    NOT caught: one name the data split into two entries at its comma
    ("Jak'Sho" + "The Protean"); neither fragment names the other, so that
    is fixed in the data file, not here."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: list[tuple[tuple[str, ...], str]] = []
    for value in raw:
        name = _clean_name(value)
        key = _item_key(name)
        if not key[0] or any(_same_item(key, s) for s in seen):
            continue
        seen.append(key)
        out.append(name)
    return out


def _lookup(db, champion: str) -> dict | None:
    """The champion's entry in a builds document, or None.

    Exact key first, then a case-insensitive match over real champion keys
    (never the `_note` / `_provenance` style metadata keys). A non-dict
    entry is treated as absent."""
    if not isinstance(db, dict):
        return None
    entry = db.get(champion)
    if entry is None:
        folded = champion.casefold()
        for key, value in db.items():
            if (isinstance(key, str) and not key.startswith("_")
                    and key.casefold() == folded):
                entry = value
                break
    return entry if isinstance(entry, dict) else None


def _resolve_build_path(champion: str) -> tuple[list[str], str]:
    """Find the canonical item path for a champion. Prefers
    arena_champion_builds.json (s33 refresh - uses ideal_core_priority).
    Falls back to aram_champion_builds.json (full_build) for champs
    not yet in the arena dataset, or whose arena entry is unusable.

    Returns (item_list, source_label) where source_label is "arena"
    or "aram-fallback" or "" if no data found. The list is a fresh copy.
    """
    champ = _clean_name(champion)
    if not champ or champ.startswith("_"):
        return [], ""
    arena_entry = _lookup(_load_arena_builds(), champ)
    if arena_entry is not None:
        icp = _build_list(arena_entry.get("ideal_core_priority"))
        if icp:
            return icp, "arena"
    aram_entry = _lookup(_load_aram_builds(), champ)
    if aram_entry is not None:
        full = _build_list(aram_entry.get("full_build"))
        if full:
            return full, "aram-fallback"
    return [], ""


def _load_tags() -> dict[str, list[str]]:
    """Build a name->tags map from DDragon. Uses display name (with
    apostrophes) as key, matching the championName values arena state
    emits in `teams[*].name`.

    A malformed entry is skipped on its own; a `data` block that is not an
    object, or that yields no usable entry at all, is a failed load
    (logged once, not cached, retried on the next call)."""
    global _tags_cache
    if _tags_cache is None:
        doc = _read_json_object(_DDRAGON_PATH)
        if doc is None:
            return {}
        data = doc.get("data")
        if not isinstance(data, dict):
            _warn_load_once(_DDRAGON_PATH, TypeError(
                f"expected a `data` object, got {type(data).__name__}"))
            return {}
        out: dict[str, list[str]] = {}
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            name = _clean_name(entry.get("name"))
            if not name:
                continue
            raw = entry.get("tags")
            if isinstance(raw, str):
                raw = [raw]
            out[name] = (
                [t for t in raw if isinstance(t, str)]
                if isinstance(raw, (list, tuple)) else []
            )
        if not out:
            _warn_load_once(_DDRAGON_PATH, ValueError("no usable champion entry"))
            return {}
        _tags_cache = out
    return _tags_cache


def _is_tank(champ_name: str, tags_map: dict[str, list[str]]) -> bool:
    return "Tank" in (tags_map.get(champ_name) or [])


def _is_healer(champ_name: str) -> bool:
    return champ_name in _HEALERS


def _filter_owned(build: list[str], owned: Iterable[str]) -> list[str]:
    """Drop build items the player already owns.

    Two names are the same item per `_same_item`: compared as case-folded
    whole words one is a leading prefix of the other, so a short form still
    catches its long form ("Zhonya's" / "Zhonya's Hourglass",
    "Kinkou Jitte (...)" / "Kinkou Jitte"), or a spelling variant matches
    by letters ("Storm Surge" / owned "Stormsurge"). The older first-word substring
    rule matched across items: owning Guinsoo's Rageblade hid Blade of The
    Ruined King ("blade" in "rageblade"), owning BotRK hid The Collector
    ("the"), owning Blackfire Torch hid Black Cleaver (RM-1947; the
    BotRK -> Rageblade direction was BUG #2 of the ARAM drain).
    """
    owned_keys = [k for k in (_item_key(o) for o in _name_list(owned)) if k[0]]
    out = []
    for item in _name_list(build):
        key = _item_key(item)
        if not key[0]:
            continue
        if any(_same_item(key, o) or _names_owned_variant(key, o)
               for o in owned_keys):
            continue
        out.append(item)
    return out


def _names_owned_variant(build_key, owned_key) -> bool:
    """True when the shorter name's words (2 or more) END the longer one: a
    champion-specific variant ("Talisman of Ascension" / "Veigar's Talisman
    of Ascension"), an in-progress quest ("Wooglet's Witchcap" / owned
    "Quest: Wooglet's Witchcap"), or the tail fragment of a name the arena
    data split at its comma ("The Protean" / "Jak'Sho, The Protean"; the
    head fragment "Jak'Sho" is a plain word prefix). Either side may be the
    longer one."""
    short, long_ = build_key[0], owned_key[0]
    if len(short) > len(long_):
        short, long_ = long_, short
    return 2 <= len(short) < len(long_) and long_[-len(short):] == short


def _push_to_front(build: list[str], predicate, max_pos: int = 2) -> None:
    """If a matching item exists at position >= max_pos, move it to
    position 0. Mutates in place; first match wins."""
    for i, item in enumerate(build):
        if predicate(item) and i >= max_pos:
            build.insert(0, build.pop(i))
            return


def _has_match(build: list[str], predicate) -> bool:
    return any(predicate(i) for i in build)


def _substitute_in_build(build: list[str], sub_map: dict[str, str]) -> bool:
    """Replace the first item present in `sub_map` with its mapped value.
    Returns True on substitution. No-op if no item matches or the
    mapped value equals the original.
    """
    for i, item in enumerate(build):
        replacement = sub_map.get(item)
        if replacement and replacement != item:
            build[i] = replacement
            return True
    return False


def _is_anti_heal(item: str) -> bool:
    return any(s in item for s in _ANTI_HEAL)


def _is_anti_tank(item: str) -> bool:
    return any(s in item for s in _ANTI_TANK)


def recompute_arena_build(
    champion: str,
    current_items: Iterable[str],
    gold: int,
    alive_opponents: Iterable[str],
    hp_pct: int,
) -> list[str]:
    """Per-round arena item recommendation.

    Returns a fresh list of up to 6 distinct item names ordered by
    relevance. Returns [] if the champion isn't in the build DB, the
    champion is not a usable name, or all items are already owned (caller
    should leave existing item_build untouched in that case). Junk inputs
    (non-str members, a bare str where a list belongs) degrade, never
    raise. `gold` and `hp_pct` are accepted for the callers' shared call
    shape and do not change the result yet.
    """
    full, _source = _resolve_build_path(champion)
    if not full:
        return []

    owned = _name_list(current_items)
    remaining = _filter_owned(full, owned)
    if not remaining:
        return []

    tags = _load_tags()
    opps = _name_list(alive_opponents)
    tank_count = sum(1 for c in opps if _is_tank(c, tags))
    healer_count = sum(1 for c in opps if _is_healer(c))

    # Anti-tank: 2+ tanks -> push first matching anti-tank item to front
    # (if not already in top 2). Skipped silently if no match.
    if tank_count >= 2:
        _push_to_front(remaining, _is_anti_tank, max_pos=2)

    # Anti-heal: 2+ heavy-heal opponents -> push antiheal item to front.
    # If the build lacks any antiheal entirely (e.g. Caitlyn's curated
    # full_build has Lord Dominik's but no Mortal Reminder), try a
    # one-for-one substitution from _HEAL_SUBSTITUTIONS first so the
    # subsequent push-to-front has something to grab. Skipped when the
    # player already OWNS an anti-heal item: Grievous Wounds does not
    # stack, and the substitution would otherwise re-recommend the owned
    # Mortal Reminder (RM-1949).
    if healer_count >= 2 and not _has_match(owned, _is_anti_heal):
        if not _has_match(remaining, _is_anti_heal):
            _substitute_in_build(remaining, _HEAL_SUBSTITUTIONS)
        _push_to_front(remaining, _is_anti_heal, max_pos=2)

    return remaining[:6]
