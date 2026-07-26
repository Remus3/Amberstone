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
#
# CALIBRATED, not chosen. Measured 2026-07-26 over all 46 corpus matches, both
# junglers, every drake: 308 samples, a balanced 154 secured / 154 lost. The
# threshold that best separates them at the default 30 s lead is 2750 units
# (68.8 pct accuracy). The previous hand-picked 5000 scored 53.6 pct at 60 s,
# i.e. barely above a coin flip.
FAR_UNITS = 2750

# Default lead. 30 s is the operating point: it is the longest lead that still
# carries signal AND is actionable (a 0 s verdict is near-tautological - "you
# were at the drake when your team took the drake").
DEFAULT_LEAD_S = 30

# MEASURED SIGNAL DECAY - lead_s -> best achievable accuracy, same 308 samples.
#
# !! THE INTERPRETATION BELOW WAS WRONG AND IS RETRACTED. It read: "mean sample
# age is a flat ~15 s at every lead, so this decay is REAL behaviour, not
# sampling error." That is a non-sequitur. Constant staleness produces constant
# NOISE, and the noise turned out to be enormous.
#
# MEASURED 2026-07-26 against seek-sampled exact positions (~19 unit precision)
# on NA1_5607614664, 21 drake/jungler samples:
#     Match-V5 distance error vs exact:  mean 1971, median 853, max 8565 units
#     samples whose error alone exceeds the 2750 threshold:  6 of 21
# Worst case: at the 706 s drake, Vi's exact distance was 61 units - he was
# standing on the dragon and killed it - while the Match-V5 frame put him at
# 8626 units, across the map.
#
# So a 60 s-sampled position CANNOT support a 2750-unit threshold, and the
# decay curve below is substantially an artefact of sampling noise rather than
# a measurement of jungler behaviour. Lead 0 scores best not because its data
# is cleaner but because the true answer there is strongly bimodal and survives
# heavy noise.
#
# CONSEQUENCE: FAR_UNITS and SIGNAL_DECAY are retained ONLY as the historical
# 60 s-tier calibration. Do not treat either as a fact about junglers, and do
# not re-derive coaching from them. A trustworthy version of this metric needs
# seek-sampled positions (core/replay_camera.screen_to_map), which is
# interactive and one game at a time - see docs/REPLAY_FRAME_ANALYSIS_SPEC.md.
#
#   lead    0 s -> 0.692     lead   30 s -> 0.688
#   lead   60 s -> 0.568     lead   90 s -> 0.529     lead  120 s -> 0.516
#
# CONSEQUENCE, and the reason `drake_pathing_verdict` refuses a long lead: any
# verdict at 60 s or beyond is not supported by this data. Do not widen the
# lead without re-running the calibration - see tests for the guard.
SIGNAL_DECAY = {0: 0.692, 30: 0.688, 60: 0.568, 90: 0.529, 120: 0.516}
SUPPORTED_LEAD_MAX_S = 30


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
    item_ids: list = field(default_factory=list)


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
    killer_team_id: int = 0


@dataclass
class Timeline:
    frames: list = field(default_factory=list)
    events: list = field(default_factory=list)
    frame_interval_ms: int = 60000
    # Whether frames carry real map coordinates. The :2999 seek producer sets
    # this False - Riot exposes no champion coordinates there, so x/y are 0 and
    # any distance computed from them would measure from the map origin.
    positions_available: bool = True


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
    secured: bool = False       # did THIS player's team take the objective
    lead_s: float = DEFAULT_LEAD_S


def team_of(participant_id: int) -> int:
    """Match-V5 seats 1-5 on team 100 and 6-10 on team 200.

    Verified, not assumed: 460 of 460 participants across all 46 corpus
    matches agree, 0 exceptions.
    """
    return 100 if participant_id <= 5 else 200


def normalize_timeline(raw) -> Timeline:
    """Match-V5 timeline blob -> the neutral shape every derivation consumes."""
    info = (raw or {}).get("info") or {}
    tl = Timeline(frame_interval_ms=int(info.get("frameInterval") or 60000),
                  positions_available=True)
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
                ward_type=str(ev.get("wardType") or ""),
                killer_team_id=int(ev.get("killerTeamId") or 0)))
    return tl


