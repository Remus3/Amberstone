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
    "COMPLETION_RUNE_IDS",
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

    ``condition`` is the gating tag (item 232 proc-signature lift). Default
    "unconditional" keeps every pre-lift rune byte-identical. Tags:
    "unconditional" | "caster_hp_below" | "caster_hp_above" | "target_hp_below"
    | "target_hp_above" | "game_time" | "per_attack" | "shield_gated" (DSP4 -
    Shield Bash, procs on the empowered AA after gaining a shield). A gated
    rune's closure /
    amp consumes the gating-context kwargs (caster_hp_pct / game_time_s / role /
    bonus_as) threaded through ``**extra``; at the DEFAULT context every gate
    yields the no-contribution value (amp 1.0 / 0.0 burst), so a default-context
    caller sees byte-identical behaviour to the pre-lift exclusion.
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
    condition: str = "unconditional"


# ---------------------------------------------------------------------------
# Per-rune compute closures.
# Each takes (level, ad, ap, bonus_hp, target_max_hp, mode) via **kw and
# returns a float. They read only the kwargs they need; extras are ignored.
# Item 232 lift: the gating context (caster_hp_pct / game_time_s / role /
# bonus_as) is ALSO threaded via the same **kw. Closures that ignore those
# kwargs (via **_kw) are unaffected -> byte-identical at the default context.
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

def _hail_of_blades(*, level=1.0, ad=0.0, ap=0.0, role="melee", **_kw) -> float:
    # DDragon 16.11.1 longDesc: "On-Hit Damage: 4 - 20 (+0.08 bonus AD, +0.06 AP)
    # damage" as TRUE damage, up to 3 attacks, CD 10s. This is ADDITIVE (BOTH
    # 0.08 bonus AD AND 0.06 AP per the "+0.08 bonus AD, +0.06 AP" wording) -
    # NOT adaptive. Returns the per-AA (single-attack) contribution; the "up to
    # 3 attacks" multiplier is the caller's concern (do NOT multiply by 3 here).
    # Item 232: role accepted for signature parity with Lethal Tempo, but Hail
    # of Blades' On-Hit Damage does NOT vary by role (DDragon gives one number,
    # not a melee||ranged split), so role is unused and the melee default value
    # is byte-identical.
    return _lerp_by_level(4.0, 20.0, level) + 0.08 * _f(ad) + 0.06 * _f(ap)


