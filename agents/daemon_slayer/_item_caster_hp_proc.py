"""RM-91 T2: ITEM caster-HP -> DAMAGE proc credit, DERIVED (DEFAULT-OFF).

WHY THIS MODULE EXISTS - AND WHY T1 WAS NOT ENOUGH
--------------------------------------------------
RM-91 T1 (``_health_damage_coupling``, ENGINE 1.258.0) credits the CHAMPION's
kit for re-spending the health an item grants: Shen E pays 11 percent of his
bonus health back as physical damage, so a health item is worth more to him than
the EHP denominator says. That credit is a factor MONOTONE in the candidate's
health delta, which means it can lift health items above resist items and
nothing else. It provably cannot reorder two health items - a 600-HP item can
never overtake a 1000-HP one.

The row's actual headline was never health-vs-resist. ``Randuin's Omen`` 3143 is
engine #1 on ``/rank-tank`` for Shen, Sejuani, Skarner, Zac and Tahm Kench while
appearing in the real core build of NONE of them, and it holds that slot because
it is a genuinely enormous raw-EHP purchase. T1 cannot touch that.

T2 is the half that can, because it prices a DIFFERENT payment: the ITEM's OWN
caster-HP-scaling proc. Titanic Hydra's Cleave deals 1 percent of the wielder's
maximum health on every basic attack. Heartsteel's Colossal Consumption deals 6
percent. Unending Despair's Anguish deals 3 percent of bonus health every 4
seconds. ``ehp.py`` imports no abilities module and reads zero damage, so none of
it is priced anywhere on the tank route. Randuin's Omen has no such proc at all,
which is exactly why crediting one stops it from dominating: the credit is keyed
by ITEM ID and is INDEPENDENT of how much health the candidate grants.

T1 AND T2 DO NOT DOUBLE-COUNT
-----------------------------
They credit different payers out of different pools. T1: the champion's KIT
re-spends the health DELTA the candidate adds. T2: the candidate ITEM re-spends
the caster's EXISTING pool. Shen's E and Titanic Hydra's Cleave are two separate
real payments, so both levers may be armed together - and they ride separate
flags for the same reason the RM-87 resist lever does, so that arming one never
silently arms the other.

DERIVED, NOT HAND-AUTHORED - the deliberate departure from T1
------------------------------------------------------------
T1 is a hand-seeded champion table because ``champion_abilities.json`` needs
human adjudication: most kits emit sub-component AND Total blocks for one
ability, and a naive sum triple-counts. T2 has no such problem, because the
coefficient already lives in ``_effects_data.py`` as EXECUTABLE code. So this
module DIFFERENTIATES each ``PeriodicProc`` against its own ``CallContext``
rather than restating a number:

    max_hp_pct = 100 * d(proc damage) / d(caster_max_hp)

Three things fall out of that choice, all of them wanted:

  1. A coefficient edit in ``_effects_data.py`` propagates automatically. A
     hand-transcription drift is impossible by construction.
  2. MIRRORS need no suffix rule. The filed row warned that mirror prefixes are
     irregular - 2502 becomes 222502 on ARAM but 2501 / 447111 on Arena - so a
     by-name or by-suffix table would have been wrong. A machine sweep of
     ``ITEM_EFFECTS`` sidesteps the question.
  3. It catches a divergence a by-name table would have flattened: Heartsteel's
     cadence is NOT mirrored. SR 3084 procs every 30 seconds, Arena 223084 every
     3.5 (the documented HEARTSTEEL_CADENCE_FIX_IDS split), so the Arena mirror
     pays ~8.6x as often for the same 6 percent.

*** THE MISCLASSIFICATION TRAP ***
A finite-difference probe reports a slope for any proc whose damage MENTIONS the
caster's health, including procs where the caster's health is not the damage
SOURCE. ``4017`` Hellfire Hatchet is the live instance: its Char burn reads
``min(2000, max(0, caster_max_hp - target_max_hp))``, a tankiness COMPARISON
that amplifies damage when the wielder out-tanks the target. The probe happily
reports a 6 percent slope and crediting it would be a category error - the
wielder is not spending health, it is being rewarded for having more than the
target. It is therefore DENIED BY ID in ``_DENIED_ITEM_IDS``, and the test suite
pins that the deny is non-vacuous (the probe really would credit it).

``4015`` Perplexity needs no deny entry: its ``caster_max_hp`` lives in a note
string and in the ``giant_slayer_*`` fields, and this derivation only ever reads
``periodics``. That exclusion is STRUCTURAL, and it is pinned as such so it is
not later mistaken for an oversight.

TITANIC'S AoE HALF IS CONSERVATIVELY EXCLUDED
---------------------------------------------
Titanic Hydra emits two procs: Cleave (primary) at 1 percent of max health, and
Cleave (to nearby) at 3 percent per EXTRA target, scaled by
``max(0, targets_in_rotation - 1)``. The probe runs single-target, so the AoE
half differentiates to exactly zero and only the 1 percent primary is credited.
That is the conservative reading on purpose - crediting the AoE half would price
every Cleave as a teamfight Cleave.

CADENCE
-------
``PeriodicProc`` states its own period, so the amortization is READ, not
assigned by tier the way T1's ``conditional_probability`` has to be. Every
percent is converted to a count of fires over one documented reference fight:

  * ``every_n_seconds = s``  ->  ``_REFERENCE_FIGHT_SECONDS / s``
  * ``every_n_attacks = n``  ->  ``_REFERENCE_FIGHT_SECONDS *
    _ASSUMED_ATTACKS_PER_SECOND / n``, with ``stack_ramp_seconds`` respected as a
    floor on the effective period per the ``PeriodicProc`` docstring.

The two constants are the whole heuristic content of this module and are named,
documented and operator-tunable. They exist to put the credit on a readable
scale - the acceptance flip lands near strength 12, inside the 8-25 band T1's
tests already use - not because a fight is exactly ten seconds long.

CONSUMER CONTRACT
-----------------
``ehp.rank_items_by_ehp`` folds this into the RANKING KEY ONLY, following the
``_conv_key`` / ``_coupling_key`` / ``_health_key`` precedent - no row value is
ever mutated - and the whole lane is inert unless BOTH
``apply_item_caster_hp_proc=True`` AND ``item_caster_hp_proc_strength > 0.0``,
so the default path is byte-identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache, lru_cache

from ._effects_types import CallContext
from .effects import ITEM_EFFECTS

# ---------------------------------------------------------------------------
# The two operator-tunable heuristic constants. See CADENCE above.
# ---------------------------------------------------------------------------
# One reference teamfight. Turns a per-second / per-attack proc rate into a
# dimensionless count of payments, which is what puts the credit on the same
# readable scale as the T1 sibling's strength band.
_REFERENCE_FIGHT_SECONDS = 10.0
# A deliberately CONSERVATIVE tank attack rate. A real tank with boots and one
# legendary attacks faster than this; understating it understates the credit for
# on-hit procs (Titanic, Reverberation) rather than overstating it.
_ASSUMED_ATTACKS_PER_SECOND = 1.0
# Defensive ceiling on the converted fraction. NON-BINDING at 16.14.1 - the
# largest shipped value is Sunfire / Titanic at 0.10 - and present only so a
# future sub-second proc period cannot manufacture an unbounded sort key.
_MAX_CONVERTED_FRACTION = 1.0

# Items whose proc damage RESPONDS to caster health without the caster's health
# being the damage SOURCE. See THE MISCLASSIFICATION TRAP above. Matched by ID,
# never by name (feedback_deny_sweep_by_id_suffix_not_name) - and enumerated
# explicitly rather than by suffix, because mirror prefixes are irregular.
#   * 4017 Hellfire Hatchet - Char reads (caster_max_hp - target_max_hp), a
#     tankiness comparison. No mirror of it exists at 16.14.1.
_DENIED_ITEM_IDS = frozenset({"4017"})

# ---------------------------------------------------------------------------
# Probe context. Fixed, documented values - the derivation is a DERIVATIVE, so
# the operating point only has to be somewhere the proc lambdas are linear, and
# the census guard test re-derives every coefficient at the same point.
# ---------------------------------------------------------------------------
_PROBE_MAX_HP = 3000.0
_PROBE_BONUS_HP = 1500.0
_PROBE_STEP_HP = 1000.0
# targets_in_rotation=1.0 is load-bearing: it is what conservatively zeroes
# Titanic's AoE half. target_max_hp sits BELOW _PROBE_MAX_HP so a
# caster-minus-target comparison proc probes as non-zero and its deny entry is
# provably doing work rather than silently duplicating a zero.
_PROBE_TARGET_MAX_HP = 2400.0


def _probe_ctx(*, max_hp: float, bonus_hp: float) -> CallContext:
    return CallContext(
        base_ad=100.0,
        bonus_ad=50.0,
        level=13,
        ap=0.0,
        caster_max_hp=max_hp,
        caster_bonus_hp=bonus_hp,
        targets_in_rotation=1.0,
        target_max_hp=_PROBE_TARGET_MAX_HP,
    )


@dataclass(frozen=True)
class ItemCasterHpProcEntry:
    """One item's own caster-health -> damage conversion, derived from its procs.

    ``max_hp_pct`` / ``bonus_hp_pct`` are the percent of the WIELDER's maximum /
    bonus health the item's procs re-spend as damage per fire, differentiated out
    of ``ITEM_EFFECTS``. Exactly one is non-zero for every shipped item at
    16.14.1; the guard test fails a future two-pool proc rather than averaging
    the two pools together.

    ``fires_per_fight`` is that proc's cadence expressed over one reference
    fight, so the consumer needs no cadence logic of its own.
    """

    item_id: str
    item_name: str
    proc_name: str
    max_hp_pct: float = 0.0
    bonus_hp_pct: float = 0.0
    fires_per_fight: float = 0.0


def _fires_per_fight(proc) -> float:
    """Cadence -> count of fires over one reference fight.

    Reads the proc's OWN period rather than assigning a tier, which is the
    structural advantage T2 has over T1: an item states its cadence in data, a
    champion ability's real-world cast rate does not.
    """
    if proc.every_n_seconds > 0:
        return _REFERENCE_FIGHT_SECONDS / float(proc.every_n_seconds)
    n_attacks = max(1, int(proc.every_n_attacks))
    # Per the PeriodicProc docstring, a stack ramp floors the effective period:
    # the discharge cannot arrive faster than the ramp allows.
    attack_period = 1.0 / _ASSUMED_ATTACKS_PER_SECOND
    period = max(float(proc.stack_ramp_seconds), n_attacks * attack_period)
    if period <= 0.0:
        return 0.0
    return _REFERENCE_FIGHT_SECONDS / period


def _derive(item_id: str) -> ItemCasterHpProcEntry | None:
    """Differentiate one item's procs against caster health. None if inert."""
    if not item_id or item_id in _DENIED_ITEM_IDS:
        return None
    eff = ITEM_EFFECTS.get(str(item_id))
    if eff is None:
        return None
    lo = _probe_ctx(max_hp=_PROBE_MAX_HP, bonus_hp=_PROBE_BONUS_HP)
    hi_max = _probe_ctx(
        max_hp=_PROBE_MAX_HP + _PROBE_STEP_HP, bonus_hp=_PROBE_BONUS_HP
    )
    hi_bonus = _probe_ctx(
        max_hp=_PROBE_MAX_HP, bonus_hp=_PROBE_BONUS_HP + _PROBE_STEP_HP
    )
    max_pct = 0.0
    bonus_pct = 0.0
    fires = 0.0
    proc_name = ""
    for proc in (eff.periodics or ()):
        base = proc.resolve_damage(lo)
        d_max = (proc.resolve_damage(hi_max) - base) / _PROBE_STEP_HP * 100.0
        d_bonus = (proc.resolve_damage(hi_bonus) - base) / _PROBE_STEP_HP * 100.0
        if abs(d_max) <= 1e-12 and abs(d_bonus) <= 1e-12:
            continue
        # A health LOSS proc is not a conversion; floor rather than credit a
        # negative percent into a sort key (the _conv_key guard shape).
        max_pct += max(0.0, d_max)
        bonus_pct += max(0.0, d_bonus)
        # The dominant (fastest) sensitive proc sets the cadence. Every shipped
        # item has exactly ONE sensitive proc, so this is a tie-break that never
        # fires today; it is here so a future second sensitive proc degrades to
        # the faster cadence instead of silently keeping whichever came first.
        this_fires = _fires_per_fight(proc)
        if this_fires > fires:
            fires = this_fires
            proc_name = proc.name
    if (max_pct + bonus_pct) <= 0.0 or fires <= 0.0:
        return None
    return ItemCasterHpProcEntry(
        item_id=str(item_id),
        item_name=str(eff.name or item_id),
        proc_name=proc_name,
        max_hp_pct=max_pct,
        bonus_hp_pct=bonus_pct,
        fires_per_fight=fires,
    )


