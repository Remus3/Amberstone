# arch: static DS build-order fallback for the NEXT BUY feed | section=core | frozen=no
"""core.next_buy_fallback - roster-wide NEXT BUY feed from the STATIC DS tables.

RM-114 / item A-27. ``item_advisor.resolve_build`` is a hand-curated table
covering exactly 6 of 173 champions (the operator's own pool). Every other
champion returned ``[]``, so ``dashboard/_liveclient.py`` emitted no
``sr_items`` row with ``next: true`` and the in-game GOLD / TRINKET rows
rendered "-" for 97 percent of the roster.

This module re-sources the missing builds from the STATIC precomputed Daemon
Slayer build-order tables, as a FALLBACK ONLY. Deliberately NOT a live HTTP
call to :8860 - the static tables are the same data the champ-select Build
Order card already serves, they carry no runtime dependency on the DS server
being up, and they cannot stall the liveclient path.

REUSE, not a second parser: the table read is
``core.laning_scenario_precompute.load_build_orders`` (memoised, fail-soft to
``{}``), which reads the FLAT
``data/daemon_slayer/<patch>/build_orders_<mode>.json``.

KEYSPACE - there are TWO build-order keyspaces in this repo and they are NOT
interchangeable:

  * FLAT ``data/daemon_slayer/<patch>/build_orders_<mode>.json`` is
    DISPLAY-name keyed: "Miss Fortune", "Nunu & Willump", "Kha'Zix".
  * NEWER ``data/daemon_slayer/build_orders/<patch>/build_orders_<mode>.json``
    (``generate_table`` in core/build_order_precompute.py) is canonical-id
    keyed: "MissFortune", "Nunu", "Khazix".

This module reads the FLAT table (the operator-specified source) but joins on
``core.archetype_picks.canonical_champion_id`` applied to BOTH sides, so the
lookup key is the DDragon id on either end and a display-name spelling drift
(apostrophe, ampersand, spacing) cannot silently drop a champion. Measured
2026-07-24: all 173 flat keys map to 173 DISTINCT canonical ids in all three
modes, so the re-key is lossless.

MODE - the table stem is resolved with ``core.mode_capabilities.district_config``
(fail-CLOSED: unknown / PRACTICETOOL / TFT / garbage -> None). Only
"sr" / "aram" / "arena" have tables; anything else returns [] so the caller
falls through to today's behavior rather than to a WRONG-mode build. Arena and
ARAM item pools genuinely differ (Arena uses the 22xxxx / 44xxxx mirror ids),
so a cross-mode leak is a real defect class.

ENEMY LEAN (RM-164) - each champion's row carries THREE orders, "ad_heavy" /
"balanced" / "ap_heavy". Reading only "balanced" threw away a real signal: 71
of 173 SR champions, 71 of 173 ARAM and 67 of 173 Arena have a lean bucket
that differs from balanced, and for Alistar on SR the divergence is at the
OPENING slot (3143 Randuin's Omen, armor, vs 2504 Kaenic Rookern). The caller
already holds the enemy roster, so ``fallback_build_ids`` / ``fallback_build``
take it as a trailing optional argument and prefer the matching bucket. The
classifier is REUSED: ``core.aram_comp_verdict.compute_factors`` (display
names -> ad/ap counts) into ``core.aram_item_interaction.shape_from_factors``
(counts -> the coarse damage/frontline label). Omitting the roster reproduces
the pre-RM-164 balanced-only behavior exactly.

KILL SWITCH - ``RC_NEXTBUY_DS_FALLBACK``, default ON. Set to "0" to restore
the pre-slice behavior exactly.

FAIL-SOFT - every public entry point is total: a missing file, a bad key, a
malformed row, or any exception degrades to ``[]``. Nothing here may raise
into the liveclient path.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from pathlib import Path

from core import laning_scenario_precompute as _lsp
from core.aram_comp_verdict import compute_factors
from core.aram_item_interaction import shape_from_factors
from core.archetype_picks import canonical_champion_id
from core.mode_capabilities import district_config

FALLBACK_ENV = "RC_NEXTBUY_DS_FALLBACK"

# Table stems that actually exist on disk. district_config also answers
# "brawl", which has NO build-order table - excluded so brawl falls through
# to today's empty behavior instead of borrowing another mode's pool.
_SUPPORTED_STEMS = frozenset({"sr", "aram", "arena"})

# Neutral build path inside a champion's bucket dict, and the terminal
# fallback for every lean that does not resolve. Mirrors ``_BUILD_BUCKET`` in
# core/laning_scenario_precompute.py and the ``_next_build_item`` preference in
# core/laning_verdicts.py.
_PREFERRED_BUCKET = "balanced"

# Damage-axis labels shape_from_factors can emit that name a real bucket. Its
# third label, "mixed", deliberately has no bucket of its own - a mixed enemy
# comp IS the balanced case.
_LEAN_BUCKETS = frozenset({"ad_heavy", "ap_heavy"})

# An item id is 1-9 ASCII digits (SR 4-digit, Arena 22xxxx / 44xxxx). The
# length cap keeps a hostile cell away from int()'s 4300-digit ValueError,
# and ASCII-only refuses Unicode digits that str.isdigit / int() accept.
_ITEM_ID_RE = re.compile(r"[0-9]{1,9}")

# Roster shapes compute_factors itself accepts; anything else (a dict, a bare
# string) would otherwise be iterated into keys or characters.
_ROSTER_TYPES = (list, tuple, set, frozenset)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ITEMS_INDEX_PATH = _PROJECT_ROOT / "web" / "data" / "items_index.json"

_lock = threading.Lock()
# stem -> {canonical_champion_id: {bucket: [item_id_str]}}
_CANON_CACHE: dict = {}
# item id (str) -> display name
_ID_TO_NAME_CACHE: dict = {}


def reset_cache() -> None:
    """Drop the memoised canonical index + item-name map (tests / patch roll)."""
    with _lock:
        _CANON_CACHE.clear()
        _ID_TO_NAME_CACHE.clear()


def fallback_enabled() -> bool:
    """True unless ``RC_NEXTBUY_DS_FALLBACK`` is set to "0" / "false" / "no" /
    "off" (any case, surrounding spaces ignored) or to an empty value. Unset
    means ON.

    Read at CALL time, not import time, so the switch can be flipped without a
    restart and so tests can patch os.environ.
    """
    try:
        raw = os.environ.get(FALLBACK_ENV)
        if raw is None:
            return True
        return str(raw).strip().lower() not in ("0", "false", "no", "off", "")
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return True


def _table_stem(game_mode) -> str:
    """Raw Live Client gameMode ("CLASSIC" / "KIWI" / "CHERRY") -> table stem.

    Returns "" for anything without a table so the caller falls through to
    today's behavior rather than to a wrong-mode build.
    """
    try:
        stem = district_config(game_mode)
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return ""
    return stem if stem in _SUPPORTED_STEMS else ""


def _canon_table(stem: str) -> dict:
    """The flat build-order table for ``stem``, RE-KEYED on canonical champion id.

    Reuses core.laning_scenario_precompute.load_build_orders for the actual
    file read (no second parser). Memoised per stem; fail-soft to {}.
    """
    cached = _CANON_CACHE.get(stem)
    if cached is not None:
        return cached
    out: dict = {}
    try:
        orders = _lsp.load_build_orders(stem)
        if isinstance(orders, dict):
            for key, buckets in orders.items():
                if not isinstance(buckets, dict):
                    continue
                canon = canonical_champion_id(key)
                if canon:
                    out[canon] = buckets
    except Exception:  # noqa: BLE001 - missing / malformed table -> no fallback
        return {}
    # RM-443: memoise only a table that loaded. An empty table is either a
    # failed (uncached, retried) build-orders load or a genuinely empty one
    # that load_build_orders already memoises, so re-deriving it is free.
    if out:
        with _lock:
            _CANON_CACHE[stem] = out
    return out


def _item_id(value) -> str | None:
    """``value`` as a canonical item-id string ("3143"), or None.

    Accepts a positive int, an integral finite float and a string of 1-9
    ASCII digits (surrounding whitespace ignored). Refuses bool (``False``
    equals 0 and ``True`` 1), zero, negatives, fractional or non-finite
    floats and everything else, so a junk table cell is dropped instead of
    being stringified into a fake id ("True", "{'id': 1}").
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not (math.isfinite(value) and value.is_integer()):
            return None
        value = int(value)
    if isinstance(value, int):
        return str(value) if 0 < value < 10 ** 9 else None
    if isinstance(value, str):
        text = value.strip()
        if _ITEM_ID_RE.fullmatch(text) and int(text) > 0:
            return str(int(text))
    return None


