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
(see the GAP-2 BILINEAR section below). Item 249 then added the per-stack
schema lift and SEEDED Kai'Sa P (the canonical per-stack case STAGED through
item 248) + Darius P + Twitch P + upgraded Orianna P (see the GAP-2 PER-STACK
section below).

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

GAP-2 PER-STACK passives (item 249, per-stack damage schema lift): some
passives deal damage that scales LINEARLY with the number of stacks on the
target. The per_stack COEFFICIENTS are exact; only the stack MULTIPLIER is a
steady-state ``assumed_stacks`` (documented per entry, operator-tunable,
externalized so a future live consumer can feed the real count - mirrors item
236's tenacity externalization). The lift adds ``PerStackTerm`` +
``PassiveDamageEntry.per_stack`` / ``assumed_stacks``; ``to_damage_block``
FOLDS ``field + per_stack.field * assumed_stacks`` element-wise into the
synthetic block, so ``ability_dps._evaluate_block`` needs ZERO new math (the
per-stack contribution collapses into the ordinary base/scaling fields once
the assumed count is fixed). SEEDED from verbatim 16.11.1
effects_descriptions, all default-OFF byte-identical: Kai'Sa P Caustic Wounds
(4:24 + 12% AP, + (1:6 + 3% AP) per Plasma stack; the "12%:24% based on
stacks" AP ratio is linear = 12% + 3%/stack) + Darius P Hemorrhage ((13:30 +
30% bonus AD) per stack bleed dot) + Twitch P Deadly Venom ((6/12/18/24/30 +
18% AP) per stack true dot) + an UPGRADE to the already-seeded Orianna P
(adds the 2:10 + 3% AP per-stack ramp it was missing). EXHAUSTED scan: of the
15 no_damage P-forms with "per stack"+"damage" language, only these 4 are
per-stack TARGET damage; the other 11 are NOT (Belveth/Garen/Irelia/Kayle/
Samira/Senna/Volibear/Wukong gain AS/MS/armor stat STEROIDS per stack;
Mel/Smolder are stack-gain / damage-store mechanics; Sona's per-stack
Accelerando is a haste steroid - Sona P is separately seeded for its flat
Power Chord, not a per-stack term) - documented inline, not seeded. The Kai'Sa
5th-stack-consume sub-term (15% + 6%/100 AP of MISSING health) is OMITTED:
conditional (fires on the 5th stack) AND inert at the default full-HP ctx
(same precedent as Ekko W).

GAP-2 CONDITIONAL-GATE passives (item 255, conditional-gate schema lift): a
class whose damage fires on a non-steady-state CONDITION (an Nth-stack
explosion, a sub-X%-HP gate, a marked-target consume, an Nth-shot) and scales
on target MAX or MISSING HP. The lift adds (a) ``PassiveDamageEntry.
target_missing_hp_pct`` (the missing-HP sibling of ``target_max_hp_pct``;
resolves to 0 at the default full-HP ctx = byte-identical lower-bound, like the
missing-HP HEAL seeds) and (b) ``conditional_probability`` (default 1.0 = no-op
for the 23 prior entries; ``to_damage_block`` multiplies every coefficient by
it so the injected block is the amortized expected magnitude). Two shapes:
MAX-HP (non-zero at the default ctx -> the gate is the only thing keeping it
from over-injecting; conditional_probability < 1.0 carries the firing midpoint)
vs MISSING-HP (0 at the default ctx -> the HP gate is ctx-encoded, so
conditional_probability stays 1.0 unless there is a SEPARATE event gate). No
new evaluator code (target_missing_hp_pct -> target_missing_hp is already in
``_SCALING_TARGETS``; bilinear ``_per_100(.., "ap", "target_missing_hp")`` rides
the item-248 path). SEEDED (5): Brand P (max-HP ring explosion, prob 0.5),
Ekko W (missing-HP sub-30%, prob 1.0 ctx-gated), Jhin P (missing-HP 4th shot,
prob 0.25 EXACT), K'Sante P (flat + max-HP mark consume, prob 1.0), Sejuani P
(max-HP frozen detonation, prob 0.5). All default-OFF byte-identical.

