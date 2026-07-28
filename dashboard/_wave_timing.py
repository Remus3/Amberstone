"""R221 - pure deterministic wave SPAWN CLOCK over the ``MinionsSpawning`` anchor.

Consumes ``minion_spawn_events`` as emitted by ``dashboard/_liveclient.py``
(rows of ``{"spawn_at_s": float, "event_id": int | None}``, stream order) plus a
game clock, and answers only what a spawn anchor plus a cadence can actually
support: which wave has landed, when the last one landed, when the next one
lands, and whether that next one carries the siege minion.

SCOPE FENCE - READ BEFORE ADDING A KEY
--------------------------------------
This module MUST NOT emit ``wave_top`` / ``wave_mid`` / ``wave_bot``, and MUST
NOT emit a FREEZE / TRADE / CRASH / DISENGAGE verb or any lane push percentage.
Those belong to a wave STATE machine, which ROADMAP RM-124 declares data-blocked
three ways: ``:2999`` exposes no minion entities, the Overlay Platform M GEP contract
gives ``minionKills`` counts only, and Match-V5 has no minion event type - so
nothing wave-shaped is even backfillable from the match corpus. A spawn clock
knows WHEN a wave left the nexus; it cannot know WHERE that wave sits in a lane,
who last hit into it, or which way it is pushing. Deriving a lane state from
spawn timing would be fabrication, and a wrong precompute is worse than no
precompute - the dead 3-lane readout at ``web/js/panels/next.js:16-83`` stays
dead until a real producer exists. ``tests/test_wave_timing.py`` pins the
returned key set exactly, so adding one of those keys fails the suite.

Every value is honest-None when unknown, and a no-data call returns ALL keys
None rather than a partially-guessed readout.
"""
from __future__ import annotations

import math
import statistics

# Ordered ``(from_game_time_s, every_n_waves)`` breakpoints: the siege minion
# rides every Nth wave from that game time onward.
#
# WHY THIS IS A TABLE AND NOT INLINE ARITHMETIC: the sources conflict, so the
# conflict is confined to one reviewable place. wiki.leagueoflegends.com/en-us/
# Minion puts the first cadence break at 14:00 (every 3rd wave before it, every
# 2nd until 25:00, every wave after); other prose in circulation puts that same
# break at 15:00. Separately, a 2025 change moved first-cannon ARRIVAL from 2:05
# to 2:35, which shifts the wave-ordinal the first siege rides and therefore the
# parity this modulo depends on. The wiki figure is taken here because it is the
# one source cited with a version, not because the disagreement is resolved.
#
# LIVE-GATED: unvalidated against a real game as of 2026-07-28. Both the 14:00
# break and the ordinal parity need one observed game before this readout is
# trusted for anything beyond display. Do not retune a breakpoint without a
# live observation - the boundary tests pin these literals so a silent edit
# cannot pass.
_CANNON_CADENCE = (
    (0.0, 3),
    (840.0, 2),     # 14:00 per the wiki; a competing source says 15:00 (900.0)
    (1500.0, 1),    # 25:00 - both sources agree here
)

# Fallback spacing, reached ONLY when a single event gives no observed gap to
# measure. It is deliberately the weakest input in the module: the wave interval
# is itself piecewise (30s, then 25s, then 20s in the same wiki entry), so a
# constant is wrong for most of a game. Two events beat it immediately.
_DEFAULT_WAVE_INTERVAL_S = 30.0

# The elapsed-time floor below is a division of one float by another, and a
# clock sitting exactly one interval past the anchor can land a hair under the
# integer boundary in binary - which would drop the wave that just spawned and
# report a full-interval countdown for a wave already on the field.
_FLOOR_EPS_S = 1e-9

# Sub-second precision is noise for a spawn readout, and unrounded float
# arithmetic surfaces artifacts like 214.99999999999997 straight into a UI cell.
_ROUND_DP = 3

_KEYS = ("wave_number", "last_spawn_s", "next_spawn_s", "next_spawn_in_s",
         "next_is_cannon", "cannon_every_n_waves")


