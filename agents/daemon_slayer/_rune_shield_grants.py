"""R142-S2: SELF-side rune SHIELD registry, keyed by rune id.

The SHIELD lane of the R136 rune-registry family. Its siblings split the EHP
fraction between them and this module adds the one term neither carries:

  * ``_rune_resist_grants``  -> bonus armor / MR. DENOMINATOR.
  * ``_rune_health_grants``  -> permanent max HP and raw self-HEAL. NUMERATOR.
  * ``_rune_hsp_amp``        -> a flat Heal-and-Shield-Power FRACTION. A
    MULTIPLIER on other lanes, not a pool of its own.
  * ``_rune_shield_grants``  (this module) -> a raw SELF-SHIELD amount.
    NUMERATOR. A temporary absorb pool, so - like flat max HP - it lifts
    physical, magical AND true EHP uniformly.

NOTHING HERE IS DUPLICATED FROM A SIBLING. ``_rune_health_grants`` credits only
Grasp (8437) and Overgrowth (8451), and it credits HEALS, never shields.
``_rune_hsp_amp`` credits only Revitalize (8453), and it returns an
AMPLIFICATION FRACTION rather than a shield magnitude - it is a consumer of
whatever this module produces, not a peer source of it. ``_rune_resist_grants``
explicitly READ AND REJECTED Guardian at ``_rune_resist_grants.py:52-57``
("8465 Guardian ally shield") because a shield is not a resist. This module is
the lane that rejection pointed at. Guardian's SELF-shield was therefore worth
exactly ZERO EHP.

STRUCTURAL GAP - why a rune registry at all. The existing SHIELD-side registry
``_item_spell_shield_overrides`` is keyed by ITEM ID and its
``item_spell_shield_fraction`` looks each contribution up by item id. A RUNE has
no item id, so it can never reach that lookup no matter what it grants. That is
the same reasoning every sibling rune / passive registry in this engine carries.
The two lanes ALSO differ structurally in what they express: the item lane
returns a normalized BLOCK FRACTION in [0, 1) that discounts CC pressure (a
spell shield negates one whole hostile ability), while this lane returns a raw
SHIELD AMOUNT in HP units that adds to the EHP numerator. Same word, different
quantity - Guardian absorbs a measured number of damage points, it does not
negate an ability.

DDragon 16.14.1 ``data/meta_build/ddragon/16.14.1/runesReforged.json`` longDesc
for 8465 Guardian, quoted VERBATIM (re-read from raw source for this slice; the
raw JSON wraps the magnitudes in <scaleLevel> / <scaleAP> / <scalehealth> tags
and separates the lines with <br>):

  "<i>Guard</i> allies within 350 units of you, and allies you target with
  spells for 2.5s. While <i>Guarding</i>, if you or the ally take more than a
  small amount of damage over the duration of the <i>Guard</i>, both of you gain
  a shield for 1.5s.<br><br>Cooldown: <scaleLevel>75 - 40</scaleLevel> seconds
  <br>Shield: <scaleLevel>40 - 150</scaleLevel> + <scaleAP>20%</scaleAP> of your
  ability power + <scalehealth>6%</scalehealth> of your bonus health<br>Proc
  Threshold: <scaleLevel>50 - 165</scaleLevel> postmitigation damage"

TWO TERMS ARE READ AND REJECTED, NOT MISSED. Both omissions are REQUIREMENTS of
this slice and both push the credit DOWNWARD, which is the safe direction.

  (1) THE ALLY HALF IS OMITTED. The tooltip shields "both of you". Only the
      WIELDER's own shield is credited here. The ally's shield is THROUGHPUT TO A
      SECOND UNIT, and the EHP frame models exactly one unit - the wielder's own
      effective health. There is no second healthbar in the fraction to add it
      to. Crediting it would inflate the wielder's personal survivability with
      value that never lands on the wielder. The ally-throughput question belongs
      to the ``hps.py`` lane, which already owns ally-directed output. The module
      name says SELF for this reason.

  (2) THE ABILITY-POWER TERM IS OMITTED - IT IS UNREPRESENTABLE, NOT FORGOTTEN.
      "+20% of your ability power" cannot be computed at this seam because there
      is no AP value at the seam to read. MEASURED, not assumed (the R136
      finding, re-verified for this slice):

        grep -nE "ability_power|abilitypower|total_ap|bonus_ap|ap_flat" ehp.py
        -> ZERO matches (exit 1).

      All 27 "ap" substring hits in ``ehp.py`` are ``enemy_ap_share``, which is
      the ENEMY damage-type mix used to weight blended EHP - it is a share of
      incoming damage, not the wielder's ability-power stat, and it is
      mathematically unusable as one. Inventing an AP value would be the exact
      "scaffolded against an assumed API surface" failure the repo bans.

      So the credit is a DELIBERATE UNDERCOUNT. For an enchanter running Guardian
      the omitted term is the LARGER half at full build, which means this
      registry systematically under-credits the champions it exists for. That is
      accepted: an undercount can only make a flipped-on scorer conservative,
      whereas a fabricated AP value could make it wrong in the dangerous
      direction. The shipped precedent for crediting a strict SUBSET of a
      tooltip's terms is the Irelia-W / Fizz-P omission precedent already in this
      engine, and the sibling ``_rune_hsp_amp`` does the same thing to
      Revitalize's second sentence.

      When an AP convention eventually exists at the EHP call site, the term is a
      one-line addition here. Until then
      ``AbilityPowerOmissionRegressionTests`` in the test file keeps the omission
      LOUD: the public signature accepts no AP argument, so a well-meaning edit
      that passes one goes RED rather than silently succeeding.

WHAT IS THEREFORE MODELLED:

    shield = scaleLevel(40 at level 1 -> 150 at level 18)
             + 6% of BONUS health

using the standard Riot linear interpolation across the 17 level-ups between
level 1 and level 18 - the identical semantics as
``_rune_resist_grants.aftershock_resist_cap`` (its "80-150 (based on level)"
walk), so the two rune lanes read "based on level" the same way. BONUS health is
``max(0.0, total_hp - base_hp)``, clamped exactly like the percent-of-BONUS
resist term at ``_rune_resist_grants.py:273-275``, so a below-base build yields
the flat term alone and never a negative contribution.

AMORTIZATION IS LOAD-BEARING HERE, and it is the ONLY assumption in the module -
every MAGNITUDE above is exact DDragon. The raw duty cycle is tiny: a 1.5s shield
on a level-scaled 75-to-40s cooldown is roughly 0.02 to 0.0375 of wall-clock
time. Pricing the shield at its raw duty cycle would be WRONG in the other
direction, because the uptime is not uniformly distributed - it is
ENGAGEMENT-SYNCHRONIZED in the strongest sense available in this engine:

  * the shield does not fire on a timer or on a separate cast. It fires ON the
    incoming damage that triggers it, which is precisely the moment the EHP frame
    models. Every point of it lands on damage actually being taken.
  * the Proc Threshold ("50 - 165 postmitigation damage", also level-scaled) is a
    gate on WHETHER it fires at all, not on how much it absorbs. It is folded
    into the firing probability below rather than ignored: it is the reason the
    probability is not 1.0 even inside a fight, since chip damage under the
    threshold never procs the guard. It is deliberately NOT modelled as a
    separate subtractive term - doing so would need a per-instance incoming
    damage distribution the engine does not carry, and the DS conditional
    target-state arc is operator-CLOSED.

AGAINST THE SIBLING CONVENTION. ``_rune_resist_grants._RUNE_ACTIVE_RESIST_PROB``
is 0.3 for Aftershock / Unflinching. Guardian is priced BELOW it, at 0.2, and the
value is NOT silently inherited:

  * Aftershock holds 2.5s on a 20s cooldown and can therefore realistically fire
    MORE THAN ONCE inside a long modeled fight. Guardian's cooldown is 2x to
    3.75x longer (75-40s), so within one sustained fight it fires ONCE at best.
    It must not be priced at or above the 0.3 sibling.
  * 0.2 is not a new number. It is the value this engine already accepts for "a
    reactively popped 1.5s spell shield"
    (``_champion_spell_shield_overrides._SPELL_SHIELD_REACTIVE_PROB`` = 0.2,
    declared at ``_champion_spell_shield_overrides.py:111`` and aliased by
    ``_item_spell_shield_overrides._ITEM_SPELL_SHIELD_PROB``). Guardian's shield
    duration is ALSO exactly 1.5s and its shape is the same cooldown-gated single
    reactive absorb, so it lands on the existing price for that shape rather than
    inventing one.

It is RESTATED as a literal rather than imported: an import would couple a rune
registry to a champion registry with a different flip gate, and the sibling
registries are all import-pure for that reason. The restatement is documented
here and pinned by ``AmortizationTests``, which asserts the 0.3 ceiling holds.
Operator-tunable; a future Phase-D live pass tunes it per rune without touching
any math.

FAIL-SOFT, mirroring ``_rune_hsp_amp``: an empty / None rune list, a
non-iterable, a garbage entry, or a non-numeric pool argument all return 0.0, so
the orchestrator's DEFAULT-OFF seam stays BYTE-IDENTICAL.

PERCENT IS TAKEN ON THE CALLER'S RESOLVED POOL. ``total_hp`` / ``base_hp`` are
the resolved build health and the base per-level health - the same pair
``_rune_resist_grants`` receives for armor / MR. Neither may already contain this
registry's own output: feeding peer grant-lane output back into a grant lane is
grant-on-grant compounding and makes the result depend on the SOURCE ORDER of the
peer registries (GUARD 2 of
``tests/test_rune_resist_signature_convention_r134.py``).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL. ``apply_rune_shield_grants`` defaults False on
this function itself (belt and braces, the ``_rune_health_grants`` posture): an
un-opted caller gets 0.0 no matter what rune page it passes. The orchestrator
owns the ``compute_ehp`` seam, the live default-ON flip, and the decision about
how the returned amount folds into the numerator - this module takes no position
on that and holds no feature flag of its own.

Keyed by string rune_id to match the engine's id convention (strings throughout);
integer ids are coerced on lookup, and a repeated id is credited at most once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# --- Guardian (8465) - EXACT DDragon 16.14.1 magnitudes ----------------------
# "Shield: <scaleLevel>40 - 150</scaleLevel>" - the level-1 and level-18
# endpoints of the linear walk.
_GUARDIAN_SHIELD_AT_LEVEL_1: float = 40.0
_GUARDIAN_SHIELD_AT_LEVEL_18: float = 150.0

# "<scalehealth>6%</scalehealth> of your bonus health". Stored as a PERCENT
# (6.0 == 6%) to match the _rune_resist_grants field convention (75.0 == 75%),
# NOT the _rune_hsp_amp fraction convention - the consumers differ.
_GUARDIAN_BONUS_HP_PCT: float = 6.0

# "Cooldown: <scaleLevel>75 - 40</scaleLevel> seconds". Not used in the credited
# magnitude - it is the evidence behind the amortization midpoint below, and it
# is exposed so the duty-cycle argument in this docstring is reproducible in a
# test rather than only asserted in prose.
_GUARDIAN_COOLDOWN_AT_LEVEL_1: float = 75.0
_GUARDIAN_COOLDOWN_AT_LEVEL_18: float = 40.0

# The shield holds 1.5s. Kept as a named constant for the same reason as the
# cooldown - it is the numerator of the raw duty cycle the midpoint overrides.
_GUARDIAN_SHIELD_DURATION_S: float = 1.5

# Operator-tunable amortization midpoint - the expected share of the modeled
# sustained fight the wielder's own Guardian shield is realized. See the module
# docstring for the full argument. In short: the raw duty cycle is ~0.02-0.0375
# (1.5s on a 75-40s cooldown), but the shield is ENGAGEMENT-SYNCHRONIZED - it
# fires ON the incoming damage the EHP frame models, so the raw duty cycle
# under-prices it. It is priced BELOW the 0.3 sibling
# (_rune_resist_grants._RUNE_ACTIVE_RESIST_PROB) because Guardian's cooldown is
# 2x-3.75x Aftershock's and cannot fire twice in one fight. 0.2 is the value this
# engine already accepts for "a reactively popped 1.5s spell shield"
# (_champion_spell_shield_overrides._SPELL_SHIELD_REACTIVE_PROB, line 111);
# Guardian's shield is also exactly 1.5s and the same cooldown-gated single
# reactive absorb, so it adopts that existing price rather than a new one.
# Restated, not imported, to keep this registry import-pure. The Proc Threshold
# ("50 - 165 postmitigation damage") is folded in HERE - it is why the midpoint
# is not higher, since sub-threshold chip damage never procs the guard.
_RUNE_GUARDIAN_SHIELD_PROB: float = 0.2


@dataclass(frozen=True)
class RuneShieldEntry:
    """One rune-keyed SELF-side shield grant.

    Every field carries a default so a future required field can be appended at
    the END without reordering (the repo dataclass convention).

    ``shield_at_level_1`` / ``shield_at_level_18`` are the endpoints of a linear
    "based on level" walk; a rune with a level-flat shield sets both to the same
    value. ``bonus_hp_pct`` carries a PERCENT (6.0 == 6%) of the wielder's BONUS
    health (total minus base), clamped at zero so a below-base build never
    subtracts. The two terms SUM.

    ``conditional_probability`` amortizes the firing window. It is the ONLY
    assumption an entry carries - every magnitude field is exact DDragon.

    NOTE THE ABSENCE OF ANY ABILITY-POWER FIELD. That is deliberate and is
    asserted by ``test_no_ap_field_exists_on_the_entry_dataclass``: ``ehp.py``
    carries no wielder AP value, so an AP field here could only be populated with
    a fabricated number. See the module docstring.

    ``family`` dedups mutually exclusive / aliased ids, mirroring every sibling
    registry. Runes have no mirror ids today, so the single entry gets its own
    family; the field exists so a future alias (a rune shard or a mode variant)
    cannot silently double-credit.
    """

    shield_at_level_1: float = 0.0
    shield_at_level_18: float = 0.0
    bonus_hp_pct: float = 0.0
    conditional_probability: float = _RUNE_GUARDIAN_SHIELD_PROB
    family: str = ""
    note: str = ""


_RUNE_SHIELD_GRANTS: dict[str, RuneShieldEntry] = {
    # 8465 Guardian (Resolve keystone) - verbatim: "Guard allies within 350 units
    # of you ... both of you gain a shield for 1.5s. ... Shield: 40 - 150 + 20%
    # of your ability power + 6% of your bonus health". SELF HALF ONLY, and the
    # ability-power term is deliberately absent (unrepresentable at the EHP
    # seam). Both omissions are argued at length in the module docstring.
    "8465": RuneShieldEntry(
        shield_at_level_1=_GUARDIAN_SHIELD_AT_LEVEL_1,
        shield_at_level_18=_GUARDIAN_SHIELD_AT_LEVEL_18,
        bonus_hp_pct=_GUARDIAN_BONUS_HP_PCT,
        family="guardian",
        note=(
            "Guardian: self-shield of 40-150 by level plus 6% bonus health, "
            "1.5s on a 75-40s cooldown; the ally half and the 20% ability-power "
            "term are deliberate omissions, both undercounting"
        ),
    ),
}

# DELIBERATE ONE-ID ALLOWLIST, not a tree-wide sweep. Every other current-patch
# Resolve rune was read and ROUTED AWAY rather than overlooked:
#   * 8437 Grasp of the Undying - a HEAL plus permanent max HP. Already credited
#     by _rune_health_grants; no shield clause at all.
#   * 8439 Aftershock  - bonus resists (plus a magic-damage explosion). The
#     _rune_resist_grants lane and rune_procs.py respectively.
#   * 8429 Conditioning - flat and percent bonus resists. _rune_resist_grants.
#   * 8242 Unflinching  - flat bonus resists while crowd controlled.
#     _rune_resist_grants.
#   * 8451 Overgrowth   - permanent max health. _rune_health_grants.
#   * 8453 Revitalize   - Heal and Shield Power. A MULTIPLIER on shields, not a
#     shield. _rune_hsp_amp owns it, and it is a CONSUMER of this module's
#     output rather than a peer source of it.
#   * 8473 Bone Plating - "the next 3 spells or attacks you receive from them
#     deal 30-60 (based on level) less damage". A flat PER-INSTANCE damage BLOCK,
#     which is the _rune_flat_mitigation / _passive_mitigation_overrides lane. A
#     block is not an absorb pool: it shaves a fixed amount off each of three
#     instances rather than soaking a single budget, so folding it in here would
#     both double-credit that registry and use the wrong arithmetic.
#   * 8446 Demolish     - bonus physical damage to TOWERS. Not a survivability
#     term in any lane.
#   * 8463 Font of Life - DATA-BLOCKED, and deliberately NOT built. Its longDesc
#     heal magnitude is the UNRESOLVED DDragon template variable "@BaseHeal@",
#     present verbatim in ALL FOUR vendored snapshots, so there is no number to
#     read. It is also an ALLY heal, not a self shield, so it fails this
#     registry's SELF and SHIELD tests independently of the data block.
#   * 8444 Second Wind  - "heal for 4% of your missing health over 10s". A HEAL,
#     not a shield, and it is being built in a PARALLEL SLICE. It must not be
#     duplicated here.


__all__ = [
    "RuneShieldEntry",
    "_RUNE_SHIELD_GRANTS",
    "rune_shield_grants",
    "guardian_shield_base",
    "guardian_cooldown",
    "guardian_self_shield",
]


def _lerp_by_level(at_level_1: float, at_level_18: float, level: int) -> float:
    """Linear interpolation across the 17 level-ups between level 1 and 18.

    The standard Riot "based on level" reading used throughout the engine, with
    identical semantics to ``_rune_resist_grants.aftershock_resist_cap``. Works
    for a DECREASING walk (Guardian's 75-to-40s cooldown) as well as an
    increasing one. ``level`` is clamped into ``[1, 18]`` so an out-of-range
    caller yields the nearest endpoint rather than an extrapolated value.
    """
    lv = max(1, min(18, int(level)))
    return at_level_1 + (at_level_18 - at_level_1) * (lv - 1) / 17.0


def guardian_shield_base(level: int) -> float:
    """Guardian's level-scaled flat shield term - 40 at level 1, 150 at 18.

    Verbatim longDesc clause: "Shield: 40 - 150 + ...". This is the FLAT half
    only; the 6%-of-bonus-health half is added by ``guardian_self_shield`` and
    the 20%-ability-power half is deliberately absent (see the module docstring).
    """
    entry = _RUNE_SHIELD_GRANTS["8465"]
    return _lerp_by_level(
        entry.shield_at_level_1, entry.shield_at_level_18, level
    )


def guardian_cooldown(level: int) -> float:
    """Guardian's level-scaled cooldown - 75s at level 1, 40s at 18.

    Verbatim longDesc clause: "Cooldown: 75 - 40 seconds". Exposed so the raw
    duty cycle behind ``_RUNE_GUARDIAN_SHIELD_PROB`` is reproducible in a test
    rather than only argued in prose. It does NOT enter the credited magnitude -
    the amortization midpoint is a single operator-tunable constant, not a
    computed duty cycle, precisely because the shield is engagement-synchronized
    rather than uniformly distributed.
    """
    return _lerp_by_level(
        _GUARDIAN_COOLDOWN_AT_LEVEL_1, _GUARDIAN_COOLDOWN_AT_LEVEL_18, level
    )


def _entry_shield(
    entry: RuneShieldEntry, level: int, total_hp: float, base_hp: float
) -> float:
    """Exact pre-amortization shield magnitude for one entry.

    The level-scaled flat term PLUS ``bonus_hp_pct`` of ``max(0.0, total - base)``
    - the percent-of-BONUS clamp of ``_rune_resist_grants.py:273-275``, so a
    below-base build contributes the flat term alone rather than a negative. The
    result is floored at 0.0 so a degenerate pool cannot produce a negative
    numerator term.
    """
    total = _lerp_by_level(entry.shield_at_level_1, entry.shield_at_level_18, level)
    if entry.bonus_hp_pct:
        bonus_hp = max(0.0, float(total_hp) - float(base_hp))
        total += bonus_hp * (entry.bonus_hp_pct / 100.0)
    return max(0.0, total)


def guardian_self_shield(*, level: int, total_hp: float, base_hp: float) -> float:
    """Guardian's EXACT self-shield magnitude, BEFORE amortization.

    ``scaleLevel(40 -> 150)`` plus ``6% of max(0.0, total_hp - base_hp)``. This is
    what the tooltip says the wielder's own shield is worth at that level and
    build, MINUS the unrepresentable ability-power term - so it is a deliberate
    lower bound on the true value, never an over-estimate.

    Keyword-only ON PURPOSE: the signature accepts no ability-power argument, so
    an edit that tries to pass one raises ``TypeError`` instead of silently
    doing nothing. That is the omission tripwire described in the module
    docstring.

    Exposed separately from the seam so the DDragon endpoints and the
    bonus-health clamp are testable without constructing a rune page or opting
    into the seam flag.
    """
    return _entry_shield(_RUNE_SHIELD_GRANTS["8465"], level, total_hp, base_hp)


def rune_shield_grants(
    rune_ids: Optional[Iterable[str | int]],
    *,
    level: int,
    total_hp: float,
    base_hp: float,
    apply_rune_shield_grants: bool = False,
) -> float:
    """Return the amortized SELF-side rune shield amount, in HP.

    A bare float EHP-NUMERATOR contribution - a temporary absorb pool, so it
    lifts physical, magical AND true EHP uniformly (true EHP ignores resists, so
    a denominator term cannot reach it, but a numerator term can). This function
    takes NO position on how the caller folds it in; the orchestrator owns that
    seam, the ``compute_ehp`` wiring and the live default-ON flip.

    ``total_hp`` is the champion's RESOLVED build max health and ``base_hp`` the
    base per-level health - the same pair ``_rune_resist_grants`` receives for
    armor / MR, and neither may already contain this registry's own output (no
    grant-on-grant compounding). ``level`` drives the flat term's linear walk.

    Per entry the exact magnitude is computed first and ONLY THEN scaled by the
    entry's ``conditional_probability`` - the magnitude is a game mechanic, the
    probability is our modeling assumption about uptime, so the order matters
    (the ``_rune_resist_grants`` cap-before-probability contract).

    ``apply_rune_shield_grants`` is the DEFAULT-OFF gate: False (the default)
    returns 0.0 for ANY rune page, so an un-opted caller is byte-identical.

    A ``family`` tag is credited at most once, so a duplicated or aliased id
    cannot double-credit; different families sum. Runes outside the one-id
    allowlist contribute 0.0 by construction, so a full offensive page returns
    exactly 0.0.

    FAIL-SOFT: an empty / None / non-iterable rune list, a garbage entry, or a
    non-numeric pool argument returns 0.0 rather than raising.
    """
    if not apply_rune_shield_grants or not rune_ids:
        return 0.0
    try:
        iterator = iter(rune_ids)
    except TypeError:
        return 0.0
    total = 0.0
    seen_families: set[str] = set()
    for rid in iterator:
        try:
            entry = _RUNE_SHIELD_GRANTS.get(str(rid))
        except Exception:
            continue
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        seen_families.add(entry.family)
        try:
            magnitude = _entry_shield(entry, level, total_hp, base_hp)
        except (TypeError, ValueError):
            # A non-numeric pool or level argument - stay inert rather than
            # propagating into the EHP numerator.
            return 0.0
        total += magnitude * entry.conditional_probability
    return total
