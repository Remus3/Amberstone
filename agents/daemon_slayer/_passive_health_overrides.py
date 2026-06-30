"""R46 (2026-06-30) - effects-text-only STACKING permanent max-HP passives.

A NEW survivability axis and the SECOND EHP-NUMERATOR term (after the revive
multiplier): a champion passive that grants PERMANENT bonus maximum health PER
STACK and accumulates (effectively) without bound over a game. It is NOT in the
resolved stat block - not a base-per-level value, not an item - so neither EHP
scorer saw it. Three champions carry the class at patch 16.13.1:
  - Sion W Soul Furnace (passive): "Sion gains 4 bonus health whenever he kills
    an enemy, increased to 15 for large enemies and takedowns against enemy
    champions." Infinitely farm-stacking.
  - Cho'Gath R Feast: "Each stack of Feast ... grants Cho'Gath bonus health ...
    Only 6 stacks can be gained from non-epic monsters or minions." The per-stack
    health is the parsed 'Bonus Health Per Stack' damage_block [80, 120, 160] by
    R rank; champion / epic takedowns are uncapped.
  - Swain P Ravenous Flock: "Soul Fragment: For each stack, Swain gains 15 bonus
    health permanently." One fragment per nearby enemy-champion death collected.

WHY THE EHP NUMERATOR (not the denominator): a flat bonus max-HP sits at the TOP
of the damage stack exactly like ``ext_flat_hp`` (the enchanter ally flat-HP
grant) and ``flat_mit_*`` (R9 per-instance flat DR) at ``ehp.py`` - it adds RAW
to every per-type numerator (physical / magical / true) and then rides the SAME
armor/MR curve. Unlike the resist registry (which raises the armor/MR
denominator) or the DR registry (which divides the denominator), a max-HP add is
a clean numerator term that lifts EVERY damage-type EHP uniformly, including true
EHP (which ignores resists). It is a pure pool increase.

THE STACK-COUNT PROXY (the data we lack live): a stacking-HP passive's value is
``hp_per_stack * stack_count``, but we have no live stack feed. So the per-stack
HP is EXACT from the verbatim 16.13.1 Meraki truth
(``data/daemon_slayer/16.13.1/champion_abilities.json``), and the STACK COUNT by
champion level is an operator-tunable CONSERVATIVE midpoint - the analog of
``_passive_revive_overrides._REVIVE_PROB`` and
``_passive_flat_mitigation_overrides._ASSUMED_FLAT_DR_INSTANCES``. Each
``assumed_stacks_by_level`` is a deliberately LOW, monotonic-non-decreasing
18-entry curve (a farming Sion main stacks far more than the modeled count; the
midpoint under-credits on purpose so a flipped-on scorer never OVER-states the
pool). A future live-stack consumer (the in-game stack count from the Live Client
buff list, when that surfaces) replaces the curve without re-authoring the math.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``assume_passive_health_stacks`` defaults
False; with it OFF ``passive_health_stack_hp`` returns 0.0 and every EHP numerator
is unchanged. No live :8893 default scorer flips it on; it is opt-in everywhere
(mirrors ``apply_passive_revive`` / ``assume_passive_flat_mitigation``). The live
default-ON flip is EXCLUDED (no live stack feed) -> ``docs/LIVE_GAME_GATED_SYNC.md``.

WHY HAND-AUTHORED, not parsed: identical reasoning to the revive / heal / shield /
flat-mitigation registries - a text-parser mis-extracts and re-breaks on each
patch prose rewrite. Each entry's per-stack HP comes from the verbatim
``effects_descriptions`` (Sion / Swain) or the parsed ``damage_blocks`` modifier
(Cho'Gath Feast 'Bonus Health Per Stack') cited in its ``note``; a patch
re-extract re-verifies the cited text.

RANK-AT-LEVEL NOTE (Cho'Gath Feast): the per-stack HP is a per-RANK block
[80, 120, 160], but Feast is an ULTIMATE - unavailable below level 6 and ranked at
6 / 11 / 16. So Cho'Gath's ``hp_per_stack`` is stored as an 18-entry per-LEVEL
tuple (0 below level 6, then 80 / 120 / 160 over the standard max-ult-first rank
cadence) with ``level_scaled_hp=True``. Sion (4) and Swain (15) are flat innate /
basic-ability values, ``level_scaled_hp=False``.

CONSERVATIVE-VALUE NOTE (Sion): Sion's passive grants 4 per normal kill, 15 for
large enemies / champion takedowns. The seed uses the 4 (the bulk farm value); the
15 is the rarer large/champ upside, OMITTED to keep the credit conservative (the
same boundary class as the flat-mitigation registry's omitted +AP sub-terms).
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Conservative assumed STACK-COUNT-by-level curves (the live feed we lack) ---
# Each is an 18-entry (levels 1-18) monotonic-non-decreasing count. The values are
# deliberately LOW relative to a real game's stacking so the modeled max-HP pool
# never OVER-states. Operator-tunable; the analog of _REVIVE_PROB.

# Sion W: farm-driven, ~3 kills/level modeled (a real Sion main stacks far more).
_SION_STACKS: tuple[float, ...] = (
    3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54,
)
# Swain P: ~1 collected Soul Fragment per 2 levels (you do not claim every kill's
# fragment); a conservative late-game count of 9.
_SWAIN_STACKS: tuple[float, ...] = (
    0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9,
)
# Cho'Gath R Feast: gated at level 6 (the ult), a slow ramp capped at a
# conservative 3 stacks (well below the 6-stack minion cap and the uncapped
# champ-kill case).
_CHO_STACKS: tuple[float, ...] = (
    0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3,
)
# Cho'Gath R Feast per-stack HP by champion level: the Meraki [80, 120, 160] rank
# block resolved over the standard max-ult-first cadence (R1 at 6-10, R2 at 11-15,
# R3 at 16-18); 0 below level 6 (no ult).
_CHO_HP_PER_STACK: tuple[float, ...] = (
    0, 0, 0, 0, 0, 80, 80, 80, 80, 80, 120, 120, 120, 120, 120, 160, 160, 160,
)


@dataclass(frozen=True)
class PassiveHealthEntry:
    """One hand-authored effects-text-only STACKING permanent max-HP passive.

    ``hp_per_stack`` is the bonus MAX HEALTH granted per stack - EXACT from the
    cited 16.13.1 Meraki text. It is a flat float (Sion 4, Swain 15) or, when
    ``level_scaled_hp``, an 18-entry per-level tuple read at champion level
    (``level-1``) for an ultimate whose per-stack HP is rank-scaled (Cho'Gath
    Feast 80/120/160).

    ``assumed_stacks_by_level`` is the 18-entry (levels 1-18) CONSERVATIVE stack
    count midpoint (the live stack feed we lack). The credited bonus HP is
    ``hp_per_stack(level) * assumed_stacks_by_level[level-1]``.

    ``level_scaled_hp`` (default False) - set True when ``hp_per_stack`` is the
    per-level tuple (Cho'Gath), False for a flat per-stack value (Sion / Swain).
    """

    hp_per_stack: float | tuple[float, ...]
    assumed_stacks_by_level: tuple[float, ...]
    note: str = ""
    attribute: str = "Passive Health"
    level_scaled_hp: bool = False


# (champion_id, key, form_index) -> PassiveHealthEntry. Keyed (champion, key, form)
# for parity with the revive / heal / shield / flat-mitigation registries;
# ``passive_health_stack_hp`` aggregates ALL entries whose key champion matches.
# Seeded 2026-06-30 against verbatim 16.13.1 effects_descriptions (+ the parsed
# Feast 'Bonus Health Per Stack' damage_block for Cho'Gath).
_PASSIVE_HEALTH_OVERRIDES: dict[tuple[str, str, int], PassiveHealthEntry] = {
    # Sion W Soul Furnace (passive): "Sion gains 4 bonus health whenever he kills
    # an enemy, increased to 15 for large enemies and takedowns against enemy
    # champions." Infinitely farm-stacking. hp_per_stack 4.0 (the bulk normal-kill
    # value; the +15 large/champ upside is OMITTED to keep the credit
    # conservative). Stacks modeled at ~3 kills/level (a real Sion main stacks far
    # more - the midpoint under-credits on purpose).
    ("Sion", "W", 0): PassiveHealthEntry(
        hp_per_stack=4.0,
        assumed_stacks_by_level=_SION_STACKS,
        note=(
            "Soul Furnace passive: 'Sion gains 4 bonus health whenever he kills "
            "an enemy, increased to 15 for large enemies and takedowns'; flat 4 "
            "per normal kill (the +15 large/champ upside omitted, conservative); "
            "infinitely farm-stacking; ~3 kills/level conservative midpoint"
        ),
        attribute="Soul Furnace",
    ),
    # Cho'Gath R Feast: "Each stack of Feast ... grants Cho'Gath bonus health ...
    # Only 6 stacks can be gained from non-epic monsters or minions." The per-stack
    # health is the parsed 'Bonus Health Per Stack' damage_block [80, 120, 160] by
    # R rank, stored as an 18-entry per-level tuple (0 below the level-6 ult; R1
    # 6-10, R2 11-15, R3 16-18). Stacks modeled at a conservative ramp capped at 3
    # (below the 6-stack minion cap; champ/epic kills are uncapped).
    ("Chogath", "R", 0): PassiveHealthEntry(
        hp_per_stack=_CHO_HP_PER_STACK,
        assumed_stacks_by_level=_CHO_STACKS,
        note=(
            "Feast: per-stack bonus health from the parsed 'Bonus Health Per "
            "Stack' damage_block [80,120,160] by R rank (rank-at-level: R1 6-10, "
            "R2 11-15, R3 16-18; 0 below the level-6 ult); 6-stack minion cap, "
            "uncapped from champ/epic; conservative stack ramp capped at 3"
        ),
        attribute="Feast",
        level_scaled_hp=True,
    ),
    # Swain P Ravenous Flock: "Soul Fragment: For each stack, Swain gains 15 bonus
    # health permanently." One Soul Fragment per nearby enemy-champion death
    # collected by his ravens. hp_per_stack 15.0 flat. Stacks modeled at ~1 per 2
    # levels (you do not claim every kill's fragment; conservative late-game 9).
    ("Swain", "P", 0): PassiveHealthEntry(
        hp_per_stack=15.0,
        assumed_stacks_by_level=_SWAIN_STACKS,
        note=(
            "Ravenous Flock: 'Soul Fragment: For each stack, Swain gains 15 bonus "
            "health permanently'; flat 15 per collected fragment; ~1 per 2 levels "
            "conservative midpoint (not every kill's fragment is claimed)"
        ),
        attribute="Ravenous Flock",
    ),
}

__all__ = [
    "PassiveHealthEntry",
    "_PASSIVE_HEALTH_OVERRIDES",
    "passive_health_stack_hp",
    "_hp_per_stack_at_level",
    "_stacks_at_level",
]


def _hp_per_stack_at_level(
    hp_per_stack: float | tuple[float, ...], level: int, level_scaled_hp: bool
) -> float:
    """Resolve an entry's per-stack HP at the champion level.

    A ``level_scaled_hp`` entry carries an 18-entry per-level tuple read at
    ``level-1`` (clamped to the tuple bounds); a flat entry is its float.
    """
    if level_scaled_hp and isinstance(hp_per_stack, (tuple, list)):
        if not hp_per_stack:
            return 0.0
        idx = max(0, min(int(level) - 1, len(hp_per_stack) - 1))
        return float(hp_per_stack[idx])
    if isinstance(hp_per_stack, (tuple, list)):
        # Defensive: a tuple on a non-level_scaled entry resolves at its first.
        return float(hp_per_stack[0]) if hp_per_stack else 0.0
    return float(hp_per_stack)


def _stacks_at_level(assumed_stacks_by_level: tuple[float, ...], level: int) -> float:
    """Resolve the conservative assumed stack count at champion level (the tuple
    read at ``level-1``, clamped to the tuple bounds)."""
    if not assumed_stacks_by_level:
        return 0.0
    idx = max(0, min(int(level) - 1, len(assumed_stacks_by_level) - 1))
    return float(assumed_stacks_by_level[idx])


def passive_health_stack_hp(
    champion_id: str, level: int, assume_passive_health_stacks: bool
) -> float:
    """Return the raw bonus MAX HP from stacking-HP passives matching ``champion_id``.

    Summed over every registered entry whose key champion matches, each
    contributing ``hp_per_stack(level) * assumed_stacks_by_level[level-1]``. When
    ``assume_passive_health_stacks`` is False (the default) returns 0.0 - the EHP
    numerators are byte-identical.

    The caller adds this value to EVERY per-type EHP NUMERATOR (mirrors
    ``ext_flat_hp``): a larger max-HP pool = a larger numerator = larger EHP across
    all damage types (including true), the correct "more health -> survives more"
    direction.
    """
    if not assume_passive_health_stacks:
        return 0.0
    cid = str(champion_id)
    lvl = int(level)
    total = 0.0
    for (entry_cid, _key, _form), entry in _PASSIVE_HEALTH_OVERRIDES.items():
        if entry_cid != cid:
            continue
        hp = _hp_per_stack_at_level(entry.hp_per_stack, lvl, entry.level_scaled_hp)
        stacks = _stacks_at_level(entry.assumed_stacks_by_level, lvl)
        bonus = hp * stacks
        if bonus > 0.0:
            total += bonus
    return total