def _is_number(value) -> bool:
    # bool is an int subclass, so an unguarded isinstance check reads True as
    # game time 1.0 - a plausible-looking clock that is pure garbage.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _spawn_times(rows) -> list:
    """Valid spawn times, ascending.

    Sorted rather than trusted in stream order because the ordinal is derived
    positionally: one out-of-order row would otherwise mis-number every wave
    after it, and the sort costs nothing on an already-ordered list.
    """
    if not isinstance(rows, (list, tuple)):
        return []
    times = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("spawn_at_s")
        if not _is_number(value):
            continue
        times.append(float(value))
    times.sort()
    return times


def _observed_interval(times: list) -> float:
    """Wave spacing measured off the stream, with the constant as last resort.

    MEDIAN, not mean and not last-gap: a dropped or coalesced event leaves one
    doubled gap in an otherwise regular series, and a mean would smear that
    outlier across the whole projection while the median ignores it.
    """
    gaps = []
    for i in range(1, len(times)):
        gap = times[i] - times[i - 1]
        if gap > 0:
            gaps.append(gap)
    if not gaps:
        return _DEFAULT_WAVE_INTERVAL_S
    return float(statistics.median(gaps))


def _cadence_at(game_time_s: float) -> int | None:
    every_n = None
    for from_s, value in _CANNON_CADENCE:
        if game_time_s >= from_s:
            every_n = value
        else:
            break
    return every_n


def wave_timing(minion_spawn_events: list, game_time_s: float | None) -> dict:
    """Return the wave spawn-clock readout for ``game_time_s``.

    Keys: ``wave_number`` (1-based ordinal of the most recent wave to have
    spawned), ``last_spawn_s``, ``next_spawn_s``, ``next_spawn_in_s``,
    ``next_is_cannon``, ``cannon_every_n_waves``. Any key whose answer is not
    derivable is None; with no usable input every key is None.
    """
    # Built fresh per call - a module-level sentinel would let one caller's
    # mutation leak into every later no-data readout.
    out = dict.fromkeys(_KEYS)

    if not _is_number(game_time_s):
        return out
    now = float(game_time_s)

    times = _spawn_times(minion_spawn_events)
    if not times:
        return out

    interval = _observed_interval(times)

    spawned = [t for t in times if t <= now]
    if spawned:
        last_spawn = spawned[-1]
        # Waves that landed after the newest event we hold. Normally zero; it
        # goes positive when the caller's snapshot is stale, and projecting
        # them is what keeps the countdown forward-looking instead of frozen on
        # an old anchor. The ordinal has to absorb the same projection or
        # next_is_cannon would be computed against a stale wave number.
        unobserved = int(math.floor((now - last_spawn + _FLOOR_EPS_S) / interval))
        next_spawn = last_spawn + (unobserved + 1) * interval
        out["last_spawn_s"] = last_spawn
        out["wave_number"] = len(spawned) + unobserved
        next_wave_number = out["wave_number"] + 1
    else:
        # Nothing has fired yet at this clock. The stream is cumulative-past in
        # a real game so this is defensive, but counting an unfired wave would
        # be a fabricated ordinal - leave wave_number and last_spawn_s None and
        # report only the arrival we can see coming.
        next_spawn = times[0]
        next_wave_number = 1

    out["next_spawn_s"] = round(next_spawn, _ROUND_DP)
    # Clamped as a floor guarantee for consumers rendering a countdown; the
    # projection above already makes next_spawn strictly greater than now.
    out["next_spawn_in_s"] = max(0.0, round(next_spawn - now, _ROUND_DP))

    # Reported cadence is the one in force NOW (what the player is playing
    # under); the cannon test uses the cadence in force when that wave actually
    # spawns. The two differ only in the seconds spanning a breakpoint, and
    # answering each question at its own instant beats one blended answer.
    out["cannon_every_n_waves"] = _cadence_at(now)
    cadence_at_next = _cadence_at(next_spawn)
    if cadence_at_next:
        out["next_is_cannon"] = next_wave_number % cadence_at_next == 0

    return out
