"""2026-07-27 (R212) - per-champion CRIT CHANCE / CRIT DAMAGE MULTIPLIER registry.

``dps.py`` resolves every champion's basic attack as::

    ad * (1 + crit * crit_bonus)
    crit_bonus = DEFAULT_CRIT_BONUS (0.75) + total_crit_damage_bonus(items)

The sibling RM-46 registry (``_crit_conversion_overrides``, Ashe) overrides ONLY
the crit-DAMAGE-BONUS axis, and only additively / by replacement. Three axes had
no seam anywhere in the engine before this module:

  1. **a crit-CHANCE multiplier.** Yasuo and Yone double their total critical
     strike chance from all other sources. The engine hands them the raw item
     sum, so a 25 pct crit item pays them 25 pct where the game pays 50 pct - a
     flat halving of the entire crit axis for two champions.
  2. **the >100 pct crit-chance OVERFLOW conversion.** Crit chance hard-caps at
     100 pct in League, and three champions convert the discarded excess into
     something else: Yasuo / Yone into 0.5 bonus attack damage per excess
     percentage point, Senna into 0.35 pct life steal per excess point. Without
     this, the doubling above would silently throw the excess away - which is
     WORSE than not modelling the doubling at all, because the engine would
     credit a crit item that the game converts into AD as if it did nothing.
  3. **a crit-damage MULTIPLIER on the whole ``(1 + crit_bonus)`` product.**
     Jhin's Whisper penalty is 0.86 applied to base-plus-bonuses, NOT an
     additive term on the bonus alone. His notes state the order of operations
     verbatim and explicitly reject the additive reading (see GROUND TRUTH).
     The engine has no multiplicative crit-damage axis at all - grep 0.86 across
     ``agents/daemon_slayer/*.py`` returns nothing outside this module.

CONSUMER: ``dps.compute_dps(apply_crit_chance_overrides=True)`` - DEFAULT-OFF.
With the flag omitted (the default) NOTHING in this module is imported or read
and every champion, the four registered ones included, is byte-identical to the
pre-seam engine. The live default-ON flip stays validation-gated
(do-not-flip-blind), same posture as the sibling ``apply_crit_conversion`` /
``apply_melee_aa_gate`` / ``assume_passive_as_stacks`` seams.

WHY AN EXPLICIT DICT, not a parsed rule: the numbers live in free-text DDragon /
Meraki innate prose that is rewritten most patches, and no structured field
encodes "this champion's crit chance is doubled". A text rule would mis-key
every champion whose passive merely MENTIONS crit - Ashe's crit-to-damage
conversion (``_crit_conversion_overrides``), Jhin's attack-speed lock
(``_passive_as_lock_overrides``), Senna's crit-to-range growth - each a
DIFFERENT mechanic with its own registry. Entries here are hand-authored from
the verbatim cited fragment, one champion at a time, and
``tests/test_crit_chance_overrides_r212.py`` re-reads those fragments off disk
as a drift guard.

OUT-OF-SCOPE, deliberately: **Jhin's own bonus-AD-from-crit-chance ratio.**
"Every Moment Matters" grants him bonus AD "(+ 0.35% per 1% critical strike
chance)" of BASE AD. That is an AD-SCALING term, not a crit-RESOLUTION term: it
changes how much damage an attack starts from, not the probability of a critical
strike nor the multiplier a critical strike applies. It is already modelled by
``_passive_as_lock_overrides.AsLockEntry.ad_per_crit`` (0.35), and duplicating
it here would double-credit him. Only the 0.86 crit-damage PENALTY belongs to
this registry.

Also out of scope: Senna's "+10% critical strike chance per 20 Mist stacks" and
"+20 bonus attack range" - stack-count-conditional GRANTS, not a resolution
rule; this registry answers "given a resolved crit chance, what does the game
actually do with it".

GROUND TRUTH: ``data/daemon_slayer/16.14.1/champion_abilities.json`` -> data ->
<Champion> -> P (patch 16.14.1), verbatim:

  Yasuo "Way of the Wanderer" effects_descriptions[0]:
    "Innate - Intent: Yasuo's total critical strike chance is doubled from all
     other sources. Additionally,[ every 1% critical strike chance in excess of
     100% is converted into 0.5 bonus attack damage. ]"
  Yone "Way of the Hunter" effects_descriptions[0]:
    the identical mechanic, "Yone's total critical strike chance is doubled from
     all other sources. Additionally,[ every 1% critical strike chance in excess
     of 100% is converted into 0.5 bonus attack damage. ]"
  Senna "Absolution" effects_descriptions[2]:
    "Mist: For each stack of Mist, Senna gains 0.75 bonus attack damage. For
     every 20 stacks, she also gains 20 bonus attack range and 10% critical
     strike chance. Additionally, every 1% critical strike chance in excess of
     100% is converted into 0.35% life steal."
  Jhin "Whisper" notes (U+00D7 MULTIPLICATION SIGN written as ``x`` here to keep
  this file 7-bit ASCII; the test asserts the real glyph off disk):
    "The penalty to Jhin's critical damage also reduces the base damage
     ((100 + 75) x 0.86 rather than 100 + (75 x 0.86)) and stacks with other
     sources (i.e Infinity Edge) ((100 + 75 + 40) x 0.86)."

The Jhin fragment is the whole reason ``crit_damage_multiplier`` multiplies
``(1.0 + crit_bonus)`` instead of ``crit_bonus``: at crit 1.0 the auto-attack
term must read 1.75 x 0.86 = 1.505, and with a +0.40 crit-damage source
2.15 x 0.86 = 1.849. (The note's "40" is a historical Infinity Edge value; the
SHIPPED IE in ``_effects_data.py:33`` carries crit_damage_bonus=0.30. The
identity being pinned is the ORDER OF OPERATIONS, not IE's current number.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# "total critical strike chance is doubled from all other sources" - Yasuo /
# Yone. Named so the tests can pin the literal without re-deriving it.
_YASUO_YONE_CRIT_CHANCE_MULTIPLIER = 2.0
# "every 1% critical strike chance in excess of 100% is converted into 0.5 bonus
# attack damage" - flat AD per EXCESS PERCENTAGE POINT.
_YASUO_YONE_OVERFLOW_AD_PER_PCT = 0.5
# "every 1% critical strike chance in excess of 100% is converted into 0.35%
# life steal" - PERCENT of life steal per excess percentage point.
_SENNA_OVERFLOW_LIFESTEAL_PER_PCT = 0.35
# Jhin's Whisper crit-damage penalty, applied to the WHOLE (1 + crit_bonus).
_JHIN_CRIT_DAMAGE_MULTIPLIER = 0.86

# Critical strike chance hard-caps at 100 pct in League. Jhin's notes cite the
# cap verbatim ("35% from critical strike chance on account of the 100% cap"),
# and the cap is precisely what makes the overflow axis exist at all.
_CRIT_CHANCE_CAP = 1.0


@dataclass(frozen=True)
class CritChanceEntry:
    """One champion's crit CHANCE / crit DAMAGE MULTIPLIER override.

    champion_id: canonical DDragon id, must equal this row's dict key.
    note: hand-authored provenance sentence, surfaced in the DPS result notes.
    crit_chance_multiplier: multiplies the champion's resolved crit chance
      BEFORE the 100 pct cap (Yasuo / Yone 2.0). 1.0 is the identity.
    crit_damage_multiplier: multiplies the WHOLE ``(1.0 + crit_bonus)`` product,
      not ``crit_bonus`` alone (Jhin 0.86). 1.0 is the identity. See the module
      GROUND TRUTH block for why the distinction is load-bearing.
    overflow_ad_per_pct: flat bonus attack damage granted per PERCENTAGE POINT
      of multiplied crit chance above 100 pct (Yasuo / Yone 0.5).
    overflow_lifesteal_per_pct: life steal, in PERCENT, granted per PERCENTAGE
      POINT of multiplied crit chance above 100 pct (Senna 0.35).
    """

    champion_id: str
    note: str
    crit_chance_multiplier: float = 1.0
    crit_damage_multiplier: float = 1.0
    overflow_ad_per_pct: float = 0.0
    overflow_lifesteal_per_pct: float = 0.0


_CRIT_CHANCE: dict[str, CritChanceEntry] = {
    "Yasuo": CritChanceEntry(
        champion_id="Yasuo",
        crit_chance_multiplier=_YASUO_YONE_CRIT_CHANCE_MULTIPLIER,
        overflow_ad_per_pct=_YASUO_YONE_OVERFLOW_AD_PER_PCT,
        note=(
            "Way of the Wanderer (P): total critical strike chance is doubled "
            "from all other sources; every 1% of critical strike chance in "
            "excess of 100% converts into 0.5 bonus attack damage."
        ),
    ),
    "Yone": CritChanceEntry(
        champion_id="Yone",
        crit_chance_multiplier=_YASUO_YONE_CRIT_CHANCE_MULTIPLIER,
        overflow_ad_per_pct=_YASUO_YONE_OVERFLOW_AD_PER_PCT,
        note=(
            "Way of the Hunter (P): total critical strike chance is doubled "
            "from all other sources; every 1% of critical strike chance in "
            "excess of 100% converts into 0.5 bonus attack damage."
        ),
    ),
    "Senna": CritChanceEntry(
        champion_id="Senna",
        overflow_lifesteal_per_pct=_SENNA_OVERFLOW_LIFESTEAL_PER_PCT,
        note=(
            "Absolution (P) Mist: every 1% of critical strike chance in excess "
            "of 100% converts into 0.35% life steal. Her crit chance itself is "
            "unmodified - only the overflow is special."
        ),
    ),
    "Jhin": CritChanceEntry(
        champion_id="Jhin",
        crit_damage_multiplier=_JHIN_CRIT_DAMAGE_MULTIPLIER,
        note=(
            "Whisper (P): the critical damage penalty multiplies the WHOLE "
            "critical strike product ((100 + 75) x 0.86, and (100 + 75 + 40) x "
            "0.86 with a crit-damage item), not the bonus alone. His "
            "crit-chance-to-bonus-AD ratio is Every Moment Matters and lives "
            "in _passive_as_lock_overrides, not here."
        ),
    ),
}


def crit_chance_entry(champion_id: str) -> Optional[CritChanceEntry]:
    """Return the champion's crit-chance entry, or None when unregistered.

    None is the overwhelmingly common answer (169 of 173 champions), and every
    consumer must treat it as "use the universal crit model unchanged".
    """
    return _CRIT_CHANCE.get(champion_id)


def resolve_crit(
    champion_id: str, crit_chance: float, crit_bonus: float
) -> tuple[float, float, Optional[CritChanceEntry]]:
    """Resolve the auto-attack crit CHANCE + crit BONUS pair for a champion.

    ``crit_chance`` is the caller's already-resolved crit chance (stats plus any
    item-effect contribution) and ``crit_bonus`` the universal
    ``DEFAULT_CRIT_BONUS + total_crit_damage_bonus(items)``. Returns
    ``(effective_crit_chance, effective_crit_bonus, entry)``.

    An unregistered champion gets both inputs back UNCHANGED with a None entry,
    so the caller's default path is a single dict lookup and stays bit-for-bit
    identical.

    The effective bonus is ``(1.0 + crit_bonus) * crit_damage_multiplier - 1.0``
    so that the caller's existing ``1 + crit * crit_bonus`` term reproduces the
    verbatim Jhin arithmetic without the caller learning a new shape.

    The chance is capped at 100 pct AFTER the multiply. The excess is NOT lost -
    ``overflow_bonus_ad`` / ``overflow_lifesteal_pct`` are what the caller reads
    to credit it, and they take the RAW (pre-multiply) chance for exactly that
    reason.
    """
    entry = _CRIT_CHANCE.get(champion_id)
    if entry is None:
        return crit_chance, crit_bonus, None
    effective_chance = min(
        _CRIT_CHANCE_CAP, crit_chance * entry.crit_chance_multiplier
    )
    effective_bonus = (1.0 + crit_bonus) * entry.crit_damage_multiplier - 1.0
    return effective_chance, effective_bonus, entry


def _excess_pct_points(
    entry: Optional[CritChanceEntry], crit_chance: float
) -> float:
    """Multiplied crit chance above 100 pct, in PERCENTAGE POINTS.

    ``crit_chance`` is the RAW (pre-multiply) chance - the same value handed to
    ``resolve_crit`` - because the doubling is what CREATES the excess for
    Yasuo / Yone. Returns 0.0 for a None entry or when nothing overflows.
    """
    if entry is None:
        return 0.0
    multiplied = crit_chance * entry.crit_chance_multiplier
    return max(0.0, multiplied - _CRIT_CHANCE_CAP) * 100.0


def overflow_bonus_ad(
    entry: Optional[CritChanceEntry], crit_chance: float
) -> float:
    """Flat bonus ATTACK DAMAGE converted from excess crit chance.

    Unit: raw attack damage. Yasuo at raw crit 0.60 doubles to 1.20, overflows
    by 20 percentage points, and converts to 20 * 0.5 = 10.0 bonus AD.
    """
    return _excess_pct_points(entry, crit_chance) * entry.overflow_ad_per_pct if entry else 0.0


def overflow_lifesteal_pct(
    entry: Optional[CritChanceEntry], crit_chance: float
) -> float:
    """Life steal converted from excess crit chance.

    Unit: PERCENT (return 14.0 for "14% life steal", not 0.14). Senna at raw
    crit 1.40 overflows by 40 percentage points -> 40 * 0.35 = 14.0 percent.

    NO ENGINE CONSUMER TODAY, deliberately (WHY): ``compute_dps`` models neither
    life steal nor sustain, so there is no honest place to spend this number and
    inventing one would fabricate DPS. It is exposed here (and pinned by tests)
    so the ground truth is captured once, at the same time as its two sibling
    axes, instead of being re-derived when a sustain scorer eventually lands.
    Note also that ``dps.py`` clamps resolved crit chance at 1.0 before this
    registry ever sees it, so with Senna's identity chance multiplier her
    overflow is structurally 0 on the shipped engine - her row is the ground
    truth record, not a live term.
    """
    return (
        _excess_pct_points(entry, crit_chance) * entry.overflow_lifesteal_per_pct
        if entry
        else 0.0
    )
