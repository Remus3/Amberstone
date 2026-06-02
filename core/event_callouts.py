# arch: deterministic event-milestone callout table | section=core | frozen=no
"""Deterministic event-milestone callout DB (no LLM, no network, no engine).

PURPOSE
    Precomputed objective / spike timing callouts so live coaching can
    surface "next drake 5:00 / your lvl-6 spike / 3-item powerspike /
    baron 20:00" WITHOUT a Claude Haiku call. Pure: every output is a
    function of (mode, game_time_s, level, item_count).

WHY a static table and not the live timer
    RC already reads live objective timers (`obj_timers_dict`) from the
    LiveClient API. This module is the *schedule* a coach reads to
    pre-warn the operator BEFORE the live timer ticks (e.g. "drake spawns
    5:00 - set up vision" surfaced at 4:30) and to flag level/item
    powerspikes the live timer feed does not carry at all. The two are
    complementary: live timer = ground truth once a thing exists; this
    table = the deterministic schedule + spike windows.

TIMING SOURCES (Summoner's Rift, current-patch canonical LoL values)
    These are long-stable map constants, not balance-churn numbers:
      - First dragon spawn ......... 5:00 (300s)
      - Dragon respawn cadence ..... 5:00 (300s) after a take
      - Rift Herald spawn .......... 14:00 (840s)
      - Baron Nashor spawn ......... 20:00 (1200s)
      - Turret plating falls ....... 14:00 (840s)
      - Elder Dragon (earliest) .... ~35:00 (2100s, soul-gated; we use
                                     a nominal late marker)
    Cited from canonical LoL map mechanics (League of Legends Wiki
    "Epic monster" / "Turret" pages; values stable across seasons for
    the listed objectives). The repo carried NO prior spawn-time
    constant (grep at author time found only DS damage numbers), so
    these are the canonical values, not a reuse.

    ARAM (Howling Abyss) has NO neutral objectives - the ARAM coach
    prompt itself states "No dragon/baron/rift herald - only towers and
    Nexus matter" (coaches/aram_coach.py). So the ARAM milestone set is
    spike levels + first-item only; map objectives are SR-only.

    Arena (CHERRY) is round-based with no map objectives - spike levels
    + item spikes only.

CHAMPION SPIKES (mode-agnostic, level- and item-driven)
      - Level 6 .... ult unlocked (first all-in spike)
      - Level 11 ... ult rank 2 + most kits online
      - Level 16 ... ult rank 3 (max ult)
      - 1 item ..... first completed item (mythic-equivalent spike)
      - 2 item ..... two-item spike
      - 3 item ..... three-item spike (peak mid-game)
"""
from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Canonical Summoner's Rift objective schedule (seconds). SR-only.
# Each entry: tag -> (spawn_s, line, cadence_s_or_None).
# cadence_s set => the objective respawns on that cadence after spawn_s
# (used so a single drake "tag" keeps producing the *next* drake ETA as
# the game runs long). cadence None => one-shot (herald, baron, elder,
# plates).
# ---------------------------------------------------------------------------
_SR_FIRST_DRAGON_S = 300.0     # 5:00
_SR_DRAGON_CADENCE_S = 300.0   # 5:00 respawn cadence
_SR_RIFT_HERALD_S = 840.0      # 14:00
_SR_BARON_S = 1200.0           # 20:00
_SR_PLATES_FALL_S = 840.0      # 14:00 (turret plating gone)
_SR_ELDER_NOMINAL_S = 2100.0   # ~35:00 nominal late marker

_SR_OBJECTIVES: tuple[tuple[str, float, str, Optional[float]], ...] = (
    ("dragon",  _SR_FIRST_DRAGON_S, "Drake spawns 5:00 - set up vision", _SR_DRAGON_CADENCE_S),
    ("herald",  _SR_RIFT_HERALD_S,  "Rift Herald 14:00 - ward river",    None),
    ("plates",  _SR_PLATES_FALL_S,  "Plates fall 14:00 - shove for gold", None),
    ("baron",   _SR_BARON_S,        "Baron up 20:00 - ward river",       None),
    ("elder",   _SR_ELDER_NOMINAL_S, "Elder Dragon late - group for it",  None),
)

# ---------------------------------------------------------------------------
# Champion power spikes (mode-agnostic). Level + item driven.
# ---------------------------------------------------------------------------
_SPIKE_LEVELS: tuple[int, ...] = (6, 11, 16)
_SPIKE_LEVEL_LINES: dict[int, str] = {
    6:  "Your lvl-6 spike - look for all-in",
    11: "Your lvl-11 spike - ult rank 2",
    16: "Your lvl-16 spike - max ult power",
}

_SPIKE_ITEMS: tuple[int, ...] = (1, 2, 3)
_SPIKE_ITEM_LINES: dict[int, str] = {
    1: "1-item spike - fight on cooldowns up",
    2: "2-item spike - force fights now",
    3: "3-item spike - your peak mid-game",
}

