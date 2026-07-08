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
# Canonical SR epic-objective spawn schedule (seconds). ONE cited source: the
# served callout path (this module) AND the vision-gated contest detector
# (core.decision_detector imports these) read the SAME constants so the two can
# never drift. Stable LoL Summoner's Rift map constants.
SR_DRAGON_FIRST_S = 300.0      # 5:00 first drake
SR_DRAGON_RESPAWN_S = 300.0    # 5:00 after a take
SR_BARON_FIRST_S = 1200.0      # 20:00 first Baron
SR_BARON_RESPAWN_S = 360.0     # 6:00 after a take

# Back-compat aliases used by the static schedule table below.
_SR_FIRST_DRAGON_S = SR_DRAGON_FIRST_S
_SR_DRAGON_CADENCE_S = SR_DRAGON_RESPAWN_S
_SR_RIFT_HERALD_S = 840.0      # 14:00
_SR_BARON_S = SR_BARON_FIRST_S
_SR_PLATES_FALL_S = 840.0      # 14:00 (turret plating gone)
_SR_ELDER_NOMINAL_S = 2100.0   # ~35:00 nominal late marker
_INHIB_RESPAWN_S = 300.0       # 5:00 - inhibitor respawn after it falls

# Epic-monster team-buff durations (seconds). Stable map constants, NOT balance
# churn: Baron Nashor's "Hand of Baron" lasts 180s; Elder Dragon's "Aspect of the
# Dragon" execute buff lasts 150s. Keyed PER objective so each countdown is
# correct-by-construction rather than one averaged window (the research-doc title
# merged both as 180s; the accurate per-monster durations are used here so the
# late-game macro read is exact). Elemental drakes grant no expiring team buff,
# so they are deliberately absent.
_BARON_BUFF_S = 180.0
_ELDER_BUFF_S = 150.0
_EPIC_BUFF_S: dict[str, float] = {"baron": _BARON_BUFF_S, "elder": _ELDER_BUFF_S}

# Per (objective, side) epic-buff directive. The SIDE is the whole value - the
# correct response inverts on who holds the buff - so a side-less buff is dropped
# rather than rendered ambiguously. <= 10 words, ASCII, " - " clause break.
_EPIC_BUFF_LINES: dict[tuple[str, str], str] = {
    ("baron", "ally"):  "Baron buff - take towers and objectives now",
    ("baron", "enemy"): "Enemy baron - defend, do not face-check",
    ("elder", "ally"):  "Elder buff - force the fight now",
    ("elder", "enemy"): "Enemy elder - disengage, avoid the fight",
}

# Live Client inhibitor structure-name lane token -> label. Best-effort: an
# unrecognized name yields no lane, so the callout stays generic and a naming
# convention change can never produce a WRONG lane.
_INHIB_LANE_BY_TOKEN: dict[str, str] = {"L": "top", "C": "mid", "R": "bot"}

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

# Modes that have lane structures (turrets/inhibitors) to siege. SR + ARAM
# (Howling Abyss has a single lane with turrets + an inhibitor); Arena's ring
# has none, so the instant siege callout never fires there.
_SIEGE_MODES: frozenset[str] = frozenset({"sr", "aram"})

# Modes where recalling to fountain is a real mechanic. Only Summoner's Rift
# (ARAM has no recall; Arena has no fountain; Brawl is death-only buy).
_RECALL_MODES: frozenset[str] = frozenset({"sr"})

# A structure that fell within this many seconds is a LIVE siege moment - the
# instant deterministic callout fires so coaching is on-screen immediately,
# bridging the multi-second Haiku coach latency during a base push (the slow
# "base-attack tick" was just inherent Haiku latency; this is the no-LLM bridge).
_SIEGE_RECENCY_S: float = 30.0

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


# Window (seconds) after a spawn during which an objective still surfaces as
# "active" ("UP now") so the coach can call the contest, not just the pre-warn.
_OBJ_ACTIVE_WINDOW_S = 30.0


def _last_kill_t(objective_events: object, *, name: str,
                 elemental_only: bool = False) -> Optional[float]:
    """Latest ``down_at_s`` of a kill of ``name`` in the events list, or None.

    ``elemental_only`` (dragon) excludes the Elder dragon - an Elder take is not
    an elemental-drake respawn anchor (it has its own slower timer + a post-soul
    pit). Fail-soft: bad entries skipped."""
    if not isinstance(objective_events, list):
        return None
    last: Optional[float] = None
    for ev in objective_events:
        if not isinstance(ev, dict) or ev.get("name") != name:
            continue
        if elemental_only and not _is_elemental_drake(ev):
            continue
        try:
            t = float(ev.get("down_at_s"))
        except (TypeError, ValueError):
            continue
        if last is None or t > last:
            last = t
    return last