def _lethal_tempo(*, level=1.0, role="melee", bonus_as=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "Attacking an enemy champion grants you [6%
    # Melee || 4% Ranged] Attack Speed for 6 seconds, up to 6. At max stacks,
    # deal [9 - 30 Melee || 6 - 24 Ranged] bonus adaptive damage On-Attack,
    # increased by 1% per 1% Bonus Attack Speed." Item 232 lift: role picks the
    # melee (9-30) vs ranged (6-24) by-level base; bonus_as applies the
    # "+1% per 1% bonus AS" amp via result *= (1.0 + bonus_as) (bonus_as is a
    # fraction, e.g. 0.50 = +50% bonus AS -> 1.5x). DEFAULTS role="melee" +
    # bonus_as=0.0 -> 9-30 melee with no amp = BYTE-IDENTICAL to the pre-lift
    # value. No stated bAD/AP coefficient so NO stat scaling is applied.
    base = _lerp_by_level(6.0, 24.0, level) if str(role) == "ranged" else _lerp_by_level(9.0, 30.0, level)
    return base * (1.0 + _f(bonus_as))


# ---------------------------------------------------------------------------
# Item 232 proc-signature lift: the 3 previously-EXCLUDED gated runes, now
# EXPRESSIBLE with HONEST gates that yield byte-identical defaults.
# ---------------------------------------------------------------------------

# Last Stand 8299 honest-gate parameters (DDragon 16.11.1 longDesc verbatim:
# "Deal 5% - 11% increased damage to champions while you are below 60% health.
# Max damage gained at 30% health."). Named so the gate is tunable in one place.
_LAST_STAND_HP_HIGH = 0.60   # at/above this caster hp fraction -> no amp (1.0)
_LAST_STAND_HP_LOW = 0.30    # at/below this -> max amp
_LAST_STAND_AMP_MIN = 1.05   # amp just under the high threshold
_LAST_STAND_AMP_MAX = 1.11   # amp at/below the low threshold


def _last_stand_amp(*, caster_hp_pct=1.0) -> float:
    # HONEST GATE: amp = 1.0 at caster_hp_pct >= _LAST_STAND_HP_HIGH (no amp);
    # ramps linearly _LAST_STAND_AMP_MIN -> _LAST_STAND_AMP_MAX as hp goes HIGH
    # -> LOW; capped at MAX below LOW. Returned by keystone_amp, NOT compute
    # (8299 is a stacking_amp). At the DEFAULT caster_hp_pct=1.0 -> amp 1.0 ->
    # base unchanged -> BYTE-IDENTICAL to the item-231 exclusion (a burst-MAX
    # caller at full HP sees NO change).
    hp = _f(caster_hp_pct)
    if hp >= _LAST_STAND_HP_HIGH:
        return 1.0
    if hp <= _LAST_STAND_HP_LOW:
        return _LAST_STAND_AMP_MAX
    span = _LAST_STAND_HP_HIGH - _LAST_STAND_HP_LOW
    frac = (_LAST_STAND_HP_HIGH - hp) / span
    return _LAST_STAND_AMP_MIN + (_LAST_STAND_AMP_MAX - _LAST_STAND_AMP_MIN) * frac


def _adaptive_grant(ad: float, ap: float, ad_val: float, ap_val: float) -> float:
    # Pick the flat adaptive STAT-GRANT value by the standard adaptive rule:
    # AD-side value when bonus AD >= bonus AP (AD wins ties, League default),
    # else AP-side value. Unlike :func:`_adaptive_coeff` (a stat-SCALED proc
    # coefficient), this returns the grant value DIRECTLY (no stat multiply).
    return ad_val if _f(ad) >= _f(ap) else ap_val


def _absolute_focus(*, level=1.0, ad=0.0, ap=0.0, caster_hp_pct=1.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "While above 70% health, gain an adaptive bonus
    # of up to 18 Attack Damage or 30 Ability Power (based on level). Grants
    # 1.8 Attack Damage or 3 Ability Power at level 1." This is a caster-hp-gated
    # adaptive STAT GRANT, not proc damage - so like Conqueror it is proc_type
    # "adaptive" and the BURST CONSUMER SKIPS proc_type=="adaptive" (it does NOT
    # enter the burst total). At the DEFAULT caster_hp_pct=1.0 (>0.70) compute
    # returns the grant value (1.8->18 AD / 3->30 AP adaptive by level, AD-side
    # on the default ad>=ap tie) but since burst SKIPS adaptive the burst is
    # BYTE-IDENTICAL; a fight_report may surface the stat. caster_hp_pct <= 0.70
    # -> 0.0 (gate fails).
    if _f(caster_hp_pct) <= 0.70:
        return 0.0
    return _adaptive_grant(ad, ap, _lerp_by_level(1.8, 18.0, level), _lerp_by_level(3.0, 30.0, level))


def _gathering_storm(*, ad=0.0, ap=0.0, game_time_s=0.0, **_kw) -> float:
    # DDragon 16.11.1 longDesc: "Every 10 min gain AP or AD, adaptive. 10 min:
    # +8 AP or 5 AD  20 min: +24 AP or 14 AD  30 min: +48 AP or 29 AD  40 min:
    # +80 AP or 48 AD  50 min: +120 AP or 72 AD  60 min: +168 AP or 101 AD."
    # A game-time-gated adaptive STAT GRANT (not proc damage). proc_type
    # "adaptive" -> the BURST CONSUMER SKIPS it (does NOT enter the burst total)
    # -> burst BYTE-IDENTICAL. Modeled as the AD-side 5-per-10-min / AP-side
    # 8-per-10-min linear ramp (game_time_s / 600.0 * milestone); the longDesc
    # accelerates at later milestones but the 10-min cadence anchor is the
    # honest first-order ramp. At the DEFAULT game_time_s=0.0 -> 0.0 (a burst
    # scorer at t=0 has the rune contribute nothing, matching the exclusion).
    # game_time_s=600 (10 min) -> 5 AD (AD-side); game_time_s=1800 (30 min) ->
    # 15 AD. AD-side on the default ad>=ap tie.
    t = _f(game_time_s)
    if t <= 0.0:
        return 0.0
    return _adaptive_grant(ad, ap, 5.0 * (t / 600.0), 8.0 * (t / 600.0))


# ---------------------------------------------------------------------------
# DSP4 self-rune completion seam (8401 Shield Bash). The ONE remaining LIVE,
# pickable rune that deals direct champion proc damage and was unmodeled.
# ---------------------------------------------------------------------------

def _shield_bash(*, level=1.0, bonus_hp=0.0, shield_amount=0.0, **_kw) -> float:
    # DDragon 16.12.1 longDesc: "Whenever you gain a new shield, your next basic
    # attack against a champion deals 5 - 30 (+2.5% Bonus Health) (+15.0% New
    # Shield Amount) bonus adaptive damage." "adaptive" is the damage TYPE
    # (physical when bonus AD >= bonus AP else magic), NOT a stat-scaled
    # coefficient - the scaling sources are bonus HEALTH + the new SHIELD
    # AMOUNT, so there is NO AD/AP coefficient. shield_amount is a NEW optional
    # kwarg (default 0.0 = the shield-independent floor); the burst scorer has
    # no live shield signal and passes 0.0, scoring the 5-30 + 2.5% bonus HP
    # floor (best-case-shielded approximation - a Resolve-tree carrier in a
    # fight nearly always holds a shield). A future live caster-stat producer
    # supplies the shield amount for the +15% term. 16.12.1 == 16.11.1 for this
    # rune (identical longDesc both patches).
    return (
        _lerp_by_level(5.0, 30.0, level)
        + 0.025 * _f(bonus_hp)
        + 0.15 * _f(shield_amount)
    )


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
# Conditionally modeled (honest gate, byte-identical default) - item 232
# proc-signature lift. These 3 runes WERE honest exclusions (item 231) because
# the unconditional best-case proc model could not express their gates without
# inflating the burst-MAX scorer. The item 232 lift makes the gate EXPRESSIBLE:
# each rune carries a `condition` tag + reads the gating-context kwargs, and
# the DEFAULT context (caster_hp_pct=1.0 / game_time_s=0.0) yields the SAME
# no-contribution value the exclusion produced. The item-231 REASONING was
# correct (unconditional best-case inflates); the lift does NOT contradict it -
# it computes correctly ONLY when a caller supplies the gating context.
#
# Last Stand 8299 (Precision slot-4, the SAME mutually-exclusive slot as
# Coup de Grace 8014 + Cut Down 8017). DDragon 16.11.1 longDesc: "Deal 5% - 11%
# increased damage to champions while you are below 60% health. Max damage
# gained at 30% health." Its two slot siblings (Cut Down >60%, Coup de Grace
# <40%) gate on the TARGET's hp and a burst window routinely MEETS those, so
# they are modeled unconditionally best-case (stacking_amp 1.08x). Last Stand
# gates on the CASTER being below 60% hp (max at 30%) - in a burst-MAX scorer
# the caster is typically at FULL hp on the opener, the OPPOSITE of the gate.
# Item 232: NOW MODELED as condition="caster_hp_below" stacking_amp; keystone_amp
# returns base * _last_stand_amp(caster_hp_pct=) = 1.0 at the default full HP
# (byte-identical - NO inflation) and 1.05->1.11 when a caller supplies a low
# caster_hp_pct. Item-231's anti-inflation concern is HONORED by the default.
#
# Absolute Focus 8233 (Sorcery). DDragon 16.11.1 longDesc: "While above 70%
# health, gain an adaptive bonus of up to 18 Attack Damage or 30 Ability Power
# (based on level)." A caster-hp-gated adaptive STAT GRANT, not proc damage -
# same class as Conqueror (the lone other adaptive STAT entry). Item 232: NOW
# MODELED as condition="caster_hp_above" proc_type="adaptive"; compute returns
# the grant (1.8->18 AD / 3->30 AP) when caster_hp_pct>0.70 else 0.0. Because
# the burst consumer SKIPS proc_type=="adaptive", the grant does NOT enter the
# burst total -> burst is BYTE-IDENTICAL even at the default full HP. A
# fight_report may surface the stat.
#
# Gathering Storm 8236 (Sorcery). DDragon 16.11.1 longDesc: "Every 10 min gain
# AP or AD, adaptive. 10 min: +8 AP or 5 AD ... 60 min: +168 AP or 101 AD."
# A game-time-gated adaptive STAT GRANT (not proc damage). Item 232: NOW MODELED
# as condition="game_time" proc_type="adaptive"; compute returns the time-scaled
# grant (0.0 at game_time_s=0, >0 thereafter). Burst SKIPS adaptive -> burst is
# BYTE-IDENTICAL. A fight_report may surface the stat.
#
# ---------------------------------------------------------------------------
# Honest exclusions (NOT in RUNE_PROCS) - truly out of scope (heal / tower, not
# champion proc damage). They are listed here so they are never re-pitched as
# proc-damage entries.
#
# Taste of Blood 8139 (Domination) + Demolish 8446 (Resolve) are NOT proc-damage
# entries: 8139 longDesc "Heal when you damage an enemy champion" is the
# Grasp/Aery-shield heal-side exclusion class (sustain, not burst), and 8446
# longDesc "Your third attack against towers deals ... bonus physical damage"
# is TOWER-ONLY damage (no champion damage to score). Do NOT add either.

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

# R51 (ENGINE 1.163.0) target_hp gate thresholds. Verbatim from live DDragon
# 16.13.1 runesReforged.json longDesc:
#   Cut Down 8017      -> "more than 60% health"  (strict >; target_hp_above)
#   Coup de Grace 8014 -> "less than 40% health"  (strict <; target_hp_below)
# Consumed ONLY when keystone_amp is called with gate_target_hp=True (the
# DEFAULT-OFF R51 seam); at the default the amp stays unconditional so every
# pre-R51 caller is byte-identical (burst-window approximation preserved).
_CUT_DOWN_HP_GATE = 0.60
_COUP_DE_GRACE_HP_GATE = 0.40

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
        condition="target_hp_below",
        formula=(
            "8% more damage to champions below 40% health (execute amp). "
            "condition='target_hp_below' is METADATA: the burst-MAX scorer "
            "applies the 1.08 amp UNCONDITIONALLY (item 232/233 burst-window "
            "approximation - a burst opens >60% and the killing portion carries "
            "the target through the <40% execute band, so the amp is met within "
            "the window; gating by a single target_hp_pct snapshot would be LESS "
            "accurate for a burst). A future per-instant scenario eval can read "
            "the tag + target_hp_pct to gate. keystone_amp applies 1.08 flat; "
            "compute returns 0.0 (DDragon 16.11.1; brief crossed id with Cut "
            "Down - 8014 IS Coup de Grace)"
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
        condition="target_hp_above",
        formula=(
            "8% more damage to champions above 60% health. condition="
            "'target_hp_above' is METADATA: the burst-MAX scorer applies the "
            "1.08 amp UNCONDITIONALLY (burst-window approximation, mirror of "
            "Coup de Grace 8014; the burst opener meets the >60% gate). A future "
            "per-instant scenario eval can gate via target_hp_pct. keystone_amp "
            "applies 1.08 flat; compute returns 0.0 (DDragon 16.11.1; brief "
            "crossed id - 8017 IS Cut Down)"
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
            "Attacking an enemy champion grants you [6% Melee || 4% Ranged] "
            "Attack Speed for 6 seconds, up to 6. At max stacks, deal "
            "[9 - 30 Melee || 6 - 24 Ranged] bonus adaptive damage On-Attack, "
            "increased by 1% per 1% Bonus Attack Speed. Item 232: role picks "
            "melee 9-30 (default, byte-identical) vs ranged 6-24; bonus_as "
            "applies *= (1.0 + bonus_as). Defaults role=melee + bonus_as=0 -> "
            "byte-identical to pre-lift. Stacking AS buff has no cooldown "
            "(DDragon 16.11.1)"
        ),
        compute=_lethal_tempo,
        condition="per_attack",
    ),
    # --- item 232 proc-signature lift: 3 conditionally-modeled gated runes ---
    # All three default to ZERO contribution at the default full-HP / time-0
    # context (matching the item-231 exclusion), but compute correctly when a
    # caller supplies the gating context.
    8299: RuneProc(
        rune_id=8299,
        name="Last Stand",
        tree="Precision",
        proc_type="stacking_amp",
        cooldown_s=0.0,
        formula=(
            "Deal 5% - 11% increased damage to champions while you are below "
            "60% health. Max damage gained at 30% health. Item 232 HONEST "
            "GATE (caster_hp_below): keystone_amp(8299, base, caster_hp_pct=) "
            "returns base*amp where amp=1.0 at hp>=0.60 (no amp), ramps 1.05 "
            "-> 1.11 linearly as hp 0.60 -> 0.30, capped 1.11 below 0.30. At "
            "the DEFAULT caster_hp_pct=1.0 -> amp 1.0 -> BYTE-IDENTICAL to the "
            "item-231 exclusion (a burst-MAX caller at full HP sees NO change). "
            "amp_mult left 1.0 - the amp is caster-hp-dependent, computed in "
            "keystone_amp via _last_stand_amp, NOT a flat multiplier "
            "(DDragon 16.11.1)"
        ),
        compute=lambda **_kw: 0.0,
        condition="caster_hp_below",
    ),
    8233: RuneProc(
        rune_id=8233,
        name="Absolute Focus",
        tree="Sorcery",
        proc_type="adaptive",
        cooldown_s=0.0,
        formula=(
            "While above 70% health, gain an adaptive bonus of up to 18 Attack "
            "Damage or 30 Ability Power (based on level). Grants 1.8 Attack "
            "Damage or 3 Ability Power at level 1. Item 232: caster-hp-gated "
            "adaptive STAT GRANT (caster_hp_above), NOT proc damage. proc_type "
            "adaptive -> burst consumer SKIPS it -> burst BYTE-IDENTICAL even "
            "at the default caster_hp_pct=1.0 (>0.70) where compute returns the "
            "1.8->18 AD / 3->30 AP grant. compute returns 0.0 at hp<=0.70 "
            "(gate fails). A fight_report may surface the stat (DDragon 16.11.1)"
        ),
        compute=_absolute_focus,
        condition="caster_hp_above",
    ),
    8236: RuneProc(
        rune_id=8236,
        name="Gathering Storm",
        tree="Sorcery",
        proc_type="adaptive",
        cooldown_s=0.0,
        formula=(
            "Every 10 min gain AP or AD, adaptive. 10 min: +8 AP or 5 AD  "
            "20 min: +24 AP or 14 AD  30 min: +48 AP or 29 AD  40 min: +80 AP "
            "or 48 AD  50 min: +120 AP or 72 AD  60 min: +168 AP or 101 AD. "
            "Item 232: game-time-gated adaptive STAT GRANT (game_time), NOT "
            "proc damage. proc_type adaptive -> burst consumer SKIPS it -> "
            "burst BYTE-IDENTICAL. compute returns the AD-side 5-per-10-min / "
            "AP-side 8-per-10-min ramp scaled by game_time_s; 0.0 at the "
            "DEFAULT game_time_s=0.0, >0 at game_time_s>0 (DDragon 16.11.1)"
        ),
        compute=_gathering_storm,
        condition="game_time",
    ),
    # --- DSP4 self-rune completion seam (1.130.0) ---
    8401: RuneProc(
        rune_id=8401,
        name="Shield Bash",
        tree="Resolve",
        proc_type="on_proc_burst",
        cooldown_s=0.0,
        condition="shield_gated",
        formula=(
            "Whenever you gain a new shield, your next basic attack against a "
            "champion deals 5 - 30 (+2.5% Bonus Health) (+15.0% New Shield "
            "Amount) bonus adaptive damage; up to 2s after the shield expires. "
            "adaptive = damage TYPE not a stat coefficient (scales on bonus "
            "health + shield amount, NO AD/AP). compute = 5-30 by level + "
            "0.025*bonus_hp + 0.15*shield_amount; shield_amount default 0.0 "
            "(the shield-independent floor the burst scorer reads). No fixed "
            "cooldown (gated by shield-gain events) -> cooldown_s 0.0. DEFAULT "
            "-OFF behind COMPLETION_RUNE_IDS: the burst/combo scorers SKIP it "
            "unless score_completion_runes=True (do-not-flip-blind; the live "
            "flip is operator-gated in docs/LIVE_GAME_GATED_SYNC.md) "
            "(DDragon 16.12.1; identical longDesc at 16.11.1)"
        ),
        compute=_shield_bash,
    ),
}


# DSP4 self-rune completion seam: the rune ids gated behind the explicit
# default-OFF ``score_completion_runes`` burst/combo flag. Members are in
# RUNE_PROCS (usable by fight_report / rune_wpa / direct queries) but the
# damage/amp SCORERS skip them unless the seam is flipped ON, so the live /rank
# path stays byte-identical to the pre-DSP4 engine. The pre-DSP4 runes are NOT
# in this set - they are consumed unconditionally (the item-226/229/232
# precedent). Newly completed runes that change a scorer total join here.
COMPLETION_RUNE_IDS: frozenset[int] = frozenset({8401})


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
    *,
    caster_hp_pct: float = 1.0,
    game_time_s: float = 0.0,
    role: str = "melee",
    bonus_as: float = 0.0,
    target_hp_pct: float = 1.0,
    shield_amount: float = 0.0,
    **extra,
) -> float:
    """Compute a rune's per-proc damage (or per-stack adaptive value).

    Fail-soft: an unknown ``rune_id`` returns 0.0; a compute error returns 0.0.
    ``extra`` carries optional per-rune kwargs (e.g. ``souls`` for Dark
    Harvest) without breaking the fixed signature.

    Item 232 proc-signature lift: the gating-context kwargs
    ``caster_hp_pct`` (default 1.0 = full HP), ``game_time_s`` (default 0.0),
    ``role`` (default "melee"), ``bonus_as`` (default 0.0) are threaded into the
    per-rune closure. At the DEFAULTS every gated rune yields its
    no-contribution value, so a default-context caller sees BYTE-IDENTICAL
    behaviour to the pre-lift engine for every previously-registered rune.

    For ``stacking_amp`` runes this returns the on-proc burst piece (Press the
    Attack's 40-160 adaptive hit); the multiplier is via :func:`keystone_amp`.
    For ``adaptive`` runes (Conqueror / Absolute Focus / Gathering Storm) this
    returns the PER-STACK adaptive force or the gated stat grant; the burst
    consumer SKIPS proc_type=="adaptive" so it never enters the burst total.
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
                caster_hp_pct=caster_hp_pct,
                game_time_s=game_time_s,
                role=role,
                bonus_as=bonus_as,
                target_hp_pct=target_hp_pct,
                shield_amount=shield_amount,
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
    caster_hp_pct: float = 1.0,
    game_time_s: float = 0.0,
    role: str = "melee",
    bonus_as: float = 0.0,
    target_hp_pct: float = 1.0,
    gate_target_hp: bool = False,
    gate_caster_hp: bool = False,
) -> float:
    """Apply a flat-damage keystone AMPLIFIER to ``base_damage``.

    For Press the Attack (8005, ``stacking_amp``) this multiplies by 1.08
    (the flat 8% amp once the 3-stack proc is active). For Conqueror (8010)
    this is a deliberate NO-OP pass-through: on patch 16.11 Conqueror is a
    stat stack, not a damage amp (its per-stack adaptive force is surfaced via
    :func:`compute_rune_proc_damage`).

    Item 232 proc-signature lift: the gating-context kwargs are accepted with
    BYTE-IDENTICAL defaults. Last Stand (8299, condition="caster_hp_below") is
    the one gate-dependent amp: it returns ``base * _last_stand_amp(caster_hp_pct)``
    = ``base`` unchanged at the default ``caster_hp_pct=1.0`` (full HP, no amp,
    byte-identical to the item-231 exclusion), ramping to 1.11x as the caller
    supplies a low caster HP. All other ``stacking_amp`` runes use the flat
    ``amp_mult`` and ignore the gating kwargs (byte-identical).

    R53 (ENGINE 1.164.0) caster_hp gate seam: ``gate_caster_hp`` is the burst-path
    companion to the Last Stand caster-hp gate. The 8299 ramp is single-sourced
    through ``_last_stand_amp(caster_hp_pct)`` and is BYTE-IDENTICAL whether the
    flag is True or False - the flag only travels alongside ``caster_hp_pct`` so
    the caller's intent is explicit; the FUNCTIONAL default-OFF toggle (WHICH
    caster HP the burst scorer feeds Last Stand) lives in
    :func:`agents.daemon_slayer.burst.compute_burst_damage`
    (``gate_caster_hp_amp`` + ``caster_current_hp_pct``). The live default-ON flip
    is operator-gated (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.

    Cut Down (8017, condition="target_hp_above") + Coup de Grace (8014,
    condition="target_hp_below") apply their 1.08 flat amp UNCONDITIONALLY here
    at the DEFAULT ``gate_target_hp=False`` (item 232/233): a burst spans the
    target HP range (opens >60%, kills <40%) so the burst-MAX scorer meets BOTH
    gates within the window - gating by a single ``target_hp_pct`` snapshot would
    be LESS accurate for a burst.

    R51 (ENGINE 1.163.0) target_hp gate seam: pass ``gate_target_hp=True`` to
    HONESTLY gate those two runes on the supplied ``target_hp_pct`` per the live
    DDragon 16.13.1 longDesc - Cut Down amps only when the target is strictly
    ABOVE 60% health, Coup de Grace only when strictly BELOW 40% health; the gate
    that fails returns ``base`` unchanged (no amp). At the DEFAULT
    ``gate_target_hp=False`` the gate block is skipped entirely -> BYTE-IDENTICAL
    to the pre-R51 unconditional burst-window approximation. The seam is
    DEFAULT-OFF everywhere in this run; the live default-ON flip is operator-gated
    (docs/LIVE_GAME_GATED_SYNC.md - do not flip blind). The gate only touches the
    two ``target_hp_above`` / ``target_hp_below`` runes; every other amp rune
    ignores ``gate_target_hp`` (byte-identical).

    Unknown rune ids and non-amp runes return ``base_damage`` unchanged.
    ``stacks`` / ``game_time_s`` / ``role`` / ``bonus_as`` are accepted for
    forward compatibility / signature parity but are unused for the current amp
    registry. Fail-soft.
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
    if rune_id == 8299:
        # Last Stand: caster-hp-gated amp (NOT a flat amp_mult). Default
        # caster_hp_pct=1.0 -> _last_stand_amp returns 1.0 -> base unchanged.
        # R53 gate_caster_hp is byte-identical here (the ramp is single-sourced on
        # caster_hp_pct); the burst seam picks WHICH caster HP to feed in.
        try:
            return base * _last_stand_amp(caster_hp_pct=caster_hp_pct)
        except (TypeError, ValueError):
            return base
    if gate_target_hp and proc.condition in ("target_hp_above", "target_hp_below"):
        # R51 seam: honestly gate Cut Down (>60% target HP) / Coup de Grace
        # (<40% target HP) on target_hp_pct. Gate not met -> no amp (base).
        thp = _f(target_hp_pct)
        if proc.condition == "target_hp_above":
            gate_met = thp > _CUT_DOWN_HP_GATE
        else:
            gate_met = thp < _COUP_DE_GRACE_HP_GATE
        if not gate_met:
            return base
    try:
        return base * float(proc.amp_mult)
    except (TypeError, ValueError):
        return base
