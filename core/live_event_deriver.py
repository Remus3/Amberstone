# arch: pure live event deriver over consecutive Live Client snapshots | section=core | frozen=no
"""core/live_event_deriver.py - RM-604 / X-04 (external reference F, clean-room).

``derive_events(prev, cur)`` turns two CONSECUTIVE normalized Live Client
snapshots (the core/liveclient_cache.py payload that /api/state, the RM-605
recorder and the decision loop all read) into a list of discrete events.

Rules (re-implemented from the behaviour text only):

  * Events are a pure function of the two rows. No clock, no I/O, no state;
    inputs are never mutated. (The one exception is the static completed-item
    catalog, see ``completed_ids`` below.)
  * First knowledge is state, not an event: ``prev is None`` (first snapshot,
    or the first after a link loss / no-game) emits nothing.
  * A None reading never transitions anything. A missing / junk / None value
    on EITHER side of a field (isDead, level, items, the Events block) emits
    nothing for that field, and ``cur is None`` emits nothing at all.
  * A backwards game clock (new match, or a rewind) is treated as a first
    snapshot.

Kinds:
  death / respawn    allPlayers[].isDead False->True / True->False, keyed by
                     championName (a name held by two rows is ambiguous and
                     skipped, e.g. a one-for-all lobby).
  level_up           allPlayers[].level increase: {from, to}.
  item_completed     a COMPLETED item id gained a slot in a player's
                     inventory (components never fire). The completed set is
                     dashboard/_deterministic_coaching.py ``_legendary_catalog``
                     (the repo's existing owned-item spike classifier) unless
                     the caller passes ``completed_ids``.
  objective_taken    a new events.Events entry (by EventID) whose EventName is
                     in ``OBJECTIVE_EVENT_NAMES`` (incl. HordeKill = voidgrub),
                     with the RM-601 ``stolen`` flag and dragon_type.
  skill_point        RESERVED for RM-603 (X-03). Not emitted here: the
                     ability-level key naming varies by mode and X-03's
                     normalizer owns that read, so it is not trivially
                     derivable from the raw row.

Related: the concurrent P2-4 intake's edge watcher (core/edge_watcher.py on its
own branch, not on main when this landed) has the same priming rule (the first
observation never fires, an unreachable read re-primes silently). It is a
stateful per-target poller; this module is a stateless two-row diff, so the
replay server (tools/replay_session.py) can call it directly.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional

from core.liveclient_coerce import as_bool, as_list

DEATH = "death"
RESPAWN = "respawn"
LEVEL_UP = "level_up"
ITEM_COMPLETED = "item_completed"
OBJECTIVE_TAKEN = "objective_taken"
SKILL_POINT = "skill_point"  # reserved for RM-603 / X-03; never emitted here

EMITTED_KINDS: FrozenSet[str] = frozenset(
    {DEATH, RESPAWN, LEVEL_UP, ITEM_COMPLETED, OBJECTIVE_TAKEN})
RESERVED_KINDS: FrozenSet[str] = frozenset({SKILL_POINT})

# Live Client EventName -> objective name. Shared with
# dashboard/_liveclient.py (objective_events) so the two never drift.
OBJECTIVE_EVENT_NAMES: Dict[str, str] = {
    "DragonKill": "dragon",
    "BaronKill": "baron",
    "HeraldKill": "herald",
    "HordeKill": "voidgrub",
}

# Our own tolerance: Live Client gameTime jitters by well under a second
# between polls; a drop larger than this is a new match or a rewind.
_BACKWARDS_TOLERANCE_S = 1.0

_IDENTITY_KEYS = ("summonerName", "riotId", "riotIdGameName")


def _load_completed_ids() -> FrozenSet[str]:
    """The repo's existing completed-item set (memoised there)."""
    from dashboard._deterministic_coaching import _legendary_catalog
    return frozenset(_legendary_catalog()[0])


def _resolve_completed(completed_ids: Optional[Iterable[Any]]) -> FrozenSet[str]:
    if completed_ids is not None:
        return frozenset(str(i) for i in completed_ids)
    try:
        return _load_completed_ids()
    except Exception:  # noqa: BLE001 - no catalog -> no item events
        return frozenset()


def _unwrap(row: Any) -> Optional[dict]:
    """A recorded replay frame carries the snapshot under ``snapshot``."""
    if not isinstance(row, dict):
        return None
    if "gameData" not in row and "allPlayers" not in row and isinstance(row.get("snapshot"), dict):
        return row["snapshot"]
    return row


