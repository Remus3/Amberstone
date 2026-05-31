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
ASCII only. ``__all__`` exports the public surface. This registry IS consumed
by ``burst.py`` and ``combo.py`` (DS V2 S3, ENGINE 1.65.0): they fold
``compute_rune_proc_damage`` + ``keystone_amp`` into the damage total when a
rune set is passed. Registry expansions therefore DO bump ENGINE.
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
# S4 expansion (8 -> 14): six net-new runes, every coefficient verbatim from
# the live DDragon 16.11.1 runesReforged.json longDesc.
# ---------------------------------------------------------------------------

def _summon_aery(*, level=1.0, ad=0.0, ap=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "dealing 10 - 50 based on level (+0.05 AP)
    # (+0.1 bonus AD)" adaptive. This is the DAMAGE layer only - the shield
    # side of Aery (20-100 + same scaling) is NOT modeled here (a shield is
    # mitigation, not burst). Adaptive tiebreak goes to AD.
    base = _lerp_by_level(10.0, 50.0, level)
    return base + _adaptive_coeff(ad, ap, 0.10, 0.05)


def _grasp(*, caster_max_hp=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "Deal bonus magic damage equal to 3.5% of
    # your max health" (Ranged: 40% effective). This scales on CASTER max
    # health, which is NOT a fixed signature kwarg - read it from **extra via
    # caster_max_hp. The melee 100%-effective value is modeled; pass
    # caster_max_hp via extra. Ranged 40%-effective scaling is the caller's
    # responsibility (not applied here - no role flag in the proc signature).
    return 0.035 * _f(caster_max_hp)


def _aftershock(*, level=1.0, bonus_hp=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "Damage: 25 - 120 (+8% of your bonus health)".
    # Level-scaled magic burst after immobilizing an enemy champion.
    return _lerp_by_level(25.0, 120.0, level) + 0.08 * _f(bonus_hp)


# ---------------------------------------------------------------------------
# per_attack expansion (item-229-NEXT(3)): the two per-AA damage runes. These
# add damage to EACH auto-attack (proc_type "per_attack"), so the closure
# returns the SINGLE-AA contribution; any per-window stack multiplier (Hail of
# Blades' "up to 3 attacks") is the caller's concern, NOT multiplied here.
# Every coefficient is verbatim from the live DDragon 16.11.1 runesReforged.json
# longDesc (data/meta_build/ddragon/16.11.1/runesReforged.json); DDragon wins.
# ---------------------------------------------------------------------------

def _hail_of_blades(*, level=1.0, ad=0.0, ap=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "On-Hit Damage: 4 - 20 (+0.08 bonus AD, +0.06 AP)
    # damage" as TRUE damage, up to 3 attacks, CD 10s. This is ADDITIVE (BOTH
    # 0.08 bonus AD AND 0.06 AP per the "+0.08 bonus AD, +0.06 AP" wording) -
    # NOT adaptive. Returns the per-AA (single-attack) contribution; the "up to
    # 3 attacks" multiplier is the caller's concern (do NOT multiply by 3 here).
    return _lerp_by_level(4.0, 20.0, level) + 0.08 * _f(ad) + 0.06 * _f(ap)


def _lethal_tempo(*, level=1.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "At max stacks, deal [9 - 30 Melee || 6 - 24
    # Ranged] bonus adaptive damage On-Attack, increased by 1% per 1% Bonus
    # Attack Speed." The 9-30 melee value is a flat adaptive-TYPED by-level
    # number with NO stated bAD/AP coefficient, so NO stat scaling is applied.
    # We model the MELEE 100%-effective max-stack value (mirrors the existing
    # Grasp melee-100%-modeled precedent in this file). The ranged 6-24 value
    # AND the "+1% per 1% bonus AS" amp are NOT applied here (no role flag /
    # no bonus-AS in the proc signature).
    return _lerp_by_level(9.0, 30.0, level)


# ---------------------------------------------------------------------------
# Registry. Keyed by Riot perk id.
# ---------------------------------------------------------------------------

# Honest exclusion (NOT in RUNE_PROCS): Fleet Footwork 8021 (Precision).
# DDragon 16.11.1 longDesc: "Energized attacks heal you for 10 - 130 (+0.1
# Bonus AD, +0.05 AP) and grant 20% Move Speed for 1s." It is a HEAL + MOVE
# SPEED sustain keystone with NO damage component - modeling it as a damage
# rune would invent numbers that do not exist. Same data-availability-ceiling
# discipline as the Summon Aery shield side (mitigation, not burst) and the
# Grasp heal side (heal + permanent-HP not modeled): we only register the
# DAMAGE a rune deals. Do NOT add 8021 to RUNE_PROCS as a burst rune.

# ---------------------------------------------------------------------------
# Honest exclusions (NOT in RUNE_PROCS) - the on-hit/per_attack-expansion dry
# well (operator NEXT "expand per_attack to other on-hit runes if DDragon
# exposes them"). A scoping pass verified the DDragon 16.11.1 well: of all 64
# runes, the 16 above are modeled, Fleet Footwork 8021 (above) is the heal+MS
# sustain exclusion, and the runes below are sustain / utility / stat-stack /
# tower-only OR caster-state / game-time gated - none is a defensible proc-
# damage entry. They are listed here so they are never re-pitched.
#
# Last Stand 8299 (Precision slot-4, the SAME mutually-exclusive slot as
# Coup de Grace 8014 + Cut Down 8017 modeled above).
# DDragon 16.11.1 longDesc: "Deal 5% - 11% increased damage to champions while
# you are below 60% health. Max damage gained at 30% health."
# EXCLUDED (the one borderline candidate). Its two slot siblings ARE modeled
# unconditionally best-case (stacking_amp 1.08x) because their gates are on the
# TARGET's hp (Cut Down >60%, Coup de Grace <40%) and a burst window routinely
# MEETS those: you open a burst on a healthy target (>60%) and the killing
# portion of the burst carries it through the execute band (<40%). Last Stand
# instead gates on the CASTER being below 60% hp (max at 30%). In a burst-MAX
# scorer the caster is the one bursting and is typically at FULL hp on the
# opener - the OPPOSITE of the gate. Applying a best-case 1.11x unconditionally
# would inflate every burst total by 11% for a caster-state (<=30% hp while
# bursting) the scorer almost never represents. The caster-state gate is not
# expressible / not defensible in the unconditional best-case proc model, so
# Last Stand is an honest exclusion rather than a misleading 1.11x amp. Do NOT
# add 8299 to RUNE_PROCS.
#
# Absolute Focus 8233 (Sorcery). DDragon 16.11.1 longDesc: "While above 70%
# health, gain an adaptive bonus of up to 18 Attack Damage or 30 Ability Power
# (based on level)." This is a caster-hp-gated STAT GRANT, not proc damage -
# the same class as the Eyeball / Legend stat runes this module never models
# (RUNE_PROCS registers damage a rune deals, not stat sticks; Conqueror is the
# lone adaptive STAT entry and it is EXCLUDED from the burst total). Do NOT add
# 8233 to RUNE_PROCS.
#
# Gathering Storm 8236 (Sorcery). DDragon 16.11.1 longDesc: "Every 10 min gain
# AP or AD, adaptive. 10 min: +8 AP or 5 AD ... 60 min: +168 AP or 101 AD."
# A game-time-gated adaptive STAT GRANT (not proc damage, and the value depends
# on elapsed game time which is not in the proc signature). Same stat-grant
# exclusion class as Absolute Focus. Do NOT add 8236 to RUNE_PROCS.
#
# Taste of Blood 8139 (Domination) + Demolish 8446 (Resolve) are likewise NOT
# proc-damage entries: 8139 longDesc "Heal when you damage an enemy champion"
# is the Grasp/Aery-shield heal-side exclusion class (sustain, not burst), and
# 8446 longDesc "Your third attack against towers deals ... bonus physical
# damage" is TOWER-ONLY damage (no champion damage to score). Do NOT add either.

# Press the Attack flat damage amplifier (post 3-stack): "amplifies your
# damage dealt by 8%". DDragon 16.11.1 longDesc says a flat 8% (the brief's
# "8-12% by level" is STALE). 1.08 multiplier.
_PTA_AMP_MULT = 1.08

# S4 amp multipliers (DDragon 16.11.1):
#   First Strike 8369 = 7% extra true damage -> 1.07.
#   Coup de Grace 8014 = 8% more damage (target < 40% HP) -> 1.08.
#   Cut Down 8017 = 8% more damage (target > 60% HP) -> 1.08.
# All three flow through keystone_amp generically (base * amp_mult); no
# keystone_amp change is needed.
_FIRST_STRIKE_AMP_MULT = 1.07
_COUP_DE_GRACE_AMP_MULT = 1.08
_CUT_DOWN_AMP_MULT = 1.08

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
    # --- S4 expansion (8 -> 14) ---
    8214: RuneProc(
        rune_id=8214,
        name="Summon Aery",
        tree="Sorcery",
        proc_type="on_proc_burst",
        cooldown_s=2.0,
        formula=(
            "10-50 by level + 0.10 bonus AD + 0.05 AP (adaptive) on damage; "
            "Aery returns to you before re-firing (~2s effective). DAMAGE "
            "layer only - the shield side (20-100 + same scaling) is NOT "
            "modeled (mitigation, not burst) (DDragon 16.11.1)"
        ),
        compute=_summon_aery,
    ),
    8437: RuneProc(
        rune_id=8437,
        name="Grasp of the Undying",
        tree="Resolve",
        proc_type="on_proc_burst",
        cooldown_s=4.0,
        formula=(
            "3.5% caster max health magic damage on the empowered AA; "
            "ranged 40% effective (melee 100% modeled); pass caster_max_hp "
            "via extra (heal + permanent-HP sides not modeled) "
            "(DDragon 16.11.1)"
        ),
        compute=_grasp,
    ),
    8439: RuneProc(
        rune_id=8439,
        name="Aftershock",
        tree="Resolve",
        proc_type="on_proc_burst",
        cooldown_s=20.0,
        formula=(
            "25-120 by level + 0.08 bonus health magic burst after "
            "immobilizing an enemy champion; CD 20s "
            "(resist-bonus side not modeled) (DDragon 16.11.1)"
        ),
        compute=_aftershock,
    ),
    8369: RuneProc(
        rune_id=8369,
        name="First Strike",
        tree="Inspiration",
        proc_type="stacking_amp",
        cooldown_s=25.0,
        formula=(
            "7% extra TRUE damage vs champions for 3s; CD 25-15s. keystone_amp "
            "applies the 1.07 multiplier; compute returns 0.0 (pure amp, no "
            "burst piece). Gold-on-hit (50%/35% ranged of bonus damage) is "
            "NOT damage so not modeled (DDragon 16.11.1)"
        ),
        compute=lambda **_kw: 0.0,
        amp_mult=_FIRST_STRIKE_AMP_MULT,
    ),
    # DDragon 16.11.1 id crossing: the WAKEUP brief said "Coup de Grace 8299 /
    # Cut Down 8014" which CROSSED the ids. Live runesReforged.json is
    # authoritative: 8299 = Last Stand, 8014 = Coup de Grace, 8017 = Cut Down.
    # The two amp runes below use the DDragon-correct ids.
    8014: RuneProc(
        rune_id=8014,
        name="Coup de Grace",
        tree="Precision",
        proc_type="stacking_amp",
        cooldown_s=0.0,
        formula=(
            "8% more damage to champions below 40% health (execute amp). "
            "Modeled as a flat 1.08 amp; the <40% HP condition is a caller "
            "gate not applied here. keystone_amp applies 1.08; compute "
            "returns 0.0 (DDragon 16.11.1; brief crossed id with Cut Down - "
            "8014 IS Coup de Grace)"
        ),
        compute=lambda **_kw: 0.0,
        amp_mult=_COUP_DE_GRACE_AMP_MULT,
    ),
    8017: RuneProc(
        rune_id=8017,
        name="Cut Down",
        tree="Precision",
        proc_type="stacking_amp",
        cooldown_s=0.0,
        formula=(
            "8% more damage to champions above 60% health. Modeled as a flat "
            "1.08 amp; the >60% HP condition is a caller gate not applied "
            "here. keystone_amp applies 1.08; compute returns 0.0 "
            "(DDragon 16.11.1; brief crossed id - 8017 IS Cut Down)"
        ),
        compute=lambda **_kw: 0.0,
        amp_mult=_CUT_DOWN_AMP_MULT,
    ),
    # --- per_attack expansion (item-229-NEXT(3)) ---
    9923: RuneProc(
        rune_id=9923,
        name="Hail of Blades",
        tree="Domination",
        proc_type="per_attack",
        cooldown_s=10.0,
        formula=(
            "per-AA TRUE damage 4-20 by level + 0.08 bonus AD + 0.06 AP "
            "(ADDITIVE, not adaptive); up to 3 attacks per proc, CD 10s. "
            "compute returns the SINGLE-AA contribution; the 3-attack window "
            "multiplier is the caller's concern (DDragon 16.11.1)"
        ),
        compute=_hail_of_blades,
    ),
    8008: RuneProc(
        rune_id=8008,
        name="Lethal Tempo",
        tree="Precision",
        proc_type="per_attack",
        cooldown_s=0.0,
        formula=(
            "at max stacks (6) deal 9-30 by level bonus adaptive on-attack "
            "(MELEE 100%-effective modeled, no stat coeff stated). Ranged "
            "6-24 value + the '+1% per 1% bonus AS' amp NOT applied (no role "
            "flag / no bonus-AS in the proc signature); stacking AS buff has "
            "no cooldown (DDragon 16.11.1)"
        ),
        compute=_lethal_tempo,
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