def _schedule_row(tag: str, next_spawn: float, game_time_s: float) -> dict:
    """One objective row from an absolute next-spawn time: an upcoming ETA when
    the spawn is in the future, else an active 'UP now' row (eta_s <= 0)."""
    eta = next_spawn - game_time_s
    if eta > 0:
        return {"tag": tag, "line": milestone_line(tag),
                "eta_s": round(eta, 1), "kind": "objective"}
    return {"tag": tag, "line": _active_line(tag, milestone_line(tag)),
            "eta_s": round(eta, 1), "kind": "objective"}


def _dynamic_epic_callouts(objective_events: object,
                           game_time_s: float) -> tuple[list[dict], set]:
    """Real-take-driven drake/baron rows + the set of tags they CLAIM.

    Promotes the ``last_kill + respawn`` math (the same shape as
    ``core.decision_detector._next_objective_spawn``) into the served path so a
    drake/baron ETA tracks the actual take instead of the static game-start
    cadence. A claimed tag is skipped by the static schedule. Claims:
      - dragon: when Soul is already secured (>= 4 elemental drakes) the pit
        spawns Elder, so the elemental-drake row is SUPPRESSED (claimed, no
        row). Otherwise, when an elemental drake has been taken, the row keys
        off that take (last elemental kill + 300s).
      - baron: when a Baron has been taken, the row keys off it (last kill +
        360s) - which also gives Baron a real RESPAWN ETA the static one-shot
        schedule never had.
    Objectives with no kill yet are left to the static schedule (unclaimed).
    """
    rows: list[dict] = []
    claimed: set = set()
    if not isinstance(objective_events, list) or not objective_events:
        return rows, claimed

    counts = _elemental_drake_counts(objective_events)
    if max(counts.values()) >= _SOUL_SECURED_STACKS:
        claimed.add("dragon")  # Soul locked; Elder pit, no elemental-drake row
    else:
        last_drake = _last_kill_t(objective_events, name="dragon",
                                  elemental_only=True)
        if last_drake is not None:
            claimed.add("dragon")
            rows.append(_schedule_row(
                "dragon", last_drake + SR_DRAGON_RESPAWN_S, game_time_s))

    last_baron = _last_kill_t(objective_events, name="baron")
    if last_baron is not None:
        claimed.add("baron")
        rows.append(_schedule_row(
            "baron", last_baron + SR_BARON_RESPAWN_S, game_time_s))

    return rows, claimed


def _objective_callouts(game_time_s: float,
                        objective_events: object = None) -> list[dict]:
    """Build SR neutral-objective callouts at the given game time.

    Drake/Baron ETAs track the REAL last take (last_kill + respawn) once a kill
    event is present (see _dynamic_epic_callouts); absent any kill they fall
    back to the static schedule. For cadence objectives (dragon) the static path
    returns the next spawn ETA, or an active callout (eta_s <= 0) within a short
    window after a spawn so a coach can say "drake UP now". One-shot objectives
    (herald/baron/plates/elder) return their single ETA, or active once reached.
    """
    out, claimed = _dynamic_epic_callouts(objective_events, game_time_s)
    # Window (seconds) after a spawn during which we still surface it as
    # "active" so the coach can call the contest, not just the pre-warn.
    active_window = _OBJ_ACTIVE_WINDOW_S
    for tag, spawn_s, _line, cadence_s in _SR_OBJECTIVES:
        if tag in claimed:
            continue  # emitted (or suppressed) with real-take timing above
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


def _inhib_lane(name: object) -> str:
    """Parse the lane from a Live Client inhibitor structure name.

    The Live Client InhibKilled event names the structure like
    ``Barracks_T2_L1`` (team token T1/T2, lane token L1/C1/R1). Returns
    ``top``/``mid``/``bot`` or ``''`` when the name does not match (fail-soft -
    a generic callout is correct, a wrong lane is not).
    """
    if not isinstance(name, str):
        return ""
    for part in name.upper().split("_"):
        if len(part) == 2 and part[0] in _INHIB_LANE_BY_TOKEN and part[1].isdigit():
            return _INHIB_LANE_BY_TOKEN[part[0]]
    return ""


