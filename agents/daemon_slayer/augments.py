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
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from agents.daemon_slayer.data_loader import DataSnapshot

# --- Rarity constants (cdragon convention) -----------------------------------
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
    # cdragon `calculations` formula defs (Riot's GameCalculation struct).
    # Each key is a calculation name (e.g. "Damage", "TotalDamage"); value
    # carries `mFormulaParts` + optional `mMultiplier`. Captured here so
    # downstream formula evaluators can compute real scaling instead of
    # relying on the hand-maintained `_AUGMENT_STAT_OVERLAYS` registry.
    # 83/220 augments ship non-empty calculations as of cdragon 16.10.1.
    calculations: dict = None  # populated in __post_init__ when None
    tooltip: str = ""

    def __post_init__(self) -> None:
        # frozen dataclass: bypass setattr for the default-None case.
        if self.calculations is None:
            object.__setattr__(self, "calculations", {})

    @property
    def rarity_label(self) -> str:
        return RARITY_LABEL.get(self.rarity, f"r{self.rarity}")

    @property
    def calculation_keys(self) -> list[str]:
        """Names of formula entries available for this augment (may be empty)."""
        return list(self.calculations.keys())

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
            calculations=dict(rec.get("calculations") or {}),
        )


# --- Stat overlay registry ---------------------------------------------------
#
# Each entry: apiName -> callable(augment) -> dict[canonical_stat_key, value]
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
#   ``_combine_items`` (``base_as x (1 + bonus_pct)``). The augment overlay
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
AIM_FOR_THE_HEAD = "AimForTheHead"

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
    # Gold (id 336): "Gain 25% Critical Strike Chance and 25% Critical Strike
    # Damage" - the flat half of Aim for the Head. The cap + excess conversion
    # half is NOT an additive overlay; it runs in apply_augment_conversions
    # once the build's raw (uncapped) crit chance is known. ``crit_damage`` is
    # a bonus crit-damage FRACTION added to dps.DEFAULT_CRIT_BONUS, the same
    # unit as ItemEffect.crit_damage_bonus (Infinity Edge +0.30).
    AIM_FOR_THE_HEAD: lambda a: {
        "crit": _v(a, "CritChanceBonus"),
        "crit_damage": _v(a, "CritDamageBonus"),
    },
}


# --- Conversion augments -----------------------------------------------------
#
# Augments whose effect depends on the FINISHED build (a cap on a stat, or one
# stat converted into another) cannot be an additive overlay. They run after
# the overlay merge in engine.build_champion via apply_augment_conversions.
# Mechanics re-implemented from the augment's own game text + dataValues in
# the cdragon arena dump (data/daemon_slayer/<patch>/arena_augments.json);
# index 0 of each dataValues array, the same convention as _v() above.
#
# * AimForTheHead (id 336, Gold) - desc: "Your Critical Strike Chance is
#   capped at @CritChanceCeiling*100@%. Convert @CritChanceToDamageRatio*100@%
#   of Critical Strike Chance above @CritChanceCeiling*100@% into Critical
#   Strike Damage." 16.18.1: ceiling 0.5, ratio 0.4. The excess is measured
#   on the RAW sum (items + augments, before League's 100% clamp), because the
#   text converts chance "above" the ceiling and does not stop at 100%.
# * TapDancer (id 81, Prismatic) - desc: "Your Attacks grant you @MSPerHit@
#   Move Speed On-Hit. Gain Attack Speed equal to @MSToASConversion*10000@% of
#   your Move Speed." 16.18.1: 6 MS per hit, conversion 0.001 (the tooltip
#   calc MSToASConversionCalc = MSToASConversion x stat 7 (move speed),
#   displayed as a percent: 400 MS -> +40% bonus attack speed). The text
#   names NO stack cap and no duration, so stacks are a caller input with an
#   assumed default; the only ceiling is League's 2.5 attack-speed cap.
TAP_DANCER = "TapDancer"

# Assumed on-hit stacks for Tap Dancer when the caller supplies none: a
# sustained-fight mid-point (about 10 autos into an Arena round fight).
# Operator-tunable, mirroring dps._ASSUMED_TAKEDOWN_STACKS doctrine.
ASSUMED_TAP_DANCER_STACKS = 10


def soft_capped_move_speed(raw_ms: float) -> float:
    """League's move-speed soft caps (the value the game calls "your Move
    Speed"): x0.5 below 220, x0.8 above 415, x0.5 above 490. Continuous at
    every breakpoint (415 -> 415, 490 -> 475)."""
    if raw_ms > 490.0:
        return raw_ms * 0.5 + 230.0
    if raw_ms > 415.0:
        return raw_ms * 0.8 + 83.0
    if raw_ms < 220.0:
        return raw_ms * 0.5 + 110.0
    return raw_ms


def resolve_augment(entry, snapshot: "DataSnapshot") -> Augment | None:
    """Resolve one augment reference (Augment / record / id / apiName / name)
    to an :class:`Augment`, or None when the snapshot does not know it."""
    if isinstance(entry, Augment):
        return entry
    if isinstance(entry, dict):
        return Augment.from_record(entry)
    if isinstance(entry, (int, str)):
        try:
            return Augment.from_record(snapshot.arena_augment(entry))
        except (KeyError, AttributeError):
            return None
    return None


def _resolved_by_api(augments, snapshot) -> dict[str, Augment]:
    out: dict[str, Augment] = {}
    for entry in augments or ():
        aug = resolve_augment(entry, snapshot)
        if aug is not None and aug.api_name not in out:
            out[aug.api_name] = aug
    return out


