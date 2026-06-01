"""2026-06-01 (GAP 2) - effects-text-only HEAL registry (bilinear AP/AD-on-HP).

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

EXHAUSTED scan (all 171 champs, forms with NO heal block whose
effects_descriptions carry a "heal" + a "per 100 X" + a max/missing "health"):
the BILINEAR self-heal set is exactly the 3 SEEDED below. Documented
EXCLUSIONS (scanned, deliberately NOT seeded):
  - Fiora P Duelist's Dance: the heal is a FLAT "35 : 100 (based on level)"
    (no bilinear term); the bilinear "3% + 4% per 100 bonus AD of max HP" on
    Fiora P is the DAMAGE (true), not the heal. A flat effects-text heal
    belongs in a future LINEAR effects-text-heal registry, not this bilinear
    one.
  - Vladimir Q Transfusion: ALREADY carries a snapshot heal block (the base
    Transfusion heal is scored). The bilinear "5% + 4% per 100 AP of missing
    health" is a CONDITIONAL Crimson-Rush-empowered BONUS heal on top of the
    base - the no-existing-heal-block gate correctly skips it (injecting would
    double-count) and the conditional empowerment is a Phase-D decision.
The other ~54 effects-text heals found in the scan are LINEAR-only (flat /
% AP / % missing HP with no per-100 product) - out of scope for the BILINEAR
lift; a future linear effects-text-heal registry is their home.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_damage_overrides import _per_100

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

    raw_modifiers = tuple(
        {"values": _values_list(value), "units": [str(unit)]}
        for (value, unit) in entry.linear_terms
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
    )