def _clean_order(order) -> list:
    """The canonical item ids of one bucket, in order; [] for a non-list."""
    if not isinstance(order, list):
        return []
    return [i for i in (_item_id(v) for v in order) if i]


def _id_to_name() -> dict:
    """items_index byId (item id string -> display name). Memoised; {} on error.

    Only a non-blank STRING value is a name (stripped); a dict, list or
    number value is skipped rather than rendered as its repr. A file with no
    usable name is not memoised, so a repaired file is picked up (RM-443).
    """
    if _ID_TO_NAME_CACHE:
        return _ID_TO_NAME_CACHE
    try:
        doc = json.loads(_ITEMS_INDEX_PATH.read_text(encoding="utf-8"))
        by_id = doc.get("byId")
        if not isinstance(by_id, dict):
            return {}
        names: dict = {}
        for key, value in by_id.items():
            item_id = _item_id(key)
            if item_id and isinstance(value, str) and value.strip():
                names[item_id] = value.strip()
        with _lock:
            _ID_TO_NAME_CACHE.update(names)
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return {}
    return _ID_TO_NAME_CACHE


def preferred_bucket(enemy_team=None) -> str:
    """Bucket name to read for an enemy roster of champion DISPLAY names.

    "ad_heavy" / "ap_heavy" when the enemy comp leans hard enough on one
    damage axis, else "balanced". Absent, empty, unresolvable or malformed
    input all degrade to "balanced" rather than manufacturing a lean, because
    a wrong lean serves the wrong resistance item - strictly worse than the
    neutral order. Only a list / tuple / set roster is read (the shapes
    ``compute_factors`` accepts): a dict or a bare string is malformed, not
    a roster of its keys or characters. Never raises.
    """
    try:
        if not isinstance(enemy_team, _ROSTER_TYPES):
            return _PREFERRED_BUCKET
        names = [c.strip() for c in enemy_team
                 if isinstance(c, str) and c.strip()]
        if not names:
            return _PREFERRED_BUCKET
        lean = shape_from_factors(compute_factors(names)).split("/", 1)[0]
        return lean if lean in _LEAN_BUCKETS else _PREFERRED_BUCKET
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return _PREFERRED_BUCKET


