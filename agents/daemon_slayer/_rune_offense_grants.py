"""Per-rune adaptive OFFENSIVE stat-grant registry, keyed by rune id.

The OFFENSE-side mirror of the R132 ``_rune_resist_grants`` lane. Where that
registry credits a rune-granted bonus armor / magic resist into the EHP
DENOMINATOR, this one credits a rune-granted adaptive bonus ATTACK DAMAGE /
ABILITY POWER into the DPS stat block - the axis every DS offensive scorer
already reads from items and from nothing else.

Three runes are seeded: the two Sorcery adaptive stat grants (Gathering Storm
8236, Absolute Focus 8233) and the Precision keystone Conqueror 8010.

WHAT WAS MISSING. ``rune_procs.py`` DOES register both Sorcery adaptive stat
grants - Absolute Focus 8233 (``rune_procs.py:743``) and Gathering Storm 8236
(``rune_procs.py:762``) - but it registers them with ``proc_type="adaptive"``,
and EVERY consumer of that registry skips exactly that proc_type:

  * ``burst.py:1034``   -> ``if proc is None or proc.proc_type == "adaptive": continue``
  * ``fight_report.py:45`` -> "adaptive" returns a stat value, not damage, so it
    is surfaced as a report line and never folded into a damage total.

So the adaptive force is COMPUTED and then DISCARDED. No DPS, ability-DPS,
hybrid or rank path has ever seen it. ``rune_procs.py:426`` and
``rune_procs.py:434`` state this outcome in their own words ("the grant does NOT
enter the burst total", "burst is BYTE-IDENTICAL"), which was the correct call
for a BURST scorer at t=0 but leaves the SUSTAINED scorers - which evaluate a
completed six-item build well past the 10-minute mark - crediting zero AD/AP for
a rune that grants up to 101 AD or 168 AP. This registry closes that.

DDragon 16.14.1 ``runesReforged.json`` longDescs, quoted VERBATIM (tags stripped,
text otherwise unaltered):

  * 8236 Gathering Storm: "Every 10 min gain AP or AD, adaptive.<br><br><i>10
    min</i>: + 8 AP or 5 AD <br><i>20 min</i>: + 24 AP or 14 AD<br><i>30 min</i>:
    + 48 AP or 29 AD<br><i>40 min</i>: + 80 AP or 48 AD<br><i>50 min</i>: + 120
    AP or 72 AD<br><i>60 min</i>: + 168 AP or 101 AD<br>etc..."
  * 8233 Absolute Focus: "While above 70% health, gain an adaptive bonus of up to
    18 Attack Damage or 30 Ability Power (based on level). <br><br>Grants 1.8
    Attack Damage or 3 Ability Power at level 1. "
  * 8010 Conqueror: "Basic attacks or spells that deal damage to an enemy
    champion grant 2 stacks of Conqueror for 5s, gaining 1.8-4 Adaptive Force
    per stack. Stacks up to 12 times. Ranged champions gain only 1 stack per
    basic attack.<br><br>When fully stacked, heal for 8% of the damage you deal
    to champions (5% for ranged champions)."

GATHERING STORM IS A STEP FUNCTION, NOT A RAMP - this is the load-bearing
modelling decision and it is a deliberate DIVERGENCE from the pre-existing
``rune_procs._gathering_storm``, which linearly interpolates ``5.0 * t / 600``
and admits so in its own comment ("the longDesc accelerates at later milestones
but the 10-min cadence anchor is the honest first-order ramp"). The feed does not
describe a ramp. It says "Every 10 min GAIN" and then enumerates six discrete
milestone rows whose spacing is manifestly non-linear on the AD side
(5, 14, 29, 48, 72, 101 - first differences 9, 15, 19, 24, 29). A linear read
prices 30 minutes at 15 AD where the feed says 29 AD, understating the rune by
roughly half at exactly the game time the sustained scorers model. The step table
below is transcribed from the feed and nothing is interpolated between rows.

BEYOND 60 MINUTES IS DATA-BLOCKED. The feed terminates the table with "etc..."
and states no magnitude for the 70-minute row or later. The first differences do
not extrapolate to a single defensible next value, so this registry CLAMPS at the
60-minute row rather than inventing one. Recorded, not guessed.

BELOW 10 MINUTES IS ZERO, and that is the feed's own text, not an assumption:
"Every 10 min gain" places the first grant AT the 10-minute mark, so
``game_minute`` under 10.0 yields no stack and the entry contributes 0.0.

ABSOLUTE FOCUS carries NO uptime assumption either. Its gate is on the CASTER's
health ("While above 70% health") and the sustained-DPS frame this registry feeds
models a full-health caster - the same frame ``compute_dps`` already expresses
through ``assume_caster_lowhp=False``. So the gate is evaluated at the explicit,
overridable ``caster_hp_pct`` argument (default 1.0, which passes), and its
magnitude is the feed's own level walk from the level-1 endpoint (1.8 AD / 3.0
AP) to the level-18 endpoint (18.0 AD / 30.0 AP) using the standard Riot linear
per-level interpolation every other "based on level" magnitude in this engine
uses. Nothing here is a tuned constant.

CONQUEROR'S RAW FEED NUMBER IS ADAPTIVE FORCE, NOT AD - converting it is
mandatory and is the easiest way to get 8010 wrong. Gathering Storm and Absolute
Focus each enumerate their two columns explicitly ("168 AP or 101 AD"; "18 Attack
Damage or 30 Ability Power"), so those entries transcribe and never convert.
Conqueror states only the undifferentiated scalar "1.8-4 Adaptive Force per
stack", so this entry MUST apply Riot's conversion: 1 Adaptive Force is 1 Ability
Power OR 0.6 Attack Damage. That ratio is not imported from outside - it is the
registry's OWN data, since ``round(0.6 * ap) == ad`` holds for every stated row
above (18/30; 5/8, 14/24, 29/48, 48/80, 72/120, 101/168), and a property test
pins it against those rows so the conversion cannot drift from the feed. Reading
the raw Adaptive Force scalar straight onto the AD column would inflate the AD
side by 1/0.6 = 1.667x.

CONQUEROR'S STACK COUNT IS A KNOB, NOT A HARDCODED 12 - this is the load-bearing
modelling decision for 8010. The feed's cap is 12 ("Stacks up to 12 times"), and
``rune_procs.py:212`` states the engine's own contract for this rune in its own
words: "compute_rune_proc_damage surfaces the PER-STACK adaptive force; the
caller multiplies by the live stack count (max 12)". The stack count therefore
belongs to the CALLER, and this module exposes it as
``_ASSUMED_CONQUEROR_STACKS`` (default 12.0, the feed's cap) overridable per call
via ``conqueror_stacks`` - exactly the shape ``_ASSUMED_GAME_MINUTE`` /
``game_minute`` already has here.

WHY A KNOB RATHER THAN A CONSTANT - the SIGN OF THE CONSERVATISM INVERTS between
the two sides of the fight. On a THREAT lane, assuming an ENEMY is at max stacks
is the pessimistic-for-the-player reading: it over-states incoming danger, which
is the safe direction to be wrong in. On the SELF side the identical assumption
over-states OUR OWN build and flatters every item ranked underneath it - the
unsafe direction. A max-stack default is defensible for the fully-committed
teamfight this registry models, but it must stay a stated, overridable assumption
rather than a baked-in constant, so a consumer holding a real stack reading can
supply it. For that reason no precedent is taken from any threat-lane treatment
of this rune; the citation above is the feed and the rune_procs contract.

THE RANGED STACK PENALTY IS OUT OF SCOPE, recorded rather than guessed. The feed
says "Ranged champions gain only 1 stack per basic attack" - a stacking-RATE
difference against a cap that is 12 for everyone. ``rune_offense_grants`` has no
role parameter and no attack-range input: ``burst.py:1030`` derives its
``_caster_role`` from attackrange, but this lane never receives it. Applying a
ranged reduction would mean inventing a magnitude rather than deriving one, so it
is left unmodeled and stated. A consumer that knows the real accrual should
express it through the ``conqueror_stacks`` knob, which is what the knob is for.

ADAPTIVE SIDE RESOLUTION reuses the engine's existing rule rather than restating
it: ``rune_procs._adaptive_coeff`` documents "AD wins ties (League's adaptive
force defaults to AD when AD bonus >= AP bonus)". This module applies the same
comparison to pick which column of each entry pays out, comparing the build's
BONUS AD against its AP - so an AP build gets the AP column and an AD build the
AD column, decided by the resolved build rather than by a per-champion guess.

DELIBERATE EXCLUSIONS - read and rejected, not overlooked. This registry is a
seeded ALLOWLIST like its R132 sibling, and the rest of the Sorcery + Domination
+ Precision offensive surface is out of it for stated reasons:

  * 8010 Conqueror's fully-stacked HEAL ("heal for 8% of the damage you deal to
    champions (5% for ranged champions)") is EXCLUDED while its Adaptive Force
    is credited. The two halves of that rune sit on different axes: the force is
    a persistent offensive stat and belongs in the DPS numerator this registry
    feeds, but the heal is SUSTAIN - it converts damage already dealt into
    effective health and moves no DPS field. It is the survivability lane's to
    price (the same lane that already carries heal / shield / DR), not this
    one's. Crediting it here would be scoring a defensive quantity on an
    offensive axis, and would silently double-count once the sustain lane
    reaches it.
  * 8232 Waterwalking ("Gain 10 Move Speed and 13 - 30 Adaptive Force (based on
    level) when in the river") DOES grant adaptive force with an exact magnitude,
    but only "when in the river". Unlike Absolute Focus's caster-HP gate and
    Gathering Storm's game-clock gate, river occupancy has NO anchor anywhere in
    this engine - crediting it would require inventing an uptime constant with
    nothing to calibrate against, and the modeled sustained teamfight is not a
    river fight by default. EXCLUDED as an uptime-blocked entry, not as a
    non-grant. It is the single best candidate for a future pass that gains a
    positional signal.
  * 8210 Transcendence, 8106 Ultimate Hunter grant Ability Haste only. Ability
    Haste as a DS axis was MEASURED INERT and is settled - not re-litigated here.
  * 8226 Manaflow Band grants maximum MANA ("permanently increases your maximum
    mana by 25, up to 250 mana"), which is the ``_item_mana_health`` axis, not an
    offensive stat.
  * 8234 Celerity, 8275 Nimbus Cloak, 8105 Relentless Hunter, 8230 Phase Rush
    grant MOVE SPEED only - no offensive stat on any of them.
  * 9923 Hail of Blades grants "120% (60% for ranged champions) Attack Speed ...
    for up to 3 attacks" - a real offensive stat, but a 3-attack window on a 10s
    cooldown is a BURST-window steroid, and it is ALREADY registered and scored
    in ``rune_procs.py:685``. Adding it here would double-credit it.
  * 8112 Electrocute, 8128 Dark Harvest, 8229 Arcane Comet, 8214 Summon Aery,
    8237 Scorch, 8126 Cheap Shot, 8143 Sudden Impact, 8992 Deathfire Touch are
    PROC DAMAGE, already registered in ``rune_procs.py`` and scored by the burst
    consumer. They grant no persistent stat.
  * 8135 Treasure Hunter (gold), 8140 Grisly Mementos (trinket haste), 8141 Deep
    Ward (ward duration), 8137 Sixth Sense (vision), 8139 Taste of Blood (heal),
    8224 Nullifying Orb (ultimate damage amp, a multiplier lane not a stat) grant
    no AD, AP or attack speed.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_rune_offense_grants`` seam on
``compute_dps`` / ``compute_hybrid`` / ``rank_items_by_hybrid`` defaults False;
with it OFF both grants are 0.0 and every DPS field is unchanged, even when a
full rune page is supplied via ``rune_ids``. The live default-ON flip is
operator-gated, mirroring ``apply_rune_resist_grants``.

Keyed by string rune_id to match the engine's item-id convention (strings
throughout); integer ids are coerced on lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# Operator-tunable game-clock reading for the modeled fight, EXPLICIT so no
# caller silently inherits a lategame assumption. Adopted UNCHANGED from
# ``_rune_resist_grants._ASSUMED_GAME_MINUTE`` so the two rune lanes read the
# same clock and stay comparable; overridable per call via ``game_minute``,
# which a live consumer can drive from the real Live Client game clock.
_ASSUMED_GAME_MINUTE: float = 15.0

# Gathering Storm 8236 milestone table, transcribed VERBATIM from the DDragon
# 16.14.1 longDesc as (minute, ad, ap) rows. NOT interpolated: the feed states
# "Every 10 min gain" and enumerates discrete rows, and the AD-side first
# differences (9, 15, 19, 24, 29) are plainly non-linear. Rows are ascending by
# minute; the lookup takes the LAST row whose minute has been reached.
_GATHERING_STORM_STEPS: tuple[tuple[float, float, float], ...] = (
    (10.0, 5.0, 8.0),
    (20.0, 14.0, 24.0),
    (30.0, 29.0, 48.0),
    (40.0, 48.0, 80.0),
    (50.0, 72.0, 120.0),
    (60.0, 101.0, 168.0),
)

# Absolute Focus 8233 level endpoints, verbatim: "up to 18 Attack Damage or 30
# Ability Power (based on level)" and "Grants 1.8 Attack Damage or 3 Ability
# Power at level 1."
_ABSOLUTE_FOCUS_AD_AT_LEVEL_1: float = 1.8
_ABSOLUTE_FOCUS_AD_AT_LEVEL_18: float = 18.0
_ABSOLUTE_FOCUS_AP_AT_LEVEL_1: float = 3.0
_ABSOLUTE_FOCUS_AP_AT_LEVEL_18: float = 30.0

# Absolute Focus's caster-health gate, verbatim: "While above 70% health".
# Strict greater-than, matching ``rune_procs._absolute_focus`` which returns 0.0
# at ``caster_hp_pct <= 0.70``.
_ABSOLUTE_FOCUS_HP_GATE: float = 0.70

# Riot's Adaptive Force conversion: 1 AF is 1 Ability Power OR 0.6 Attack Damage.
# Needed only by Conqueror, whose feed states a raw AF scalar instead of the two
# explicit columns its registry siblings enumerate. Pinned by a property test
# against those siblings' rows (round(0.6 * ap) == ad on all 7), so this is the
# registry's own ratio rather than an outside assertion.
_ADAPTIVE_FORCE_AD_PER_AF: float = 0.6

# Conqueror 8010 per-stack endpoints, verbatim: "gaining 1.8-4 Adaptive Force per
# stack." Units are ADAPTIVE FORCE, not AD - see the conversion above.
_CONQUEROR_AF_PER_STACK_AT_LEVEL_1: float = 1.8
_CONQUEROR_AF_PER_STACK_AT_LEVEL_18: float = 4.0

# The feed's hard cap, verbatim: "Stacks up to 12 times." Used to CLAMP a
# caller-supplied stack count, never as the stack count itself.
_CONQUEROR_MAX_STACKS: float = 12.0

# The modeled stack count, EXPLICIT and overridable per call via
# ``conqueror_stacks`` - rune_procs.py:212 puts the stack count on the caller
# ("the caller multiplies by the live stack count (max 12)"). Defaults to the cap
# for the fully-committed teamfight this registry models, but stays a knob
# because max-stacks is conservative on a threat lane and ANTI-conservative here.
_ASSUMED_CONQUEROR_STACKS: float = 12.0


def _clamp_level(level: float) -> float:
    """Clamp to the 1-18 champion level range, fail-soft to 1.0."""
    try:
        lvl = float(level)
    except (TypeError, ValueError):
        return 1.0
    if lvl < 1.0:
        return 1.0
    if lvl > 18.0:
        return 18.0
    return lvl


def _lerp_by_level(low: float, high: float, level: float) -> float:
    """Standard Riot linear per-level walk between the level-1 and level-18 endpoints."""
    lvl = _clamp_level(level)
    return low + (high - low) * (lvl - 1.0) / 17.0


def gathering_storm_step(game_minute: float) -> tuple[float, float]:
    """Return the ``(ad, ap)`` Gathering Storm grant at ``game_minute``.

    A STEP function over ``_GATHERING_STORM_STEPS``, never an interpolation.
    Below the first milestone (10 min) the rune has granted nothing and this
    returns ``(0.0, 0.0)``. Past the last stated milestone (60 min) the value is
    CLAMPED to the 60-minute row: the feed ends in "etc..." and states no
    magnitude beyond it, so extrapolating would be inventing a constant.
    """
    try:
        minute = float(game_minute)
    except (TypeError, ValueError):
        return (0.0, 0.0)
    ad = 0.0
    ap = 0.0
    for step_minute, step_ad, step_ap in _GATHERING_STORM_STEPS:
        if minute >= step_minute:
            ad, ap = step_ad, step_ap
        else:
            break
    return (ad, ap)


def absolute_focus_grant(level: float, caster_hp_pct: float) -> tuple[float, float]:
    """Return the ``(ad, ap)`` Absolute Focus grant at ``level``.

    Gated STRICTLY above 70% caster health per the verbatim longDesc; at or below
    the gate this returns ``(0.0, 0.0)``. Above it, the magnitude is the feed's
    own level-1 to level-18 walk.
    """
    try:
        hp_pct = float(caster_hp_pct)
    except (TypeError, ValueError):
        return (0.0, 0.0)
    if hp_pct <= _ABSOLUTE_FOCUS_HP_GATE:
        return (0.0, 0.0)
    return (
        _lerp_by_level(
            _ABSOLUTE_FOCUS_AD_AT_LEVEL_1, _ABSOLUTE_FOCUS_AD_AT_LEVEL_18, level
        ),
        _lerp_by_level(
            _ABSOLUTE_FOCUS_AP_AT_LEVEL_1, _ABSOLUTE_FOCUS_AP_AT_LEVEL_18, level
        ),
    )


def conqueror_grant(
    level: float, stacks: Optional[float] = None
) -> tuple[float, float]:
    """Return the ``(ad, ap)`` Conqueror grant at ``level`` and ``stacks``.

    Verbatim longDesc: "Basic attacks or spells that deal damage to an enemy
    champion grant 2 stacks of Conqueror for 5s, gaining 1.8-4 Adaptive Force per
    stack. Stacks up to 12 times. Ranged champions gain only 1 stack per basic
    attack. When fully stacked, heal for 8% of the damage you deal to champions
    (5% for ranged champions)."

    UNITS: the feed's per-stack number is ADAPTIVE FORCE, not AD. It pays out as
    the AP column directly and as ``0.6 * AF`` on the AD column, Riot's standard
    conversion - the same ratio every explicitly-enumerated row in this registry
    already exhibits. Returning the raw scalar on both columns would over-credit
    AD by 1.667x.

    ``stacks`` defaults to ``_ASSUMED_CONQUEROR_STACKS`` and is CLAMPED to the
    feed's 0..12 range. It is a knob rather than a constant because
    ``rune_procs.py:212`` assigns the live stack count to the caller, and because
    a max-stack assumption is conservative on a threat lane but ANTI-conservative
    on this one, where it flatters our own build.

    STATED LIMITATION - RANGED ACCRUAL IS OUT OF SCOPE: the "only 1 stack per
    basic attack" clause is not applied. It is a stacking-RATE difference against
    an identical 12 cap, and no role / attack-range input reaches this function
    (its surface is level and stacks), so applying it would mean inventing a
    magnitude rather than deriving one. A caller that knows the real accrual
    expresses it through ``stacks``.

    The fully-stacked 8% / 5% heal is deliberately NOT credited here; it is a
    sustain quantity on a different axis, not an offensive stat. See the module
    docstring's DELIBERATE EXCLUSIONS.
    """
    count = _ASSUMED_CONQUEROR_STACKS if stacks is None else stacks
    try:
        count = float(count)
    except (TypeError, ValueError):
        count = _ASSUMED_CONQUEROR_STACKS
    count = max(0.0, min(_CONQUEROR_MAX_STACKS, count))
    adaptive_force = count * _lerp_by_level(
        _CONQUEROR_AF_PER_STACK_AT_LEVEL_1,
        _CONQUEROR_AF_PER_STACK_AT_LEVEL_18,
        level,
    )
    return (_ADAPTIVE_FORCE_AD_PER_AF * adaptive_force, adaptive_force)


@dataclass(frozen=True)
class RuneOffenseEntry:
    """One rune's adaptive offensive stat grant.

    ``grant`` resolves the ``(ad, ap)`` PAIR the rune would give on each side; the
    caller then picks ONE side by the adaptive rule (AD on ties). Holding both
    columns rather than a pre-resolved scalar is what lets the adaptive decision
    be made from the RESOLVED BUILD instead of being baked into the registry.

    ``family`` mirrors the R132 lane's duplicate guard: a family is credited at
    most once, so a duplicated or aliased id cannot double-credit. Runes have no
    mirror ids today; the field exists so a future alias cannot silently stack.
    """

    name: str
    tree: str
    gate: str
    note: str
    family: str = ""
    _grant: object = field(default=None, repr=False)

    def grant(
        self,
        *,
        level: float,
        game_minute: float,
        caster_hp_pct: float,
        conqueror_stacks: Optional[float],
    ) -> tuple[float, float]:
        fn = self._grant
        if fn is None:  # pragma: no cover - every seeded entry supplies one
            return (0.0, 0.0)
        return fn(
            level=level,
            game_minute=game_minute,
            caster_hp_pct=caster_hp_pct,
            conqueror_stacks=conqueror_stacks,
        )


_RUNE_OFFENSE_GRANTS: dict[str, RuneOffenseEntry] = {
    # 8236 Gathering Storm (Sorcery, slot 4) - verbatim: "Every 10 min gain AP or
    # AD, adaptive. 10 min: + 8 AP or 5 AD  20 min: + 24 AP or 14 AD  30 min:
    # + 48 AP or 29 AD  40 min: + 80 AP or 48 AD  50 min: + 120 AP or 72 AD
    # 60 min: + 168 AP or 101 AD  etc..." Modeled as the discrete step table, not
    # a ramp; clamped at the 60-minute row because the feed states nothing past
    # it. Already registered in rune_procs.py:762 as proc_type "adaptive", which
    # every consumer skips - this entry is what actually pays it into the stats.
    "8236": RuneOffenseEntry(
        name="Gathering Storm",
        tree="Sorcery",
        gate="game_minute",
        family="gathering_storm",
        note=(
            "Gathering Storm: adaptive step grant at each 10-minute mark, "
            "5/14/29/48/72/101 AD or 8/24/48/80/120/168 AP, clamped at 60 min"
        ),
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks: (
            gathering_storm_step(game_minute)
        ),
    ),
    # 8233 Absolute Focus (Sorcery, slot 3) - verbatim: "While above 70% health,
    # gain an adaptive bonus of up to 18 Attack Damage or 30 Ability Power (based
    # on level). Grants 1.8 Attack Damage or 3 Ability Power at level 1." Level
    # walk between the two stated endpoints, gated STRICTLY above 70% caster
    # health. Already registered in rune_procs.py:743 as proc_type "adaptive",
    # which every consumer skips.
    "8233": RuneOffenseEntry(
        name="Absolute Focus",
        tree="Sorcery",
        gate="caster_hp_above",
        family="absolute_focus",
        note=(
            "Absolute Focus: adaptive 1.8-18 AD or 3-30 AP by level, "
            "while above 70% caster health"
        ),
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks: (
            absolute_focus_grant(level, caster_hp_pct)
        ),
    ),
    # 8010 Conqueror (Precision keystone, slot 0) - verbatim: "Basic attacks or
    # spells that deal damage to an enemy champion grant 2 stacks of Conqueror
    # for 5s, gaining 1.8-4 Adaptive Force per stack. Stacks up to 12 times.
    # Ranged champions gain only 1 stack per basic attack. When fully stacked,
    # heal for 8% of the damage you deal to champions (5% for ranged champions)."
    #
    # UNITS: the feed's "1.8-4 Adaptive Force per stack" is ADAPTIVE FORCE, not
    # AD. Its siblings above enumerate both columns and so never convert; this
    # one must, at Riot's 1 AF = 1 AP or 0.6 AD. At the default 12 stacks that is
    # 21.6-48.0 AP or 12.96-28.8 AD by level. Putting the raw AF scalar on the AD
    # column would over-credit AD by 1.667x - the specific error this entry is
    # written to avoid.
    #
    # STACK MODELLING: the stack count is a KNOB (_ASSUMED_CONQUEROR_STACKS,
    # default 12 = the feed's cap, per-call override conqueror_stacks), NOT a
    # hardcoded 12. rune_procs.py:212 assigns the live stack count to the caller
    # in its own words, and the conservatism inverts by side: max-stacks is the
    # safe pessimistic reading for an ENEMY's Conqueror but the unsafe optimistic
    # one for our own, where it inflates this build against every item ranked
    # under it. Hence a stated default, not a constant. The ranged
    # 1-stack-per-AA clause is left unmodeled because no role / attack-range
    # input reaches this lane - stated in conqueror_grant's docstring, and
    # expressible through the same knob.
    #
    # The fully-stacked 8% / 5% HEAL is deliberately excluded: it is sustain, not
    # an offensive stat, so it belongs to the survivability lane and not to this
    # DPS-numerator registry. Crediting it here would score a defensive quantity
    # on an offensive axis. See the module docstring's DELIBERATE EXCLUSIONS.
    "8010": RuneOffenseEntry(
        name="Conqueror",
        tree="Precision",
        gate="stack_uptime",
        family="conqueror",
        note=(
            "Conqueror: 1.8-4 Adaptive Force per stack by level at the "
            "assumed 12-stack count, converted to 21.6-48.0 AP or "
            "12.96-28.8 AD; the fully-stacked heal is sustain and is excluded"
        ),
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks: (
            conqueror_grant(level, conqueror_stacks)
        ),
    ),
}


def rune_offense_grants(
    rune_ids: Iterable[str | int],
    *,
    level: int,
    bonus_ad: float,
    ap: float,
    game_minute: Optional[float] = None,
    caster_hp_pct: float = 1.0,
    conqueror_stacks: Optional[float] = None,
) -> tuple[float, float]:
    """Return the ``(bonus_ad, bonus_ap)`` rune-side adaptive offensive grant.

    ``bonus_ad`` / ``ap`` are the champion's RESOLVED build offensive stats - the
    same pair ``compute_dps`` derives before it builds its ``CallContext``. They
    are read ONLY to decide the adaptive side; no entry scales off them, so a
    grant can never compound on another grant.

    ``level`` drives Absolute Focus's walk. ``game_minute`` defaults to the
    explicit, tunable ``_ASSUMED_GAME_MINUTE`` and drives Gathering Storm's step.
    ``caster_hp_pct`` defaults to 1.0 (the full-health sustained-DPS frame) and
    gates Absolute Focus. ``conqueror_stacks`` defaults to the equally explicit
    ``_ASSUMED_CONQUEROR_STACKS`` and scales Conqueror; it is a knob because
    ``rune_procs.py:212`` puts the live stack count on the caller and because a
    max-stack assumption flatters our own build on this side of the fight.

    Per entry: the ``(ad, ap)`` pair is resolved, then ONE side is taken by the
    standard adaptive rule (AD when ``bonus_ad >= ap``, matching
    ``rune_procs._adaptive_coeff``), then accumulated onto the matching return
    slot. A ``family`` tag is credited at most once, so a duplicated or aliased id
    cannot double-credit; different families sum.

    Runes not in the registry contribute 0 - the registry is a seeded allowlist,
    so every proc-damage keystone, every move-speed rune and every ability-haste
    rune returns 0.0 by construction. The returned values are added to
    ``bonus_ad`` and ``ap`` inside ``compute_dps``. The default-OFF gating lives
    in ``compute_dps`` (this function is only called when
    ``apply_rune_offense_grants`` is True).
    """
    minute = _ASSUMED_GAME_MINUTE if game_minute is None else float(game_minute)
    try:
        build_ad = float(bonus_ad)
    except (TypeError, ValueError):
        build_ad = 0.0
    try:
        build_ap = float(ap)
    except (TypeError, ValueError):
        build_ap = 0.0
    prefer_ad = build_ad >= build_ap

    grant_ad = 0.0
    grant_ap = 0.0
    seen_families: set[str] = set()
    for rid in rune_ids:
        entry = _RUNE_OFFENSE_GRANTS.get(str(rid))
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        if entry.family:
            seen_families.add(entry.family)
        side_ad, side_ap = entry.grant(
            level=level,
            game_minute=minute,
            caster_hp_pct=caster_hp_pct,
            conqueror_stacks=conqueror_stacks,
        )
        if prefer_ad:
            grant_ad += side_ad
        else:
            grant_ap += side_ap
    return (grant_ad, grant_ap)
