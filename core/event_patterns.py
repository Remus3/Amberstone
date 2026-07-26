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
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# Match-V5 teamPosition -> RC role enum.
POSITION_TO_ROLE = {
    "TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID",
    "BOTTOM": "BOT", "UTILITY": "SUPPORT",
}

EARLY_GAME_MS = 8 * 60 * 1000


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


def role_of(match: dict, participant_id: int) -> str:
    for p in (match.get("info") or {}).get("participants") or []:
        if p.get("participantId") == participant_id:
            return POSITION_TO_ROLE.get(p.get("teamPosition") or "", "")
    return ""


def won(match: dict, participant_id: int) -> bool:
    for p in (match.get("info") or {}).get("participants") or []:
        if p.get("participantId") == participant_id:
            return bool(p.get("win"))
    return False


def team_of(participant_id: int) -> int:
    """Seats 1-5 are team 100, 6-10 are team 200.

    Verified across 460 of 460 participants in the corpus, zero exceptions.
    """
    return 100 if participant_id <= 5 else 200


def _events(timeline: dict) -> list:
    return [e for f in ((timeline.get("info") or {}).get("frames") or [])
            for e in (f.get("events") or [])]


def _frames(timeline: dict) -> list:
    return list((timeline.get("info") or {}).get("frames") or [])


# --------------------------------------------------------------- criteria

def deaths_by_cost(match, timeline, pid) -> list:
    """Every death, carrying what it handed the enemy.

    `bounty` is the kill's gold value and `shutdownBounty` is the extra paid
    for ending a streak, so their sum is the measured cost of that death.
    """
    role = role_of(match, pid)
    out = []
    for e in _events(timeline):
        if e.get("type") != "CHAMPION_KILL" or e.get("victimId") != pid:
            continue
        pos = e.get("position") or {}
        out.append(Finding(
            criterion="death_cost", participant_id=pid, role=role,
            t_ms=int(e.get("timestamp") or 0),
            magnitude_gold=int(e.get("bounty") or 0)
            + int(e.get("shutdownBounty") or 0),
            detail={"x": pos.get("x"), "y": pos.get("y"),
                    "killer": e.get("killerId"),
                    "assists": len(e.get("assistingParticipantIds") or []),
                    "shutdown": int(e.get("shutdownBounty") or 0)}))
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
    team = team_of(pid)
    mine = took = 0
    for e in _events(timeline):
        if e.get("type") != "ELITE_MONSTER_KILL":
            continue
        if e.get("killerTeamId") != team:
            continue
        took += 1
        if e.get("killerId") == pid or pid in (
                e.get("assistingParticipantIds") or []):
            mine += 1
    if not took:
        return []
    return [Finding(criterion="objective_participation", participant_id=pid,
                    role=role_of(match, pid), value=mine / took,
                    detail={"participated": mine, "team_took": took})]


def kill_participation(match, timeline, pid) -> list:
    """Share of team kills the player was killer or assist on."""
    team = team_of(pid)
    mine = total = 0
    for e in _events(timeline):
        if e.get("type") != "CHAMPION_KILL":
            continue
        killer = e.get("killerId") or 0
        if not killer or team_of(killer) != team:
            continue
        total += 1
        if killer == pid or pid in (e.get("assistingParticipantIds") or []):
            mine += 1
    if not total:
        return []
    return [Finding(criterion="kill_participation", participant_id=pid,
                    role=role_of(match, pid), value=mine / total,
                    detail={"participated": mine, "team_kills": total})]


def plate_share(match, timeline, pid) -> list:
    """Turret plates taken by this player, and the team's total."""
    team = team_of(pid)
    mine = team_total = 0
    for e in _events(timeline):
        if e.get("type") != "TURRET_PLATE_DESTROYED":
            continue
        # teamId on a plate event is the team that LOST the plate.
        if e.get("teamId") == team:
            continue
        team_total += 1
        if e.get("killerId") == pid:
            mine += 1
    return [Finding(criterion="plate_share", participant_id=pid,
                    role=role_of(match, pid),
                    value=(mine / team_total) if team_total else 0.0,
                    detail={"plates": mine, "team_plates": team_total})]


def skill_order(match, timeline, pid) -> list:
    """The first six skill points, in order. A build signature, not a score."""
    slots = [int(e.get("skillSlot") or 0) for e in _events(timeline)
             if e.get("type") == "SKILL_LEVEL_UP"
             and e.get("participantId") == pid]
    if not slots:
        return []
    return [Finding(criterion="skill_order", participant_id=pid,
                    role=role_of(match, pid),
                    detail={"order": slots[:6],
                            "signature": "".join(str(s) for s in slots[:6])})]


def item_order(match, timeline, pid) -> list:
    """Purchase sequence with timestamps, corrected for undos.

    An ITEM_UNDO removes the most recent matching purchase; without that the
    sequence contains items the player never actually kept.
    """
    seq = []
    for e in _events(timeline):
        if e.get("participantId") != pid:
            continue
        typ = e.get("type")
        if typ == "ITEM_PURCHASED":
            seq.append((int(e.get("timestamp") or 0), int(e.get("itemId") or 0)))
        elif typ == "ITEM_UNDO":
            before = e.get("beforeId") or e.get("afterId") or 0
            for i in range(len(seq) - 1, -1, -1):
                if seq[i][1] == int(before or 0):
                    seq.pop(i)
                    break
    if not seq:
        return []
    return [Finding(criterion="item_order", participant_id=pid,
                    role=role_of(match, pid), t_ms=seq[0][0],
                    detail={"purchases": seq})]


def gold_deficit_profile(match, timeline, pid) -> list:
    """How long this player's TEAM spent behind, and whether it recovered.

    T1 frames, so it is labelled tier T1 - the only criterion here that is not
    pure T2, and it is included because "actions while behind" needs a notion
    of behind.
    """
    frames = _frames(timeline)
    if not frames:
        return []
    team = team_of(pid)
    behind = 0
    total = 0
    series = []
    for f in frames:
        pfs = list((f.get("participantFrames") or {}).values())
        if not pfs:
            # A frame carrying no participant data is NOT an even frame.
            # Counting it as diff=0 fabricates a "not behind" reading out of
            # missing data, which is worse than having no reading at all.
            continue
        ours = sum(int(p.get("totalGold") or 0) for p in pfs
                   if team_of(int(p.get("participantId") or 0)) == team)
        theirs = sum(int(p.get("totalGold") or 0) for p in pfs
                     if team_of(int(p.get("participantId") or 0)) != team)
        diff = ours - theirs
        series.append(diff)
        total += 1
        if diff < 0:
            behind += 1
    if not total:
        return []
    return [Finding(criterion="gold_deficit_profile", participant_id=pid,
                    role=role_of(match, pid), tier="T1",
                    value=behind / total,
                    magnitude_gold=int(min(series)) if series else 0,
                    detail={"frames_behind": behind, "frames": total,
                            "max_deficit": int(min(series)) if series else 0,
                            "final_diff": int(series[-1]) if series else 0,
                            "recovered": bool(series and min(series) < 0
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
    "item_order": item_order,
    "gold_deficit_profile": gold_deficit_profile,
}


def analyse(match: dict, timeline: dict, pid: int) -> list:
    """Every criterion for one player. Order is the registry's."""
    out = []
    for fn in CRITERIA.values():
        out.extend(fn(match, timeline, pid))
    return out
