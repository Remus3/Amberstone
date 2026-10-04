"""RM-603 (external reference F): unspent skill-point tracker (live half).

A PURE step function over consecutive Live Client readings. It holds no
process state of its own: the caller (the RM-604 live event deriver, once it
lands) keeps one ``TrackerState`` per game and feeds every tick through
``step``. Nothing here does I/O.

Model
-----
unspent = level - (sum of the four Q/W/E/R ranks - free ranks)

``spendable`` is ``unspent`` clamped to what the rank rules allow right now:
a point no slot can legally take (every slot capped for this level, or the
kit fully maxed in a mode that levels past 18) never lights. Events fire on
changes of ``spendable``, so a point that cannot be spent is not a nag.

Rules this module enforces (re-implemented from the behaviour text of
external reference F; the rank tables are game rules, stated in our words):

* R ranks only at levels 6 / 11 / 16 for a standard kit.
* A basic ability may reach rank k only at level 2k - 1.
* A capped ability never lights.
* A ``None`` reading (any slot missing, level missing) never transitions
  anything - the state is returned unchanged and no event fires.
* First sight is STATE, not an event: the first complete reading of a game
  seeds the held count silently, even when a point is already held.

Events (dicts, kind-tagged, ASCII):
  {"kind": "skill_point", "t_s", "unspent", "champion"}
  {"kind": "skill_spent", "t_s", "unspent", "held_for", "champion"}
``held_for`` is game-time seconds the spent point sat, FIFO (the oldest held
point is the one spent), so two points spent together each carry their own
hold.

Clock: game time (``gameData.gameTime`` seconds). It is deterministic,
replayable and pause-safe, where wall time is not.

Special kits (fence; see tests/test_skill_point_tracker.py). Probe
2026-10-04 of data/daemon_slayer/16.18.1/champion_abilities.json, per-rank
cooldown array lengths: Udyr Q/W/E/R = 6/6/6/6, Jayce Q/W/E = 6, Elise Q/W/E
= 5, Karma R = 4, Annie = 5/5/5/3 - those agree with the table below. The DS
arrays are NOT rank-shaped for form-swap ults (Jayce R = 6 constant entries,
Elise R = 3, Nidalee R = 1), so those R caps are the game-rule value, not DS
data. Match-V5 probe (data/rewind_history.db, same date): the free level-1 R
rank of Jayce / Elise / Nidalee / Karma emits NO SKILL_LEVEL_UP (NORMAL
skill-ups == final level), confirming it is not paid with a point; Aphelios
logs MORE skill-ups than levels (+2 seen), so his ranks are not level points
and he is fenced out entirely. LIVE-GATED: that the Live Client reports the
free R rank as abilityLevel 1 at level 1 is unverified on a real frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SLOTS = ("q", "w", "e", "r")

# Our own value, measured 2026-10-04 over data/rewind_history.db (Match-V5
# LEVEL_UP -> SKILL_LEVEL_UP FIFO pairs, starting points excluded): Summoner's
# Rift n=84200 median 1.6 s, p90 7.3 s, p95 12.1 s; ARAM n=315503 median 2.3 s,
# p90 16.6 s. 15 s sits above the SR p95, so about 19 in 20 real Rift spends
# never toast and the toast marks a genuine outlier hold.
NAG_AFTER_S = 15.0


@dataclass(frozen=True)
class KitRules:
    """Rank caps for one kit. Defaults are the standard kit."""

    basic_max: int = 5
    r_max: int = 3
    # Levels at which each R rank unlocks (rank k needs r_levels[k-1]).
    r_levels: tuple = (6, 11, 16)
    # R ranks granted at level 1 without spending a point.
    free_r: int = 0
    # True when R follows the basic half-level rule (no 6/11/16 gate).
    r_is_basic: bool = False
    # False = this kit's ranks are not level points; never nag.
    supported: bool = True


STANDARD = KitRules()

_FREE_R_KIT = KitRules(r_max=4, r_levels=(1, 6, 11, 16), free_r=1)

SPECIAL_KITS = {
    # Four basic-like abilities, each 6 ranks, R rankable from level 1.
    "Udyr": KitRules(basic_max=6, r_max=6, r_is_basic=True),
    # Transform ult: R rank 1 free at level 1 and it NEVER ranks further;
    # the points go to basics, which rank to 6 (3 x 6 = 18 points).
    "Jayce": KitRules(basic_max=6, r_max=1, r_levels=(1,), free_r=1),
    "Elise": _FREE_R_KIT,
    "Nidalee": _FREE_R_KIT,
    "Karma": _FREE_R_KIT,
    # No normal ability ranks (level points buy stats, not ranks).
    "Aphelios": KitRules(supported=False),
}


def kit_rules(champion) -> KitRules:
    """Rules for ``champion`` (Live Client championName / Match-V5
    championName); unknown or empty -> the standard kit."""
    key = str(champion or "").replace(" ", "").replace("'", "")
    return SPECIAL_KITS.get(key, STANDARD)


@dataclass(frozen=True)
class SkillReading:
    level: int
    ranks: dict


def _rank_int(v):
    """A non-negative int rank, or None. bool is rejected (True is not 1)."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError, OverflowError):
        return None
    if n != v and not isinstance(v, str):
        return None
    return n if n >= 0 else None


