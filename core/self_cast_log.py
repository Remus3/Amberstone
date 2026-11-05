"""core/self_cast_log.py - self ability-usage log from :2999 resource deltas.

RM-606 (directive X-06, behaviour from external reference F; clean-room, no
code or constants copied). No computer vision: the log is inferred from the
active player's resource bar as seen by the existing 0.5 s Live Client poll
(core/liveclient_cache.py, via its add_listener API).

Rules
-----
* A cast is a resource FALL past FALL_THRESHOLD that HOLDS. One reading past
  the threshold is only a candidate; the next distinct reading either
  confirms it (the value is still at least FALL_THRESHOLD under the
  pre-fall baseline) or reverts it (dropped, never emitted).
* A fall on the same poll as a resourceMax change is rejected. A level-up
  adds the same amount to max and current, so it cannot fake a cast; an item
  sale or form swap that moves max is not a cast either. A max change on the
  CONFIRMING poll is netted out (value minus max delta) before the hold test.
* A fall seen across a poll gap (game-time delta > GAP_S) is emitted once,
  with span=(t_before, t_after), and its size is treated as a FLOOR (regen
  during the gap hid part of it, and it may hide several casts).
* The slot is named by matching the absolute fall to the per-rank cost of
  each LEARNED slot at its CURRENT rank, from DS champion data
  (data/daemon_slayer/<patch>/champion_abilities.json, the same file
  agents/daemon_slayer/abilities.py loads; read directly here so the DS
  package is not imported into the live process).
* Only MANA and ENERGY are tracked. Manaless, rage, fury, heat, flow,
  shield, bloodwell, ferocity and every other or unknown resource type is
  EXCLUDED explicitly (fail closed).

Emitted record: {t, slot_guess, cost, confidence, span}
  t           game time (s) of the reading where the fall was seen
  slot_guess  "Q" / "W" / "E" / "R", or None (no match, or a tie between
              slots of equal cost)
  cost        observed absolute fall (a floor when span is set)
  confidence  CONF_* tier below (our own ordinal scale, not a probability)
  span        None, or (t_before, t_after) for a fall seen across a gap

Known blind spots (directive risks): 2 Hz sampling merges back-to-back casts
inside one poll; regen, potions and blue buff hide part of a cost (see
partial_tolerance); refunds are invisible; toggles and channels that drain
per second produce falls that match no per-rank cost (slot_guess None).

DEFAULT OFF. Enabled only when RC_SELF_CAST_LOG is truthy (same flag
discipline as RC_CAPGAP_SHADOW in dashboard/routes_state.py). No coach
consumes this log yet: the per-slot totals must first be validated against
Match-V5 spell1Casts..spell4Casts (validate_against_match_v5) on recorded
sessions, which is live-gated.

Thread safety: on_snapshot runs on the single liveclient poll thread; the
module state is guarded by one lock so events() / reset() are safe from
other threads.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

_log = logging.getLogger("rc.self_cast_log")

FLAG_ENV = "RC_SELF_CAST_LOG"
_TRUTHY = ("1", "true", "yes", "on")

SLOTS = ("Q", "W", "E", "R")
TRACKED_RESOURCES = frozenset({"MANA", "ENERGY"})
# Named explicitly so the exclusion is visible in review; any type outside
# TRACKED_RESOURCES is excluded whether or not it is listed here.
EXCLUDED_RESOURCES = frozenset({
    "NONE", "RAGE", "FURY", "HEAT", "FLOW", "SHIELD", "BLOODWELL", "FEROCITY",
    "GNARFURY", "WIND", "BATTLEFURY", "DRAGONFURY", "CRIMSONRUSH", "OTHER",
})

# --- our own constants (not measured from any external source) ------------
# Minimum fall that becomes a candidate. The cheapest per-rank MANA/ENERGY
# cost in the 16.18.1 DS data is well above this; regen only raises the
# value, so a fall this size is spending (or a drain), not noise.
FALL_THRESHOLD = 5.0
# A game-time delta above this between two readings is a poll gap. 2.5x the
# 0.5 s cadence: one missed poll is tolerated, two are a gap.
GAP_S = 1.25
# Partial-cost tolerance: regen, a potion tick or blue buff inside one poll
# can hide part of a cost, so an observed fall may sit BELOW the true cost
# by up to max(PARTIAL_ABS, PARTIAL_REL * cost). Postulate; re-measure on
# recorded sessions (live-gated).
PARTIAL_ABS = 8.0
PARTIAL_REL = 0.15
# An observed fall may exceed the cost only by float/rounding noise.
OVER_TOL = 1.0
# Confidence tiers (ordinal).
CONF_EXACT = 0.9       # one slot, |fall - cost| <= OVER_TOL
CONF_PARTIAL = 0.6     # one slot, within the partial-cost tolerance
CONF_GAP = 0.3         # matched only as a floor across a poll gap
CONF_AMBIGUOUS = 0.2   # several slots share the matching cost
CONF_NONE = 0.1        # a held fall that matches no learned slot

# Match-V5 validation tolerance per slot: |log - truth| <= max(MATCH_ABS_TOL,
# round(MATCH_REL_TOL * truth)). Our own postulate, chosen to absorb the
# merged back-to-back casts and invisible refunds listed above; it must be
# re-measured once recorded sessions exist (live-gated).
MATCH_ABS_TOL = 3
MATCH_REL_TOL = 0.20

_EVENTS_MAX = 2000

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DS_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

CostTable = Dict[str, Tuple[Optional[str], Optional[Tuple[float, ...]]]]


# -- flag --------------------------------------------------------------------

def is_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(FLAG_ENV, "0")).strip().lower() in _TRUTHY


def is_tracked_resource(rtype: Any) -> bool:
    return isinstance(rtype, str) and rtype.strip().upper() in TRACKED_RESOURCES


# -- readings ----------------------------------------------------------------

@dataclass(frozen=True)
class Reading:
    t: float
    value: float
    maximum: float
    rtype: str
    ranks: Dict[str, int] = field(default_factory=dict)


# Range bounds on Live Client readings (s144 true-audit). A value outside is
# junk, not a reading: a resourceValue of -50 was a fake 450-point "cast".
_T_MAX = 10.0 ** 6        # game-time seconds
_RES_MAX = 10.0 ** 5      # resourceValue / resourceMax
_RANK_MAX = 6             # the highest abilityLevel any slot reaches
_COUNT_MAX = 10 ** 5      # a Match-V5 spellNCasts truth


def _num(v: Any) -> Optional[float]:
    """A finite float from an int-not-bool or float, else None. A >1e308 int
    is None rather than OverflowError."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _bounded(v: Any, hi: float) -> Optional[float]:
    f = _num(v)
    return f if f is not None and 0.0 <= f <= hi else None