def objective_events(tl: Timeline, monster: str = "DRAGON") -> list:
    return [e for e in tl.events
            if e.type == "ELITE_MONSTER_KILL" and e.monster_type == monster]


def position_at(tl: Timeline, participant_id: int, t_ms: int):
    """Nearest frame sample to *t_ms*, or None if the player never appears.

    Returns the sampling error rather than hiding it: at a 60 s interval the
    answer can be up to half an interval away from the moment asked about.
    """
    if not tl.positions_available:
        raise ValueError(
            "this timeline has no position data (produced by a source that "
            "exposes no map coordinates); a distance derivation cannot run "
            "on it")
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
        # SR side is the sign of (x - y), the main diagonal from base to base:
        # bot-right is x > y, top-left is y > x.
        #
        # NOT (x + y) vs the map size - that is the ANTI-diagonal, which
        # measures how far advanced toward the enemy base a player is, not
        # which side of the map they are on. Measured consequence of getting
        # this wrong: DRAGON_PIT sums to 14280 against a 14820 map, so the
        # drake pit itself classified as top side and a jungler standing
        # 3063 units from the pit was reported "opposite half of the map".
        same = ((sample.x - sample.y) > 0) == ((target[0] - target[1]) > 0)
        out.append(Approach(lead_s=lead,
                            distance=_distance((sample.x, sample.y), target),
                            same_half=same, sample_age_s=sample.age_s))
    return out


def drake_pathing_verdict(tl: Timeline, participant_id: int,
                          lead_s: float = DEFAULT_LEAD_S) -> list:
    """One verdict per drake: was this jungler in position, or late?

    Deliberately narrow. It exists to prove the pipeline answers a real
    question end to end, not to be a general pathing model.

    Raises on a lead beyond SUPPORTED_LEAD_MAX_S. That is not defensiveness -
    the calibration measured the signal decaying to 0.516 by 120 s, so a
    long-lead verdict would be a confident statement about noise.
    """
    if lead_s > SUPPORTED_LEAD_MAX_S:
        raise ValueError(
            f"lead_s={lead_s} exceeds the calibrated support of "
            f"{SUPPORTED_LEAD_MAX_S}s; measured accuracy falls to "
            f"{SIGNAL_DECAY.get(60, 0):.3f} at 60s. Re-run the calibration "
            f"before widening it.")
    if not tl.positions_available:
        raise ValueError(
            "this timeline has no position data; the drake pathing verdict is "
            "distance-based and cannot run on it")
    my_team = team_of(participant_id)
    out = []
    for ev in objective_events(tl, "DRAGON"):
        ap = objective_approach(tl, participant_id, ev, leads_s=(lead_s,))
        if not ap:
            continue
        a = ap[0]
        secured = ev.killer_team_id == my_team
        at = f"{ev.t_ms / 1000:.0f}s"
        if a.distance <= FAR_UNITS:
            verdict = "IN_POSITION"
            line = (f"In position {lead_s:.0f}s before the drake at {at} "
                    f"({a.distance:.0f} units out); "
                    + ("your team took it." if secured else "the enemy took it."))
        elif not a.same_half:
            verdict = "LATE"
            line = (f"Opposite half of the map {lead_s:.0f}s before the drake "
                    f"at {at} ({a.distance:.0f} units out); "
                    + ("your team took it anyway." if secured
                       else "the enemy took it."))
        else:
            verdict = "TRAILING"
            line = (f"Right side but {a.distance:.0f} units off the drake at "
                    f"{at}, {lead_s:.0f}s prior; "
                    + ("secured." if secured else "lost it."))
        out.append(Verdict(t_ms=ev.t_ms, verdict=verdict, distance=a.distance,
                           coaching=line, source="match_v5_timeline",
                           sample_age_s=a.sample_age_s, secured=secured,
                           lead_s=lead_s))
    return out
