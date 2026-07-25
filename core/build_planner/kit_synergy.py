"""core.build_planner.kit_synergy - champion-kit vs item synergy scoring (WP-C1).

Scores how well an item fits a champion's kit:

    synergy_score(item, champ) = dot(item_vector(item), kit_weights(champ))
                                 + effect_synergy(item, champ)
                                 - anti_synergy_penalty(item, champ)

item_vector projects an item onto a canonical 10-axis offense space
(AD / bonusAD / AP / AS / crit / on-hit / AH / HP-scaling / %maxHP / true).
kit_weights projects a champion's kit onto the SAME axes as per-axis
multipliers, so the dot product is a stat-linear fit score. Four hard gates
(double-crit, AS-cap, spellblade cadence, %maxHP-on-hit) plus an anti-synergy
penalty (crit on a 0-crit champ, AH overstack, lifesteal on a no-auto champ)
correct the stat-linear baseline for non-linear kit interactions.

Data is loaded by MIRRORING core/archetype_picks.py:174-220 - the active patch
from data/daemon_slayer/current.txt, then that patch's items.json. We NEVER
import the DS engine (agents/daemon_slayer/*) - the in-process split-brain guard
(dashboard/routes_state.py:548-549) forbids it. DS effect files were read
REFERENCE-ONLY to pick the curated item-id tables below; nothing is imported.

The kit_weights BASE is PER-CHAMPION: core.build_planner.champ_kit_data derives a
distinct weight vector for each of the 173 champions from champions.json ground
truth (damage_distribution + roles/tags + attackrange + attackspeedperlevel +
healing/shielding), so the scorer discriminates every champion - not just an
archetype. The flat _ARCHETYPE_WEIGHTS vector below is now only the FALLBACK for a
blank / unknown champ; the ~6 _KIT_TRAITS overrides still fine-tune the curated
champs on top of the derived base.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from core.archetype_picks import get_archetype_for, kit_damage_axis
from core.build_planner.champ_kit_data import derive_kit_weights

_log = logging.getLogger("rc.build_planner.kit_synergy")

_DS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "daemon_slayer"

# --------------------------------------------------------------------------- #
# Canonical axis set - order is load-bearing for dot().
# --------------------------------------------------------------------------- #
AXES: tuple[str, ...] = (
    "AD", "bonusAD", "AP", "AS", "crit",
    "on-hit", "AH", "HP-scaling", "%maxHP", "true",
)

# --------------------------------------------------------------------------- #
# items.json stat field -> axis, with a normalization divisor so the axes are
# commensurate (~0..1.5 scale). Verified present in 16.13.1 items.json.
# --------------------------------------------------------------------------- #
_STAT_AXIS_DIVISOR: dict[str, tuple[str, float]] = {
    "FlatPhysicalDamageMod": ("AD", 70.0),
    "FlatMagicDamageMod": ("AP", 100.0),
    "PercentAttackSpeedMod": ("AS", 0.40),
    "FlatCritChanceMod": ("crit", 0.25),
    "FlatHPPoolMod": ("HP-scaling", 400.0),
}

# --------------------------------------------------------------------------- #
# Curated effect-flag id tables (canonical SHORT ids from the live items.json
# data map - NOT the 22xxxx / 44xxxx duplicate variants). DS effect parsers
# (agents/daemon_slayer/_effects_data.py et al) were read REFERENCE-ONLY to
# choose these ids; nothing is imported from them.
# --------------------------------------------------------------------------- #
# on-hit / AH are tag-driven (verified the tags exist on the cited ids).
# %maxHP / true / bonusAD / spellblade have no clean tag -> curated sets.
_MAXHP_DAMAGE_IDS: frozenset[str] = frozenset({
    "6653",  # Liandry's - %maxHP burn
    "4637",  # Demonic Embrace - %maxHP burn
    "6632",  # Divine Sunderer - %maxHP on spellblade
    "3153",  # BoRK - on-hit %curHP, counted in the %maxHP family
})
_TRUE_DAMAGE_IDS: frozenset[str] = frozenset()  # no mainline 16.13.1 carrier
_BONUS_AD_SCALING_IDS: frozenset[str] = frozenset({
    "3142",  # Youmuu's Ghostblade
    "6692",  # Eclipse
    "3071",  # Black Cleaver
    "3508",  # Essence Reaver
})
_SPELLBLADE_IDS: frozenset[str] = frozenset({
    "3057",  # Sheen
    "3078",  # Trinity Force
    "3508",  # Essence Reaver
    "6632",  # Divine Sunderer
})

# --------------------------------------------------------------------------- #
# Base archetype weight vectors (per-axis multiplier). Keyed by the
# get_archetype_for(champ)["primary"] archetype. Tuned so the named-champ
# orderings in the WP-C1 spec hold with the divisors above.
# --------------------------------------------------------------------------- #
_ARCHETYPE_WEIGHTS: dict[str, dict[str, float]] = {
    "carry":     {"AD": 1.0, "bonusAD": 0.3, "AP": 0.0, "AS": 1.0, "crit": 1.0,
                  "on-hit": 0.6, "AH": 0.1, "HP-scaling": 0.0, "%maxHP": 0.4, "true": 0.6},
    "bruiser":   {"AD": 1.0, "bonusAD": 0.6, "AP": 0.0, "AS": 0.6, "crit": 0.3,
                  "on-hit": 0.6, "AH": 0.5, "HP-scaling": 0.3, "%maxHP": 0.6, "true": 0.5},
    "tank":      {"AD": 0.2, "bonusAD": 0.1, "AP": 0.1, "AS": 0.3, "crit": 0.0,
                  "on-hit": 0.4, "AH": 0.4, "HP-scaling": 1.0, "%maxHP": 0.7, "true": 0.3},
    "mage":      {"AD": 0.0, "bonusAD": 0.0, "AP": 1.0, "AS": 0.2, "crit": 0.0,
                  "on-hit": 0.2, "AH": 0.9, "HP-scaling": 0.0, "%maxHP": 0.5, "true": 0.3},
    "assassin":  {"AD": 1.0, "bonusAD": 0.8, "AP": 0.0, "AS": 0.3, "crit": 0.2,
                  "on-hit": 0.2, "AH": 0.6, "HP-scaling": 0.0, "%maxHP": 0.2, "true": 0.7},
    "enchanter": {"AD": 0.0, "bonusAD": 0.0, "AP": 0.6, "AS": 0.1, "crit": 0.0,
                  "on-hit": 0.1, "AH": 0.9, "HP-scaling": 0.2, "%maxHP": 0.2, "true": 0.1},
}

# --------------------------------------------------------------------------- #
# Per-champ kit-trait overrides, applied AFTER base + axis refinement. Keyed by
# normalized champ key (display name + apostrophe/space-stripped variants). Each
# entry is (weight_overrides, trait_flags). The weight overrides are absolute
# per-axis replacements; missing axes keep the post-axis value.
# --------------------------------------------------------------------------- #
_KIT_TRAITS: dict[str, tuple[dict[str, float], dict[str, object]]] = {
    "Miss Fortune": (
        {"AD": 1.0, "AS": 1.0, "crit": 1.1, "on-hit": 0.5, "AH": 0.05,
         "%maxHP": 0.3, "true": 0.6},
        {"crit_scaling": True, "no_autos": False},
    ),
    "Yasuo": (
        {"AD": 1.0, "AS": 0.9, "crit": 1.0, "on-hit": 0.4, "AH": 0.2},
        {"double_crit": True, "crit_scaling": True},
    ),
    "Yone": (
        {"AD": 1.0, "AS": 0.9, "crit": 1.0, "on-hit": 0.4, "AH": 0.2},
        {"double_crit": True, "crit_scaling": True},
    ),
    "Kog'Maw": (
        {"AS": 1.8, "on-hit": 1.0, "%maxHP": 0.8, "AP": 0.5, "crit": 0.3,
         "AD": 0.6},
        {"as_cap": True, "crit_scaling": True},
    ),
    "Ornn": (
        {"HP-scaling": 1.4, "%maxHP": 0.8, "AD": 0.3, "AP": 0.5, "crit": 0.0,
         "AH": 0.4},
        {"hp_offense": True, "crit_scaling": False},
    ),
    "Sion": (
        {"HP-scaling": 1.5, "%maxHP": 0.7, "AD": 0.4, "crit": 0.0, "AH": 0.3},
        {"hp_offense": True, "crit_scaling": False},
    ),
}

# Gate / penalty / bonus constants.
_AS_CAP = 2.5
_SPELLBLADE_CADENCE_BONUS = 0.8
_SPELLBLADE_NONUSER_BONUS = 0.2
_MAXHP_ONHIT_BONUS = 0.7
_BONUS_AD_MATCH_BONUS = 0.4
_TRUE_MATCH_BONUS = 0.3
_CRIT_ON_ZERO_PENALTY = 2.5
_AH_NOSCALE_PENALTY = 0.5
_AH_OVERSTACK_PENALTY = 0.8
_AH_SOFT_CAP = 60.0
_LIFESTEAL_NOAUTO_PENALTY = 3.0
# Sheen-line spellblade proc on a non-spellblade-user (the carry-coherence
# artifact). Penalty-units, in-family with the crit-on-0 / lifesteal-noauto docks.
_SPELLBLADE_NONUSER_PENALTY = 2.0
_HIGH_AS_WEIGHT = 0.6  # threshold above which a champ is "high-AS"

# --------------------------------------------------------------------------- #
# Item data loader - mirrors core/archetype_picks.py:174-220.
# --------------------------------------------------------------------------- #
_ITEM_CACHE: Optional[dict[str, dict]] = None
_ITEM_LOCK = threading.Lock()


def _resolve_ds_patch() -> Optional[str]:
    """Active DS patch from data/daemon_slayer/current.txt (or None)."""
    try:
        txt = (_DS_DIR / "current.txt").read_text(encoding="utf-8").strip()
        return txt or None
    except Exception:  # noqa: BLE001 - missing file -> no item data
        return None


def _load_items() -> dict[str, dict]:
    """Load the active patch's items.json 'data' map, keyed by str(id).

    Fail-soft to {} on any read/parse error, same as archetype_picks.
    """
    global _ITEM_CACHE
    with _ITEM_LOCK:
        if _ITEM_CACHE is not None:
            return _ITEM_CACHE
        out: dict[str, dict] = {}
        patch = _resolve_ds_patch()
        if patch:
            path = _DS_DIR / patch / "items.json"
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                data = raw.get("data", raw)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            out[str(k)] = v
            except FileNotFoundError:
                _log.warning("kit_synergy: %s missing - no item data", path)
            except Exception as exc:  # noqa: BLE001 - fail-soft to {}
                _log.warning("kit_synergy: item load failed: %s", exc)
        _ITEM_CACHE = out
        return out


def _invalidate_item_cache() -> None:
    """Drop the item cache so the next read re-pulls (patch refresh / tests)."""
    global _ITEM_CACHE
    with _ITEM_LOCK:
        _ITEM_CACHE = None


# --------------------------------------------------------------------------- #
# Resolution helpers.
# --------------------------------------------------------------------------- #
def _resolve_item(item) -> dict:
    """Return the items.json entry dict for ``item``.

    ``item`` may be an id (str/int) looked up by str(id), or an entry dict
    already in hand (a DS preview row) - used as-is. Unknown id -> {}.
    """
    if isinstance(item, dict):
        return item
    return _load_items().get(str(item), {})


def _item_id(item) -> Optional[str]:
    """Best-effort canonical id string for ``item`` (None if not derivable)."""
    if isinstance(item, dict):
        for k in ("id", "itemId", "item_id"):
            v = item.get(k)
            if v is not None:
                return str(v)
        return None
    return str(item)


# Mode-mirror id widths, DERIVED from the live 706-item catalog (16.14.1) rather
# than assumed. Measured facts behind the normalizer below:
#   * every catalog id is a pure numeric of width 4 (429 ids) or 6 (277 ids);
#   * NO id is a suffix of another id of the SAME width, so width alone decides;
#   * every suffix relation in the catalog (200 pairs) is exactly a 2-digit
#     prefix on a 4-digit canonical id - observed prefixes 12 / 22 / 32 / 44 /
#     55 / 66 / 99, of which 22 (175 ids, 143 on map 30) is the Arena mirror.
# So "6 digits -> take the last 4" is unambiguous and collision-free over the
# real catalog. A naive endswith() would NOT be: it would also fold long ids into
# short ones in the wrong direction. tests/test_kit_synergy_mirror_ids.py asserts
# every one of these structural facts against the live items.json, so a Riot
# id-space change fails loudly instead of silently re-opening the gap.
_MIRROR_ID_WIDTH = 6
_CANONICAL_ID_WIDTH = 4


def canonical_item_id(item_id) -> Optional[str]:
    """Return the CANONICAL (Summoner's Rift) id string for ``item_id``.

    A mode-mirror id (Arena / map 30 ``22xxxx``, and the sibling 12 / 32 / 44 /
    55 / 66 / 99 families) is a 2-digit prefix on the canonical 4-digit id, so the
    canonical form is the trailing 4 digits. Anything that is not a 6-digit pure
    numeric is returned unchanged, which makes the function the IDENTITY on the
    whole 4-digit keyspace - it can never merge two canonical items.

    Used ONLY to normalize membership tests against this module's curated
    SR-literal id tables. It deliberately does NOT redirect the items.json stat
    lookup: an Arena mirror credits its OWN DDragon stat line (R161 doctrine B).
    """
    if item_id is None:
        return None
    sid = str(item_id)
    if len(sid) == _MIRROR_ID_WIDTH and sid.isdigit():
        return sid[_MIRROR_ID_WIDTH - _CANONICAL_ID_WIDTH:]
    return sid


# --------------------------------------------------------------------------- #
# item_vector + item_effect_flags
# --------------------------------------------------------------------------- #
def item_effect_flags(item) -> frozenset[str]:
    """Return the set of passive effect flags for ``item``.

    Flags: on-hit, AH (tag-driven), %maxHP, true, bonusAD, spellblade (curated).
    """
    entry = _resolve_item(item)
    flags: set[str] = set()
    tags = entry.get("tags") or []
    if "OnHit" in tags:
        flags.add("on-hit")
    if "AbilityHaste" in tags:
        flags.add("AH")
    # Every curated table below holds CANONICAL 4-digit SR ids, so the incoming id
    # is normalized by SUFFIX first - otherwise a mode-mirror id (Arena 22xxxx and
    # the 12 / 32 / 44 / 55 / 66 / 99 families) misses every membership test and
    # silently loses its curated flags. That gap made the carry coherence dock
    # INERT IN ARENA: item_effect_flags("223508") returned only the tag-driven
    # {AH, on-hit} while item_effect_flags("3508") returned the full
    # {AH, bonusAD, on-hit, spellblade}, so anti_synergy_penalty / stat_fit never
    # docked Essence Reaver's Arena mirror and it held slot 1 for Caitlyn / Jinx /
    # Twitch in build_orders_arena.json. Suffix normalization (not name matching)
    # is the repo rule - memory feedback_deny_sweep_by_id_suffix_not_name; 5 of the
    # 175 Arena pairs carry a renamed or blank mirror name, so a name join drops
    # them. The tag-driven flags above still read the MIRROR's own entry.
    iid = canonical_item_id(_item_id(item))
    if iid is not None:
        if iid in _MAXHP_DAMAGE_IDS:
            flags.add("%maxHP")
        if iid in _TRUE_DAMAGE_IDS:
            flags.add("true")
        if iid in _BONUS_AD_SCALING_IDS:
            flags.add("bonusAD")
        if iid in _SPELLBLADE_IDS:
            flags.add("spellblade")
    return frozenset(flags)


def item_vector(item) -> dict[str, float]:
    """Project ``item`` onto the canonical 10-axis offense space.

    Returns a dense dict keyed by every name in AXES (missing axes -> 0.0).
    Stat axes come from normalized items.json stats; passive axes (on-hit / AH /
    %maxHP / true / bonusAD) each contribute a fixed unit magnitude (1.0) when
    the corresponding effect flag is present. Lifesteal is stashed on the entry
    as ``_lifesteal`` (not a vector axis - consumed by the anti-synergy only).
    """
    entry = _resolve_item(item)
    vec: dict[str, float] = {axis: 0.0 for axis in AXES}
    stats = entry.get("stats") or {}
    for field, (axis, divisor) in _STAT_AXIS_DIVISOR.items():
        try:
            raw = float(stats.get(field) or 0.0)
        except (TypeError, ValueError):
            raw = 0.0
        if raw:
            vec[axis] += raw / divisor

    flags = item_effect_flags(item)
    for flag in ("on-hit", "AH", "%maxHP", "true", "bonusAD"):
        if flag in flags:
            vec[flag] += 1.0

    return vec


def _item_lifesteal(item) -> float:
    """Lifesteal fraction (PercentLifeStealMod) - 0.0 when absent."""
    entry = _resolve_item(item)
    stats = entry.get("stats") or {}
    try:
        return float(stats.get("PercentLifeStealMod") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# champ resolution + kit traits
# --------------------------------------------------------------------------- #
def _champ_key_variants(champ: str):
    """Yield the stripped-key variants archetype_picks uses for a champ name."""
    if not champ:
        return
    yield champ
    yield champ.replace("'", "")
    yield champ.replace(" ", "")
    yield champ.replace("'", "").replace(" ", "")


def _lookup_kit_traits(champ: str):
    """Return the (overrides, flags) _KIT_TRAITS entry for ``champ`` or None."""
    # Direct match on display name first.
    if champ in _KIT_TRAITS:
        return _KIT_TRAITS[champ]
    # Build a normalized lookup once (cheap - 6 entries).
    norm = {}
    for name, payload in _KIT_TRAITS.items():
        for v in _champ_key_variants(name):
            norm[v] = payload
    for v in _champ_key_variants(champ):
        if v in norm:
            return norm[v]
    return None


def champ_kit_traits(champ) -> dict:
    """Return the kit-trait dict for ``champ``.

    Shape: {archetype, damage_axis, crit_scaling, hp_offense, spellblade_user,
    no_autos, double_crit, as_cap}.
    """
    name = str(champ) if champ is not None else ""
    arch = (get_archetype_for(name) or {}).get("primary", "carry")
    axis = kit_damage_axis(name)
    flags = {
        "archetype": arch,
        "damage_axis": axis,
        "crit_scaling": False,
        "hp_offense": False,
        "spellblade_user": False,
        "no_autos": False,
        "double_crit": False,
        "as_cap": False,
    }
    override = _lookup_kit_traits(name)
    if override is not None:
        _, ov_flags = override
        for k, v in ov_flags.items():
            flags[k] = v
    # Default crit_scaling heuristic when not explicitly overridden: an AD carry
    # / assassin kit scales with crit; everything else does not.
    if override is None or "crit_scaling" not in override[1]:
        flags["crit_scaling"] = arch in {"carry", "assassin"} and axis != "ap"
    # spellblade_user heuristic (cadence-driven ability spammers). An explicit
    # override may set it; otherwise the archetype + AH heuristic decides.
    if not flags["spellblade_user"]:
        ah_w = _base_axis_weights(name).get("AH", 0.0)
        flags["spellblade_user"] = (
            arch in {"bruiser", "assassin", "mage"}
            or (axis is not None and ah_w >= 0.4)
        )
    return flags


# --------------------------------------------------------------------------- #
# kit_weights
# --------------------------------------------------------------------------- #
def _base_axis_weights(champ: str) -> dict[str, float]:
    """Per-champion base weight vector (pre-override).

    Prefers the PER-CHAMPION derived vector (champ_kit_data.derive_kit_weights,
    from champions.json ground truth) so each of the 173 champions gets a
    distinct base - the WP-C1 model only distinguished ~6 curated champs and fell
    back to a flat per-archetype vector for the rest. Falls back to that flat
    archetype vector + AD/AP axis refinement only when the champ is blank or
    absent from champions.json (the derivation returns None). Separated so the
    spellblade-user heuristic can read the AH weight without recursing through
    the per-champ override.
    """
    derived = derive_kit_weights(champ)
    if derived is not None:
        # The derivation already encodes the damage axis (via the champ's
        # damage_distribution), so no extra AD/AP refinement is applied here.
        return dict(derived)
    arch = (get_archetype_for(champ) or {}).get("primary", "carry")
    base = dict(_ARCHETYPE_WEIGHTS.get(arch, _ARCHETYPE_WEIGHTS["carry"]))
    axis = kit_damage_axis(champ)
    if axis == "ap":
        base["AD"] = 0.0
        base["bonusAD"] = 0.0
        base["crit"] = 0.0
        base["AP"] = max(base["AP"], 0.9)
    elif axis == "ad":
        base["AP"] = 0.0
    return base


def kit_weights(champ, *, current_as: Optional[float] = None) -> dict[str, float]:
    """Return the dense per-axis weight vector for ``champ``.

    Order: base archetype vector -> AD/AP axis refinement -> per-champ override
    -> hard gates (double-crit, AS-cap). current_as feeds the AS-cap gate.
    """
    name = str(champ) if champ is not None else ""
    weights = _base_axis_weights(name)

    override = _lookup_kit_traits(name)
    if override is not None:
        ov_weights, _ = override
        for axis, val in ov_weights.items():
            weights[axis] = val

    # Ensure dense + clamp >= 0 (AH ~0.05 stays positive-tiny).
    weights = {axis: max(0.0, float(weights.get(axis, 0.0))) for axis in AXES}

    traits = champ_kit_traits(name)
    # Gate 1: double-crit - Yasuo / Yone value crit ~2x.
    if traits.get("double_crit"):
        weights["crit"] = weights["crit"] * 2.0
    # Gate 2: AS-cap - marginal AS worthless past the 2.5 attack-speed cap.
    if traits.get("as_cap") and current_as is not None and current_as >= _AS_CAP:
        weights["AS"] = 0.0

    return weights


# --------------------------------------------------------------------------- #
# effect_synergy + anti_synergy_penalty
# --------------------------------------------------------------------------- #
def effect_synergy(item, champ) -> float:
    """Non-linear, cadence-driven synergy bonuses (gates 3 + 4 plus matches)."""
    flags = item_effect_flags(item)
    traits = champ_kit_traits(champ)
    weights = kit_weights(champ)
    arch = traits.get("archetype")
    axis = traits.get("damage_axis")
    total = 0.0

    # Gate 3: spellblade cadence (NOT stat-linear).
    if "spellblade" in flags:
        total += (_SPELLBLADE_CADENCE_BONUS if traits.get("spellblade_user")
                  else _SPELLBLADE_NONUSER_BONUS)

    high_as = weights.get("AS", 0.0) >= _HIGH_AS_WEIGHT
    # Gate 4: %maxHP-on-hit scales multiplicatively with attack speed.
    if "%maxHP" in flags and "on-hit" in flags and high_as:
        total += _MAXHP_ONHIT_BONUS

    # bonusAD-scaling match.
    if ("bonusAD" in flags and axis == "ad"
            and arch in {"assassin", "bruiser", "carry"}):
        total += _BONUS_AD_MATCH_BONUS

    # true-damage match.
    if "true" in flags and arch in {"carry", "assassin", "bruiser"}:
        total += _TRUE_MATCH_BONUS

    return total


def anti_synergy_penalty(item, champ, has_autos: Optional[bool] = None,
                         *, owned_ah: float = 0.0) -> float:
    """Sum of anti-synergy penalties (all subtracted in synergy_score)."""
    vec = item_vector(item)
    flags = item_effect_flags(item)
    traits = champ_kit_traits(champ)
    weights = kit_weights(champ)
    total = 0.0

    # crit on a 0-crit-scaling champ.
    if vec["crit"] > 0 and not traits.get("crit_scaling"):
        total += _CRIT_ON_ZERO_PENALTY * vec["crit"]

    # AH overstack / no-AH-scaling waste.
    if "AH" in flags:
        if weights.get("AH", 0.0) <= 0.1:
            total += _AH_NOSCALE_PENALTY
        if owned_ah >= _AH_SOFT_CAP:
            total += _AH_OVERSTACK_PENALTY

    # lifesteal on a no-auto / ability-only champ.
    lifesteal = _item_lifesteal(item)
    if lifesteal > 0:
        no_autos = traits.get("no_autos") or (has_autos is False)
        if no_autos:
            total += _LIFESTEAL_NOAUTO_PENALTY * lifesteal

    # Spellblade proc on a non-spellblade-user (the carry-coherence artifact).
    # An ability-charged Sheen-line item (Essence Reaver / Trinity / Divine
    # Sunderer / Sheen) has its proc DPS modeled on an ability-cast tempo a pure
    # auto-attacker (crit / on-hit marksman) never sustains, so the engine
    # over-credits its delta_dps. Dock the pairing so the coherence re-rank sinks
    # it below the flag-less crit core (Infinity Edge). A genuine spellblade user
    # (spellblade_user True - bruisers, Yasuo, casters) is NOT penalized.
    if "spellblade" in flags and not traits.get("spellblade_user"):
        total += _SPELLBLADE_NONUSER_PENALTY

    return total


# --------------------------------------------------------------------------- #
# stat_fit - champ-aware stat-linear fit (the coherence re-rank lever)
# --------------------------------------------------------------------------- #
def stat_fit(item, champ, *, current_as: Optional[float] = None) -> float:
    """Champ-aware ``dot(item_vector, kit_weights)`` with the spellblade per-auto
    credit corrected - the metric lever the carry coherence re-rank consumes.

    An ability-charged Spellblade item (``_SPELLBLADE_IDS``) does NOT deliver its
    per-auto on-hit / bonusAD value to a kit that does not use spellblade procs
    (``champ_kit_traits(champ)["spellblade_user"]`` is False) - a pure crit / auto
    marksman never charges the Sheen proc on the ability-cast tempo the DPS model
    assumes, so those two flag axes are artifact credit. They are dropped from the
    projected vector for that pairing ONLY; the flat stat axes (AD / crit / AS /
    AP / HP) are untouched, as is a genuine spellblade user (Yasuo, bruisers).

    This is the load-bearing correction that stops Essence Reaver (3508) and
    Eclipse (6692) out-fitting Infinity Edge (3031) for a crit ADC. It does NOT
    mutate the champ-agnostic ``item_vector`` (a private copy is projected), so
    ``synergy_score`` + every existing caller stay byte-identical.
    """
    vec = dict(item_vector(item))
    flags = item_effect_flags(item)
    if "spellblade" in flags and not champ_kit_traits(champ).get("spellblade_user"):
        vec["on-hit"] = 0.0
        vec["bonusAD"] = 0.0
    weights = kit_weights(champ, current_as=current_as)
    return sum(vec[axis] * weights[axis] for axis in AXES)


# --------------------------------------------------------------------------- #
# synergy_score
# --------------------------------------------------------------------------- #
def synergy_score(item, champ, *, current_as: Optional[float] = None,
                  has_autos: Optional[bool] = None) -> float:
    """Total kit-fit score for ``item`` on ``champ``.

    dot(item_vector, kit_weights) + effect_synergy - anti_synergy_penalty.
    """
    vec = item_vector(item)
    weights = kit_weights(champ, current_as=current_as)
    dot = sum(vec[axis] * weights[axis] for axis in AXES)
    return dot + effect_synergy(item, champ) - anti_synergy_penalty(
        item, champ, has_autos=has_autos)