@cache
def item_caster_hp_proc(item_id: str) -> ItemCasterHpProcEntry | None:
    """Return the item's derived caster-HP proc entry, or None.

    Fail-soft by design (the sibling-registry contract): an unknown / empty /
    denied / proc-less id returns None, which collapses the consumer's credit to
    an exact no-op. Memoized because the ranker asks once per candidate per call.
    """
    if not item_id:
        return None
    return _derive(str(item_id))


@lru_cache(maxsize=1)
def caster_hp_proc_census() -> dict[str, ItemCasterHpProcEntry]:
    """Every credited item at the active patch, derived by sweeping ITEM_EFFECTS.

    Used by the guard test to pin the population in BOTH directions, and by the
    consumer's observability note. Not on any hot path - the ranker goes through
    ``item_caster_hp_proc`` per candidate instead.
    """
    out: dict[str, ItemCasterHpProcEntry] = {}
    for item_id in ITEM_EFFECTS:
        entry = item_caster_hp_proc(str(item_id))
        if entry is not None:
            out[str(item_id)] = entry
    return out


def proc_converted_points(
    entry: ItemCasterHpProcEntry,
    pool_max_hp: float,
    pool_bonus_hp: float,
) -> float:
    """Health points the ITEM re-spends as damage per fire, given the pools.

    Each percent reads the pool it names, which is what keeps a bonus-basis proc
    (Unending Despair, 3 percent of BONUS health) from being priced as though it
    read the much larger total pool. Cadence is applied by the CALLER, once, to
    the final normalized credit, so it can never be double-applied.

    Negative pools floor at zero - the same guard shape as
    ``_health_damage_coupling.coupled_health_points``.
    """
    total = max(0.0, float(pool_max_hp))
    bonus = max(0.0, float(pool_bonus_hp))
    return (entry.max_hp_pct / 100.0) * total + (entry.bonus_hp_pct / 100.0) * bonus


__all__ = [
    "ItemCasterHpProcEntry",
    "item_caster_hp_proc",
    "caster_hp_proc_census",
    "proc_converted_points",
    "_DENIED_ITEM_IDS",
    "_REFERENCE_FIGHT_SECONDS",
    "_ASSUMED_ATTACKS_PER_SECOND",
    "_MAX_CONVERTED_FRACTION",
]
