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
* Wire input is untrusted (s144 true-audit): a rank outside 0.._MAX_RANK, a
  level outside 1.._MAX_LEVEL, a str that is not plain ASCII digits, a
  malformed hand-built ``SkillReading``, or a clock that is not an int /
  float within +-_MAX_GAME_TIME_S (bool, str, NaN, inf, a long int, 1e300)
  is "no reading" - nothing
  transitions, nothing fires, nothing raises. A non-str champion is unknown,
  and an unknown champion on one tick keeps the kit already stored in the
  state rather than flipping to the standard kit.

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

# Plausibility bounds, not game rules: the highest real kit cap is 6 (Udyr,
# Jayce) and a standard level cap is 18, with headroom for a mode that
# levels past it. Anything beyond is junk, never a 300-digit rank echoed into
# /api/state ``ability_ranks`` (dashboard/_liveclient.py).
_MAX_RANK = 10
_MAX_LEVEL = 100
# A real game clock is under two hours; 10**6 s (11.5 days) is junk, never a
# 301-digit "unspent for ...s" callout line.
_MAX_GAME_TIME_S = 1e6


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


def _champ(champion) -> str:
    """The champion name, or "" (unknown) for anything that is not a str."""
    return champion if isinstance(champion, str) else ""


def kit_rules(champion) -> KitRules:
    """Rules for ``champion`` (Live Client championName / Match-V5
    championName); unknown, empty or not a str -> the standard kit."""
    key = _champ(champion).replace(" ", "").replace("'", "")
    return SPECIAL_KITS.get(key, STANDARD)


@dataclass(frozen=True)
class SkillReading:
    level: int
    ranks: dict


def _rank_int(v, hi=_MAX_RANK):
    """An int in 0..``hi``, or None. bool is rejected (True is not 1); a
    float must be integral; a str must be plain ASCII digits (int() alone
    also takes "1_0", " 3", "+5" and non-ASCII digits)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str):
        if not (v.isascii() and v.isdigit()) or len(v) > 6:
            return None
        v = int(v)
    elif not isinstance(v, (int, float)):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError, OverflowError):
        return None
    if n != v:
        return None
    return n if 0 <= n <= hi else None


def _game_time(v):
    """A finite float game time within +-_MAX_GAME_TIME_S, or None. Only an
    int or float is a clock: bool, str, NaN, inf and a long int that float()
    overflows are not."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        t = float(v)
    except OverflowError:
        return None
    return t if abs(t) <= _MAX_GAME_TIME_S else None


def _is_int(v, lo, hi) -> bool:
    """A real int (not bool, float or str) in lo..hi."""
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _valid(reading) -> bool:
    """True for a SkillReading whose level and four ranks are ints in range.
    read_skill_snapshot only builds those; a hand-built one can carry a str,
    a float or a missing slot, which the rank arithmetic cannot take."""
    if not isinstance(reading, SkillReading):
        return False
    if not _is_int(reading.level, 1, _MAX_LEVEL):
        return False
    ranks = reading.ranks
    if not isinstance(ranks, dict):
        return False
    return all(_is_int(ranks.get(s), 0, _MAX_RANK) for s in SLOTS)


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
    level = _rank_int(src.get("level"), _MAX_LEVEL)
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
    if not _valid(reading):
        return None
    rules = kit_rules(champion)
    if not rules.supported:
        return None
    free = min(rules.free_r, reading.ranks["r"])
    return reading.level - (sum(reading.ranks[s] for s in SLOTS) - free)


def _slot_cap(rules: KitRules, level: int, slot: str) -> int:
    """Highest rank ``slot`` may hold at ``level``."""
    if slot != "r" or rules.r_is_basic:
        cap = rules.basic_max if slot != "r" else rules.r_max
        return min(cap, (level + 1) // 2)
    return min(rules.r_max, sum(1 for lv in rules.r_levels if level >= lv))


def slot_open(reading: SkillReading, champion, slot: str) -> bool:
    """True when ``slot`` can take one more rank at this level."""
    if slot not in SLOTS or not _valid(reading):
        return False
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
    """Advance one tick. Returns (new_state, events).

    A tick with no champion (or a non-str one) keeps the champion already
    stored in ``state``: it is neither a new game nor a kit change."""
    t = _game_time(now_s)
    if t is None or not _valid(reading):
        return state, []
    champ = _champ(champion) or state.champion
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
    t = _game_time(now_s)
    start = _game_time(state.since[0])
    if t is None or start is None:
        return None
    nag = _game_time(nag_after_s)
    if nag is None or nag < 0:
        nag = NAG_AFTER_S
    held_s = t - start
    if held_s < nag:
        return None
    n = len(state.since)
    noun = "point" if n == 1 else "points"
    return {"tag": "skill_point",
            "line": f"{n} skill {noun} unspent for {int(held_s)}s",
            "eta_s": None, "kind": "skill_point"}
