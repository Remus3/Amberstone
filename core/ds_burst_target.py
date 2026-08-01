"""Squishy-carry target profile for the burst-carry ranking scenario.

Pure leaf module - ZERO engine imports so it can be imported from
``core.daemon_slayer_client`` (the :8860 HTTP boundary) WITHOUT importing the
``agents.daemon_slayer`` engine package in-process. That import is structurally
forbidden by the split-brain guard (tests/test_ds_preview_e2e_p1l21.py
TestNoEngineSplitBrain): the client must reach the engine only over HTTP, never
run a second in-process copy at a possibly-different ENGINE_VERSION. The profile
is a caller-side POLICY value (the assumed defenses of the enemy carry a burst
ADC deletes), not engine math, so it lives here in ``core`` next to its only
consumer, the carry branch of ``rank_for_primary_archetype``. It is the exact
sibling of ``core.ds_champion_fight_length`` (the per-champion fight_length
allow-map) and ``core.ds_archetype_hp_pct`` (the archetype current-HP default) -
both carry-branch caller-side policy values.

WHY a squishy-carry target (lever L4)
-------------------------------------
The DS carry ranking is computed against a TARGET stat line. The default target
is ``coach_integration.enemy_stats.compute_enemy_stats`` - a per-mode, level-aware
TEAM AVERAGE (at SR L16: armor ~120 / max_hp ~2760). That average is pulled UP by
the enemy tank + bruiser, so it over-rewards front-loaded current-HP on-hit
(Blade of the Ruined King) and under-rewards crit / lethality-execute (Infinity
Edge / The Collector / Yun Tal) - the exact core a crit ADC uses to DELETE the
enemy CARRY. The operator does not auto-attack the tank down; the operator bursts
the squishy backline carry. So for the burst carries (the champions in
``core.ds_champion_fight_length``'s allow-map, where ``fight_length`` is engaged)
the ranking target should be that squishy carry, not the team average.

This is applied ONLY at the shared carry chokepoint and ONLY when the champion's
``fight_length`` is engaged (a mapped burst carry), so it auto-scopes to the
allow-map: a non-mapped champion (Vayne / Ashe / a clean scorer) keeps the
caller's target UNCHANGED (byte-identical). It covers BOTH the live per-tick
coach path and the offline build-order / loadout backfill (they share
``rank_for_primary_archetype``). Metric / stat-line only - no win-rate, no
blacklist, no name-gate beyond the existing fight_length allow-map.

DERIVATION (grounded in DDragon 16.13.1 base stats, no invented magic numbers)
------------------------------------------------------------------------------
Representative squishy-carry set = 19 enemy backline champions a crit ADC
deletes (ADCs: Caitlyn, Jinx, Ashe, Kai'Sa, Ezreal, Jhin, Zeri, Xayah, Aphelios,
Lucian; mages: Lux, Syndra, Ziggs, Xerath, Vex, Orianna, Zoe, Veigar, Brand).
Their DDragon ``stats`` base + per-level means (data/daemon_slayer/16.13.1/
champions.json), scaled by the canonical growth curve
``(n-1)*(0.7025 + 0.0175*(n-1))`` (the SAME formula agents.daemon_slayer.stats
uses), give:

    level:   armor    mr     hp
    L11      62.8    41.2   1522
    L12      67.6    42.6   1634
    L13      72.5    44.0   1750
    L16      88.3    48.6   2118   <- pure base, 0 defensive items

L16 ANCHOR (armor 70 / mr 50 / max_hp 2050 / bonus_hp 1450), each axis grounded:
  * target_armor 70 - the enemy carry's armor at the MID-GAME DELETION WINDOW
    (the first/second-item spike, ~L12-13, where a crit ADC actually bursts a
    carry BEFORE it completes a defensive item): set base armor L12=67.6 /
    L13=72.5, so 70 is the midpoint. LOW armor is what lets crit + lethality
    (Collector / LDR / Serylda's) out-value on-hit. Far below the 120 team avg.
  * target_mr 50 - the set base MR near operator level (L16=48.6). Largely inert
    for a PHYSICAL crit ADC (verified: sweeping target_mr does not reorder the
    carry ranking) - carried for completeness / future magic-crit champs.
  * target_max_hp 2050 / target_bonus_hp 1450 - the set base HP near operator
    level (L15=1992 / L16=2118); HP scales slowly so the carry is ~full-level HP
    even mid-fight. bonus_hp = max_hp - 600 (base-champ HP, mirrors
    enemy_stats._CHAMP_BASE_HP_AVG). Well below the 2760 team-average max_hp, so
    the current-HP on-hit item (BORK) and %max-HP procs lose their inflated lead.

The profile SCALES with level by each axis' representative-set growth ratio to
L16 (``scaled(base, per, level) / scaled(base, per, 16)``), so a lower-level call
gets a correspondingly lower squishy target and L16 returns the anchor exactly.

``mode`` is accepted for parity with the chokepoint (and future per-mode
calibration) but is currently unused: a squishy carry is squishy in every mode,
and the live validation is SR. ARAM / Arena / Brawl receive the same SR-derived
squishy profile until a mode-specific set is calibrated.
"""
from __future__ import annotations

