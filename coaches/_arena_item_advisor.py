"""Arena per-round item advisor.

Replaces the static champ-select item_build (frozen `full_build` joined,
written once at champ-select via item_advisor) with a per-round
recommendation derived from:

  - the curated `full_build` for this champion in aram_champion_builds.json
  - already-owned items (substring dedup, same idiom as ARAM coach)
  - alive opponents' tank/healer counts → anti-tank + anti-heal pivots

No Haiku call — pure rule-based, runs every coach tick. Defaults
chosen for s33 (operator-confirmed): healer threshold 2+, finished
items only, 6-item cap, `is_next_opponent` punted to a later pass
so we operate on all alive opponents (good proxy for the next 1-3
rounds since arena pairings rotate).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

_APP_DIR = Path(__file__).parent.parent
_BUILDS_PATH = _APP_DIR / "data" / "meta_build" / "aram_champion_builds.json"
_DDRAGON_PATH = _APP_DIR / "data" / "meta" / "ddragon_champions.json"

# Champions with sustained mid-fight heal (not just lifesteal). Targeted
# at arena 2v2v2v2 — these meaningfully sustain a fight; pure-lifesteal
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

_builds_cache: dict | None = None
_tags_cache: dict[str, list[str]] | None = None


def _load_builds() -> dict:
    global _builds_cache
    if _builds_cache is None:
        try:
            _builds_cache = json.loads(_BUILDS_PATH.read_text(encoding="utf-8"))
        except Exception:
            _builds_cache = {}
    return _builds_cache


def _load_tags() -> dict[str, list[str]]:
    """Build a name→tags map from DDragon. Uses display name (with
    apostrophes) as key, matching the championName values arena state
    emits in `teams[*].name`."""
    global _tags_cache
    if _tags_cache is None:
        out: dict[str, list[str]] = {}
        try:
            doc = json.loads(_DDRAGON_PATH.read_text(encoding="utf-8"))
            for entry in (doc.get("data") or {}).values():
                name = entry.get("name")
                if name:
                    out[name] = list(entry.get("tags") or [])
        except Exception:
            pass
        _tags_cache = out
    return _tags_cache


def _is_tank(champ_name: str, tags_map: dict[str, list[str]]) -> bool:
    return "Tank" in (tags_map.get(champ_name) or [])


def _is_healer(champ_name: str) -> bool:
    return champ_name in _HEALERS


def _filter_owned(build: list[str], owned: Iterable[str]) -> list[str]:
    """Substring-both-ways dedup. Mirrors `_dedup_build_vs_owned` in
    aram_coach so the same "short form catches long form" rule applies
    (e.g. "Zhonya's" in build matches "Zhonya's Hourglass" in owned).
    """
    owned_lower = [o.lower() for o in (owned or []) if o]
    out = []
    for item in build:
        if not item:
            continue
        item_lower = item.lower()
        item_short = item.split()[0].lower()
        skip = False
        for o in owned_lower:
            o_short = o.split()[0]
            if (item_short and item_short in o) or (o_short and o_short in item_lower):
                skip = True
                break
        if not skip:
            out.append(item)
    return out


def _push_to_front(build: list[str], predicate, max_pos: int = 2) -> None:
    """If a matching item exists at position >= max_pos, move it to
    position 0. Mutates in place; first match wins."""
    for i, item in enumerate(build):
        if predicate(item) and i >= max_pos:
            build.insert(0, build.pop(i))
            return


def recompute_arena_build(
    champion: str,
    current_items: Iterable[str],
    gold: int,
    alive_opponents: Iterable[str],
    hp_pct: int,
) -> list[str]:
    """Per-round arena item recommendation.

    Returns a list of up to 6 item names ordered by relevance. Returns
    [] if the champion isn't in the build DB or all items are already
    owned (caller should leave existing item_build untouched in that
    case).
    """
    builds = _load_builds()
    entry = builds.get(champion) or {}
    full = list(entry.get("full_build") or [])
    if not full:
        return []

    remaining = _filter_owned(full, current_items)
    if not remaining:
        return []

    tags = _load_tags()
    opps = list(alive_opponents or [])
    tank_count = sum(1 for c in opps if _is_tank(c, tags))
    healer_count = sum(1 for c in opps if _is_healer(c))

    # Anti-tank: 2+ tanks → push first matching anti-tank item to front
    # (if not already in top 2). Skipped silently if no match.
    if tank_count >= 2:
        _push_to_front(
            remaining,
            lambda i: any(s in i for s in _ANTI_TANK),
            max_pos=2,
        )

    # Anti-heal: 2+ heavy-heal opponents → push antiheal item to front.
    if healer_count >= 2:
        _push_to_front(
            remaining,
            lambda i: any(s in i for s in _ANTI_HEAL),
            max_pos=2,
        )

    return remaining[:6]