def _count(v: Any, hi: int) -> Optional[int]:
    """An int-not-bool or integral float in 0..hi, else None (12.7 is not a
    count, and neither is -3)."""
    f = _bounded(v, float(hi))
    return int(f) if f is not None and f == int(f) else None


def reading_from_allgamedata(data: Any) -> Optional[Reading]:
    """Build a Reading from a parsed /allgamedata dict, or None.

    Keys (probed in dashboard/_liveclient.py and
    game_reader/snapshot_normalizer.py): activePlayer.championStats.
    {resourceValue, resourceMax, resourceType}, activePlayer.abilities.
    {Q,W,E,R}.abilityLevel, gameData.gameTime.

    gameTime must be a number in 0..10**6 and resourceValue / resourceMax
    numbers in 0..10**5, else None. An abilityLevel that is not an integral
    0..6 reads as 0 (unlearned), so a junk rank never names a slot.
    """
    if not isinstance(data, dict):
        return None
    ap = data.get("activePlayer")
    gd = data.get("gameData")
    if not isinstance(ap, dict) or not isinstance(gd, dict):
        return None
    cs = ap.get("championStats")
    if not isinstance(cs, dict):
        return None
    t = _bounded(gd.get("gameTime"), _T_MAX)
    value = _bounded(cs.get("resourceValue"), _RES_MAX)
    maximum = _bounded(cs.get("resourceMax"), _RES_MAX)
    if t is None or value is None or maximum is None:
        return None
    rtype = cs.get("resourceType")
    rtype = rtype.strip().upper() if isinstance(rtype, str) else ""
    ranks: Dict[str, int] = {}
    abilities = ap.get("abilities")
    if isinstance(abilities, dict):
        for slot in SLOTS:
            ab = abilities.get(slot) or abilities.get(slot.lower())
            lvl = _count(ab.get("abilityLevel"), _RANK_MAX) \
                if isinstance(ab, dict) else None
            ranks[slot] = lvl if lvl is not None else 0
    else:
        ranks = {s: 0 for s in SLOTS}
    return Reading(t=t, value=value, maximum=maximum, rtype=rtype, ranks=ranks)