# Representative squishy-carry set base + per-level stat means (DDragon 16.13.1,
# 19-champ set - see the module docstring). Used ONLY to scale the L16 anchor
# across levels via the canonical growth curve; scaled(_, _, 16) reproduces the
# L16 means (armor 88.3 / mr 48.6 / hp 2118.3).
_SET_ARMOR_BASE, _SET_ARMOR_PER = 23.68, 4.461
_SET_MR_BASE, _SET_MR_PER = 29.79, 1.300
_SET_HP_BASE, _SET_HP_PER = 604.53, 104.579

# L16 anchor (the mid-game-deletion-window squishy carry - see the docstring).
_ANCHOR_ARMOR = 70.0
_ANCHOR_MR = 50.0
_ANCHOR_MAX_HP = 2050.0

# Base-champion HP subtracted to get bonus_hp (mirrors
# coach_integration.enemy_stats._CHAMP_BASE_HP_AVG so both target derivations
# agree on the flat-HP baseline).
_BASE_CHAMP_HP = 600.0

# Champion level range (DDragon clamp).
_MIN_LEVEL, _MAX_LEVEL = 1, 18


def _growth(level: int) -> float:
    """Canonical per-level growth multiplier (agents.daemon_slayer.stats mirror).

    ``(n-1) * (0.7025 + 0.0175 * (n-1))`` - the League base-stat growth curve.
    Reproduced here (not imported) to keep this module engine-free.
    """
    return (level - 1) * (0.7025 + 0.0175 * (level - 1))


def _scaled(base: float, per: float, level: int) -> float:
    """``base + per * growth(level)`` - a representative-set stat at ``level``."""
    return base + per * _growth(level)


def squishy_carry_target(mode: str, level: int) -> dict:
    """Return the squishy-carry ranking target for a burst carry.

    Keys mirror the DS ``rank_for`` / ``rank_for_primary_archetype`` target
    kwargs: ``target_armor`` / ``target_mr`` / ``target_max_hp`` /
    ``target_bonus_hp``. The L16 anchor is 70 / 50 / 2050 / 1450; every axis
    scales with ``level`` by the representative squishy set's own growth ratio to
    L16 (so L16 returns the anchor exactly and a lower level returns a
    proportionally lower target). ``mode`` is accepted for parity but currently
    unused (see the module docstring). See the module docstring for the full
    DDragon 16.13.1 derivation. This is a caller-side stat-line policy - no
    win-rate, no engine import.
    """
    _ = mode  # reserved for future per-mode calibration; see the module docstring
    lvl = max(_MIN_LEVEL, min(_MAX_LEVEL, int(level)))

    def _axis(anchor: float, base: float, per: float) -> float:
        return anchor * _scaled(base, per, lvl) / _scaled(base, per, 16)

    armor = _axis(_ANCHOR_ARMOR, _SET_ARMOR_BASE, _SET_ARMOR_PER)
    mr = _axis(_ANCHOR_MR, _SET_MR_BASE, _SET_MR_PER)
    max_hp = _axis(_ANCHOR_MAX_HP, _SET_HP_BASE, _SET_HP_PER)
    bonus_hp = max(0.0, max_hp - _BASE_CHAMP_HP)
    return {
        "target_armor": round(armor, 1),
        "target_mr": round(mr, 1),
        "target_max_hp": round(max_hp, 1),
        "target_bonus_hp": round(bonus_hp, 1),
    }
