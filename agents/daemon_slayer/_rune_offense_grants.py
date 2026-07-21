"""Per-rune OFFENSIVE stat-grant registry, keyed by rune id.

The OFFENSE-side mirror of the R132 ``_rune_resist_grants`` lane. Where that
registry credits a rune-granted bonus armor / magic resist into the EHP
DENOMINATOR, this one credits a rune-granted bonus ATTACK DAMAGE / ABILITY
POWER / ATTACK SPEED into the DPS stat block - the axes every DS offensive
scorer already reads from items and from nothing else.

Five runes are seeded: the two Sorcery adaptive stat grants (Gathering Storm
8236, Absolute Focus 8233), the Precision keystone Conqueror 8010, the
Precision attack-speed grant Legend: Alacrity 9104, and the Inspiration
census-driven adaptive grant Jack Of All Trades 8316.

THREE COLUMNS, NOT TWO (R155). Every entry resolves an ``(ad, ap,
attack_speed_fraction)`` triple. The first two are ADAPTIVE - exactly one of
them pays out, chosen from the resolved build - and the third is NOT. Attack
speed has no adaptive sides: Legend: Alacrity grants the identical bonus to an
AD build and an AP build, so the third column BYPASSES the ``prefer_ad``
branch and accumulates on every entry. Folding it through the adaptive branch
would silently delete the grant for whichever side lost the comparison.

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
  * 9104 Legend: Alacrity: "Gain 3% attack speed plus an additional 1.5% for
    every <i>Legend</i> stack (<statGood>max 10 stacks</statGood>).<br><br>Earn
    progress toward <i>Legend</i> stacks for every champion takedown, epic
    monster takedown, large monster kill, and minion kill."
  * 8316 Jack Of All Trades: "For each different stat gained from items, gain
    one Jack stack. Each stack grants you 1 Ability Haste.<br><br>Gain 10 or 25
    bonus Adaptive Force at 5 and 10 stacks, respectively."

LEGEND: ALACRITY IS A FRACTION, AND THE FOLD IS WHERE IT GOES WRONG. The value
this entry returns is a BONUS-AS FRACTION (0.03 at zero stacks, 0.18 at the
feed's 10-stack cap), but ``stats["as"]`` in the DPS pipeline is FINAL attacks
per second - ``engine.py:196`` resolves it as ``base_as * (1 + bonus_pct)``.
League folds bonus attack speed onto the INNATE base AS, so the consumer MUST
scale by ``champ["stats"]["attackspeed"]`` before adding. Adding the raw
fraction to the final AS field over-credits by ``1 / base_as`` - the identical
unit bug R42 fixed for Yun Tal's ``cond_as`` and R7 for ``passive_as``, whose
folds this one is written to mirror exactly.

ATTACK-SPEED-LOCK CHAMPIONS GET ZERO, AND THAT IS DELIBERATE. ``engine.py:439``
zeroes ``item_totals["as_pct"]`` for any champion carrying an
``_passive_as_lock_overrides.as_lock_entry`` with ``locks_as`` set (Jhin's
Whisper: his attack speed cannot increase, and would-be bonus AS is converted
into bonus AD instead). The rune AS fold in ``dps.py`` runs DOWNSTREAM of that
zeroing, so the consumer re-checks the lock and grants nothing. The
``ad_per_bonus_as`` conversion is NOT applied to the rune: that coefficient was
authored against ITEM attack speed, and routing a rune through it would be
inventing a magnitude the override table was never built against. Conservative
by construction and recorded here rather than guessed.

LEGEND: ALACRITY'S STACK COUNT IS A KNOB, NOT A HARDCODED 10 - the same
doctrine as ``_ASSUMED_CONQUEROR_STACKS`` below, for the same reason. The feed
caps at 10 ("max 10 stacks"), and the accrual is a takedown / large-monster /
minion-kill counter that no input reaching this lane can observe. So the count
is ``_ASSUMED_LEGEND_STACKS`` (default 10.0, the feed's cap), overridable per
call via ``legend_stacks`` and clamped to 0..10. Max-stacks is the pessimistic
(safe) reading on a THREAT lane and the ANTI-conservative one here, where it
flatters our own build against every item ranked under it - so it must stay a
stated, overridable assumption rather than a baked-in constant.

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

JACK OF ALL TRADES'S STACK COUNT IS NOT A KNOB - it is the only entry here whose
count is COMPUTED, and computing it is the whole reason 8316 moved out of the
exclusions block. The feed says "For each different stat gained from items, gain
one Jack stack", so the census is over the engine's OWN canonical item-stat
decomposition: ``stats.aggregate_item_stats`` maps every DDragon item stat key
onto a ``{axis}_{flat|pct}`` slot, and ``jack_of_all_trades_stacks`` counts the
DISTINCT AXES with a nonzero total. The ``_flat`` / ``_pct`` kind suffix is
stripped before counting, so movement speed - which arrives through TWO DDragon
keys (``FlatMovementSpeedMod`` + ``PercentMovementSpeedMod``) and lands in two
slots - is one different stat and contributes one stack, which is what the feed
describes. R145's ``conqueror_stacks`` / R155's ``legend_stacks`` are knobs
because their accrual is an unobservable in-game counter; this one is a property
of the build the caller already holds, so it is derived instead of assumed.

THE CENSUS IS BLIND TO ABILITY HASTE, and that is a DATA limitation rather than
a modelling choice: ``ITEM_STAT_KEY_MAP`` has no Ability Haste entry at all
because DDragon item stat blocks do not carry one. So an AH-only item
contributes NO stack in this model and the census is a floor, not an exact
count. Recorded rather than guessed - inventing an AH column here would mean
inventing the per-item magnitudes to fill it. The rune's own ability-haste half
("Each stack grants you 1 Ability Haste") is uncredited for the separate and
settled reason that Ability Haste as a DS axis was MEASURED INERT.

STEP, NOT RAMP, AND THE TIERS ARE NOT SUMMED. "Gain 10 or 25 bonus Adaptive
Force at 5 and 10 stacks, respectively" is two discrete tiers joined by "or":
the 10-stack tier pays 25 TOTAL, replacing the 5-stack tier's 10 rather than
adding to it. Below 5 stacks the rune has granted no Adaptive Force at all, and
7 stacks pays exactly what 5 stacks pays. Reading it as a per-stack ramp, or
summing the two rows to 35, are the two ways to get the magnitude wrong.

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
  * 9105 Legend: Haste ("Gain 1.5 basic ability haste for every Legend stack
    (max 10 stacks)") is 9104's slot-mate and grants ABILITY HASTE only, so it
    falls under the same settled measured-inert finding. EXCLUDED permanently,
    not pending: crediting it would be scoring an axis this engine has proven
    moves nothing.
  * 9103 Legend: Bloodline ("Gain 0.45% Life Steal for every Legend stack (max
    15 stacks). At maximum Legend stacks, gain 85 max health") is the third
    Legend slot-mate. Both of its halves are SUSTAIN / EFFECTIVE-HEALTH - life
    steal and max health - so it belongs to the survivability lane that already
    prices heal / shield / DR, not to this DPS-numerator registry. Note its cap
    is 15 stacks, not 10: ``_LEGEND_MAX_STACKS`` here is Alacrity's own cap and
    must not be reused for Bloodline if that lane ever credits it.
  * 8316 Jack Of All Trades's ABILITY HASTE half ("Each stack grants you 1
    Ability Haste") stays EXCLUDED under the same settled measured-inert
    finding as 9105 above, while its ADAPTIVE FORCE half is CREDITED as of R156
    - the two halves of the rune sit on different axes and only one of them
    moves a DPS field. The R155 note recorded the Adaptive Force half as a
    MEASURED FUTURE blocked on a per-build distinct-stat census; that census is
    now built (``jack_of_all_trades_stacks`` over
    ``stats.aggregate_item_stats``) and the entry is seeded, so this bullet is
    kept as the record of what changed and why, not as a fence. The stack count
    is still never guessed: it is derived from the resolved build.
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

ALL FIVE TREES ARE MACHINE-GUARDED AS OF R159. R158 guarded DOMINATION 8100 (12
runes) and SORCERY 8200 (13 runes); R159 swept the remaining three - PRECISION
8000 (13), INSPIRATION 8300 (12) and RESOLVE 8400 (12) - so every one of the 62
runes the live DDragon feed carries is now either seeded above or recorded in
``_ADJUDICATED_NON_GRANTS`` below: 5 registered (8010, 8233, 8236, 8316, 9104)
and 57 adjudicated. ``tests/test_rune_offense_saturation_r158.py`` fails if the
feed ever carries a rune - in any tree - that is neither, if an adjudicated id
stops existing, if a tree id in its sweep list is not in the feed, or if the
feed grows a tree the list omits. The exclusions list above is no longer prose
anywhere: the registry is SATURATED against the whole feed, and further coverage
needs a schema lift (a role argument, a positional signal, a consumable-uptime
anchor), not another scan.

THREE ADJUDICATED ROWS ARE DELIBERATE GAPS RATHER THAN NON-GRANTS, and their
reasons name what blocks them instead of falsely claiming no offensive stat:
8232 Waterwalking (Adaptive Force, but river-uptime-blocked), 8008 Lethal Tempo
(stacking attack speed, but role-split with no role argument at this seam, and
already an input to its own rune_procs term) and 8313 Triple Tonic (a 60-second
Elixir of Force at level 6, with no consumable-uptime anchor).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_rune_offense_grants`` seam on
``compute_dps`` / ``compute_hybrid`` / ``rank_items_by_hybrid`` defaults False;
with it OFF all three grants are 0.0 and every DPS field is unchanged, even when
a full rune page is supplied via ``rune_ids``. The live default-ON flip is
operator-gated, mirroring ``apply_rune_resist_grants``.

Keyed by string rune_id to match the engine's item-id convention (strings
throughout); integer ids are coerced on lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# The census substrate. ``stats`` is a leaf module (stdlib imports only), so
# this cannot cycle back through the registry.
from .stats import aggregate_item_stats

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

# Legend: Alacrity 9104, verbatim: "Gain 3% attack speed plus an additional 1.5%
# for every Legend stack (max 10 stacks)." Units are a BONUS-AS FRACTION, never
# a final attacks/sec value - see the module docstring's fold note.
_LEGEND_ALACRITY_BASE_AS: float = 0.03
_LEGEND_ALACRITY_AS_PER_STACK: float = 0.015

# The feed's hard cap for the ALACRITY stack counter, verbatim: "max 10 stacks".
# Used to CLAMP a caller-supplied count, never as the count itself. NOT shared
# with Legend: Bloodline, whose own feed text caps at 15.
_LEGEND_MAX_STACKS: float = 10.0

# The modeled Legend stack count, EXPLICIT and overridable per call via
# ``legend_stacks``. Defaults to the feed's cap for the completed-build fight
# this registry models, but stays a knob for the same reason
# _ASSUMED_CONQUEROR_STACKS does: max-stacks is conservative on a threat lane
# and ANTI-conservative on our own build.
_ASSUMED_LEGEND_STACKS: float = 10.0

# Jack Of All Trades 8316, verbatim: "For each different stat gained from items,
# gain one Jack stack. Each stack grants you 1 Ability Haste. Gain 10 or 25
# bonus Adaptive Force at 5 and 10 stacks, respectively." Units on the two tier
# values are ADAPTIVE FORCE, so they convert through
# _ADAPTIVE_FORCE_AD_PER_AF exactly as Conqueror's do. The tiers REPLACE one
# another ("10 or 25"), they do not sum, and nothing is granted below the low
# tier. 10 stacks is both the high tier and the model's cap: the feed states no
# row above it and the census has no axis left to add.
_JACK_AF_AT_LOW_TIER: float = 10.0
_JACK_AF_AT_HIGH_TIER: float = 25.0
_JACK_LOW_TIER_STACKS: float = 5.0
_JACK_HIGH_TIER_STACKS: float = 10.0
_JACK_MAX_STACKS: float = 10.0


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


def legend_alacrity_grant(stacks: Optional[float] = None) -> float:
    """Return the Legend: Alacrity bonus-ATTACK-SPEED FRACTION at ``stacks``.

    Verbatim longDesc: "Gain 3% attack speed plus an additional 1.5% for every
    Legend stack (max 10 stacks). Earn progress toward Legend stacks for every
    champion takedown, epic monster takedown, large monster kill, and minion
    kill."

    So 0.03 at zero stacks, 0.18 at the feed's 10-stack cap, linear between.
    Nothing here is interpolated or tuned: both coefficients and the cap are the
    feed's own numbers.

    UNITS: the return is a bonus-AS FRACTION. The consumer must fold it as
    ``innate_base_as * fraction`` onto the FINAL attacks/sec field, not add it
    raw - see the module docstring. This function has no unit ambiguity to
    resolve on its own, so the contract is stated at both ends.

    ``stacks`` defaults to ``_ASSUMED_LEGEND_STACKS`` and is CLAMPED to the
    feed's 0..10 range. It is a knob rather than a constant because the accrual
    is a takedown / large-monster / minion-kill counter that no input reaching
    this lane observes, and because a max-stack assumption flatters our own
    build on this side of the fight. A caller holding a real Legend count
    supplies it.

    STATED LIMITATION - THE ACCRUAL RATE IS OUT OF SCOPE: the feed enumerates
    four progress sources but states no per-source progress value, so no
    time-to-max model is derivable from it. That is why the count is an
    assumption with a knob and not a computed quantity.
    """
    count = _ASSUMED_LEGEND_STACKS if stacks is None else stacks
    try:
        count = float(count)
    except (TypeError, ValueError):
        count = _ASSUMED_LEGEND_STACKS
    count = max(0.0, min(_LEGEND_MAX_STACKS, count))
    return _LEGEND_ALACRITY_BASE_AS + count * _LEGEND_ALACRITY_AS_PER_STACK


def jack_of_all_trades_stacks(item_stat_blocks) -> float:
    """Census the DISTINCT canonical stat AXES a resolved build supplies.

    Verbatim longDesc: "For each different stat gained from items, gain one Jack
    stack." The census is taken over the engine's own item-stat decomposition -
    ``aggregate_item_stats`` maps each DDragon key onto a ``{axis}_{kind}`` slot
    - by stripping the ``_flat`` / ``_pct`` kind suffix and counting the axes
    with a nonzero total. An axis reached through BOTH a flat and a pct key
    (movement speed is the live case) is ONE different stat and so contributes
    ONE stack, which is the specific miscount this shape exists to avoid.

    ``item_stat_blocks`` is the same list ``engine.py:318-320`` builds from a
    resolved build: ``[record.get("stats", {}) for record in item_records]``.

    STATED LIMITATION - ABILITY HASTE IS INVISIBLE HERE: ``ITEM_STAT_KEY_MAP``
    carries no Ability Haste key because DDragon item stat blocks do not carry
    one, so an AH-only item adds no stack and this count is a floor rather than
    an exact census. Recorded, not guessed.

    Clamped to ``0.._JACK_MAX_STACKS`` and fail-soft to 0.0 on junk input, so a
    caller that cannot decompose its build gets no grant rather than a wrong one.
    """
    try:
        blocks = [b for b in item_stat_blocks if isinstance(b, dict)]
        totals = aggregate_item_stats(blocks)
    except (TypeError, ValueError, AttributeError):
        return 0.0
    per_axis: dict[str, float] = {}
    for slot, value in totals.items():
        axis = slot.rsplit("_", 1)[0]
        per_axis[axis] = per_axis.get(axis, 0.0) + abs(float(value))
    count = float(sum(1 for total in per_axis.values() if total > 0.0))
    return max(0.0, min(_JACK_MAX_STACKS, count))


def jack_of_all_trades_grant(stacks) -> tuple[float, float]:
    """Return the ``(ad, ap)`` Jack Of All Trades grant at ``stacks``.

    Verbatim longDesc: "For each different stat gained from items, gain one Jack
    stack. Each stack grants you 1 Ability Haste. Gain 10 or 25 bonus Adaptive
    Force at 5 and 10 stacks, respectively."

    A STEP FUNCTION WITH TWO TIERS, NOT A RAMP - the feed enumerates exactly two
    magnitudes at exactly two stack counts, so 7 stacks pays what 5 stacks pays
    and 4 stacks pays nothing. Reading "one Jack stack" per stat as a per-stack
    Adaptive Force accrual is the misread: the stacks are the COUNTER, and only
    the two stated thresholds pay.

    THE TIERS ARE NOT CUMULATIVE. "10 or 25" is a disjunction, so reaching the
    10-stack tier grants 25 Adaptive Force TOTAL - the high tier REPLACES the
    low one. Summing the rows to 35 would over-credit the rune by 40%.

    UNITS: the feed's numbers are ADAPTIVE FORCE, the same as Conqueror's and
    unlike Gathering Storm's and Absolute Focus's explicitly-enumerated columns,
    so they convert at Riot's 1 AF = 1 AP or 0.6 AD. That is 6.0 AD / 10.0 AP at
    the low tier and 15.0 AD / 25.0 AP at the high one.

    The ability-haste half is deliberately NOT credited: Ability Haste as a DS
    axis was measured inert and is settled. See the module docstring.
    """
    try:
        count = float(stacks)
    except (TypeError, ValueError):
        return (0.0, 0.0)
    count = max(0.0, min(_JACK_MAX_STACKS, count))
    if count >= _JACK_HIGH_TIER_STACKS:
        adaptive_force = _JACK_AF_AT_HIGH_TIER
    elif count >= _JACK_LOW_TIER_STACKS:
        adaptive_force = _JACK_AF_AT_LOW_TIER
    else:
        return (0.0, 0.0)
    return (_ADAPTIVE_FORCE_AD_PER_AF * adaptive_force, adaptive_force)


@dataclass(frozen=True)
class RuneOffenseEntry:
    """One rune's offensive stat grant.

    ``grant`` resolves the ``(ad, ap, attack_speed_fraction)`` TRIPLE the rune
    would give. The first two columns are ADAPTIVE - the caller picks ONE of
    them by the adaptive rule (AD on ties). Holding both rather than a
    pre-resolved scalar is what lets the adaptive decision be made from the
    RESOLVED BUILD instead of being baked into the registry.

    The THIRD column is NOT adaptive and is never routed through that choice:
    attack speed has no sides, so it accumulates on every entry. An entry that
    grants no attack speed returns 0.0 there, and vice versa; nothing in the
    registry pays out on both an adaptive column and the AS column today.

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
        legend_stacks: Optional[float],
        jack_stacks: Optional[float],
    ) -> tuple[float, float, float]:
        fn = self._grant
        if fn is None:  # pragma: no cover - every seeded entry supplies one
            return (0.0, 0.0, 0.0)
        return fn(
            level=level,
            game_minute=game_minute,
            caster_hp_pct=caster_hp_pct,
            conqueror_stacks=conqueror_stacks,
            legend_stacks=legend_stacks,
            jack_stacks=jack_stacks,
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
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks,
        legend_stacks, jack_stacks: (
            gathering_storm_step(game_minute) + (0.0,)
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
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks,
        legend_stacks, jack_stacks: (
            absolute_focus_grant(level, caster_hp_pct) + (0.0,)
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
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks,
        legend_stacks, jack_stacks: (
            conqueror_grant(level, conqueror_stacks) + (0.0,)
        ),
    ),
    # 9104 Legend: Alacrity (Precision, slot 2) - verbatim: "Gain 3% attack speed
    # plus an additional 1.5% for every Legend stack (max 10 stacks). Earn
    # progress toward Legend stacks for every champion takedown, epic monster
    # takedown, large monster kill, and minion kill."
    #
    # THE ONLY NON-ADAPTIVE ENTRY, and the reason this registry grew a third
    # column. Its two adaptive columns are 0.0 and its whole payout is the AS
    # fraction, which the caller accumulates OUTSIDE the prefer_ad branch. An AD
    # build and an AP build receive the identical grant, which is what the feed
    # describes and what the adaptive branch would have destroyed.
    #
    # UNITS: a bonus-AS FRACTION (0.03 at 0 stacks, 0.18 at the cap), NOT final
    # attacks/sec. The consumer folds it as ``innate_base_as * fraction`` with
    # the 2.5 League hard-cap re-clamp, mirroring the R42 cond_as and R7
    # passive_as folds. Adding the raw fraction over-credits by 1 / base_as.
    #
    # STACK MODELLING: a KNOB (_ASSUMED_LEGEND_STACKS, default 10 = the feed's
    # cap, per-call override legend_stacks), NOT a hardcoded 10 - identical
    # doctrine to Conqueror's above, including the inverted conservatism by side
    # of the fight. The four stated progress sources carry no per-source value in
    # the feed, so no accrual model is derivable and the count stays an
    # assumption.
    #
    # AS-LOCK CHAMPIONS: the consumer gates this grant on
    # _passive_as_lock_overrides.as_lock_entry (engine.py:439) and grants ZERO to
    # a locked champion (Jhin). Deliberately conservative - the override table's
    # ad_per_bonus_as conversion is authored against ITEM attack speed and is not
    # applied to a rune. Stated, not guessed.
    "9104": RuneOffenseEntry(
        name="Legend: Alacrity",
        tree="Precision",
        gate="legend_stacks",
        family="legend_alacrity",
        note=(
            "Legend: Alacrity: 3% attack speed plus 1.5% per Legend stack at "
            "the assumed 10-stack cap = 0.18 bonus-AS fraction; NOT adaptive, "
            "so AD and AP builds receive it identically; zero for an "
            "attack-speed-locked champion"
        ),
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks,
        legend_stacks, jack_stacks: (
            (0.0, 0.0, legend_alacrity_grant(legend_stacks))
        ),
    ),
    # 8316 Jack Of All Trades (Inspiration, slot 2) - verbatim: "For each
    # different stat gained from items, gain one Jack stack. Each stack grants
    # you 1 Ability Haste. Gain 10 or 25 bonus Adaptive Force at 5 and 10
    # stacks, respectively."
    #
    # THE ONLY ENTRY WHOSE COUNT IS COMPUTED. Conqueror's and Alacrity's stack
    # counts are unobservable in-game counters and therefore knobs with stated
    # defaults; this one is a property of the build the caller already holds, so
    # jack_stacks is DERIVED (jack_of_all_trades_stacks over the resolved build's
    # item stat blocks) rather than assumed. jack_stacks=None means the caller
    # supplied no census, and the entry then contributes 0.0 - which is what
    # keeps every pre-R156 call site byte-identical.
    #
    # UNITS: the feed's "10 or 25 bonus Adaptive Force" is ADAPTIVE FORCE like
    # Conqueror's, not AD, so it converts at 1 AF = 1 AP or 0.6 AD -> 6.0 AD /
    # 10.0 AP at the low tier, 15.0 AD / 25.0 AP at the high one.
    #
    # STEP AND NOT CUMULATIVE: "at 5 and 10 stacks, respectively" is two
    # thresholds and "10 or 25" is a disjunction, so the high tier REPLACES the
    # low one and sub-5 pays nothing. Summing them would over-credit by 40%.
    #
    # The ability-haste half is EXCLUDED - Ability Haste as a DS axis was
    # measured inert and is settled - and the attack-speed column is 0.0: this
    # is an adaptive grant, so exactly one of its first two columns pays out.
    "8316": RuneOffenseEntry(
        name="Jack Of All Trades",
        tree="Inspiration",
        gate="distinct_item_stats",
        family="jack_of_all_trades",
        note=(
            "Jack Of All Trades: 10 Adaptive Force at 5 distinct item stats "
            "and 25 at 10 (the tiers replace, they do not sum), converted to "
            "6.0/15.0 AD or 10.0/25.0 AP; the stack count is censused from the "
            "resolved build, and the per-stack ability haste is excluded"
        ),
        _grant=lambda *, level, game_minute, caster_hp_pct, conqueror_stacks,
        legend_stacks, jack_stacks: (
            jack_of_all_trades_grant(jack_stacks) + (0.0,)
        ),
    ),
}


# THE EXCLUSIONS BLOCK ABOVE IS PROSE, AND PROSE CANNOT FAIL CI. That is the
# whole reason this mapping exists. Every rune below was read and rejected, and
# the docstring already says so in sentences - but a docstring cannot notice
# when a patch adds a THIRTEENTH Domination rune. An unlisted rune contributes
# 0.0 by construction (the registry is an allowlist), which is exactly what a
# deliberately-excluded rune contributes, so the two states are
# indistinguishable at runtime. The new rune would silently earn nothing
# forever and nothing in the repo would say a word.
#
# This mapping is the machine-readable half of the same claim. It carries no
# magnitudes and no behavior: nothing reads it except
# ``tests/test_rune_offense_saturation_r158.py``, which asserts that every rune
# id in ALL FIVE TREES in the live DDragon
# ``runesReforged.json`` feed is either in ``_RUNE_OFFENSE_GRANTS`` or here, that
# the two sets are disjoint, and - running the claim the other way - that every
# id here actually EXISTS in the feed. That last direction is not decoration:
# adjudicating a rune that has been REMOVED from the game (Eyeball Collection
# 8138, Ghost Poro 8120, Zombie Ward - all absent from 16.14.1) records a
# decision about something nobody can equip, and reads as coverage while
# providing none.
#
# Domination and Sorcery reasons are lifted from the DELIBERATE EXCLUSIONS block
# above rather than re-derived, so the two records cannot drift into disagreeing
# about why a rune was declined. The R159 rows (Precision 8000, Inspiration 8300,
# Resolve 8400) had no prose to lift from and were adjudicated straight off the
# 16.14.1 ``longDesc`` for each id, reusing the same vocabulary. SCOPE IS NOW THE
# WHOLE FEED: five trees, 62 runes, 5 registered and 57 recorded here.
#
# THREE ROWS ARE DELIBERATE GAPS, NOT NON-GRANTS, and say so in their own words
# (8232 Waterwalking river uptime, 8008 Lethal Tempo role-split attack speed,
# 8313 Triple Tonic's 60-second Elixir of Force). A saturation guard
# whose reasons quietly claimed "no offensive stat" for a rune that grants one
# would be worse than no guard: it would launder an unmodelled grant as a
# measured decision. Naming the blocker keeps the record honest and keeps each
# row a live candidate for the pass that gains the missing anchor.
_ADJUDICATED_NON_GRANTS: dict[str, str] = {
    # --- Domination 8100 (12 runes, none registered) ---
    "8112": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "8128": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "9923": (
        "burst-window attack-speed steroid (3 attacks on a 10s cooldown), already "
        "registered and scored at rune_procs.py:685 - adding it here would "
        "double-credit it"
    ),
    "8126": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "8139": "heal, not an offensive stat - grants no AD, AP or attack speed",
    "8143": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "8137": "vision, not an offensive stat - grants no AD, AP or attack speed",
    "8140": "trinket haste, not an offensive stat - grants no AD, AP or attack speed",
    "8141": "ward duration, not an offensive stat - grants no AD, AP or attack speed",
    "8135": "gold, not an offensive stat - grants no AD, AP or attack speed",
    "8105": "move speed only - no offensive stat on it",
    "8106": "ability haste only, and Ability Haste as a DS axis was MEASURED INERT",
    # --- Sorcery 8200 (13 runes; 8236 + 8233 are REGISTERED above) ---
    "8214": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "8229": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "8230": "move speed only - no offensive stat on it",
    "8992": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "8224": "ultimate damage amp, a multiplier lane not a stat",
    "8226": (
        "maximum mana, which is the _item_mana_health axis and not an offensive stat"
    ),
    "8275": "move speed only - no offensive stat on it",
    "8210": "ability haste only, and Ability Haste as a DS axis was MEASURED INERT",
    "8234": "move speed only - no offensive stat on it",
    "8237": "proc damage, registered in rune_procs.py and scored by the burst consumer",
    "8232": (
        "UPTIME-BLOCKED, not a non-grant: it does grant 13-30 Adaptive Force by "
        "level, but only while in the river, and river occupancy has no anchor "
        "anywhere in this engine - the best candidate for a future pass that "
        "gains a positional signal"
    ),
    # --- Precision 8000 (13 runes; 8010 + 9104 are REGISTERED above) ---
    "8005": (
        "bonus adaptive burst plus a flat 8% damage amp, both registered in "
        "rune_procs.py and scored by the burst consumer - the amp is a "
        "multiplier lane, not a stat"
    ),
    "8008": (
        "ROLE-BLOCKED, not a non-grant: it does grant stacking attack speed "
        "(6% melee / 4% ranged per stack, up to 6 stacks), but the value is "
        "role-split and this seam takes no melee-or-ranged argument, and the "
        "same bonus attack speed is already an INPUT to its on-attack damage "
        "term in rune_procs.py, so the two lanes would have to be wired "
        "together rather than credited independently"
    ),
    "8021": (
        "energized heal plus move speed - no AD, AP or attack speed, and "
        "deliberately excluded from rune_procs.py as well (it heals, it does "
        "not deal damage)"
    ),
    "9101": "heal on kill, not an offensive stat - grants no AD, AP or attack speed",
    "9111": (
        "takedown heal plus gold, not an offensive stat - grants no AD, AP or "
        "attack speed"
    ),
    "8009": (
        "mana or energy restore, which is the _item_mana_health axis and not an "
        "offensive stat"
    ),
    "9105": (
        "basic ability haste only (1.5 per Legend stack), and Ability Haste as "
        "a DS axis was MEASURED INERT"
    ),
    "9103": (
        "life steal (0.45% per Legend stack) plus 85 max health at full stacks "
        "- sustain and health, neither is AD, AP or attack speed"
    ),
    "8014": (
        "conditional damage amp (8% against targets below 40% health), a "
        "multiplier lane not a stat, and already registered in rune_procs.py "
        "with its target-health gate"
    ),
    "8017": (
        "conditional damage amp (8% against targets above 60% health), a "
        "multiplier lane not a stat, and already registered in rune_procs.py "
        "with its target-health gate"
    ),
    "8299": (
        "conditional damage amp (5-11% while below 60% of your own health), a "
        "multiplier lane not a stat, and already registered in rune_procs.py "
        "with its caster-health gate"
    ),
    # --- Inspiration 8300 (12 runes; 8316 is REGISTERED above) ---
    "8351": (
        "slow plus a damage-reduction zone applied to enemies - crowd control "
        "and an enemy-side multiplier lane, not an AD, AP or attack speed grant"
    ),
    "8360": (
        "swaps a Summoner Spell, not an offensive stat - grants no AD, AP or "
        "attack speed"
    ),
    "8369": (
        "gold plus a 7% damage amp, registered in rune_procs.py and scored as a "
        "multiplier lane, not a stat"
    ),
    "8306": (
        "replaces Flash with a Hexflash blink - mobility, not an offensive stat"
    ),
    "8304": (
        "free boots at 12 min plus 10 move speed - move speed only, no "
        "offensive stat on it"
    ),
    "8321": (
        "gold back on Legendary purchases, not an offensive stat - grants no "
        "AD, AP or attack speed"
    ),
    "8313": (
        "UPTIME-BLOCKED, not a non-grant: the level-6 Elixir of Force it hands "
        "out grants 25 Adaptive Force, but for 60 seconds once, and this engine "
        "has no consumable-uptime anchor to spend that against; its two "
        "siblings grant nothing offensive (Elixir of Avarice is gold plus "
        "minion-only true damage, Elixir of Skill is a skill point)"
    ),
    "8352": (
        "front-loads potion healing (40% of the restoration immediately), not "
        "an offensive stat"
    ),
    "8345": (
        "biscuit healing plus 30 permanent max health per biscuit - heal and "
        "health, neither is AD, AP or attack speed"
    ),
    "8347": (
        "18 Summoner Spell Haste and 10 Item Haste only - a cooldown lane, and "
        "haste as a DS axis was MEASURED INERT"
    ),
    "8410": "move speed only - no offensive stat on it",
    # --- Resolve 8400 (12 runes, none registered) ---
    "8437": (
        "proc magic damage off max health, registered in rune_procs.py and "
        "scored by the burst consumer; its heal and permanent 5 health per proc "
        "are sustain, not AD, AP or attack speed"
    ),
    "8439": (
        "armor and magic resist, registered in _rune_resist_grants.py, and its "
        "explosion damage is registered in rune_procs.py - neither half is an "
        "AD, AP or attack speed grant"
    ),
    "8465": "ally shield, not an offensive stat - grants no AD, AP or attack speed",
    "8446": (
        "bonus physical damage against TOWERS only, deliberately excluded from "
        "rune_procs.py for the same reason - it never touches a champion damage "
        "lane, let alone a stat"
    ),
    "8463": (
        "heal on self and the lowest-health nearby ally, not an offensive stat"
    ),
    "8401": (
        "bonus adaptive damage on the next attack after gaining a shield, "
        "registered in rune_procs.py and scored by the burst consumer"
    ),
    "8429": (
        "flat plus percentage armor and magic resist, registered in "
        "_rune_resist_grants.py - resists, not an offensive stat"
    ),
    "8444": "heal over time off missing health, not an offensive stat",
    "8473": (
        "flat damage reduction on the next 3 hits taken, a mitigation lane not "
        "a stat"
    ),
    "8451": (
        "permanent maximum health only - health is not one of this registry's "
        "three columns (AD, AP, attack speed)"
    ),
    "8453": (
        "5% Heal and Shield Power plus a low-health heal and shield amp - a "
        "healing lane, not AD, AP or attack speed"
    ),
    "8242": (
        "10 armor and magic resist while crowd controlled, registered in "
        "_rune_resist_grants.py - resists, not an offensive stat"
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
    legend_stacks: Optional[float] = None,
    # R156: appended at the END per the no-mid-signature-insert convention, and
    # defaulting to None so a caller that supplies no census gets no Jack grant
    # and stays byte-identical.
    jack_stacks: Optional[float] = None,
) -> tuple[float, float, float]:
    """Return the ``(bonus_ad, bonus_ap, bonus_as_fraction)`` rune-side grant.

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
    ``legend_stacks`` is the same shape for Legend: Alacrity, defaulting to
    ``_ASSUMED_LEGEND_STACKS`` and clamped to the feed's 0..10 range.

    ``jack_stacks`` is NOT that shape. Jack Of All Trades's count is censused
    from the caller's own resolved build (``jack_of_all_trades_stacks``), so
    there is no defensible assumed default: None means "no census supplied" and
    the entry then contributes 0.0, which is what keeps every pre-R156 caller
    byte-identical. A supplied value is clamped to 0..``_JACK_MAX_STACKS``.

    Per entry: the ``(ad, ap, as_frac)`` triple is resolved. ONE of the first two
    is taken by the standard adaptive rule (AD when ``bonus_ad >= ap``, matching
    ``rune_procs._adaptive_coeff``) and accumulated onto the matching return
    slot. The THIRD column bypasses that choice entirely and always accumulates:
    attack speed is not adaptive, so routing it through ``prefer_ad`` would drop
    the grant for whichever side lost. A ``family`` tag is credited at most once,
    so a duplicated or aliased id cannot double-credit on ANY column; different
    families sum.

    Runes not in the registry contribute 0 - the registry is a seeded allowlist,
    so every proc-damage keystone, every move-speed rune and every ability-haste
    rune returns 0.0 by construction. The AD / AP values are added to
    ``bonus_ad`` and ``ap`` inside ``compute_dps``; the AS FRACTION is folded
    there as ``innate_base_as * fraction`` onto the rotation AS (never added
    raw), gated on the champion not being attack-speed-locked. The default-OFF
    gating lives in ``compute_dps`` (this function is only called when
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
    # None stays None so the Jack entry can tell "no census supplied" (contribute
    # nothing) apart from "censused zero"; both pay 0.0, but only the clamp is
    # this function's business.
    if jack_stacks is not None:
        try:
            jack_stacks = max(0.0, min(_JACK_MAX_STACKS, float(jack_stacks)))
        except (TypeError, ValueError):
            jack_stacks = None

    grant_ad = 0.0
    grant_ap = 0.0
    grant_as = 0.0
    seen_families: set[str] = set()
    for rid in rune_ids:
        entry = _RUNE_OFFENSE_GRANTS.get(str(rid))
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        if entry.family:
            seen_families.add(entry.family)
        side_ad, side_ap, side_as = entry.grant(
            level=level,
            game_minute=minute,
            caster_hp_pct=caster_hp_pct,
            conqueror_stacks=conqueror_stacks,
            legend_stacks=legend_stacks,
            jack_stacks=jack_stacks,
        )
        if prefer_ad:
            grant_ad += side_ad
        else:
            grant_ap += side_ap
        # NOT inside the prefer_ad branch: attack speed is not adaptive, so an
        # AD build and an AP build must both receive it in full.
        grant_as += side_as
    return (grant_ad, grant_ap, grant_as)
