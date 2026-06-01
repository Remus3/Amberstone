"""2026-06-01 (GAP 2) - effects-text-only HEAL registry (bilinear + linear).

Item 250 seeded the 3 BILINEAR ``(base% + per100% * stat) * HP`` self-heals
(Viego P / Karma W f1 / Kayn R). Item 251 (the sibling slice) added the LINEAR
effects-text heals: flat ("35 : 100 based on level"), caster-stat-scaled
("+ 20% AP", "5.5% of max HP"), per-level-pct-of-HP, and per-level on a
SPELL slot (Rakan Q / Talon Q, via ``level_scaled``). Same module, same seam,
same consumer - a linear entry simply carries no ``bilinear_terms``.

Item 252 (this slice) adds the PER-CHARGE seam - the heal sibling of the
item-249 per-stack DAMAGE fold. ``per_charge`` linear terms fold *
``assumed_charges`` into ``raw_modifiers`` at BUILD time (zero new eval math);
the coefficients are exact, only the stocked-charge count is the operator-
tunable assumption. The sole per-charge heal is Taric Q Starlight's Touch
(25 + 15% AP + 1% max HP per charge); the only other charge mechanic, Zeri P,
is a DAMAGE charge, not a heal.

UNLIKE the 3 bilinear seeds (every term target/missing-HP scaled -> 0 at the
default ``resolve_target_relative=False``), most linear entries have a FLAT /
caster-stat term that resolves NON-zero even at the default - so
``apply_passive_heal=True`` surfaces them without an HP assumption. The
``apply_passive_heal=False`` DEFAULT (``load_default``) is still byte-identical;
only the opt-in flag path differs from the all-bilinear item-250 story.

Sibling of ``_passive_damage_overrides.py`` (the effects-text-only passive
DAMAGE registry, items 247-249), but for self/ally HEALS that the Meraki
``leveling`` -> ``damage_blocks`` pipeline could not structure. The roster
audit found a class of P/W/R forms that parse to NO ``attribute_kind ==
"heal"`` block (the heal lives only in the form's stripped
``effects_descriptions`` text) yet carry a real heal formula whose dominant
term is a BILINEAR ``(base% + per100% * stat) * HP`` product - an AP / bonus-AD
scaled %-of-HP self-heal that no single linear ``_HEAL_UNIT_TO_CTX`` /
``_TARGET_REL_STAT_KIND`` unit expresses (each of those is one pct * one ctx
stat; the bilinear term is a PRODUCT of two ctx stats: e.g. Viego P's
"2% per 100 AP of the target's maximum health" = AP * target_max_hp).

Why a NEW registry + consumer (not the damage one): the damage registry feeds
``ability_dps`` (it injects ``attribute_kind="damage"`` blocks the damage
evaluator reads from TYPED scaling fields). HEALS feed ``ability_hps``
(``compute_ability_hps``) which reads heal/shield blocks from
``block.raw_modifiers`` (a list of ``{values, units}`` dicts), NOT the typed
fields. So this registry injects ``attribute_kind="heal"`` blocks whose
LINEAR %-of-HP terms ride ``raw_modifiers`` (resolved by the EXISTING v2
``resolve_target_relative`` / ``extra_units`` machinery - the same path the
snapshot missing-HP / target-HP heals already use) and whose BILINEAR terms
ride ``DamageBlock.bilinear_terms`` (the item-248 field, evaluated in
``ability_hps._eval_heal_shield_block`` against a ``bilinear_ctx`` dict).

Why HAND-AUTHORED, not parsed: identical reasoning to the damage registry -
a text-parser mis-extracts the endpoints and re-breaks on each patch's prose
rewrite. We author the exact terms per ``(champion_id, key, form_index)`` from
the verbatim ``effects_descriptions`` fragment cited in each entry's ``note``;
a future patch re-extract re-verifies the cited text rather than re-parsing it.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the seam in ``abilities.py`` injects the
synthetic heal block ONLY when the opt-in ``apply_passive_heal=True`` flag is
passed to ``AbilitiesSnapshot.load`` AND the form has NO existing heal block
(so a snapshot heal is never double-counted). With the flag OFF (the default,
``load_default``) NO synthetic block is appended and the full DS suite is
unchanged.

STRONGER than the damage registry's default story: every seeded heal scales on
a TARGET-relative or CASTER-MISSING-HP quantity (Viego/Kayn = target max HP;
Karma = caster missing HP), which ``compute_ability_hps`` resolves to ZERO
unless the caller opts into ``resolve_target_relative=True`` AND passes the HP
assumption. So even with ``apply_passive_heal=True`` the DEFAULT
``compute_ability_hps`` call (``resolve_target_relative=False``) is byte-
identical - the seeded heals contribute 0 (unresolved lower bound) and the
spell row is skipped. The heal only surfaces under the documented opt-in lower-
bound path (``resolve_target_relative=True`` + ``target_max_hp`` /
``caster_missing_hp_pct``), exactly the v2 ``ability_hps`` contract.

cadence field MEANING (metadata only - does NOT change the injected block):
records the in-game trigger rhythm for a future consumer.
  - "per_cast"   - heal fires once per cast of the (empowered) spell; its
                   per-second contribution = heal_per_cast * the form's
                   cooldown-derived cast rate (Karma W f1 / Kayn R have a
                   cooldown so they contribute per-second).
  - "per_fight"  - one heal per fight window on a takedown/consume event
                   (Viego P fires on a Mist-Wraith consume after a takedown).
                   A passive P-slot has NO cooldown, so ``compute_ability_hps``
                   gives it ``casts_per_sec == 0`` -> heal_per_cast is surfaced
                   but heal_per_sec is honestly 0 (no fixed cadence); routing
                   the on-event cadence to a live clock is a future consumer's
                   job (mirrors the damage registry's on_hit -> AA staging).

How it injects: ``to_heal_block(entry)`` builds a synthetic
``DamageBlock(attribute_kind="heal", raw_modifiers=(...linear...),
bilinear_terms=(...))``. ``_eval_heal_shield_block`` sums the linear
``raw_modifiers`` (via the existing unit maps) + the bilinear products (via
the new ``bilinear_ctx``). Keyed ``(champion_id, key, form_index)`` - same
shape as ``_passive_damage_overrides`` / ``_ability_overrides``.

EXHAUSTED scan (all 171 champs, forms with NO ``attribute_kind=="heal"`` block
whose effects_descriptions carry a "heal"/"restore" verb): 84 candidate forms.
The BILINEAR set is exactly the 3 item-250 seeds; the LINEAR seedable set is the
16 item-251 entries below (14 P-slot + Rakan Q + Talon Q); the item-252
per-charge seam adds Taric Q (the sole per-charge heal). Documented EXCLUSIONS
(scanned, deliberately NOT seeded - with the reason class):
  - VAMP / "% of post-mitigation damage dealt" (not resolvable at rest, same
    boundary as the damage registry's omitted vamp): Aatrox P/E, Briar P,
    DrMundo Q, Gwen P, Kayn P, Morgana P, Vladimir W, Warwick P/R, XinZhao W,
    Aphelios P2, Nilah Q/R, Olaf E.
  - RESOURCE restores (mana / energy / Courage - NOT health): Akali W, Ambessa
    P, Bard P, Brand P, Ezreal W, Fizz W, Hwei W3, Jayce W, Kalista E, Karthus
    E, Kassadin W, Kennen P/E, Kled P/Q, LeeSin P, Malzahar E, Shen E, Smolder
    Q, Syndra P, Velkoz Q, Xerath P, Yuumi E, Zed W (Cho'Gath P's mana half is
    skipped; its 18:52 heal half IS seeded).
  - REVIVE / grey-health conversion (full-HP resurrect or damage-mirror, not a
    recurring castable heal): Anivia P, Pyke P, Rengar W, TahmKench E.
  - BESPOKE products / crit / form gates (no clean linear shape): Kindred W
    (missing-HP * flat), Darius Q (targets-hit * missing-HP), TwistedFate W
    (% crit), Aphelios R (gun-form-gated + spell-slot level), Elise R (heal
    spiderlings to full), Nilah P (heal-amp multiplier). [Taric Q per-charge is
    SEEDED via the item-252 per-charge fold.]
  - Vladimir Q Transfusion: ALREADY carries a snapshot heal block (the no-
    existing-heal-block gate correctly skips it; the Crimson-Rush bonus is a
    Phase-D conditional decision).
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_damage_overrides import _lerp_per_level, _per_100, _step_per_level

# Import the engine DamageBlock lazily in to_heal_block (abilities.py imports
# this module after defining DamageBlock; a top-level import would be circular).


@dataclass(frozen=True)
class PassiveHealEntry:
    """One hand-authored effects-text-only HEAL formula.

    ``linear_terms`` is a tuple of ``(value, unit)`` pairs: ``value`` is a flat
    pct (or a per-level/per-rank tuple) and ``unit`` is a heal unit string
    (``""`` for a flat base, or a ``_HEAL_UNIT_TO_CTX`` / ``_TARGET_REL_STAT_KIND``
    key like ``"% missing health"`` / ``"% of target's maximum health"``). Each
    becomes one ``raw_modifiers`` entry on the synthetic block, resolved by the
    EXISTING ``_eval_heal_shield_block`` unit machinery (so the target-relative
    / caster-missing-HP units stay gated by ``resolve_target_relative`` - the v2
    lower-bound contract).

    ``bilinear_terms`` is a tuple of ``(factor, ctx_attr_a, ctx_attr_b)`` from
    ``_per_100(...)`` - each contributes ``factor * bilinear_ctx[a] *
    bilinear_ctx[b]`` (an AP / bonus-AD scaled %-of-HP product). The HP factor
    of a bilinear term (``caster_missing_hp`` / ``target_max_hp``) is resolved
    to 0 unless the caller opts into ``resolve_target_relative``, so the
    bilinear contribution is gated the same way the linear %-of-HP term is.
    """

    linear_terms: tuple[tuple[float | tuple[float, ...], str], ...]
    cadence: str
    note: str
    attribute: str = "Passive Heal"
    bilinear_terms: tuple[tuple[float, str, str], ...] = ()
    # When True the synthetic heal block's per-rank ``values`` lists are read
    # at champion LEVEL (level-1), not the spell rank - for a SPELL-slot
    # (Q/W/E/R) heal whose magnitude scales "based on level" (Rakan Q / Talon
    # Q). P-slot heals already see ``rank == level-1`` so they leave this False.
    level_scaled: bool = False
    # GAP-2 per-charge heal seam (item 252 schema lift, mirrors the item-249
    # per-stack DAMAGE fold): ``per_charge`` is a tuple of ``(value, unit)``
    # linear terms read "per charge" (same shape + unit maps as ``linear_terms``;
    # ``value`` flat or a per-level/per-rank tuple). ``to_heal_block`` FOLDS each
    # into ``raw_modifiers`` as ``value * assumed_charges`` at BUILD time - so the
    # existing ``_eval_heal_shield_block`` needs ZERO new math (the per-charge
    # contribution collapses into ordinary raw_modifiers once the count is fixed).
    # ``assumed_charges`` is the operator-tunable steady-state stock (the
    # per-charge COEFFICIENTS are exact; only the count is the assumption); a
    # future live consumer feeds the real stocked-charge count. Default () / 0.0
    # = no per-charge term (every prior entry unaffected, byte-identical).
    per_charge: tuple[tuple[float | tuple[float, ...], str], ...] = ()
    assumed_charges: float = 0.0


# (champion_id, key, form_index) -> PassiveHealEntry.
# Seeded 2026-06-01 against verbatim effects_descriptions at patch 16.11.1.
# The BILINEAR self-heal set (exhaustive). Every term is exact for the modeled
# clause; documented per-entry caveats name the omitted / conditional pieces.
_PASSIVE_HEAL_OVERRIDES: dict[tuple[str, str, int], PassiveHealEntry] = {
    # Viego P Sovereign's Domination: on consuming a Mist Wraith (spawned on an
    # enemy-champion takedown) Viego "heals himself for 2% (+ 2.5% per 100 bonus
    # AD) (+ 2% per 100 AP) (+ 5% per 100% bonus attack speed) of the target's
    # maximum health". 3 modeled terms: flat 2% target max HP + 2.5%/100 bonus
    # AD + 2%/100 AP (both bilinear * target max HP). The 5% per 100% BONUS
    # ATTACK SPEED term is OMITTED: AbilityContext carries no bonus-AS stat for
    # the heal block, so it belongs in a future AS-aware seam (same boundary as
    # the damage registry's omitted crit terms - exact for the modeled terms).
    # cadence per_fight (takedown-gated consume); a passive P has no cooldown so
    # compute_ability_hps gives heal_per_sec 0 - the per-cast heal is surfaced,
    # the on-consume cadence routing is a future live consumer's job.
    ("Viego", "P", 0): PassiveHealEntry(
        linear_terms=((2.0, "% of target's maximum health"),),
        bilinear_terms=(
            _per_100(2.5, "bonus_ad", "target_max_hp"),
            _per_100(2.0, "ap", "target_max_hp"),
        ),
        cadence="per_fight",
        note="Sovereign's Domination: heal 2% (+ 2.5% per 100 bonus AD) (+ 2% per 100 AP) of target max HP on Mist-Wraith consume; +5% per 100% bonus-AS term omitted (no AS ctx on a heal block); takedown-gated per_fight cadence (passive -> heal_per_sec 0)",
        attribute="Sovereign's Domination",
    ),
    # Karma W form 1 (Renewal, the Mantra-empowered W): "Karma heals for 17%
    # (+ 1% per 100 AP) of her missing health once on-cast, and again once the
    # tether lasts its full duration or the target dies while tethered." We
    # model the guaranteed ON-CAST heal (1x): flat 17% caster missing HP +
    # 1%/100 AP bilinear * caster missing HP. The SECOND heal (on tether-
    # complete / target death) is conditional and OMITTED (a future cadence /
    # conditional decision). form_index 1 = the empowered W, so a consumer must
    # route W -> 1 via form_index_overrides to see it (default walks W form 0,
    # Focused Resolve, which has no heal). Missing-HP scaled -> resolves to 0 at
    # the default full-HP ctx (the documented lower-bound contract).
    ("Karma", "W", 1): PassiveHealEntry(
        linear_terms=((17.0, "% missing health"),),
        bilinear_terms=(_per_100(1.0, "ap", "caster_missing_hp"),),
        cadence="per_cast",
        note="Renewal: heal 17% (+ 1% per 100 AP) of caster missing HP on-cast of the Mantra-empowered W (form 1); the 2nd on-tether-complete heal omitted (conditional); missing-HP scaled (0 at full HP, resolves under resolve_target_relative)",
        attribute="Renewal",
    ),
    # Kayn R Umbral Trespass (Darkin/Rhaast bonus): "Darkin Bonus: Umbral
    # Trespass ... also heals Rhaast for 11.25% (+ 7.5% per 100 bonus AD) of the
    # target's maximum health after the recast's delay." flat 11.25% target max
    # HP + 7.5%/100 bonus AD bilinear * target max HP. FORM-CONDITIONAL: the
    # heal exists ONLY in Rhaast (Darkin) form; the Shadow Assassin form heals
    # nothing. The snapshot has one R form (f0) covering both, so injecting
    # default-credits both - the form gate is NOT modeled (the magnitude is
    # gate-independent, same precedent as Zed P's below-50%-HP fire gate in the
    # damage registry). cadence per_cast (the ult has a cooldown -> per-second).
    ("Kayn", "R", 0): PassiveHealEntry(
        linear_terms=((11.25, "% of target's maximum health"),),
        bilinear_terms=(_per_100(7.5, "bonus_ad", "target_max_hp"),),
        cadence="per_cast",
        note="Umbral Trespass (Darkin): heal 11.25% (+ 7.5% per 100 bonus AD) of target max HP; Rhaast/Darkin-form-only (Shadow Assassin heals nothing) - form gate not modeled (magnitude gate-independent, Zed-P precedent)",
        attribute="Umbral Trespass",
    ),
    # ---- LINEAR effects-text heals (item 251, the sibling slice to the 3
    # bilinear seeds above). Each is flat / caster-stat-scaled / per-level-pct
    # of HP with NO per-100 product. Authored from verbatim 16.11.1
    # effects_descriptions. The flat / caster-stat terms resolve NON-zero at the
    # default (resolve_target_relative=False) - unlike the bilinear seeds - so
    # apply_passive_heal=True surfaces them even without an HP assumption; the
    # apply_passive_heal=False DEFAULT stays byte-identical. P-slot heals use the
    # 18-element per-LEVEL tuple (rank == level-1); the 2 SPELL-slot level-scaled
    # heals (Rakan Q / Talon Q) set level_scaled=True so the per-level tuple is
    # indexed by level, not the spell rank. ----
    # Ahri P Essence Theft: at 9 stacks consume to "heal herself for 35 : 95
    # (based on level) (+ 20% AP)". The 2nd takedown-within-3s heal (75 : 165 +
    # 30% AP) is a separate conditional event, OMITTED (model the guaranteed
    # 9-stack consume). per_fight (stack-consume; passive -> heal_per_sec 0).
    ("Ahri", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(35.0, 95.0), ""), (20.0, "% ap")),
        cadence="per_fight",
        note="Essence Theft: heal 35 : 95 (based on level) (+ 20% AP) on 9-stack consume; the 2nd takedown-gated heal (75 : 165 + 30% AP) omitted (conditional)",
        attribute="Essence Theft",
    ),
    # Alistar P Triumphant Roar: at 7 stacks "heal himself for 5% of his maximum
    # health and nearby allied champions for 7%". Model the 5% SELF heal (the
    # 7% ally heal is a separate target). per_fight (stack-consume).
    ("Alistar", "P", 0): PassiveHealEntry(
        linear_terms=((5.0, "% maximum health"),),
        cadence="per_fight",
        note="Triumphant Roar: heal 5% of caster max HP on 7-stack consume; the 7% ally heal omitted (different target)",
        attribute="Triumphant Roar",
    ),
    # Aurora P Spirit Abjuration: "For each active Spirit, Aurora is healed for
    # 3 : 20 (based on level) (+ 2% AP) every second" (max per tick 12 : 80 + 8%
    # AP at 4 Spirits). Model the PER-SPIRIT value (lower bound, 1 Spirit); the
    # per-tick max is up to 4x at full Spirits. per_cast (every second).
    ("Aurora", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(3.0, 20.0), ""), (2.0, "% ap")),
        cadence="per_cast",
        note="Spirit Abjuration: heal 3 : 20 (based on level) (+ 2% AP) per active Spirit per second (lower bound, 1 Spirit; up to 4x at 4 Spirits)",
        attribute="Spirit Abjuration",
    ),
    # Cho'Gath P Carnivore: "Whenever Cho'Gath kills an enemy, it heals for 18 :
    # 52 (based on level)" (+ a separate mana restore, ignored). flat per-level.
    # per_fight (on-kill).
    ("Chogath", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(18.0, 52.0), ""),),
        cadence="per_fight",
        note="Carnivore: heal 18 : 52 (based on level) on enemy kill; mana restore ignored (resource, not health)",
        attribute="Carnivore",
    ),
    # Evelynn P Demon Shade: "While below 250 : 590 (+ 250% AP) health, Evelynn
    # heals herself for 15 : 150 (based on level) every second". The below-
    # threshold gate is NOT modeled (the heal magnitude is gate-independent,
    # Warwick-P / Zed-P precedent). per_cast (every second).
    ("Evelynn", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(15.0, 150.0), ""),),
        cadence="per_cast",
        note="Demon Shade: heal 15 : 150 (based on level) per second while below the HP threshold; threshold gate not modeled (magnitude gate-independent)",
        attribute="Demon Shade",
    ),
    # Fiora P Duelist's Dance: triggering a Vital "heals Fiora for 35 : 100
    # (based on level)" (the bilinear "3% + 4% per 100 bonus AD of max HP" on the
    # same passive is the DAMAGE, not the heal - excluded here, lives in the
    # damage path). flat per-level. per_cast (Vital trigger).
    ("Fiora", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(35.0, 100.0), ""),),
        cadence="per_cast",
        note="Duelist's Dance: heal 35 : 100 (based on level) on Vital trigger; the bilinear %-HP term on this passive is the DAMAGE not the heal",
        attribute="Duelist's Dance",
    ),
    # Gragas P Happy Hour: "after casting an ability, Gragas heals himself for
    # 5.5% of his maximum health". flat % max HP. per_cast (after ability).
    ("Gragas", "P", 0): PassiveHealEntry(
        linear_terms=((5.5, "% maximum health"),),
        cadence="per_cast",
        note="Happy Hour: heal 5.5% of caster max HP after casting an ability",
        attribute="Happy Hour",
    ),
    # Lillia P Dream-Laden Bough: "heals herself for ... 6 : 90 (based on level)
    # (+ 30% AP) against champions" (the vs-large-monster 39 + 15% AP + the per-
    # 0.5s variant are alternates, not modeled). flat per-level + 30% AP.
    ("Lillia", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(6.0, 90.0), ""), (30.0, "% ap")),
        cadence="per_cast",
        note="Dream-Laden Bough: heal 6 : 90 (based on level) (+ 30% AP) vs champions; vs-monster + per-0.5s-tick variants omitted",
        attribute="Dream-Laden Bough",
    ),
    # Maokai P Sap Magic: empowered AA "heal him for 4% : 12.8% (based on level)
    # maximum health". per-LEVEL pct of caster max HP. per_cast (empowered AA).
    ("Maokai", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(4.0, 12.8), "% maximum health"),),
        cadence="per_cast",
        note="Sap Magic: heal 4% : 12.8% (based on level) of caster max HP on the empowered basic attack",
        attribute="Sap Magic",
    ),
    # Rek'Sai P Fury of the Xer'Sai: on Burrow "consumes her current Fury ... to
    # heal for up to 10% : 20% (based on level) maximum health at 100 Fury".
    # per-LEVEL pct of caster max HP (the at-100-Fury max). per_fight (Fury
    # consume).
    ("RekSai", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(10.0, 20.0), "% maximum health"),),
        cadence="per_fight",
        note="Fury of the Xer'Sai: heal 10% : 20% (based on level) of caster max HP at 100 Fury on Burrow (max-Fury value)",
        attribute="Fury of the Xer'Sai",
    ),
    # Swain P Ravenous Flock: claiming a Soul Fragment "heal for 3% : 6% (based
    # on level) of his maximum health". per-LEVEL pct of caster max HP.
    # per_fight (soul-fragment claim).
    ("Swain", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(3.0, 6.0), "% maximum health"),),
        cadence="per_fight",
        note="Ravenous Flock: heal 3% : 6% (based on level) of caster max HP on claiming a Soul Fragment",
        attribute="Ravenous Flock",
    ),
    # Trundle P King's Tribute: "Whenever a nearby enemy dies, Trundle heals
    # himself for 1.8% : 5.5% (based on level) of the target's maximum health".
    # per-LEVEL pct of TARGET max HP -> resolves to 0 at the default full-HP ctx
    # (the lower-bound contract, like the bilinear seeds). per_fight (on death).
    ("Trundle", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(1.8, 5.5), "% of target's maximum health"),),
        cadence="per_fight",
        note="King's Tribute: heal 1.8% : 5.5% (based on level) of TARGET max HP on a nearby enemy death; target-relative -> 0 at full HP, resolves under resolve_target_relative",
        attribute="King's Tribute",
    ),
    # Xin Zhao P Determination: 3rd stack on-hit "heal Xin Zhao for 3% / 3.5% /
    # 4% (based on level) of his maximum health (+ 65% AP)". 3-tier LEVEL step
    # pct of caster max HP + flat 65% AP. per_cast (on-hit 3rd stack).
    ("XinZhao", "P", 0): PassiveHealEntry(
        linear_terms=(
            (_step_per_level((3.0, 3.5, 4.0)), "% maximum health"),
            (65.0, "% ap"),
        ),
        cadence="per_cast",
        note="Determination: heal 3% / 3.5% / 4% (based on level) of caster max HP (+ 65% AP) on the 3rd-stack on-hit; even-thirds level boundaries (step estimate)",
        attribute="Determination",
    ),
    # Yuumi P Bop 'n' Block: the periodic empowered hit "heal her for 20 : 110
    # (based on level) (+ 25% AP)". flat per-level + 25% AP. per_cast (periodic).
    ("Yuumi", "P", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(20.0, 110.0), ""), (25.0, "% ap")),
        cadence="per_cast",
        note="Bop 'n' Block: heal 20 : 110 (based on level) (+ 25% AP) on the periodic empowered hit; the same-amount ally heal omitted (different target)",
        attribute="Bop 'n' Block",
    ),
    # Rakan Q Boisterous Bravado: "Rakan heals himself and nearby allied
    # champions for 40 : 210 (based on level) (+ 55% AP)". SPELL-slot heal that
    # scales by LEVEL (not Q rank) -> level_scaled=True so the 18-element tuple
    # is indexed by level. flat per-level + 55% AP. per_cast.
    ("Rakan", "Q", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(40.0, 210.0), ""), (55.0, "% ap")),
        cadence="per_cast",
        note="Boisterous Bravado: heal 40 : 210 (based on level) (+ 55% AP) after the Q radius delay; SPELL-slot level-scaled (level_scaled indexes by level not Q rank)",
        attribute="Boisterous Bravado",
        level_scaled=True,
    ),
    # Talon Q Noxian Diplomacy: "If Noxian Diplomacy kills the target, Talon
    # heals for 9 : 55 (based on level)". SPELL-slot LEVEL-scaled flat ->
    # level_scaled=True. per_fight (on-kill).
    ("Talon", "Q", 0): PassiveHealEntry(
        linear_terms=((_lerp_per_level(9.0, 55.0), ""),),
        cadence="per_fight",
        note="Noxian Diplomacy: heal 9 : 55 (based on level) on a Q kill; SPELL-slot level-scaled (level_scaled indexes by level not Q rank); kill-gated per_fight",
        attribute="Noxian Diplomacy",
        level_scaled=True,
    ),
    # ---- PER-CHARGE effects-text heal (item 252, the per-charge seam - the
    # heal sibling of the item-249 per-stack DAMAGE fold). The per-charge terms
    # fold * assumed_charges at build time; the COEFFICIENTS are exact, only the
    # stock count is the operator-tunable assumption. ----
    # Taric Q Starlight's Touch: "Active: Taric heals himself and nearby allied
    # champions for 25 (+ 15% AP) (+ 1% of his maximum health) per charge of
    # Starlight's Touch that he periodically stocks, up to a maximum amount"
    # (max 125 + 75% AP + 5% max HP at 5 charges). The 3 PER-CHARGE terms (flat
    # 25 + 15% AP + 1% caster max HP) fold * assumed_charges. Q RANK sets the MAX
    # charges (Maximum Charges block = 1/2/3/4/5 by rank); assumed_charges 3.0 =
    # typical mid-fight stock (operator-tunable; true cap = Q rank, 5 at rank 5,
    # so 3.0 over-credits Q rank 1/2 - the same steady-state-midpoint
    # approximation class as the item-249 assumed_stacks). The SELF heal is
    # modeled; the ally heal is the same per-charge amount on a different target
    # (omitted). All terms flat / caster-stat -> resolve NON-zero at the default
    # (no HP assumption needed, like the other linear caster-stat seeds); the
    # apply_passive_heal=False DEFAULT stays byte-identical. per_cast (Q has a
    # cooldown -> heal_per_sec is computed). NO existing heal block on Taric Q
    # (only a "Maximum Charges" attribute_kind="other" block), so the seam's
    # no-existing-heal-block gate admits it.
    ("Taric", "Q", 0): PassiveHealEntry(
        linear_terms=(),
        per_charge=(
            (25.0, ""),
            (15.0, "% ap"),
            (1.0, "% maximum health"),
        ),
        assumed_charges=3.0,
        cadence="per_cast",
        note="Starlight's Touch: heal 25 (+ 15% AP) (+ 1% of caster max HP) per charge (cap = Q rank, max 5; assumed_charges 3.0 = mid-fight stock, operator-tunable); ally heal omitted (same per-charge amount, different target)",
        attribute="Starlight's Touch",
    ),
}


def to_heal_block(entry: PassiveHealEntry):
    """Build a synthetic ``DamageBlock(attribute_kind="heal", ...)`` from a
    ``PassiveHealEntry``.

    The block carries the LINEAR %-of-HP terms in ``raw_modifiers`` (the
    ``{values, units}`` shape ``_eval_heal_shield_block`` parses - so the
    target-relative / caster-missing-HP units stay gated by the existing v2
    ``resolve_target_relative`` machinery) and the BILINEAR products in
    ``bilinear_terms`` (the item-248 field, summed in
    ``_eval_heal_shield_block`` against ``bilinear_ctx``). A linear ``value``
    that is a tuple is emitted as a per-rank ``values`` list; a flat float is a
    1-element list (``_value_at_rank`` clamps it to that value at every rank).

    Imported lazily to avoid the abilities.py circular import.
    """
    from .abilities import DamageBlock

    def _values_list(v: float | tuple[float, ...]) -> list[float]:
        if isinstance(v, (tuple, list)):
            return [float(x) for x in v] or [0.0]
        return [float(v)]

    def _scale_value(
        v: float | tuple[float, ...], mult: float
    ) -> float | tuple[float, ...]:
        if isinstance(v, (tuple, list)):
            return tuple(float(x) * mult for x in v)
        return float(v) * mult

    raw_modifiers = tuple(
        {"values": _values_list(value), "units": [str(unit)]}
        for (value, unit) in entry.linear_terms
    )
    # item 252 per-charge fold: each per_charge (value, unit) becomes one
    # raw_modifiers entry scaled by assumed_charges at BUILD time, so the
    # existing eval reads it as an ordinary linear term (zero new eval math).
    # No per_charge terms / assumed_charges 0 -> contributes nothing.
    charges = float(entry.assumed_charges) if entry.per_charge else 0.0
    if charges:
        raw_modifiers = raw_modifiers + tuple(
            {
                "values": _values_list(_scale_value(value, charges)),
                "units": [str(unit)],
            }
            for (value, unit) in entry.per_charge
        )
    bilinear_terms = tuple(
        (float(factor), str(attr_a), str(attr_b))
        for (factor, attr_a, attr_b) in entry.bilinear_terms
    )
    return DamageBlock(
        attribute=entry.attribute,
        attribute_kind="heal",
        raw_modifiers=raw_modifiers,
        bilinear_terms=bilinear_terms,
        level_scaled=entry.level_scaled,
    )
