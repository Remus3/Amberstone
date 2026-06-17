"""Daemon Slayer V2 enemy-rune threat seam (DSP6).

Net-new additive substrate. RC modeled the player's OWN runes (``rune_procs.py``,
``core/rune_wpa.py``) but had ZERO model of the ENEMY's runes as a threat that
modulates how survivable the player is (EHP preset) or how tanky the enemy is
(target preset). This module is the enemy-side mirror of ``summoners.py`` - a
self-contained hardcoded registry, a pure formula closure per rune, fail-soft,
``__all__``-exported.

DEFAULT-OFF: nothing wires this into a live scorer in the shipping run, so the
live ``rank.py`` / ``compute_dps`` / ``compute_ehp`` / ``compute_burst`` output
is BYTE-IDENTICAL to the pre-DSP6 engine. ``ENEMY_RUNE_SEAM_IDS`` is the explicit
marker for the rune ids this seam models. The live default-ON consumption (a
fight_report / matchup / EHP-preset consumer reading the enemy's actual rune set
from the live client to discount the player's effective survivability and the
player's heal valuation, and to raise the enemy's poke-resist) is operator-gated
- see ``docs/LIVE_GAME_GATED_SYNC.md``. Per the seam contract a WRONG precompute
is worse than none, so the flip is validated against a real game before taken.

DATA SOURCE: every coefficient is verbatim from the live DDragon
``runesReforged.json`` ``longDesc`` at patch 16.12.1
(``data/meta_build/ddragon/16.12.1/runesReforged.json``), cross-checked against
the LoL wiki (``reference_lol_wiki_access``). DDragon is authoritative per the
repo DON'T-REDO rule (never aggregator D / aggregator A). Each coefficient cites its
DDragon longDesc value in the ``formula`` string. Do NOT invent numbers.

axis semantics (the preset each rune modulates when a consumer is wired):
  * ``incoming_amp``   - Press the Attack: the enemy amplifies their damage
                         dealt by 8% (a flat incoming-damage amp on the player,
                         an EHP-numerator divisor 1/(1+amp)).
  * ``damage_ramp``    - Conqueror: a ramping bonus Adaptive Force the enemy
                         gains over a fight (the legacy "true-dmg ramp" lens) -
                         raw bonus enemy damage plus, at max stacks, lifesteal
                         that makes the enemy outlast the player (target preset).
  * ``poke_sustain``   - Grasp of the Undying + Second Wind: the enemy recovers
                         poke damage (Grasp heal + permanent HP, Second Wind
                         missing-HP regen), raising the enemy's effective HP vs
                         sustained / poke damage (target preset).

ANTIHEAL is the fourth DSP6 threat bucket but is NOT a rune: no League rune
grants Grievous Wounds (it comes from items - Executioner's / Morellonomicon /
Chempunk - and from Ignite, already modeled in ``summoners.py`` id 14). The seam
carries it as a non-rune constant + a flag helper (``enemy_antiheal_pct``) so a
single consumer can discount the player's heal-based EHP when ANY antiheal source
is on the enemy team, alongside the rune threats. ``ENEMY_RUNE_SEAM_IDS`` does
NOT include antiheal (it has no id).

Contract: fail-soft (never raises; unknown rune -> 0.0). ASCII only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable

__all__ = [
    "EnemyRuneThreat",
    "ENEMY_RUNE_THREATS",
    "ENEMY_RUNE_SEAM_IDS",
    "GRIEVOUS_WOUNDS_PCT",
    "compute_enemy_rune_value",
    "enemy_incoming_amp_pct",
    "enemy_damage_ramp",
    "enemy_poke_sustain_pct",
    "enemy_poke_sustain_hp",
    "enemy_grasp_magic_proc",
    "enemy_antiheal_pct",
]


# ---------------------------------------------------------------------------
# Scaling helpers (pure, fail-soft) - mirror summoners._clamp_level / _lerp.
# ---------------------------------------------------------------------------

def _clamp_level(level: float) -> int:
    """Clamp an incoming level to the League 1..18 band, integer (fail-soft)."""
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        return 1
    if lvl < 1:
        return 1
    if lvl > 18:
        return 18
    return lvl


def _lerp_by_level(low: float, high: float, level: float) -> float:
    """Linear interpolate ``low`` (level 1) to ``high`` (level 18).

    The standard League "X - Y based on level" 17-step ramp: value at level L is
    ``low + (high - low) * (L - 1) / 17``, with L clamped to 1..18.
    """
    lvl = _clamp_level(level)
    return low + (high - low) * (lvl - 1) / 17.0


# Grievous Wounds healing-reduction fraction. League applies 40% (the "light"
# Grievous Wounds tier - Ignite, Executioner's, most ranged antiheal items);
# the "heavy" 50% tier (melee Mortal Reminder / Chempunk on champions below 50%
# HP) is a consumer refinement, not modeled here. Cited: LoL wiki Grievous
# Wounds, 2026-06-17 (matches summoners.py Ignite antiheal_pct=0.40).
GRIEVOUS_WOUNDS_PCT = 0.40


# ---------------------------------------------------------------------------
# EnemyRuneThreat dataclass.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnemyRuneThreat:
    """A single enemy rune's primary threat contribution.

    ``compute`` is the PRIMARY-axis closure: a flat level-independent scalar for
    ``incoming_amp`` (Press the Attack 0.08) and ``poke_sustain`` (Grasp 0.013
    of max HP, Second Wind 0.04 of missing HP); a level-scaled scalar for
    ``damage_ramp`` (Conqueror max-stack Adaptive Force, 21.6 - 48.0 by level).
    The flat fields below carry the secondary magnitudes so an axis helper can
    read them without re-deriving from the closure.
    """

    rune_id: int
    name: str
    axis: str
    formula: str
    compute: Callable[..., float] = field(
        default=lambda **_kw: 0.0, compare=False, repr=False
    )
    incoming_amp_pct: float = 0.0     # Press the Attack damage amp on the player
    poke_heal_pct: float = 0.0        # Grasp heal of max HP / Second Wind of missing HP
    grasp_magic_pct: float = 0.0      # Grasp bonus magic damage (% of enemy max HP)
    perm_hp: float = 0.0              # Grasp permanent HP per proc
    ranged_factor: float = 1.0        # Grasp ranged effectiveness (0.40)
    lifesteal_pct_melee: float = 0.0  # Conqueror max-stack heal (melee)
    lifesteal_pct_ranged: float = 0.0  # Conqueror max-stack heal (ranged)


# ---------------------------------------------------------------------------
# Per-rune PRIMARY-axis closures. Each reads only ``level``; extras ignored.
# ---------------------------------------------------------------------------

def _press_the_attack(**_kw) -> float:
    # DDragon: "amplifies your damage dealt by 8%". The flat incoming-damage amp
    # on the player (level-independent). The 40-160 adaptive third-hit burst is
    # carried in the formula string, not the primary axis.
    return 0.08


def _conqueror(*, level=1.0, **_kw) -> float:
    # DDragon: "1.8-4 Adaptive Force per stack. Stacks up to 12 times." Max-stack
    # bonus Adaptive Force = 12 * (1.8 - 4.0 by level) = 21.6 (L1) -> 48.0 (L18).
    return 12.0 * _lerp_by_level(1.8, 4.0, level)


def _grasp(**_kw) -> float:
    # DDragon: "Heal you for 1.3% of your max health" per proc (melee). The
    # primary poke-sustain axis is the heal fraction of max HP.
    return 0.013


def _second_wind(**_kw) -> float:
    # DDragon: "heal for 4% of your missing health over 10s" after taking damage.
    return 0.04


# ---------------------------------------------------------------------------
# Registry. Keyed by Riot rune id (DDragon runesReforged.json).
# ---------------------------------------------------------------------------

ENEMY_RUNE_THREATS: Dict[int, EnemyRuneThreat] = {
    8005: EnemyRuneThreat(
        rune_id=8005,
        name="Press the Attack",
        axis="incoming_amp",
        formula=(
            "3 consecutive basic attacks deal 40-160 adaptive (by level) and "
            "amplify the attacker's damage dealt by 8% until they leave combat. "
            "compute = incoming_amp_pct 0.08 (the player takes 8% more from a "
            "PtA enemy; EHP-numerator divisor 1/1.08); the 40-160 third-hit "
            "burst is incidental (DDragon runesReforged 16.12.1)"
        ),
        compute=_press_the_attack,
        incoming_amp_pct=0.08,
    ),
    8010: EnemyRuneThreat(
        rune_id=8010,
        name="Conqueror",
        axis="damage_ramp",
        formula=(
            "2 stacks per damaging hit, 1.8-4 Adaptive Force per stack (by "
            "level), up to 12 stacks (ranged 1 stack/AA). At max, heal 8% of "
            "damage dealt to champions (5% ranged). compute = max-stack Adaptive "
            "Force = 12 * (1.8-4 by level) = 21.6-48.0 (raw bonus enemy damage, "
            "the ramp); lifesteal_pct_melee 0.08 / ranged 0.05 carried for the "
            "enemy-sustain (target) lens (DDragon runesReforged 16.12.1)"
        ),
        compute=_conqueror,
        lifesteal_pct_melee=0.08,
        lifesteal_pct_ranged=0.05,
    ),
    8437: EnemyRuneThreat(
        rune_id=8437,
        name="Grasp of the Undying",
        axis="poke_sustain",
        formula=(
            "every 4s in combat the next AA deals 3.5% max-HP magic damage, "
            "heals 1.3% max HP, and grants +5 permanent HP (ranged 40% "
            "effective). compute = poke_heal_pct 0.013 (heal fraction of max HP "
            "per proc); grasp_magic_pct 0.035, perm_hp 5.0, ranged_factor 0.40 "
            "(DDragon runesReforged 16.12.1)"
        ),
        compute=_grasp,
        poke_heal_pct=0.013,
        grasp_magic_pct=0.035,
        perm_hp=5.0,
        ranged_factor=0.40,
    ),
    8444: EnemyRuneThreat(
        rune_id=8444,
        name="Second Wind",
        axis="poke_sustain",
        formula=(
            "after taking damage from an enemy champion, heal for 4% of missing "
            "health over 10s. compute = poke_heal_pct 0.04 (heal fraction of "
            "MISSING HP) (DDragon runesReforged 16.12.1)"
        ),
        compute=_second_wind,
        poke_heal_pct=0.04,
    ),
}


# DSP6 enemy-rune threat seam: the rune ids this seam models. Members exist in
# ENEMY_RUNE_THREATS (queryable by fight_report / matchup / a future EHP-preset
# consumer) but NO live scorer consumes them in this revision, so the live /rank
# path is byte-identical to the pre-DSP6 engine. A live default-ON consumer flip
# joins the operator's list in docs/LIVE_GAME_GATED_SYNC.md (do-not-flip-blind).
# Antiheal is NOT included (no rune grants Grievous Wounds; it is a non-rune
# threat carried via GRIEVOUS_WOUNDS_PCT + enemy_antiheal_pct).
ENEMY_RUNE_SEAM_IDS: frozenset[int] = frozenset(ENEMY_RUNE_THREATS)


# ---------------------------------------------------------------------------
# Public functions (fail-soft: unknown id / bad input -> 0.0, never raise).
# ---------------------------------------------------------------------------

def compute_enemy_rune_value(rune_id: int, level: float = 1.0) -> float:
    """Return a rune's PRIMARY-axis scalar (level-scaled where applicable).

    Press the Attack -> 0.08 incoming amp; Conqueror -> max-stack Adaptive Force
    (21.6-48.0 by level); Grasp -> 0.013 heal fraction; Second Wind -> 0.04 heal
    fraction. Unknown id -> 0.0.
    """
    threat = ENEMY_RUNE_THREATS.get(rune_id)
    if threat is None:
        return 0.0
    try:
        return float(threat.compute(level=level))
    except Exception:
        return 0.0


def enemy_incoming_amp_pct(rune_ids: Iterable[int]) -> float:
    """Total flat incoming-damage amp on the player from enemy runes.

    Press the Attack contributes 0.08 (the enemy's 8% damage-dealt amp lands as
    an 8% incoming amp on the player). A consumer applies it as an EHP-numerator
    divisor ``ehp / (1.0 + amp)``; amp 0.0 -> byte-identical. Conqueror is a raw
    bonus-damage ramp (``enemy_damage_ramp``), NOT a flat % amp, so it is NOT
    summed here. Unknown / empty -> 0.0.
    """
    total = 0.0
    for rid in _iter_ids(rune_ids):
        threat = ENEMY_RUNE_THREATS.get(rid)
        if threat is not None:
            total += float(threat.incoming_amp_pct)
    return total


def enemy_damage_ramp(rune_ids: Iterable[int], level: float = 1.0) -> float:
    """Raw flat bonus enemy damage from a ramping rune (Conqueror's max-stack
    Adaptive Force, 21.6-48.0 by level). This is the "true-dmg ramp" lens: extra
    enemy output that lowers the player's effective survivability. Summed across
    any ramp-axis runes in the set. Unknown / empty -> 0.0.
    """
    total = 0.0
    for rid in _iter_ids(rune_ids):
        threat = ENEMY_RUNE_THREATS.get(rid)
        if threat is not None and threat.axis == "damage_ramp":
            total += compute_enemy_rune_value(rid, level=level)
    return total


def enemy_poke_sustain_pct(rune_ids: Iterable[int], ranged: bool = False) -> float:
    """Nominal poke-recovery fraction the enemy gains from Grasp + Second Wind.

    Grasp heals 1.3% of MAX HP per proc (x ranged_factor 0.40 if ``ranged``);
    Second Wind heals 4% of MISSING HP. The two bases differ (max vs missing HP)
    so this nominal sum is a coarse poke-resist indicator; ``enemy_poke_sustain_
    hp`` gives the exact HP given both bases. Unknown / empty -> 0.0.
    """
    total = 0.0
    for rid in _iter_ids(rune_ids):
        threat = ENEMY_RUNE_THREATS.get(rid)
        if threat is None or threat.axis != "poke_sustain":
            continue
        frac = float(threat.poke_heal_pct)
        if ranged and threat.rune_id == 8437:
            frac *= float(threat.ranged_factor)
        total += frac
    return total


def enemy_poke_sustain_hp(
    rune_ids: Iterable[int],
    enemy_max_hp: float,
    enemy_missing_hp: float = 0.0,
    ranged: bool = False,
) -> float:
    """Concrete bonus EHP (in HP) the enemy recovers vs poke from Grasp + Second
    Wind. Grasp = (0.013 * max_hp + 5.0 perm) * ranged_factor; Second Wind =
    0.04 * missing_hp. Fail-soft (bad numbers -> 0.0). Unknown / empty -> 0.0.
    """
    try:
        max_hp = float(enemy_max_hp)
        missing_hp = float(enemy_missing_hp)
    except (TypeError, ValueError):
        return 0.0
    total = 0.0
    for rid in _iter_ids(rune_ids):
        threat = ENEMY_RUNE_THREATS.get(rid)
        if threat is None or threat.axis != "poke_sustain":
            continue
        if threat.rune_id == 8437:  # Grasp
            rf = float(threat.ranged_factor) if ranged else 1.0
            total += (float(threat.poke_heal_pct) * max_hp + float(threat.perm_hp)) * rf
        elif threat.rune_id == 8444:  # Second Wind
            total += float(threat.poke_heal_pct) * missing_hp
    return total


def enemy_grasp_magic_proc(
    rune_ids: Iterable[int], enemy_max_hp: float, ranged: bool = False
) -> float:
    """Grasp's bonus magic damage per proc (3.5% of the GRASP-CARRIER's max HP,
    x 0.40 if ranged). A small incoming-damage threat carried for completeness.
    Returns 0.0 when no Grasp in the set or on bad input.
    """
    if 8437 not in set(_iter_ids(rune_ids)):
        return 0.0
    threat = ENEMY_RUNE_THREATS[8437]
    try:
        max_hp = float(enemy_max_hp)
    except (TypeError, ValueError):
        return 0.0
    rf = float(threat.ranged_factor) if ranged else 1.0
    return float(threat.grasp_magic_pct) * max_hp * rf


def enemy_antiheal_pct(antiheal_present: bool) -> float:
    """Grievous Wounds healing-reduction fraction to apply to the PLAYER's heals
    when ANY antiheal source is on the enemy team (0.40), else 0.0.

    Antiheal is the DSP6 fourth threat bucket but is NOT a rune (no rune grants
    Grievous Wounds); it is carried here as a flag-driven constant so a single
    consumer can discount the player's heal-based EHP alongside the rune threats.
    The antiheal source itself (Ignite id 14 -> ``summoners.summoner_antiheal_
    pct``; antiheal items) is detected elsewhere; this returns the magnitude.
    """
    return GRIEVOUS_WOUNDS_PCT if antiheal_present else 0.0


def _iter_ids(rune_ids: Iterable[int]) -> Iterable[int]:
    """Fail-soft id iterator: an empty / None / non-iterable input yields none."""
    if not rune_ids:
        return ()
    try:
        return tuple(int(r) for r in rune_ids)
    except (TypeError, ValueError):
        return ()