# Recall-affordability: a back-timing callout fires only when current gold has
# reached the cost of the NEXT item in the build order. gold >= cost is a hard
# fact (not a prediction), so this is a correct-by-construction directive - the
# next item + its cost are passed in by the caller (which reads the precomputed
# build-order tables + item catalog), keeping this module pure.
_RECALL_KIND = "recall"

# Modes that have neutral map objectives. Only Summoner's Rift.
_OBJECTIVE_MODES: frozenset[str] = frozenset({"sr"})

# Modes this table understands at all. Unknown -> [] (fail-soft).
_KNOWN_MODES: frozenset[str] = frozenset({"sr", "aram", "arena"})


def _norm_mode(mode: object) -> str:
    """Lowercase a mode string; non-str -> empty (fail-soft)."""
    if not isinstance(mode, str):
        return ""
    return mode.strip().lower()


def milestone_line(tag: object) -> str:
    """Return the short human line for a milestone tag.

    Accepts an objective tag (dragon/herald/baron/plates/elder), a
    level-spike tag ("lvl6"/"lvl11"/"lvl16"), or an item-spike tag
    ("item1"/"item2"/"item3"). Unknown tag -> "" (never raises).
    """
    if not isinstance(tag, str):
        return ""
    t = tag.strip().lower()
    for otag, _spawn, line, _cad in _SR_OBJECTIVES:
        if otag == t:
            return line
    if t.startswith("lvl"):
        try:
            lv = int(t[3:])
        except ValueError:
            return ""
        return _SPIKE_LEVEL_LINES.get(lv, "")
    if t.startswith("item"):
        try:
            n = int(t[4:])
        except ValueError:
            return ""
        return _SPIKE_ITEM_LINES.get(n, "")
    return ""


