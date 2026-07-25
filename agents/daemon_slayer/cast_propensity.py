"""RM-98 - cast-rate propensity prior (DEFAULT-OFF seam).

Implements the ADJUDICATED recommendation of
``docs/specs/SPEC_rm98_cast_rate_time_base.md:135-147``.

THE PROBLEM (adjudicated, not re-opened here)
---------------------------------------------
``data/daemon_slayer/spell_cast_rates.json`` is a WHOLE-GAME rate:
``participants.spell[1-4]_casts / matches.game_duration_s``. Every consumer
multiplies it into a per-second COMBAT term (``ability_dps.py:1261``
``dps = post_mit * measured``), which is a units error - a whole-game
denominator divided into a combat-window numerator. The spec sized the
characteristic distortion at ~7x per spell (SPEC:100-107) and proved the
term is NOT inert (SPEC:91-99).

WHY NOT FIX THE DENOMINATOR
---------------------------
Both replacement denominators RM-39 named are MEASURED INFEASIBLE
(SPEC:116-133) and must not be re-attempted:

* "casts per second alive" is directly computable from
  ``participants.time_spent_dead`` and lifts Renekton W by only 1.25x
  against a 27x gap. INADEQUATE.
* "casts per second within N seconds of combat" needs sub-minute frame
  cadence; ``timeline_frames`` measures 60016-60021 ms between frames, so a
  3-10s combat window is not resolvable. NOT AVAILABLE.

A correction factor layered on the old rate is explicitly ruled out by
``SPEC_rm39_rm43_ability_haste.md:174-176``.

THE FIX - DEMOTION, NOT REPLACEMENT
-----------------------------------
Demote the measured rate from a DPS MULTIPLIER to a dimensionless
CAST-PROPENSITY PRIOR, and rebuild the per-second term on the
cooldown-inverse availability rate - which is already in the right units -
modulated by that prior::

    availability   = 1 / cooldown                     (casts/sec, combat basis)
    propensity     = measured / availability          (dimensionless)
    prior          = min(1.0, propensity / REFERENCE) (fraction of availability)
    combat_rate    = availability * prior

The prior needs correct RELATIVE ordering across spells and champions -
which the whole-game basis DOES preserve - and does not need a correct
denominator.

WHY THIS IS BASIS-FREE, AND WHY THAT IS THE WHOLE POINT
-------------------------------------------------------
The whole-game basis distorts every measured rate by the SAME unknown
factor ``f`` (the fraction of game time that is combat time):
``measured_i = true_combat_rate_i * f``. So ``propensity_i`` carries that
same ``f``, and dividing by a REFERENCE propensity calibrated from the same
table cancels it EXACTLY. Re-generate ``spell_cast_rates.json`` on any other
denominator, re-calibrate ``FULL_AVAILABILITY_PROPENSITY`` from the new
table, and this module returns the identical numbers. That invariance is
what makes this a prior rather than the correction factor RM-39 forbade:
the output does not depend on the denominator at all, only on the
cross-spell ordering the denominator leaves intact.

CALIBRATING THE REFERENCE
-------------------------
``FULL_AVAILABILITY_PROPENSITY`` is the propensity of a spell that IS cast
as often as it is available in combat - the point where the prior saturates
at 1.0. It must be the UPPER edge of the honest propensity distribution,
not its middle: a median reference would hand half the roster a prior above
full availability, which is incoherent.

Measured 2026-07-24 over the live 16.14.1 snapshot: 676 per-spell rows with
``casts_per_sec_source == "measured"``, all 173 champions, level 13, SR,
empty build (the propensity is build-independent - both halves of the ratio
are, at a fixed level). Distribution::

    min 0.0024  p10 0.167  p25 0.252  med 0.378  p75 0.527
    p90 0.719   p95 0.894  p99 2.325  max 10.976  mean 0.459

p90 = 0.7191 is the reference. 70 of 676 rows (10.4 pct) clamp.

THE ABOVE-1.0 TAIL IS A COOLDOWN-MODEL ARTIFACT, AND IT NEEDS A FLOOR
---------------------------------------------------------------------
24 of 676 rows (3.6 pct) measure a propensity above 1.0 - Ivern R 10.98,
Shaco R 5.56, Zyra W 3.63, Riven Q 2.59. These are spells the
``1 / cooldown`` availability model UNDERCOUNTS: multi-cast and pet/recast
kits fire more ``spell[N]_casts`` events than one cooldown permits (Riven Q
Broken Wings is three casts per 13s cooldown; Ivern R Daisy issues repeated
commands). For them ``availability * prior`` lands BELOW the measured rate,
so the transform would be a CUT - measured Riven Q 0.19941 vs a rebased
0.07692, which is a 2.6x reduction of the term Riven is 65.9 pct dependent on
(SPEC:91-99). That would be a regression, not a repair.

The floor that fixes it is not a fudge, it is a proof. Combat time is a
subset of game time, so for any spell::

    true_combat_rate = casts / combat_time >= casts / game_time = measured

The measured whole-game rate is a STRICT LOWER BOUND on the combat-window
rate. ``combat_basis_casts_per_sec`` therefore returns
``max(measured, availability * prior)``, and the floor binds on exactly the
propensity-above-1.0 rows - the algebra: with a reference below 1.0, the floor
can only bind when ``propensity > 1``. Those rows come out unchanged, which is
the correct conservative answer for a spell whose availability the engine
cannot model. It is also a free diagnostic: a propensity above 1.0 is a
machine-detectable flag that a spell's cooldown does not describe its real
cast cadence.

A direct consequence, and the seam's directional contract: the transform
never lowers a row. Flag ON is a monotone non-decreasing move on every
ability term it touches.

WHAT THE PRIOR PROTECTS (RM-39's must-not-discard signal, SPEC:144-147)
----------------------------------------------------------------------
A pure cooldown-inverse model hands EVERY spell a prior of 1.0 and asserts
every champion casts everything the instant it comes up. Measured Aatrox at
level 13: Q propensity 0.6065 (prior 0.843), W 0.2556 (prior 0.355), E
0.5657 (prior 0.787), R 0.4975 (prior 0.692). Infernal Chains really is cast
less than half as readily as Darkin Blade, and the prior keeps that ordering
verbatim from the measured table while fixing the units.

SCOPE
-----
This module is pure math. RM-98 as filed is UNDER-SCOPED (SPEC:109-114); the
only consumer wired at first landing is ``hybrid.py`` behind
``apply_cast_rate_propensity_prior`` (DEFAULT-OFF). The remaining consumers
named by the spec are deliberately NOT wired - see the docstring on
``propensity_adjusted_dps_delta``.
"""
from __future__ import annotations

