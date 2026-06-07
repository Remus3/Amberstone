"""Hitbox-aware AoE multiplier consumer for the CDragon geometry sidecar.

The geometry sidecar (``cdragon_spell_stats.json``) carries per-spell shape
metadata extracted from CDragon bins.  Each spell record may include a
``geometry`` sub-dict with keys ``cast_radius``, ``cast_radius_conflated``,
``cone_angle``, ``cone_distance``, and ``line_width``.  This module classifies
that dict into a canonical shape string and converts it into a damage
multiplier suitable for teamfight AoE burst scoring.

Design model
------------
LoL AoE spells deal their full single-target damage to every target they
hit (no per-target falloff for the vast majority of spells).  A spell that
hits N enemies in a teamfight therefore deals approximately N x its listed
single-target damage.  Point/unknown spells always hit exactly 1 target and
return multiplier 1.0, making this module byte-identical to the current
single-target burst scorer when targets_hit=1 (the default).

The ``_AOE_TARGET_CAP`` constant parameterizes the realistic upper bound on
targets a teamfight AoE can hit (a full enemy team of five).  All module-scope
magic numbers are named constants.

CDragon geometry shape detection
---------------------------------
* ``line_width`` non-null  -> line skillshot
* ``cone_distance`` non-null OR ``cone_angle`` non-null -> cone
* ``cast_radius`` non-null AND ``cast_radius_conflated=False``
  AND value NOT in ``_CONFLATED_RADIUS_SENTINELS``  -> circle
* Anything else (null geometry, empty dict, boilerplate sentinel)  -> point

The ``cast_radius_conflated`` flag signals that CDragon filled a boilerplate
sentinel value (210.0 or 100.0) rather than a real measured radius.  Trusting
a conflated radius as "circle" would classify melee basic attacks as AoE.

Usage
-----
Call ``spell_aoe_multiplier(snapshot, champ_id, slot, targets_hit)`` from any
burst/combo scorer that already calls ``snapshot.spell_geometry``.  The
function is fail-soft: any exception returns 1.0.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Maximum realistic targets a teamfight AoE spell hits.  A full enemy team is
# 5; capping at 5 prevents unrealistic overcount for extreme sweeping spells.
_AOE_TARGET_CAP: int = 5

# CDragon fills these sentinel values for cast_radius when the real radius is
# unknown (the game engine renders the hit-check internally).  A conflated
# sentinel should NOT be treated as a real circle radius.  Source: CDragon
# bin extractor header comment in cdragon_spell_stats.json.
_CONFLATED_RADIUS_SENTINELS: frozenset[float] = frozenset({210.0, 100.0})

# CDragon fills these boilerplate values for cone_distance when the real cone
# length is unknown (the 210 / 100 extractor conflation).  At 16.11.1
# cone_distance=100.0 appears 487 times and 0.0 45 times, versus 23 spells with a
# real length.  A sentinel is NOT a real cone reach and rejects to None.  Mirrors
# the value of missile._CONE_DISTANCE_SENTINELS (kept local so this module is a
# self-contained forward-marker with no cross-module import).
_CONE_DISTANCE_SENTINELS: frozenset[float] = frozenset({0.0, 100.0})


# ---------------------------------------------------------------------------
# Shape classification
# ---------------------------------------------------------------------------

def classify_spell_shape(geometry: dict | None) -> str:
    """Classify the geometry dict into a canonical shape string.

    Parameters
    ----------
    geometry:
        The ``geometry`` sub-dict from ``DataSnapshot.spell_geometry``, or
        None / empty dict when the sidecar is absent or the spell is
        point/self-cast.

    Returns
    -------
    One of ``"line"``, ``"cone"``, ``"circle"``, ``"point"``, or
    ``"unknown"``.  ``"unknown"`` is returned only when the input is None
    or an empty dict.  A dict with keys present but all null values falls
    through to ``"point"``.
    """
    if not geometry:
        return "unknown"

    # Line skillshot: non-null line_width
    if geometry.get("line_width") is not None:
        return "line"

    # Cone: non-null cone_distance OR non-null cone_angle
    if (
        geometry.get("cone_distance") is not None
        or geometry.get("cone_angle") is not None
    ):
        return "cone"

    # Circle: non-null cast_radius AND NOT conflated AND not a sentinel value
    cast_radius = geometry.get("cast_radius")
    cast_radius_conflated = geometry.get("cast_radius_conflated", False)
    if (
        cast_radius is not None
        and not cast_radius_conflated
        and cast_radius not in _CONFLATED_RADIUS_SENTINELS
    ):
        return "circle"

    # Everything else: point/self-cast / unknown / boilerplate sentinel
    return "point"


# ---------------------------------------------------------------------------
# AoE predicate
# ---------------------------------------------------------------------------

def is_aoe_shape(geometry: dict | None) -> bool:
    """Return True when the geometry corresponds to an AoE shape.

    Line, cone, and circle shapes can hit multiple targets.  Point and
    unknown shapes cannot.
    """
    return classify_spell_shape(geometry) in ("line", "cone", "circle")


# ---------------------------------------------------------------------------
# Multiplier calculation
# ---------------------------------------------------------------------------

def aoe_multiplier(geometry: dict | None, targets_hit: int) -> float:
    """Convert a targets_hit count into a damage multiplier.

    For AoE shapes (line / cone / circle) the multiplier equals
    ``float(clamp(targets_hit, 1, _AOE_TARGET_CAP))``, reflecting
    ``targets_hit`` independent activations of the single-target damage.

    For point or unknown shapes the spell can only ever hit one target,
    so the multiplier is always 1.0 regardless of ``targets_hit``.

    Parameters
    ----------
    geometry:
        The geometry sub-dict from ``DataSnapshot.spell_geometry``.
    targets_hit:
        Number of enemy champions hit in the simulated teamfight window.
        Values below 1 are clamped to 1; values above ``_AOE_TARGET_CAP``
        are clamped to ``_AOE_TARGET_CAP``.

    Returns
    -------
    float
    """
    if not is_aoe_shape(geometry):
        return 1.0
    clamped = min(max(int(targets_hit), 1), _AOE_TARGET_CAP)
    return float(clamped)


# ---------------------------------------------------------------------------
# Convenience wrapper over DataSnapshot
# ---------------------------------------------------------------------------

def spell_aoe_multiplier(
    snapshot: object,
    champ_id: str,
    slot: str,
    targets_hit: int,
) -> float:
    """Fetch geometry from *snapshot* and return the AoE multiplier.

    Convenience function that calls ``snapshot.spell_geometry(champ_id, slot)``
    then delegates to ``aoe_multiplier``.  Fail-soft: any exception (e.g. the
    snapshot has no ``spell_geometry`` method, unknown champ) returns 1.0,
    keeping the scorer byte-identical to the pre-geometry baseline.

    Parameters
    ----------
    snapshot:
        A ``DataSnapshot`` instance (or any object with a
        ``spell_geometry(champ_id, slot)`` method).
    champ_id:
        DDragon champion key, e.g. ``"Lux"``.
    slot:
        Spell slot string: ``"Q"``, ``"W"``, ``"E"``, or ``"R"``.
    targets_hit:
        Number of enemy champions hit; see ``aoe_multiplier``.

    Returns
    -------
    float - always >= 1.0
    """
    try:
        geometry = snapshot.spell_geometry(champ_id, slot)
        return aoe_multiplier(geometry, targets_hit)
    except Exception:
        return 1.0


def spell_cone_angle(
    snapshot: object,
    champ_id: str,
    slot: str,
) -> float | None:
    """Angular SPREAD (degrees) of a cone spell, or None.

    Forward-marker accessor (item 340): exposes the CDragon ``cone_angle``
    geometry datum as a first-class comparable MAGNITUDE.  ``classify_spell_shape``
    reads ``cone_angle`` only as a non-null presence flag (the "cone" shape
    classifier, ``cone_angle is not None``) and ``missile._distance_from_geometry``
    reads only ``cone_distance`` / ``cast_radius`` (never the angle), so the
    numeric spread - which governs ease-of-landing and overlap density, a tight
    20deg Ashe Volley vs a wide 40deg Cassiopeia Petrifying Gaze - was
    structurally discarded.  This accessor lifts that ignored dimension into a
    queryable magnitude, reading the SAME already-loaded sidecar as
    ``spell_aoe_multiplier`` / ``spell_geometry`` (no data duplication,
    patch-refresh-safe), and is the cone sibling of the item-338 line-width
    (``line_width``) accessor.

    NOTHING consumes this accessor at ship: ``classify_spell_shape`` /
    ``spell_aoe_multiplier`` and every serialized surface are untouched, so live
    DS output is byte-identical and ENGINE_VERSION does NOT bump (the item-336 /
    337 / 338 / 339 forward-marker contract).

    Returns the positive ``cone_angle`` float for a cone spell, or None when the
    spell has no geometry, no ``cone_angle`` (line / circle / point), or a
    non-positive / non-numeric angle.  The 0.0 sentinel (CDragon fills it for
    radial-cone spells such as Aurelion Sol Q) returns None via the ``<= 0``
    guard, while ``classify_spell_shape`` still treats it as a cone (presence is
    magnitude-blind) - so the lift is byte-identical to classification.  A None
    return is the byte-identical fallback (mirrors the defensive idiom of the
    other accessors in this module).
    """
    try:
        geometry = snapshot.spell_geometry(champ_id, slot)
        if not geometry:
            return None
        angle = geometry.get("cone_angle")
        if angle is None:
            return None
        angle = float(angle)
        if angle <= 0:
            return None
        return angle
    except (TypeError, ValueError, AttributeError):
        return None


def spell_cone_distance(
    snapshot: object,
    champ_id: str,
    slot: str,
) -> float | None:
    """Reach / LENGTH (units) a cone spell projects from the caster, or None.

    Forward-marker accessor (item 341): exposes the CDragon ``cone_distance``
    geometry datum as a first-class comparable MAGNITUDE.  ``classify_spell_shape``
    reads ``cone_distance`` only as a non-null presence flag (the "cone" shape
    classifier, ``cone_distance is not None``) and
    ``missile._distance_from_geometry`` reads it only as a travel-distance INPUT
    that it folds into ``dist / speed`` (a travel TIME), so the raw reach - which
    together with the item-340 angular spread describes the cone footprint (a long
    narrow cone vs a short wide one) - was structurally discarded.  This accessor
    lifts that ignored dimension into a queryable magnitude, reading the SAME
    already-loaded sidecar as ``spell_aoe_multiplier`` / ``spell_geometry`` (no
    data duplication, patch-refresh-safe), and is the reach sibling of the
    item-340 cone-angle accessor.

    NOTHING consumes this accessor at ship: ``classify_spell_shape`` /
    ``spell_aoe_multiplier`` / the cone-angle accessor and every serialized
    surface are untouched, so live DS output is byte-identical and ENGINE_VERSION
    does NOT bump (the item-336 / 337 / 338 / 339 / 340 forward-marker contract).

    Returns the positive ``cone_distance`` float for a cone spell, or None when
    the spell has no geometry, no ``cone_distance`` (line / circle / point), a
    non-positive / non-numeric reach, or a CDragon placeholder sentinel.  Unlike
    the cone-angle accessor (whose guard is ``<= 0`` only), ``cone_distance``
    carries TWO boilerplate sentinels - 0.0 and 100.0 (``_CONE_DISTANCE_SENTINELS``)
    - that both reject to None.  The 0.0 sentinel still classifies as a cone
    (presence is magnitude-blind) while this accessor returns None - so the lift
    is byte-identical to classification.  A None return is the byte-identical
    fallback (mirrors the defensive idiom of the other accessors in this module).
    """
    try:
        geometry = snapshot.spell_geometry(champ_id, slot)
        if not geometry:
            return None
        distance = geometry.get("cone_distance")
        if distance is None or isinstance(distance, bool):
            return None
        distance = float(distance)
        if distance <= 0 or distance in _CONE_DISTANCE_SENTINELS:
            return None
        return distance
    except (TypeError, ValueError, AttributeError):
        return None