def inhibitor_callouts(inhib_events: object, game_time_s: float) -> list[dict]:
    """Build inhibitor-respawn callouts from InhibKilled events.

    Correct-by-construction: an inhibitor respawns exactly ``_INHIB_RESPAWN_S``
    after it falls, so the respawn ETA is ``(down_at_s + 300) - game_time_s`` -
    a hard fact, not a prediction. Each event is ``{down_at_s: float, name:
    str}`` (name optional; used only to label the lane). Events whose respawn
    has already passed (eta <= 0) are dropped (the inhibitor is back up; a
    later re-kill re-surfaces with a fresh future eta). Team side is
    deliberately NOT claimed - the operator knows which inhibitor fell, the
    value is the respawn timing, and omitting the side means the callout can
    never be backwards. Fail-soft: a non-list / bad entry -> ``[]``.
    """
    if not isinstance(inhib_events, list):
        return []
    try:
        gt = float(game_time_s)
    except (TypeError, ValueError):
        gt = 0.0
    out: list[dict] = []
    for ev in inhib_events:
        if not isinstance(ev, dict):
            continue
        try:
            down_at = float(ev.get("down_at_s"))
        except (TypeError, ValueError):
            continue
        eta = (down_at + _INHIB_RESPAWN_S) - gt
        if eta <= 0:
            continue  # already respawned
        lane = _inhib_lane(ev.get("name"))
        lane_clause = f" ({lane})" if lane else ""
        out.append({
            "tag": f"inhib_{lane or 'lane'}",
            "line": f"Inhib down{lane_clause} - super minions pushing",
            "eta_s": round(eta, 1),
            "kind": "inhibitor",
        })
    return out


def structure_siege_callout(
    turret_events: object,
    inhib_events: object,
    game_time_s: float,
    *,
    recency_s: float = _SIEGE_RECENCY_S,
) -> list[dict]:
    """Active siege callouts for structures that fell within ``recency_s``.

    Pure + fail-soft (no network/LLM). Each turret/inhib event is the Live
    Client ``{down_at_s, name}`` shape dashboard/_liveclient surfaces. A kill
    still inside the recency window yields an ACTIVE (eta_s=0) callout so the
    dashboard/overlay shows it instantly - bridging the multi-second Haiku coach
    latency during a base push. Older kills fade (no callout). An inhibitor
    outranks a turret (appended first; both are active so a stable sort keeps the
    order). Team side is deliberately NOT claimed - a wrong side is worse than
    none, and the operator already sees which structure fell.
    """
    try:
        gt = float(game_time_s)
    except (TypeError, ValueError):
        return []

    def _has_recent(evs: object) -> bool:
        if not isinstance(evs, list):
            return False
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            try:
                d = float(ev.get("down_at_s"))
            except (TypeError, ValueError):
                continue
            if 0.0 <= (gt - d) <= recency_s:
                return True
        return False

    out: list[dict] = []
    if _has_recent(inhib_events):
        out.append({
            "tag": "siege_inhib",
            "line": "Inhibitor down - super minions pushing; group to siege or peel, do not split low",
            "eta_s": 0,
            "kind": "siege",
        })
    if _has_recent(turret_events):
        out.append({
            "tag": "siege_turret",
            "line": "Turret down - space opened; re-ward the flank, do not dive without numbers",
            "eta_s": 0,
            "kind": "siege",
        })
    return out


def _epic_kind(ev: dict) -> Optional[str]:
    """Classify a Baron/Elder buff event -> 'baron' | 'elder' | None.

    Baron is the BaronKill stream (``name == 'baron'``). Elder is a DragonKill
    (``name == 'dragon'``) whose ``dragon_type`` is 'Elder'; the elemental drakes
    grant no expiring team buff, so they are NOT epic-buff events. Keeping the
    elder discriminator on a separate ``dragon_type`` field (rather than renaming
    the event) leaves ``core.macro_response`` - which keys on ``name == 'dragon'``
    - byte-identical. Fail-soft: unrecognized -> None.
    """
    name = ev.get("name")
    if name == "baron":
        return "baron"
    if name == "dragon":
        dt = ev.get("dragon_type")
        if isinstance(dt, str) and dt.strip().lower() == "elder":
            return "elder"
    return None


