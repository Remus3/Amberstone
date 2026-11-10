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

The registry counts above are the AUTHORING-TIME record (ENGINE 1.39.0);
the registry has grown since, so read
``agents/daemon_slayer/cc_conditional_registry.json`` for a live count.

NAMES (s144 true-audit)
    Every coach passes the Live Client roster, whose ``championName`` is a
    DISPLAY name ("Twisted Fate", "Nunu & Willump", "Tahm Kench"), while
    the cc_conditional registry keys on canonical DDragon ids
    ("TwistedFate", "Nunu", "TahmKench"). Each entry is stripped and
    resolved through ``core.archetype_picks.canonical_champion_id`` before
    the engine read (the same bridge ``core.enemy_cc_threat_context``
    uses); a resolver failure falls back to the stripped name. The roster
    is NOT de-duplicated: ONEFORALL fields five copies of one champion and
    each carries its own conditional CC.

FAIL-SOFT
    Never raises out of a coach prompt build. A mode that is not a
    non-blank str, a roster that is not a list / tuple (a bare string is
    NOT iterated per character), a non-str, blank or oversized entry, a
    ``fight_window_s`` that is not a positive finite number, a
    ``cc_effectiveness_factor`` outside [0, 1], and a non-finite, bool or
    non-number engine value all degrade to "" or skip that one entry. At
    most ``_MAX_ENEMIES`` entries are read. An engine failure is skipped
    and logged at debug.
"""

from __future__ import annotations

import logging
import math

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

_log = logging.getLogger(__name__)

# Upper bound on roster entries read per call. The widest live roster is
# Arena (7 enemy duos = 14); the bound only stops a junk list from
# driving an unbounded number of engine reads.
_MAX_ENEMIES = 32
# No champion display name or id is anywhere near this long; a longer
# entry is junk, not a champion.
_MAX_NAME_LEN = 64


def _canonical_id(name: str) -> str:
    """Resolve a Live Client display name to its canonical DDragon id.

    Lazy import, fail-soft: any resolver failure returns ``name`` itself
    (a canonical id still matches the registry; a display form does not).
    """
    try:
        from core.archetype_picks import canonical_champion_id

        cid = canonical_champion_id(name)
    except Exception:  # noqa: BLE001 - fail-soft resolver, never break a prompt
        _log.debug("cc_conditional_impact: id resolve failed for %r", name,
                   exc_info=True)
        return name
    return cid if isinstance(cid, str) and cid else name


def _finite_number(value: object) -> float | None:
    """``float(value)`` for a finite int / float (never a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except OverflowError:
        return None
    return out if math.isfinite(out) else None


def cc_conditional_impact_line(
    enemies: list[str | None] | tuple[str | None, ...] | None,
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
      * mode is not a non-blank str
      * enemies is not a list / tuple, or is empty
      * sum of conditional_cc_seconds across enemies is 0.0 (no enemy
        carries a registered conditional CC entry)
      * fight_window_s is not a positive finite number (prevents
        div-by-zero and a "nan%" line)
      * cc_effectiveness_factor is not a finite number in [0, 1]

    Mode-agnostic: SR / ARAM / KIWI / Arena / Brawl all flow through
    ``compute_cc_pressure``. ARAM uses tenacity-lengthened durations
    through the same ``effective_cc_duration`` engine seam as the
    unconditional path; other modes use the base.

    Each entry is a Live Client display name or a canonical id; it is
    stripped and resolved to the canonical id before the engine read.
    Blank / None / non-str / oversized entries are skipped (matches the
    sibling ``cc_blended_ehp_impact_line`` contract for blank / None).
    """
    if not isinstance(mode, str) or not mode.strip():
        return ""
    mode = mode.strip()
    if not isinstance(enemies, (list, tuple)) or not enemies:
        return ""
    window = _finite_number(fight_window_s)
    if window is None or window <= 0.0:
        return ""
    factor = _finite_number(cc_effectiveness_factor)
    if factor is None or not 0.0 <= factor <= 1.0:
        return ""

    conditional_total = 0.0
    for raw in enemies[:_MAX_ENEMIES]:
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not name or len(name) > _MAX_NAME_LEN:
            continue
        champion_id = _canonical_id(name)
        try:
            result = compute_cc_pressure(
                champion_id, mode, include_conditional=True
            )
        except Exception:  # noqa: BLE001 - engine seam is fail-soft by contract
            _log.debug("cc_conditional_impact: compute_cc_pressure failed "
                       "for %r", champion_id, exc_info=True)
            continue
        if result is None:
            continue
        cc = _finite_number(getattr(result, "conditional_cc_seconds", 0.0))
        if cc is not None and cc > 0.0:
            conditional_total += cc

    if not math.isfinite(conditional_total) or conditional_total <= 0.0:
        return ""

    cc_pressure_fraction = min(conditional_total / window, 1.0)
    effective_ehp_loss_pct = cc_pressure_fraction * factor * 100.0

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
