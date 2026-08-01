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
    (core/build_order_precompute.py:79) is canonical-id keyed: "MissFortune",
    "Nunu", "Khazix".

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

KILL SWITCH - ``RC_NEXTBUY_DS_FALLBACK``, default ON. Set to "0" to restore
the pre-slice behavior exactly.

FAIL-SOFT - every public entry point is total: a missing file, a bad key, a
malformed row, or any exception degrades to ``[]``. Nothing here may raise
into the liveclient path.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from core import laning_scenario_precompute as _lsp
from core.archetype_picks import canonical_champion_id
from core.mode_capabilities import district_config

FALLBACK_ENV = "RC_NEXTBUY_DS_FALLBACK"

# Table stems that actually exist on disk. district_config also answers
# "brawl", which has NO build-order table - excluded so brawl falls through
# to today's empty behavior instead of borrowing another mode's pool.
_SUPPORTED_STEMS = frozenset({"sr", "aram", "arena"})

# Preferred build path inside a champion's bucket dict. Mirrors
# core/laning_scenario_precompute.py:355 and core/laning_verdicts.py:197.
_PREFERRED_BUCKET = "balanced"

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
    """True unless ``RC_NEXTBUY_DS_FALLBACK`` is explicitly "0" / "false" / "off".

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
        out = {}
    with _lock:
        _CANON_CACHE[stem] = out
    return out


def _id_to_name() -> dict:
    """items_index byId (item id string -> display name). Memoised; {} on error."""
    if _ID_TO_NAME_CACHE:
        return _ID_TO_NAME_CACHE
    try:
        doc = json.loads(_ITEMS_INDEX_PATH.read_text(encoding="utf-8"))
        by_id = doc.get("byId")
        if isinstance(by_id, dict):
            with _lock:
                _ID_TO_NAME_CACHE.update(
                    {str(k): str(v) for k, v in by_id.items() if v}
                )
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return {}
    return _ID_TO_NAME_CACHE


def fallback_build_ids(champion, game_mode) -> list:
    """Ordered DS item IDS for ``champion`` in ``game_mode``, or [].

    Total: unknown champion, unmapped mode, missing table, malformed row, or
    the kill switch being off all yield []. Never raises.
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
        order = buckets.get(_PREFERRED_BUCKET)
        if not isinstance(order, list) or not order:
            order = next(
                (v for v in buckets.values() if isinstance(v, list) and v), None
            )
        if not isinstance(order, list):
            return []
        return [str(i) for i in order if i or i == 0]
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return []


def fallback_build(champion, game_mode) -> list:
    """Ordered item DISPLAY NAMES for ``champion`` in ``game_mode``, or [].

    Same shape ``item_advisor.resolve_build`` returns, so the caller can drop
    it straight into the EXISTING boots-phase / is_redundant pipeline rather
    than around it. Unresolvable ids are skipped, not faked. Never raises.
    """
    try:
        ids = fallback_build_ids(champion, game_mode)
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
