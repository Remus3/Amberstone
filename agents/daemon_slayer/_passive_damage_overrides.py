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

GAP-2 exotic passives (item 247, gap-plan Phase C3): 6 of the 8 are now
SEEDED below with documented v1 caveats (Aatrox P / Jarvan IV P / Zed P /
Caitlyn P / Ekko P / Gangplank P). The level-scaled %-HP and 3-tier-step
coefficients ride the ``float | tuple`` scaling fields (``to_damage_block``
coerces either); the crit-interaction terms (Caitlyn's +crit-chance AD,
Gangplank's +2 per 1% crit) and Zed's below-50%-HP fire gate are documented
omissions in each entry's note (they belong in the AA-crit / conditional
seam, NOT a passive damage block). Their default-OFF magnitudes are exact for
the modeled terms. Item 248 then added the bilinear AP-on-HP schema lift and
SEEDED Gwen P (the item-247 staged candidate) + Aurora / Lillia / Renata P
(see the GAP-2 BILINEAR section below); Kai'Sa P stays staged (per-stack).

GAP-2 BILINEAR passives (item 248, bilinear AP-on-HP schema lift): the
AP-scaled %-of-HP form ("X% (+ Y% per 100 AP) of the target's HP") is a
``ctx[ap] * ctx[target_hp]`` PRODUCT that no single ``_SCALING_TARGETS`` field
expresses (each field is one pct * one ctx attr; base-X%-only under-models by
~2x at 200 AP). The lift adds ``DamageBlock.bilinear_terms`` (a flat
``factor * ctx[a] * ctx[b]`` product summed in ``ability_dps._evaluate_block``)
+ the ``_per_100(pct, per_attr, of_attr)`` authoring helper. SEEDED below from
verbatim 16.11.1 effects_descriptions, all default-OFF byte-identical: Gwen P
A Thousand Cuts (1% + 0.55% per 100 AP max HP) - the canonical case the lift
was built for, was STAGED through item 247 - plus Aurora P Spirit Abjuration
(2.5% + 2% per 100 AP max HP, 3rd-stack consume), Lillia P Dream-Laden Bough
(5% + 1.25% per 100 AP max HP dot), Renata P Leverage (1%:2% level + 2% per
100 AP max HP, first-hit per_fight). All four scale on target MAX HP, which is
non-zero at the default full-HP ctx (so they are not inert).

STAGED candidates (documented, NOT live entries - the bilinear lift does NOT
cover them; each needs a further runtime decision / its own slice):
  - per-stack ramps: Kai'Sa P Caustic Wounds (4 : 24 + 1 : 6 per Plasma stack
    + 12% : 24% per stacks AP) - the DOMINANT per-application term scales with
    the live Plasma-stack count (no single steady-state value); needs a
    stack-count assumption (its own decision). The 5th-stack-consume sub-term
    (15% + 6% per 100 AP of MISSING health) IS bilinear-expressible now, but
    is only part of the passive + fires on the 5th stack (a conditional
    cadence), so Kai'Sa stays staged whole rather than shipped partial.
  - bilinear-but-CONDITIONAL: Brand P Blaze ring detonation (8%:12% + 2% per
    100 AP max HP) fires only on a 3-stack + 2s-delay explosion (the base
    Ablaze DoT is NOT bilinear); Ekko W Parallel Convergence (3% + 3% per 100
    AP MISSING HP) fires only vs targets below 30% HP and scales on MISSING HP
    (~0 at the default full-HP ctx). Both need a Phase-D conditional / low-HP
    assumption, not a default-OFF steady-state ship.
  - bilinear HEALS (not damage): Karma W f1 Renewal (17% + 1% per 100 AP
    missing HP self-heal), Viego P Sovereign's Domination (2% + 2.5%/100 bonus
    AD + 2%/100 AP + 5%/100% bonus AS max-HP self-heal on Mist Wraith consume)
    - the bilinear term is a heal, out of scope for a damage block.

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


