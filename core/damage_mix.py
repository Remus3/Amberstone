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

Cache: 60s TTL in-memory keyed by ``(id(snapshot), champ_id_str,
items_csv_str, level, mode, target_armor, target_mr)``; each entry carries a
weakref to its snapshot and is served only to that same object, so a
snapshot reload (or an id() recycled after GC) recomputes. At most
``MAX_CACHE_ENTRIES`` live entries; the oldest is evicted first. The
dashboard polls ``/api/state`` every 2s so a cached hit on identical inputs
is the common path. A cached ``DamageMix.mix`` is a read-only mapping, so
one caller cannot poison what the next one is served.

Input contract (S144-T-701): ``level`` is an int (not bool) in [1, 18];
``mode`` a non-empty str; ``target_armor`` / ``target_mr`` finite real
numbers (not bool); ``items`` an iterable of ids, never a bare str / bytes,
and the six-slot cap stops pulling at the seventh id. Anything else raises
``ValueError``. A non-finite or negative engine contribution counts as 0.0,
so every channel is finite and non-negative and the ratios keep their
sum-to-1.0 promise.
"""

from __future__ import annotations

import math
import threading
import time
import weakref
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

# Cache TTL. 60s mirrors the 2s dashboard poll cadence comfortably; the
# 4-tuple key includes level + mode so a champ level-up or mode change
# invalidates correctly.
CACHE_TTL_S = 60.0
MAX_ITEMS = 6  # six inventory slots in League (boots count)
# Live-entry bound: a sweep of distinct (champ, items, level, target) inputs
# inside one TTL window can no longer grow the cache without limit.
MAX_CACHE_ENTRIES = 512


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
    # compute_damage_mix stores a read-only MappingProxyType here, since the
    # same object is handed to every cache hit for up to CACHE_TTL_S.
    mix: Mapping[str, float] = field(default_factory=dict)

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

# Entries are (weakref-to-snapshot, mapping). The weakref guards against
# id() reuse: a freed snapshot's address can be recycled by a NEW snapshot
# object, which would otherwise be served the OLD map silently.
_KEY_TO_ID_CACHE: dict[int, tuple[weakref.ref, dict[int, str]]] = {}
_KEY_CACHE_LOCK = threading.Lock()


def _key_to_id_map(snapshot: DataSnapshot) -> dict[int, str]:
    """Build (and cache) the {numeric_key: string_id} map for a snapshot.

    Cached per snapshot object so the same snapshot isn't re-iterated on
    every request. The cache key is ``id(snapshot)``; each entry carries a
    weakref to the snapshot it was built from and is rebuilt if the id was
    recycled by a different object (id() reuse after GC). Dead entries are
    pruned on insert so a snapshot reload (patch refresh) cannot grow the
    cache unboundedly.
    """
    snap_id = id(snapshot)
    with _KEY_CACHE_LOCK:
        cached = _KEY_TO_ID_CACHE.get(snap_id)
        if cached is not None and cached[0]() is snapshot:
            return cached[1]
        mapping: dict[int, str] = {}
        for cid, c in snapshot.champions.items():
            try:
                mapping[int(c["key"])] = cid
            except (KeyError, ValueError, TypeError):
                continue
        # Prune entries whose snapshot has been garbage-collected.
        dead = [k for k, (ref, _m) in _KEY_TO_ID_CACHE.items() if ref() is None]
        for k in dead:
            _KEY_TO_ID_CACHE.pop(k, None)
        try:
            _KEY_TO_ID_CACHE[snap_id] = (weakref.ref(snapshot), mapping)
        except TypeError:
            # Snapshot type without weakref support (e.g. a slotted test
            # double): skip caching rather than fail - correctness first.
            pass
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
    # ASCII only: str.isdigit() is true for Arabic-Indic / full-width
    # digits (int() then reads them as a key) and for superscripts (int()
    # then raises its own message instead of ours).
    if s.isascii() and s.isdigit():
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
    ``ValueError`` on any item id not in the snapshot, on a bare str /
    bytes (it used to be iterated one character at a time), and on a
    seventh non-blank id - raised as soon as it is pulled, so an unbounded
    iterable is never drained. Order preserved - the engine's
    collect_effects dedups via unique_passive_key so duplicate item ids
    are fine.
    """
    if isinstance(raw, (str, bytes, bytearray)):
        raise ValueError("items must be an iterable of item ids, not a string")
    out: list[str] = []
    for raw_id in raw:
        s = str(raw_id).strip()
        if not s:
            continue
        if len(out) >= MAX_ITEMS:
            raise ValueError(f"too many items: more than {MAX_ITEMS}")
        if s not in snapshot.items:
            raise ValueError(
                f"unknown item id {s!r} in snapshot {snapshot.patch}"
            )
        out.append(s)
    return tuple(out)


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------

@dataclass
class _CacheEntry:
    expires_at: float
    mix: DamageMix
    # Weakref to the snapshot the mix was computed from; None = unbound
    # (served to any snapshot - only hand-built test entries use it).
    snap_ref: Optional[weakref.ref] = None


_MIX_CACHE: dict[tuple, _CacheEntry] = {}
_MIX_LOCK = threading.Lock()


def _cache_key(
    champ_id: str, items: tuple[str, ...], level: int, mode: str,
    snapshot: object = None, target_armor: float = 70.0,
    target_mr: float = 40.0,
) -> tuple:
    # id(snapshot) keeps two live snapshots from sharing a slot; the entry's
    # snap_ref check (in _cache_get) catches an id() recycled after GC.
    # The targets are part of the result, so they are part of the key.
    return (id(snapshot), champ_id, ",".join(items), int(level), mode,
            float(target_armor), float(target_mr))


