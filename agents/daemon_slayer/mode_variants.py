"""Canonical registry vs DDragon THROWBACK-MODE variant rows.

DDragon 16.15.1 shipped a parallel legacy-mode registry beside the live one:

* **Champions** - 60 ``Jade_<Champion>`` rows at ``base_key + 60000`` (measured
  60001..60117 against base keys 1..950). Not aliases: each carries its own stat
  line (Jade_Ahri hp 460/+80 against the live Ahri 590/+104 - an older patch's
  Ahri).
* **Items** - 162 rows in ``[770000, 780000)`` (measured 771001..773521), a
  keyspace that did not exist at 16.14.1 at all. Mirror rows sit at
  ``base_id + 770000``; the rest are RETIRED items with no live counterpart
  (Sightstone, Zz'Rot Portal, Hex Core mk-1, Sight Ward, Eggnog).

Both sets flag ``maps["453"]`` - the throwback mode - and most also flag
``maps["12"]`` (Howling Abyss). That second flag is the reason this partition is
not cosmetic: RC models ARAM on map 12, and admitting the band takes the
map-12-legal item pool from 251 to 403 with 95 outright base/mirror duplicates.
A normal ARAM game does not sell Elixir of Agility.

Nothing downstream can cover the champion rows either - Meraki 404s all 60, so
they have no ability formulas, no wiki sidecar, no archetype pick and no build
order.

So the snapshot on disk stays FAITHFUL to what DDragon shipped (the mirror is a
mirror) and the partition happens at load, in ``DataSnapshot.load`` and in
``core.build_order_precompute.full_roster``. Filtering the band restores the
registry to exactly its 16.14.1 shape - 173 champions, 706 items - which is the
measurement that says DDragon 16.15.1 added no canonical content here.

When a real throwback mode is wired into mode detection, drop the filter rather
than re-extracting history.

The champion test is the KEY, never the ``Jade_`` name prefix: a name test would
silently miss the next variant Riot ships under a different word, and would
wrongly drop a real champion who one day ships with that word in the id.
"""

from __future__ import annotations

from typing import Any, Mapping

# Real champion keys are small ints (1..950 at 16.15.1). Riot stamps a throwback
# champion at base_key + 60000, so any key at or above the floor is a variant.
VARIANT_CHAMPION_KEY_FLOOR = 60000

# Throwback items occupy a closed band. It is NOT open-ended: live registries
# already use 220000 (Arena mirrors) below it and 994403 above it, so an
# unbounded ">= 770000" would swallow a legitimate row.
VARIANT_ITEM_ID_RANGE = (770000, 780000)

__all__ = [
    "VARIANT_CHAMPION_KEY_FLOOR",
    "VARIANT_ITEM_ID_RANGE",
    "is_mode_variant_champion",
    "is_mode_variant_item",
    "canonical_champions",
    "canonical_items",
]


def is_mode_variant_champion(champ_id: str, entry: Any) -> bool:
    """True when ``entry`` is a throwback champion row, not a live champion.

    Fail-safe: a row whose key is absent or unparseable is treated as CANONICAL.
    Dropping a row we cannot classify would silently shrink the roster, which is
    the failure mode this module exists to prevent.
    """
    if not isinstance(entry, Mapping):
        return False
    try:
        key = int(str(entry.get("key")).strip())
    except (TypeError, ValueError):
        return False
    return key >= VARIANT_CHAMPION_KEY_FLOOR


def is_mode_variant_item(item_id: Any) -> bool:
    """True when ``item_id`` falls in the throwback item band.

    Fail-safe in the same direction: a non-numeric id is treated as CANONICAL.
    """
    try:
        iid = int(str(item_id).strip())
    except (TypeError, ValueError):
        return False
    low, high = VARIANT_ITEM_ID_RANGE
    return low <= iid < high


def canonical_champions(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``data`` without throwback champion rows (order preserved)."""
    return {
        cid: entry
        for cid, entry in data.items()
        if not is_mode_variant_champion(cid, entry)
    }


def canonical_items(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``data`` without throwback item rows (order preserved)."""
    return {
        iid: entry
        for iid, entry in data.items()
        if not is_mode_variant_item(iid)
    }