def _str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _full_ids(p: Mapping[str, Any]) -> set:
    """Every "Name#TAG" form a player row carries (riotId, a summonerName
    with a tag, riotIdGameName + riotIdTagLine)."""
    out = {_str(p.get("riotId")), _str(p.get("summonerName"))}
    name, tag = _str(p.get("riotIdGameName")), _str(p.get("riotIdTagLine"))
    if name and tag:
        out.add(name + "#" + tag)
    return {s for s in out if "#" in s and not s.startswith("#")}


def _base_names(p: Mapping[str, Any]) -> set:
    """Every game name (no tag) a player row carries."""
    out = set()
    for k in ("riotIdGameName", "summonerName", "riotId"):
        s = _str(p.get(k)).split("#", 1)[0].strip()
        if s:
            out.add(s)
    return out


def active_champion_name(data: Any) -> Optional[str]:
    """championName of the active player from allPlayers (display name).

    An exact "Name#TAG" match wins; a game-name-only match counts only when
    exactly one player has it (two players may share a game name across tag
    lines). Ambiguous or absent is None, never the first row that matched.
    """
    if not isinstance(data, dict):
        return None
    ap = data.get("activePlayer")
    if not isinstance(ap, dict):
        return None
    players = data.get("allPlayers")
    if not isinstance(players, list):
        return None
    rows = [p for p in players if isinstance(p, dict)]
    me_full, me_base = _full_ids(ap), _base_names(ap)
    hits = [p for p in rows if me_full & _full_ids(p)] if me_full else []
    if not hits and me_base:
        hits = [p for p in rows if me_base & _base_names(p)]
    if len(hits) != 1:
        return None
    name = _str(hits[0].get("championName"))
    return name or None


# -- slot matching -----------------------------------------------------------

def partial_tolerance(cost: float) -> float:
    """How far BELOW a true cost an observed fall may sit (regen / potion /
    blue buff inside one poll). Our own postulate; see module docstring."""
    return max(PARTIAL_ABS, PARTIAL_REL * float(cost))


def _cost_at_rank(costs: Optional[Tuple[float, ...]], rank: int) -> Optional[float]:
    if not costs or rank < 1:
        return None
    idx = min(rank, len(costs)) - 1
    c = float(costs[idx])
    return c if c > 0 else None


def _live_costs(ranks: Mapping[str, int], table: CostTable,
                rtype: str) -> List[Tuple[str, float]]:
    out = []
    for slot in SLOTS:
        entry = table.get(slot)
        if not entry:
            continue
        res, costs = entry
        if not isinstance(res, str) or res.upper() != rtype.upper():
            continue
        c = _cost_at_rank(costs, int(ranks.get(slot, 0) or 0))
        if c is not None:
            out.append((slot, c))
    return out


def match_slot(fall: float, ranks: Mapping[str, int], table: CostTable,
               rtype: str, floor: bool = False
               ) -> Tuple[Optional[str], Optional[float], float]:
    """Return (slot_guess, matched_cost, confidence) for an observed fall.

    Normal: a slot matches when cost - partial_tolerance(cost) <= fall <=
    cost + OVER_TOL. floor=True (fall seen across a gap): the fall is a
    lower bound, so the smallest current-rank cost >= fall - OVER_TOL wins.
    Ties between slots of equal cost return slot None (CONF_AMBIGUOUS).
    """
    live = _live_costs(ranks, table, rtype)
    if floor:
        cands = [(s, c) for s, c in live if c >= fall - OVER_TOL]
        if not cands:
            return None, None, CONF_NONE
        best = min(c for _s, c in cands)
        tied = [s for s, c in cands if abs(c - best) <= 1e-9]
        if len(tied) > 1:
            return None, best, CONF_AMBIGUOUS
        return tied[0], best, CONF_GAP
    cands = [(s, c) for s, c in live
             if c - partial_tolerance(c) <= fall <= c + OVER_TOL]
    if not cands:
        return None, None, CONF_NONE
    best = min(abs(c - fall) for _s, c in cands)
    tied = [(s, c) for s, c in cands if abs(abs(c - fall) - best) <= 1e-9]
    if len(tied) > 1:
        return None, tied[0][1], CONF_AMBIGUOUS
    s, c = tied[0]
    conf = CONF_EXACT if abs(c - fall) <= OVER_TOL else CONF_PARTIAL
    return s, c, conf


