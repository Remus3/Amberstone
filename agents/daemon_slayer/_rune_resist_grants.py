"""Per-rune conditional / time-gated RESIST-GRANT registry, keyed by rune id.

The RUNE-SIDE lane of the champion ``_passive_resist_overrides.resist_grants`` -
the FOURTH survivability axis: a bonus armor / magic-resistance grant that raises
the EHP DENOMINATOR DIRECTLY (added to ``eff_armor`` / ``eff_mr`` BEFORE the
``_armor_factor`` curve), NOT the numerator. That champion registry is keyed by
``champion_id`` and its item twin ``_item_resist_grants`` is keyed by item id, so
a RUNE can never match either - the exact structural gap this registry fills, the
same reasoning the sibling ``_item_revive`` / ``_item_survival_window`` /
``_item_spell_shield_overrides`` / ``_item_mana_health`` registries carry.

Mechanic: the engine modelled runes as OFFENSE ONLY before this registry. A grep
of ``ehp.py`` and ``rank.py`` for ``rune`` / ``perk`` / ``keystone`` returned ZERO
matches, and ``rune_procs.py`` registers Aftershock (8439) for its magic-damage
explosion ALONE - its own formula string says verbatim "(resist-bonus side not
modeled)". Three current-patch Resolve runes therefore earned ZERO EHP for the
bonus resists they grant. Their DDragon 16.14.1 ``runesReforged.json`` longDescs,
quoted VERBATIM:

  * 8439 Aftershock: "After immobilizing an enemy champion, increase your Armor
    and Magic Resist by 45 + 75% of your Bonus Resists for 2.5s. Then explode,
    dealing magic damage to nearby enemies.<br><br>Damage: 25 - 120 (+8% of your
    bonus health)<br>Cooldown: 20s<br><br>Resistance bonus from Aftershock capped
    at: 80-150 (based on level)<br>"
  * 8429 Conditioning: "After 12 min gain +8 Armor and +8 Magic Resist and
    increase your Armor and Magic Resist by 3%."
  * 8242 Unflinching: "Gain 10 Armor and Magic Resist when crowd controlled and
    for 2 seconds after."

THE AFTERSHOCK CAP IS LOAD-BEARING - it is NOT the uncapped 45 + 0.75 * bonus.
The longDesc's final clause ("capped at: 80-150 (based on level)") makes the
grant ``min(45 + 0.75 * bonus_resist, cap_by_level)``, and the cap BINDS on
exactly the high-bonus-resist tank / warden cohort that actually runs Aftershock:
at 150 bonus armor the uncapped value is 157.5, over the level-18 cap of 150.
Dropping the cap would over-credit the champions this feed exists for, so it is
modelled explicitly by ``aftershock_resist_cap`` and pinned by a dedicated test.
The 80-to-150 walk uses the standard Riot linear per-level interpolation between
level 1 and level 18 (``_lerp_per_level`` semantics), matching how every other
"based on level" magnitude in the engine is read.

Three entry SHAPES share this registry + the one ``apply_rune_resist_grants``
seam, all expressed through the same flat / percent / cap fields:
(1) Aftershock - flat 45 PLUS percent-of-BONUS 75%, under a LEVEL-SCALED CAP,
    amortized by a cooldown-gated firing midpoint;
(2) Conditioning - flat 8 PLUS percent-of-TOTAL 3%, NO cap, PERMANENT once its
    12-minute threshold passes (``conditional_probability`` 1.0, EXACT), gated by
    ``online_minute``;
(3) Unflinching - flat 10, NO percent, NO cap, amortized by the same conditional
    firing midpoint.

Only three ids are SEEDED. This registry is a deliberate ALLOWLIST, not a
tree-wide sweep: the other Resolve runes either grant no resist at all (8446
Demolish tower damage, 8451 Overgrowth max health, 8453 Revitalize heal/shield
power, 8463 Font of Life ally healing, 8465 Guardian ally shield) or reduce
damage through a different axis entirely (8473 Bone Plating is a flat
per-instance damage BLOCK, which is the ``_passive_mitigation_overrides`` lane,
NOT a resist add). Each was read and rejected rather than overlooked.

Amortization (CONDITIONAL, unlike an always-on static stat): Aftershock and
Unflinching realize their value only in a firing WINDOW, so each is scaled by
``_RUNE_ACTIVE_RESIST_PROB`` - the expected fraction of the modeled fight the
grant is up. The resist MAGNITUDE of every entry is EXACT DDragon; ONLY THE
FIRING MIDPOINT IS AN ASSUMPTION (the champion ``_ACTIVE_RESIST_PROB`` / item
``_ITEM_RESIST_STACK_PROB`` convention). Conditioning carries NO firing
assumption at all (prob 1.0 - it is permanent once online); its only assumption
is the game-clock reading, which is the explicit, tunable
``_ASSUMED_GAME_MINUTE``.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_rune_resist_grants`` seam on
``compute_ehp`` defaults False; with it OFF every grant is 0.0 and every EHP field
is unchanged, even when a full rune page is supplied via ``rune_ids``. The live
default-ON flip is operator-gated (mirrors ``apply_item_resist_grants`` /
``apply_item_spell_shield`` / ``apply_passive_resist``).

Keyed by string rune_id to match the engine's item-id convention (strings
throughout); integer ids are coerced on lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# Operator-tunable amortization midpoint for a CONDITIONAL rune resist grant -
# the expected fraction of the modeled sustained fight the grant is up. Aftershock
# holds for 2.5s on a 20s cooldown (a 0.125 raw duty cycle) and Unflinching holds
# while crowd controlled plus 2s after, so neither is always-on. Both are priced
# ABOVE their raw duty cycle because they are ENGAGEMENT-SYNCHRONIZED rather than
# uniformly distributed: Aftershock fires on the immobilize that STARTS the fight
# (the tank/warden cohort that runs it opens with hard CC), and Unflinching is up
# precisely while the champion is being focused - both windows land on the
# highest-incoming-damage moment the EHP frame models, which is the moment the
# resist matters. 0.3 is the value the champion registry already uses for "a short
# defensive ACTIVE resist grant" (``_passive_resist_overrides._ACTIVE_RESIST_PROB``)
# and is adopted here unchanged so the two lanes stay comparable. Documented +
# conservative; a future Phase-D pass tunes per-rune live (each entry carries its
# own ``conditional_probability`` so the two can decouple).
_RUNE_ACTIVE_RESIST_PROB: float = 0.3

# Aftershock's resist bonus is capped at "80-150 (based on level)" (verbatim
# longDesc). These are the level-1 and level-18 endpoints of that linear walk.
_AFTERSHOCK_CAP_AT_LEVEL_1: float = 80.0
_AFTERSHOCK_CAP_AT_LEVEL_18: float = 150.0

# Conditioning's DDragon threshold, verbatim: "After 12 min gain ...". EXACT, not
# an assumption - the assumption is which side of it the modeled fight sits on
# (``_ASSUMED_GAME_MINUTE`` below).
_CONDITIONING_ONLINE_MINUTE: float = 12.0

# Operator-tunable game-clock reading for the modeled fight, EXPLICIT so no caller
# silently inherits a lategame assumption. This is the ONE assumption behind
# Conditioning (its magnitude is exact and its uptime is permanent once online).
# 15.0 is chosen because the DS EHP scorers evaluate COMPLETED-ITEM builds in a
# sustained teamfight frame - a state a game has essentially always reached past
# the 12-minute mark - and it is conservative relative to the full six-item build
# the ranker routes actually score. Overridable per call via the ``game_minute``
# argument of ``rune_resist_grants``, which a future live consumer can drive from
# the real Live Client game clock instead of this constant.
_ASSUMED_GAME_MINUTE: float = 15.0


def aftershock_resist_cap(level: int) -> float:
    """Return Aftershock's level-scaled resist cap - 80 at level 1, 150 at 18.

    Verbatim longDesc clause: "Resistance bonus from Aftershock capped at: 80-150
    (based on level)". Linear interpolation across the 17 level-ups between 1 and
    18, the standard Riot "based on level" reading used throughout the engine.
    ``level`` is clamped into ``[1, 18]`` so an out-of-range caller yields the
    nearest endpoint rather than an extrapolated (and uncapped-in-practice) value.
    """
    lv = max(1, min(18, int(level)))
    span = _AFTERSHOCK_CAP_AT_LEVEL_18 - _AFTERSHOCK_CAP_AT_LEVEL_1
    return _AFTERSHOCK_CAP_AT_LEVEL_1 + span * (lv - 1) / 17.0


@dataclass(frozen=True)
class RuneResistEntry:
    """One rune-keyed conditional bonus armor / magic-resistance grant.

    ``armor`` / ``mr`` are flat bonus values (Aftershock 45, Conditioning 8,
    Unflinching 10). ``armor_pct`` / ``mr_pct`` carry a PERCENT (75.0 == 75%) of
    the champion's resist selected by ``pct_base`` ("total" = base + build, or
    "bonus" = build delta = total - base) - Aftershock 75% of BONUS resists,
    Conditioning 3% of TOTAL resists. An entry may carry both the flat and the
    percent fields; they SUM, and the sum is then clamped by ``level_capped``.

    ``level_capped`` selects the Aftershock cap: when True the combined flat +
    percent value is clamped to ``aftershock_resist_cap(level)`` BEFORE the
    amortization midpoint is applied (the cap is a game mechanic on the magnitude;
    the probability is our modeling assumption about uptime, so the order matters
    and the cap must come first).

    ``online_minute`` gates a time-threshold rune (Conditioning 12.0): the grant
    contributes 0.0 until the modeled game clock reaches it. 0.0 means no gate.

    ``conditional_probability`` amortizes a firing window. A PERMANENT grant (once
    any ``online_minute`` gate is met) uses 1.0 - EXACT, no amortization.

    ``family`` dedups mutually exclusive ids, mirroring the item registry's
    base/Arena-mirror handling. Runes have no mirror ids today, so each entry gets
    its own family; the field exists so a future alias (a rune-shard or a mode
    variant) cannot silently double-credit.
    """

    armor: float = 0.0
    mr: float = 0.0
    armor_pct: float = 0.0
    mr_pct: float = 0.0
    pct_base: str = "total"
    level_capped: bool = False
    online_minute: float = 0.0
    conditional_probability: float = _RUNE_ACTIVE_RESIST_PROB
    family: str = ""
    note: str = ""


_RUNE_RESIST_GRANTS: dict[str, RuneResistEntry] = {
    # 8439 Aftershock (Resolve keystone) - verbatim: "After immobilizing an enemy
    # champion, increase your Armor and Magic Resist by 45 + 75% of your Bonus
    # Resists for 2.5s. ... Cooldown: 20s ... Resistance bonus from Aftershock
    # capped at: 80-150 (based on level)". Flat 45 + 75% of BONUS resist, CAPPED
    # by level. The magic-damage explosion half is already registered in
    # rune_procs.py (8439) and is NOT a survivability term - only the resist side
    # is credited here, closing that module's "(resist-bonus side not modeled)".
    "8439": RuneResistEntry(
        armor=45.0, mr=45.0, armor_pct=75.0, mr_pct=75.0, pct_base="bonus",
        level_capped=True, family="aftershock",
        note="Aftershock: 45 + 75% bonus resists for 2.5s on a 20s cooldown, capped 80-150 by level",
    ),
    # 8429 Conditioning (Resolve, slot 2) - verbatim: "After 12 min gain +8 Armor
    # and +8 Magic Resist and increase your Armor and Magic Resist by 3%." Flat
    # 8/8 PLUS 3% of TOTAL resist (the tooltip says "your Armor", not "bonus
    # Armor", so pct_base is total). PERMANENT once the 12-minute threshold
    # passes -> conditional_probability 1.0, EXACT, no firing amortization; the
    # only assumption is the game-clock reading (_ASSUMED_GAME_MINUTE).
    "8429": RuneResistEntry(
        armor=8.0, mr=8.0, armor_pct=3.0, mr_pct=3.0, pct_base="total",
        online_minute=_CONDITIONING_ONLINE_MINUTE, conditional_probability=1.0,
        family="conditioning",
        note="Conditioning: +8 armor/MR and +3% total armor/MR, permanent after 12 min",
    ),
    # 8242 Unflinching (Resolve, slot 3) - verbatim: "Gain 10 Armor and Magic
    # Resist when crowd controlled and for 2 seconds after." Flat 10/10, NO
    # percent term, NO level scaling, NO cap. Conditional on being crowd
    # controlled -> amortized at the shared firing midpoint. The rune's tenacity /
    # slow-resist half (absent from this longDesc in 16.14.1) is a different axis
    # and is not credited here.
    "8242": RuneResistEntry(
        armor=10.0, mr=10.0, family="unflinching",
        note="Unflinching: +10 armor/MR while crowd controlled and for 2s after",
    ),
}


def rune_resist_grants(
    rune_ids: Iterable[str | int],
    *,
    level: int,
    total_armor: float,
    total_mr: float,
    base_armor: float,
    base_mr: float,
    game_minute: Optional[float] = None,
) -> tuple[float, float]:
    """Return the ``(bonus_armor, bonus_mr)`` rune-side conditional resist grant.

    ``total_armor`` / ``total_mr`` are the champion's RESOLVED build resists (base
    per-level + items); ``base_armor`` / ``base_mr`` are the base per-level
    resists - the caller passes both from ``compute_ehp`` (the same values the
    champion ``resist_grants`` and the item ``item_resist_grants`` receive).
    ``level`` drives Aftershock's cap. ``game_minute`` defaults to the explicit,
    tunable ``_ASSUMED_GAME_MINUTE`` and gates any entry carrying an
    ``online_minute`` threshold.

    Per entry: the percent-of-bonus term multiplies ``max(0.0, total - base)``
    (clamped so a below-base build never yields a negative grant) and the
    percent-of-total term multiplies the resolved total. The flat and percent
    terms SUM, that sum is clamped to ``aftershock_resist_cap(level)`` when the
    entry is ``level_capped``, and only THEN is the entry's
    ``conditional_probability`` applied - the cap is a game mechanic on the
    magnitude, the probability is a modeling assumption about uptime.

    A ``family`` tag is credited at most once, so a duplicated or aliased id
    cannot double-credit. Different families sum. Runes not in the registry
    contribute 0 - the registry is a seeded allowlist, so every offensive
    keystone and every non-resist Resolve rune returns 0.0 by construction. The
    returned values are added to ``eff_armor`` / ``eff_mr`` (the DENOMINATOR) next
    to the champion ``bonus_armor`` / ``bonus_mr`` and the item
    ``item_resist_armor`` / ``item_resist_mr``. The default-OFF gating lives in
    ``compute_ehp`` (this function is only called when ``apply_rune_resist_grants``
    is True).
    """
    minute = _ASSUMED_GAME_MINUTE if game_minute is None else float(game_minute)
    bonus_armor = 0.0
    bonus_mr = 0.0
    seen_families: set[str] = set()
    for rid in rune_ids:
        entry = _RUNE_RESIST_GRANTS.get(str(rid))
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        seen_families.add(entry.family)
        # Time-threshold gate (Conditioning "After 12 min").
        if entry.online_minute and minute < entry.online_minute:
            continue
        # Flat term.
        raw_a = entry.armor
        raw_m = entry.mr
        # Percent-of-resist term (bonus or total base).
        if entry.armor_pct or entry.mr_pct:
            if entry.pct_base == "bonus":
                res_a = max(0.0, total_armor - base_armor)
                res_m = max(0.0, total_mr - base_mr)
            else:
                res_a = max(0.0, total_armor)
                res_m = max(0.0, total_mr)
            raw_a += res_a * (entry.armor_pct / 100.0)
            raw_m += res_m * (entry.mr_pct / 100.0)
        # Level-scaled cap (Aftershock 80-150), BEFORE amortization.
        if entry.level_capped:
            cap = aftershock_resist_cap(level)
            raw_a = min(raw_a, cap)
            raw_m = min(raw_m, cap)
        prob = entry.conditional_probability
        bonus_armor += raw_a * prob
        bonus_mr += raw_m * prob
    return bonus_armor, bonus_mr
