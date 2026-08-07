"""DSP5/6/7 live-context consumers (no-op until a live surface supplies context).

The three DSP substrate seams shipped registries but NO scorer consumes them -
a flag-flip does nothing until a consumer reads the registry against the LIVE
summoner / rune / ally set. This module is that consumer layer: three thin,
pure, fail-soft functions a live surface (fight_report / matchup / a coach / a
peel readout) calls with the real live-client context. Each is byte-identical
to the pre-DSP engine when given an EMPTY context (no spells / no runes / no
allies), so importing + wiring it changes nothing until a live caller supplies
data.

The LIVE default-ON wire (feeding the real summoner / rune / ally set from the
live client + eyeballing the adjusted readout) stays operator-gated - see
docs/LIVE_GAME_GATED_SYNC.md. Per the seam contract a WRONG precompute is worse
than none, so the wire is validated against a real game before it is taken.

  * DSP5 summoner_fight_adjustments - self + enemy summoner-spell adjustments
  * DSP6 enemy_rune_threat          - enemy-rune incoming-amp / ramp / sustain / antiheal
  * DSP7 ally_protected_ehp         - an ally's EHP with enchanter shield/heal +
                                      resist grants folded in (also the item-321
                                      ally-resist producer surface)

Contract: fail-soft (never raises). ASCII only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from ._passive_ally_grant_overrides import ally_flat_hp_grant, ally_resist_grant
from .data_loader import DataSnapshot
from .ehp import EhpResult, compute_ehp
from .enemy_runes import (
    enemy_antiheal_pct,
    enemy_damage_ramp,
    enemy_incoming_amp_pct,
    enemy_poke_sustain_hp,
)
from .summoners import (
    compute_summoner_ehp_bonus,
    compute_summoner_ms_pct,
    summoner_antiheal_pct,
    summoner_cc_discount_pct,
    summoner_incoming_dr_pct,
)

__all__ = [
    "SummonerFightAdjustments",
    "EnemyRuneThreatSummary",
    "summoner_fight_adjustments",
    "enemy_rune_threat",
    "ally_protected_ehp",
]


# --- DSP5 summoner-spell consumer -------------------------------------------

@dataclass(frozen=True)
class SummonerFightAdjustments:
    """Aggregated summoner-spell combat adjustments for one fight.

    ``self_*`` are sourced from the PLAYER's two spells, ``enemy_*`` from the
    enemy's. CC-discount / MS / incoming-DR take the BEST spell in the set (they
    do not stack); EHP-bonus sums (Heal + Barrier could both be carried). An
    EMPTY set on a side leaves its fields 0.0 (byte-identical no-op).
    """

    self_ehp_bonus: float = 0.0        # Heal + Barrier flat EHP-equivalent
    self_cc_discount_pct: float = 0.0  # Cleanse tenacity (best)
    self_ms_pct: float = 0.0           # Ghost / Heal move speed (best)
    self_incoming_dr_pct: float = 0.0  # Exhaust on the enemy carry (best)
    enemy_antiheal_pct: float = 0.0    # enemy Ignite -> discount OUR heals (best)


def summoner_fight_adjustments(
    self_spell_ids: Iterable[int] = (),
    enemy_spell_ids: Iterable[int] = (),
    level: float = 1.0,
) -> SummonerFightAdjustments:
    """Fold the player's + enemy's live summoner set into one adjustment struct.

    Reads ``summoners.py`` per spell id. Empty inputs -> all-zero. Fail-soft
    (unknown ids contribute 0.0).
    """
    self_ids = [int(s) for s in (self_spell_ids or ())]
    enemy_ids = [int(s) for s in (enemy_spell_ids or ())]
    return SummonerFightAdjustments(
        self_ehp_bonus=float(sum(compute_summoner_ehp_bonus(s, level) for s in self_ids)),
        self_cc_discount_pct=max(
            (summoner_cc_discount_pct(s) for s in self_ids), default=0.0),
        self_ms_pct=max(
            (compute_summoner_ms_pct(s, level) for s in self_ids), default=0.0),
        self_incoming_dr_pct=max(
            (summoner_incoming_dr_pct(s) for s in self_ids), default=0.0),
        enemy_antiheal_pct=max(
            (summoner_antiheal_pct(s) for s in enemy_ids), default=0.0),
    )


# --- DSP6 enemy-rune threat consumer ----------------------------------------

@dataclass(frozen=True)
class EnemyRuneThreatSummary:
    """Enemy-rune threat folded for the player's effective-survivability lens.

    ``ehp_divisor`` = ``1 + incoming_amp_pct``; divide a player EHP value by it
    to model the enemy's damage amp. ``antiheal_pct`` discounts the player's
    heal-based EHP. EMPTY rune set -> amp 0.0, divisor 1.0 (no-op).
    """

    incoming_amp_pct: float = 0.0   # Press the Attack: enemy damage amp on player
    damage_ramp: float = 0.0        # Conqueror max-stack bonus Adaptive Force
    poke_sustain_hp: float = 0.0    # Grasp + Second Wind enemy poke recovery
    antiheal_pct: float = 0.0       # enemy antiheal -> discount our heal-EHP
    ehp_divisor: float = 1.0        # 1 + incoming_amp_pct


def enemy_rune_threat(
    enemy_rune_ids: Iterable[int] = (),
    level: float = 1.0,
    *,
    antiheal_present: bool = False,
    enemy_max_hp: float = 0.0,
    enemy_missing_hp: float = 0.0,
) -> EnemyRuneThreatSummary:
    """Fold the enemy's live rune set into one threat struct.

    Reads ``enemy_runes.py``. ``poke_sustain_hp`` needs ``enemy_max_hp`` (0.0
    leaves it 0.0). ``antiheal_present`` is True when ANY antiheal source is on
    the enemy team (no rune grants it; items/Ignite do). Empty + defaults -> a
    pure no-op (divisor 1.0). Fail-soft.
    """
    ids = [int(r) for r in (enemy_rune_ids or ())]
    amp = float(enemy_incoming_amp_pct(ids))
    poke = (
        float(enemy_poke_sustain_hp(ids, enemy_max_hp, enemy_missing_hp))
        if enemy_max_hp > 0.0 else 0.0
    )
    return EnemyRuneThreatSummary(
        incoming_amp_pct=amp,
        damage_ramp=float(enemy_damage_ramp(ids, level)),
        poke_sustain_hp=poke,
        antiheal_pct=float(enemy_antiheal_pct(bool(antiheal_present))),
        ehp_divisor=1.0 + amp,
    )


# --- DSP7 ally-grant EHP consumer -------------------------------------------

def ally_protected_ehp(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Sequence[str | int]] = None,
    ally_grant_champions: Iterable[str] = (),
    *,
    mode: str = "SR",
    enemy_champions: Iterable[str] = (),
    granter_resists: Optional[dict] = None,
    apply_mode_modifiers: bool = False,
) -> EhpResult:
    """EHP of ``champion_id`` with its live allies' enchanter grants folded in.

    Sums, over ``ally_grant_champions`` (the protected ally's LIVE teammates),
    each granter's flat-HP grant (DSP7 - Janna/Lulu/Karma/Yuumi E + Seraphine W
    shields, Soraka/Nami W heals) and resist grant (item-321 ally-resist -
    Orianna E / Braum W / Taric W), and feeds them to ``compute_ehp`` as
    ``external_flat_hp`` / ``external_resist_armor`` / ``external_resist_mr``.

    EMPTY ``ally_grant_champions`` -> external_* all 0.0 -> byte-identical to a
    plain ``compute_ehp`` call. Taric's percent-of-resist grant needs the
    granter's resolved armor/MR via ``granter_resists[granter] = (total_armor,
    total_mr, base_armor, base_mr)``; absent it contributes 0.0 (the flat
    Orianna/Braum grants are self-contained). Fail-soft.
    """
    allies = [str(a) for a in (ally_grant_champions or ()) if str(a)]
    flat_hp = 0.0
    ext_armor = ext_mr = 0.0
    gr = granter_resists or {}
    for g in allies:
        flat_hp += ally_flat_hp_grant(g, level, True)
        r = tuple(gr.get(g) or ())
        a, m = ally_resist_grant(
            g, level, True,
            granter_total_armor=r[0] if len(r) > 0 else 0.0,
            granter_total_mr=r[1] if len(r) > 1 else 0.0,
            granter_base_armor=r[2] if len(r) > 2 else 0.0,
            granter_base_mr=r[3] if len(r) > 3 else 0.0,
        )
        ext_armor += a
        ext_mr += m
    return compute_ehp(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=item_ids,
        mode=mode,
        enemy_champions=enemy_champions,
        external_flat_hp=max(0.0, flat_hp),
        external_resist_armor=max(0.0, ext_armor),
        external_resist_mr=max(0.0, ext_mr),
        # RM-172: compute_ehp has accepted this since item 232; this consumer
        # never forwarded it, so /ally-protected-ehp could not reach the ARENA
        # stat-growth addend lane. DEFAULT-OFF -> byte-identical.
        apply_mode_modifiers=apply_mode_modifiers,
    )