# -- detector ----------------------------------------------------------------

class SelfCastDetector:
    """Hold-confirm cast detector over successive Readings."""

    def __init__(self, costs: Optional[CostTable] = None) -> None:
        self.costs: CostTable = dict(costs or {})
        self.excluded_reason: Optional[str] = None
        self._base: Optional[Reading] = None
        self._cand: Optional[Reading] = None

    def reset(self) -> None:
        self._base = None
        self._cand = None

    def _emit(self, base: Reading, cand: Reading) -> Dict[str, Any]:
        fall = base.value - cand.value
        gap = (cand.t - base.t) > GAP_S
        slot, _c, conf = match_slot(fall, cand.ranks, self.costs, cand.rtype,
                                    floor=gap)
        return {
            "t": round(cand.t, 3),
            "slot_guess": slot,
            "cost": round(fall, 2),
            "confidence": conf,
            "span": (round(base.t, 3), round(cand.t, 3)) if gap else None,
        }

    def feed(self, r: Reading) -> List[Dict[str, Any]]:
        if not is_tracked_resource(r.rtype):
            self.excluded_reason = f"resource type {r.rtype!r} is not MANA/ENERGY"
            self.reset()
            return []
        self.excluded_reason = None
        base = self._base
        if base is None or base.rtype != r.rtype or r.t < base.t:
            # First reading, resource swap, or game time ran backwards (new
            # game): rebase without emitting.
            self.reset()
            self._base = r
            return []
        last = self._cand or base
        if r.t <= last.t:
            return []  # same frame handed to a second poll; not a new reading
        out: List[Dict[str, Any]] = []
        if self._cand is not None:
            cand = self._cand
            self._cand = None
            held_value = r.value - (r.maximum - cand.maximum)
            if base.value - held_value >= FALL_THRESHOLD:
                out.append(self._emit(base, cand))
                base = cand
                self._base = cand
            else:
                self._base = r  # reverted
                return out
        if r.maximum != base.maximum:
            self._base = r  # level-up / item / form: never a cast
            return out
        if base.value - r.value >= FALL_THRESHOLD:
            self._cand = r
        else:
            self._base = r
        return out


def detect_from_frames(frames: Iterable[Any], costs: CostTable
                       ) -> List[Dict[str, Any]]:
    """Offline: run the detector over a sequence of /allgamedata dicts (for
    example the frames of an X-05 session recording). Unparseable frames are
    skipped."""
    det = SelfCastDetector(costs)
    out: List[Dict[str, Any]] = []
    for fr in frames:
        r = reading_from_allgamedata(fr)
        if r is not None:
            out.extend(det.feed(r))
    return out


# -- DS cost data ------------------------------------------------------------

_COST_CACHE: Dict[str, Dict[str, CostTable]] = {}
_COST_LOCK = threading.Lock()


# current.txt names ONE directory under the DS data root ("16.21.1"), so
# "../x", "a/b" or "." is refused instead of read outside the root.
_PATCH_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")


def _current_patch(root: Path) -> Optional[str]:
    try:
        patch = (root / "current.txt").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if not _PATCH_RE.fullmatch(patch) or ".." in patch:
        return None
    return patch


def _per_rank_costs(cost: Any) -> Optional[Tuple[float, ...]]:
    """Per-rank costs, POSITIONAL: a junk entry is 0.0 (no usable cost at
    that rank) instead of being dropped, which shifted every later rank down
    one place."""
    if not isinstance(cost, list):
        return None
    out = []
    for x in cost:
        f = _num(x)
        out.append(f if f is not None and f > 0 else 0.0)
    return tuple(out) if any(c > 0 for c in out) else None


def _load_all_costs(root: Path, patch: str) -> Dict[str, CostTable]:
    path = root / patch / "champion_abilities.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return {}
    out: Dict[str, CostTable] = {}
    for champ, kit in data.items():
        if not isinstance(kit, dict):
            continue
        table: CostTable = {}
        for slot in SLOTS:
            forms = kit.get(slot)
            if not isinstance(forms, list) or not forms:
                continue
            f0 = forms[0] if isinstance(forms[0], dict) else {}
            res = f0.get("resource")
            table[slot] = (res if isinstance(res, str) else None,
                           _per_rank_costs(f0.get("cost")))
        out[champ] = table
    return out


