"""R136-S1: SELF-side rune permanent-max-HP / self-heal registry, keyed by rune id.

The EHP-NUMERATOR twin of the R132 ``_rune_resist_grants`` registry (which raises
the DENOMINATOR). Same author conventions, same allowlist discipline, same
DEFAULT-OFF contract - the difference is purely which side of the EHP fraction
the credit lands on:

  * ``_rune_resist_grants``  -> bonus armor / MR, added to ``eff_armor`` /
    ``eff_mr`` BEFORE the ``_armor_factor`` curve. DENOMINATOR.
  * ``_rune_health_grants``  (this module) -> bonus MAX HEALTH and raw HEAL,
    added to the per-type numerators next to ``passive_health_hp`` /
    ``heal_total``. NUMERATOR. A pure pool increase, so it lifts physical,
    magical AND true EHP uniformly (true EHP ignores resists, so a denominator
    term cannot reach it - a numerator term can).

WHAT WAS MISSING. ``rune_procs.py`` registers Grasp of the Undying (8437) for its
bonus magic DAMAGE alone, and its own formula string admits the gap verbatim at
``rune_procs.py:606``: "(heal + permanent-HP sides not modeled)". Overgrowth
(8451) was modelled NOWHERE - ``_rune_resist_grants.py:52-57`` explicitly read and
rejected it for the RESIST registry ("8451 Overgrowth max health") because max
health is not a resist. This module is the lane that rejection pointed at. Both
runes' self-side survivability was therefore worth exactly ZERO EHP.

DDragon 16.14.1 ``data/meta_build/ddragon/16.14.1/runesReforged.json`` longDescs,
quoted VERBATIM (re-read from raw source for this slice, not paraphrased):

  * 8437 GraspOfTheUndying: "Every 4s in combat, your next basic attack on a
    champion will:<li>Deal bonus magic damage equal to 3.5% of your max health<li>
    Heal you for 1.3% of your max health<li>Permanently increase your health by 5
    <br><rules><i>Ranged Champions:</i> Damage, healing, and permanent health
    gained are 40% effective.</rules>"
  * 8451 Overgrowth: "Absorb life essence from monsters or enemy minions that die
    near you, permanently gaining 3 maximum health for every 8.<br><br>When you've
    absorbed 120 monsters or enemy minions, gain an additional 3.5% maximum
    health."

COEFFICIENT REUSE - NOT RE-DERIVED. Grasp's three magnitudes already exist,
DDragon-cited, on the ENEMY side in ``enemy_runes.py``:

  * ``enemy_runes.py:213``  ``poke_heal_pct=0.013``   -> ``_GRASP_HEAL_PCT_MAX_HP``
  * ``enemy_runes.py:215``  ``perm_hp=5.0``           -> ``_GRASP_PERM_HP_PER_PROC``
  * ``enemy_runes.py:216``  ``ranged_factor=0.40``    -> ``_GRASP_RANGED_FACTOR``

(field declarations at ``enemy_runes.py:130-133``; the whole 8437 entry spans
``enemy_runes.py:201-217``). They are RESTATED here rather than imported: an
import would create a cycle risk and couple a survivability registry to the
enemy-threat seam, which is a different consumer with a different flip gate. The
restatement is held safe by ``tests/test_rune_health_grants_r136.py``
(``GraspCoefficientAntiDriftTests``), which imports BOTH sides - it lives outside
the production import graph, so it can hold the pair at once and goes RED the
moment either side is edited alone. That test is the reason this restatement is
not drift-prone. NOTE: ``enemy_runes.py`` cites patch 16.12.1 and this module
cites 16.14.1; all three Grasp magnitudes are unchanged across those patches
(re-verified against the 16.14.1 longDesc above), which is why the equality guard
holds today.

THE STACK-COUNT PROXY (convention COPIED, not invented). Both runes accumulate
over a whole game and we have no live stack feed, exactly the problem
``_passive_health_overrides.py`` already solved for Sion / Cho'Gath / Swain. Its
convention is adopted verbatim:

  * the shape - an 18-entry (levels 1-18) monotonic-non-decreasing
    ``assumed_stacks_by_level`` tuple, read at ``level-1`` and clamped to the
    tuple bounds (``_passive_health_overrides.py:69-94`` for the curves,
    ``:207-213`` for the ``_stacks_at_level`` reader);
  * the arithmetic - credited HP is ``per_stack_value * stacks_at_level(level)``
    (``_passive_health_overrides.py:107-109``);
  * the CALIBRATION RULE - "deliberately LOW ... the midpoint under-credits on
    purpose so a flipped-on scorer never OVER-states the pool"
    (``_passive_health_overrides.py:33-38``). Both curves below are set under a
    realistic game so an accidental flip cannot inflate a tank.

Per-rune proxy reasoning is on each curve. The MAGNITUDES are EXACT DDragon;
ONLY THE STACK COUNTS ARE ASSUMPTIONS - the same split the sibling registries
draw between an exact coefficient and a tunable midpoint.

TWO DIFFERENT PROXY QUESTIONS, deliberately kept separate. Grasp's two halves do
NOT share a count, because they accrue on different clocks:

  * the PERMANENT HP is CUMULATIVE OVER THE GAME - every proc since minute 0 is
    still on the healthbar - so it uses the level curve
    (``_GRASP_PROCS_BY_LEVEL``), exactly like a Sion stack;
  * the HEAL is PER-FIGHT - only procs inside the modeled sustained fight heal
    you - so it uses a single fight-window count (``_GRASP_PROCS_PER_FIGHT``) and
    is LEVEL-INDEPENDENT by construction.

Collapsing these into one number would either price a whole game's healing into
one teamfight or throw away 17 levels of stacked HP.

OVERGROWTH'S THRESHOLD IS DISCRETE, NOT SMEARED. The longDesc has two distinct
terms and they are modelled as two distinct terms:

  * a QUANTIZED block: "3 maximum health for every 8" is
    ``floor(absorbed / 8) * 3``, NOT a smooth 0.375 per minion. You gain nothing
    for the 7 minions after a block boundary.
  * a one-shot THRESHOLD: "When you've absorbed 120 ... gain an additional 3.5%
    maximum health" pays its full 3.5% at exactly 120 absorbed and 0.0 below.
    Smearing it linearly across 0..120 would credit a level-4 tank with a
    fraction of a bonus it provably does not have yet. Pinned by
    ``OvergrowthThresholdTests`` (112 and 119 absorbed must read EQUAL - same
    block, both pre-threshold - and the 119->120 step must carry the entire
    percent term in one jump).

RANGED FACTOR APPLIES TO GRASP ONLY. Grasp's ``<rules>`` clause makes "Damage,
healing, and permanent health gained ... 40% effective" for ranged champions, so
BOTH self-side halves take 0.40. Overgrowth's longDesc carries NO ``<rules>``
clause at all, so its ``ranged_factor`` stays 1.0. A blanket "scale every rune by
0.40 when ranged" bug is caught by ``test_overgrowth_has_no_ranged_penalty`` and
by ``test_combined_page_is_reduced_but_not_by_40_percent``. The caller supplies
``is_ranged``; ``compute_ehp`` already computes it at ``ehp.py:1411`` via
``_is_ranged(base)`` (base attackrange > 250, ``ehp.py:246-262``), so no champion
lookup is needed here and this module stays import-pure.

PERCENT-OF-MAX-HP IS TAKEN ON THE CALLER'S RESOLVED POOL. Overgrowth's 3.5% reads
the ``max_hp`` the caller passes - the RESOLVED build health - and NOT a total
that already includes this registry's own flat grants. That is the same contract
GUARD 2 of ``tests/test_rune_resist_signature_convention_r134.py`` pins for
``total_armor``: feeding peer grant-lane output back into a grant lane is
grant-on-grant compounding and makes the result depend on the SOURCE ORDER of the
peer registries. The flat and percent terms here are peers; neither compounds the
other.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL. ``apply_rune_health_grants`` defaults False on
this function itself (belt and braces - the sibling gates only at ``compute_ehp``,
so a caller that forgets the seam check there would still get live numbers; here
an un-opted caller gets ``(0.0, 0.0)`` no matter what rune page it passes). With
it OFF every EHP field is unchanged. The live default-ON flip is operator-gated,
mirroring ``apply_rune_resist_grants`` / ``assume_passive_health_stacks``.

Keyed by string rune_id to match the engine's id convention (strings throughout);
integer ids are coerced on lookup, mirroring
``_rune_resist_grants.rune_resist_grants``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

# --- Grasp of the Undying (8437) - EXACT DDragon 16.14.1 magnitudes -----------
# Restated from the enemy-side twin so the two lanes cannot drift; see the module
# docstring for the enemy_runes.py line citations and the anti-drift test that
# enforces the equality.

# "Heal you for 1.3% of your max health" (enemy_runes.py:213 poke_heal_pct).
_GRASP_HEAL_PCT_MAX_HP: float = 0.013
# "Permanently increase your health by 5" (enemy_runes.py:215 perm_hp).
_GRASP_PERM_HP_PER_PROC: float = 5.0
# "Ranged Champions: Damage, healing, and permanent health gained are 40%
# effective" (enemy_runes.py:216 ranged_factor).
_GRASP_RANGED_FACTOR: float = 0.40

# --- Overgrowth (8451) - EXACT DDragon 16.14.1 magnitudes --------------------
# "permanently gaining 3 maximum health for every 8".
_OVERGROWTH_HP_PER_BLOCK: float = 3.0
_OVERGROWTH_ABSORBS_PER_BLOCK: float = 8.0
# "When you've absorbed 120 monsters or enemy minions, gain an additional 3.5%
# maximum health." A DISCRETE threshold, never smeared. Percent is stored as
# 3.5 == 3.5% to match the sibling registry's "75.0 == 75%" field convention
# (_rune_resist_grants.RuneResistEntry armor_pct).
_OVERGROWTH_THRESHOLD_ABSORBS: float = 120.0
_OVERGROWTH_THRESHOLD_PCT_MAX_HP: float = 3.5

# --- Conservative assumed STACK-COUNT-by-level curves (the live feeds we lack) -
# Convention copied verbatim from _passive_health_overrides.py:69-94: an 18-entry
# (levels 1-18) monotonic-non-decreasing count, deliberately LOW relative to a
# real game so the modeled pool never OVER-states. Operator-tunable; a future live
# consumer (the in-game stack count, when it surfaces) replaces the curve without
# re-authoring any math.

# Grasp procs LANDED CUMULATIVELY BY LEVEL. Grasp is a lane-bully rune on a 4s
# in-combat cooldown that requires a basic attack ON A CHAMPION, so its stacking
# is front-loaded into laning trades and tapers once sidelane/teamfight tempo
# takes over - hence the ~3/level early slope flattening to ~2/level late. The
# level-18 count of 45 is ~225 permanent HP melee (90 ranged), comfortably UNDER a
# real Grasp top-laner's game and conservative by design.
_GRASP_PROCS_BY_LEVEL: tuple[float, ...] = (
    2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 31, 33, 35, 37, 39, 41, 43, 45,
)

# Grasp procs inside ONE modeled sustained fight (the EHP frame's window). The
# rune fires at most once per 4s in combat, so a teamfight the EHP scorers model
# admits only a handful; 2.0 is the conservative midpoint (the engage proc plus
# one follow-up). This is the ONLY assumption behind the heal term - its 1.3%
# magnitude is exact - and it is deliberately NOT the level curve above, because
# healing does not accumulate across a game the way permanent HP does.
_GRASP_PROCS_PER_FIGHT: float = 2.0

# Overgrowth absorbs (monsters + enemy minions dying NEAR you - not last-hits, so
# a frontliner banks them passively just by standing in the wave) CUMULATIVELY BY
# LEVEL. Set so the 120 threshold is first met at level 13, which is late enough
# to be honest about a rune that genuinely takes most of a game to complete and
# early enough that the threshold is reachable rather than dead code. The
# level-18 count of 160 yields 60 flat HP plus the 3.5%, under a real game's
# absorb count.
_OVERGROWTH_ABSORBED_BY_LEVEL: tuple[float, ...] = (
    8, 18, 28, 38, 48, 58, 68, 78, 88, 96, 104, 112, 120, 128, 136, 144, 152, 160,
)


@dataclass(frozen=True)
class RuneHealthEntry:
    """One rune-keyed SELF-side permanent max-HP / self-heal grant.

    Every field carries a default so a future required field can be appended at
    the END without reordering (the repo dataclass convention) and so the two
    structurally different runes share one registry shape - the same
    flat/percent/threshold unification ``_rune_resist_grants.RuneResistEntry``
    uses for its three entry shapes.

    Permanent max-HP is expressed by whichever pair of fields the rune's tooltip
    uses; an entry may carry either or both, and they SUM:

    * ``perm_hp_per_proc`` - a PER-STACK flat grant (Grasp 5.0 per proc). The
      credited HP is ``perm_hp_per_proc * stacks``.
    * ``perm_hp_per_block`` / ``absorbs_per_block`` - a QUANTIZED grant
      (Overgrowth "3 maximum health for every 8"). The credited HP is
      ``floor(stacks / absorbs_per_block) * perm_hp_per_block`` - integer blocks,
      so a partial block pays nothing.
    * ``threshold_absorbs`` / ``threshold_pct_max_hp`` - a ONE-SHOT threshold
      (Overgrowth "absorbed 120 ... an additional 3.5% maximum health"). Pays
      ``threshold_pct_max_hp / 100 * max_hp`` once ``stacks >= threshold_absorbs``
      and EXACTLY 0.0 below it. Never interpolated: this is a discrete game
      mechanic, not a ramp.

    ``heal_pct_max_hp`` / ``procs_per_fight`` carry the per-fight self-heal
    (Grasp 1.3% of max health per proc): ``heal_pct_max_hp * max_hp *
    procs_per_fight``. A rune with no healing clause leaves both at 0.0.

    ``ranged_factor`` scales BOTH halves when the wielder is ranged - 0.40 for
    Grasp (its ``<rules>`` clause covers healing and permanent health explicitly),
    1.0 for Overgrowth (no such clause exists in its longDesc).

    ``assumed_stacks_by_level`` is the 18-entry conservative stack-count proxy.

    ``family`` dedups mutually exclusive / aliased ids, mirroring the sibling
    registries. Runes have no mirror ids today, so each entry gets its own family;
    the field exists so a future alias cannot silently double-credit.
    """

    heal_pct_max_hp: float = 0.0
    perm_hp_per_proc: float = 0.0
    perm_hp_per_block: float = 0.0
    absorbs_per_block: float = 0.0
    threshold_absorbs: float = 0.0
    threshold_pct_max_hp: float = 0.0
    ranged_factor: float = 1.0
    procs_per_fight: float = 0.0
    assumed_stacks_by_level: tuple[float, ...] = ()
    family: str = ""
    note: str = ""


_RUNE_HEALTH_GRANTS: dict[str, RuneHealthEntry] = {
    # 8437 Grasp of the Undying (Resolve keystone) - verbatim: "Every 4s in
    # combat, your next basic attack on a champion will: ... Heal you for 1.3% of
    # your max health ... Permanently increase your health by 5 ... Ranged
    # Champions: Damage, healing, and permanent health gained are 40% effective."
    # ONLY the heal + permanent-HP sides are credited here. The bonus magic
    # DAMAGE side (3.5% max health) is ALREADY scored by rune_procs.py:597-610
    # and is not a survivability term - crediting it here would double-count it.
    # This entry closes that module's own admission at rune_procs.py:606,
    # "(heal + permanent-HP sides not modeled)".
    "8437": RuneHealthEntry(
        heal_pct_max_hp=_GRASP_HEAL_PCT_MAX_HP,
        perm_hp_per_proc=_GRASP_PERM_HP_PER_PROC,
        ranged_factor=_GRASP_RANGED_FACTOR,
        procs_per_fight=_GRASP_PROCS_PER_FIGHT,
        assumed_stacks_by_level=_GRASP_PROCS_BY_LEVEL,
        family="grasp_of_the_undying",
        note=(
            "Grasp of the Undying: heals 1.3% max health and grants +5 permanent "
            "health per proc (every 4s in combat), 40% effective when ranged; the "
            "3.5% max-health magic damage half is scored in rune_procs.py and is "
            "deliberately NOT repeated here"
        ),
    ),
    # 8451 Overgrowth (Resolve, slot 3) - verbatim: "Absorb life essence from
    # monsters or enemy minions that die near you, permanently gaining 3 maximum
    # health for every 8. When you've absorbed 120 monsters or enemy minions, gain
    # an additional 3.5% maximum health." Two SEPARATE terms: a quantized
    # per-8-absorb block AND a one-shot 3.5% threshold at 120. NO healing clause
    # (heal fields stay 0.0) and NO ranged <rules> clause (ranged_factor 1.0) -
    # both absences are asserted by the test file, not merely assumed.
    "8451": RuneHealthEntry(
        perm_hp_per_block=_OVERGROWTH_HP_PER_BLOCK,
        absorbs_per_block=_OVERGROWTH_ABSORBS_PER_BLOCK,
        threshold_absorbs=_OVERGROWTH_THRESHOLD_ABSORBS,
        threshold_pct_max_hp=_OVERGROWTH_THRESHOLD_PCT_MAX_HP,
        assumed_stacks_by_level=_OVERGROWTH_ABSORBED_BY_LEVEL,
        family="overgrowth",
        note=(
            "Overgrowth: +3 maximum health per 8 monsters/minions absorbed "
            "(quantized blocks), plus a one-shot +3.5% maximum health at exactly "
            "120 absorbed; no heal clause and no ranged penalty in 16.14.1"
        ),
    ),
}

__all__ = [
    "RuneHealthEntry",
    "_RUNE_HEALTH_GRANTS",
    "rune_health_grants",
    "grasp_permanent_hp",
    "grasp_heal_hp",
    "overgrowth_hp_for_absorbed",
    "stacks_at_level",
]


def stacks_at_level(assumed_stacks_by_level: tuple[float, ...], level: int) -> float:
    """Resolve the conservative assumed stack count at a champion level.

    The tuple read at ``level-1``, clamped to the tuple bounds so an out-of-range
    caller yields the nearest endpoint rather than raising or extrapolating.
    Identical semantics to ``_passive_health_overrides._stacks_at_level``
    (``_passive_health_overrides.py:207-213``); duplicated rather than imported to
    keep this registry standalone and import-pure.
    """
    if not assumed_stacks_by_level:
        return 0.0
    idx = max(0, min(int(level) - 1, len(assumed_stacks_by_level) - 1))
    return float(assumed_stacks_by_level[idx])


def _entry_permanent_hp(
    entry: RuneHealthEntry, stacks: float, max_hp: float
) -> float:
    """Permanent bonus MAX HP for one entry at a resolved stack count.

    Sums the three independent permanent-HP shapes described on
    ``RuneHealthEntry``: the per-stack flat grant, the quantized per-block grant,
    and the one-shot percent-of-max-HP threshold. The ranged factor is NOT applied
    here - the caller applies it once to both halves.
    """
    stacks = max(0.0, float(stacks))
    pool = max(0.0, float(max_hp))
    total = 0.0
    # Per-stack flat grant (Grasp +5 per proc).
    if entry.perm_hp_per_proc:
        total += entry.perm_hp_per_proc * stacks
    # Quantized block grant (Overgrowth +3 per 8 absorbed). Integer blocks only -
    # a partial block pays nothing, per the "for every 8" wording.
    if entry.perm_hp_per_block and entry.absorbs_per_block > 0.0:
        blocks = math.floor(stacks / entry.absorbs_per_block)
        total += entry.perm_hp_per_block * float(blocks)
    # One-shot threshold (Overgrowth +3.5% max HP at 120 absorbed). DISCRETE: full
    # value at or above the threshold, exactly 0.0 below it, never interpolated.
    if entry.threshold_absorbs > 0.0 and entry.threshold_pct_max_hp:
        if stacks >= entry.threshold_absorbs:
            total += pool * (entry.threshold_pct_max_hp / 100.0)
    return total


def _entry_heal_hp(entry: RuneHealthEntry, max_hp: float) -> float:
    """Raw per-fight self-heal for one entry (pre heal-amplification).

    ``heal_pct_max_hp * max_hp * procs_per_fight``. Level-independent by design:
    healing is realized inside the modeled fight window, unlike permanent HP which
    accumulates across the whole game. The ranged factor is applied by the caller.
    """
    if not entry.heal_pct_max_hp or not entry.procs_per_fight:
        return 0.0
    return entry.heal_pct_max_hp * max(0.0, float(max_hp)) * entry.procs_per_fight


def grasp_permanent_hp(procs: float, is_ranged: bool = False) -> float:
    """Grasp's permanent bonus max HP for a given cumulative proc count.

    ``5 per proc``, times 0.40 when the wielder is ranged. Exposed separately so
    the coefficient and the ranged branch are testable without constructing a rune
    page.
    """
    entry = _RUNE_HEALTH_GRANTS["8437"]
    raw = _entry_permanent_hp(entry, procs, 0.0)
    return raw * (entry.ranged_factor if is_ranged else 1.0)


def grasp_heal_hp(procs: float, max_hp: float, is_ranged: bool = False) -> float:
    """Grasp's raw self-heal over ``procs`` procs at a given max-HP pool.

    ``1.3% of max health per proc``, times 0.40 when the wielder is ranged.
    Pre-amplification: a caller folding this into ``heal_total`` should add it on
    the RAW side so any heal-power multiplier applies, matching how Grasp's heal
    behaves in game.
    """
    entry = _RUNE_HEALTH_GRANTS["8437"]
    raw = entry.heal_pct_max_hp * max(0.0, float(max_hp)) * max(0.0, float(procs))
    return raw * (entry.ranged_factor if is_ranged else 1.0)


def overgrowth_hp_for_absorbed(absorbed: float, max_hp: float) -> float:
    """Overgrowth's permanent bonus max HP at a given absorb count.

    ``floor(absorbed / 8) * 3`` PLUS a one-shot ``3.5% * max_hp`` once ``absorbed``
    reaches 120. Exposed separately so the discrete threshold can be pinned at its
    exact binding point (119 vs 120) without depending on the level curve. No
    ranged factor - Overgrowth's longDesc has no ranged clause.
    """
    return _entry_permanent_hp(_RUNE_HEALTH_GRANTS["8451"], absorbed, max_hp)


def rune_health_grants(
    rune_ids: Iterable[str | int],
    *,
    level: int,
    max_hp: float,
    is_ranged: bool = False,
    apply_rune_health_grants: bool = False,
) -> tuple[float, float]:
    """Return ``(permanent_hp, heal_hp)`` - the SELF-side rune health grant.

    BOTH returned values are EHP NUMERATOR terms:

    * ``permanent_hp`` is a flat bonus MAX HEALTH pool add. The caller folds it
      into every per-type numerator next to ``passive_health_hp`` /
      ``ext_flat_hp`` (``ehp.py:1791-1793``), so it lifts physical, magical AND
      true EHP uniformly - the correct "more health survives more" direction.
    * ``heal_hp`` is a RAW per-fight heal, pre-amplification. The caller folds it
      into the heal lane BEFORE ``heal_amp_mult`` (``ehp.py:1477``,
      ``heal_total = (heal_item_total + heal_lifesteal) * heal_amp_mult``) so
      Revitalize and other heal-power sources apply to it as they do in game.

    Neither value touches the denominator - this registry grants no resists. Its
    R132 twin ``_rune_resist_grants.rune_resist_grants`` is the denominator lane.

    ``max_hp`` is the champion's RESOLVED build max health (base per-level +
    items) - the same pool the caller's ``hp`` numerator term carries. It is NOT a
    total that already includes this registry's own grants: Overgrowth's 3.5%
    reads the resolved pool only, so the flat and percent terms stay peers and
    neither compounds the other (the ``total_armor`` contract of GUARD 2 in
    ``tests/test_rune_resist_signature_convention_r134.py``, applied to the
    numerator).

    ``level`` indexes both conservative stack-count proxies. ``is_ranged`` is the
    wielder's ranged status - ``compute_ehp`` already has it at ``ehp.py:1411``
    (``_is_ranged(base)``) - and scales Grasp's two halves by 0.40 while leaving
    Overgrowth untouched.

    ``apply_rune_health_grants`` is the DEFAULT-OFF seam gate: False (the default)
    returns ``(0.0, 0.0)`` for ANY rune page, so an un-opted caller is
    byte-identical. The flag lives on this function as well as at the
    ``compute_ehp`` seam deliberately - a caller that forgets the outer check
    still gets inert output rather than silently live numbers.

    A ``family`` tag is credited at most once, so a duplicated or aliased id
    cannot double-credit; different families sum. Runes outside the two-id
    allowlist contribute 0.0 by construction, so every offensive keystone and
    every non-max-HP Resolve rune returns zero.
    """
    if not apply_rune_health_grants:
        return 0.0, 0.0
    permanent_hp = 0.0
    heal_hp = 0.0
    seen_families: set[str] = set()
    for rid in rune_ids:
        entry = _RUNE_HEALTH_GRANTS.get(str(rid))
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        seen_families.add(entry.family)
        stacks = stacks_at_level(entry.assumed_stacks_by_level, level)
        factor = entry.ranged_factor if is_ranged else 1.0
        permanent_hp += _entry_permanent_hp(entry, stacks, max_hp) * factor
        heal_hp += _entry_heal_hp(entry, max_hp) * factor
    return permanent_hp, heal_hp
