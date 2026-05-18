"""Arena augment data layer + stat-overlay scaffold (Phase 6 step 2).

Loads cdragon's Arena (cherry) augment dump from
``data/daemon_slayer/<patch>/arena_augments.json`` and exposes a typed
:class:`Augment` view plus a ``compute_augment_stats()`` overlay used by the
engine when ``mode == ARENA``.

Per-augment stat overlays are added incrementally. The current registry covers
only the stat-defining augments where the overlay is uncontroversial (flat AD,
flat AP, flat HP, AS%, AH, MR, armor). Combat-mechanic augments (chain damage,
revives, summoner spells) are left to step 3 once the engine grows a hook for
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# ─── Rarity constants (cdragon convention) ───────────────────────────────────
# 0 = Silver, 1 = Gold, 2 = Prismatic, 4 = Hero (apiName starts with "GoH")
RARITY_SILVER = 0
RARITY_GOLD = 1
RARITY_PRISMATIC = 2
RARITY_HERO = 4

RARITY_LABEL: dict[int, str] = {
    RARITY_SILVER: "silver",
    RARITY_GOLD: "gold",
    RARITY_PRISMATIC: "prismatic",
    RARITY_HERO: "hero",
}


@dataclass(frozen=True)
class Augment:
    id: int
    api_name: str
    name: str
    rarity: int
    desc: str
    data_values: dict
    tooltip: str = ""

    @property
    def rarity_label(self) -> str:
        return RARITY_LABEL.get(self.rarity, f"r{self.rarity}")

    @classmethod
    def from_record(cls, rec: dict) -> "Augment":
        return cls(
            id=int(rec.get("id", 0)),
            api_name=str(rec.get("apiName", "")),
            name=str(rec.get("name", "")),
            rarity=int(rec.get("rarity", -1)),
            desc=str(rec.get("desc", "")),
            tooltip=str(rec.get("tooltip", "")),
            data_values=dict(rec.get("dataValues") or {}),
        )


# ─── Stat overlay registry ───────────────────────────────────────────────────
#
# Each entry: apiName → callable(augment) -> dict[canonical_stat_key, value]
# Canonical stat keys match `agents/daemon_slayer/stats.py` RESOLVED_STAT_ORDER:
#   "hp", "mp", "hpregen", "mpregen", "armor", "mr", "ad", "ap", "as",
#   "crit", "lifesteal", "spellvamp", "ms", "attackrange"
# AS values are unit-fraction bonus (0.10 = +10% AS), matching ITEM_STAT_KEY_MAP.
# Crit chance is unit-fraction (0.25 = +25%).
#
# dataValues entries are arrays indexed by stack/level; for static stats we
# read index 0 (the "base" value Riot ships).
def _v(aug: Augment, key: str, idx: int = 0, default: float = 0.0) -> float:
    arr = aug.data_values.get(key)
    if isinstance(arr, list) and len(arr) > idx:
        try:
            return float(arr[idx])
        except (TypeError, ValueError):
            return default
    if isinstance(arr, (int, float)):
        return float(arr)
    return default


# Tier-1 registry: verified against the cdragon dataValues field at index 0
# (the base value Riot ships for the augment's first acquisition).
#
# Conservative: only purely-additive flat-stat augments where the engine's
# post-combine merge is faithful. Skipped categories (and why):
#
# * **AS-bearing augments** (Deft, Chauffeur, DualWield, Quest_AngelofRetribution,
#   MadScientist) - engine treats item AS as multiplicative on base via
#   ``_combine_items`` (``base_as × (1 + bonus_pct)``). The augment overlay
#   merges AFTER ``_combine_items`` as a flat add, which is wrong by the
#   factor of base_as for AS. Needs an ``as_pct``-style overlay channel
#   before these can land. Tracked for a follow-up pass.
# * **AbilityHaste-only augments** (Recursion, BacktoBasics, BreadSandwich,
#   Dashing) - ``ah`` is not a canonical stat key in stats.py.
# * **Omnivamp augments** (Goredrink, Vengeance) - not modeled.
# * **AdaptiveForce augments** (SlapAround, Dematerialize, MagicalGirl) -
#   AF resolves to AD or AP via game-side rules; needs caller context.
#   Most are also stack/conditional grants.
# * **Conditional / active-mechanic** augments (Firefox autocast, Homeguard
#   speed-burst, Quest_*, MadScientist random per-round, BigBrain's AP=1.0
#   ratio anchor) - overlay can't honestly capture uptime/triggered grants.
# * **Ratio / tradeoff** augments (Chauffeur immobility, DrawYourSword
#   melee-conversion) - mechanic cost not modeled.
_AUGMENT_STAT_OVERLAYS: dict[str, callable] = {
    # Silver: +20 AD, +10 ability haste, +10 lethality. (Lethality not yet a
    # canonical stat key - silently dropped; AD overlay is what matters.)
    "TheBrutalizer": lambda a: {
        "ad": _v(a, "AD"),
    },
    # Gold: +1000 HP. Augment also imposes a damage-reduction debuff, but
    # the engine doesn't model damage taken/dealt mods - stat is honest.
    "CelestialBody": lambda a: {
        "hp": _v(a, "Health"),
    },
    # Silver: +60 AP, no tradeoff.
    "WitchfulThinking": lambda a: {
        "ap": _v(a, "AP"),
    },
    # Gold: +50% crit chance. Pure flat grant, no condition.
    "ItsCritical": lambda a: {
        "crit": _v(a, "CritChance"),
    },
    # Prismatic: +25% crit chance. The "Your Abilities can Critically
    # Strike" clause is a separate mechanic; the crit-chance grant itself
    # is unconditional.
    "JeweledGauntlet": lambda a: {
        "crit": _v(a, "CritChance"),
    },
    # Gold: +25% crit chance. Heal/shield-crit clause is a parallel
    # mechanic; the +25% crit grant lands unconditionally.
    "CriticalHealing": lambda a: {
        "crit": _v(a, "CritChance"),
    },
    # Gold: +25% crit chance. The lifesteal-on-crit clause is parallel;
    # the crit grant is unconditional.
    "SoulSiphon": lambda a: {
        "crit": _v(a, "CritChance"),
    },
    # Gold: +25% crit chance. The "items + DoT can crit" clause expands
    # what crit applies to; the crit grant itself is flat.
    "Vulnerability": lambda a: {
        "crit": _v(a, "CritChance"),
    },
    # Silver: +25% crit chance. Defensive-crit mechanic (Critically Defend)
    # uses the same crit pool but doesn't consume the offensive grant.
    "TankItOrLeaveIt": lambda a: {
        "crit": _v(a, "CritChance"),
    },
    # Silver: +10 flat MS. SlowResist also granted but not a canonical
    # stat key. Engine merges flat MS additively after item flat+pct
    # combine, which slightly underweights the augment when the player
    # also has %MS items (e.g. boot enchants); acceptable for a coach.
    "LegDay": lambda a: {
        "ms": _v(a, "MovementSpeed"),
    },
}


def compute_augment_stats(
    augments: Iterable[Augment | dict | int | str],
    snapshot,
) -> dict[str, float]:
    """Sum stat overlays for the given augments.

    Accepts ``Augment`` instances, raw cdragon records (dicts), or
    id/apiName references (int/str) - refs are resolved via ``snapshot``.
    Unknown augments are silently treated as zero overlay until their entry
    lands in :data:`_AUGMENT_STAT_OVERLAYS`. This is intentional: we
    progressively add stat-bearing augments without breaking calls that
    pass a full augment list.
    """
    totals: dict[str, float] = {}
    for entry in augments:
        if isinstance(entry, Augment):
            aug = entry
        elif isinstance(entry, dict):
            aug = Augment.from_record(entry)
        elif isinstance(entry, (int, str)):
            try:
                rec = snapshot.arena_augment(entry)
            except (KeyError, AttributeError):
                continue
            aug = Augment.from_record(rec)
        else:
            continue
        fn = _AUGMENT_STAT_OVERLAYS.get(aug.api_name)
        if fn is None:
            continue
        for k, v in fn(aug).items():
            if not v:
                continue
            totals[k] = totals.get(k, 0.0) + float(v)
    return totals


def list_augments_by_rarity(snapshot, rarity: int) -> list[Augment]:
    return [
        Augment.from_record(rec)
        for rec in snapshot.arena_augments_by_id.values()
        if rec.get("rarity") == rarity
    ]