def clear_cache() -> None:
    """Wipe the cache - tests use this to isolate cache hit/miss runs."""
    with _MIX_LOCK:
        _MIX_CACHE.clear()


def _cache_get(key: tuple, snapshot: object = None) -> Optional[DamageMix]:
    now = time.monotonic()
    with _MIX_LOCK:
        entry = _MIX_CACHE.get(key)
        if entry is None:
            return None
        if entry.expires_at < now or (
            entry.snap_ref is not None and entry.snap_ref() is not snapshot
        ):
            # Expired, or computed from a different (since freed) snapshot
            # whose id() was recycled - drop it so it is never served.
            _MIX_CACHE.pop(key, None)
            return None
        return entry.mix


def _cache_put(key: tuple, mix: DamageMix, snapshot: object = None) -> None:
    now = time.monotonic()
    try:
        snap_ref = weakref.ref(snapshot) if snapshot is not None else None
    except TypeError:
        # Snapshot type without weakref support: do not cache at all, since
        # an unbound entry could be served to a recycled id().
        return
    with _MIX_LOCK:
        # Prune expired entries on insert. _cache_get only evicts the key
        # it is asked for, so keys that are never re-read (old item builds,
        # old levels) would otherwise accumulate for the process lifetime.
        stale = [k for k, e in _MIX_CACHE.items() if e.expires_at < now]
        for k in stale:
            _MIX_CACHE.pop(k, None)
        # Re-insert at the tail so dict order stays oldest-first, then
        # evict from the head down to the bound.
        _MIX_CACHE.pop(key, None)
        while len(_MIX_CACHE) >= MAX_CACHE_ENTRIES:
            _MIX_CACHE.pop(next(iter(_MIX_CACHE)))
        _MIX_CACHE[key] = _CacheEntry(
            expires_at=now + CACHE_TTL_S, mix=mix, snap_ref=snap_ref)


# ---------------------------------------------------------------------
# Core aggregator
# ---------------------------------------------------------------------

def _normalize_damage_type(dt: Optional[str]) -> str:
    """DS engine uses 'PHYSICAL' / 'MAGIC' / 'TRUE' in AbilitySpellDps; the
    legacy effects.py module uses lowercase 'physical' / 'magical' / 'true'
    for procs. Funnel both into the 4 channel names we expose.
    """
    if not dt or not isinstance(dt, str):
        # A non-str tag (engine drift) is unknown, never an AttributeError.
        return ""
    d = dt.strip().upper()
    if d == "PHYSICAL":
        return "physical"
    if d in ("MAGIC", "MAGICAL"):
        return "magical"
    if d == "TRUE":
        return "true"
    return ""


def _finite_target(name: str, value: object) -> float:
    """A target resist as a finite float; ValueError otherwise.

    bool and str are refused rather than coerced: True would read as 1
    armor and "70" would reach the engine as a string. A NaN would also
    make the cache key unequal to itself, so every call missed and added
    one entry.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a real number, got {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return out


def _finite_nonneg(value: object) -> float:
    """An engine DPS / attack-speed number, or 0.0 if it is not a finite
    non-negative real (NaN, inf, negative, None, non-numeric)."""
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(out) or out < 0.0:
        return 0.0
    return out


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
    Both targets are part of the cache key (S144-T-701: they used to be
    left out, so a 0/0 call after a default call was served the 70/40
    mix flagged cached=True), and so is the snapshot object.
    """
    # bool is an int subclass (True read as level 1); a float was computed
    # at its own value but cached under int(level). Both are refused.
    if (not isinstance(level, int) or isinstance(level, bool)
            or level < 1 or level > 18):
        raise ValueError(f"level must be an int in [1, 18], got {level!r}")
    if not isinstance(mode, str) or not mode:
        raise ValueError(f"mode must be a non-empty str, got {mode!r}")
    target_armor = _finite_target("target_armor", target_armor)
    target_mr = _finite_target("target_mr", target_mr)
    cid = resolve_champ_id(snapshot, champ_id_or_key)
    item_tuple = normalize_items(snapshot, items)
    key = _cache_key(cid, item_tuple, level, mode, snapshot,
                     target_armor, target_mr)
    if use_cache:
        hit = _cache_get(key, snapshot)
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
        dps = _finite_nonneg(sp.dps)
        if ch == "physical":
            physical_ability += dps
        elif ch == "magical":
            magical_ability += dps
        elif ch == "true":
            true_ability += dps
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
    # Every engine number goes through _finite_nonneg: max(0.0, nan) is
    # 0.0 but max(0.0, inf) is inf, and inf / inf is a NaN ratio.
    eff_as = _finite_nonneg(aa.stats.get("as", 0.0))
    on_hit_dps = _finite_nonneg(
        _finite_nonneg(aa.per_attack_on_hit_damage) * eff_as)
    base_aa_dps = max(0.0, _finite_nonneg(aa.weighted_dps) - on_hit_dps)

    physical_dps = physical_ability + base_aa_dps
    magical_dps = magical_ability
    true_dps = true_ability

    total = physical_dps + magical_dps + true_dps + on_hit_dps
    if not math.isfinite(total):
        # Four finite non-negative floats can still overflow their sum.
        physical_dps = magical_dps = true_dps = on_hit_dps = total = 0.0
    if total > 0:
        mix = {
            "physical": physical_dps / total,
            "magical": magical_dps / total,
            "true": true_dps / total,
            "on_hit": on_hit_dps / total,
        }
    else:
        mix = dict.fromkeys(CHANNELS, 0.0)

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
        mix=MappingProxyType(mix),
    )
    if use_cache:
        _cache_put(key, result, snapshot)
    return result, False
