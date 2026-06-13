"""missile.py - skillshot travel-time from the missile_speed sidecar bucket.

Pairs CDragon missile_speed (416 spells at 16.11.1) with geometry for
distance to compute approximate in-flight duration of a projectile spell.

Speed bands gate the MIX of values honestly:
  <400          dash / melee / on-hit artifact  -> not a projectile
  400-4999      real projectile (1000-3000 band) -> compute travel
  >=5000        instant / global (incl. 1e9 sentinel) -> 0.0 travel
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .data_loader import DataSnapshot

# --- module constants ---

_MIN_PROJECTILE_SPEED: float = 400.0
"""Below this speed the entry is a dash / melee / on-hit artifact, not a
real projectile.  The lower band of the CDragon mix (20, 7, ...) falls here."""

_INSTANT_SPEED: float = 5000.0
"""At or above this speed the projectile is effectively instant or global
(e.g. Jhin W 10000, Swain Q 1e9 sentinel).  Travel time = 0.0."""

_DEFAULT_DISTANCE: float = 1000.0
"""Fallback cast distance (units) when geometry yields no usable range.
Represents a typical mid-range skillshot cast."""

_CONE_DISTANCE_SENTINELS: frozenset[float] = frozenset({0.0, 100.0})
"""CDragon cone_distance boilerplate values that are NOT real cone lengths.
At 16.11.1 cone_distance=100.0 appears 487 times + 0.0 45 times (the
placeholder) vs ~23 spells with a real value - mirrors the cast_radius
210/100 conflation. A sentinel cone_distance is rejected so the travel-time
falls to a real cast_radius or _DEFAULT_DISTANCE, never the 100 garbage."""

_MIN_REAL_DISTANCE: float = 200.0
"""Floor below which a geometry distance is treated as an artifact (e.g. the
cast_radius=20 dash entries) and rejected in favor of _DEFAULT_DISTANCE."""


# --- internal helpers ---

def _distance_from_geometry(geometry: "dict | None") -> "float | None":
    """Extract a REAL travel distance from the CDragon geometry dict.

    Priority:
      1. ``cone_distance`` when non-null, NOT a placeholder sentinel
         (0.0 / 100.0), and >= ``_MIN_REAL_DISTANCE`` (cone spell length).
      2. ``cast_radius`` when non-null, NOT ``cast_radius_conflated``, and
         >= ``_MIN_REAL_DISTANCE`` (projectile / circle range).
      3. None otherwise (caller falls to ``_DEFAULT_DISTANCE``).

    The sentinel / floor filters are essential: cone_distance=100.0 is a
    near-universal CDragon placeholder, so taking it verbatim would yield a
    nonsense 100/speed travel time on ~487 spells. ``line_width`` is a
    perpendicular width, not a travel length, so it is never used here.
    """
    if not geometry:
        return None

    cone_dist = geometry.get("cone_distance")
    if cone_dist is not None:
        try:
            cd = float(cone_dist)
            if cd not in _CONE_DISTANCE_SENTINELS and cd >= _MIN_REAL_DISTANCE:
                return cd
        except (TypeError, ValueError):
            pass

    cast_rad = geometry.get("cast_radius")
    conflated = geometry.get("cast_radius_conflated", True)
    if cast_rad is not None and not conflated:
        try:
            cr = float(cast_rad)
            if cr >= _MIN_REAL_DISTANCE:
                return cr
        except (TypeError, ValueError):
            pass

    return None


# --- public API ---

def is_projectile(
    snapshot: "DataSnapshot",
    champ_id: str,
    slot: str,
) -> bool:
    """Return True when the spell has a real projectile missile.

    A real projectile has missile_speed >= ``_MIN_PROJECTILE_SPEED``.
    Artifacts (dashes, melee on-hit, ~20 u/s entries), absent entries,
    and instant/global speeds all return False here -- instant spells
    ARE projectiles in a gameplay sense but their travel time is 0.0,
    not None, so callers that only want finite travel-time projectiles
    may want to check that separately.
    """
    try:
        speed = snapshot.spell_missile_speed(champ_id, slot)
        if speed is None:
            return False
        return float(speed) >= _MIN_PROJECTILE_SPEED
    except Exception:
        return False


def spell_travel_time(
    snapshot: "DataSnapshot",
    champ_id: str,
    slot: str,
    distance: "float | None" = None,
) -> "float | None":
    """Approximate travel time (seconds) for a skillshot projectile.

    Returns None when the spell is not a real projectile (artifact / absent).
    Returns 0.0 for instant / global missiles (speed >= ``_INSTANT_SPEED``).
    Otherwise returns ``dist / speed`` rounded to 4 decimal places, where
    ``dist`` is the explicit ``distance`` argument if positive, else the
    distance derived from the spell's CDragon geometry, else
    ``_DEFAULT_DISTANCE``.

    Parameters
    ----------
    snapshot:
        Loaded DataSnapshot (provides missile_speed + geometry accessors).
    champ_id:
        DDragon champion id (e.g. "Lux", "Morgana").
    slot:
        Spell slot string: "Q", "W", "E", or "R".
    distance:
        Optional explicit cast distance in units.  When omitted or <= 0,
        geometry is consulted and ``_DEFAULT_DISTANCE`` is the final fallback.

    Returns
    -------
    float | None
        Travel time in seconds, or None for non-projectiles.
    """
    try:
        speed = snapshot.spell_missile_speed(champ_id, slot)
        if speed is None:
            return None
        speed = float(speed)
        if speed < _MIN_PROJECTILE_SPEED:
            return None
        if speed >= _INSTANT_SPEED:
            return 0.0
        # Reject a non-finite explicit distance (inf / NaN): math.isfinite
        # guards the ``distance > 0`` test (inf passes it and would serialize
        # a bare ``Infinity`` JSON token downstream). A non-finite distance
        # falls back to geometry / _DEFAULT_DISTANCE.
        if distance is not None and math.isfinite(distance) and distance > 0:
            dist = float(distance)
        else:
            geo = snapshot.spell_geometry(champ_id, slot)
            dist = _distance_from_geometry(geo) or _DEFAULT_DISTANCE
        travel = round(dist / speed, 4)
        # Final guard: a non-finite product (defensive against a non-finite
        # geometry datum) returns None rather than a bare NaN/Infinity token
        # that breaks JSON.parse on the consuming route.
        if not math.isfinite(travel):
            return None
        return travel
    except Exception:
        return None


def spell_missile_width(
    snapshot: "DataSnapshot",
    champ_id: str,
    slot: str,
) -> "float | None":
    """Perpendicular HITBOX WIDTH (units) of a line skillshot, or None.

    Forward-marker accessor (item 338): exposes the CDragon ``line_width``
    geometry datum as a first-class comparable MAGNITUDE.  ``geometry.py``
    reads ``line_width`` only as a non-null presence flag (the "line"
    shape classifier) and ``_distance_from_geometry`` explicitly REJECTS it
    ("a perpendicular width, not a travel length, so it is never used here"),
    so the numeric width - which governs ease-of-landing, a narrow 40u
    Nidalee Q spear vs a wide 100u Xerath Q bolt - was structurally
    discarded.  This accessor lifts that ignored dimension into a queryable
    magnitude, reading the SAME already-loaded sidecar as ``spell_travel_time``
    (no data duplication, patch-refresh-safe).

    NOTHING consumes this accessor at ship: ``is_projectile`` /
    ``spell_travel_time`` / ``_distance_from_geometry`` and every serialized
    surface are untouched, so live DS output is byte-identical and
    ENGINE_VERSION does NOT bump (the item-336 / item-337 forward-marker
    contract).

    Returns the positive ``line_width`` float for a line skillshot, or None
    when the spell has no geometry, no ``line_width`` (cone / circle / point),
    or a non-positive / non-numeric width.  A None return is the
    byte-identical fallback (mirrors the defensive idiom of the other
    accessors in this module).
    """
    try:
        geometry = snapshot.spell_geometry(champ_id, slot)
        if not geometry:
            return None
        width = geometry.get("line_width")
        if width is None:
            return None
        width = float(width)
        if width <= 0:
            return None
        return width
    except (TypeError, ValueError, AttributeError):
        return None