def load_cost_table(champion_id: str, data_root: Optional[Path] = None
                    ) -> CostTable:
    """slot -> (resource, per-rank costs) for a DDragon champion id, from the
    current DS patch. Uses form 0 of each slot. {} if unknown/unavailable.

    Only a load that produced champions is cached: a read that failed (the
    file mid-rewrite, a truncated JSON) is retried on the next call instead of
    leaving every champion costless for the life of the process."""
    root = data_root or _DS_DATA_ROOT
    patch = _current_patch(root)
    if not patch or not isinstance(champion_id, str) or not champion_id:
        return {}
    key = str(root) + "|" + patch
    with _COST_LOCK:
        tables = _COST_CACHE.get(key)
        if tables is None:
            tables = _load_all_costs(root, patch)
            if tables:
                _COST_CACHE[key] = tables
        return dict(tables.get(champion_id, {}))


def _canonical_id(name: str) -> str:
    try:
        from core.archetype_picks import canonical_champion_id
        return canonical_champion_id(name) or name
    except Exception:  # noqa: BLE001
        return name


# -- live wiring (default OFF) -----------------------------------------------

_state_lock = threading.Lock()
_detector: Optional[SelfCastDetector] = None
_champion: Optional[str] = None
# Game time of the last cost-table load for the live detector, and the
# minimum game-time spacing between retries while that detector is costless.
_cost_try_t: Optional[float] = None
COST_RETRY_S = 30.0
_events: deque = deque(maxlen=_EVENTS_MAX)
_LISTENER_INSTALLED = False


def on_snapshot(snap: object) -> int:
    """liveclient_cache listener. Returns the number of events emitted.
    Fail-soft: anything unexpected returns 0.

    A frame whose champion lookup fails (champ None) keeps the current
    detector: swapping in an empty-cost one dropped the pending candidate and
    its baseline on one bad frame. The cost table (a multi-MB JSON on the
    first call) is read outside _state_lock so events() / reset() never wait
    on it. A detector left costless by a failed load retries the load at most
    once per COST_RETRY_S of game time instead of staying costless until the
    champion changes."""
    global _detector, _champion, _cost_try_t
    try:
        data = getattr(snap, "data", None)
        if not isinstance(data, dict):
            return 0
        r = reading_from_allgamedata(data)
        if r is None:
            return 0
        champ = active_champion_name(data)
        with _state_lock:
            need = _detector is None or (champ is not None
                                         and champ != _champion)
            retry = (not need and champ is not None and _detector is not None
                     and not _detector.costs
                     and (_cost_try_t is None or r.t < _cost_try_t
                          or r.t - _cost_try_t >= COST_RETRY_S))
        costs: CostTable = {}
        if (need or retry) and champ:
            cid = _canonical_id(champ)
            costs = load_cost_table(cid) if cid else {}
        with _state_lock:
            if _detector is None or (champ is not None
                                     and champ != _champion):
                if not need:
                    return 0  # reset() ran between the locks; rebuild next
                _detector = SelfCastDetector(costs)
                _champion = champ
                _cost_try_t = r.t
            elif retry and champ == _champion and not _detector.costs:
                # A costless detector (the load failed) picks the table up
                # in place, keeping its baseline and candidate.
                _cost_try_t = r.t
                _detector.costs = dict(costs)
            new = _detector.feed(r)
            _events.extend(new)
        return len(new)
    except Exception as exc:  # noqa: BLE001
        _log.debug("self_cast_log listener: %s", exc)
        return 0


def events() -> List[Dict[str, Any]]:
    """A copy of the log: each record is a new dict, so a consumer that
    mutates one never rewrites the stored event."""
    with _state_lock:
        return [dict(e) for e in _events]


def reset() -> None:
    global _detector, _champion, _cost_try_t
    with _state_lock:
        _detector = None
        _champion = None
        _cost_try_t = None
        _events.clear()


def install_if_enabled() -> bool:
    """Register on_snapshot on liveclient_cache when RC_SELF_CAST_LOG is
    truthy. Idempotent and fail-soft; True only on the installing call."""
    global _LISTENER_INSTALLED
    if _LISTENER_INSTALLED or not is_enabled():
        return False
    try:
        from core import liveclient_cache
        liveclient_cache.add_listener(on_snapshot)
    except Exception as exc:  # noqa: BLE001
        _log.debug("self_cast_log install failed: %s", exc)
        return False
    _LISTENER_INSTALLED = True
    _log.info("self_cast_log listener installed (%s)", FLAG_ENV)
    return True