from typing import Iterable, Optional

# See "CALIBRATING THE REFERENCE" above. p90 of the roster-wide measured
# propensity distribution (676 rows, 16.14.1, level 13, SR). Re-derive this
# whenever ``spell_cast_rates.json`` is regenerated on a new patch OR on a new
# denominator; the module output is invariant to the denominator ONLY if the
# reference is recalibrated from the same table.
FULL_AVAILABILITY_PROPENSITY = 0.7191

# The row-level filter ``ability_dps`` uses for a missing damage_type
# (``ability_dps.py:1220`` - ``(damage_type or "MAGIC").upper()``). Mirrored
# here verbatim so a None damage_type sorts the same way on both paths.
_DEFAULT_DAMAGE_TYPE = "MAGIC"

# Only rows the engine sourced from the measured whole-game table are re-based.
# A row whose ``casts_per_sec_source`` is the ``1 / cooldown * mana_uptime``
# fallback is ALREADY on a combat basis; re-basing it would double-apply the
# transform. This is also the half-fix SPEC:109-112 describes for the six
# champions (Aphelios, Katarina, Kled, Teemo, Vayne, Vi) that sum a
# combat-basis fallback and a whole-game measured rate in the same total.
_MEASURED_SOURCE = "measured"


def theoretical_casts_per_sec(cooldown: float) -> float:
    """Cooldown-inverse availability in casts/sec. 0.0 for a degenerate cd."""
    cd = float(cooldown or 0.0)
    return (1.0 / cd) if cd > 0.0 else 0.0


def cast_propensity(cooldown: float, measured_casts_per_sec: float) -> float:
    """Dimensionless measured-over-available ratio.

    Carries the whole-game basis distortion as a common factor; see the module
    docstring for why that cancels downstream. Returns 0.0 when availability is
    undefined (cooldown <= 0), which is the no-signal answer, not a zero rate.
    """
    availability = theoretical_casts_per_sec(cooldown)
    if availability <= 0.0:
        return 0.0
    return float(measured_casts_per_sec or 0.0) / availability


