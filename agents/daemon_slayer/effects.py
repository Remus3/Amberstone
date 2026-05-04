"""Phase 4 thin slice — per-item conditional effects.

DDragon item ``stats`` blocks only carry the flat/percent stat lines
(AD, AS, crit, hp, ...). The DPS-relevant text — IE's crit-damage bump,
Kraken's every-3rd-attack proc, Stormrazor's Energized — lives in the
description prose with the numbers stripped. This module pins those
numbers per-patch as Python constants so ``dps.py`` can layer them onto
the rotation math.

The thin slice covers five marquee items (IE, Bloodthirster,
Stormrazor, Kraken Slayer, Immortal Shieldbow). The pattern is the
extension point: adding more items means appending to ``ITEM_EFFECTS``.
The schema deliberately stays narrow — only ``crit_damage_bonus`` and
a single ``PeriodicProc`` per item — and will need to grow callable
scaling (vs target missing HP, vs bonus AD, etc.) when the long tail
of items lands. Until then, constants are honest about being
patch-pinned approximations.

Items whose effect is purely defensive (BT shield, Shieldbow lifeline)
are listed with ``defensive_only=True`` so the schema is exercised
end-to-end and so a future review can spot which items need DPS modeling
versus which are correctly DPS-neutral.

Numbers below are pinned to patch 16.9.1 (matches
``data/daemon_slayer/current.txt``). When the snapshot bumps, the
extractor manifest will diverge from this constant table — Phase 4
expansion lands a patch-notes diff that re-pins these values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


PHYSICAL = "physical"
MAGICAL = "magical"
_DAMAGE_TYPES = frozenset({PHYSICAL, MAGICAL})


@dataclass(frozen=True)
class PeriodicProc:
    """A periodic on-hit / on-timer damage proc.

    Either ``every_n_attacks`` (Kraken-style) OR ``every_n_seconds``
    (Stormrazor-style) is set; the other stays at the default zero.
    Both being set is a config error caught at construction.
    """
    name: str
    bonus_damage: float
    damage_type: str
    every_n_attacks: int = 0
    every_n_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.damage_type not in _DAMAGE_TYPES:
            raise ValueError(
                f"PeriodicProc.damage_type must be one of {sorted(_DAMAGE_TYPES)}, "
                f"got {self.damage_type!r}"
            )
        attacks_set = self.every_n_attacks > 0
        seconds_set = self.every_n_seconds > 0
        if attacks_set == seconds_set:
            raise ValueError(
                "PeriodicProc must set exactly one of every_n_attacks "
                "(>0) or every_n_seconds (>0)"
            )


@dataclass(frozen=True)
class ItemEffect:
    item_id: str
    name: str
    crit_damage_bonus: float = 0.0   # added to dps.DEFAULT_CRIT_BONUS
    periodic: Optional[PeriodicProc] = None
    defensive_only: bool = False     # documents "no DPS effect" entries
    note: str = ""                   # one-line summary surfaced in DpsResult.notes


# Patch 16.9.1 — refresh on patch bump (extractor manifest is the trigger).
ITEM_EFFECTS: dict[str, ItemEffect] = {
    "3031": ItemEffect(
        item_id="3031",
        name="Infinity Edge",
        crit_damage_bonus=0.30,
        note="Infinity Edge: +30% bonus crit damage",
    ),
    "3072": ItemEffect(
        item_id="3072",
        name="Bloodthirster",
        defensive_only=True,
        note="Bloodthirster: Ichorshield (excess lifesteal → shield); no DPS contribution",
    ),
    "3097": ItemEffect(
        item_id="3097",
        name="Stormrazor",
        periodic=PeriodicProc(
            name="Energized Bolt",
            bonus_damage=120.0,
            damage_type=MAGICAL,
            every_n_seconds=4.0,
        ),
        note="Stormrazor: Energized ~120 magic dmg every ~4s",
    ),
    "6672": ItemEffect(
        item_id="6672",
        name="Kraken Slayer",
        periodic=PeriodicProc(
            name="Bring It Down",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_attacks=3,
        ),
        note="Kraken Slayer: Bring It Down ~100 physical dmg every 3rd attack",
    ),
    "6673": ItemEffect(
        item_id="6673",
        name="Immortal Shieldbow",
        defensive_only=True,
        note="Immortal Shieldbow: Lifeline (low-HP shield); no DPS contribution",
    ),
}


def collect_effects(item_ids: Iterable[str | int]) -> list[ItemEffect]:
    """Return the ItemEffect entries that match the build's items, in order.

    Items without an entry in ``ITEM_EFFECTS`` are silently skipped — they
    contribute their stat-block to the engine via ``stats.aggregate_item_stats``
    but no conditional layer applies. Duplicates (e.g. two IEs) are kept
    so the engine's existing item-stack semantics carry through; the engine
    does not enforce per-item uniqueness.
    """
    out: list[ItemEffect] = []
    for iid in item_ids:
        eff = ITEM_EFFECTS.get(str(iid))
        if eff is not None:
            out.append(eff)
    return out


def total_crit_damage_bonus(effects: Iterable[ItemEffect]) -> float:
    """Sum ``crit_damage_bonus`` across the build's effects."""
    return sum(e.crit_damage_bonus for e in effects)
