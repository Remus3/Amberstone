"""Daemon Slayer V2 keystone / proc RUNE damage + amp layer (RUNE_PROCS).

Net-new additive substrate (DS V2 3.2). RC had ZERO rune-proc layer before
this module (item 226 verified). Nothing wires this into a live scorer in the
shipping run - it is a self-contained hardcoded registry in the same style as
``_effects_data.ITEM_EFFECTS``, with a pure formula closure per rune.

DATA SOURCE: every coefficient is verbatim from the live DDragon
``runesReforged.json`` ``longDesc`` field at patch 16.11.1
(``data/meta_build/ddragon/16.11.1/runesReforged.json``), cross-checked
against the LoL wiki. DDragon is the authoritative source per the repo
DON'T-REDO rule (never aggregator D / aggregator A). Where the DS_V2 brief named a
coefficient that disagreed with the live DDragon longDesc, the DDragon value
WINS and the divergence is documented inline in the ``formula`` string so the
provenance is auditable (Do NOT invent numbers).

proc_type semantics:
  * ``on_proc_burst``  - one burst of damage when the rune procs. The closure
                         returns that burst.
  * ``per_attack``     - damage added to each auto-attack. The closure returns
                         the per-AA contribution.
  * ``stacking_amp``   - a flat-damage AMPLIFIER (Press the Attack). Consumed
                         via :func:`keystone_amp`; the closure returns the
                         multiplier-minus-one as a "damage-equivalent" of 0 so
                         the burst path stays honest (amp is not a flat burst).
  * ``adaptive``       - an adaptive stat stack surfaced as a damage-equivalent
                         per-stack value (Conqueror current-patch). The closure
                         returns the per-stack adaptive force; the caller
                         multiplies by live stack count.

Adaptive rule: an adaptive rune picks AD vs AP by whichever the build has more
of - ``if ad >= ap`` use the AD coefficient else the AP coefficient (standard
League adaptive tiebreak goes to AD).

Contract: fail-soft (never raises; unknown rune -> 0.0 / pass-through).
ASCII only. ``__all__`` exports the public surface. ENGINE_VERSION is NOT
bumped (additive, no live scorer consumes this yet).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

__all__ = [
    "RuneProc",
    "RUNE_PROCS",
    "compute_rune_proc_damage",
    "keystone_amp",
]


# ---------------------------------------------------------------------------
# Scaling helpers (pure, fail-soft).
# ---------------------------------------------------------------------------

def _clamp_level(level: float) -> int:
    """Clamp an incoming level to the League 1..18 band, integer."""
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

    Standard League "X - Y based on level" 17-step ramp: value at level L is
    low + (high - low) * (L - 1) / 17, with L clamped to 1..18.
    """
    lvl = _clamp_level(level)
    return low + (high - low) * (lvl - 1) / 17.0


def _adaptive_coeff(ad: float, ap: float, ad_coeff: float, ap_coeff: float) -> float:
    """Pick the AD-side vs AP-side coefficient by the standard adaptive rule.

    AD wins ties (League's adaptive force defaults to AD when AD bonus >= AP
    bonus). Returns the chosen coefficient multiplied by the matching stat.
    """
    try:
        ad_v = float(ad)
        ap_v = float(ap)
    except (TypeError, ValueError):
        return 0.0
    if ad_v >= ap_v:
        return ad_coeff * ad_v
    return ap_coeff * ap_v


