# arch: MIA reachability rings - SOLE zoi.mia producer (ZOI Wave 3, spec E-2) | section=core | frozen=no
"""core.mia_reachability - MIA reachability rings for the minimap overlay.

The SOLE producer of the ``zoi.mia`` payload (operator decision 1 in
docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md section 8 - do NOT author a
separate zoi_mia.py). One growing circle per fogged enemy: origin at the
last-seen map position, radius = how far the champion could have walked
since (missing time x estimated movespeed), confidence decaying the
longer they stay unseen.

INPUT - the ``core.vision_tracker`` per-enemy rows (vision_tracker.py:376-388):
    {champion, team, level, is_dead, respawn_in_s, visible, missing_for_s,
     last_seen_pos: {x, z}, last_seen_t, last_seen_zone}
accepted as either the tracker's ``state()["enemies"]`` dict (champion ->
row, vision_tracker.py:177-184) or a plain list of rows.

OUTPUT - the fixed cross-agent contract payload, or ``None``:
    {"rings": [{"champion": str|None, "cx": float, "cy": float,
                "r_frac": float, "missing_for_s": float,
                "confidence": float}],
     "count": int}
Coordinates are box-fraction [0, 1] within the minimap crop, the same
convention as ``zoi.bubbles`` (core/zoi_influence.py).

AXIS CONVENTION (grep-verified): League map units put the Blue/Order base
at LOW x, LOW z (core/vision_tracker.py:55-61 ``_sr_zone`` blue_base is
``x < 3500 and z < 3500``), while the box-fraction minimap frame is
y-DOWN with blue base bottom-LEFT (config/minimap_grids/sr.json:4 -
blue_base poly y in [0.82, 1.0]). So:
    cx = x / extent
    cy = 1 - z / extent          (z axis INVERTED to minimap y)
A flipped HUD mirrors the crop on X (core/minimap_districts.py:11-13);
``minimap_rect["flip"]`` (core/league_settings.py:142) applies the same
mirror here so rings line up with the flipped crop: cx -> 1 - cx.

MODE GATE (fail-CLOSED, mirrors core/mode_capabilities._normalize):
SR only. ``mode`` accepts the _state_builder mode_key ``"sr"``
(dashboard/_state_builder.py:119), the canonical ``"SR"``
(core/game_snapshot.py:64) and the raw Riot ``"CLASSIC"``. ARAM/KIWI,
ARENA/CHERRY, brawl, tft, garbage, None -> ``None`` (shared vision or no
fog - no rings ever).

DOCUMENTED CONSTANTS:
  - MIN_MISSING_S = 3.0: an enemy must be fogged STRICTLY longer than
    this before a ring appears (mirrors the laning MISS threshold,
    core/laning_cv_overrides.py:50 - shorter gaps are brush/clip noise).
  - R_MIN_FRAC = 0.02: floor so a just-fogged enemy still renders a
    visible pin-prick ring (2% of the minimap side).
  - R_MAX_FRAC = 0.6: cap - beyond this the ring covers most of the map
    and carries no information ("could be anywhere").
  - CONF_HALF_LIFE_S = 30.0: confidence halves every 30s of fog
    (exponential decay; ~0.93 at the 3s floor, 0.5 at 30s, 0.25 at 60s).
  - CONF_MIN = 0.05: confidence floor so a rendered ring never fades to
    fully invisible while it still qualifies.

Dead enemies get NO ring - respawn is API truth (respawnTimer ->
``respawn_in_s``); a track with no ``last_seen_pos`` gets NO ring (never
guess an origin). Pure, no I/O, fail-soft: garbage rows are skipped,
garbage containers / non-SR modes return ``None``. NEVER raises.
"""
from __future__ import annotations

from core.champion_movespeed import distance_frac_per_s, est_ms

#: SR map extent in game units (core/vision_tracker.py:55).
_SR_MAP_EXTENT = 14800.0

#: Fog floor (s) before a ring appears - see module docstring.
MIN_MISSING_S = 3.0

#: Ring radius clamps, box-fraction of the minimap side.
R_MIN_FRAC = 0.02
R_MAX_FRAC = 0.6

#: Confidence exponential-decay half-life (s) + floor.
CONF_HALF_LIFE_S = 30.0
CONF_MIN = 0.05

#: Mode spellings accepted as Summoner's Rift (case-insensitive):
#: _state_builder mode_key "sr", canonical "SR", raw Riot "CLASSIC".
_SR_MODE_KEYS = frozenset({"sr", "classic"})


