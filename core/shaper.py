"""
core/shaper.py - Interactive Item Shaper backend primitive.

BACKEND-ONLY. No UI surface. Scoped from the BACKLOG entry
"Interactive Item Shaper (post-DS-100%)" - the underlying scorer surface
is solid (6 archetype scorers wired, 547/705 items, no fallbacks) so we
can ship the primitive ahead of DS 100% coverage. The UI layer remains
blocked on DS 100% per operator gate.

Surface (this module is the ONLY public boundary):

  ShaperState(damage_nudge, survivability_nudge, utility_nudge)
      Frozen dataclass; ints clamped to {-2, -1, 0, +1, +2}. Values
      outside the range raise ValueError at construction time so a bad
      caller fails loud, not silently.

  apply_shaper(weights: dict, shaper: ShaperState) -> dict
      Pure function. Takes an archetype scorer's weight dict and returns
      a NEW dict (input never mutated) with each axis nudged by
      +/- 0.075 per knob step. After all 3 knobs apply, weights are
      clamped to [0.05, 0.90] and renormalized to sum to 1.0.

Axis classification is by substring match on the dict keys:
  - "damage"        -> damage axis (e.g. Bruiser 'damage_alpha')
  - "survivability" -> survivability axis (e.g. Bruiser 'survivability_beta')
  - "utility"       -> utility axis (e.g. Bruiser 'utility_gamma')

Keys that match no axis are passed through unchanged (kept in the
returned dict at their original value, and the renorm step accounts
for them so the FULL dict still sums to 1.0).

Degenerate guard: if after the per-axis math the weights collapse to
all-zero or all-identical, the original dict is returned unchanged
and a warning is logged. This is the "snap back to baseline" failsafe
the operator-facing UI will hit if a user presses all knobs the same
direction repeatedly.

Non-engine module. Does NOT alter the scorer weights at their source
in `agents/daemon_slayer/rank.py` - the shaper transforms a copy at
call-time only; the scorer dict is the source of truth. No
ENGINE_VERSION bump is owed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger(__name__)

# Tuning constants. NUDGE_STEP is the per-click shift applied to the
# raw axis weight BEFORE clamp + renorm; 0.075 was chosen so that the
# typical Bruiser baseline (0.65 / 0.35 / 0.0) shifts by roughly the
# +/- 0.10-0.15 range the BACKLOG note sketched (alpha 0.65 -> ~0.80
# with DAMAGE+1 after renorm, ~0.45 with SURVIVABILITY+1 after renorm).
NUDGE_STEP: float = 0.075
WEIGHT_MIN: float = 0.05
WEIGHT_MAX: float = 0.90
KNOB_MIN: int = -2
KNOB_MAX: int = 2

# Substring tags used to classify dict keys to axes. Lowercased compare.
_AXIS_TAGS = {
    "damage": "damage",
    "survivability": "survivability",
    "utility": "utility",
}


@dataclass(frozen=True)
class ShaperState:
    """Three knobs. Each in {-2, -1, 0, +1, +2}. Frozen, hashable."""

    damage_nudge: int = 0
    survivability_nudge: int = 0
    utility_nudge: int = 0

    def __post_init__(self) -> None:
        for name, val in (
            ("damage_nudge", self.damage_nudge),
            ("survivability_nudge", self.survivability_nudge),
            ("utility_nudge", self.utility_nudge),
        ):
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValueError(
                    f"ShaperState.{name} must be int, got {type(val).__name__}"
                )
            if val < KNOB_MIN or val > KNOB_MAX:
                raise ValueError(
                    f"ShaperState.{name}={val} out of range "
                    f"[{KNOB_MIN}, {KNOB_MAX}]"
                )


def _classify_axis(key: str) -> str | None:
    """Return 'damage' / 'survivability' / 'utility' / None for a key."""
    lk = key.lower()
    # Order matters only for disambiguation; substrings here are
    # disjoint in every archetype scorer dict we ship.
    for tag, axis in _AXIS_TAGS.items():
        if tag in lk:
            return axis
    return None


def _degenerate(values: list[float]) -> bool:
    """All zero OR all identical to within float epsilon."""
    if not values:
        return True
    if all(abs(v) < 1e-12 for v in values):
        return True
    first = values[0]
    return all(abs(v - first) < 1e-12 for v in values)


def apply_shaper(weights: Dict[str, float], shaper: ShaperState) -> Dict[str, float]:
    """
    Apply the three knobs to a weight dict and return a NEW dict.

    The returned dict has the same keys as the input. Values are
    clamped to [WEIGHT_MIN, WEIGHT_MAX] per-key then the whole dict is
    renormalized so values sum to 1.0. If the result collapses
    (all-zero / all-identical) the ORIGINAL dict is returned unchanged.

    `weights` is never mutated.
    """
    if not weights:
        return dict(weights)

    # 1) Compute per-axis shift from knobs.
    shifts = {
        "damage": shaper.damage_nudge * NUDGE_STEP,
        "survivability": shaper.survivability_nudge * NUDGE_STEP,
        "utility": shaper.utility_nudge * NUDGE_STEP,
    }

    # 2) Apply shift per key (axis-classified), copy into a new dict.
    #    Track which keys were ACTUALLY nudged so the clamp floor only
    #    applies where a shift moved the weight - a baseline value of
    #    0.0 on a legitimately-disabled axis with zero knob must round
    #    -trip to 0.0 unchanged (identity invariant).
    nudged: Dict[str, float] = {}
    was_shifted: Dict[str, bool] = {}
    for key, val in weights.items():
        axis = _classify_axis(key)
        if axis is not None:
            shift = shifts[axis]
            nudged[key] = float(val) + shift
            was_shifted[key] = abs(shift) > 1e-12
        else:
            nudged[key] = float(val)
            was_shifted[key] = False

    # 3) Clamp each value. Floor applies only to shifted keys (see
    #    above) so we do not silently inflate a 0.0 baseline; ceiling
    #    applies to all keys defensively against pathological input.
    clamped = {
        k: (
            max(WEIGHT_MIN, min(WEIGHT_MAX, v))
            if was_shifted[k]
            else min(WEIGHT_MAX, v)
        )
        for k, v in nudged.items()
    }

    # 4) Degenerate guard. If the clamp produced all-zero or
    #    all-identical values across the keys, snap back to baseline.
    clamp_values = list(clamped.values())
    if _degenerate(clamp_values):
        logger.warning(
            "shaper: degenerate post-clamp weight distribution "
            "(keys=%s clamp_values=%s knobs=%s) - returning baseline",
            list(weights.keys()),
            clamp_values,
            (
                shaper.damage_nudge,
                shaper.survivability_nudge,
                shaper.utility_nudge,
            ),
        )
        return dict(weights)

    # 5) Renormalize to sum to 1.0.
    total = sum(clamp_values)
    if total <= 0.0:
        # Caught by _degenerate above for the all-zero case; defensive
        # fallback in case a future axis ever produces a negative.
        logger.warning(
            "shaper: non-positive sum after clamp (%.6f) - returning baseline",
            total,
        )
        return dict(weights)

    return {k: v / total for k, v in clamped.items()}


__all__ = ["ShaperState", "apply_shaper", "NUDGE_STEP", "WEIGHT_MIN", "WEIGHT_MAX"]
