"""2026-05-31 (GAP 2) - effects-text-only passive damage registry.

Context: a sibling-project scraper-refactor chat (validated against DS) and
RC's own roster audit found ~84 ability forms that parse to
``parse_status == "no_damage"`` (empty / no ``attribute_kind == "damage"``
block) yet carry a real damage formula spelled out in the form's
``effects_descriptions`` text. The overwhelming majority are P-slot
empowered-AA / on-hit passives (Ziggs Short Fuse, Lux Illumination, Akali
Assassin's Mark, Kha'Zix Unseen Threat, etc.) whose damage the Meraki
``leveling`` -> ``damage_blocks`` pipeline could not structure, so the
evaluator scores them at zero.

Why HAND-AUTHORED, not parsed: a text-parser silently mis-extracts the
endpoints (a "X : Y (based on level)" lerp vs a "X / Y / Z (based on level)"
3-point step vs a per-stack/per-AP nested term) and re-breaks on every
patch's prose rewrite - the sibling project's "edge cases will have to be
reverted" trap. We instead author the exact formula per (champion, key,
form_index) from the verbatim ``effects_descriptions`` fragment cited in each
entry's ``note``, and a future patch re-extract simply re-verifies the cited
text rather than re-parsing it.

How it injects: ``to_damage_block(entry)`` builds a synthetic
``DamageBlock(attribute_kind="damage", ...)`` that routes through the
EXISTING ``ability_dps._evaluate_block`` / ``_select_blocks`` machinery with
ZERO new math - ``base`` is summed directly per rank, and each scaling field
(``ap_pct`` / ``bonus_ad_pct`` / ``total_ad_pct`` / ``target_max_hp_pct``) is
multiplied by its ``_SCALING_TARGETS`` context attribute and divided by 100.

base REPRESENTATION (the engine convention these entries match exactly):
``ability_dps.rank_at_level("P", level)`` returns ``level - 1`` clamped to
[0, 17]; ``DamageBlock.value_at`` indexes the per-rank list by that rank and
clamps a short list to its last element. So for a P-slot passive that scales
smoothly with level ("X : Y based on level"), the correct ``base`` is a
per-LEVEL tuple of length 18 lerped linearly from the level-1 endpoint X to
the level-18 endpoint Y. The existing level-scaled P damage block in the live
data (Aphelios P "Bonus Attack Damage" base = [5,10,15,20,25,30]) confirms
level-scaled bases live as per-rank/per-level tuples consumed by
``value_at``; this registry uses the full 18-element form so the value at
every level is exact (Aphelios's 6-element form is an "every 6 levels" step,
a different scaling shape than these smooth lerps). ``_lerp_per_level`` is the
single source for the 18-element build. A 3-point "X / Y / Z (based on
level)" passive (Zed P) is NOT seeded in v1 (see staged list).

cadence field MEANING (metadata only in v1 - does NOT change the injected
block, which is unconditional steady-state damage): records the in-game
trigger rhythm so a future consumer can route the passive's DPS to the
correct clock:
  - "on_hit"   - empowered / on-hit basic-attack passive; its sustained DPS
                 belongs on the AUTO-ATTACK cadence (the empowered AA replaces
                 a normal AA, gated by an internal cooldown). This is the
                 explicit live-validation-gated default-flip caveat: when the
                 inject flag is later flipped default-on, an on_hit passive's
                 DPS must be attributed to the AA cadence, NOT a phantom spell
                 cast cadence, or it double-counts / mis-rates.
  - "per_fight"- one trigger per fight window (e.g. a per-target internal CD
                 longer than a typical trade).
  - "dot"      - damage-over-time tick (e.g. Gangplank Trial by Fire's 2.5s
                 burn) - STAGED, not seeded in v1.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the seam in ``abilities.py`` only injects
when the opt-in ``apply_passive_damage=True`` flag is passed to
``AbilitiesSnapshot.load``. With the flag OFF (the default) NO synthetic block
is appended, so the seeded P forms keep their original ``damage_blocks`` and
``parse_status == "no_damage"``, and the full DS suite is unchanged.

STAGED candidates (documented, NOT live entries - need extra modeling before
they can be authored against a fixed level/AP/AD pin):
  - % max/current/missing-HP coefficients: Aatrox P (4%:8% target max HP),
    JarvanIV P (8% target current HP, min 20 cap 400), Zed P (6/8/10%
    target max HP below 50% - also a 3-point level step), Gwen P
    (1% + 0.55% per 100 AP of target max HP - nested AP-on-HP term). These
    need a target-HP value (and Zed's a below-50% conditional gate) to
    resolve to a number; the % fields exist in ``_SCALING_FIELDS`` but the
    realistic-target-HP and conditional-gate decisions are their own slice.
  - crit-chance coefficients: Caitlyn P Headshot (60/90/120% AD scaling by
    level, an empowered-AA crit-interaction). No crit-chance scaling field
    on DamageBlock; needs the AA-crit interaction modeled.
  - per-stack ramps: Kai'Sa P Caustic Wounds (4:24 + 1:6 per Plasma stack +
    12%:24% nested) - a stacking term with no single steady-state value.
  - conditional gates: Ekko P Resonance (fires on the 3rd Resonance stack
    only), Zed P (below-50%-HP gate).
  - dot cadence: Gangplank P Trial by Fire (50:250 + 100% bAD + 2 per 1%
    crit, true damage over 2.5s) - dot cadence + a crit coefficient.

KogMaw P "Icathian Surprise" is explicitly NOT a damage passive (it is the
death-state self-detonation zombie passive); do NOT author it.

Applied at load time in ``abilities.AbilitiesSnapshot.load`` (behind the
opt-in flag) so every consumer (ability_dps / burst / dps / fight_report /
scenario / hps) would see the same corrected form uniformly when enabled.
Keyed ``(champion_id, key, form_index)`` - the same shape as
``_ability_overrides`` (item 238).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Import the engine DamageBlock so to_damage_block builds the real type that
# _evaluate_block consumes. abilities.py imports THIS module after it defines
# DamageBlock, so a top-level import here would be circular; to_damage_block
# imports DamageBlock lazily (function-level) instead.


# Number of champion levels (League). A smooth "X : Y (based on level)"
# passive lerps across all 18 levels; the per-level tuple has one entry per
# level, indexed by ``rank_at_level("P", level) == level - 1``.
_LEVEL_COUNT: int = 18


def _lerp_per_level(low: float, high: float, count: int = _LEVEL_COUNT) -> tuple[float, ...]:
    """Build a per-LEVEL tuple lerping linearly from ``low`` (level 1) to
    ``high`` (level ``count``).

    ``count`` defaults to 18 (the engine clamps higher ranks to the last
    element via ``DamageBlock.value_at``, and ``rank_at_level('P', level)``
    clamps to [0, 17], so an 18-element tuple is exact at every level).
    Rounded to 6 places so the authored values are stable + ASCII-clean.
    """
    if count < 2:
        return (float(low),)
    span = count - 1
    return tuple(round(low + (high - low) * i / span, 6) for i in range(count))


@dataclass(frozen=True)
class PassiveDamageEntry:
    """One hand-authored effects-text-only passive damage formula.

    Mirrors the ``DamageBlock`` optional scaling fields we need for v1's
    flat-per-level + AP / bonus-AD / total-AD forms (plus
    ``target_max_hp_pct`` so the schema can carry a future % max-HP entry
    without a re-author). ``base`` is the per-LEVEL tuple built by
    ``_lerp_per_level`` (resolved to match the engine's
    ``value_at(rank == level - 1)`` indexing).

    ``damage_type`` is one of ``"PHYSICAL"`` / ``"MAGIC"`` / ``"TRUE"`` (the
    engine routes mitigation off ``form.damage_type``, NOT off the block, so
    this is documentation of the passive's type for the entry's note + for a
    future per-block-type consumer; the seam does not currently flip
    ``form.damage_type`` when it is already non-null).
    """

    base: tuple[float, ...]
    damage_type: str
    cadence: str
    note: str
    attribute: str = "Passive Damage"
    bonus_ad_pct: float = 0.0
    ap_pct: float = 0.0
    total_ad_pct: float = 0.0
    target_max_hp_pct: float = 0.0


# (champion_id, key, form_index) -> PassiveDamageEntry.
# Seeded 2026-05-31 against verbatim effects_descriptions at patch 16.11.1.
# v1 scope: the CLEANEST single-clause flat-per-level + AP / bonus-AD forms
# (every base is an "X : Y (based on level)" smooth lerp; every scaling term
# is a single flat % of AP and/or bonus AD). The exotic forms (% HP, crit,
# per-stack, conditional, dot) are STAGED in the module docstring, not here.
_PASSIVE_DAMAGE_OVERRIDES: dict[tuple[str, str, int], PassiveDamageEntry] = {
    # Ziggs Short Fuse: "deal 20 : 160 (based on level) (+ 50% AP) bonus
    # magic damage" on the empowered basic attack.
    ("Ziggs", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(20.0, 160.0),
        ap_pct=50.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Short Fuse: 20 : 160 (based on level) (+ 50% AP) bonus magic damage",
        attribute="Short Fuse",
    ),
    # Lux Illumination: "deal 30 : 200 (based on level) (+ 30% AP) bonus
    # magic damage" when the mark is consumed.
    ("Lux", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(30.0, 200.0),
        ap_pct=30.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Illumination: 30 : 200 (based on level) (+ 30% AP) bonus magic damage",
        attribute="Illumination",
    ),
    # Orianna Clockwork Windup: on-hit "10 : 50 (based on level) (+ 15% AP)
    # bonus magic damage" (2-stack-ramped empowered AA; we author the
    # full-magnitude on-hit value).
    ("Orianna", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(10.0, 50.0),
        ap_pct=15.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Clockwork Winding: 10 : 50 (based on level) (+ 15% AP) bonus magic damage on-hit",
        attribute="Clockwork Winding",
    ),
    # Warwick Eternal Hunger: "12 : 46 (based on level) (+ 15% bonus AD)
    # (+ 10% AP) bonus magic damage on-hit".
    ("Warwick", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(12.0, 46.0),
        bonus_ad_pct=15.0,
        ap_pct=10.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Eternal Hunger: 12 : 46 (based on level) (+ 15% bonus AD) (+ 10% AP) bonus magic damage on-hit",
        attribute="Eternal Hunger",
    ),
    # Akali Assassin's Mark (Swinging Kama): "35 : 182 (based on level)
    # (+ 60% bonus AD) (+ 55% AP) bonus magic damage" on the empowered AA.
    ("Akali", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(35.0, 182.0),
        bonus_ad_pct=60.0,
        ap_pct=55.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Assassin's Mark (Swinging Kama): 35 : 182 (based on level) (+ 60% bonus AD) (+ 55% AP) bonus magic damage",
        attribute="Assassin's Mark",
    ),
    # Kha'Zix Unseen Threat: "17 : 136 (based on level) (+ 50% bonus AD)
    # bonus magic damage" on the empowered AA.
    ("Khazix", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(17.0, 136.0),
        bonus_ad_pct=50.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Unseen Threat: 17 : 136 (based on level) (+ 50% bonus AD) bonus magic damage",
        attribute="Unseen Threat",
    ),
    # Qiyana Royal Privilege: "15 : 83 (based on level) (+ 30% bonus AD)
    # (+ 30% AP) bonus physical damage" on basic attacks / abilities.
    ("Qiyana", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(15.0, 83.0),
        bonus_ad_pct=30.0,
        ap_pct=30.0,
        damage_type="PHYSICAL",
        cadence="on_hit",
        note="Royal Privilege: 15 : 83 (based on level) (+ 30% bonus AD) (+ 30% AP) bonus physical damage",
        attribute="Royal Privilege",
    ),
    # Vex Gloom detonation: "40 : 150 (based on level) (+ 25% AP) bonus magic
    # damage" (Doom n Gloom mark detonation against champions).
    ("Vex", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(40.0, 150.0),
        ap_pct=25.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Gloom detonation: 40 : 150 (based on level) (+ 25% AP) bonus magic damage",
        attribute="Gloom",
    ),
    # Sona Power Chord: "20 : 240 (based on level) (+ 20% AP)" on the
    # empowered (3-stack) basic attack.
    ("Sona", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(20.0, 240.0),
        ap_pct=20.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Power Chord: 20 : 240 (based on level) (+ 20% AP) magic damage",
        attribute="Power Chord",
    ),
    # Vel'Koz Organic Deconstruction: "35 : 180 (based on level) (+ 60% AP)
    # bonus true damage" on the 3rd Deconstruction stack.
    ("Velkoz", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(35.0, 180.0),
        ap_pct=60.0,
        damage_type="TRUE",
        cadence="on_hit",
        note="Organic Deconstruction: 35 : 180 (based on level) (+ 60% AP) bonus true damage",
        attribute="Organic Deconstruction",
    ),
}


def to_damage_block(entry: PassiveDamageEntry):
    """Build a synthetic ``DamageBlock`` from a ``PassiveDamageEntry``.

    The returned block is ``attribute_kind="damage"`` so
    ``ability_dps._select_blocks`` (which filters to damage blocks) and
    ``_evaluate_block`` consume it with zero new math: ``base`` is the
    per-level tuple, and each populated scaling field is a 1-element tuple of
    the flat percentage (``value_at`` returns that single value at every
    rank, matching the existing constant-scaling convention).

    Imported lazily to avoid a circular import (abilities.py imports this
    module to wire the load-time seam, and DamageBlock is defined in
    abilities.py).
    """
    from .abilities import DamageBlock

    kwargs: dict[str, tuple[float, ...]] = {"base": tuple(entry.base)}
    if entry.bonus_ad_pct:
        kwargs["bonus_ad_pct"] = (float(entry.bonus_ad_pct),)
    if entry.ap_pct:
        kwargs["ap_pct"] = (float(entry.ap_pct),)
    if entry.total_ad_pct:
        kwargs["total_ad_pct"] = (float(entry.total_ad_pct),)
    if entry.target_max_hp_pct:
        kwargs["target_max_hp_pct"] = (float(entry.target_max_hp_pct),)
    return DamageBlock(
        attribute=entry.attribute,
        attribute_kind="damage",
        **kwargs,
    )
