"""Aggregate enemy CC pressure -> blended-EHP impact coach-prompt consumer.

Closes item 137 carry (a) coach-prompt half: first coach-prompt consumer
of the ``cc_blended_ehp`` math model shipped item 137 Slice A ``99164e8``
(ENGINE 1.33.0 - 2nd engine math consumer of ``compute_cc_pressure``).

Sibling of ``core.enemy_cc_threat_context.enemy_cc_threat_line`` (item 136
Slice B per-enemy CC breakdown) and ``core.aram_tenacity_context``. This
renderer summarizes the AGGREGATE EHP impact across all enemies in a
single prompt-friendly line; per-enemy detail lives in enemy_cc_threat_line.

Math mirrors ``agents.daemon_slayer.ehp.compute_ehp`` exactly:
  total_cc_seconds = sum(compute_cc_pressure(e, mode).total_cc_seconds for e in enemies)
  cc_pressure_fraction = min(total_cc_seconds / fight_window_s, 1.0)
  effective_ehp_loss_pct = cc_pressure_fraction * cc_effectiveness_factor * 100

``_FIGHT_WINDOW_S = 6.0`` + ``_CC_EFFECTIVENESS_FACTOR = 0.5`` match
``ehp.py`` constants exactly (operator-tunable midpoints per item 137
don't-redo: "do NOT change defaults - they MUST match
agents/daemon_slayer/ehp.py exactly"). Kwargs let callers override per
call (testing / future calibration) but the defaults are pinned.

Output line format:

    Enemy CC pressure: 2.5s over 6s fight = 42% saturation, blended-EHP impact -21%

Returns "" when:
  * mode is None / blank
  * enemies is None / empty
  * sum of total_cc_seconds across enemies is 0.0

Mode-agnostic: SR / ARAM / KIWI / Arena / Brawl all flow through
``compute_cc_pressure`` which handles per-mode tenacity (ARAM lengthens
CC on the 17 modified-tenacity champs; SR is identity).
"""

from __future__ import annotations

from typing import Iterable

try:
    # Slice A of item 136 ships ``agents.daemon_slayer.cc_pressure``;
    # the parallel-slice ship pattern (orchestrator merges sequentially)
    # may import this consumer BEFORE the engine module exists in a
    # given branch. The fallback stub returns None so the renderer
    # produces an empty line cleanly (matches the contract "empty
    # result when champion not in registry"). Mirrors the
    # ``core.enemy_cc_threat_context`` fallback verbatim.
    from agents.daemon_slayer.cc_pressure import compute_cc_pressure
except ImportError:  # pragma: no cover - exercised only pre-merge
    def compute_cc_pressure(champion: str, mode: str = "SR"):  # type: ignore[misc]
        return None


# These constants MUST match agents/daemon_slayer/ehp.py exactly per
# item 137 don't-redo. Per-call kwargs allow override (calibration /
# testing) but the defaults are the operator-tunable midpoints.
_FIGHT_WINDOW_S = 6.0
_CC_EFFECTIVENESS_FACTOR = 0.5


def cc_blended_ehp_impact_line(
    enemies: Iterable[str | None] | None,
    mode: str | None,
    *,
    fight_window_s: float = _FIGHT_WINDOW_S,
    cc_effectiveness_factor: float = _CC_EFFECTIVENESS_FACTOR,
) -> str:
    """Render a one-line aggregate enemy CC pressure -> blended-EHP impact.

    Reads ``compute_cc_pressure(enemy, mode).total_cc_seconds`` for each
    enemy, sums the totals across the enemy team, derives the bounded
    saturation fraction and the conservative-midpoint EHP impact, and
    returns a single prompt-friendly line.

    Returns "" when:
      * mode is None / blank
      * enemies is None / empty
      * sum of total_cc_seconds across enemies is 0.0 (no registered CC)
      * fight_window_s is non-positive (defensive - prevents div-by-zero)

    Mode-agnostic: SR / ARAM / KIWI / Arena / Brawl all flow through
    ``compute_cc_pressure``. ARAM uses tenacity-lengthened durations
    (the engine seam applies per-spell); other modes use the base.

    Blank / None entries in ``enemies`` are silently skipped (matches
    the enemy_cc_threat_line contract).
    """
    if not mode:
        return ""
    if not enemies:
        return ""
    if fight_window_s <= 0:
        return ""

    total_cc_seconds = 0.0
    for name in enemies:
        if not name:
            continue
        try:
            result = compute_cc_pressure(name, mode)
        except Exception:  # noqa: BLE001
            continue
        if result is None:
            continue
        try:
            cc = float(getattr(result, "total_cc_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if cc > 0:
            total_cc_seconds += cc

    if total_cc_seconds <= 0.0:
        return ""

    cc_pressure_fraction = min(total_cc_seconds / fight_window_s, 1.0)
    effective_ehp_loss_pct = (
        cc_pressure_fraction * cc_effectiveness_factor * 100.0
    )

    return (
        f"Enemy CC pressure: {total_cc_seconds:.1f}s over "
        f"{fight_window_s:.0f}s fight = "
        f"{cc_pressure_fraction * 100:.0f}% saturation, "
        f"blended-EHP impact -{effective_ehp_loss_pct:.0f}%"
    )


__all__ = [
    "cc_blended_ehp_impact_line",
]
