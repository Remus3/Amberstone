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

Contract: fail-soft on the LIVE CONTEXT inputs (S144-T-570). DSP5 and DSP6
never raise and always return finite numbers: a junk id (non-numeric string,
None, bool, fractional or non-finite float, any other object) is dropped and
the rest of the set still counts; a bare scalar is ONE id, never iterated per
character ("14" is Ignite, not Cleanse + Flash); a non-finite or non-number
``level`` is the default 1.0; a non-finite or non-number HP is 0.0;
``antiheal_present`` is armed only by True, a non-zero finite number or a
"true" / "yes" / "on" / "1" word. DSP7 is fail-soft on its GRANT inputs the
same way (a malformed ``granter_resists`` value or slot is absent, a bare
string granter is one champion); ``champion_id`` / ``level`` / ``item_ids`` /
``mode`` errors still raise (KeyError / ValueError from ``compute_ehp``, which
``/ally-protected-ehp`` maps to 404 / 422; the route validates ``level``). Well-formed input is
byte-identical to the pre-hardening module. ASCII only.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

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


# --- input coercion (S144-T-570) ----------------------------------------------

_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})


def _finite_or(value: Any, default: float) -> float:
    """``value`` as a finite float, else ``default``.

    bool is not a number here (``True`` would read as 1.0); a numeric string
    is read, as the DS routes' ``_finite_float`` reads one.
    """
    if isinstance(value, bool):
        return default
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return f if math.isfinite(f) else default


def _one_id(value: Any) -> Optional[int]:
    """One Riot id, or None when ``value`` is not an integral id."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _id_list(values: Any) -> list[int]:
    """Riot ids from an id set; a bare scalar is ONE id, junk ids drop."""
    if values is None:
        return []
    if isinstance(values, (str, int, float)):
        values = (values,)
    try:
        items = list(values)
    except TypeError:
        return []
    return [i for i in (_one_id(v) for v in items) if i is not None]


def _flag(value: Any) -> bool:
    """A strict boolean: garbage, NaN and every other word read False."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return math.isfinite(value) and value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_WORDS
    return False


def _champion_list(values: Any) -> list[str]:
    """Granter champion ids; a bare string is ONE champion, non-strings drop."""
    if values is None:
        return []
    if isinstance(values, str):
        values = (values,)
    try:
        items = list(values)
    except TypeError:
        return []
    return [v for v in items if isinstance(v, str)]


def _resist_slots(value: Any) -> tuple[float, float, float, float]:
    """``(total_armor, total_mr, base_armor, base_mr)`` from one
    ``granter_resists`` value. A non-sequence (or a string / mapping) is
    absent; a malformed slot is 0.0; a missing slot is 0.0."""
    if not isinstance(value, (list, tuple)):
        return (0.0, 0.0, 0.0, 0.0)
    slots = [_finite_or(v, 0.0) for v in value[:4]]
    slots += [0.0] * (4 - len(slots))
    return (slots[0], slots[1], slots[2], slots[3])


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
    (unknown ids contribute 0.0; junk ids drop; a bad level is 1.0).
    """
    self_ids = _id_list(self_spell_ids)
    enemy_ids = _id_list(enemy_spell_ids)
    level = _finite_or(level, 1.0)
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
    pure no-op (divisor 1.0). Fail-soft: junk ids drop (the rest still count),
    a bad level is 1.0, a bad or negative HP is 0.0, so every output is
    finite (the registry magnitudes are finite).
    """
    ids = _id_list(enemy_rune_ids)
    level = _finite_or(level, 1.0)
    max_hp = _finite_or(enemy_max_hp, 0.0)
    # A negative missing HP would turn Second Wind into an enemy HP LOSS.
    missing_hp = max(0.0, _finite_or(enemy_missing_hp, 0.0))
    amp = float(enemy_incoming_amp_pct(ids))
    poke = (
        float(enemy_poke_sustain_hp(ids, max_hp, missing_hp))
        if max_hp > 0.0 else 0.0
    )
    return EnemyRuneThreatSummary(
        incoming_amp_pct=amp,
        damage_ramp=float(enemy_damage_ramp(ids, level)),
        poke_sustain_hp=poke,
        antiheal_pct=float(enemy_antiheal_pct(_flag(antiheal_present))),
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
    Orianna/Braum grants are self-contained). Fail-soft on the grant inputs:
    a bare string granter is one champion, a non-string granter is skipped
    (a blank one matches no granter), a ``granter_resists`` that is not a
    mapping is absent, a value that is not a list / tuple is absent, and a
    bool, null, non-numeric or non-finite slot is 0.0. A bad ``level`` still
    raises (the grant helpers' ``int(level)``, then ``compute_ehp``), as do
    ``champion_id`` / ``item_ids`` / ``mode`` errors from ``compute_ehp``.
    """
    allies = _champion_list(ally_grant_champions)
    flat_hp = 0.0
    ext_armor = ext_mr = 0.0
    gr = granter_resists if isinstance(granter_resists, Mapping) else {}
    for g in allies:
        flat_hp += ally_flat_hp_grant(g, level, True)
        total_armor, total_mr, base_armor, base_mr = _resist_slots(gr.get(g))
        a, m = ally_resist_grant(
            g, level, True,
            granter_total_armor=total_armor,
            granter_total_mr=total_mr,
            granter_base_armor=base_armor,
            granter_base_mr=base_mr,
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
