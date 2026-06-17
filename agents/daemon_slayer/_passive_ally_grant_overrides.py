"""2026-06-03 (GAP 2) - effects-text ALLY-TARGETED survivability grant registry.

The SIXTH survivability axis, and the FIRST that scores a DIFFERENT champion
than the caster. The five SELF axes - heal + shield THROUGHPUT
(``ability_hps``), a flat-% damage-reduction DENOMINATOR multiplier
(``_passive_mitigation_overrides``), a resist-stat DENOMINATOR add
(``_passive_resist_overrides``), and a death-triggered second-life NUMERATOR
multiplier (``_passive_revive_overrides``) - all raise the CASTER's own
Effective HP. An ALLY-TARGETED grant rides a TEAMMATE: the value the granter's
ability confers is added to the PROTECTED ALLY's Effective HP, not the
granter's. This is the "the grant rides an ally, not the caster - the Orianna-E
ball-attached class" that the item-264..272 resist registry AND the item-288
revive registry both flagged as the remaining survivability exclusion.

Two ally sub-axes - the ally analogs of the just-completed self resist
(items 264-272) and self revive (item 288):

  - ALLY RESIST: bonus armor / magic resistance the granter confers on a
    teammate (Orianna E ball, Braum W base, Taric W tether). It raises the
    PROTECTED ALLY's armor / MR DENOMINATOR (added before the resistance curve),
    exactly like the self resist registry but applied to the ally. The flat
    halves (Orianna, Braum) are self-contained granter-side constants; the Taric
    percent half is a percent of the GRANTER's own armor, so it resolves only
    when the granter's resolved armor is supplied (mirrors the item-268
    percent-of-resist mode, but keyed on the GRANTER not the scored champion).

  - ALLY REVIVE: a death-triggered second HP pool the granter confers on a
    teammate (Renata W Bailout, restored to 100% max health). A NUMERATOR
    multiplier on the PROTECTED ALLY's Effective HP, exactly like the self revive
    registry (item 288) but applied to the ally.

The CONSUMER seam is GENERIC: ``compute_ehp`` gains ``external_resist_armor`` /
``external_resist_mr`` / ``external_revive_multiplier`` (default 0.0 / 0.0 / 1.0
= byte-identical). The PROTECTED ally's Effective HP is computed by feeding these
from a granter's registry value - ``ally_resist_grant("Orianna", level, True)``
-> (armor, mr) -> ``compute_ehp(ally, external_resist_armor=armor,
external_resist_mr=mr)``. The grant value is sourced HERE; the application is the
same armor/MR-before-curve and numerator-multiplier math the self axes use. The
auto-pairing (which live ally is protected by which granter mid-fight) is the
future Phase D consumer job; this registry ships the granter-side grant values
plus the single application seam, byte-identical at its default (the established
"registry + one seam behind a default-off flag" pattern).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the aggregators return (0.0, 0.0) / 1.0 when
``apply_ally_grant`` is False (the default), and ``compute_ehp``'s external
params default to the no-op 0.0 / 0.0 / 1.0. Opt-in everywhere (mirrors
``apply_passive_resist`` / ``apply_passive_revive``).

EXHAUSTIVE roster scan (all 171 champs, every ability form whose
affects=Allies + effects_descriptions / parsed block carry a survivability grant
that RIDES a teammate). The clean ally-grant set is:
  - Orianna E Command: Protect: "The Ball grants bonus armor and bonus magic
    resistance to the unit it is attached to." 6/12/18/24/30 armor + MR by E rank
    (the "Bonus Resistances" block); flat, self-contained. The 2.5s shield on
    arrival is ``ability_hps`` THROUGHPUT, not this axis.
  - Braum W Stand Behind Me: "grants himself and the ally bonus armor and bonus
    magic resistance". Ally base 20/25/30/35/40 armor + MR by W rank (the "Ally
    Bonus Armor" block series[0]); the +12%-of-bonus second series is OMITTED
    (cross-champion, no ally-bonus ctx on the seam). 3s active -> amortized.
  - Taric W Bastion: "the ally also gains the bonus armor" = 6/7/8/9/10% of
    Taric's TOTAL armor by W rank (ARMOR ONLY, the percent-of-GRANTER mode). The
    flat MR is 0 (Bastion is armor only, matching the self Taric W entry).
    Permanent tether -> prob 1.0.
  - Renata W Bailout: "restored to 100% of their maximum health" on a fatal hit.
    revived_fraction 1.0 (the Anivia-P shape, no ally-HP dependency); gated on
    the burn (a takedown during the burn must arrive or the ally dies anyway) ->
    amortized at the ally-revive midpoint.

Documented EXCLUSIONS (scanned, deliberately NOT seeded - with the reason
class):
  - ALLY SHIELDS / HEALS (Orianna E's 2.5s shield, every enchanter shield/heal -
    Janna / Lulu / Karma / Yuumi / Soraka ...) are survivability THROUGHPUT
    already scored by ``ability_hps`` (the enchanter scorer); an amount of HP is
    not a resist-denominator add nor a numerator multiplier - a different,
    shipped axis.
  - ALLY DAMAGE-IMMUNITY / DEATH-PREVENTION windows: Taric R Cosmic Radiance
    (invulnerability), Kindred R Lamb's Respite (no-unit-can-die zone), Kayle R
    Divine Judgment (invulnerability), Galio R Hero's Entrance (a brief shield +
    knockup - shield is throughput), Tahm Kench R Devour / Kalista R Fate's Call
    / Ryze R Realm Warp (reposition / untargetable), Yuumi W (attach
    untargetable), Zilean R's 3s invuln-then-revive window: a binary "cannot take
    damage / cannot die" window is NOT a finite Effective-HP multiplier (it would
    be infinite EHP), so it is a DIFFERENT seam (a guaranteed-survival window, the
    ally analog of the self invulnerability the DR registry excluded) - NOT
    modeled as an EHP term here.
  - FLAT-HEAL / BASE-HP ally revives whose second-life FRACTION needs the
    protected ally's max HP: Zilean R Chronoshift (revives + heals a flat amount
    by rank) and Akshan W Going Rogue (resurrects dead allies to base + restored
    health). The restored HP is a flat amount, so its fraction of the ally's max
    HP is build-dependent on the PROTECTED ALLY (not a granter-side constant) AND
    the heal value is absent from the parsed Meraki block (the items 147-153
    parse-strip boundary). Deferred to the Phase D consumer that resolves the live
    ally build. Renata W is seeded because it restores a clean 100% of max health
    (fraction 1.0) with no ally-HP dependency.
  - Ornn P Living Forge: a false-positive scan hit - it upgrades ITEMS into
    Masterwork variants with bonus stats, it does not grant an ally a resist.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ._passive_resist_overrides import _ACTIVE_RESIST_PROB, _value_at_level

# Operator-tunable midpoint for an ally REVIVE (the expected fraction of the
# modeled fight in which the granted second life BOTH triggers AND results in a
# sustained life). Below the self-revive 0.4 (_passive_revive_overrides) because
# Renata W's revive is more conditional than Anivia / Zac: the restored ally
# still dies to the true-damage burn unless a takedown lands during the burn
# window, so the second life often does NOT persist. Documented + conservative;
# Phase D feeds the live takedown-likelihood without re-authoring. Parallel to
# ``_passive_revive_overrides._REVIVE_PROB`` / ``_ACTIVE_RESIST_PROB``.
_ALLY_REVIVE_PROB = 0.3

# DSP7 (2026-06-17, ENGINE 1.133.0): operator-tunable midpoint for an ally
# SHIELD / HEAL flat-HP grant - the expected fraction of the modeled fight in
# which the granted shield / heal HP is PRESENT on the protected ally. A short
# enchanter shield (Janna E / Lulu E) decays if not consumed and a heal restores
# burst HP, but both reapply on a short cooldown, so the grant sits between the
# 0.3 short-active (Braum W ``_ACTIVE_RESIST_PROB``) and a 1.0 permanent tether -
# the 0.5 availability midpoint (the ``_ALLYAMP_CONDITIONAL_PROB`` shape).
# Conservative + documented; a Phase D consumer feeds the live re-apply cadence
# without re-authoring.
_ALLY_SHIELD_HEAL_PROB = 0.5


@dataclass(frozen=True)
class AllyGrantEntry:
    """One hand-authored effects-text ally-targeted survivability grant.

    ALLY RESIST half - bonus armor / MR the granter confers on a TEAMMATE:
      ``armor`` / ``mr`` (flat add, self-contained granter-side constant; a
      per-ABILITY-RANK tuple when ``rank_scaled``), and ``armor_pct`` / ``mr_pct``
      (a PERCENT of the GRANTER's resolved resist, ``pct_base`` "total" or
      "bonus"; resolves only when the granter's resists are supplied to
      ``ally_resist_grant``).

    ALLY REVIVE half - a death-triggered second HP pool the granter confers on a
      TEAMMATE: ``revived_hp_fraction`` is the fraction of the ALLY's max HP the
      ally is restored to (Renata 1.0 = 100% max health), so the ally's second
      Effective-HP pool is that fraction of its first - ``ally_revive_multiplier``
      returns ``1 + revived_hp_fraction(level) * conditional_probability``.

    ``conditional_probability`` amortizes a short active / a gated revive by its
    expected uptime+success midpoint (a permanent grant uses 1.0).

    ``rank_scaled`` (item 267 convention): the value is a per-ABILITY-RANK tuple
    resolved from the champion level via the engine-default skill priority.
    ``level_scaled``: a per-CHAMPION-LEVEL tuple read at ``level-1``. Mutually
    exclusive; rank is checked first.
    """

    armor: float | tuple[float, ...] = 0.0
    mr: float | tuple[float, ...] = 0.0
    armor_pct: float | tuple[float, ...] = 0.0
    mr_pct: float | tuple[float, ...] = 0.0
    pct_base: str = "total"
    revived_hp_fraction: float | tuple[float, ...] = 0.0
    conditional_probability: float = 1.0
    rank_scaled: bool = False
    level_scaled: bool = False
    attribute: str = "Ally Grant"
    note: str = ""
    # DSP7 (2026-06-17): ally SHIELD / HEAL flat-HP grant - the THIRD EHP-grant
    # mode (after the resist DENOMINATOR add + the revive NUMERATOR multiplier):
    # a flat HP an enchanter CONFERS on a protected ally, modeled as an EHP
    # NUMERATOR ADD (a shield / heal rides the SAME armor/MR curve as base HP, so
    # +H raw HP scales every per-type EHP exactly like +H max HP). Used ONLY by
    # the separate ``_ALLY_FLAT_HP_GRANT_OVERRIDES`` registry + ``ally_flat_hp_
    # grant``; the 4 item-289 resist/revive entries leave both 0.0 (byte-
    # identical). A per-ABILITY-RANK tuple when ``rank_scaled``.
    shield_hp: float | tuple[float, ...] = 0.0
    heal_hp: float | tuple[float, ...] = 0.0


# (champion_id, key, form_index) -> AllyGrantEntry. Keyed for parity with the
# self heal/shield/DR/resist/revive registries. Seeded 2026-06-03 against verbatim
# effects_descriptions + parsed blocks at patch 16.11.1.
_PASSIVE_ALLY_GRANT_OVERRIDES: dict[tuple[str, str, int], AllyGrantEntry] = {
    # Orianna E Command: Protect: "Passive: The Ball grants bonus armor and bonus
    # magic resistance to the unit it is attached to." 6/12/18/24/30 armor + MR by
    # E rank (the parsed "Bonus Resistances" [other] block). Flat, self-contained
    # (no granter / ally build dependency). prob 1.0 = the value WHILE the ball is
    # attached (the scenario the protected ally's EHP frame models; live attach
    # rate is a Phase D gate). The 2.5s shield on arrival is ability_hps
    # throughput, NOT this axis. rank_scaled (E priority_3).
    ("Orianna", "E", 0): AllyGrantEntry(
        armor=(6.0, 12.0, 18.0, 24.0, 30.0),
        mr=(6.0, 12.0, 18.0, 24.0, 30.0),
        conditional_probability=1.0,
        note="Command: Protect: 6/12/18/24/30 ally armor + MR by E rank (Bonus Resistances block); flat self-contained; value while the ball is attached (prob 1.0); 2.5s shield is ability_hps throughput; rank_scaled (E priority_3)",
        attribute="Command: Protect",
        rank_scaled=True,
    ),
    # Braum W Stand Behind Me: "grants himself and the ally bonus armor and bonus
    # magic resistance for 3 seconds." Ally base 20/25/30/35/40 armor + MR by W
    # rank (the parsed "Ally Bonus Armor" block series[0]); the +12%-of-bonus
    # second series is OMITTED (cross-champion, no ally-bonus ctx on the seam,
    # the item-264/270 boundary). 3s active -> amortized at the active midpoint.
    # rank_scaled (W priority_2). The SELF half of the same grant is the
    # _passive_resist_overrides Braum W entry; this is the ALLY copy.
    ("Braum", "W", 0): AllyGrantEntry(
        armor=(20.0, 25.0, 30.0, 35.0, 40.0),
        mr=(20.0, 25.0, 30.0, 35.0, 40.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Stand Behind Me: 20/25/30/35/40 ally armor + MR by W rank (series[0]); +12%-of-bonus second series omitted (cross-champion); 3s active amortized at the midpoint; rank_scaled (W priority_2)",
        attribute="Stand Behind Me",
        rank_scaled=True,
    ),
    # Taric W Bastion: "the ally also gains the bonus armor" = 6/7/8/9/10% of
    # Taric's TOTAL armor by W rank (ARMOR ONLY; the percent-of-GRANTER mode -
    # resolves only when the granter's resolved armor is supplied to
    # ally_resist_grant). MR 0 (Bastion is armor only, matching the self Taric W
    # entry). Permanent tether -> prob 1.0. rank_scaled (W priority_2).
    ("Taric", "W", 0): AllyGrantEntry(
        armor_pct=(6.0, 7.0, 8.0, 9.0, 10.0),
        mr_pct=0.0,
        pct_base="total",
        conditional_probability=1.0,
        note="Bastion: ally gains 6/7/8/9/10% of Taric's TOTAL armor by W rank (ARMOR ONLY, percent-of-GRANTER mode; resolves only with the granter armor supplied); permanent tether prob 1.0; rank_scaled (W priority_2)",
        attribute="Bastion",
        rank_scaled=True,
    ),
    # Renata W Bailout: "If the target takes fatal damage while Bailout is active,
    # they are restored to 100% of their maximum health" (then a true-damage burn
    # kills them unless a takedown lands during the burn). revived_fraction 1.0
    # (the Anivia-P full-HP shape; no ally-HP dependency, unlike the Zilean /
    # Akshan flat-heal revives). Amortized at the ALLY-revive midpoint (the
    # burn-gate makes it more conditional than a self revive).
    ("Renata", "W", 0): AllyGrantEntry(
        revived_hp_fraction=1.0,
        conditional_probability=_ALLY_REVIVE_PROB,
        note="Bailout: ally restored to 100% max health on a fatal hit (revived_fraction 1.0); burn-gated (a takedown must land or the ally dies anyway) -> amortized at the ally-revive midpoint",
        attribute="Bailout",
    ),
}

# DSP7 (2026-06-17, ENGINE 1.133.0) - ally enchanter SHIELD / HEAL flat-HP grant
# registry. The THIRD EHP-grant mode and the SHIELD/HEAL bucket the item-289
# resist/revive registry deliberately EXCLUDED ("ally shields/heals are
# ability_hps THROUGHPUT, not a resist-denominator add nor a revive-numerator
# multiplier - a different axis"). Here the SAME shield/heal HP is modeled on the
# survivability side as a flat EHP NUMERATOR ADD a teammate confers on a
# PROTECTED ally - a distinct quantity from the granter-side ability_hps
# throughput (the ally analog of base HP: it rides the protected ally's armor/MR
# curve). Kept in a SEPARATE dict from _PASSIVE_ALLY_GRANT_OVERRIDES so the
# item-289 4-clean-entry shape + its exclusion test stay byte-identical.
#
# MAGNITUDES are the verbatim per-rank BASE shield/heal values from
# data/daemon_slayer/16.12.1/champion_abilities.json (the source ability_hps.py
# reads; probed 2026-06-17). The AP ratio (e.g. Janna E +55% AP) is OMITTED: the
# granter's resolved AP is a live Phase-D input, so the seam ships the
# self-contained base floor (the resist-registry "omit the cross-champion bonus
# half" precedent). conditional_probability = _ALLY_SHIELD_HEAL_PROB (the 0.5
# uptime midpoint). rank_scaled (the grant ability's rank resolved from level).
_ALLY_FLAT_HP_GRANT_OVERRIDES: dict[tuple[str, str, int], AllyGrantEntry] = {
    # Janna E Eye of the Storm: shield 80/120/160/200/240 (+55% AP) by E rank.
    ("Janna", "E", 0): AllyGrantEntry(
        shield_hp=(80.0, 120.0, 160.0, 200.0, 240.0),
        conditional_probability=_ALLY_SHIELD_HEAL_PROB,
        note="Eye of the Storm: 80/120/160/200/240 base ally shield by E rank (+55% AP omitted - granter AP is a live input); champion_abilities.json 16.12.1; rank_scaled",
        attribute="Eye of the Storm",
        rank_scaled=True,
    ),
    # Lulu E Help, Pix!: shield 80/120/160/200/240 (+55% AP) by E rank.
    ("Lulu", "E", 0): AllyGrantEntry(
        shield_hp=(80.0, 120.0, 160.0, 200.0, 240.0),
        conditional_probability=_ALLY_SHIELD_HEAL_PROB,
        note="Help, Pix!: 80/120/160/200/240 base ally shield by E rank (+55% AP omitted); champion_abilities.json 16.12.1; rank_scaled",
        attribute="Help, Pix!",
        rank_scaled=True,
    ),
    # Karma E Inspire: shield 80/130/180/230/280 (+60% AP) by E rank.
    ("Karma", "E", 0): AllyGrantEntry(
        shield_hp=(80.0, 130.0, 180.0, 230.0, 280.0),
        conditional_probability=_ALLY_SHIELD_HEAL_PROB,
        note="Inspire: 80/130/180/230/280 base ally shield by E rank (+60% AP omitted); champion_abilities.json 16.12.1; rank_scaled",
        attribute="Inspire",
        rank_scaled=True,
    ),
    # Yuumi E Zoomies: shield 65/90/115/140/165 (+30% AP) by E rank.
    ("Yuumi", "E", 0): AllyGrantEntry(
        shield_hp=(65.0, 90.0, 115.0, 140.0, 165.0),
        conditional_probability=_ALLY_SHIELD_HEAL_PROB,
        note="Zoomies: 65/90/115/140/165 base ally shield by E rank (+30% AP omitted); champion_abilities.json 16.12.1; rank_scaled",
        attribute="Zoomies",
        rank_scaled=True,
    ),
    # Seraphine W Surround Sound: shield 60/80/100/120/140 (+20% AP) by W rank.
    ("Seraphine", "W", 0): AllyGrantEntry(
        shield_hp=(60.0, 80.0, 100.0, 120.0, 140.0),
        conditional_probability=_ALLY_SHIELD_HEAL_PROB,
        note="Surround Sound: 60/80/100/120/140 base ally shield by W rank (+20% AP omitted; the per-ally missing-HP heal half is target-relative -> omitted); champion_abilities.json 16.12.1; rank_scaled",
        attribute="Surround Sound",
        rank_scaled=True,
    ),
    # Soraka W Astral Infusion: heal 90/110/130/150/170 (+50% AP) by W rank.
    ("Soraka", "W", 0): AllyGrantEntry(
        heal_hp=(90.0, 110.0, 130.0, 150.0, 170.0),
        conditional_probability=_ALLY_SHIELD_HEAL_PROB,
        note="Astral Infusion: 90/110/130/150/170 base ally heal by W rank (+50% AP omitted); champion_abilities.json 16.12.1; rank_scaled",
        attribute="Astral Infusion",
        rank_scaled=True,
    ),
    # Nami W Ebb and Flow: heal 55/80/105/130/155 (+40% AP) by W rank (the bounce
    # primary heal; the Minimum Heal band variant is omitted, not double-counted).
    ("Nami", "W", 0): AllyGrantEntry(
        heal_hp=(55.0, 80.0, 105.0, 130.0, 155.0),
        conditional_probability=_ALLY_SHIELD_HEAL_PROB,
        note="Ebb and Flow: 55/80/105/130/155 base ally heal by W rank (+40% AP omitted; Minimum Heal band variant omitted); champion_abilities.json 16.12.1; rank_scaled",
        attribute="Ebb and Flow",
        rank_scaled=True,
    ),
}

__all__ = [
    "AllyGrantEntry",
    "_PASSIVE_ALLY_GRANT_OVERRIDES",
    "_ALLY_FLAT_HP_GRANT_OVERRIDES",
    "ally_resist_grant",
    "ally_revive_multiplier",
    "ally_flat_hp_grant",
    "_ALLY_REVIVE_PROB",
    "_ALLY_SHIELD_HEAL_PROB",
]


def ally_resist_grant(
    champion_id: str,
    level: int,
    apply_ally_grant: bool,
    *,
    granter_total_armor: float = 0.0,
    granter_total_mr: float = 0.0,
    granter_base_armor: float = 0.0,
    granter_base_mr: float = 0.0,
) -> tuple[float, float]:
    """Return ``(ally_armor, ally_mr)`` a champion CONFERS ON A TEAMMATE.

    Sums, over every registered ally-resist grant matching ``champion_id``:
      - the FLAT-ADD half (Orianna E, Braum W): ``value(level) * prob``.
      - the PERCENT-OF-GRANTER-RESIST half (Taric W):
        ``(pct(level)/100) * granter_resist * prob`` where ``granter_resist`` is
        ``granter_total_*`` for ``pct_base="total"`` or the granter BONUS
        (``max(0, total - base)``) for ``pct_base="bonus"``.

    The granter resists are keyword-only with 0.0 defaults, so a percent entry
    (Taric W) contributes 0.0 until the granter's resolved armor / MR is supplied
    - the flat entries (Orianna, Braum) are self-contained and unaffected. When
    ``apply_ally_grant`` is False (the default) both returns are 0.0.

    The CONSUMER adds each to the PROTECTED ALLY's resolved resist before the
    resistance curve (``compute_ehp(ally, external_resist_armor=...)``); a positive
    grant lowers the ally's damage-taken multiplier = a larger ally Effective HP =
    the correct "a teammate buffed my resists -> I survive more" direction.
    """
    ally_armor = ally_mr = 0.0
    if not apply_ally_grant:
        return ally_armor, ally_mr
    cid = str(champion_id)
    lvl = int(level)
    g_bonus_armor = max(0.0, float(granter_total_armor) - float(granter_base_armor))
    g_bonus_mr = max(0.0, float(granter_total_mr) - float(granter_base_mr))
    for (entry_cid, _key, _form), entry in _PASSIVE_ALLY_GRANT_OVERRIDES.items():
        if entry_cid != cid:
            continue
        prob = float(entry.conditional_probability)
        a = _value_at_level(
            entry.armor, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        m = _value_at_level(
            entry.mr, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        ally_armor += a * prob
        ally_mr += m * prob
        # Percent-of-GRANTER-resist half (Taric W): multiplies the supplied
        # granter resolved resist (defaults 0.0 -> 0.0 until provided).
        if entry.armor_pct or entry.mr_pct:
            res_a = float(granter_total_armor) if entry.pct_base == "total" else g_bonus_armor
            res_m = float(granter_total_mr) if entry.pct_base == "total" else g_bonus_mr
            # P2-W2 slice E: a non-finite granter resist (inf / NaN) would leak
            # through ``(pct/100) * res`` into a bare NaN/Infinity JSON token on
            # the protected ally's EHP-denominator seam. Treat a non-finite
            # resist as the no-op 0.0 - finite-input calls stay byte-identical.
            if not math.isfinite(res_a):
                res_a = 0.0
            if not math.isfinite(res_m):
                res_m = 0.0
            pa = _value_at_level(
                entry.armor_pct, lvl, entry.level_scaled,
                key=_key, rank_scaled=entry.rank_scaled,
            )
            pm = _value_at_level(
                entry.mr_pct, lvl, entry.level_scaled,
                key=_key, rank_scaled=entry.rank_scaled,
            )
            ally_armor += (pa / 100.0) * res_a * prob
            ally_mr += (pm / 100.0) * res_m * prob
    return ally_armor, ally_mr


def ally_revive_multiplier(
    champion_id: str, level: int, apply_ally_grant: bool
) -> float:
    """Return the ALLY Effective-HP NUMERATOR multiplier a champion CONFERS.

    ``1 + sum(revived_hp_fraction(level) * conditional_probability)`` over every
    registered ally-revive matching ``champion_id`` (Renata W -> 1.0 fraction).
    A granted revive restores a second HP pool to the TEAMMATE; the teammate's
    second Effective HP is ``revived_hp_fraction`` of its first (it runs through
    the same armor/MR curve), so the multiplier scales the PROTECTED ally's
    per-type Effective HP. When ``apply_ally_grant`` is False (the default) the
    multiplier is 1.0 - byte-identical.

    The CONSUMER multiplies the protected ally's per-type Effective HP by this
    value (``compute_ehp(ally, external_revive_multiplier=...)``).
    """
    if not apply_ally_grant:
        return 1.0
    cid = str(champion_id)
    lvl = int(level)
    extra = 0.0
    for (entry_cid, _key, _form), entry in _PASSIVE_ALLY_GRANT_OVERRIDES.items():
        if entry_cid != cid:
            continue
        frac = _value_at_level(
            entry.revived_hp_fraction, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        extra += max(0.0, frac) * float(entry.conditional_probability)
    return 1.0 + extra


def ally_flat_hp_grant(
    champion_id: str, level: int, apply_ally_grant: bool
) -> float:
    """Return the flat EHP-numerator HP a champion CONFERS on a protected ally.

    DSP7 (ENGINE 1.133.0): sums, over every ``_ALLY_FLAT_HP_GRANT_OVERRIDES``
    entry matching ``champion_id``, ``(shield_hp(level) + heal_hp(level)) *
    conditional_probability`` - the enchanter shield / heal HP (Janna E / Lulu E
    / Karma E / Yuumi E / Seraphine W shields, Soraka W / Nami W heals) amortized
    by the ``_ALLY_SHIELD_HEAL_PROB`` uptime midpoint. The base value is resolved
    at the grant ability's level-scaled rank (``rank_scaled``).

    The CONSUMER adds this to the PROTECTED ally's EHP numerator
    (``compute_ehp(ally, external_flat_hp=...)``); a flat shield / heal rides the
    SAME armor/MR curve as base HP, so it scales every per-type Effective HP
    exactly like the same bonus max HP = the correct "a teammate shielded me ->
    I survive more" direction. When ``apply_ally_grant`` is False (the default)
    the return is 0.0 - byte-identical. Fail-soft (unknown / blank champion ->
    0.0); never raises.
    """
    if not apply_ally_grant:
        return 0.0
    cid = str(champion_id)
    if not cid:
        return 0.0
    lvl = int(level)
    total = 0.0
    for (entry_cid, _key, _form), entry in _ALLY_FLAT_HP_GRANT_OVERRIDES.items():
        if entry_cid != cid:
            continue
        prob = float(entry.conditional_probability)
        s = _value_at_level(
            entry.shield_hp, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        h = _value_at_level(
            entry.heal_hp, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        total += (max(0.0, s) + max(0.0, h)) * prob
    return total
