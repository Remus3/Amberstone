"""Event-tier (T2) derivations over a match, for ladder-scale pattern mining.

Every criterion here is computable HEADLESS from a Match-V5 match blob plus its
timeline, with no game client and no external data. That constraint is
deliberate: it is what lets these run over the whole ladder corpus, which is
what turns a finding into a rate and a rate into a coaching rule.

WHAT THIS IS FOR - see docs/REPLAY_T2_PARSE_CRITERIA.md sections 2 and 4:

  PGR   rank a single match's findings by magnitude.
  MINE  aggregate findings across the corpus, split win-side vs loss-side, and
        require a MEASURED RATE DIFFERENCE before anything is promoted to a
        coaching rule. A winner's habit is not automatically correct - winners
        make mistakes they get away with, and a corpus will teach those
        happily unless the promotion gate is enforced.

Nothing here uses position beyond what T2 events carry natively (kills,
objectives, plates and buildings all have their own coordinates). Continuous
position is T3/T4 and is deliberately out of scope, because Match-V5's 60 s
frame sampling carries ~2000 units of error - measured, see the retraction in
`core/replay_analysis.py`.

INPUT CONTRACT (s144 lane 8 audit). The match and timeline are Riot JSON that
RC did not author, and the corpus miner catches only OSError / JSONDecodeError
per file, so an exception here aborts the WHOLE mine. Every reader therefore
fails soft and never fabricates:

  * a container of the wrong shape (a non-dict match, timeline, frame, event
    or participant; a non-list frames / events / participants) reads as empty;
  * a number is accepted only as a real int or an integral finite float -
    never a bool, a string, a fraction, NaN or infinity (`_int`);
  * a participant id is a seat 1-10 (`_seat`); anything else matches nobody,
    and a criterion asked about a non-seat returns no finding;
  * an event whose time is missing or invalid is never dated 0:00: a death or
    a purchase without a time is skipped, and a skill-point event without one
    still moves the FIFO queue but is never measured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

# Match-V5 teamPosition -> RC role enum.
POSITION_TO_ROLE = {
    "TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID",
    "BOTTOM": "BOT", "UTILITY": "SUPPORT",
}

EARLY_GAME_MS = 8 * 60 * 1000

# Match-V5 skillSlot values: 1-4 = Q W E R.
_SKILL_SLOTS = (1, 2, 3, 4)
_TEAMS = (100, 200)


@dataclass(frozen=True)
class Finding:
    """One observation about one player in one match.

    `magnitude_gold` is measured currency, never an invented severity score -
    bounty, shutdown bounty, or a gold delta. `tier` and `source` travel with
    the finding so a consumer can never confuse a T2 fact with a T1 estimate.
    """

    criterion: str
    participant_id: int
    role: str
    t_ms: int = 0
    magnitude_gold: int = 0
    value: float = 0.0
    detail: dict = field(default_factory=dict)
    tier: str = "T2"
    source: str = "match_v5_timeline"


# ------------------------------------------------------- strict readers

def _int(v):
    """A real integer, or None.

    Accepts an int or an integral finite float (JSON may carry 3006.0).
    Refuses a bool (True would read as seat 1 or as 1 gold), a string, a
    fraction (never truncated into a different value), NaN and infinity.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        return int(v)
    return None


def _nonneg(v):
    """`_int` restricted to >= 0 (a time, a bounty, an item id), or None."""
    n = _int(v)
    return n if n is not None and n >= 0 else None


def _gold(v) -> int:
    """A bounty / shutdown amount.

    Missing or malformed reads as 0, exactly as an absent field always has;
    a negative amount is not a refund.
    """
    n = _nonneg(v)
    return n if n is not None else 0


def _seat(v):
    """A Match-V5 participant seat 1-10, or None."""
    n = _int(v)
    return n if n is not None and 1 <= n <= 10 else None


def _seat_team(v):
    """Team of a seat (1-5 = 100, 6-10 = 200), or None for a non-seat."""
    n = _seat(v)
    if n is None:
        return None
    return 100 if n <= 5 else 200