def epic_buff_callouts(objective_events: object, game_time_s: float) -> list[dict]:
    """Build sided epic-buff-expiry countdowns from Baron/Elder kill events.

    Correct-by-construction: an epic buff expires exactly its fixed duration
    after the objective falls, so remaining = ``(down_at_s + dur) - game_time`` -
    a hard fact, not a prediction. Each event is the
    ``{name, killer_team, down_at_s}`` shape ``dashboard/_liveclient.py`` emits
    (dragon events additionally carry ``dragon_type`` for the Elder
    discriminator). Unlike the inhibitor callout the SIDE is the whole value here
    (the correct response inverts on who holds the buff), so a ``killer_team`` of
    "unknown" is dropped rather than rendered side-less. Expired buffs
    (remaining <= 0) drop - a later re-take re-surfaces with a fresh window.
    Fail-soft: non-list / bad entry -> ``[]`` (never raises).
    """
    if not isinstance(objective_events, list):
        return []
    try:
        gt = float(game_time_s)
    except (TypeError, ValueError):
        gt = 0.0
    out: list[dict] = []
    for ev in objective_events:
        if not isinstance(ev, dict):
            continue
        kind = _epic_kind(ev)
        if kind is None:
            continue
        side = ev.get("killer_team")
        if side not in ("ally", "enemy"):
            continue  # the side IS the value; never render an unsided epic buff
        try:
            down_at = float(ev.get("down_at_s"))
        except (TypeError, ValueError):
            continue
        remaining = (down_at + _EPIC_BUFF_S[kind]) - gt
        if remaining <= 0:
            continue  # buff expired
        out.append({
            "tag": f"{kind}_buff_{side}",
            "line": _EPIC_BUFF_LINES[(kind, side)],
            "eta_s": round(remaining, 1),
            "kind": "epic_buff",
        })
    return out


# A team secures Dragon Soul on its 4th elemental drake, so at EXACTLY 3 the
# next drake IS the soul drake - the single glanceable "force or deny"
# inflection. Elder dragons spawn only AFTER soul and never count toward it.
_SOUL_POINT_STACKS = 3
_SOUL_SECURED_STACKS = 4   # the 4th elemental drake locks Soul; pit -> Elder
_SOUL_POINT_LINES: dict[str, str] = {
    "ally":  "Soul point - next drake is SOUL, force it",
    "enemy": "Enemy soul point - next drake SOUL, deny or disengage",
}

# Soul SECURED (4+ stacks): the soul is live on the map - the highest-priority
# soul read. "{el}" is the locked element (latest elemental drake's type); the
# parenthetical is dropped when the element is unknown.
_SOUL_SECURED_LINES: dict[str, str] = {
    "ally":  "You have SOUL ({el}) - force 5v5 fights",
    "enemy": "Enemy SOUL ({el}) - avoid 5v5, play for picks",
}

# Soul-RACE lead: a side ahead by >= _SOUL_RACE_MIN_LEAD with >= _SOUL_RACE_MIN_
# STACKS drakes and nobody at the point yet. Glanceable race state (ally-enemy
# score), not an inflection. Lower priority than secured / point.
_SOUL_RACE_MIN_LEAD = 1
_SOUL_RACE_MIN_STACKS = 2
_SOUL_RACE_LINES: dict[str, str] = {
    "ally":  "Ahead {a}-{b} on drakes - keep drake priority",
    "enemy": "Behind {a}-{b} on drakes - contest or deny next",
}


def _locked_element(objective_events: object) -> str:
    """Title-cased element of the LATEST elemental drake - the locked map element
    (drakes 3+ are all one type) and thus the Dragon Soul type. '' if unknown."""
    if not isinstance(objective_events, list):
        return ""
    latest_t: Optional[float] = None
    el = ""
    for ev in objective_events:
        if not isinstance(ev, dict) or not _is_elemental_drake(ev):
            continue
        dt = ev.get("dragon_type")
        if not isinstance(dt, str) or not dt.strip():
            continue
        try:
            t = float(ev.get("down_at_s"))
        except (TypeError, ValueError):
            continue
        if latest_t is None or t > latest_t:
            latest_t = t
            el = dt.strip().title()
    return el


def _is_elemental_drake(ev: dict) -> bool:
    """True for a soul-counting elemental drake - a DragonKill that is NOT the
    Elder dragon (Elder spawns post-soul and does not count toward soul)."""
    if ev.get("name") != "dragon":
        return False
    dt = ev.get("dragon_type")
    return not (isinstance(dt, str) and dt.strip().lower() == "elder")


def _elemental_drake_counts(objective_events: object) -> dict:
    """Per-side count of elemental drakes taken (Elder + unknown-killer
    excluded). Shared by the soul-point row and the L3 soul-secured guard."""
    counts = {"ally": 0, "enemy": 0}
    if not isinstance(objective_events, list):
        return counts
    for ev in objective_events:
        if not isinstance(ev, dict) or not _is_elemental_drake(ev):
            continue
        side = ev.get("killer_team")
        if side in counts:
            counts[side] += 1
    return counts