def _slot_rank(container, slot):
    """Rank of ``slot`` from any of the three shapes. Key PRESENCE decides,
    so a real 0 stays 0 (a falsy-or fallback would turn it into None)."""
    if not isinstance(container, dict):
        return None
    entry = container.get(slot)
    if entry is None:
        entry = container.get(slot.upper())
    if isinstance(entry, dict):
        for key in ("abilityLevel", "level"):
            if key in entry:
                return _rank_int(entry[key])
        return None
    return _rank_int(entry)


def read_skill_snapshot(src) -> SkillReading | None:
    """One reading from any of:

    * the normalizer state (game_reader/snapshot_normalizer.py
      ``my_abilities``: {q: {name, level}}),
    * the raw :2999 ``activePlayer`` ({level, abilities: {Q: {abilityLevel}}}),
    * the dashboard liveclient summary ({level, ability_ranks: {q: int}}).

    Returns None when the level or ANY of Q/W/E/R is missing or malformed.
    """
    if not isinstance(src, dict):
        return None
    level = _rank_int(src.get("level"))
    if level is None or level < 1:
        return None
    container = None
    for key in ("ability_ranks", "my_abilities", "abilities"):
        if isinstance(src.get(key), dict):
            container = src[key]
            break
    if container is None:
        return None
    ranks = {}
    for slot in SLOTS:
        r = _slot_rank(container, slot)
        if r is None:
            return None
        ranks[slot] = r
    return SkillReading(level=level, ranks=ranks)


def unspent(reading: SkillReading | None, champion) -> int | None:
    """Level points not yet placed. None for a fenced kit or no reading.
    May be negative on an inconsistent frame; callers clamp."""
    if reading is None:
        return None
    rules = kit_rules(champion)
    if not rules.supported:
        return None
    free = min(rules.free_r, reading.ranks["r"])
    return reading.level - (sum(reading.ranks.values()) - free)


def _slot_cap(rules: KitRules, level: int, slot: str) -> int:
    """Highest rank ``slot`` may hold at ``level``."""
    if slot != "r" or rules.r_is_basic:
        cap = rules.basic_max if slot != "r" else rules.r_max
        return min(cap, (level + 1) // 2)
    return min(rules.r_max, sum(1 for lv in rules.r_levels if level >= lv))


def slot_open(reading: SkillReading, champion, slot: str) -> bool:
    """True when ``slot`` can take one more rank at this level."""
    rules = kit_rules(champion)
    if not rules.supported:
        return False
    return reading.ranks[slot] < _slot_cap(rules, reading.level, slot)


def spendable(reading: SkillReading | None, champion) -> int:
    """Points that can actually be placed now: unspent clamped to the open
    room across all slots. 0 for a fenced kit or no reading."""
    n = unspent(reading, champion)
    if not n or n <= 0:
        return 0
    rules = kit_rules(champion)
    room = sum(max(0, _slot_cap(rules, reading.level, s) - reading.ranks[s])
               for s in SLOTS)
    return min(n, room)


@dataclass(frozen=True)
class TrackerState:
    """Carried between ticks by the caller. ``since`` holds one game-time
    stamp per currently held spendable point, oldest first."""

    seen: bool = False
    level: int = 0
    since: tuple = field(default_factory=tuple)
    champion: str = ""


def step(state: TrackerState, reading: SkillReading | None, now_s,
         champion) -> tuple:
    """Advance one tick. Returns (new_state, events)."""
    try:
        t = float(now_s)
    except (TypeError, ValueError):
        return state, []
    if reading is None:
        return state, []
    champ = str(champion or "")
    n = spendable(reading, champ)
    new_game = (not state.seen or reading.level < state.level
                or (state.champion and champ and champ != state.champion))
    if new_game:
        # First sight is state, not an event.
        return TrackerState(seen=True, level=reading.level,
                            since=tuple([t] * n), champion=champ), []
    held = list(state.since)
    events = []
    while len(held) < n:
        held.append(t)
        events.append({"kind": "skill_point", "t_s": t, "unspent": len(held),
                       "champion": champ})
    while len(held) > n:
        start = held.pop(0)
        events.append({"kind": "skill_spent", "t_s": t, "unspent": len(held),
                       "held_for": round(max(0.0, t - start), 3),
                       "champion": champ})
    return TrackerState(seen=True, level=reading.level, since=tuple(held),
                        champion=champ), events


def skill_point_callout(state: TrackerState, now_s,
                        nag_after_s: float = NAG_AFTER_S) -> dict | None:
    """House callout shape ({tag, line, eta_s, kind}; see
    core/heal_threat.py heal_threat_callout) once the oldest held point has
    sat ``nag_after_s`` game seconds, else None. Descriptive wording.

    NOTE: /api/state ``callouts`` is blanked while a game is live by the B4
    suppression (dashboard/_state_builder.py suppress_live_envelope), so this
    row only renders where B4 allows it; wiring it is not a B4 bypass.
    """
    if not state.since:
        return None
    try:
        t = float(now_s)
    except (TypeError, ValueError):
        return None
    held_s = t - state.since[0]
    if held_s < nag_after_s:
        return None
    n = len(state.since)
    noun = "point" if n == 1 else "points"
    return {"tag": "skill_point",
            "line": f"{n} skill {noun} unspent for {int(held_s)}s",
            "eta_s": None, "kind": "skill_point"}