def _seats(v) -> set:
    """The valid seats in an id list; a non-list carries none."""
    if not isinstance(v, list):
        return set()
    return {n for n in (_seat(x) for x in v) if n is not None}


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _participant(match, participant_id):
    """The match participant sitting in this seat, or None."""
    seat = _seat(participant_id)
    if seat is None:
        return None
    for p in _list(_dict(_dict(match).get("info")).get("participants")):
        if isinstance(p, dict) and _seat(p.get("participantId")) == seat:
            return p
    return None


def role_of(match: dict, participant_id: int) -> str:
    p = _participant(match, participant_id)
    if p is None:
        return ""
    pos = p.get("teamPosition")
    return POSITION_TO_ROLE.get(pos, "") if isinstance(pos, str) else ""


def won(match: dict, participant_id: int) -> bool:
    """True only for a real JSON true; a string "False" is not a win."""
    p = _participant(match, participant_id)
    return p is not None and p.get("win") is True


def team_of(participant_id: int) -> int:
    """Seats 1-5 are team 100, 6-10 are team 200.

    Verified across 460 of 460 participants in the corpus, zero exceptions
    (re-measured s144: 30050 of 30050, every match queue 420). Raises
    ValueError on a non-seat (0, 11+, a bool, a string) instead of silently
    answering 100 or 200 - an Arena seat 11-16 is not team 200.
    """
    team = _seat_team(participant_id)
    if team is None:
        raise ValueError(f"not a Match-V5 seat 1-10: {participant_id!r}")
    return team


def _frames(timeline: dict) -> list:
    info = _dict(_dict(timeline).get("info"))
    return [f for f in _list(info.get("frames")) if isinstance(f, dict)]


def _events(timeline: dict) -> list:
    return [e for f in _frames(timeline) for e in _list(f.get("events"))
            if isinstance(e, dict)]


# --------------------------------------------------------------- criteria

def deaths_by_cost(match, timeline, pid) -> list:
    """Every death, carrying what it handed the enemy.

    `bounty` is the kill's gold value and `shutdownBounty` is the extra paid
    for ending a streak, so their sum is the measured cost of that death.

    A death with no valid time is skipped: dating it 0:00 would make it an
    early death, and the PGR tags deaths by time.
    """
    seat = _seat(pid)
    if seat is None:
        return []
    role = role_of(match, seat)
    out = []
    for e in _events(timeline):
        if (e.get("type") != "CHAMPION_KILL"
                or _seat(e.get("victimId")) != seat):
            continue
        t = _nonneg(e.get("timestamp"))
        if t is None:
            continue
        pos = _dict(e.get("position"))
        shutdown = _gold(e.get("shutdownBounty"))
        out.append(Finding(
            criterion="death_cost", participant_id=seat, role=role,
            t_ms=t, magnitude_gold=_gold(e.get("bounty")) + shutdown,
            detail={"x": pos.get("x"), "y": pos.get("y"),
                    "killer": e.get("killerId"),
                    "assists": len(_list(e.get("assistingParticipantIds"))),
                    "shutdown": shutdown}))
    return out


def _relabel(findings, criterion: str) -> list:
    """Re-tag derived findings with their OWN criterion name.

    Not cosmetic. Every subset below is derived from deaths_by_cost, and if
    they keep its label then a consumer grouping by criterion counts one death
    once per subset it falls into - death_cost inflates several-fold and every
    subset reads as zero. Measured on a real match: one death appeared three
    times.
    """
    return [replace(f, criterion=criterion) for f in findings]


def shutdowns_given(match, timeline, pid) -> list:
    """Deaths that paid a shutdown - you were ahead and gave it back."""
    return _relabel([f for f in deaths_by_cost(match, timeline, pid)
                     if f.detail.get("shutdown", 0) > 0], "shutdowns_given")


def early_deaths(match, timeline, pid) -> list:
    """Deaths inside the first 8 minutes, when a death costs tempo not gold."""
    return _relabel([f for f in deaths_by_cost(match, timeline, pid)
                     if f.t_ms <= EARLY_GAME_MS], "early_deaths")


