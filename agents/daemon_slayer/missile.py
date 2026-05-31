"""missile.py - skillshot travel-time from the missile_speed sidecar bucket.

Pairs CDragon missile_speed (416 spells at 16.11.1) with geometry for
distance to compute approximate in-flight duration of a projectile spell.

Speed bands gate the MIX of values honestly:
  <400          dash / melee / on-hit artifact  -> not a projectile
  400-4999      real projectile (1000-3000 band) -> compute travel
  >=5000        instant / global (incl. 1e9 sentinel) -> 0.0 travel
"""

from __future__ import annotations

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


# --- internal helpers ---

def _distance_from_geometry(geometry: "dict | None") -> "float | None":
    """Extract a travel distance from the CDragon geometry dict.

    Priority:
      1. ``cone_distance`` when non-null (cone spell length).
      2. ``cast_radius`` when non-null AND ``cast_radius_conflated`` is False
         (projectile / circle range).
      3. None otherwise.

    ``line_width`` is a perpendicular width, not a travel length, so it is
    never used as a distance here.
    """
    if not geometry:
        return None

    cone_dist = geometry.get("cone_distance")
    if cone_dist is not None:
        try:
            return float(cone_dist)
        except (TypeError, ValueError):
            pass

    cast_rad = geometry.get("cast_radius")
    conflated = geometry.get("cast_radius_conflated", True)
    if cast_rad is not None and not conflated:
        try:
            return float(cast_rad)
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
        if distance is not None and distance > 0:
            dist = float(distance)
        else:
            geo = snapshot.spell_geometry(champ_id, slot)
            dist = _distance_from_geometry(geo) or _DEFAULT_DISTANCE
        return round(dist / speed, 4)
    except Exception:
        return None