def _f(v: float) -> float:
    """Coerce to float, fail-soft to 0.0."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# RuneProc dataclass.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuneProc:
    """A single keystone / proc rune's damage or amp model.

    ``compute`` is a closure that takes the resolved-stat kwargs and returns a
    float. For ``on_proc_burst`` / ``per_attack`` it is the damage; for
    ``adaptive`` it is the per-stack adaptive-force value; for ``stacking_amp``
    it returns 0.0 (the amp lives in :func:`keystone_amp`, not the burst path).

    ``amp_mult`` is the flat multiplier a ``stacking_amp`` rune applies to
    inbound damage (1.0 = no amp). Non-amp runes leave it at 1.0.
    """

    rune_id: int
    name: str
    tree: str
    proc_type: str
    cooldown_s: float
    formula: str
    compute: Callable[..., float] = field(
        default=lambda **_kw: 0.0, compare=False, repr=False
    )
    amp_mult: float = 1.0


# ---------------------------------------------------------------------------
# Per-rune compute closures.
# Each takes (level, ad, ap, bonus_hp, target_max_hp, mode) via **kw and
# returns a float. They read only the kwargs they need; extras are ignored.
# ---------------------------------------------------------------------------

def _electrocute(*, level=1.0, ad=0.0, ap=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "70 - 240 (+0.1 bonus AD, +0.05 AP)" adaptive.
    # (Brief said 30-180 + 0.40 bAD + 0.25 AP - STALE; DDragon wins.)
    base = _lerp_by_level(70.0, 240.0, level)
    return base + _adaptive_coeff(ad, ap, 0.10, 0.05)


def _dark_harvest(*, ad=0.0, ap=0.0, souls=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "30 (+11 damage per soul) (+0.1 bonus AD)
    # (+0.05 AP)" on a champion below 50% health. (Brief said 20 + 5*souls +
    # 0.25 bAD + 0.15 AP - STALE; DDragon wins.) souls is an optional stack
    # count surfaced via the kwargs (default 0).
    return 30.0 + 11.0 * _f(souls) + _adaptive_coeff(ad, ap, 0.10, 0.05)


def _arcane_comet(*, level=1.0, ad=0.0, ap=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "15 - 100 based on level (+0.05 AP and +0.1
    # bonus AD)" adaptive. (Brief said 30-100 + 0.35 AP + 0.20 bAD - STALE;
    # DDragon wins.)
    base = _lerp_by_level(15.0, 100.0, level)
    return base + _adaptive_coeff(ad, ap, 0.10, 0.05)


def _sudden_impact(*, level=1.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "bonus 20 - 80 True Damage based on level".
    # (Brief said magic 0.20 bAD + 0.15 AP - STALE; the current rune is a flat
    # level-scaled TRUE-damage proc, no AD/AP scaling. DDragon wins.)
    return _lerp_by_level(20.0, 80.0, level)


def _cheap_shot(*, level=1.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "10 - 45 bonus true damage (based on level)"
    # vs impaired target. (Brief said 12-40 true - close but DDragon's 10-45
    # is authoritative.)
    return _lerp_by_level(10.0, 45.0, level)


def _scorch(*, level=1.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "20 - 40 bonus magic damage based on level".
    # 10s cooldown. (Brief said 15-35 - STALE; DDragon wins.)
    return _lerp_by_level(20.0, 40.0, level)


def _press_the_attack_burst(*, level=1.0, ad=0.0, ap=0.0, **_kw) -> float:
    # Press the Attack ALSO deals a 3-hit adaptive burst on top of the amp.
    # DDragon 16.11.1 longDesc: "deals 40 - 160 bonus adaptive damage (based
    # on level)". This is the burst piece; the 8% amp is in keystone_amp.
    base = _lerp_by_level(40.0, 160.0, level)
    return base + _adaptive_coeff(ad, ap, 0.0, 0.0)


def _conqueror_adaptive(*, level=1.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "gaining 1.8-4 Adaptive Force per stack.
    # Stacks up to 12 times." Patch-16.11 behaviour: Conqueror is a STAT
    # STACK, not a flat damage amp - so keystone_amp is a no-op pass-through
    # for it (see below). compute_rune_proc_damage surfaces the PER-STACK
    # adaptive force; the caller multiplies by the live stack count (max 12).
    # (Brief said 1.8-3.0; DDragon longDesc says 1.8-4.0 - DDragon wins.)
    return _lerp_by_level(1.8, 4.0, level)


# ---------------------------------------------------------------------------
# Registry. Keyed by Riot perk id.
# ---------------------------------------------------------------------------

# Press the Attack flat damage amplifier (post 3-stack): "amplifies your
# damage dealt by 8%". DDragon 16.11.1 longDesc says a flat 8% (the brief's
# "8-12% by level" is STALE). 1.08 multiplier.
_PTA_AMP_MULT = 1.08

RUNE_PROCS: Dict[int, RuneProc] = {
    8112: RuneProc(
        rune_id=8112,
        name="Electrocute",
        tree="Domination",
        proc_type="on_proc_burst",
        cooldown_s=20.0,
        formula=(
            "70-240 by level + 0.10 bonus AD + 0.05 AP (adaptive); "
            "3 separate hits in 3s; CD 20s "
            "(DDragon 16.11.1; brief 30-180/0.40/0.25 was stale)"
        ),
        compute=_electrocute,
    ),
    8128: RuneProc(
        rune_id=8128,
        name="Dark Harvest",
        tree="Domination",
        proc_type="on_proc_burst",
        cooldown_s=35.0,
        formula=(
            "30 + 11*souls + 0.10 bonus AD + 0.05 AP (adaptive); "
            "target < 50% HP; CD 35s (resets to 1.0s on takedown) "
            "(DDragon 16.11.1; brief 20+5*souls/0.25/0.15 was stale)"
        ),
        compute=_dark_harvest,
    ),
    8229: RuneProc(
        rune_id=8229,
        name="Arcane Comet",
        tree="Sorcery",
        proc_type="on_proc_burst",
        cooldown_s=20.0,
        formula=(
            "15-100 by level + 0.10 bonus AD + 0.05 AP (adaptive); "
            "ability hit; CD 20-8s "
            "(DDragon 16.11.1; brief 30-100/0.35/0.20 was stale)"
        ),
        compute=_arcane_comet,
    ),
    8143: RuneProc(
        rune_id=8143,
        name="Sudden Impact",
        tree="Domination",
        proc_type="on_proc_burst",
        cooldown_s=10.0,
        formula=(
            "20-80 TRUE damage by level after dash/blink/stealth; CD 10s "
            "(DDragon 16.11.1; brief 0.20 bAD + 0.15 AP magic was stale - "
            "current rune is flat level-scaled true damage, no AD/AP)"
        ),
        compute=_sudden_impact,
    ),
    8126: RuneProc(
        rune_id=8126,
        name="Cheap Shot",
        tree="Domination",
        proc_type="on_proc_burst",
        cooldown_s=4.0,
        formula=(
            "10-45 TRUE damage by level vs impaired target; CD 4s "
            "(DDragon 16.11.1; brief said 12-40)"
        ),
        compute=_cheap_shot,
    ),
    8237: RuneProc(
        rune_id=8237,
        name="Scorch",
        tree="Sorcery",
        proc_type="on_proc_burst",
        cooldown_s=10.0,
        formula=(
            "20-40 magic damage by level on next ability hit (after 1s); "
            "CD 10s (DDragon 16.11.1; brief said 15-35)"
        ),
        compute=_scorch,
    ),
    8005: RuneProc(
        rune_id=8005,
        name="Press the Attack",
        tree="Precision",
        proc_type="stacking_amp",
        cooldown_s=0.0,
        formula=(
            "after 3 consecutive basic attacks: 40-160 adaptive burst by "
            "level AND amplify all damage dealt by 8% (flat). keystone_amp "
            "applies the 1.08 multiplier; compute returns the burst piece "
            "(DDragon 16.11.1; brief 8-12%-by-level amp was stale - it is "
            "flat 8%)"
        ),
        compute=_press_the_attack_burst,
        amp_mult=_PTA_AMP_MULT,
    ),
    8010: RuneProc(
        rune_id=8010,
        name="Conqueror",
        tree="Precision",
        proc_type="adaptive",
        cooldown_s=0.0,
        formula=(
            "1.8-4.0 Adaptive Force PER STACK by level, up to 12 stacks; "
            "at max heal 8% (5% ranged) of damage dealt. Patch 16.11: this "
            "is a STAT STACK not a damage amp, so keystone_amp is a no-op "
            "pass-through for Conqueror. compute returns the per-stack "
            "adaptive value; caller multiplies by live stack count (max 12) "
            "(DDragon 16.11.1; brief 1.8-3.0 was stale - it is 1.8-4.0)"
        ),
        compute=_conqueror_adaptive,
    ),
}


# ---------------------------------------------------------------------------
# Public functions.
# ---------------------------------------------------------------------------

def compute_rune_proc_damage(
    rune_id: int,
    level: float,
    ad: float = 0.0,
    ap: float = 0.0,
    bonus_hp: float = 0.0,
    target_max_hp: float = 0.0,
    mode: str = "SR",
    **extra,
) -> float:
    """Compute a rune's per-proc damage (or per-stack adaptive value).

    Fail-soft: an unknown ``rune_id`` returns 0.0; a compute error returns 0.0.
    ``extra`` carries optional per-rune kwargs (e.g. ``souls`` for Dark
    Harvest) without breaking the fixed signature.

    For ``stacking_amp`` runes this returns the on-proc burst piece (Press the
    Attack's 40-160 adaptive hit); the 8% multiplier is via :func:`keystone_amp`.
    For ``adaptive`` runes (Conqueror) this returns the PER-STACK adaptive
    force; the caller multiplies by the live stack count.
    """
    proc = RUNE_PROCS.get(rune_id)
    if proc is None:
        return 0.0
    try:
        return float(
            proc.compute(
                level=level,
                ad=ad,
                ap=ap,
                bonus_hp=bonus_hp,
                target_max_hp=target_max_hp,
                mode=mode,
                **extra,
            )
        )
    except Exception:
        # Fail-soft: never raise from the public surface.
        return 0.0


def keystone_amp(
    rune_id: int,
    base_damage: float,
    *,
    stacks: Optional[int] = None,
) -> float:
    """Apply a flat-damage keystone AMPLIFIER to ``base_damage``.

    For Press the Attack (8005, ``stacking_amp``) this multiplies by 1.08
    (the flat 8% amp once the 3-stack proc is active). For Conqueror (8010)
    this is a deliberate NO-OP pass-through: on patch 16.11 Conqueror is a
    stat stack, not a damage amp (its per-stack adaptive force is surfaced via
    :func:`compute_rune_proc_damage`).

    Unknown rune ids and non-amp runes return ``base_damage`` unchanged.
    ``stacks`` is accepted for forward compatibility (a future per-stack amp
    rune) but is unused for the current registry. Fail-soft.
    """
    try:
        base = float(base_damage)
    except (TypeError, ValueError):
        return 0.0
    proc = RUNE_PROCS.get(rune_id)
    if proc is None:
        return base
    if proc.proc_type != "stacking_amp":
        return base
    try:
        return base * float(proc.amp_mult)
    except (TypeError, ValueError):
        return base
