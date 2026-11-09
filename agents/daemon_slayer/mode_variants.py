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
measurement that says DDragon 16.15.1 added no canonical content here. (Those
counts are the 16.15.1 measurement, not a live invariant: later patches moved
both sides, and tests/test_champion_mode_variants.py pins the current ones.)

When a real throwback mode is wired into mode detection, drop the filter rather
than re-extracting history.

The champion test is the KEY, never the ``Jade_`` name prefix: a name test would
silently miss the next variant Riot ships under a different word, and would
wrongly drop a real champion who one day ships with that word in the id.

Ids are read by the DDragon grammar - an ``int`` or a string
of ASCII decimal digits, optionally padded with ASCII whitespace - and NOT by
Python's ``int()``, which also accepts digit-group underscores, a sign and every
Unicode decimal digit. Anything outside the grammar is unclassifiable and so,
by the fail-safe below, KEPT (s144 true-audit, S144-T-682).
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


# DDragon pads nothing, but the old parser stripped surrounding whitespace and a
# hand-edited cache may carry a trailing newline; ASCII padding stays tolerated.
_ASCII_WHITESPACE = " \t\r\n\v\f"


def _ddragon_int(value: Any) -> int | None:
    """``value`` as a DDragon id, or None when it is outside the id grammar.

    Never raises: no ``str()`` is called on an arbitrary object, and a digit
    string too long for ``int()`` (the interpreter's digit limit) is None.
    """
    if isinstance(value, int):
        # A bool is an int of 0 / 1: below the floor and outside the band.
        return int(value)
    if not isinstance(value, str):
        return None
    text = value.strip(_ASCII_WHITESPACE)
    if not (text.isascii() and text.isdigit()):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _require_mapping(data: Any, fname: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(
            f"{fname} expects a mapping of DDragon rows, got {type(data).__name__}"
        )
    return data


def is_mode_variant_champion(champ_id: str, entry: Any) -> bool:
    """True when ``entry`` is a throwback champion row, not a live champion.

    Fail-safe: a row whose key is absent, unparseable or outside the DDragon id
    grammar is treated as CANONICAL. Dropping a row we cannot classify would
    silently shrink the roster, which is the failure mode this module exists to
    prevent. ``champ_id`` is deliberately unused - the test is the key.
    """
    if not isinstance(entry, Mapping):
        return False
    key = _ddragon_int(entry.get("key"))
    return key is not None and key >= VARIANT_CHAMPION_KEY_FLOOR


def is_mode_variant_item(item_id: Any) -> bool:
    """True when ``item_id`` falls in the throwback item band.

    Fail-safe in the same direction: an id outside the DDragon grammar is
    treated as CANONICAL.
    """
    iid = _ddragon_int(item_id)
    if iid is None:
        return False
    low, high = VARIANT_ITEM_ID_RANGE
    return low <= iid < high


def canonical_champions(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``data`` without throwback champion rows (order preserved).

    Raises TypeError naming this function when ``data`` is not a mapping.
    """
    rows = _require_mapping(data, "canonical_champions")
    return {
        cid: entry
        for cid, entry in rows.items()
        if not is_mode_variant_champion(cid, entry)
    }


def canonical_items(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``data`` without throwback item rows (order preserved).

    Raises TypeError naming this function when ``data`` is not a mapping.
    """
    rows = _require_mapping(data, "canonical_items")
    return {
        iid: entry
        for iid, entry in rows.items()
        if not is_mode_variant_item(iid)
    }