def cast_propensity_prior(
    cooldown: float,
    measured_casts_per_sec: float,
    reference: Optional[float] = None,
) -> float:
    """Fraction of availability the champion actually realises, in [0, 1].

    ``reference`` defaults to ``FULL_AVAILABILITY_PROPENSITY``. Clamped at 1.0
    because a prior is a fraction of availability - see the module docstring on
    the above-1.0 cooldown-model artifact tail.
    """
    ref = FULL_AVAILABILITY_PROPENSITY if reference is None else float(reference)
    if ref <= 0.0:
        return 0.0
    prop = cast_propensity(cooldown, measured_casts_per_sec)
    if prop <= 0.0:
        return 0.0
    return min(1.0, prop / ref)


def combat_basis_casts_per_sec(
    cooldown: float,
    measured_casts_per_sec: float,
    reference: Optional[float] = None,
) -> float:
    """Combat-window casts/sec: availability modulated by the propensity prior,
    floored at the measured rate.

    The floor is the lower-bound proof in the module docstring: combat time is
    a subset of game time, so the whole-game measured rate can never exceed the
    true combat rate. It binds only on the propensity-above-1.0 rows whose
    ``1 / cooldown`` availability is undercounted (multi-cast / pet kits).

    Falls back to the measured value verbatim when availability is undefined
    (cooldown <= 0) - there is no prior to apply, and silently zeroing the row
    would be a worse answer than the status quo.
    """
    measured = float(measured_casts_per_sec or 0.0)
    availability = theoretical_casts_per_sec(cooldown)
    if availability <= 0.0:
        return measured
    rebased = availability * cast_propensity_prior(cooldown, measured, reference)
    return max(measured, rebased)


def propensity_adjusted_dps_delta(
    per_spell: Iterable,
    credited_damage_types: Optional[frozenset] = None,
    reference: Optional[float] = None,
) -> float:
    """Sum of per-row DPS deltas from re-basing measured rows onto the prior.

    Returns ``sum(post_mit * (combat_rate - measured))`` over eligible rows, so
    a caller adds it to whatever ability total it already holds. Expressing the
    seam as a DELTA rather than a recomputed total is deliberate: it leaves
    every other layer of ``total_ability_dps`` - the ability-amp multiplier and
    the always-on ``item_proc_dps`` fold - untouched and un-double-counted.

    ``per_spell`` is a sequence of ``ability_dps.AbilitySpellDps`` rows. Each
    row already carries everything needed: ``post_mitigation_damage_per_cast``,
    ``casts_per_sec``, ``casts_per_sec_source`` and ``cooldown``. The
    reconstruction is exact - ``ability_dps.py:1261`` sets
    ``dps = post_mit * casts_per_sec``.

    ``credited_damage_types`` mirrors the RM-39 AD-axis filter in
    ``hybrid._physical_ability_damage``; None credits every row. The None
    damage_type falls back to MAGIC exactly as ``ability_dps.py:1220`` does.

    NOT WIRED (SPEC:109-114, deliberate - narrow first, widen on evidence):
    ``ability_dps.py:1252`` itself, the ``item_proc_dps`` fold inside
    ``total_ability_dps``, ``dps.py:1023`` (Malignance ult rate),
    ``hps.py:679`` and ``onhit_dps.py:143``. Each is its own consumer with its
    own default-flip decision; this landing wires ``hybrid.py`` only.
    """
    total = 0.0
    for row in per_spell or ():
        if getattr(row, "casts_per_sec_source", "") != _MEASURED_SOURCE:
            continue
        if credited_damage_types is not None:
            dt = (getattr(row, "damage_type", None) or _DEFAULT_DAMAGE_TYPE).upper()
            if dt not in credited_damage_types:
                continue
        measured = float(getattr(row, "casts_per_sec", 0.0) or 0.0)
        if measured <= 0.0:
            continue
        cooldown = float(getattr(row, "cooldown", 0.0) or 0.0)
        rebased = combat_basis_casts_per_sec(cooldown, measured, reference)
        if rebased == measured:
            continue
        post_mit = float(getattr(row, "post_mitigation_damage_per_cast", 0.0) or 0.0)
        total += post_mit * (rebased - measured)
    return total