def dragon_soul_callout(objective_events: object) -> Optional[dict]:
    """Return ONE ``kind="dragon_soul"`` soul-point row, or ``None``.

    Counts elemental drakes per side from the ``objective_events`` stream
    ({name, killer_team, down_at_s, dragon_type}) and returns the single
    highest-priority soul read, by a 3-tier cascade (enemy outranks ally within
    a tier - the enemy state is the bigger threat):

      1. SOUL SECURED (>= 4 elemental): the soul is live -> a locked-element
         "they have SOUL (<element>)" row.
      2. SOUL POINT (EXACTLY 3): the next drake grants soul -> the
         correct-by-construction "force or deny" inflection row.
      3. SOUL RACE: a side leads by >= _SOUL_RACE_MIN_LEAD with >=
         _SOUL_RACE_MIN_STACKS drakes (nobody at the point) -> a glanceable
         ally-enemy race-lead row.

    Unresolved-killer ("unknown") drakes are NOT attributed - a conservative
    undercount so the row can never FALSELY claim a point/soul (a missed warning
    beats a wrong one, mirroring the inhibitor/epic-buff side discipline).
    Standing advisory (``eta_s`` None) like the macro/heal rows, so the callouts
    renderer paints it with no web change. Fail-soft: bad input -> None.
    """
    if not isinstance(objective_events, list):
        return None
    counts = _elemental_drake_counts(objective_events)

    # 1. Soul secured - a live soul on the map is the highest-priority read.
    for side in ("enemy", "ally"):
        if counts[side] >= _SOUL_SECURED_STACKS:
            el = _locked_element(objective_events)
            tmpl = _SOUL_SECURED_LINES[side]
            line = tmpl.format(el=el) if el else tmpl.replace(" ({el})", "")
            return {"tag": f"soul_secured_{side}", "line": line,
                    "eta_s": None, "kind": "dragon_soul"}

    # 2. Soul point - the force-or-deny inflection.
    for side in ("enemy", "ally"):  # enemy deny outranks ally force for the slot
        if counts[side] == _SOUL_POINT_STACKS:
            return {"tag": f"soul_point_{side}", "line": _SOUL_POINT_LINES[side],
                    "eta_s": None, "kind": "dragon_soul"}

    # 3. Soul race - a meaningful pre-point lead (ally-enemy score always).
    a, e = counts["ally"], counts["enemy"]
    leader = "ally" if a > e else ("enemy" if e > a else None)
    if leader is not None:
        hi = a if leader == "ally" else e
        if hi >= _SOUL_RACE_MIN_STACKS and abs(a - e) >= _SOUL_RACE_MIN_LEAD:
            return {"tag": f"soul_race_{leader}",
                    "line": _SOUL_RACE_LINES[leader].format(a=a, b=e),
                    "eta_s": None, "kind": "dragon_soul"}
    return None


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
    inhib_events: object = None,
    turret_events: object = None,
    objective_events: object = None,
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
        inhib_events: list of ``{down_at_s, name}`` InhibKilled events (SR
            only). Each still-down inhibitor yields a respawn-timing callout
            300s after it fell (see inhibitor_callouts).
        objective_events: list of ``{name, killer_team, down_at_s}`` Baron/Elder
            kill events (SR only). Each live epic buff yields a sided expiry
            countdown (see epic_buff_callouts).

    Returns:
        list of dicts ``{tag, line, eta_s, kind}`` where:
          - kind in {objective, level_spike, item_spike, recall, epic_buff}
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
        callouts.extend(_objective_callouts(gt, objective_events))
        # Inhibitor respawn is SR-only (Howling Abyss has no inhibitors).
        callouts.extend(inhibitor_callouts(inhib_events, gt))
        # Epic-buff (Baron/Elder) expiry countdowns - SR-only neutral objectives.
        callouts.extend(epic_buff_callouts(objective_events, gt))
    # Instant base-siege callout (active, eta_s=0) - SR + ARAM, both have lane
    # structures. Fires for ~_SIEGE_RECENCY_S after a turret/inhib falls so the
    # no-LLM bridge is on-screen before the Haiku coach tick lands.
    if m in _SIEGE_MODES:
        callouts.extend(structure_siege_callout(turret_events, inhib_events, gt))
    callouts.extend(_level_spike_callouts(lvl))
    callouts.extend(_item_spike_callouts(items))

    # Recall is SR-only (ARAM has no fountain recall; Arena/Brawl are death-buy).
    if m in _RECALL_MODES:
        recall = recall_callout(gold, next_item_name, next_item_cost)
        if recall is not None:
            callouts.append(recall)

    callouts.sort(key=_sort_key)

    if max_n is not None and max_n >= 0:
        return callouts[:max_n]
    return callouts