REJECTS (documented, NOT seeded):
  - Kai'Sa P 5th-stack consume (15% + 6%/100 AP MISSING HP): the (Kaisa,P,0)
    key already holds the UNCONDITIONAL Caustic Wounds per-stack ramp; a
    per-entry conditional_probability would wrongly gate it. Needs per-TERM
    gating / a multi-entry registry (a further lift).
  - Zed P below-50%-HP (max-HP): already SHIPPED item 247 at full magnitude
    (gate-not-modeled, gate-independent); not retroactively re-gated (its
    flag-ON output + item-247 pins stay).
  - Zeri P full-charge empowered shot: her basic-attack damage is fully
    charge-gated/spell-replaced (both the empowered AND non-empowered forms
    differ from a normal AA), so the additive passive-damage seam mis-models
    it - needs a champion-specific AA-replacement treatment.
  - Samira P blade bonus: the missing-HP clause is a MULTIPLIER on the
    flat+AD blade bonus, not an additive %-of-HP term; the base is an AD-scaled
    on-hit (linear-registry shape), not a conditional %-HP damage.
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

from dataclasses import dataclass

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
class PerStackTerm:
    """item 249 schema lift - a per-stack damage component.

    Some passives deal damage that scales LINEARLY with the number of stacks
    present on the target (Kai'Sa Plasma, Darius Hemorrhage, Twitch Deadly
    Venom, Orianna Clockwork Winding). The coefficients are EXACT; only the
    stack MULTIPLIER is a steady-state assumption, externalized to the entry's
    ``assumed_stacks`` so a future live consumer can feed the real count
    without re-authoring (mirrors how item 236 externalized the tenacity
    assumption). The same scaling fields as ``PassiveDamageEntry`` are read as
    "per stack"; ``to_damage_block`` folds ``field + per_stack.field *
    assumed_stacks`` into the synthetic block (element-wise over the per-level
    tuples) so the evaluator needs ZERO new math - the per-stack contribution
    collapses into the ordinary ``base`` / scaling fields once the assumed
    count is fixed. A plain float is a flat per-stack coefficient; a tuple is a
    per-level per-stack coefficient (Kai'Sa "1 : 6 per level per stack").
    """

    base: float | tuple[float, ...] = 0.0
    bonus_ad_pct: float | tuple[float, ...] = 0.0
    ap_pct: float | tuple[float, ...] = 0.0
    total_ad_pct: float | tuple[float, ...] = 0.0
    target_max_hp_pct: float | tuple[float, ...] = 0.0
    target_missing_hp_pct: float | tuple[float, ...] = 0.0
    target_current_hp_pct: float | tuple[float, ...] = 0.0


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
    # item 255 conditional-gate lift: % of the target's MISSING health (the
    # caster-relative sibling of target_max_hp_pct). Resolves to 0 at the
    # default full-HP ctx (target_missing_hp = max_hp * (1 - current_pct), and
    # current_pct defaults to 1.0) - the same resting-lower-bound contract as
    # the missing-HP HEAL seeds (items 250/254): a missing-HP damage term is
    # byte-identical at the default ctx and surfaces only under
    # resolve_target_relative + a sub-threshold target_current_hp_pct.
    target_missing_hp_pct: float | tuple[float, ...] = 0.0
    # Bilinear product terms (item 248 schema lift): each
    # ``(factor, ctx_attr_a, ctx_attr_b)`` from ``_per_100(...)`` rides the
    # synthetic block as ``factor * ctx[a] * ctx[b]`` (an AP-scaled %-of-HP
    # term a single linear field cannot express). Default empty = no bilinear.
    bilinear_terms: tuple[tuple[float, str, str], ...] = ()
    # Per-stack damage component (item 249 schema lift): a ``PerStackTerm``
    # whose coefficients ``to_damage_block`` folds into the synthetic block as
    # ``field + per_stack.field * assumed_stacks``. ``assumed_stacks`` is the
    # documented steady-state stack count (operator-tunable; default 0 = inert
    # so a per_stack entry never injects a per-stack contribution until its own
    # assumed_stacks is set). Default None = no per-stack term.
    per_stack: "PerStackTerm | None" = None
    assumed_stacks: float = 0.0
    # item 255 conditional-gate lift: the documented operator-tunable fraction
    # of the relevant cadence events at which a CONDITIONAL passive's term
    # actually fires, for gates NOT expressible via the target-HP ctx (a stack
    # / explosion / mark / Nth-shot event). to_damage_block MULTIPLIES every
    # coefficient (base + each scaling field + each bilinear factor) by it at
    # build time, so the injected block is the amortized expected magnitude and
    # the evaluator stays byte-identical. Default 1.0 = byte-identical for the
    # 23 prior entries. Same midpoint convention as per_stack.assumed_stacks +
    # cc_conditional probabilities. For a ctx-encoded gate (Ekko W sub-30% HP)
    # leave it 1.0 - the resolve_target_relative + HP ctx already gates it and
    # a second probability would double-discount the in-gate magnitude.
    conditional_probability: float = 1.0


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
    # bonus magic damage, increased by 2 : 10 (based on level) (+ 3% AP) per
    # stack, up to 14 : 70 (based on level) (+ 21% AP)" (stacking to 2 on a
    # single target; all stacks lost when attacking a NEW enemy). item 249
    # per-stack lift: the flat base is the 0-stack value; the per_stack term
    # adds 2:10 base + 3% AP per stack. assumed_stacks=1.0 (the ramp-midpoint
    # of the 0..2 window; operator-tunable). At 1 stack -> 12:60 (+ 18% AP);
    # at the 2-stack cap -> 14:70 (+ 21% AP) = the documented max.
    ("Orianna", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(10.0, 50.0),
        ap_pct=15.0,
        per_stack=PerStackTerm(base=_lerp_per_level(2.0, 10.0), ap_pct=3.0),
        assumed_stacks=1.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Clockwork Winding: 10 : 50 (based on level) (+ 15% AP) + 2 : 10 (based on level) (+ 3% AP) per stack (cap 2; assumed_stacks 1.0 = ramp-midpoint, operator-tunable) bonus magic on-hit",
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
    # --- GAP-2 PER-STACK passives (item 249, per-stack damage schema lift).
    # The damage scales LINEARLY with the number of stacks on the target; the
    # per_stack coefficients are EXACT and the stack MULTIPLIER is a documented
    # steady-state ``assumed_stacks`` (operator-tunable, folded at build time).
    # All default-OFF byte-identical (the seam injects only under
    # apply_passive_damage=True). Authored from verbatim 16.11.1
    # effects_descriptions; vs-monster multipliers/caps are champ-context
    # (same precedent as Aatrox / Zed). Exhausted scan: the 11 other "per
    # stack" no_damage P-forms are NOT per-stack target damage - stat STEROIDS
    # (Belveth/Garen/Irelia/Kayle/Samira/Senna/Volibear/Wukong AS/MS/armor) or
    # stack-gain/store mechanics (Mel/Smolder); Sona's per-stack Accelerando is
    # a haste steroid (Sona P is separately seeded for its flat Power Chord).
    # Documented in the module docstring, not seeded.
    #
    # Kai'Sa P Caustic Wounds: "Plasma stacks ... deal 4 : 24 (based on level)
    # (+ 1 : 6 (based on level) per Plasma stack before application) (+ 12% :
    # 24% (based on Plasma stacks before application) AP) bonus magic damage".
    # The "12% : 24% based on stacks" AP ratio is LINEAR in stacks: 12% + 3%
    # per stack (12 at 0 stacks, 24 at 4). So: flat base 4:24 + flat 12% AP,
    # PLUS per stack (1:6 base + 3% AP). Plasma stacks to 5 then the 5th
    # consumes them all (so 0..4 are present "before application");
    # assumed_stacks=2.0 = the cycle-average over the 5-attack ramp (sees
    # 0,1,2,3,4 -> mean 2). The 5th-stack-consume sub-term (15% + 6% per 100 AP
    # of MISSING health) STAYS OMITTED even after the item-255 conditional-gate
    # lift: this (Kaisa,P,0) entry is the UNCONDITIONAL Caustic Wounds per-stack
    # ramp, and the registry is one-entry-per-(champ,key,form), so a per-entry
    # conditional_probability would WRONGLY gate the unconditional ramp too.
    # Isolating the 5th-stack term needs per-TERM gating or a multi-entry-per-
    # key registry (a further lift) - documented item-255 reject, not seeded.
    ("Kaisa", "P", 0): PassiveDamageEntry(
        base=_lerp_per_level(4.0, 24.0),
        ap_pct=12.0,
        per_stack=PerStackTerm(base=_lerp_per_level(1.0, 6.0), ap_pct=3.0),
        assumed_stacks=2.0,
        damage_type="MAGIC",
        cadence="on_hit",
        note="Caustic Wounds: 4 : 24 (based on level) (+ 12% AP) + (1 : 6 (based on level) (+ 3% AP)) per Plasma stack (cap 5/consume-at-5; assumed_stacks 2.0 = ramp-cycle-average, operator-tunable) bonus magic on-hit; 5th-stack-consume missing-HP term omitted (conditional + inert at full HP)",
        attribute="Caustic Wounds",
    ),
    # Darius P Hemorrhage: "For each stack, the target is dealt 13 : 30 (based
    # on level) (+ 30% bonus AD) total physical damage over the duration ...
    # up to a maximum of 65 : 150 (based on level) (+ 150% bonus AD)" (5
    # stacks). Pure per-stack bleed DoT (no flat base). assumed_stacks=3.0 =
    # mid of the 1..5 window (Darius applies stacks fast + refreshes; a focused
    # target sits mid-to-high). cadence dot (total over the bleed duration).
    # The 200% vs monsters multiplier is champ-context (not modeled).
    ("Darius", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        per_stack=PerStackTerm(base=_lerp_per_level(13.0, 30.0), bonus_ad_pct=30.0),
        assumed_stacks=3.0,
        damage_type="PHYSICAL",
        cadence="dot",
        note="Hemorrhage: (13 : 30 (based on level) (+ 30% bonus AD)) per stack total physical over the bleed (cap 5; assumed_stacks 3.0 = mid-ramp, operator-tunable); 200% vs monsters not modeled; dot cadence",
        attribute="Hemorrhage",
    ),
    # Twitch P Deadly Venom: "For each stack, the target is dealt 1 / 2 / 3 / 4
    # / 5 (based on level) (+ 3% AP) true damage per second over the duration
    # [total 6 / 12 / 18 / 24 / 30 (based on level) (+ 18% AP)] ... maximum 36 /
    # 72 / 108 / 144 / 180 (+ 108% AP)" (6 stacks). Per-stack true-damage DoT;
    # we author the per-stack TOTAL over the 6s venom (6/12/18/24/30 + 18% AP).
    # 5-tier level STEP (slash notation) -> _step_per_level even-fifths estimate
    # (16.11.1 Meraki gives tier values not boundaries; same precedent as the
    # Zed/Caitlyn even-thirds steps). assumed_stacks=3.0 = mid of the 1..6
    # window. cadence dot (total over the duration).
    ("Twitch", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        per_stack=PerStackTerm(
            base=_step_per_level((6.0, 12.0, 18.0, 24.0, 30.0)),
            ap_pct=18.0,
        ),
        assumed_stacks=3.0,
        damage_type="TRUE",
        cadence="dot",
        note="Deadly Venom: (6/12/18/24/30 (based on level) (+ 18% AP)) per stack total true over the 6s poison (cap 6; assumed_stacks 3.0 = mid-ramp, operator-tunable); breakpoints even-fifths estimate; dot cadence",
        attribute="Deadly Venom",
    ),
    # --- item 255 CONDITIONAL-GATE damage lift. The class items 248/249 STAGED
    # (Brand P + Ekko W) + 3 siblings the exhaustion scan surfaced. Each entry
    # is WHOLLY conditional (no unconditional base mixed in) so the per-entry
    # conditional_probability gate cleanly scales the whole block. Two shapes:
    #   (a) target MAX-HP scaled (non-zero at the default ctx) - the gate is the
    #       ONLY thing keeping it from over-injecting on every eval (Brand,
    #       Sejuani). conditional_probability < 1.0 = the documented firing
    #       midpoint (operator-tunable, Phase-D-refinable).
    #   (b) target MISSING-HP scaled (0 at the default full-HP ctx, lower-bound
    #       like the missing-HP HEAL seeds) - byte-identical default even with
    #       the flag ON; surfaces only under resolve_target_relative + a
    #       sub-threshold target_current_hp_pct (Ekko, Jhin). The HP gate is
    #       ctx-ENCODED so conditional_probability stays 1.0 EXCEPT Jhin (the
    #       4th-shot frequency is a separate, EXACT 0.25 event gate).
    # All default-OFF byte-identical (the seam only injects under
    # apply_passive_damage=True). vs-minion/monster caps + mins are
    # champ-context-uncapped (Aatrox / Zed / Gwen precedent).
    #
    # Brand P Blaze: on the 3rd Ablaze stack a ring forms and after 2s explodes
    # for "8% : 12% (based on level) (+ 2% per 100 AP) of their maximum health"
    # magic. MAX-HP -> non-zero at the default ctx; the 3-stack + 2s + 4s-no-
    # restack gate is NOT ctx-expressible, so conditional_probability=0.5 is the
    # documented firing midpoint (the ring is a reliable Brand combo finisher
    # but not every ability; operator-tunable). The base Ablaze DoT (2% max HP
    # over 4s per stack) is a SEPARATE unconditional term NOT modeled here.
    ("Brand", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=_lerp_per_level(8.0, 12.0),
        bilinear_terms=(_per_100(2.0, "ap", "target_max_hp"),),
        damage_type="MAGIC",
        cadence="per_fight",
        conditional_probability=0.5,
        note="Blaze ring explosion: 8% : 12% (based on level) (+ 2% per 100 AP) target max HP magic on the 3-stack + 2s detonation; conditional_probability 0.5 = documented firing midpoint (operator-tunable); base Ablaze DoT not modeled",
        attribute="Blaze",
    ),
    # Ekko W Parallel Convergence (passive): basic attacks vs enemies BELOW 30%
    # max HP deal "3% (+ 3% per 100 AP) of the target's missing health" bonus
    # magic (min 15, capped 150 vs minions/monsters). MISSING-HP -> 0 at the
    # default full-HP ctx; the sub-30% gate is ctx-ENCODED (evaluating at a
    # sub-30% target_current_hp_pct both meets the gate AND gives the correct
    # missing-HP magnitude) so conditional_probability stays 1.0 - a second
    # probability would double-discount the in-gate value. on_hit cadence.
    ("Ekko", "W", 0): PassiveDamageEntry(
        base=(0.0,),
        target_missing_hp_pct=3.0,
        bilinear_terms=(_per_100(3.0, "ap", "target_missing_hp"),),
        damage_type="MAGIC",
        cadence="on_hit",
        note="Parallel Convergence (passive): 3% (+ 3% per 100 AP) target MISSING HP bonus magic on-hit vs sub-30%-HP targets; 0 at the default full-HP ctx (lower-bound, surfaces under resolve_target_relative); sub-30% gate ctx-encoded so conditional_probability=1.0; min15/cap150 champ-context",
        attribute="Parallel Convergence",
    ),
    # Jhin P Whisper: the 4th (final) round always crits AND deals bonus
    # physical equal to "15% / 20% / 25% (based on level) of the target's
    # missing health" (capped 800 vs monsters). MISSING-HP -> 0 at the default
    # ctx (lower-bound). The "every 4th shot" gate is a discrete EXACT event
    # (1-of-4 attacks) NOT ctx-expressible, so conditional_probability=0.25 is
    # exact (not a midpoint). The always-crit + the "Every Moment Matters" AD
    # steroid are SEPARATE (AA-crit / AD interactions, not this term). 3-tier
    # level STEP -> _step_per_level (even-thirds; verify exact 16.11.1 in Ph-D).
    ("Jhin", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_missing_hp_pct=_step_per_level((15.0, 20.0, 25.0)),
        damage_type="PHYSICAL",
        cadence="on_hit",
        conditional_probability=0.25,
        note="Whisper 4th shot: 15/20/25% (based on level) target MISSING HP bonus physical; 0 at the default full-HP ctx (lower-bound); conditional_probability 0.25 = EXACT every-4th-shot frequency; always-crit + AD steroid omitted (separate); breakpoints even-thirds estimate; cap 800 vs monsters champ-context",
        attribute="Whisper",
    ),
    # K'Sante P Dauntless Instinct: abilities mark enemies 4s; the next basic
    # attack consumes the mark for "12 (+ 1% : 2% (based on level) of target's
    # maximum health)" bonus physical (min 15 : 100). MAX-HP -> non-zero at the
    # default ctx. The mark is reliably up after any ability (4s, refreshed) so
    # the empowered AA fires like the other on-hit mark-consume passives
    # (Ziggs / Lux / Vex / Sona / Velkoz) -> conditional_probability=1.0,
    # cadence on_hit (the consumer amortizes the after-ability frequency). The
    # "All Out Bonus" (1% + 1%/100 bonus armor + 1%/100 bonus MR of max HP) is
    # OMITTED (bonus-armor/MR scaling has no ctx on a passive block, same
    # boundary as Caitlyn's crit term); min 15:100 vs minions champ-context.
    ("KSante", "P", 0): PassiveDamageEntry(
        base=(12.0,),
        target_max_hp_pct=_lerp_per_level(1.0, 2.0),
        damage_type="PHYSICAL",
        cadence="on_hit",
        note="Dauntless Instinct mark consume: 12 (+ 1% : 2% (based on level) target max HP) bonus physical on-hit; All Out Bonus (bonus-armor/MR %max-HP) omitted (no ctx, Caitlyn-crit precedent); min15:100 champ-context",
        attribute="Dauntless Instinct",
    ),
    # Sejuani P Icebreaker: an enemy stunned by Sejuani is marked Frozen; her
    # next basic attack or ability vs a Frozen target consumes the mark for
    # "10% of their maximum health" bonus magic (capped 250 vs epic monsters).
    # MAX-HP -> non-zero at the default ctx; the Frozen gate (Sejuani must land
    # CC first) is NOT ctx-expressible so conditional_probability=0.5 = the
    # documented CC-detonation firing midpoint (operator-tunable). Flat 10% (no
    # level / AP scaling). cadence per_fight (a CC-gated burst, not per-AA).
    ("Sejuani", "P", 0): PassiveDamageEntry(
        base=(0.0,),
        target_max_hp_pct=10.0,
        damage_type="MAGIC",
        cadence="per_fight",
        conditional_probability=0.5,
        note="Icebreaker frozen detonation: 10% target max HP bonus magic on the next hit vs a Sejuani-Frozen target; conditional_probability 0.5 = documented CC-detonation firing midpoint (operator-tunable); cap 250 vs epic champ-context",
        attribute="Icebreaker",
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

    # item 249 per-stack fold: when the entry carries a PerStackTerm + a
    # non-zero assumed_stacks, each scaling field becomes
    # ``entry.field + per_stack.field * assumed_stacks`` (element-wise over the
    # per-level tuples, broadcasting a flat to the longer length). The result
    # is an ordinary DamageBlock - the evaluator stays byte-identical.
    def _as_tuple(v: float | tuple[float, ...]) -> tuple[float, ...]:
        if isinstance(v, (tuple, list)):
            return tuple(float(x) for x in v) or (0.0,)
        return (float(v),)

    def _fold(flat_v, ps_v, stacks: float) -> tuple[float, ...]:
        a = _as_tuple(flat_v)
        b = _as_tuple(ps_v)
        n = max(len(a), len(b))
        return tuple(
            round((a[i] if i < len(a) else a[-1]) + (b[i] if i < len(b) else b[-1]) * stacks, 6)
            for i in range(n)
        )

    stacks = float(entry.assumed_stacks) if entry.per_stack is not None else 0.0
    ps = entry.per_stack

    def _eff(field: str) -> float | tuple[float, ...]:
        ev = getattr(entry, field)
        if ps is not None and stacks:
            return _fold(ev, getattr(ps, field), stacks)
        return ev

    base_eff = _eff("base")
    base = tuple(float(x) for x in base_eff) if base_eff else (0.0,)
    kwargs: dict[str, tuple] = {"base": base}
    for fld in (
        "bonus_ad_pct",
        "ap_pct",
        "total_ad_pct",
        "target_max_hp_pct",
        "target_missing_hp_pct",
        "target_current_hp_pct",
    ):
        v = _eff(fld)
        if _present(v):
            kwargs[fld] = _coerce(v)
    if entry.bilinear_terms:
        kwargs["bilinear_terms"] = tuple(
            (float(factor), str(attr_a), str(attr_b))
            for (factor, attr_a, attr_b) in entry.bilinear_terms
        )

    # item 255 conditional-gate fold: scale every coefficient by the documented
    # firing probability so the injected block is the amortized expected
    # magnitude. p == 1.0 (the default for all 23 prior entries) is a no-op =
    # byte-identical. Applied AFTER the per-stack fold so a conditional
    # per-stack entry would scale the already-folded coefficients.
    p = float(entry.conditional_probability)
    if p != 1.0:
        def _scale(t: tuple[float, ...]) -> tuple[float, ...]:
            return tuple(round(x * p, 6) for x in t)
        for key, val in list(kwargs.items()):
            if key == "bilinear_terms":
                kwargs[key] = tuple(
                    (round(factor * p, 6), a, b) for (factor, a, b) in val
                )
            else:
                kwargs[key] = _scale(val)

    return DamageBlock(
        attribute=entry.attribute,
        attribute_kind="damage",
        **kwargs,
    )