def _step_per_level(values: tuple[float, ...], count: int = _LEVEL_COUNT) -> tuple[float, ...]:
    """Build a per-LEVEL tuple for a DISCRETE "X / Y / Z (based on level)" step.

    League slash-notation ("6% / 8% / 10%") is a discrete level TIER step, NOT
    a smooth lerp (colon notation "X : Y" is the smooth form ``_lerp_per_level``
    covers). The 16.11.1 Meraki ``effects_descriptions`` gives the tier VALUES
    but not the level boundaries; the LoL-wiki ``{{pp|...}}`` breakpoints belong
    to the CURRENT patch (whose values drifted from 16.11.1), so we use the
    conventional EVEN-THIRDS boundaries (levels 1-6 / 7-12 / 13-18 for 3 tiers)
    as the documented v1 estimate. Each tier occupies ``count // len(values)``
    consecutive levels; the last tier absorbs any remainder so the tuple is
    always ``count`` long. Indexed by ``rank_at_level('P', level) == level - 1``
    exactly like ``_lerp_per_level``.
    """
    n = len(values)
    if n == 0:
        return tuple(0.0 for _ in range(count))
    seg = max(1, count // n)
    return tuple(float(values[min(i // seg, n - 1)]) for i in range(count))


def _per_100(pct: float, per_attr: str, of_attr: str) -> tuple[float, str, str]:
    """Build one BILINEAR term from Riot's "X% per 100 {per_attr} of {of_attr}".

    item 248 schema lift. The AP-scaled %-of-HP form ("0.55% per 100 AP of the
    target's maximum health") is a PRODUCT of two ctx stats - ``per_attr``
    (AP / bonus AD) and ``of_attr`` (target_max_hp / target_missing_hp) - that
    no single linear ``_SCALING_TARGETS`` field expresses (each field is one
    pct * one ctx attr). The engine evaluates a bilinear term as
    ``factor * ctx[per_attr] * ctx[of_attr]``; Riot's "pct% per 100 X" notation
    converts to ``factor = (pct / 100) * (1 / 100) = pct / 10000`` (the first
    /100 turns pct into a fraction, the second is the "per 100" denominator).

    Example: ``_per_100(0.55, "ap", "target_max_hp")`` -> ``factor = 0.000055``;
    at AP=200, target_max_hp=2500 -> 0.000055 * 200 * 2500 = 27.5 = the AP part
    of Gwen P's "0.55% per 100 AP" (1.1% of 2500). ``per_attr`` / ``of_attr``
    are literal ``AbilityContext`` attribute names. Rounded to 10 places so the
    authored factor is stable + ASCII-clean.
    """
    return (round(pct / 10000.0, 10), per_attr, of_attr)


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
    # Scaling % of a caster/target stat. A plain float is a FLAT % (same at
    # every level); a tuple is a PER-LEVEL % (indexed by rank == level - 1 via
    # value_at) for a level-scaled coefficient like Aatrox P (4% : 8% max HP)
    # or Caitlyn P (60 / 90 / 120% AD step). to_damage_block coerces either.
    bonus_ad_pct: float | tuple[float, ...] = 0.0
    ap_pct: float | tuple[float, ...] = 0.0
    total_ad_pct: float | tuple[float, ...] = 0.0
    target_max_hp_pct: float | tuple[float, ...] = 0.0
    target_current_hp_pct: float | tuple[float, ...] = 0.0
    # Bilinear product terms (item 248 schema lift): each
    # ``(factor, ctx_attr_a, ctx_attr_b)`` from ``_per_100(...)`` rides the
    # synthetic block as ``factor * ctx[a] * ctx[b]`` (an AP-scaled %-of-HP
    # term a single linear field cannot express). Default empty = no bilinear.
    bilinear_terms: tuple[tuple[float, str, str], ...] = ()


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
    # --- GAP-2 exotic passives (item 247, gap-plan Phase C3). Authored from
    # verbatim 16.11.1 effects_descriptions. Each carries a documented v1
    # modeling caveat in its note; all default-OFF byte-identical (the seam
    # only injects under apply_passive_damage=True). Gwen (bilinear AP-on-HP)
    # and Kai'Sa (per-Plasma-stack ramp) remain STAGED in the docstring - they
    # need a core evaluator term / a stack-count runtime decision (their own
    # slice), not a v1 caveat.
    #
    # Aatrox P Deathbringer Stance: empowered AA deals "4% : 8% (based on
    # level) of the target's maximum health" bonus magic. cap 100 vs monsters
    # (champion context = uncapped). Level-scaled %max-HP -> per-level tuple.
    ("Aatrox", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=_lerp_per_level(4.0, 8.0),
        damage_type="MAGIC",
        cadence="on_hit",
        note="Deathbringer Stance: 4% : 8% (based on level) target max HP bonus magic (vs-monster cap 100 not modeled; champ context uncapped)",
        attribute="Deathbringer Stance",
    ),
    # Jarvan IV P Martial Cadence: empowered AA deals "8% of the target's
    # current health" bonus physical, min 20, cap 400 vs non-champions. vs
    # champions: uncapped; the min-20 floor binds only below ~250 current HP
    # (rare for a champion). v1 models the flat 8% current HP; the min/cap
    # clamp is inert in the typical champion band (documented).
    ("JarvanIV", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_current_hp_pct=8.0,
        damage_type="PHYSICAL",
        cadence="on_hit",
        note="Martial Cadence: 8% target current HP bonus physical (min 20 / cap 400 vs non-champ inert in champ band)",
        attribute="Martial Cadence",
    ),
    # Zed P Contempt for the Weak: empowered AA vs targets BELOW 50% max HP
    # deals "6% / 8% / 10% (based on level)" of target max HP bonus magic.
    # 3-tier level STEP (slash notation) -> _step_per_level; 16.11.1 Meraki
    # values, EVEN-THIRDS breakpoint estimate (the live-wiki 1;7;17 belongs to
    # the drifted 5/7.5/10 current values - verify exact 16.11.1 boundaries in
    # Phase D). The below-50%-max-HP FIRE gate is not modeled: the injected
    # magnitude IS the value when it fires (% of MAX HP, gate-independent);
    # routing the fire-probability is a Phase-D conditional decision.
    ("Zed", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=_step_per_level((6.0, 8.0, 10.0)),
        damage_type="MAGIC",
        cadence="on_hit",
        note="Contempt for the Weak: 6/8/10% (based on level) target max HP bonus magic; below-50%-HP FIRE gate not modeled (magnitude is gate-independent); breakpoints even-thirds estimate",
        attribute="Contempt for the Weak",
    ),
    # Caitlyn P Headshot: empowered AA deals "60% / 90% / 120% (based on
    # level) AD bonus physical" (the verbatim 16.11.1 value), plus a
    # (+ crit-strike-chance) AD term. v1 models the base 60/90/120% TOTAL AD
    # step; the "+ crit chance AD" multiplier is an AA-crit interaction (no
    # crit context on a passive damage block - belongs in the AA/headshot
    # crit seam, not here) and the 110/115/120% vs non-champions is omitted.
    # 3-tier step -> _step_per_level, even-thirds breakpoints (verify Phase D).
    ("Caitlyn", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        total_ad_pct=_step_per_level((60.0, 90.0, 120.0)),
        damage_type="PHYSICAL",
        cadence="on_hit",
        note="Headshot: 60/90/120% (based on level) AD bonus physical; +crit-chance AD multiplier omitted (AA-crit seam); breakpoints even-thirds estimate",
        attribute="Headshot",
    ),
    # Ekko P Z-Drive Resonance: the 3rd Resonance stack consumes them to deal
    # "30 : 140 (based on level) (+ 90% AP)" bonus magic. Smooth 2-point lerp
    # base + flat AP. The every-3rd-stack CADENCE is metadata-only (cadence
    # "on_hit"): the value is the full 3rd-stack magnitude; amortizing it
    # across the 3 triggering hits is the on_hit-cadence consumer's job (same
    # convention as the 10 v1 on_hit entries above).
    ("Ekko", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(30.0, 140.0),
        ap_pct=90.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Z-Drive Resonance: 30 : 140 (based on level) (+ 90% AP) bonus magic on 3rd stack (every-3rd-stack cadence metadata-only)",
        attribute="Z-Drive Resonance",
    ),
    # Gangplank P Trial by Fire: empowered AA sets the target on fire for
    # "50 : 250 (based on level) (+ 100% bonus AD) (+ 2 per 1% crit) bonus
    # TRUE damage over 2.5 seconds". Smooth lerp base + 100% bonus AD, dot
    # cadence. The "+2 per 1% critical strike chance" term is omitted (crit
    # interaction - no crit context on a passive damage block; same boundary
    # as Caitlyn's crit term).
    ("Gangplank", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(50.0, 250.0),
        bonus_ad_pct=100.0,
        damage_type="TRUE",
        cadence="dot",
        note="Trial by Fire: 50 : 250 (based on level) (+ 100% bonus AD) bonus true over 2.5s; +2-per-1%-crit term omitted (crit seam); dot cadence",
        attribute="Trial by Fire",
    ),
    # --- GAP-2 BILINEAR passives (item 248, bilinear AP-on-HP schema lift).
    # Each is an "X% (+ Y% per 100 AP) of the target's HP" form: the linear X%
    # rides a (level-flat or level-scaled) target_*_hp_pct field, and the AP
    # part rides a bilinear_terms PRODUCT (AP * target HP) via _per_100. All
    # default-OFF byte-identical (the seam only injects under
    # apply_passive_damage=True). Authored from verbatim 16.11.1
    # effects_descriptions; vs-minion/monster caps are champ-context-uncapped
    # (same precedent as Aatrox / Zed); heal sub-clauses are utility not damage.
    #
    # Gwen P A Thousand Cuts: on-hit "1% (+ 0.55% per 100 AP) of the target's
    # maximum health" bonus magic. The canonical bilinear case this schema
    # lift was built for (was STAGED through item 247).
    ("Gwen", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=1.0,
        bilinear_terms=(_per_100(0.55, "ap", "target_max_hp"),),
        damage_type="MAGIC",
        cadence="on_hit",
        note="A Thousand Cuts: 1% (+ 0.55% per 100 AP) target max HP bonus magic on-hit; vs-minion/monster caps + heal clause not modeled (champ context uncapped)",
        attribute="A Thousand Cuts",
    ),
    # Aurora P Spirit Abjuration: 3rd-stack consume deals "2.5% (+ 2% per 100
    # AP) of the target's maximum health" bonus magic. every-3rd-stack cadence
    # metadata-only (cadence "on_hit", full consume magnitude - same convention
    # as Ekko P). vs-monster cap 100:270 not modeled; heal sub-clause utility.
    ("Aurora", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=2.5,
        bilinear_terms=(_per_100(2.0, "ap", "target_max_hp"),),
        damage_type="MAGIC",
        cadence="on_hit",
        note="Spirit Abjuration: 2.5% (+ 2% per 100 AP) target max HP bonus magic on 3rd-stack consume (every-3rd-stack cadence metadata-only); vs-monster cap 100:270 not modeled",
        attribute="Spirit Abjuration",
    ),
    # Lillia P Dream-Laden Bough (Dream Dust): "5% (+ 1.25% per 100 AP) of the
    # target's maximum health" total magic over 3s (dot cadence). cap 65 vs
    # monsters not modeled; the Lillia self-heal sub-clause is utility.
    ("Lillia", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=5.0,
        bilinear_terms=(_per_100(1.25, "ap", "target_max_hp"),),
        damage_type="MAGIC",
        cadence="dot",
        note="Dream-Laden Bough (Dream Dust): 5% (+ 1.25% per 100 AP) target max HP total magic over 3s; cap 65 vs monsters + heal clause not modeled; dot cadence",
        attribute="Dream-Laden Bough",
    ),
    # Renata P Leverage: first (unmarked) empowered AA deals "1% : 2% (based on
    # level) (+ 2% per 100 AP) of the target's maximum health" bonus magic. The
    # level-scaled linear 1%:2% rides a per-level target_max_hp_pct tuple; the
    # AP part is bilinear. per_fight cadence (the mark persists 6s + refreshes
    # so the bonus fires once per engagement on a sustained target). The
    # ally-consume mirror + 150 epic cap are not modeled.
    ("Renata", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=_lerp_per_level(1.0, 2.0),
        bilinear_terms=(_per_100(2.0, "ap", "target_max_hp"),),
        damage_type="MAGIC",
        cadence="per_fight",
        note="Leverage: 1% : 2% (based on level) (+ 2% per 100 AP) target max HP bonus magic on first (unmarked) hit; per_fight cadence; ally-consume mirror + 150 epic cap not modeled",
        attribute="Leverage",
    ),
}


def to_damage_block(entry: PassiveDamageEntry):
    """Build a synthetic ``DamageBlock`` from a ``PassiveDamageEntry``.

    The returned block is ``attribute_kind="damage"`` so
    ``ability_dps._select_blocks`` (which filters to damage blocks) and
    ``_evaluate_block`` consume it with zero new math: ``base`` is the
    per-level tuple, and each populated scaling field is coerced to a tuple
    (a flat float -> a 1-element tuple = same % at every rank; a per-level
    tuple is passed through, so ``value_at`` returns the level-correct % for a
    level-scaled coefficient like Aatrox / Caitlyn / Zed). An entry with no
    flat ``base`` (pure %-of-HP / %-of-AD passives) gets ``base=(0.0,)``.

    Imported lazily to avoid a circular import (abilities.py imports this
    module to wire the load-time seam, and DamageBlock is defined in
    abilities.py).
    """
    from .abilities import DamageBlock

    def _coerce(v: float | tuple[float, ...]) -> tuple[float, ...]:
        if isinstance(v, (tuple, list)):
            return tuple(float(x) for x in v)
        return (float(v),)

    def _present(v: float | tuple[float, ...]) -> bool:
        if isinstance(v, (tuple, list)):
            return any(float(x) != 0.0 for x in v)
        return float(v) != 0.0

    base = tuple(float(x) for x in entry.base) if entry.base else (0.0,)
    kwargs: dict[str, tuple] = {"base": base}
    for fld in (
        "bonus_ad_pct",
        "ap_pct",
        "total_ad_pct",
        "target_max_hp_pct",
        "target_current_hp_pct",
    ):
        v = getattr(entry, fld)
        if _present(v):
            kwargs[fld] = _coerce(v)
    if entry.bilinear_terms:
        kwargs["bilinear_terms"] = tuple(
            (float(factor), str(attr_a), str(attr_b))
            for (factor, attr_a, attr_b) in entry.bilinear_terms
        )
    return DamageBlock(
        attribute=entry.attribute,
        attribute_kind="damage",
        **kwargs,
    )
