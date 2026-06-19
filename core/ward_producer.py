# arch: ward-placement producer over allPlayers inventory delta | section=core | frozen=no
"""core/ward_producer.py - infer ward placements from Live Client inventory deltas.

Companion to ``core/ward_events.py``. ``ward_events`` is the rolling-window
sink (record_ward injection API); this module is the producer half - it
diffs successive ``allPlayers`` snapshots and calls ``record_ward`` for
each inferred placement.

CONTRACT (Live Client API, 2026-05):
  ``GET /liveclientdata/allgamedata`` -> ``allPlayers`` is a list of 10
  player dicts. Per the Riot Live Client documentation, each player has
  an ``items`` array; each item entry carries::

      {itemID, slot, count, displayName, canUse, consumable, ...}

  The fields that matter for ward detection:
    * ``itemID``    - integer; the Riot item id. Wards are:
                        3340 yellow trinket (warding totem)
                        3363 farsight (blue trinket)
                        3364 sweeper (oracle / red trinket - NOT a placeable
                              ward; it reveals, no placement event - skip)
                        2055 control ward (consumable, stackable)
                        3711 / 3855 ornn / other - not wards
    * ``count``     - stack count. Control wards stack up to 2; a count
                      decrement from N -> N-1 means one was placed (or
                      consumed; we treat both as "placement attempt").
    * ``canUse``    - bool. True when the item is usable RIGHT NOW. For the
                      yellow / blue trinkets this is the only reliable
                      "fired" signal we have - a True -> False transition
                      means it was activated. A False -> True transition
                      is the cooldown finishing; we ignore that direction.
    * ``slot``      - 0..6, with slot 6 being the trinket slot. Stable.

  CAVEAT 1 (yellow trinket charges):
    The yellow Warding Totem charges over time and can store up to 2
    wards. The Live Client API does NOT expose individual charge count -
    only ``canUse`` (and the item never disappears from slot 6). We
    detect the cast via ``canUse`` True -> False. If the player used 2
    charges in rapid succession (within one poll tick) we will undercount
    by 1. The cap is rare in practice and this is the best signal
    available.

  CAVEAT 2 (sweeper / oracle 3364):
    The red sweeper trinket REVEALS, it does not place a ward. We exclude
    3364 from the producer entirely. Same for control-ward-equivalent
    augments that don't have an inventory presence.

  CAVEAT 3 (lane inference):
    ``allPlayers[i].position`` is a LANE STRING (TOP / JUNGLE / MIDDLE /
    BOTTOM / UTILITY / NONE), NOT x/z coordinates. We map role -> lane:
      TOP -> top, MIDDLE -> mid, BOTTOM -> bot, UTILITY -> bot,
      JUNGLE -> jg, anything else -> unknown. This is coarse (a JUNGLE
      role player warding a river camp is "jg" not the actual ward
      location) but better than nothing. The UX-3 heat strip is a coarse
      side-vs-side coverage panel, not a precise minimap - this is OK.

  CAVEAT 4 (side mapping):
    Live Client emits ``team`` as ORDER / CHAOS. The operator's side is
    derived from ``activePlayer.summonerName`` matching against
    ``allPlayers[i].summonerName`` to find the operator's team; everyone
    on the operator's team becomes ``ally``, everyone else ``enemy``.
    If the operator's team can't be resolved (e.g. spectator-mode polls)
    we degrade to ``ally`` for ORDER and ``enemy`` for CHAOS - the most
    common solo-queue case.

DESIGN:
  Stateless callers; the producer holds its own per-puuid (or
  per-summonerName, since Live Client doesn't expose puuid) state across
  ticks. The state is a flat dict mapping summoner_name -> last-seen
  inventory snapshot (a dict ``{itemID: (count, canUse)}``). The first
  call after a reset just snapshots state and returns 0. Subsequent calls
  diff against prior state, record_ward() for each detected event, and
  refresh state.

  Game-restart detection: a new game has a different ``activePlayer``
  (operator) summoner name or a smaller player set after we already had
  a baseline. We detect this via ``_signature(allplayers)`` - the sorted
  tuple of summoner names - and call ``reset()`` automatically when it
  changes. Callers can also call ``reset()`` explicitly.

PUBLIC API:
  - tick(allplayers_now, ts=None, *, active_summoner=None) -> int
      Diff vs prior state, record_ward() for each new event, refresh
      state. Returns count of records made. ``ts`` defaults to
      time.time(). ``active_summoner`` is the operator's summoner name
      (from ``activePlayer.summonerName``) and lets us resolve the side
      label; omit and we fall back to ORDER=ally / CHAOS=enemy.
  - reset() -> None
      Drop internal state. Called automatically on game shape change.
  - snapshot_size() -> int
      Debug helper: number of players currently tracked.

INTEGRATION:
  This module is pure - it does NOT poll Live Client. A future wire into
  ``core/liveclient_cache.py`` (or a sibling daemon) will call ``tick()``
  every snapshot refresh. Until that wire ships, the producer is
  unit-tested standalone and the heat-strip route returns an empty
  rolling window. The producer module + tests are the safe shippable
  layer; the wire is operator-gated (touches a frozen file or adjacent
  hot path).
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from core import ward_events

# Riot item ids of placeable wards. NOT a frozenset - small and fixed.
WARD_ITEM_IDS: dict[int, str] = {
    3340: "yellow",        # Warding Totem (yellow trinket)
    3363: "farsight",      # Farsight Alteration (blue trinket)
    2055: "control",       # Control Ward (consumable)
    # 3364 (Sweeper / Oracle) is NOT a placeable ward - excluded.
    # 3513 Eye-of-Herald was deprecated post-patch 12.x; not in 16.10.
}

# Lane mapping from Live Client ``position`` strings.
_POSITION_TO_LANE: dict[str, str] = {
    "TOP":     "top",
    "MIDDLE":  "mid",
    "BOTTOM":  "bot",
    "UTILITY": "bot",      # support roams bot more than anywhere else
    "JUNGLE":  "jg",
}

# Module state.
_state_lock = threading.Lock()
# _state[summoner_name] = {itemID: (count, canUse)}
_state: dict[str, dict[int, tuple[int, bool]]] = {}
# _signature is the sorted tuple of summoner names from the last tick;
# used to auto-reset on game shape change.
_signature: Optional[tuple[str, ...]] = None


def _player_signature(allplayers: list) -> tuple[str, ...]:
    """Return the sorted tuple of summoner names for shape-change detection.

    A change here = different lobby / new game. Empty input returns ().
    """
    if not isinstance(allplayers, list):
        return ()
    names: list[str] = []
    for p in allplayers:
        if not isinstance(p, dict):
            continue
        n = p.get("summonerName")
        if isinstance(n, str) and n:
            names.append(n)
    return tuple(sorted(names))


def _extract_ward_inventory(items: list) -> dict[int, tuple[int, bool]]:
    """Pull just the ward-relevant entries from a player's ``items`` array.

    Returns a dict ``{itemID: (count, canUse)}``. Non-ward items are
    excluded. Malformed entries are skipped silently (defensive against
    relay churn).
    """
    out: dict[int, tuple[int, bool]] = {}
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = it.get("itemID")
        if not isinstance(iid, int) or iid not in WARD_ITEM_IDS:
            continue
        # ``count`` defaults to 1 (single-stack items omit it on some
        # patches); ``canUse`` defaults to True when absent so a missing
        # field never falsely registers a placement.
        try:
            count = int(it.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        can_use = bool(it.get("canUse", True))
        out[iid] = (count, can_use)
    return out


def _resolve_side(player: dict, active_summoner: Optional[str],
                  active_team: Optional[str]) -> str:
    """Resolve ally / enemy for ``player``.

    If we know the operator's team (from ``active_team``), match team-eq
    -> ally, else enemy. If we don't, fall back to ORDER=ally /
    CHAOS=enemy (the solo-queue common case).
    """
    team = player.get("team")
    if active_team and team:
        return "ally" if team == active_team else "enemy"
    if team == "ORDER":
        return "ally"
    if team == "CHAOS":
        return "enemy"
    return "ally"  # last-resort default


def _resolve_lane(player: dict) -> str:
    """Map ``allPlayers[i].position`` to the ward-events lane label."""
    pos = player.get("position")
    if not isinstance(pos, str):
        return "unknown"
    return _POSITION_TO_LANE.get(pos.upper(), "unknown")


def _detect_placements(prev: dict[int, tuple[int, bool]],
                       curr: dict[int, tuple[int, bool]]) -> list[str]:
    """Diff a single player's prev vs curr ward inventory.

    Returns a list of ward_type labels (one per placement detected).
    Detection rules:
      * Control ward (2055) count decrement -> 1 placement per delta.
        Going from 2 -> 0 yields 2 placements. Going to ABSENT is also
        a decrement (count effectively 0).
      * Yellow / Farsight trinket ``canUse`` True -> False -> 1 placement.
      * Trinket appearing for the first time (new game tick) -> not a
        placement (handled by the first-tick zero-record path).
      * canUse False -> True (cooldown finished) -> ignored.
    """
    events: list[str] = []
    for iid, ward_type in WARD_ITEM_IDS.items():
        prev_entry = prev.get(iid)
        curr_entry = curr.get(iid)
        if iid == 2055:
            # Control ward: count-decrement signal.
            prev_count = prev_entry[0] if prev_entry else 0
            curr_count = curr_entry[0] if curr_entry else 0
            if curr_count < prev_count:
                events.extend([ward_type] * (prev_count - curr_count))
        else:
            # Trinkets: canUse True -> False signal.
            if prev_entry is None or curr_entry is None:
                continue
            prev_can = prev_entry[1]
            curr_can = curr_entry[1]
            if prev_can and not curr_can:
                events.append(ward_type)
    return events


def tick(allplayers_now: list, ts: Optional[float] = None,
         *, active_summoner: Optional[str] = None) -> int:
    """Diff ``allplayers_now`` vs the prior tick and record placements.

    Returns the number of placements recorded. On the very first call
    (or after a reset / game shape change) state is seeded and the
    function returns 0 - we need TWO consecutive snapshots before a delta
    can exist.

    ``active_summoner`` is the operator's summonerName from
    ``activePlayer.summonerName``; passing it lets the side resolver use
    real team membership rather than ORDER-fallback. Optional.
    """
    global _state, _signature
    if ts is None:
        ts = time.time()
    if not isinstance(allplayers_now, list):
        return 0

    # Shape-change check: if the player roster changed, reset.
    sig_now = _player_signature(allplayers_now)
    records = 0

    with _state_lock:
        if _signature is not None and sig_now != _signature:
            _state = {}
        _signature = sig_now

        # Resolve operator's team if we can.
        active_team: Optional[str] = None
        if active_summoner:
            for p in allplayers_now:
                if isinstance(p, dict) and p.get("summonerName") == active_summoner:
                    t = p.get("team")
                    if isinstance(t, str):
                        active_team = t
                    break

        first_tick = not _state

        for player in allplayers_now:
            if not isinstance(player, dict):
                continue
            name = player.get("summonerName")
            if not isinstance(name, str) or not name:
                continue
            curr_inv = _extract_ward_inventory(player.get("items") or [])
            prev_inv = _state.get(name, {})

            if not first_tick:
                events = _detect_placements(prev_inv, curr_inv)
                if events:
                    side = _resolve_side(player, active_summoner, active_team)
                    lane = _resolve_lane(player)
                    for ward_type in events:
                        ward_events.record_ward(side, lane, ward_type, ts=ts)
                        records += 1

            _state[name] = curr_inv

    return records


def reset() -> None:
    """Drop all producer state. Idempotent."""
    global _state, _signature
    with _state_lock:
        _state = {}
        _signature = None


def snapshot_size() -> int:
    """Number of players currently tracked. Debug helper."""
    with _state_lock:
        return len(_state)


def tick_from_snapshot(snap: object) -> int:
    """Adapter for ``core.liveclient_cache.add_listener``.

    Pulls ``allPlayers`` and the active summoner from a Snapshot's
    ``data`` dict (the parsed /allgamedata payload) and calls ``tick``.
    Fail-soft - any missing field returns 0 with no state change.

    Returns the number of placements recorded on this tick.
    """
    data = getattr(snap, "data", None)
    if not isinstance(data, dict):
        return 0
    allplayers = data.get("allPlayers")
    if not isinstance(allplayers, list):
        return 0
    active = None
    ap = data.get("activePlayer")
    if isinstance(ap, dict):
        nm = ap.get("summonerName")
        if isinstance(nm, str) and nm:
            active = nm
    ts = getattr(snap, "ts", None) or None
    return tick(allplayers, ts=ts, active_summoner=active)


_LISTENER_INSTALLED = False


def install_liveclient_listener() -> bool:
    """Idempotent: register tick_from_snapshot on liveclient_cache.

    Returns True on first install, False if already installed (or if
    liveclient_cache could not be imported for any reason - fail-soft).
    """
    global _LISTENER_INSTALLED
    if _LISTENER_INSTALLED:
        return False
    try:
        from core import liveclient_cache
        liveclient_cache.add_listener(tick_from_snapshot)
        _LISTENER_INSTALLED = True
        return True
    except Exception:  # noqa: BLE001
        return False