def solo_deaths(match, timeline, pid) -> list:
    """Died to a single enemy with no assists - a positioning loss, not a gank."""
    return _relabel([f for f in deaths_by_cost(match, timeline, pid)
                     if f.detail.get("assists", 0) == 0], "solo_deaths")


def objective_participation(match, timeline, pid) -> list:
    """Share of the player's TEAM's elite monsters they helped take.

    Team-relative on purpose: an absolute count only measures how many
    objectives the game happened to contain.
    """
    seat, team = _seat(pid), _seat_team(pid)
    if seat is None:
        return []
    mine = took = 0
    for e in _events(timeline):
        if e.get("type") != "ELITE_MONSTER_KILL":
            continue
        if _int(e.get("killerTeamId")) != team:
            continue
        took += 1
        if (_seat(e.get("killerId")) == seat
                or seat in _seats(e.get("assistingParticipantIds"))):
            mine += 1
    if not took:
        return []
    return [Finding(criterion="objective_participation", participant_id=seat,
                    role=role_of(match, seat), value=mine / took,
                    detail={"participated": mine, "team_took": took})]


def kill_participation(match, timeline, pid) -> list:
    """Share of team kills the player was killer or assist on."""
    seat, team = _seat(pid), _seat_team(pid)
    if seat is None:
        return []
    mine = total = 0
    for e in _events(timeline):
        if e.get("type") != "CHAMPION_KILL":
            continue
        # killerId 0 (an execution) or any non-seat is nobody's team kill.
        killer = _seat(e.get("killerId"))
        if killer is None or _seat_team(killer) != team:
            continue
        total += 1
        if killer == seat or seat in _seats(e.get("assistingParticipantIds")):
            mine += 1
    if not total:
        return []
    return [Finding(criterion="kill_participation", participant_id=seat,
                    role=role_of(match, seat), value=mine / total,
                    detail={"participated": mine, "team_kills": total})]


def plate_share(match, timeline, pid) -> list:
    """Turret plates taken by this player, and the team's total."""
    seat, team = _seat(pid), _seat_team(pid)
    if seat is None:
        return []
    mine = team_total = 0
    for e in _events(timeline):
        if e.get("type") != "TURRET_PLATE_DESTROYED":
            continue
        # teamId on a plate event is the team that LOST the plate. A plate
        # with no valid losing team belongs to neither side: reading a
        # missing teamId as "not ours" credited it to BOTH teams.
        lost = _int(e.get("teamId"))
        if lost not in _TEAMS or lost == team:
            continue
        team_total += 1
        if _seat(e.get("killerId")) == seat:
            mine += 1
    return [Finding(criterion="plate_share", participant_id=seat,
                    role=role_of(match, seat),
                    value=(mine / team_total) if team_total else 0.0,
                    detail={"plates": mine, "team_plates": team_total})]


def skill_order(match, timeline, pid) -> list:
    """The first six skill points, in order. A build signature, not a score.

    Only level POINTS count: an EVOLVE skill-up (Kha'Zix, Kai'Sa, Viktor) is
    not a point and is skipped, as skill_point_latency skips it; an event with
    no levelUpType key is a point. A skillSlot outside 1-4 is skipped, never
    recorded as slot 0.
    """
    seat = _seat(pid)
    if seat is None:
        return []
    slots = []
    for e in _events(timeline):
        if (e.get("type") != "SKILL_LEVEL_UP"
                or _seat(e.get("participantId")) != seat):
            continue
        if not _is_point(e):
            continue
        slot = _int(e.get("skillSlot"))
        if slot in _SKILL_SLOTS:
            slots.append(slot)
    if not slots:
        return []
    return [Finding(criterion="skill_order", participant_id=seat,
                    role=role_of(match, seat),
                    detail={"order": slots[:6],
                            "signature": "".join(str(s) for s in slots[:6])})]


def _is_point(event: dict) -> bool:
    """A SKILL_LEVEL_UP spends a level point unless it says it is not.

    An absent, null or empty levelUpType is NORMAL (older blobs and the
    synthetic fixtures carry none; the RM-603 rule always read it so); EVOLVE
    and any other stated kind is not a point.
    """
    kind = event.get("levelUpType")
    return kind is None or kind in ("", "NORMAL")