def fallback_build_ids(champion, game_mode, enemy_team=None) -> list:
    """Ordered DS item IDS for ``champion`` in ``game_mode``, or [].

    ``enemy_team`` is an optional list of enemy champion DISPLAY names (the
    Live Client ``allPlayers[].championName`` shape). Supplying it selects the
    matching lean bucket; omitting it reads "balanced" exactly as before.

    Total: unknown champion, unmapped mode, missing table, malformed row, or
    the kill switch being off all yield []. Never raises.

    A CLASSIFIER fault is deliberately NOT in that list. A malformed roster or
    a broken lean classifier costs the LEAN, never the ROW: it degrades to the
    "balanced" order, which is the exact pre-RM-164 behavior. Returning []
    there would DELETE the champion's next-buy row over a comp-reading
    failure, which is strictly worse than the neutral order this module
    promises to fall back to.
    """
    try:
        if not fallback_enabled():
            return []
        if not isinstance(champion, str) or not champion.strip():
            return []
        stem = _table_stem(game_mode)
        if not stem:
            return []
        canon = canonical_champion_id(champion)
        if not canon:
            return []
        buckets = _canon_table(stem).get(canon)
        if not isinstance(buckets, dict):
            return []
        # Second guard at the CALL boundary even though preferred_bucket is
        # itself total: without it a raising classifier would escape to the
        # outer handler and return [], deleting the row instead of serving the
        # neutral order. The two guards fail to different values on purpose.
        try:
            bucket = preferred_bucket(enemy_team)
        except Exception:  # noqa: BLE001 - a lean fault must not cost the row
            bucket = _PREFERRED_BUCKET
        # Each step is judged on the ids that SURVIVE validation, so a lean
        # bucket of pure junk falls through to balanced instead of serving
        # an empty or fake row.
        order = _clean_order(buckets.get(bucket))
        if not order:
            order = _clean_order(buckets.get(_PREFERRED_BUCKET))
        if not order:
            order = next(
                (ids for ids in map(_clean_order, buckets.values()) if ids), []
            )
        return order
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return []


def fallback_build(champion, game_mode, enemy_team=None) -> list:
    """Ordered item DISPLAY NAMES for ``champion`` in ``game_mode``, or [].

    Same shape ``item_advisor.resolve_build`` returns, so the caller can drop
    it straight into the EXISTING boots-phase / is_redundant pipeline rather
    than around it. ``enemy_team`` is passed through to ``fallback_build_ids``
    for the lean bucket. Unresolvable ids are skipped, not faked. Never raises.
    """
    try:
        ids = fallback_build_ids(champion, game_mode, enemy_team)
        if not ids:
            return []
        by_id = _id_to_name()
        if not by_id:
            return []
        out: list = []
        for item_id in ids:
            name = by_id.get(item_id)
            if name and name not in out:
                out.append(name)
        return out
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return []