def crit_ceiling_rule(
    augments, snapshot: "DataSnapshot"
) -> tuple[float, float] | None:
    """``(ceiling, excess_to_damage_ratio)`` when Aim for the Head is taken,
    else None. compute_dps uses it to cap the ITEM-EFFECT crit it adds on top
    of the stat block (Yun Tal Wildarrows) and convert that excess too."""
    aug = _resolved_by_api(augments, snapshot).get(AIM_FOR_THE_HEAD)
    if aug is None:
        return None
    return _v(aug, "CritChanceCeiling"), _v(aug, "CritChanceToDamageRatio")


def has_conversion_augment(augments, snapshot: "DataSnapshot") -> bool:
    by_api = _resolved_by_api(augments, snapshot)
    return AIM_FOR_THE_HEAD in by_api or TAP_DANCER in by_api


def apply_augment_conversions(
    final: dict[str, float],
    base_as: float,
    raw_crit: float,
    augments,
    snapshot: "DataSnapshot",
    augment_stacks: dict | None = None,
    attack_speed_cap: float = 2.5,
) -> list[str]:
    """Apply cap / conversion augments to the finished stat block IN PLACE.

    ``raw_crit`` is the build's crit chance BEFORE any clamp (items plus
    additive augment overlays). ``base_as`` is the champion's level-1 base
    attack speed, the multiplicand the engine uses for every bonus-AS
    fraction. Returns human-readable notes. A build with neither augment is
    untouched and returns [].
    """
    by_api = _resolved_by_api(augments, snapshot)
    notes: list[str] = []

    aim = by_api.get(AIM_FOR_THE_HEAD)
    if aim is not None:
        ceiling = _v(aim, "CritChanceCeiling")
        ratio = _v(aim, "CritChanceToDamageRatio")
        excess = max(0.0, raw_crit - ceiling)
        final["crit"] = min(final.get("crit", 0.0), ceiling)
        if excess > 0:
            final["crit_damage"] = final.get("crit_damage", 0.0) + ratio * excess
        notes.append(
            f"Aim for the Head: crit chance capped at {ceiling:.2f} "
            f"(raw {raw_crit:.4f}), excess x{ratio:.2f} -> "
            f"+{ratio * excess:.4f} crit damage"
        )

    tap = by_api.get(TAP_DANCER)
    if tap is not None:
        stacks = ASSUMED_TAP_DANCER_STACKS
        if augment_stacks and TAP_DANCER in augment_stacks:
            stacks = max(0.0, float(augment_stacks[TAP_DANCER]))
        ms = final.get("ms", 0.0) + _v(tap, "MSPerHit") * stacks
        final["ms"] = ms
        bonus_as = _v(tap, "MSToASConversion") * soft_capped_move_speed(ms)
        final["as"] = min(
            attack_speed_cap, final.get("as", 0.0) + base_as * bonus_as
        )
        notes.append(
            f"Tap Dancer: {stacks:g} on-hit stack(s) -> {ms:.1f} MS, "
            f"+{bonus_as:.4f} bonus AS from move speed"
        )
    return notes


def compute_augment_stats(
    augments: Iterable[Augment | dict | int | str],
    snapshot: "DataSnapshot",
) -> dict[str, float]:
    """Sum stat overlays for the given augments.

    Accepts ``Augment`` instances, raw cdragon records (dicts), or
    id/apiName references (int/str) - refs are resolved via ``snapshot``.
    Unknown augments are silently treated as zero overlay until their entry
    lands in :data:`_AUGMENT_STAT_OVERLAYS`. This is intentional: we
    progressively add stat-bearing augments without breaking calls that
    pass a full augment list.

    Resolution order per augment:
      1. If the augment ships non-empty ``calculations`` AND any calc key
         maps to a canonical stat grant via the formula-evaluator's
         ``STAT_GRANT_CALC_KEYS`` registry, evaluate via
         ``stat_overlay_from_calculations``. This is the seam that, once
         populated, displaces the hand-maintained overlay registry for the
         augment in question. At 16.13.1 the registry is still empty so this
         path returns ``{}`` for every augment: the only stat-named calc key
         in the data (MasterofDuality ADGained/APGained) is an
         uptime-conditional build-up grant, deliberately excluded, not a
         static overlay.
      2. Otherwise fall back to ``_AUGMENT_STAT_OVERLAYS`` (the
         hand-maintained registry, today the source of truth for 11/220
         augments + the 137/220 augments that ship empty calculations).
      3. If neither path produces an overlay, the augment is silently
         skipped.
    """
    # Local import to keep the evaluator decoupled from augments.py at
    # module-load time; both modules are pure and the import is cheap.
    from .augment_formula_eval import stat_overlay_from_calculations

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
        # Path 1: formula evaluator (preferred when calc keys are stat-named).
        overlay = stat_overlay_from_calculations(aug) if aug.calculations else {}
        # Path 2: hand-maintained registry fallback.
        if not overlay:
            fn = _AUGMENT_STAT_OVERLAYS.get(aug.api_name)
            if fn is None:
                continue
            overlay = fn(aug)
        for k, v in overlay.items():
            if not v:
                continue
            totals[k] = totals.get(k, 0.0) + float(v)
    return totals


def list_augments_by_rarity(snapshot: "DataSnapshot", rarity: int) -> list[Augment]:
    return [
        Augment.from_record(rec)
        for rec in snapshot.arena_augments_by_id.values()
        if rec.get("rarity") == rarity
    ]