# -- offline validation vs Match-V5 ------------------------------------------

def per_slot_totals(evs: Iterable[Mapping[str, Any]],
                    min_confidence: float = 0.0) -> Dict[str, int]:
    """Per-slot event counts. A non-mapping entry is not an event and is
    skipped; a confidence that is not a finite number reads 0.0 (so a NaN no
    longer passes every min_confidence); a junk min_confidence is 0.0; a
    slot_guess outside Q/W/E/R is unattributed."""
    out = {s: 0 for s in SLOTS}
    out["unattributed"] = 0
    floor = _num(min_confidence)
    floor = 0.0 if floor is None else floor
    for e in evs:
        if not isinstance(e, Mapping):
            continue
        conf = _num(e.get("confidence"))
        if (0.0 if conf is None else conf) < floor:
            continue
        s = e.get("slot_guess")
        if s in SLOTS:  # tuple membership: an unhashable guess cannot raise
            out[s] += 1
        else:
            out["unattributed"] += 1
    return out


def match_tolerance(truth: int) -> int:
    """Allowed |log - truth| per slot. Our own postulate; see constants."""
    return max(MATCH_ABS_TOL, int(round(MATCH_REL_TOL * max(0, int(truth)))))


# Match-V5 participant fields; `parse_participant` in scripts/rewind_scraper.py
# stores them in rewind_history.db participants as spell1_casts..spell4_casts.
_TRUTH_KEYS = {
    "Q": ("spell1_casts", "spell1Casts"),
    "W": ("spell2_casts", "spell2Casts"),
    "E": ("spell3_casts", "spell3Casts"),
    "R": ("spell4_casts", "spell4Casts"),
}


def _as_row(participant: Any) -> Dict[str, Any]:
    if isinstance(participant, Mapping):
        return dict(participant)
    keys = getattr(participant, "keys", None)
    if not callable(keys):
        return {}
    try:
        return {k: participant[k] for k in keys()}
    except (TypeError, KeyError, IndexError):
        return {}


def _observable(entry: Any) -> bool:
    if not isinstance(entry, (tuple, list)) or len(entry) != 2:
        return False
    res, cst = entry
    if not is_tracked_resource(res) or not isinstance(cst, (tuple, list)):
        return False
    return any((_num(x) or 0.0) > 0 for x in cst)


def validate_against_match_v5(evs: Iterable[Mapping[str, Any]],
                              participant: Mapping[str, Any],
                              costs: CostTable,
                              min_confidence: float = 0.0) -> Dict[str, Any]:
    """Compare per-slot log totals with Match-V5 spellNCasts.

    Slots whose DS data has no MANA/ENERGY cost are not observable from the
    resource bar and are reported compared=False. pass is True only when at
    least one slot was compared and every compared slot is within
    match_tolerance(truth).

    participant is a Mapping or a sqlite3.Row (anything with keys() and
    item access). A truth that is not an integral count in 0..10**5 is no
    truth (12.7 was truncated to 12, -3 was compared). A cost entry that is
    not a (resource, per-rank costs) pair with a positive finite cost is not
    observable.
    """
    totals = per_slot_totals(evs, min_confidence=min_confidence)
    row = _as_row(participant)
    table = costs if isinstance(costs, Mapping) else {}
    slots: Dict[str, Any] = {}
    compared = 0
    ok = True
    for slot in SLOTS:
        truth = None
        for k in _TRUTH_KEYS[slot]:
            truth = _count(row.get(k), _COUNT_MAX)
            if truth is not None:
                break
        log_n = totals[slot]
        observable = _observable(table.get(slot))
        if truth is None or not observable:
            slots[slot] = {"log": log_n, "truth": truth, "diff": None,
                           "allowed": None, "within": None, "compared": False}
            continue
        allowed = match_tolerance(truth)
        diff = log_n - truth
        within = abs(diff) <= allowed
        slots[slot] = {"log": log_n, "truth": truth, "diff": diff,
                       "allowed": allowed, "within": within, "compared": True}
        compared += 1
        ok = ok and within
    return {"pass": bool(ok and compared > 0), "slots": slots,
            "unattributed": totals["unattributed"]}