def _num(v):
    """Coerce to a finite float, or None (core/zoi_influence.py guard)."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _is_sr(mode) -> bool:
    """Fail-CLOSED SR check (mirrors core/mode_capabilities fail-closed
    normalization: only explicit SR spellings pass; everything else,
    including the mode_from_game_mode_string catch-all default, is
    rejected)."""
    try:
        if not isinstance(mode, str):
            return False
        return mode.strip().lower() in _SR_MODE_KEYS
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return False


def _rows(enemy_tracks):
    """Normalize the tracks container to a list of candidate rows, or
    None when the container itself is garbage."""
    if isinstance(enemy_tracks, dict):
        return list(enemy_tracks.values())
    if isinstance(enemy_tracks, (list, tuple)):
        return list(enemy_tracks)
    return None


def _ring_for(track, game_time_s, flip):
    """One contract ring for a track, or None when it does not qualify.
    Never raises (caller also guards)."""
    if not isinstance(track, dict):
        return None
    if track.get("is_dead"):
        return None  # respawn is API truth - dead champs get NO ring
    if track.get("visible") is not False:
        return None  # only an explicit fogged read qualifies

    raw_missing = track.get("missing_for_s")
    if raw_missing is None:
        # Absent stamp: derive from the game clock the same way the
        # tracker itself does (vision_tracker.py:365-367).
        missing = None
        last_seen_t = _num(track.get("last_seen_t"))
        now = _num(game_time_s)
        if last_seen_t is not None and now is not None and now >= last_seen_t:
            missing = now - last_seen_t
    else:
        # Present-but-garbage stamp (NaN / string) marks the whole row
        # suspect - skip it rather than trusting a sibling field.
        missing = _num(raw_missing)
    if missing is None or missing <= MIN_MISSING_S:
        return None

    pos = track.get("last_seen_pos")
    if not isinstance(pos, dict):
        return None  # no origin -> no ring (never guess)
    x = _num(pos.get("x"))
    z = _num(pos.get("z"))
    if x is None or z is None:
        return None

    # Map units -> box-fraction: x maps straight, z INVERTED to minimap y
    # (y-down frame, blue base bottom-left - see module docstring).
    cx = min(1.0, max(0.0, x / _SR_MAP_EXTENT))
    cy = min(1.0, max(0.0, 1.0 - z / _SR_MAP_EXTENT))
    if flip:
        cx = 1.0 - cx  # flipped HUD mirrors the crop on X

    raw_champ = track.get("champion")
    champion = raw_champ if isinstance(raw_champ, str) and raw_champ.strip() else None

    # Radius: reachable distance since last seen, clamped. A zero speed
    # (unknown data) still yields the R_MIN_FRAC pin-prick - honest floor.
    r_raw = missing * distance_frac_per_s(est_ms(champion))
    r_frac = min(R_MAX_FRAC, max(R_MIN_FRAC, r_raw))

    # Confidence: exponential decay in fog time, floored (docstring).
    conf = 0.5 ** (missing / CONF_HALF_LIFE_S)
    conf = min(1.0, max(CONF_MIN, conf))

    return {
        "champion": champion,
        "cx": round(cx, 4),
        "cy": round(cy, 4),
        "r_frac": round(r_frac, 4),
        "missing_for_s": round(float(missing), 1),
        "confidence": round(conf, 3),
    }


def compute_mia(enemy_tracks, mode, game_time_s, minimap_rect=None):
    """MIA reachability rings -> the ``zoi.mia`` contract payload, or None.

    ``enemy_tracks``: vision_tracker enemies (dict champion->row, or list
    of rows). ``mode``: SR spellings only (fail-closed - anything else
    returns None). ``game_time_s``: current game clock, used only to
    derive a missing duration when the row lacks ``missing_for_s``.
    ``minimap_rect``: the /api/state minimap_rect payload; only its
    ``flip`` flag is read (rings must mirror with a flipped crop).
    Never raises.
    """
    try:
        if not _is_sr(mode):
            return None  # shared vision / no fog / unknown -> no payload
        rows = _rows(enemy_tracks)
        if rows is None:
            return None
        flip = bool(minimap_rect.get("flip")) if isinstance(minimap_rect, dict) else False
        rings = []
        for track in rows:
            try:
                ring = _ring_for(track, game_time_s, flip)
            except Exception:  # noqa: BLE001 - fail-soft: skip bad row
                ring = None
            if ring is not None:
                rings.append(ring)
        return {"rings": rings, "count": len(rings)}
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return None