# RM-603: LEVEL_UP events at or before this game time are STARTING credit, not
# a point the player sat on. Our own value: data/rewind_history.db (probe
# 2026-10-04) stamps the ARAM level 2 and 3 grants at 503-508 ms; the first
# Rift LEVEL_UP lands after 90 s. 5 s separates the two with wide margin.
_START_GRACE_MS = 5000


def _champion_of(match: dict, participant_id: int) -> str:
    p = _participant(match, participant_id)
    name = p.get("championName") if p is not None else None
    return name if isinstance(name, str) else ""


def skill_point_latency(match, timeline, pid) -> list:
    """How long each level-up point sat before it was spent (RM-603, external
    reference F; post-game half of the live skill-point tracker).

    FIFO pairing per participant: every LEVEL_UP queues one point, every
    NORMAL SKILL_LEVEL_UP spends the oldest queued point. EVOLVE skill-ups
    are not level points and are skipped. The level-1 point (no LEVEL_UP is
    ever sent for it) and any LEVEL_UP inside the start grace (the ARAM
    level-3 start) are starting credit and are consumed without being
    measured. Kits whose skill-ups are not level points (Aphelios; see
    core/skill_point_tracker.py SPECIAL_KITS) are fenced out.

    An event with no valid time still moves the queue (the point was still
    gained or spent) but is never measured: a LEVEL_UP queues an unmeasured
    point and a skill-up spends one without recording a pair. Reading the
    missing time as 0 fabricated a 0 ms hold.
    """
    from core.skill_point_tracker import NAG_AFTER_S, kit_rules
    seat = _seat(pid)
    if seat is None or not kit_rules(_champion_of(match, seat)).supported:
        return []
    queue: list = []        # (level, t_ms, measured)
    pairs: list = []
    saw_level_up = False
    for e in _events(timeline):
        if _seat(e.get("participantId")) != seat:
            continue
        typ = e.get("type")
        t = _nonneg(e.get("timestamp"))
        if typ == "LEVEL_UP":
            saw_level_up = True
            queue.append((_nonneg(e.get("level")), t,
                          t is not None and t > _START_GRACE_MS))
        elif typ == "SKILL_LEVEL_UP":
            if not _is_point(e):
                continue
            if not queue:
                continue    # the level-1 point (or a surplus skill-up)
            level, t_lv, measured = queue.pop(0)
            if measured and t is not None:
                pairs.append({"level": level, "level_t_ms": t_lv,
                              "spent_t_ms": t, "held_ms": max(0, t - t_lv)})
    if not saw_level_up or not pairs:
        return []
    held = sorted(p["held_ms"] for p in pairs)
    median = held[(len(held) - 1) // 2]
    worst = max(pairs, key=lambda p: (p["held_ms"], -p["level_t_ms"]))
    return [Finding(
        criterion="skill_point_latency", participant_id=seat,
        role=role_of(match, seat), t_ms=worst["level_t_ms"],
        value=median / 1000.0,
        detail={"pairs": pairs, "n": len(pairs),
                "median_held_ms": median, "max_held_ms": worst["held_ms"],
                "held_over_nag": sum(1 for h in held
                                     if h >= NAG_AFTER_S * 1000),
                "nag_after_s": NAG_AFTER_S,
                "unspent_at_end": sum(1 for q in queue if q[2])})]


def item_order(match, timeline, pid) -> list:
    """Purchase sequence with timestamps, corrected for undos.

    An ITEM_UNDO carries no itemId: Riot sends ``beforeId`` (the item held
    before the undo) and ``afterId`` (the item held after it). The two
    directions are NOT interchangeable here (RM-290):

    - undone PURCHASE (beforeId set): the item never stayed, so the most
      recent matching purchase is removed;
    - undone SALE (beforeId 0, afterId set): the item came back, so the player
      KEPT it and its purchase already in the sequence must stand.

    This is a purchase-ORDER view, so afterId is never appended - that would
    be an inventory fold (``core.replay_history``), not a purchase.

    A purchase with no valid time or no valid item id (0, a fraction, a
    string) is skipped rather than recorded as item 0 or a 0:00 buy; an undo
    whose beforeId is malformed removes nothing.
    """
    seat = _seat(pid)
    if seat is None:
        return []
    seq = []
    for e in _events(timeline):
        if _seat(e.get("participantId")) != seat:
            continue
        typ = e.get("type")
        if typ == "ITEM_PURCHASED":
            t, item = _nonneg(e.get("timestamp")), _nonneg(e.get("itemId"))
            if t is not None and item:
                seq.append((t, item))
        elif typ == "ITEM_UNDO":
            before = _nonneg(e.get("beforeId"))
            if not before:
                continue  # undone sale (or malformed): the purchase stands
            for i in range(len(seq) - 1, -1, -1):
                if seq[i][1] == before:
                    seq.pop(i)
                    break
    if not seq:
        return []
    return [Finding(criterion="item_order", participant_id=seat,
                    role=role_of(match, seat), t_ms=seq[0][0],
                    detail={"purchases": seq})]


def _team_gold(pfs: list):
    """{100: gold, 200: gold} for one frame, or None when it cannot be read.

    An entry without a valid seat is ignored (it is nobody's gold, not team
    100's); a duplicated seat, a malformed gold total or a team with no
    entries at all makes the whole frame unreadable, because a one-sided or
    double-counted frame is a fabricated lead.
    """
    seen: set = set()
    gold = {100: 0, 200: 0}
    for p in pfs:
        s = _seat(p.get("participantId"))
        if s is None:
            continue
        if s in seen:
            return None
        g = _nonneg(p.get("totalGold", 0))
        if g is None:
            return None
        seen.add(s)
        gold[_seat_team(s)] += g
    if not any(s <= 5 for s in seen) or not any(s > 5 for s in seen):
        return None
    return gold


def gold_deficit_profile(match, timeline, pid) -> list:
    """How long this player's TEAM spent behind, and whether it recovered.

    T1 frames, so it is labelled tier T1 - the only criterion here that is not
    pure T2, and it is included because "actions while behind" needs a notion
    of behind. Frames `_team_gold` cannot read are skipped like empty ones.
    """
    seat, team = _seat(pid), _seat_team(pid)
    if seat is None:
        return []
    frames = _frames(timeline)
    if not frames:
        return []
    behind = 0
    total = 0
    series = []
    for f in frames:
        pfs = [p for p in _dict(f.get("participantFrames")).values()
               if isinstance(p, dict)]
        if not pfs:
            # A frame carrying no participant data is NOT an even frame.
            # Counting it as diff=0 fabricates a "not behind" reading out of
            # missing data, which is worse than having no reading at all.
            continue
        gold = _team_gold(pfs)
        if gold is None:
            continue
        diff = gold[team] - gold[300 - team]
        series.append(diff)
        total += 1
        if diff < 0:
            behind += 1
    if not total:
        return []
    return [Finding(criterion="gold_deficit_profile", participant_id=seat,
                    role=role_of(match, seat), tier="T1",
                    value=behind / total,
                    magnitude_gold=int(min(series)),
                    detail={"frames_behind": behind, "frames": total,
                            "max_deficit": int(min(series)),
                            "final_diff": int(series[-1]),
                            "recovered": bool(min(series) < 0
                                              and series[-1] > 0)})]


# Registry. A miner walks this so adding a criterion needs no miner change.
CRITERIA = {
    "death_cost": deaths_by_cost,
    "shutdowns_given": shutdowns_given,
    "early_deaths": early_deaths,
    "solo_deaths": solo_deaths,
    "objective_participation": objective_participation,
    "kill_participation": kill_participation,
    "plate_share": plate_share,
    "skill_order": skill_order,
    "skill_point_latency": skill_point_latency,
    "item_order": item_order,
    "gold_deficit_profile": gold_deficit_profile,
}


def analyse(match: dict, timeline: dict, pid: int) -> list:
    """Every criterion for one player. Order is the registry's."""
    out = []
    for fn in CRITERIA.values():
        out.extend(fn(match, timeline, pid))
    return out
