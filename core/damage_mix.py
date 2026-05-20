"""Damage-source mix aggregator (UX-2 backend, 2026-05-20).

Re-composes DS engine public outputs to deliver a per-channel
damage-distribution donut for the Active Match panel. Players consistently
misjudge whether an enemy's damage has flipped after Sheen/Riftmaker/Wit's
End - this surface answers "what kind of damage are they actually doing
right now, with their current items" rather than "what does the champion's
kit print at level 1".

Pure re-composition over public DS calls:

  - ``compute_dps(snapshot, champ, level, items)``     -> AA channel + on-hit
  - ``compute_ability_dps(snapshot, champ, level, ...)`` -> 4 spells by type

The returned ratios sum to 1.0 (within float epsilon) when ``total_dps > 0``.
On a zero-damage build (level 1 no items, or champ snapshot missing) the
mix is reported as all-zero and ``total_dps == 0.0`` - callers should
treat that as "no signal yet" rather than a 25/25/25/25 prior.

Engine math is NOT touched. The four channels are:

  - ``physical`` : AA base + per-spell ``damage_type == "PHYSICAL"``
  - ``magical``  : per-spell ``damage_type == "MAGIC"``
  - ``true``     : per-spell ``damage_type == "TRUE"``
  - ``on_hit``   : amortized per-attack item proc damage
                   (``per_attack_on_hit_damage * AS``) - this is the
                   "your AA's are now half magic" channel that the
                   donut wants to surface separately so the player can
                   see Wit's End / BotRK / Statikk-style flips.

Cache: 60s TTL in-memory keyed by ``(champ_id_str, items_csv_str,
level, mode)``. The dashboard polls ``/api/state`` every 2s so a cached
hit on identical inputs is the common path.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

# Cache TTL. 60s mirrors the 2s dashboard poll cadence comfortably; the
# 4-tuple key includes level + mode so a champ level-up or mode change
# invalidates correctly.
CACHE_TTL_S = 60.0
MAX_ITEMS = 6  # six inventory slots in League (boots count)


CHANNELS: tuple[str, ...] = ("physical", "magical", "true", "on_hit")


@dataclass(frozen=True)
class DamageMix:
    """Per-channel DPS contributions + ratios."""
    champ_id: str           # snapshot id string (e.g. "Garen")
    champ_key: int          # numeric Riot key (e.g. 86)
    items: tuple[str, ...]
    level: int
    mode: str
    physical_dps: float
    magical_dps: float
    true_dps: float
    on_hit_dps: float
    total_dps: float
    mix: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "champ_id": self.champ_id,
            "champ_key": self.champ_key,
            "items": list(self.items),
            "level": self.level,
            "mode": self.mode,
            "physical_dps": round(self.physical_dps, 3),
            "magical_dps": round(self.magical_dps, 3),
            "true_dps": round(self.true_dps, 3),
            "on_hit_dps": round(self.on_hit_dps, 3),
            "total_dps": round(self.total_dps, 3),
            "mix": {k: round(v, 6) for k, v in self.mix.items()},
        }


# ---------------------------------------------------------------------
# Champion id mapping (numeric key <-> string id)
# ---------------------------------------------------------------------

_KEY_TO_ID_CACHE: dict[int, dict[int, str]] = {}
_KEY_CACHE_LOCK = threading.Lock()


def _key_to_id_map(snapshot: DataSnapshot) -> dict[int, str]:
    """Build (and cache) the {numeric_key: string_id} map for a snapshot.

    Cached per snapshot-patch so the same snapshot object isn't re-iterated
    on every request. The cache key is ``id(snapshot)`` which is stable
    for the singleton snapshot the dashboard holds.
    """
    snap_id = id(snapshot)
    with _KEY_CACHE_LOCK:
        cached = _KEY_TO_ID_CACHE.get(snap_id)
        if cached is not None:
            return cached
        mapping = {}
        for cid, c in snapshot.champions.items():
            try:
                mapping[int(c["key"])] = cid
            except (KeyError, ValueError, TypeError):
                continue
        _KEY_TO_ID_CACHE[snap_id] = mapping
        return mapping


def resolve_champ_id(snapshot: DataSnapshot, champ_id_or_key: str | int) -> str:
    """Resolve a numeric Riot key OR a string id to the snapshot's string id.

    Raises ``ValueError`` if the input is neither a valid numeric key nor
    a string present in the snapshot. The error message names the
    snapshot patch so debugging a stale dashboard payload is one glance.
    """
    s = str(champ_id_or_key).strip()
    if not s:
        raise ValueError("empty champ_id")
    # Try numeric key first - that's what the dashboard payload uses.
    if s.isdigit():
        key = int(s)
        m = _key_to_id_map(snapshot)
        cid = m.get(key)
        if cid is None:
            raise ValueError(
                f"unknown champ key {key} in snapshot {snapshot.patch}"
            )
        return cid
    # Fall through: maybe it's already a string id ("Garen").
    if s in snapshot.champions:
        return s
    raise ValueError(
        f"unknown champ id {s!r} in snapshot {snapshot.patch}"
    )


# ---------------------------------------------------------------------
# Item id normalization
# ---------------------------------------------------------------------

def normalize_items(snapshot: DataSnapshot, raw: Iterable[str | int]) -> tuple[str, ...]:
    """Strip blanks, coerce to str, validate against snapshot.items.

    Returns a tuple (so it's hashable for the cache key). Raises
    ``ValueError`` on any item id not in the snapshot. Order preserved -
    the engine's collect_effects dedups via unique_passive_key so
    duplicate item ids are fine.
    """
    out: list[str] = []
    for raw_id in raw:
        s = str(raw_id).strip()
        if not s:
            continue
        if s not in snapshot.items:
            raise ValueError(
                f"unknown item id {s!r} in snapshot {snapshot.patch}"
            )
        out.append(s)
    if len(out) > MAX_ITEMS:
        raise ValueError(
            f"too many items: {len(out)} > {MAX_ITEMS}"
        )
    return tuple(out)


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------

@dataclass
class _CacheEntry:
    expires_at: float
    mix: DamageMix


_MIX_CACHE: dict[tuple, _CacheEntry] = {}
_MIX_LOCK = threading.Lock()


def _cache_key(
    champ_id: str, items: tuple[str, ...], level: int, mode: str,
) -> tuple:
    return (champ_id, ",".join(items), int(level), mode)


def clear_cache() -> None:
    """Wipe the cache - tests use this to isolate cache hit/miss runs."""
    with _MIX_LOCK:
        _MIX_CACHE.clear()


def _cache_get(key: tuple) -> Optional[DamageMix]:
    now = time.monotonic()
    with _MIX_LOCK:
        entry = _MIX_CACHE.get(key)
        if entry is None:
            return None
        if entry.expires_at < now:
            # Expired - drop it now so the cache doesn't grow unbounded.
            _MIX_CACHE.pop(key, None)
            return None
        return entry.mix


def _cache_put(key: tuple, mix: DamageMix) -> None:
    with _MIX_LOCK:
        _MIX_CACHE[key] = _CacheEntry(
            expires_at=time.monotonic() + CACHE_TTL_S, mix=mix,
        )


# ---------------------------------------------------------------------
# Core aggregator
# ---------------------------------------------------------------------

def _normalize_damage_type(dt: Optional[str]) -> str:
    """DS engine uses 'PHYSICAL' / 'MAGIC' / 'TRUE' in AbilitySpellDps; the
    legacy effects.py module uses lowercase 'physical' / 'magical' / 'true'
    for procs. Funnel both into the 4 channel names we expose.
    """
    if not dt:
        return ""
    d = dt.strip().upper()
    if d == "PHYSICAL":
        return "physical"
    if d == "MAGIC" or d == "MAGICAL":
        return "magical"
    if d == "TRUE":
        return "true"
    return ""


def compute_damage_mix(
    snapshot: DataSnapshot,
    champ_id_or_key: str | int,
    items: Iterable[str | int],
    level: int = 11,
    mode: str = "SR",
    target_armor: float = 70.0,
    target_mr: float = 40.0,
    *,
    use_cache: bool = True,
) -> tuple[DamageMix, bool]:
    """Compute the 4-channel damage mix for ``(champ, items)``.

    Returns ``(mix, was_cached)``. The ``was_cached`` bool tells the
    route handler whether to set ``cached=True`` in the response.

    Default target_armor/target_mr are mid-game neutrals (70 / 40);
    callers wanting the bare champion DPS unmitigated should pass 0/0.
    Both are baked into the cache key indirectly because the mix is
    deterministic per (champ, items, level, mode) given fixed targets -
    we currently fix the targets to the neutrals above; if a future
    caller wants per-target mixes, plumb target_armor/target_mr into
    the cache key.
    """
    if level < 1 or level > 18:
        raise ValueError(f"level must be in [1, 18], got {level}")
    cid = resolve_champ_id(snapshot, champ_id_or_key)
    item_tuple = normalize_items(snapshot, items)
    key = _cache_key(cid, item_tuple, level, mode)
    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return hit, True

    # Compute per-spell ability DPS - returns one entry per Q/W/E/R with
    # the damage_type and DPS already amortized over CD + mana uptime.
    abil = compute_ability_dps(
        snapshot, cid, level,
        item_ids=item_tuple, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
    )

    # Compute auto-attack DPS - base AA is physical by definition; the
    # on-hit channel splits out item-proc-per-attack contributions so
    # the donut can show "your AA's are now half magic" without the
    # player having to read the item names.
    aa = compute_dps(
        snapshot, cid, level,
        item_ids=item_tuple, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
    )

    # ---- bucket ability DPS by damage_type ----
    physical_ability = 0.0
    magical_ability = 0.0
    true_ability = 0.0
    for sp in abil.per_spell:
        ch = _normalize_damage_type(sp.damage_type)
        if ch == "physical":
            physical_ability += sp.dps
        elif ch == "magical":
            magical_ability += sp.dps
        elif ch == "true":
            true_ability += sp.dps
        # Unknown / None -> dropped silently; W is often None for
        # passive shields.

    # ---- AA base channel ----
    # weighted_dps is the rotation-weighted auto-attack DPS including
    # per-rotation periodic procs (Wit's End magical, Stormrazor, etc).
    # We want just the BASE AA portion in the physical bucket and the
    # per-attack on-hit procs in the on_hit bucket. The base portion is
    # raw_attack_dps * armor_factor * mode_mult - but compute_dps already
    # rolled that into weighted_dps via _rotation_attack_dps. Cleanest:
    # treat weighted_dps as "AA + cadence-procs"; on_hit_dps amortizes
    # the per-attack proc damage over AS so we can subtract that to
    # leave physical-only AA. The remainder counts as physical (any
    # leftover from time-based procs we keep in the physical bucket as
    # a conservative under-estimate of the magical/on-hit split for
    # time-based procs - acceptable for v1; magical periodic procs are
    # captured below explicitly when we extend).
    eff_as = float(aa.stats.get("as", 0.0))
    on_hit_dps = max(0.0, aa.per_attack_on_hit_damage * eff_as)
    base_aa_dps = max(0.0, aa.weighted_dps - on_hit_dps)

    physical_dps = physical_ability + base_aa_dps
    magical_dps = magical_ability
    true_dps = true_ability

    total = physical_dps + magical_dps + true_dps + on_hit_dps
    if total > 0:
        mix = {
            "physical": physical_dps / total,
            "magical": magical_dps / total,
            "true": true_dps / total,
            "on_hit": on_hit_dps / total,
        }
    else:
        mix = {c: 0.0 for c in CHANNELS}

    # numeric key for the donut UI - already validated upstream.
    key_to_id = _key_to_id_map(snapshot)
    id_to_key = {v: k for k, v in key_to_id.items()}
    champ_key = id_to_key.get(cid, 0)

    result = DamageMix(
        champ_id=cid,
        champ_key=champ_key,
        items=item_tuple,
        level=int(level),
        mode=mode,
        physical_dps=physical_dps,
        magical_dps=magical_dps,
        true_dps=true_dps,
        on_hit_dps=on_hit_dps,
        total_dps=total,
        mix=mix,
    )
    if use_cache:
        _cache_put(key, result)
    return result, False