def _objective_callouts(game_time_s: float) -> list[dict]:
    """Build SR neutral-objective callouts at the given game time.

    For cadence objectives (dragon) returns the next spawn ETA, or an
    active callout (eta_s <= 0) within a short window after a spawn so a
    coach can say "drake UP now". One-shot objectives (herald/baron/
    plates/elder) return their single ETA, or active once reached.
    """
    out: list[dict] = []
    # Window (seconds) after a spawn during which we still surface it as
    # "active" so the coach can call the contest, not just the pre-warn.
    active_window = 30.0
    for tag, spawn_s, _line, cadence_s in _SR_OBJECTIVES:
        line = milestone_line(tag)
        if cadence_s and cadence_s > 0:
            if game_time_s < spawn_s:
                eta = spawn_s - game_time_s
            else:
                # Next cadence boundary at/after now.
                elapsed_since_first = game_time_s - spawn_s
                n_passed = int(elapsed_since_first // cadence_s)
                next_spawn = spawn_s + (n_passed + 1) * cadence_s
                # If we just crossed a spawn within the active window,
                # surface it as active (eta_s <= 0) instead of the next one.
                last_spawn = spawn_s + n_passed * cadence_s
                if (game_time_s - last_spawn) <= active_window:
                    out.append({
                        "tag": tag,
                        "line": _active_line(tag, line),
                        "eta_s": round(last_spawn - game_time_s, 1),  # <= 0
                        "kind": "objective",
                    })
                    continue
                eta = next_spawn - game_time_s
            out.append({
                "tag": tag,
                "line": line,
                "eta_s": round(eta, 1),
                "kind": "objective",
            })
        else:
            eta = spawn_s - game_time_s
            if -active_window <= eta <= 0:
                out.append({
                    "tag": tag,
                    "line": _active_line(tag, line),
                    "eta_s": round(eta, 1),
                    "kind": "objective",
                })
            elif eta > 0:
                out.append({
                    "tag": tag,
                    "line": line,
                    "eta_s": round(eta, 1),
                    "kind": "objective",
                })
            # eta < -active_window: the one-shot is long past; drop it
            # (e.g. plates at 14:00 are irrelevant at 30:00).
    return out


def _active_line(tag: str, fallback: str) -> str:
    """Short 'this is up NOW' variant of an objective line (<= 8 words)."""
    active = {
        "dragon": "Drake UP now - contest or trade",
        "herald": "Herald UP now - take it",
        "baron":  "Baron UP now - contest with vision",
        "plates": "Plates gone now - group mid",
        "elder":  "Elder UP now - group for it",
    }
    return active.get(tag, fallback)


def _level_spike_callouts(level: int) -> list[dict]:
    """Build champion level-spike callouts.

    If the champion is AT a spike level -> active callout (eta_s 0).
    Otherwise surface the next spike level with eta_s None (time-to-level
    is not deterministic from inputs). Spike levels already passed (and
    not the current level) are dropped.
    """
    out: list[dict] = []
    for lv in _SPIKE_LEVELS:
        if level == lv:
            out.append({
                "tag": f"lvl{lv}",
                "line": _SPIKE_LEVEL_LINES[lv],
                "eta_s": 0.0,
                "kind": "level_spike",
            })
        elif level < lv:
            away = lv - level
            word = "level" if away == 1 else "levels"
            out.append({
                "tag": f"lvl{lv}",
                "line": f"Next spike lvl-{lv} ({away} {word} away)",
                "eta_s": None,
                "kind": "level_spike",
            })
        # level > lv and level != lv: spike passed, drop.
    return out


def _item_spike_callouts(item_count: int) -> list[dict]:
    """Build item-powerspike callouts.

    AT a spike item count -> active callout (eta_s 0). Below a spike
    count -> next item-spike with eta_s None (item timing depends on
    gold income, not deterministic from inputs). Passed counts drop.
    """
    out: list[dict] = []
    for n in _SPIKE_ITEMS:
        if item_count == n:
            out.append({
                "tag": f"item{n}",
                "line": _SPIKE_ITEM_LINES[n],
                "eta_s": 0.0,
                "kind": "item_spike",
            })
        elif item_count < n:
            away = n - item_count
            word = "item" if away == 1 else "items"
            out.append({
                "tag": f"item{n}",
                "line": f"Next spike {n}-item ({away} {word} away)",
                "eta_s": None,
                "kind": "item_spike",
            })
        # item_count > n: passed, drop.
    return out


def recall_callout(
    gold: object,
    next_item_name: object,
    next_item_cost: object,
) -> Optional[dict]:
    """Return a 'back now' callout when current gold can complete the next item.

    Pure + fail-soft. Returns the active recall callout dict only when gold is at
    or above the next item's cost (the affordable, actionable case); otherwise
    None - a not-yet-affordable state is the lead-projection's "farm" read, not a
    recall directive. Any non-numeric / missing / non-positive input -> None
    (never raises).
    """
    if not isinstance(next_item_name, str) or not next_item_name.strip():
        return None
    if isinstance(gold, bool) or isinstance(next_item_cost, bool):
        return None
    if not isinstance(gold, (int, float)) or not isinstance(next_item_cost, (int, float)):
        return None
    if next_item_cost <= 0:
        return None
    if gold < next_item_cost:
        return None
    return {
        "tag": _RECALL_KIND,
        "line": f"Back now - afford {next_item_name.strip()}",
        "eta_s": 0.0,
        "kind": _RECALL_KIND,
    }


def _sort_key(c: dict) -> tuple[int, float]:
    """Sort callouts active-first, then by ascending ETA, None last.

    Returns (bucket, eta) where bucket 0 = active (eta_s <= 0), 1 =
    upcoming with a numeric eta, 2 = unknown eta (None). Within bucket 1
    sort by ascending eta. None etas sort to the very end deterministically.
    """
    eta = c.get("eta_s")
    if eta is None:
        return (2, 0.0)
    if eta <= 0:
        # Active. Sort most-recently-active (eta closest to 0 from below)
        # first by using -eta so eta=0 beats eta=-25.
        return (0, -eta)
    return (1, float(eta))


def next_callouts(
    mode: str,
    game_time_s: float,
    level: int,
    item_count: int,
    *,
    max_n: int = 3,
    gold: object = None,
    next_item_name: object = None,
    next_item_cost: object = None,
) -> list[dict]:
    """Return up to ``max_n`` upcoming/active milestone callouts.

    Deterministic from inputs - no network, no LLM, no engine call.

    Args:
        mode: dashboard mode_key (sr / aram / arena). Unknown -> [].
        game_time_s: in-game clock in seconds.
        level: champion level (1-18).
        item_count: number of completed items owned (len(items)).
        max_n: cap on returned list length.
        gold: current gold on-hand (for the recall-affordability callout).
        next_item_name: display name of the next item in the build order.
        next_item_cost: total gold cost of that next item. When gold, name and
            cost are all present and gold >= cost, an active "back now" recall
            callout is emitted (correct-by-construction; see recall_callout).

    Returns:
        list of dicts ``{tag, line, eta_s, kind}`` where:
          - kind in {objective, level_spike, item_spike, recall}
          - eta_s is seconds-to-event; <= 0 means active/just-happened;
            None means the ETA is not deterministic (level/item spikes).
        Sorted active-first, then ascending ETA, None-ETA last.
        Neutral-objective callouts are SR-only; ARAM and Arena return
        spike callouts only.
    """
    m = _norm_mode(mode)
    if m not in _KNOWN_MODES:
        return []

    try:
        gt = float(game_time_s)
    except (TypeError, ValueError):
        gt = 0.0
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 1
    try:
        items = int(item_count)
    except (TypeError, ValueError):
        items = 0

    callouts: list[dict] = []
    if m in _OBJECTIVE_MODES:
        callouts.extend(_objective_callouts(gt))
    callouts.extend(_level_spike_callouts(lvl))
    callouts.extend(_item_spike_callouts(items))

    recall = recall_callout(gold, next_item_name, next_item_cost)
    if recall is not None:
        callouts.append(recall)

    callouts.sort(key=_sort_key)

    if max_n is not None and max_n >= 0:
        return callouts[:max_n]
    return callouts
