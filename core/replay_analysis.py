"""Derivations over a match timeline, in a shape that live telemetry can share.

THE STRUCTURAL POINT, which matters more than any single derivation here: the
functions below take a `Timeline`, never a Match-V5 blob. `normalize_timeline`
is one producer; a live `:2999` sampler is meant to be the second. A derivation
validated against archived games then runs unchanged on a live game, which is
what makes this a coaching pipeline rather than an analytics script.

MEASURED FIDELITY (2026-07-26, NA1_5607594617) - the two tiers are NOT the same
and conflating them produces confident nonsense:

  events  sub-second, with map coordinates. Kills at 192.4 / 198.6 / 199.4 s,
          ITEM_PURCHASED, SKILL_LEVEL_UP, WARD_PLACED, plates, ELITE_MONSTER_KILL.
  frames  60 s. Position, gold, xp, level, cs, jungle cs.

So an objective is timed to the second, but WHERE a player was when it happened
is a 60 s sample - up to a 30 s error. Every position-derived verdict therefore
carries `sample_age_s` and a `stale` flag. A verdict that hides its sampling
error is unfalsifiable.

NOT MEASURABLE AT THIS TIER, do not let a derivation imply otherwise: wave
state. There are no minion entities in the timeline, so cs rate and plate
timings are PROXIES for wave pressure, never a measurement of it. True wave
state needs Layer-2 (see docs/REPLAY_FRAME_ANALYSIS_SPEC.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Summoner's Rift landmarks, from measured event coordinates rather than a wiki.
DRAGON_PIT = (9866, 4414)
BARON_PIT = (5007, 10471)
MAP_MAX = 14820

# Distance beyond which a jungler is not plausibly contesting the objective.
FAR_UNITS = 5000


@dataclass(frozen=True)
class FrameSample:
    """One player at one 60 s sampling point."""

    t_ms: int
    participant_id: int
    x: int
    y: int
    total_gold: int = 0
    xp: int = 0
    level: int = 0
    cs: int = 0
    jungle_cs: int = 0


@dataclass(frozen=True)
class TimelineEvent:
    """One event, at its OWN sub-second timestamp - never a frame bucket."""

    t_ms: int
    type: str
    actor_id: int = 0
    victim_id: int = 0
    x: int = 0
    y: int = 0
    item_id: int = 0
    monster_type: str = ""
    ward_type: str = ""


@dataclass
class Timeline:
    frames: list = field(default_factory=list)
    events: list = field(default_factory=list)
    frame_interval_ms: int = 60000


@dataclass(frozen=True)
class PositionSample:
    """A position lookup, WITH its sampling error made visible."""

    x: int
    y: int
    t_ms: int
    age_s: float
    stale: bool


@dataclass(frozen=True)
class Approach:
    lead_s: float
    distance: float
    same_half: bool
    sample_age_s: float


@dataclass(frozen=True)
class Verdict:
    t_ms: int
    verdict: str
    distance: float
    coaching: str
    source: str
    sample_age_s: float


def normalize_timeline(raw) -> Timeline:
    """Match-V5 timeline blob -> the neutral shape every derivation consumes."""
    info = (raw or {}).get("info") or {}
    tl = Timeline(frame_interval_ms=int(info.get("frameInterval") or 60000))
    for frame in info.get("frames") or []:
        for pf in (frame.get("participantFrames") or {}).values():
            pos = pf.get("position") or {}
            tl.frames.append(FrameSample(
                t_ms=int(frame.get("timestamp") or 0),
                participant_id=int(pf.get("participantId") or 0),
                x=int(pos.get("x") or 0), y=int(pos.get("y") or 0),
                total_gold=int(pf.get("totalGold") or 0),
                xp=int(pf.get("xp") or 0), level=int(pf.get("level") or 0),
                cs=int(pf.get("minionsKilled") or 0),
                jungle_cs=int(pf.get("jungleMinionsKilled") or 0)))
        for ev in frame.get("events") or []:
            pos = ev.get("position") or {}
            tl.events.append(TimelineEvent(
                t_ms=int(ev.get("timestamp") or 0),
                type=str(ev.get("type") or ""),
                actor_id=int(ev.get("killerId") or ev.get("participantId") or 0),
                victim_id=int(ev.get("victimId") or 0),
                x=int(pos.get("x") or 0), y=int(pos.get("y") or 0),
                item_id=int(ev.get("itemId") or 0),
                monster_type=str(ev.get("monsterType") or ""),
                ward_type=str(ev.get("wardType") or "")))
    return tl


def objective_events(tl: Timeline, monster: str = "DRAGON") -> list:
    return [e for e in tl.events
            if e.type == "ELITE_MONSTER_KILL" and e.monster_type == monster]


def position_at(tl: Timeline, participant_id: int, t_ms: int):
    """Nearest frame sample to *t_ms*, or None if the player never appears.

    Returns the sampling error rather than hiding it: at a 60 s interval the
    answer can be up to half an interval away from the moment asked about.
    """
    mine = [f for f in tl.frames if f.participant_id == participant_id]
    if not mine:
        return None
    best = min(mine, key=lambda f: abs(f.t_ms - t_ms))
    age_s = abs(best.t_ms - t_ms) / 1000.0
    return PositionSample(x=best.x, y=best.y, t_ms=best.t_ms, age_s=age_s,
                          stale=age_s > tl.frame_interval_ms / 1000.0)


def _distance(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def objective_approach(tl: Timeline, participant_id: int, event: TimelineEvent,
                       leads_s=(30, 60, 90), pit=None) -> list:
    """Where the player was at each lead time before an objective fell."""
    target = pit or ((event.x, event.y) if event.x or event.y else DRAGON_PIT)
    out = []
    for lead in leads_s:
        sample = position_at(tl, participant_id, event.t_ms - int(lead * 1000))
        if sample is None:
            continue
        # "Same half" is the diagonal SR split: bot-right vs top-left of the
        # anti-diagonal through the map centre.
        same = ((sample.x + sample.y) > MAP_MAX) == ((target[0] + target[1]) > MAP_MAX)
        out.append(Approach(lead_s=lead,
                            distance=_distance((sample.x, sample.y), target),
                            same_half=same, sample_age_s=sample.age_s))
    return out


def drake_pathing_verdict(tl: Timeline, participant_id: int,
                          lead_s: float = 60) -> list:
    """One verdict per drake: was this jungler in position, or late?

    Deliberately narrow. It exists to prove the pipeline answers a real
    question end to end, not to be a general pathing model.
    """
    out = []
    for ev in objective_events(tl, "DRAGON"):
        ap = objective_approach(tl, participant_id, ev, leads_s=(lead_s,))
        if not ap:
            continue
        a = ap[0]
        if a.distance <= FAR_UNITS:
            verdict = "IN_POSITION"
            line = (f"In position for the drake at {ev.t_ms / 1000:.0f}s "
                    f"({a.distance:.0f} units out {lead_s:.0f}s prior).")
        elif not a.same_half:
            verdict = "LATE"
            line = (f"Wrong side of the map {lead_s:.0f}s before the drake at "
                    f"{ev.t_ms / 1000:.0f}s ({a.distance:.0f} units out). "
                    f"Start the rotation a camp earlier.")
        else:
            verdict = "TRAILING"
            line = (f"Right side but {a.distance:.0f} units off the drake at "
                    f"{ev.t_ms / 1000:.0f}s, {lead_s:.0f}s prior.")
        out.append(Verdict(t_ms=ev.t_ms, verdict=verdict, distance=a.distance,
                           coaching=line, source="match_v5_timeline",
                           sample_age_s=a.sample_age_s))
    return out
