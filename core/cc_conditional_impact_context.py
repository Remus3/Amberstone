"""Aggregate enemy CONDITIONAL CC pressure -> blended-EHP impact coach-prompt consumer.

FIRST coach-prompt consumer of the ``cc_conditional`` registry (item 141
Slice B ``7233568`` forward-marker module at ENGINE 1.37.0; item 142
Slice A ``8335ce1`` first engine math consumer via
``compute_cc_pressure(include_conditional=True)`` at ENGINE 1.38.0;
items 143 Slice A ``172ad6f`` + Slice B ``9173e56`` second + third
engine math consumers via ``compute_ehp`` + ``compute_hybrid`` at ENGINE
1.39.0).

This is the 4TH OVERALL CONSUMER of the cc_conditional ecosystem and
the FIRST coach-prompt consumer (the prior 3 are all engine math).

Sibling of ``core.cc_blended_ehp_context.cc_blended_ehp_impact_line``
(item 138 Slice A ``738c005`` - first coach-prompt consumer of
unconditional ``compute_cc_pressure``). The two renderers compose:
the unconditional line summarizes max-rank registered first-order CC
across enemies, this conditional line summarizes the additional
probability-weighted contribution from the conditional registry (23
entries / 23 champs at ENGINE 1.39.0 across the 10 condition tags
nth_hit / gold_card / terrain / channel_completion / dream_stack /
devour / target_hp_below / debuffed_target / dual_enemy / mode_gated).

Math reads ``compute_cc_pressure(champion, mode, include_conditional=True)``
and consumes the ``conditional_cc_seconds`` field DIRECTLY (already
post-tenacity probability-weighted by the engine seam at ENGINE 1.38.0;
no manual subtraction needed). Aggregates across enemies and renders
the bounded saturation + EHP impact per the SAME math model as the
unconditional sibling.

  conditional_total = sum(
      compute_cc_pressure(e, mode, include_conditional=True)
          .conditional_cc_seconds
      for e in enemies if e
  )
  cc_pressure_fraction = min(conditional_total / fight_window_s, 1.0)
  effective_ehp_loss_pct = cc_pressure_fraction * cc_effectiveness_factor * 100

``_FIGHT_WINDOW_S = 6.0`` + ``_CC_EFFECTIVENESS_FACTOR = 0.5`` match
``agents/daemon_slayer/ehp.py`` constants EXACTLY (operator-tunable
midpoints per item 137 + 138 don't-redo: "defaults MUST match
agents/daemon_slayer/ehp.py exactly"). Kwargs let callers override per
call (testing / future calibration) but the defaults are pinned.

Output line format (probability-weighted is the key disambiguator
versus the unconditional sibling):

    Enemy conditional CC pressure: 4.2s probability-weighted (additive on top of unconditional CC)

Returns "" when:
  * mode is None / blank
  * enemies is None / empty
  * sum of conditional_cc_seconds across enemies is 0.0 (no registered
    conditional CC among the enemy team - the common case at 23 of 172
    champs registered)

Mode-agnostic: SR / ARAM / KIWI / Arena / Brawl / NB / URF / OFA all
flow through ``compute_cc_pressure`` which handles per-mode tenacity
(ARAM lengthens conditional CC on the 17 modified-tenacity champs via
the SAME ``effective_cc_duration`` engine seam; SR is identity).
"""

from __future__ import annotations

from typing import Iterable

try:
    # Item 142 Slice A ``8335ce1`` ships
    # ``agents.daemon_slayer.cc_pressure.compute_cc_pressure(
    #     champion, mode, include_conditional=False)``. The parallel-
    # slice ship pattern (orchestrator merges sequentially) may import
    # this consumer BEFORE the engine module is reloaded on a given
    # branch. The fallback stub returns None so the renderer produces
    # an empty line cleanly (matches the contract "empty result when
    # champion not in registry"). Mirrors the
    # ``core.cc_blended_ehp_context`` fallback verbatim.
    from agents.daemon_slayer.cc_pressure import compute_cc_pressure
except ImportError:  # pragma: no cover - exercised only pre-merge
    def compute_cc_pressure(  # type: ignore[misc]
        champion: str, mode: str = "SR", *, include_conditional: bool = False,
    ):
        return None


# These constants MUST match agents/daemon_slayer/ehp.py exactly per
# items 137 + 138 don't-redo. Per-call kwargs allow override
# (calibration / testing) but the defaults are the operator-tunable
# midpoints.
_FIGHT_WINDOW_S = 6.0
_CC_EFFECTIVENESS_FACTOR = 0.5


def cc_conditional_impact_line(
    enemies: Iterable[str | None] | None,
    mode: str | None,
    *,
    fight_window_s: float = _FIGHT_WINDOW_S,
    cc_effectiveness_factor: float = _CC_EFFECTIVENESS_FACTOR,
) -> str:
    """Render a one-line aggregate enemy CONDITIONAL CC pressure -> blended-EHP impact.

    Reads ``compute_cc_pressure(enemy, mode, include_conditional=True)``
    for each enemy, sums the ``conditional_cc_seconds`` field (already
    post-tenacity probability-weighted by the engine seam) across the
    enemy team, derives the bounded saturation fraction and the
    conservative-midpoint EHP impact, and returns a single prompt-
    friendly line additive on top of the unconditional sibling.

    Returns "" when:
      * mode is None / blank
      * enemies is None / empty
      * sum of conditional_cc_seconds across enemies is 0.0 (no enemy
        carries a registered conditional CC entry)
      * fight_window_s is non-positive (defensive - prevents
        div-by-zero)

    Mode-agnostic: SR / ARAM / KIWI / Arena / Brawl all flow through
    ``compute_cc_pressure``. ARAM uses tenacity-lengthened durations
    through the same ``effective_cc_duration`` engine seam as the
    unconditional path; other modes use the base.

    Blank / None entries in ``enemies`` are silently skipped (matches
    the sibling ``cc_blended_ehp_impact_line`` contract).
    """
    if not mode:
        return ""
    if not enemies:
        return ""
    if fight_window_s <= 0:
        return ""

    conditional_total = 0.0
    for name in enemies:
        if not name:
            continue
        try:
            result = compute_cc_pressure(
                name, mode, include_conditional=True
            )
        except Exception:  # noqa: BLE001
            continue
        if result is None:
            continue
        try:
            cc = float(
                getattr(result, "conditional_cc_seconds", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            continue
        if cc > 0:
            conditional_total += cc

    if conditional_total <= 0.0:
        return ""

    cc_pressure_fraction = min(
        conditional_total / fight_window_s, 1.0
    )
    effective_ehp_loss_pct = (
        cc_pressure_fraction * cc_effectiveness_factor * 100.0
    )

    return (
        f"Enemy conditional CC pressure: "
        f"{conditional_total:.1f}s probability-weighted "
        f"(additive on top of unconditional CC) = "
        f"{cc_pressure_fraction * 100:.0f}% saturation, "
        f"blended-EHP impact -{effective_ehp_loss_pct:.0f}%"
    )


__all__ = [
    "cc_conditional_impact_line",
]