def _finite(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def _game_time(snap: dict) -> Optional[float]:
    gd = snap.get("gameData")
    return _finite(gd.get("gameTime")) if isinstance(gd, dict) else None


def _players(snap: dict) -> Dict[str, dict]:
    """championName -> row, ambiguous (duplicate) names dropped."""
    rows = [p for p in as_list(snap.get("allPlayers"), "allPlayers") if isinstance(p, dict)]
    counts = Counter(p.get("championName") for p in rows)
    out: Dict[str, dict] = {}
    for p in rows:
        name = p.get("championName")
        if isinstance(name, str) and name and counts[name] == 1:
            out[name] = p
    return out


def _identities(row: dict) -> set:
    return {row.get(k) for k in _IDENTITY_KEYS
            if isinstance(row.get(k), str) and row.get(k)}


def _active_ids(snap: dict) -> set:
    ap = snap.get("activePlayer")
    return _identities(ap) if isinstance(ap, dict) else set()


def _dead(row: dict) -> Optional[bool]:
    return as_bool(row.get("isDead"), None)  # type: ignore[arg-type]


def _items(row: dict) -> Optional[Counter]:
    raw = row.get("items")
    if not isinstance(raw, (list, dict)):
        return None
    c: Counter = Counter()
    for it in as_list(raw, "items"):
        if isinstance(it, dict):
            iid = _int(it.get("itemID"))
            if iid is not None:
                c[iid] += 1
    return c


def _objectives(snap: dict) -> Optional[Dict[int, dict]]:
    ev = snap.get("events")
    if not isinstance(ev, dict):
        return None
    raw = ev.get("Events")
    lst = as_list(raw, "Events")
    if not isinstance(raw, list) and not lst:
        return None
    out: Dict[int, dict] = {}
    for e in lst:
        if not isinstance(e, dict) or e.get("EventName") not in OBJECTIVE_EVENT_NAMES:
            continue
        eid = _int(e.get("EventID"))
        if eid is not None:
            out[eid] = e
    return out


def _player_base(kind: str, gt: Optional[float], champ: str, row: dict,
                 active: set) -> dict:
    return {"kind": kind, "game_time": gt, "champion": champ,
            "team": row.get("team") if isinstance(row.get("team"), str) else None,
            "active": bool(active & _identities(row))}


def _killer_team(killer: Any, cur: dict, players: Dict[str, dict],
                 my_team: Optional[str]) -> str:
    if not isinstance(killer, str) or not killer or not my_team:
        return "unknown"
    for champ, row in players.items():
        if killer == champ or killer in _identities(row):
            team = row.get("team")
            if not isinstance(team, str) or not team:
                return "unknown"
            return "ally" if team == my_team else "enemy"
    return "unknown"


def derive_events(prev: Any, cur: Any, *,
                  completed_ids: Optional[Iterable[Any]] = None) -> List[dict]:
    """Discrete events between two consecutive snapshots. Pure; see module doc."""
    p = _unwrap(prev)
    c = _unwrap(cur)
    if p is None or c is None:
        return []
    gt_p, gt_c = _game_time(p), _game_time(c)
    if gt_p is not None and gt_c is not None and gt_c < gt_p - _BACKWARDS_TOLERANCE_S:
        return []

    out: List[dict] = []
    pp, cp = _players(p), _players(c)
    active = _active_ids(c)
    my_team: Optional[str] = None
    for row in cp.values():
        if active & _identities(row) and isinstance(row.get("team"), str):
            my_team = row["team"]
            break

    # objectives first: they are ordered by the game's own EventID
    po, co = _objectives(p), _objectives(c)
    if po is not None and co is not None:
        for eid in sorted(set(co) - set(po)):
            e = co[eid]
            at = _finite(e.get("EventTime"))
            ev = {"kind": OBJECTIVE_TAKEN, "game_time": gt_c, "event_id": eid,
                  "objective": OBJECTIVE_EVENT_NAMES[e["EventName"]],
                  "at_s": at,
                  "killer_team": _killer_team(e.get("KillerName"), c, cp, my_team),
                  "stolen": as_bool(e.get("Stolen"), False)}
            dt = e.get("DragonType")
            if ev["objective"] == "dragon" and isinstance(dt, str) and dt:
                ev["dragon_type"] = dt
            out.append(ev)

    completed: Optional[FrozenSet[str]] = None
    for champ, crow in cp.items():
        prow = pp.get(champ)
        if prow is None:
            continue
        d0, d1 = _dead(prow), _dead(crow)
        if d0 is not None and d1 is not None and d0 != d1:
            ev = _player_base(DEATH if d1 else RESPAWN, gt_c, champ, crow, active)
            if d1:
                rt = _finite(crow.get("respawnTimer"))
                if rt is not None and rt > 0:
                    ev["respawn_in_s"] = rt
            out.append(ev)
        l0, l1 = _int(prow.get("level")), _int(crow.get("level"))
        if l0 is not None and l1 is not None and l1 > l0:
            ev = _player_base(LEVEL_UP, gt_c, champ, crow, active)
            ev["from"], ev["to"] = l0, l1
            out.append(ev)
        i0, i1 = _items(prow), _items(crow)
        if i0 is not None and i1 is not None:
            gained = [(iid, n - i0.get(iid, 0)) for iid, n in i1.items() if n > i0.get(iid, 0)]
            if gained:
                if completed is None:
                    completed = _resolve_completed(completed_ids)
                for iid, n in sorted(gained):
                    if str(iid) not in completed:
                        continue
                    for _ in range(n):
                        ev = _player_base(ITEM_COMPLETED, gt_c, champ, crow, active)
                        ev["item_id"] = iid
                        out.append(ev)
    return out


EventsSource = Callable[[Any, Any], List[dict]]
