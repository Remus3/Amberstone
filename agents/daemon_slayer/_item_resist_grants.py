"""Per-item conditional / ramping RESIST-GRANT registry, keyed by item id.

The ITEM-SIDE lane of the champion
``_passive_resist_overrides.resist_grants`` - the FOURTH survivability axis: a
bonus armor / magic-resistance grant that raises the EHP DENOMINATOR DIRECTLY
(added to ``eff_armor`` / ``eff_mr`` BEFORE the ``_armor_factor`` curve), NOT the
numerator. That champion registry is keyed by ``champion_id``, so an ITEM can
never match it - the exact structural gap the ``_item_revive`` /
``_item_survival_window`` / ``_item_spell_shield_overrides`` / ``_item_mana_health``
registries fill for the champion revive / survival-window / spell-shield / mana-HP
axes.

Three entry SHAPES share this registry + the one ``apply_item_resist_grants`` seam:
(1) the RAMPING combat passives below (Jak'Sho / Force of Nature, ``conditional_
probability`` 0.5 at-max-stacks midpoint); (2) R124 (ENGINE 1.212.0) prismatic
ALWAYS-ON percent-of-TOTAL self-amps (Shield of Molten Stone +20% armor, Cloak of
Starry Night +20% MR) at ``conditional_probability=1.0`` (EXACT, no amortization) -
see their inline block in ``_ITEM_RESIST_GRANTS``; (3) the R67-tail LEVEL-SCALED
flat grant (Terminus 3302 "Juxtaposition" Light), whose ``armor`` / ``mr`` carry an
explicit 18-long per-CHAMPION-LEVEL tuple resolved by ``level_scaled`` - the
``_passive_resist_overrides.PassiveResistEntry.level_scaled`` shape, ported to the
item lane.

R67 TAIL (Terminus 3302 Juxtaposition LIGHT) - the filed blocker was STALE. The
``_effects_data`` 3302 note read "Light hits ... stay caster-side and OUT of scope -
no item-keyed resist-grant path exists (_passive_resist_overrides.py is champion-
keyed only); FUTURE". THIS module is that path (it landed 2026-07-11, R106, ENGINE
1.199.0, eight days before the note was re-read), so the Light half is credited here
now. Meraki 16.14.1 items.3302 passive "Juxtaposition", verbatim: "''Light'' hits
grant {{pp|6 to 8 for 3|1;11;14|type=level}} {{as|'''bonus''' armor}} and {{as|
'''bonus''' magic resistance}} while ''Dark'' hits grant 10% {{as|armor
penetration}} and {{as|magic penetration}}, for a total of {{pp|6*3 to 8*3 for 3|
1;11;14}} '''bonus''' resistances and 30% resistances penetration at maximum stacks
of each." -> 6 / 7 / 8 per stack at level breakpoints 1 / 11 / 14, cap 3 stacks, so
the at-max-stacks Light total is 18 / 21 / 24. The tuple encodes those EXPLICIT feed
breakpoints directly rather than an even-thirds ``_step_per_level`` interpolation,
whose boundaries (levels 1 / 7 / 13) would disagree with the feed's 1 / 11 / 14.

ARENA MIRROR 223302 IS DELIBERATELY UNREGISTERED (doctrine B, R161). Its only
on-disk text (``items.json`` DDragon 16.14.1) is "Light Attacks grant Armor and
Magic Resist for 5s" - the grant is NAMED but carries NO magnitude, and
``items_meraki.json`` holds ZERO ``*3302`` mirror rows (only ``3302``). No feed on
disk carries an Arena Light value, so the only way to produce one would be to scale
the SR 18/21/24 by the Dark pen ratio (Arena 8%/stack vs SR 10%/stack) - inheritance
by arithmetic, exactly what doctrine B forbids. The id is enumerated in
``_ITEM_RESIST_UNSOURCED_MIRRORS`` so the R144 coverage guard can tell a knowing
exclusion from the silent-0.0 defect class. Sibling suffix sweep: only ``3302``
(maps 11 / 12 / 21 / 35) and ``223302`` (map 30) exist; map 21 is Nexus Blitz and is
unwired, so the ONE SR row covers SR + ARAM + Brawl.

Mechanic: two current-patch (16.13.1 Meraki) item COMBAT passives grant bonus
resists that RAMP to max stacks in combat and are ABSENT from the resolved stat
block. ``build_champion`` folds only the items' FLAT static resists (Jak'Sho
+45/+45, Force of Nature +55 magic resist), NOT the stacked ramp - a live probe
(R105 / LEDGER 850) confirmed the flat statics fold and the ramp earns ZERO EHP,
and corrected the stale ``ehp.py`` header note that claimed "Voidborn ... flows
through build_champion already ... EHP picks them up automatically":

  * Jak'Sho, The Protean (6665 + Arena mirror 226665) "Voidborn Resilience"
    (verbatim ``items_meraki.json`` 16.13.1): "Gain a stack for each second in
    combat with enemy champions, stacking up to 5 times. At maximum stacks,
    increase your bonus armor and bonus magic resistance by 30% until the end of
    combat." -> a PERCENT-of-BONUS resist grant (``armor_pct`` / ``mr_pct`` with
    ``pct_base="bonus"``, the item-268 champion mode). "Bonus" resist = the
    champion's resist ABOVE base-per-level (items + runes + other passives),
    INCLUDING Jak'Sho's own +45/+45 static stat, matching the tooltip.
  * Force of Nature (4401 + Arena mirror 224401) "Steadfast" (verbatim Meraki
    16.13.1): "Taking magic damage from champions generates a stack ... stacking
    up to 8 times ... At maximum stacks, gain 70 bonus magic resistance and 6%
    bonus movement speed." -> a FLAT +70 magic-resistance add (the item-264 mode).
    MAGIC RESIST ONLY (no armor); the move-speed half is not a survivability
    resist. On this SR base row the old "Dissipate" PERCENT magic damage
    reduction was removed in patch V14.1. The Arena mirror 224401 still names a
    "Dissipate" component in its live 16.14.1 text, but that one grants FLAT
    magic resist + move speed, not a percent DR - so NEITHER row has a percent
    magic DR to credit here (that would be the separate
    ``_passive_mitigation_overrides`` axis anyway).

MIRROR MAGNITUDES ARE READ, NEVER INHERITED (R133). A mode mirror is a RETUNED
item, not a re-skin of its base, so every 22xxxx / 66xxxx row carries the value
parsed from ITS OWN ``description`` in ``data/daemon_slayer/<patch>/items.json``
(DDragon; Meraki carries no mirror rows, so DDragon is the only source). The four
mirror rows below were originally seeded "base nominal" - presence in the item
index was verified, magnitude was not - and THREE of the four were wrong:
226665 is 40% not 30% (under-credited), 224401 is 50 flat MR not 70
(over-credited), and 663059 is 10% not 20% (over-credited). Only 663058 happened
to match its base. Values verified identical in 16.13.1 and 16.14.1, so this was
never patch drift. ``tests/test_item_resist_mirror_magnitudes_r133.py`` pins every
row to its own tooltip so a future "base nominal" copy cannot land silently.

Only the resist MAGNITUDE is modelled per row. The Arena Force of Nature mirror
is a DIFFERENT passive shape (Absorb / Dissipate: max 10 stacks, 7s duration,
enemy immobilizing effects grant 2 extra, one spell adds a stack per second)
rather than the base's 8-stack Steadfast; those stack economics are deliberately
NOT modelled and both rows keep the shared at-max-stacks midpoint.

Only base + Arena (22xxxx) mirrors resolve in the DS item index
(``data/daemon_slayer/16.13.1/items.json``, 706 items) - no ARAM (32xxxx) mirror
of either exists, so ARAM uses the base id. Each of the four ids was confirmed
present in the index before adding.

Why a NEW registry (not the champion ``_passive_resist_overrides``): that registry
is champion-keyed and ``resist_grants`` iterates ``champion_id``, so an item id can
never match it - the same reasoning the sibling item-side registries carry.

Why NOT ``build_champion`` (unlike the always-on flat static resists): the ramp is
CONDITIONAL - it only reaches full value after ramping to max stacks IN COMBAT
(Jak'Sho 5 seconds in combat, FoN 8 stacks of taking magic damage), so it is not a
static stat the resolved block can carry. This lane credits it as a DEFAULT-OFF
opt-in EHP-DENOMINATOR term, amortized by an at-max-stacks midpoint, keeping the
default EHP math BYTE-IDENTICAL and leaving a future live-flip / a ``build_champion``
promotion a separate operator-gated decision (mirrors the sibling item registries).

Amortization (CONDITIONAL, unlike R105's EXACT deterministic mana -> HP): each grant
realizes its full value only AT MAX STACKS, so it is scaled by
``_ITEM_RESIST_STACK_PROB`` - the expected fraction of the modeled fight spent at
max stacks. The resist MAGNITUDE is EXACT Meraki; only the firing midpoint is the
assumption (the champion ``_ACTIVE_RESIST_PROB`` convention). See that constant's
note for the value rationale.

Unique-passive / family semantics: "Voidborn Resilience" and "Steadfast" are UNIQUE
passives, and in a real build a family's base and its Arena mirror are mutually
exclusive (you never hold 6665 AND 226665). A ``family`` tag dedups within a family
so a synthetic build listing both a base and its mirror credits the grant ONCE
(critical for the percent-of-bonus half, where a naive double-add would inflate);
DIFFERENT families (Jak'Sho vs FoN) are distinct unique passives and correctly sum.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_item_resist_grants`` seam on
``compute_ehp`` defaults False; with it OFF both grants are 0.0 and every EHP field
is unchanged. The live default-ON flip is operator-gated (mirrors
``apply_item_spell_shield`` / ``apply_item_mana_health`` / ``apply_passive_resist``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Operator-tunable amortization midpoint for a ramping item resist grant - the
# expected fraction of the modeled sustained fight spent AT MAX STACKS. Both
# grants realize their full value only after ramping (Jak'Sho: 5 seconds in
# combat; FoN: 8 stacks of taking magic damage from champions), so the first
# seconds of a fight are sub-max; but once reached they HOLD (Jak'Sho "until the
# end of combat"; FoN refreshes on continued magic damage). That makes them MORE
# reliably up than a cooldown-gated active (the champion ``_ACTIVE_RESIST_PROB``
# 0.3) yet not always-on like a permanent innate grant (prob 1.0), so 0.5 - the
# midpoint the form-occupancy grant ``_FORM_OCCUPANCY_PROB`` also uses - is the
# conservative default: the ramp-up is offset by the hold-through-the-fight once
# reached. Documented + conservative; Phase D tunes per-item live (each entry
# carries its own ``conditional_probability`` so the two can decouple).
_ITEM_RESIST_STACK_PROB: float = 0.5


# Mode-mirror ids of a REGISTERED carrier that are deliberately NOT priced, so the
# R144 coverage guard (``tests/test_r144_mirror_slice_b.py``) can distinguish a
# knowing exclusion from the silent-0.0 defect class (a registry keyed on bare ids
# missing the mirror ``name_to_id`` actually returns). Membership here is a
# documented DECISION, not a magnitude: every id below contributes 0.0 exactly as an
# unregistered id would. Mirrors ``_item_general_dr._GENERAL_DR_UNSOURCED_MIRRORS``.
#
#   * 223302 - Terminus (Arena, maps.30). Juxtaposition LIGHT. Its DDragon text
#     names the grant ("Light Attacks grant Armor and Magic Resist for 5s") but
#     states NO number, and Meraki carries no ``*3302`` mirror row, so NO on-disk
#     feed holds an Arena Light magnitude. Scaling the SR 18/21/24 by the Dark pen
#     ratio (Arena 8%/stack vs SR 10%/stack) would be inheritance by arithmetic,
#     which doctrine B (R161) forbids. Its DARK half IS credited, in
#     ``_effects_data`` 223302 (``armor_pen_pct=0.24``), from the Arena feed's own
#     8%/stack - that half has a number on disk; this one does not.
_ITEM_RESIST_UNSOURCED_MIRRORS: frozenset[str] = frozenset({"223302"})


@dataclass(frozen=True)
class ItemResistEntry:
    """One item-keyed conditional bonus armor / magic-resistance grant.

    ``armor`` / ``mr`` are flat bonus values (FoN +70 MR), or - when
    ``level_scaled`` is True - a per-CHAMPION-LEVEL tuple read at ``level-1``
    (Terminus Light 18/21/24). ``armor_pct`` / ``mr_pct`` carry a PERCENT (30.0 ==
    30%) of the champion's resist selected by ``pct_base`` ("total" = base + build,
    or "bonus" = build delta = total - base) - Jak'Sho +30% of BONUS armor + MR. An
    entry may carry both the flat and the percent fields; they sum.
    ``conditional_probability`` amortizes the ramp by the expected at-max-stacks
    uptime. ``family`` dedups a base + its Arena mirror (mutually exclusive in a
    real build) so the grant is credited once. ``level_scaled`` (appended at END per
    the dataclass field-append convention) mirrors
    ``_passive_resist_overrides.PassiveResistEntry.level_scaled``.
    """

    armor: float | tuple[float, ...] = 0.0
    mr: float | tuple[float, ...] = 0.0
    armor_pct: float = 0.0
    mr_pct: float = 0.0
    pct_base: str = "total"
    conditional_probability: float = _ITEM_RESIST_STACK_PROB
    family: str = ""
    note: str = ""
    level_scaled: bool = False


_ITEM_RESIST_GRANTS: dict[str, ItemResistEntry] = {
    # Jak'Sho, The Protean - Voidborn Resilience: +30% of BONUS armor + BONUS MR
    # at 5 combat stacks, until end of combat (percent-of-bonus mode).
    "6665": ItemResistEntry(
        armor_pct=30.0, mr_pct=30.0, pct_base="bonus", family="jaksho",
        note="Voidborn Resilience: +30% bonus armor + bonus MR at max (5) stacks",
    ),
    # Arena mirror is RETUNED: lower flat statics (35/35 vs 45/45) bought with a
    # BIGGER percent - 40%, not the base's 30% (R133; was "base nominal" 30.0).
    "226665": ItemResistEntry(
        armor_pct=40.0, mr_pct=40.0, pct_base="bonus", family="jaksho",
        note="Jak'Sho Arena mirror: +40% bonus armor + bonus MR at max (5) stacks"
             " (items.json DDragon 16.14.1, verbatim 'by 40% until end of combat')",
    ),
    # Force of Nature - Steadfast: +70 flat bonus MR at 8 stacks (MR only).
    "4401": ItemResistEntry(
        mr=70.0, family="fon",
        note="Steadfast: +70 flat bonus MR at max (8) stacks; MR only",
    ),
    # Arena mirror is a DIFFERENT passive (Absorb / Dissipate) granting 50 flat
    # MR at 10 stacks, not the base's 70 at 8 (R133; was "base nominal" 70.0).
    # Only the magnitude is modelled - the differing stack economics (max 10, 7s
    # duration, +2 stacks from enemy immobilizing effects, one stack per spell
    # per second) are NOT, and the shared midpoint is kept.
    "224401": ItemResistEntry(
        mr=50.0, family="fon",
        note="Force of Nature Arena mirror Dissipate: +50 flat bonus MR at max"
             " (10) stacks; MR only (items.json DDragon 16.14.1)",
    ),
    # R124 (ENGINE 1.212.0): prismatic ALWAYS-ON percent-of-TOTAL resist self-amps.
    # Unlike Jak'Sho / FoN (which RAMP to max stacks -> prob 0.5 midpoint), these
    # are innate permanent passives -> conditional_probability=1.0 (EXACT, no
    # amortization). Shield of Molten Stone "Immovable as the Earth": +20% of TOTAL
    # armor (items.json DDragon 16.13.1; Meraki-absent). The secondary armor-scaled
    # Block Chance carries no DDragon magnitude and is NOT credited.
    "443058": ItemResistEntry(
        armor_pct=20.0, pct_base="total", conditional_probability=1.0,
        family="molten_stone",
        note="Immovable as the Earth: +20% total armor (always-on); Block Chance secondary uncredited",
    ),
    # Mode mirror (maps.11) is retuned in its FLAT statics (250 HP / 80 armor vs
    # 300 / 100) but its percent is genuinely 20%, matching the base - the one
    # R133 "base nominal" seed that landed on the right value. Verified, not
    # inherited.
    "663058": ItemResistEntry(
        armor_pct=20.0, pct_base="total", conditional_probability=1.0,
        family="molten_stone",
        note="Shield of Molten Stone mode mirror: +20% total armor (always-on),"
             " same percent as base 443058 (items.json DDragon 16.14.1)",
    ),
    # Cloak of Starry Night "Limitless as the Stars": +20% of TOTAL MR (items.json
    # DDragon 16.13.1; Meraki-absent). The secondary MR-scaled non-AA damage
    # reduction (up to 50% cap) is a separate scaling axis with no flat magnitude
    # and is NOT credited here.
    "443059": ItemResistEntry(
        mr_pct=20.0, pct_base="total", conditional_probability=1.0,
        family="starry_night",
        note="Limitless as the Stars: +20% total MR (always-on); MR-scaled non-AA DR secondary uncredited",
    ),
    # Mode mirror (maps.11) is RETUNED to HALF the base percent - 10%, not 20%
    # (R133; was "base nominal" 20.0). Its secondary non-AA DR cap is likewise
    # halved (25% vs 50%) but that axis is uncredited on both rows.
    "663059": ItemResistEntry(
        mr_pct=10.0, pct_base="total", conditional_probability=1.0,
        family="starry_night",
        note="Cloak of Starry Night mode mirror: +10% total MR (always-on),"
             " HALF the base 443059 percent (items.json DDragon 16.14.1);"
             " MR-scaled non-AA DR secondary uncredited",
    ),
    # R67 tail: Terminus "Juxtaposition" LIGHT half - the caster-side bonus armor
    # AND bonus magic resistance. LEVEL-SCALED: Meraki 16.14.1 states 6 to 8 per
    # stack at the explicit level breakpoints 1 / 11 / 14, cap 3 stacks, "for a
    # total of 6*3 to 8*3" -> 18 (L1-10) / 21 (L11-13) / 24 (L14-18), encoded as an
    # explicit 18-tuple so the boundaries match the FEED rather than an even-thirds
    # interpolation. Both axes are equal (the tooltip grants armor and MR together).
    #
    # conditional_probability=1.0 (NOT the registry's ramping 0.5 default). This was
    # a judgement call between two live conventions and the evidence for each:
    #   (a) the registry default, ``_ITEM_RESIST_STACK_PROB = 0.5`` at line 123 of
    #       this file, whose rationale note reads "the expected fraction of the
    #       modeled sustained fight spent AT MAX STACKS ... so the first seconds of
    #       a fight are sub-max".
    #   (b) the ALREADY-SHIPPED DARK half of the SAME tooltip clause, which is
    #       credited at the FULL 3-stack steady state with NO amortization:
    #       ``_effects_data.py:633-634`` sets ``armor_pen_pct=0.30`` /
    #       ``magic_pen_pct=0.30`` (10%/stack x 3), and its note at
    #       ``_effects_data.py:620-623`` justifies that as "the full-stack
    #       sustained-DPS convention (Black Cleaver 3071 5-stack 0.30 shred, Guinsoo
    #       3124 4-stack 0.32 cond-AS)". ``tests/test_pen_pct_catalog_r160.py:105``
    #       pins it: ``"3302": (10.0, 0.30)``.
    # DECISION: (b). Light and Dark are two halves of ONE alternating-basic-attack
    # accrual - same stack cap 3, same 5s window, same trigger. Crediting Light at
    # 0.5 while Dark sits at 1.0 would make one mechanic's two halves disagree
    # inside one engine, and the disagreement would be an artifact of which registry
    # each half happened to land in, not of the game. Convention (a) exists for
    # Jak'Sho / FoN, which ramp on a SLOWER clock (5 seconds in combat / 8 stacks of
    # TAKING magic damage) than a 3-stack alternating on-hit an attacking champion
    # fills in ~6 attacks. The 0.5 default is left untouched for those rows.
    "3302": ItemResistEntry(
        armor=(18.0,) * 10 + (21.0,) * 3 + (24.0,) * 5,
        mr=(18.0,) * 10 + (21.0,) * 3 + (24.0,) * 5,
        conditional_probability=1.0,
        family="terminus",
        level_scaled=True,
        note="Juxtaposition Light: 6 to 8 bonus armor AND bonus MR per stack"
             " (Meraki 16.14.1 pp 1;11;14), cap 3 stacks -> 18 / 21 / 24 at max"
             " stacks; full-stack steady state (prob 1.0) to match the already"
             " credited Dark half of the same clause; Arena mirror 223302"
             " deliberately absent (no on-disk Light magnitude, doctrine B)",
    ),
}


def _value_at_level(
    val: float | tuple[float, ...], level: int, level_scaled: bool
) -> float:
    """Resolve a grant value at the champion level.

    A LOCAL copy of the ``_passive_resist_overrides._value_at_level`` level branch
    (that module's ``rank_scaled`` ability-rank branch has no item analogue, and this
    registry must not depend on the champion registry). ``level_scaled`` reads an
    18-long per-CHAMPION-LEVEL tuple at ``level-1``, clamped to 1..18 by the tuple
    bounds. A flat value is its float; a tuple on a NON-scaled entry defensively
    resolves at its first element (the champion-registry behavior).
    """
    if level_scaled and isinstance(val, (tuple, list)):
        if not val:
            return 0.0
        idx = max(0, min(int(level) - 1, len(val) - 1))
        return float(val[idx])
    if isinstance(val, (tuple, list)):
        return float(val[0]) if val else 0.0
    return float(val)


def item_resist_grants(
    item_ids: Iterable[str | int],
    *,
    total_armor: float,
    total_mr: float,
    base_armor: float,
    base_mr: float,
    level: int = 1,
) -> tuple[float, float]:
    """Return the ``(bonus_armor, bonus_mr)`` item-side conditional resist grant.

    ``total_armor`` / ``total_mr`` are the champion's RESOLVED build resists (base
    per-level + items); ``base_armor`` / ``base_mr`` are the base per-level resists
    - the caller passes both from ``compute_ehp`` (the same values the champion
    ``resist_grants`` receives). The percent-of-bonus grant multiplies
    ``max(0.0, total - base)`` (the bonus resist, clamped so a below-base build
    never yields a negative grant); the percent-of-total grant multiplies the
    resolved total. Each grant is scaled by its entry's
    ``conditional_probability`` (the at-max-stacks midpoint).

    ``level`` selects the per-CHAMPION-LEVEL value on a ``level_scaled`` row
    (Terminus Light 18 / 21 / 24) and is clamped to 1..18 by the tuple bounds; it is
    inert on every flat / percent row (the ``_item_health_stack.item_health_stack_hp``
    level-argument precedent). Default 1 keeps pre-existing callers unchanged.

    A ``family`` tag is credited at most once (a base + its Arena mirror are
    mutually exclusive; crediting both would double-count the percent half).
    Different families sum. Items not in the registry contribute 0. The returned
    values are added to ``eff_armor`` / ``eff_mr`` (the DENOMINATOR) next to the
    champion ``bonus_armor`` / ``bonus_mr``. The default-OFF gating lives in
    ``compute_ehp`` (this function is only called when ``apply_item_resist_grants``
    is True).
    """
    bonus_armor = 0.0
    bonus_mr = 0.0
    seen_families: set[str] = set()
    for iid in item_ids:
        entry = _ITEM_RESIST_GRANTS.get(str(iid))
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        seen_families.add(entry.family)
        prob = entry.conditional_probability
        # Flat add (item-264 mode), level-resolved when ``level_scaled``.
        bonus_armor += _value_at_level(entry.armor, level, entry.level_scaled) * prob
        bonus_mr += _value_at_level(entry.mr, level, entry.level_scaled) * prob
        # Percent-of-resist add (item-268 mode).
        if entry.armor_pct or entry.mr_pct:
            if entry.pct_base == "bonus":
                res_a = max(0.0, total_armor - base_armor)
                res_m = max(0.0, total_mr - base_mr)
            else:
                res_a = max(0.0, total_armor)
                res_m = max(0.0, total_mr)
            bonus_armor += res_a * (entry.armor_pct / 100.0) * prob
            bonus_mr += res_m * (entry.mr_pct / 100.0) * prob
    return bonus_armor, bonus_mr
