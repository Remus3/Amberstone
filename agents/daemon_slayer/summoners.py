"""Daemon Slayer V2 summoner-spell seam (DSP5).

Net-new additive substrate. RC had ZERO summoner-spell layer before this module.
A self-contained hardcoded registry in the same style as ``rune_procs.RUNE_PROCS``
- a pure formula closure per spell, fail-soft, ``__all__``-exported.

DEFAULT-OFF: nothing wires this into a live scorer in the shipping run, so the
live ``rank.py`` / ``compute_dps`` / ``compute_ehp`` output is BYTE-IDENTICAL to
the pre-DSP5 engine. ``SUMMONER_SEAM_IDS`` is the explicit marker for the ids
this seam models. The live default-ON consumption (fight_report / matchup /
coach reading these to adjust a caster's effective survivability, antiheal, and
CC-duration) is operator-gated - see ``docs/LIVE_GAME_GATED_SYNC.md``. Per the
seam contract, a WRONG precompute is worse than none, so the flip is validated
against a real game before it is taken.

DATA SOURCE: DDragon ``summoner.json`` (16.12.1) and the CommunityDragon
``summoner-spells.json`` BOTH zero the numeric magnitudes for summoner spells
(the description fields carry only prose, mirroring the way DDragon strips item
passive damage formulas). The sanctioned fallback for stripped magnitudes is the
LoL wiki (``reference_lol_wiki_access``: ``wiki.leagueoflegends.com``), fetched
2026-06-17. Each coefficient below cites its wiki value verbatim in ``formula``.
CAVEAT: the wiki always reflects the live game patch, which post-dates the RC
DDragon snapshot 16.12.1; summoner-spell magnitudes are structurally patch-stable
but the exact endpoints (e.g. Ignite 70-525, Barrier 100-502.35) may drift a few
points across patches. Because the seam ships DEFAULT-OFF the magnitude has ZERO
live impact this revision; the operator's live default-ON flip re-anchors to the
then-current patch (the standard patch-refresh re-extract corrects any drift).
Do NOT invent numbers - every value here is the cited wiki value.

axis semantics (the scoring lane each spell feeds when a consumer is wired):
  * ``antiheal_true`` - Ignite: a true-damage DoT plus a Grievous Wounds
                        healing-reduction debuff on the target.
  * ``incoming_dr``   - Exhaust: reduces the exhausted enemy's damage dealt, so
                        the caster takes less (an EHP-numerator multiplier when
                        the enemy carry is exhausted).
  * ``ehp_heal``      - Heal: a flat self-heal (EHP-equivalent) plus brief MS.
  * ``ehp_shield``    - Barrier: a flat self-shield (EHP-equivalent).
  * ``cc_discount``   - Cleanse: tenacity / immobilize-duration reduction (the
                        QSS item analog feeds the same lane).
  * ``move_speed``    - Ghost: a level-scaled bonus move-speed window.

Contract: fail-soft (never raises; unknown spell -> 0.0). ASCII only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict

__all__ = [
    "SummonerSpell",
    "SUMMONER_SPELLS",
    "SUMMONER_SEAM_IDS",
    "compute_summoner_value",
    "summoner_antiheal_pct",
    "summoner_incoming_dr_pct",
    "summoner_cc_discount_pct",
    "compute_summoner_ms_pct",
    "compute_summoner_ehp_bonus",
]


# ---------------------------------------------------------------------------
# Scaling helpers (pure, fail-soft) - mirror rune_procs._clamp_level / _lerp.
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


# ---------------------------------------------------------------------------
# SummonerSpell dataclass.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SummonerSpell:
    """A single summoner spell's primary scoring contribution.

    ``compute`` is the PRIMARY-axis closure: a level-scaled scalar for
    ``antiheal_true`` (Ignite true damage), ``ehp_heal`` (Heal flat heal),
    ``ehp_shield`` (Barrier flat shield) and ``move_speed`` (Ghost MS fraction);
    a flat level-independent scalar for ``incoming_dr`` (Exhaust 0.35) and
    ``cc_discount`` (Cleanse 0.75). The flat-fraction fields below carry the
    secondary debuff/buff magnitudes so an axis helper can read them without
    re-deriving from the closure.
    """

    spell_id: int
    name: str
    axis: str
    cooldown_s: float
    duration_s: float
    formula: str
    compute: Callable[..., float] = field(
        default=lambda **_kw: 0.0, compare=False, repr=False
    )
    antiheal_pct: float = 0.0      # Ignite Grievous Wounds healing reduction
    incoming_dr_pct: float = 0.0   # Exhaust damage-dealt reduction on the target
    cc_discount_pct: float = 0.0   # Cleanse tenacity / immobilize-duration cut
    ms_pct_flat: float = 0.0       # Heal's flat MS (Ghost's MS is level-scaled)


# ---------------------------------------------------------------------------
# Per-spell PRIMARY-axis closures. Each reads only ``level``; extras ignored.
# ---------------------------------------------------------------------------

def _ignite(*, level=1.0, **_kw) -> float:
    # Wiki: "70 - 525 (based on level)" true damage dealt over 5s.
    return _lerp_by_level(70.0, 525.0, level)


def _exhaust(**_kw) -> float:
    # Wiki: reduces the target's damage dealt by 35% for 3s (level-independent).
    return 0.35


def _heal(*, level=1.0, **_kw) -> float:
    # Wiki: "80 - 346 (based on level)" health restored (+30% MS for 1s).
    return _lerp_by_level(80.0, 346.0, level)


def _barrier(*, level=1.0, **_kw) -> float:
    # Wiki: "100 - 502.35 (based on level)" shield for 2.5s.
    return _lerp_by_level(100.0, 502.35, level)


def _cleanse(**_kw) -> float:
    # Wiki: 75% tenacity for 3s (reduces incoming immobilize duration).
    return 0.75


def _ghost(*, level=1.0, **_kw) -> float:
    # Wiki: "24% - 50.82% (based on level)" bonus move speed for 10s.
    return _lerp_by_level(0.24, 0.5082, level)


# ---------------------------------------------------------------------------
# Registry. Keyed by Riot summoner-spell id.
# ---------------------------------------------------------------------------

SUMMONER_SPELLS: Dict[int, SummonerSpell] = {
    14: SummonerSpell(
        spell_id=14,
        name="Ignite",
        axis="antiheal_true",
        cooldown_s=180.0,
        duration_s=5.0,
        formula=(
            "70-525 true damage over 5s by level + 40% Grievous Wounds "
            "(healing reduction) for the same 5s. compute = 70-525 by level "
            "(total DoT); antiheal_pct = 0.40 (LoL wiki 2026-06-17; DDragon/"
            "CDragon 16.12.1 zero the magnitude)"
        ),
        compute=_ignite,
        antiheal_pct=0.40,
    ),
    3: SummonerSpell(
        spell_id=3,
        name="Exhaust",
        axis="incoming_dr",
        cooldown_s=240.0,
        duration_s=3.0,
        formula=(
            "slows the target 40% MS and reduces their damage dealt 35% for 3s. "
            "compute = incoming_dr_pct 0.35 (the caster takes 35% less from an "
            "exhausted enemy; level-independent) (LoL wiki 2026-06-17)"
        ),
        compute=_exhaust,
        incoming_dr_pct=0.35,
    ),
    7: SummonerSpell(
        spell_id=7,
        name="Heal",
        axis="ehp_heal",
        cooldown_s=240.0,
        duration_s=1.0,
        formula=(
            "restores 80-346 health by level (self + ally) and grants 30% bonus "
            "MS for 1s. compute = 80-346 by level (flat self-heal EHP); "
            "ms_pct_flat = 0.30 (LoL wiki 2026-06-17)"
        ),
        compute=_heal,
        ms_pct_flat=0.30,
    ),
    21: SummonerSpell(
        spell_id=21,
        name="Barrier",
        axis="ehp_shield",
        cooldown_s=180.0,
        duration_s=2.5,
        formula=(
            "shields 100-502.35 by level for 2.5s. compute = 100-502.35 by "
            "level (flat self-shield EHP) (LoL wiki 2026-06-17)"
        ),
        compute=_barrier,
    ),
    1: SummonerSpell(
        spell_id=1,
        name="Cleanse",
        axis="cc_discount",
        cooldown_s=240.0,
        duration_s=3.0,
        formula=(
            "removes most disables (excl. airborne / suppression / nearsight) + "
            "grants 75% tenacity for 3s. compute = cc_discount_pct 0.75 "
            "(immobilize-duration reduction; the QSS item analog feeds the same "
            "lane) (LoL wiki 2026-06-17)"
        ),
        compute=_cleanse,
        cc_discount_pct=0.75,
    ),
    6: SummonerSpell(
        spell_id=6,
        name="Ghost",
        axis="move_speed",
        cooldown_s=240.0,
        duration_s=10.0,
        formula=(
            "24%-50.82% bonus move speed by level for 10s (ignores unit "
            "collision). compute = 0.24-0.5082 by level (MS fraction) "
            "(LoL wiki 2026-06-17)"
        ),
        compute=_ghost,
    ),
}


# DSP5 summoner-spell seam: the ids this seam models. Members exist in
# SUMMONER_SPELLS (queryable by fight_report / matchup / a future coach) but NO
# live scorer consumes them in this revision, so the live /rank path is
# byte-identical to the pre-DSP5 engine. A live default-ON consumer flip joins
# the operator's list in docs/LIVE_GAME_GATED_SYNC.md (do-not-flip-blind).
SUMMONER_SEAM_IDS: frozenset[int] = frozenset(SUMMONER_SPELLS)


# ---------------------------------------------------------------------------
# Public functions (fail-soft: unknown id / bad input -> 0.0, never raise).
# ---------------------------------------------------------------------------

def compute_summoner_value(spell_id: int, level: float = 1.0) -> float:
    """Return a spell's PRIMARY-axis scalar (level-scaled where applicable).

    Ignite -> true damage; Exhaust -> 0.35 incoming-DR; Heal -> flat heal;
    Barrier -> flat shield; Cleanse -> 0.75 cc-discount; Ghost -> MS fraction.
    Unknown id -> 0.0.
    """
    spell = SUMMONER_SPELLS.get(spell_id)
    if spell is None:
        return 0.0
    try:
        return float(spell.compute(level=level))
    except Exception:
        return 0.0


def summoner_antiheal_pct(spell_id: int) -> float:
    """Grievous Wounds healing-reduction fraction (Ignite 0.40, else 0.0)."""
    spell = SUMMONER_SPELLS.get(spell_id)
    return float(spell.antiheal_pct) if spell is not None else 0.0


def summoner_incoming_dr_pct(spell_id: int) -> float:
    """Incoming damage-reduction fraction from exhausting the enemy (0.35/0.0)."""
    spell = SUMMONER_SPELLS.get(spell_id)
    return float(spell.incoming_dr_pct) if spell is not None else 0.0


def summoner_cc_discount_pct(spell_id: int) -> float:
    """CC-duration discount (tenacity) fraction (Cleanse 0.75, else 0.0)."""
    spell = SUMMONER_SPELLS.get(spell_id)
    return float(spell.cc_discount_pct) if spell is not None else 0.0


def compute_summoner_ms_pct(spell_id: int, level: float = 1.0) -> float:
    """Bonus move-speed fraction. Ghost is level-scaled (0.24-0.5082); Heal is
    a flat 0.30; every other spell is 0.0. Unknown id -> 0.0.
    """
    spell = SUMMONER_SPELLS.get(spell_id)
    if spell is None:
        return 0.0
    if spell.axis == "move_speed":
        return compute_summoner_value(spell_id, level=level)
    return float(spell.ms_pct_flat)


def compute_summoner_ehp_bonus(spell_id: int, level: float = 1.0) -> float:
    """Flat EHP-equivalent from a defensive summoner (Heal flat heal, Barrier
    flat shield), level-scaled. Damage / CC / pure-MS spells -> 0.0.
    """
    spell = SUMMONER_SPELLS.get(spell_id)
    if spell is None:
        return 0.0
    if spell.axis in ("ehp_heal", "ehp_shield"):
        return compute_summoner_value(spell_id, level=level)
    return 0.0
