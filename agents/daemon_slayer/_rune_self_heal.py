"""R142-S1: RUNE-side SELF-HEAL registry, keyed by rune id (Second Wind 8444).

The THIRD rune-side survivability lane, and the one that closes the last
unmodelled self-side Resolve rune. Its two siblings own different terms:

  * ``_rune_resist_grants``  -> bonus armor / MR. EHP DENOMINATOR.
  * ``_rune_health_grants``  -> permanent max HP + a per-proc self-heal. EHP
    NUMERATOR, but both of its halves are gated on LANDING A BASIC ATTACK
    (Grasp) or on ABSORBING MINIONS (Overgrowth).
  * ``_rune_self_heal``      (this module) -> a pure INCOMING-DAMAGE-triggered
    regeneration heal. EHP NUMERATOR.

WHY THIS IS A DISTINCT LANE FROM GRASP'S SELF-HEAL. ``_rune_health_grants``
already credits a rune self-heal (Grasp 8437, 1.3% of MAX health per proc), so
the obvious question is whether Second Wind belongs there. It does not, on three
independent axes, and nothing here duplicates anything credited there:

  1. DIFFERENT BASE. Grasp heals a percentage of MAX health - a value that is
     fully known from the resolved build. Second Wind heals a percentage of
     MISSING health, which is a FIGHT-STATE quantity the engine only has via the
     ``ehp.py`` mid-fight share convention. A registry whose per-entry arithmetic
     is ``pct * max_hp`` cannot express ``pct * (max_hp * missing_share)``
     without either bolting a second base selector onto ``RuneHealthEntry`` or
     silently mis-crediting Second Wind at full health.
  2. DIFFERENT TRIGGER DIRECTION. Grasp fires when the wielder DEALS an
     autoattack; Second Wind fires when the wielder TAKES champion damage. That
     inverts the uptime argument entirely (see the amortization note below): a
     modeled EHP fight satisfies Second Wind's trigger BY CONSTRUCTION and does
     not necessarily satisfy Grasp's.
  3. DIFFERENT SHAPE. Grasp is an instantaneous per-proc heal; Second Wind is a
     heal-over-time with a fixed 10s duration, so it is the only rune in the
     three registries whose realized value depends on the length of the modeled
     fight window.

Folding it into the R136 module would have required a base selector, a second
trigger semantic and a duration field on a dataclass built for stack-counted
instantaneous grants. It is a separate registry for the same reason
``_rune_hsp_amp`` is separate from ``_rune_resist_grants``.

DDragon 16.14.1 ``data/meta_build/ddragon/16.14.1/runesReforged.json`` longDesc,
quoted VERBATIM (re-read from raw source for this slice, not paraphrased):

  * 8444 SecondWind: "After taking damage from an enemy champion, heal for 4% of
    your missing health over 10s."

THAT IS THE WHOLE RUNE. There is no AP scaling, no bonus-health scaling, no
cooldown clause, no ranged ``<rules>`` clause and no ally component anywhere in
the longDesc - so this module carries no coefficient the tooltip does not state.
The absence of a ranged factor is deliberate and asserted, mirroring how
``_rune_health_grants`` handles Overgrowth's missing ``<rules>`` clause.

THE MISSING-HEALTH CONVENTION IS REUSED, NOT RE-INVENTED. ``ehp.py:356`` already
defines ``_MISSING_HP_SHARE_FOR_HEALS = 0.5`` - "the Phase 6.5 mid-fight HP-share
assumption for items whose heal piece scales with missing HP" - and ``ehp.py``
resolves the pool ONCE at ``ehp.py:1501`` (``missing_hp = hp *
_MISSING_HP_SHARE_FOR_HEALS``) before handing it to ``_collect_heals``. Second
Wind asks EXACTLY the question that constant answers, so it adopts that value
rather than introducing a second, competing mid-fight share. The R136 finding was
explicit on this point: the convention already exists, which is what makes this
rune buildable today.

The constant is RESTATED here rather than imported, for the same reason
``_rune_health_grants`` restates its Grasp coefficients from ``enemy_runes.py``:
the orchestrator wires this module INTO ``ehp.py``, so importing ``ehp`` back out
of it would create an import cycle. The restatement is held safe by
``ConventionPinTests`` in ``tests/test_rune_self_heal_r142.py``, which imports
BOTH sides - it lives outside the production import graph, so it can hold the
pair at once and goes RED the moment either side is edited alone. Same treatment
for ``_FIGHT_WINDOW_S = 6.0`` (``ehp.py:342``).

AMORTIZATION - WHAT IS EXACT AND WHAT IS AN ASSUMPTION. The MAGNITUDE (4% of
missing health) is EXACT DDragon and is never scaled by a firing probability.
The ONE assumption is the UPTIME treatment, and it is deliberately NOT the
sibling registries' ``_RUNE_ACTIVE_RESIST_PROB`` firing midpoint:

  * THE TRIGGER NEEDS NO PROBABILITY DISCOUNT. Second Wind fires "after taking
    damage from an enemy champion", and the EHP scorers evaluate a SUSTAINED
    FIGHT in which the champion is by definition taking champion damage. Unlike
    Aftershock (needs an immobilize) or Unflinching (needs to be crowd
    controlled), the trigger condition is not a coin flip inside the modeled
    frame - it is the frame's premise. Discounting it by a firing midpoint would
    price in an uncertainty the model does not actually have. This is the ONE
    assumption in this module and it is labelled as such.
  * THE DURATION DOES NEED A DISCOUNT. The heal is spread "over 10s" while the
    engine's modeled engagement is ``_FIGHT_WINDOW_S = 6.0`` seconds
    (``ehp.py:342``, the same window the lifesteal heal pool accumulates over).
    Only the fraction of the regeneration that lands INSIDE that window is
    survivability the scorer may credit; the tail heals after the fight is
    decided. ``_SECOND_WIND_WINDOW_UPTIME`` is therefore ``min(1.0,
    _FIGHT_WINDOW_S / SECOND_WIND_HEAL_DURATION_S)`` = 0.6, DERIVED from the two
    named constants rather than hand-typed, so a future fight-window retune
    carries automatically.

This is strictly more conservative than crediting the full 10s heal and is the
direction the sibling registries' calibration rule requires
(``_passive_health_overrides.py:33-38``: under-credit on purpose so a flipped-on
scorer never OVER-states). ``_SECOND_WIND_WINDOW_UPTIME`` is the single
operator-tunable knob; a future live consumer with a real fight-duration feed
replaces it without re-authoring any math.

RETURNS A BARE FLOAT and takes NO position on how the caller folds it. The heal
is a RAW pre-amplification heal like Grasp's: a caller folding it into
``heal_total`` should add it BEFORE ``heal_amp_mult`` (``ehp.py:791``) so
Revitalize and other heal-power sources apply to it as they do in game. That
seam - and the DEFAULT-OFF flag gating it - belongs to the orchestrator. There is
deliberately NO flag inside this module.

ONE id is SEEDED. This registry is a deliberate ALLOWLIST, not a tree-wide
sweep. Every other Resolve rune was read and ROUTED, not overlooked:

  * 8437 Grasp of the Undying - self-heal + permanent HP. ALREADY CREDITED by
    ``_rune_health_grants`` (R136). Distinct lane per the three axes above.
  * 8451 Overgrowth - permanent max health. ``_rune_health_grants`` (R136).
  * 8439 Aftershock / 8429 Conditioning / 8242 Unflinching - bonus armor / MR.
    ``_rune_resist_grants`` (R132), a DENOMINATOR lane.
  * 8453 Revitalize - Heal and Shield Power. ``_rune_hsp_amp`` (R136-S2). It
    AMPLIFIES heals rather than granting one, so crediting it here would invert
    the direction of the term (and double-count against that registry).
  * 8473 Bone Plating - a flat per-instance damage BLOCK ("30-60 (based on
    level) less damage"), which is the ``_passive_flat_mitigation_overrides`` /
    ``_rune_flat_mitigation`` lane, not a heal.
  * 8446 Demolish - bonus physical damage to TOWERS. Not a survivability term at
    all, and not a champion-combat term.
  * 8463 Font of Life - DATA-BLOCKED, not rejected on merit. Its longDesc is
    "Impairing the movement of an enemy champion restores <healing>@BaseHeal@
    Health</healing> to you and the lowest health nearby allied champion." The
    ``@BaseHeal@`` template variable is UNRESOLVED in all four vendored DDragon
    snapshots (16.11.1 / 16.12.1 / 16.13.1 / 16.14.1 - verified for this slice),
    so the rune has NO extractable magnitude from the only sanctioned data
    source. It cannot be modelled without inventing a coefficient, which the
    exact-magnitude discipline forbids. It is also a two-target heal whose ally
    half is the ``hps.py`` ally-throughput lane.
  * 8465 Guardian - a SHIELD, not a heal, and it is being built in a PARALLEL
    SLICE. Routed away here explicitly so the two slices cannot both credit it.

Keyed by string rune_id to match the engine's id convention (strings throughout);
integer ids are coerced on lookup, and a repeated id is credited at most once (a
rune page cannot carry the same rune twice, so a duplicated or aliased id must
never double-credit - the ``_rune_resist_grants`` ``family`` rationale).

FAIL-SOFT, mirroring ``_rune_hsp_amp.sum_rune_hsp_pct``: an empty / None rune
list, a non-iterable, a non-numeric pool or any lookup failure returns 0.0, so
the orchestrator's DEFAULT-OFF seam stays BYTE-IDENTICAL when the flag is off or
the page carries no self-heal rune.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# --- Second Wind (8444) - EXACT DDragon 16.14.1 magnitudes -------------------
# "heal for 4% of your missing health over 10s". Stored as a FRACTION (0.04 ==
# 4%) to match the _rune_hsp_amp convention for a value that multiplies a pool
# directly, rather than the _rune_resist_grants "75.0 == 75%" convention which
# exists because its consumers are resist magnitudes.
SECOND_WIND_MISSING_HP_PCT: float = 0.04
# "over 10s" - the regeneration duration, load-bearing for the window uptime.
SECOND_WIND_HEAL_DURATION_S: float = 10.0

# --- Engine conventions RESTATED from ehp.py (see the module docstring) ------
# Restated rather than imported to avoid an import cycle once the orchestrator
# wires this module into ehp.py; ConventionPinTests holds the pair and goes RED
# on any drift.

# ehp.py:356 - the Phase 6.5 mid-fight HP-share assumption for heals that scale
# with missing HP. Second Wind asks exactly this question, so it adopts the
# EXISTING convention instead of introducing a second one.
_MISSING_HP_SHARE_FOR_HEALS: float = 0.5

# ehp.py:342 - the modeled sustained-engagement window in seconds, the same one
# the lifesteal heal pool accumulates over.
_FIGHT_WINDOW_S: float = 6.0

# THE ONE ASSUMPTION IN THIS MODULE, and the single operator-tunable knob.
# Second Wind's TRIGGER takes no probability discount - a fight the EHP scorer is
# evaluating is one where the champion is taking champion damage by construction,
# unlike Aftershock's immobilize or Unflinching's crowd-control gate. Its
# DURATION does: only the share of a 10s regeneration that lands inside the 6s
# modeled window is survivability the scorer may credit, and the tail heals after
# the fight is decided. DERIVED from the two named constants above rather than
# hand-typed (0.6 today) so a fight-window retune carries automatically, and
# clamped at 1.0 so a future window longer than the heal cannot over-credit.
# Conservative by construction, per the _passive_health_overrides.py:33-38
# calibration rule (under-credit on purpose so a flipped-on scorer never
# OVER-states). A live fight-duration feed replaces this without touching math.
_SECOND_WIND_WINDOW_UPTIME: float = min(
    1.0, _FIGHT_WINDOW_S / SECOND_WIND_HEAL_DURATION_S
)


@dataclass(frozen=True)
class RuneSelfHealEntry:
    """One rune-keyed SELF-side incoming-damage-triggered heal.

    Every field carries a default so a future required field can be appended at
    the END without reordering (the repo dataclass convention).

    ``missing_hp_pct`` is a FRACTION of the wielder's MISSING health (Second Wind
    0.04). Missing health is ``max_health * missing_hp_share``, where the share
    is the caller's - defaulting to the engine's existing
    ``_MISSING_HP_SHARE_FOR_HEALS`` convention.

    ``window_uptime`` is the share of the heal-over-time realized inside the
    modeled fight window. It amortizes DURATION, not trigger probability - see
    the module docstring for why this rune earns no firing discount.

    ``ranged_factor`` scales the heal when the wielder is ranged. Second Wind's
    longDesc carries NO ``<rules>`` clause, so it stays 1.0; the field exists so
    a future rune with such a clause fits this shape without a schema lift.

    ``family`` dedups mutually exclusive / aliased ids, mirroring the sibling
    registries. Runes have no mirror ids today, so each entry gets its own
    family; the field exists so a future alias cannot silently double-credit.
    """

    missing_hp_pct: float = 0.0
    window_uptime: float = 1.0
    ranged_factor: float = 1.0
    family: str = ""
    note: str = ""


_RUNE_SELF_HEAL: dict[str, RuneSelfHealEntry] = {
    # 8444 Second Wind (Resolve, slot 2) - verbatim: "After taking damage from an
    # enemy champion, heal for 4% of your missing health over 10s." That is the
    # ENTIRE longDesc: no AP scaling, no bonus-health scaling, no cooldown, no
    # ranged clause, no ally component. Nothing here is credited anywhere else -
    # _rune_health_grants owns Grasp's MAX-health per-proc heal, which is a
    # different base, a different trigger direction and a different shape.
    "8444": RuneSelfHealEntry(
        missing_hp_pct=SECOND_WIND_MISSING_HP_PCT,
        window_uptime=_SECOND_WIND_WINDOW_UPTIME,
        family="second_wind",
        note=(
            "Second Wind: heals 4% of missing health over 10s after taking "
            "champion damage; magnitude is exact DDragon, only the share of the "
            "10s regeneration realized inside the modeled fight window is an "
            "assumption"
        ),
    ),
}

__all__ = [
    "RuneSelfHealEntry",
    "SECOND_WIND_MISSING_HP_PCT",
    "SECOND_WIND_HEAL_DURATION_S",
    "second_wind_heal",
    "sum_rune_self_heal",
]


def _coerce_pool(max_health: object) -> float:
    """Resolve a health pool to a non-negative float, or 0.0 if unusable.

    Fail-soft on None / non-numeric input so the orchestrator's seam cannot be
    made to raise by a malformed caller.
    """
    try:
        return max(0.0, float(max_health))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _coerce_share(missing_hp_share: object) -> float:
    """Clamp a missing-health share into ``[0.0, 1.0]``.

    Missing health can never exceed the pool, and a below-zero share would
    invert the heal into a penalty; both are clamped rather than raising.
    """
    try:
        return max(0.0, min(1.0, float(missing_hp_share)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def second_wind_heal(
    *,
    max_health: float,
    missing_hp_share: Optional[float] = None,
    is_ranged: bool = False,
) -> float:
    """Second Wind's raw self-heal inside the modeled fight window.

    ``missing_hp_pct * (max_health * missing_hp_share) * window_uptime``.
    ``missing_hp_share`` defaults to the engine's existing
    ``_MISSING_HP_SHARE_FOR_HEALS`` (``ehp.py:356``) and is clamped into
    ``[0.0, 1.0]``. Exposed separately from the page-level entry point so the
    exact DDragon coefficient and the window amortization are testable without
    constructing a rune page.
    """
    entry = _RUNE_SELF_HEAL["8444"]
    share = _coerce_share(
        _MISSING_HP_SHARE_FOR_HEALS if missing_hp_share is None else missing_hp_share
    )
    missing_hp = _coerce_pool(max_health) * share
    factor = entry.ranged_factor if is_ranged else 1.0
    return entry.missing_hp_pct * missing_hp * entry.window_uptime * factor


def sum_rune_self_heal(
    rune_ids: Optional[Iterable[str | int]],
    *,
    max_health: float,
    missing_hp_share: Optional[float] = None,
    is_ranged: bool = False,
) -> float:
    """Sum the SELF-side incoming-damage-triggered rune heal across a rune page.

    Returns a BARE FLOAT - a RAW, pre-amplification EHP NUMERATOR contribution.
    This module takes no position on how the caller folds it; a caller adding it
    to ``heal_total`` should do so BEFORE ``heal_amp_mult`` (``ehp.py:791``) so
    heal-power sources apply to it as they do in game. The DEFAULT-OFF gating
    lives in the orchestrator's seam, deliberately not here.

    ``max_health`` is the champion's RESOLVED build max health (base per-level +
    items) - the same pool the caller's ``hp`` numerator term carries, and NOT a
    total that already includes any peer registry's grants. Feeding peer
    grant-lane output back into a grant lane is grant-on-grant compounding and
    makes the result depend on the SOURCE ORDER of the peer registries (the
    ``total_armor`` contract of GUARD 2 in
    ``tests/test_rune_resist_signature_convention_r134.py``, applied to the
    numerator).

    ``missing_hp_share`` defaults to ``_MISSING_HP_SHARE_FOR_HEALS``, the
    convention ``ehp.py`` already resolves once at ``ehp.py:1501``; a caller that
    has already computed ``missing_hp / hp`` should pass it rather than let the
    default re-derive it.

    A ``family`` tag is credited at most once, so a duplicated or aliased id
    cannot double-credit; different families sum. Runes outside the one-id
    allowlist contribute 0.0 by construction, so every offensive keystone and
    every sibling-lane Resolve rune returns zero. Returns 0.0 on an empty / None
    / non-iterable argument, a non-numeric pool, or any lookup failure.
    """
    if not rune_ids:
        return 0.0
    try:
        total = 0.0
        seen_families: set[str] = set()
        for rid in rune_ids:
            if rid is None:
                continue
            entry = _RUNE_SELF_HEAL.get(str(rid))
            if entry is None:
                continue
            if entry.family and entry.family in seen_families:
                continue
            seen_families.add(entry.family)
            share = _coerce_share(
                _MISSING_HP_SHARE_FOR_HEALS
                if missing_hp_share is None
                else missing_hp_share
            )
            missing_hp = _coerce_pool(max_health) * share
            factor = entry.ranged_factor if is_ranged else 1.0
            total += entry.missing_hp_pct * missing_hp * entry.window_uptime * factor
        return total
    except Exception:
        return 0.0
