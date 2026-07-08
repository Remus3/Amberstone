"""Pure-numpy team-color blob detection on a League minimap crop - the ZOI
data layer (item 567 slice 2).

Given an RGB minimap crop (HxWx3) this finds the per-team colored blobs - the
champion icons, wards and structures that make up a team's on-map FOOTPRINT -
and returns their centroids in minimap-normalized [0,1] coordinates. It is the
input to the slice-3 Zone-of-Influence shading.

Design notes:
  - 100% LOCAL, no API, no opencv/scipy (numpy only - the RC runtime ships numpy
    but not scipy). Connected components are an 8-connected flood fill.
  - The discriminator between a vivid team ICON and the muted blue/red TERRAIN
    tint (the river, the ally/enemy base wash) is SATURATION + brightness: icons
    are highly saturated, terrain is not. Thresholds were tuned against a live
    1280x720 self-grab minimap crop (208x208), 2026-06-21.
  - This is a team-PRESENCE detector, not champion-only: a turret and a ward read
    the same team color as a champion. Distinguishing champions specifically needs
    template matching or frame-difference motion, which is a future refinement;
    for a ZOI map-control signal, total team presence is the right input anyway.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

from typing import Optional

try:
    import numpy as np
except Exception:  # noqa: BLE001 - numpy missing -> module degrades to no-op
    np = None  # type: ignore[assignment]

# Tuned thresholds (live 2026-06-21). A blob must be vivid (saturated) + bright,
# with its hue clearly in the red or blue band, to count as a team icon.
_SAT_MIN = 0.45        # min HSV saturation (icon vs terrain tint)
_VAL_MIN_RED = 110     # min brightness (max channel) for red
_VAL_MIN_BLUE = 120
_MIN_PX = 5            # reject sub-pixel noise / lone speckles
_MAX_PX = 220          # reject large terrain washes that slip through
# Mask cap as a FRACTION of total crop pixels (2026-07-08: was a fixed 6000,
# tuned at the 208px coaching-frame crop / 43K px = 13.9%. The 568px native
# grab / 323K px was hitting the cap on the normal blue terrain, bailing
# out the entire detection. A fraction is resolution-independent.)
_MASK_CAP_FRAC = 0.14  # if either mask exceeds 14% of pixels, frame is garbage


def _components(mask, min_px: int, max_px: int):
    """8-connected components of a boolean mask via flood fill (pure python over
    a coordinate set - fine for the small, saturation-gated minimap masks)."""
    ys, xs = np.where(mask)
    pending = set(zip(ys.tolist(), xs.tolist()))
    out = []
    while pending:
        sy, sx = pending.pop()
        stack = [(sy, sx)]
        comp = [(sy, sx)]
        while stack:
            y, x = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    n = (y + dy, x + dx)
                    if n in pending:
                        pending.discard(n)
                        stack.append(n)
                        comp.append(n)
        if min_px <= len(comp) <= max_px:
            cy = sum(p[0] for p in comp) / len(comp)
            cx = sum(p[1] for p in comp) / len(comp)
            out.append((cx, cy, len(comp)))
    return out


def detect_team_dots(
    rgb,
    *,
    min_px: int = _MIN_PX,
    max_px: int = _MAX_PX,
) -> list[dict]:
    """Detect per-team colored blobs in an RGB minimap crop.

    `rgb` is an (H, W, 3) array-like (numpy array or anything np.asarray accepts).
    Returns a list of dicts sorted by descending confidence, each:
        {"team": "blue"|"red", "x_frac": float, "y_frac": float,
         "px": int, "confidence": float}
    x_frac/y_frac are the centroid normalized to [0,1] within the crop.
    Returns [] when numpy is unavailable or the input is unusable.
    """
    if np is None:
        return []
    try:
        im = np.asarray(rgb)
    except Exception:  # noqa: BLE001
        return []
    if im.ndim != 3 or im.shape[2] < 3 or im.shape[0] < 3 or im.shape[1] < 3:
        return []
    im = im[:, :, :3].astype(np.int16)
    H, W, _ = im.shape
    R, G, B = im[:, :, 0], im[:, :, 1], im[:, :, 2]
    mx = np.maximum(np.maximum(R, G), B)
    mn = np.minimum(np.minimum(R, G), B)
    sat = (mx - mn) / np.maximum(mx, 1)

    red_mask = (sat > _SAT_MIN) & (mx > _VAL_MIN_RED) & (R == mx) & (R - G > 45) & (R - B > 35)
    blue_mask = (sat > _SAT_MIN) & (mx > _VAL_MIN_BLUE) & (B == mx) & (B - R > 45) & (B - G > 10)
    mask_cap = max(1, int(H * W * _MASK_CAP_FRAC))
    if int(red_mask.sum()) > mask_cap or int(blue_mask.sum()) > mask_cap:
        return []  # frame is loading / garbage - do not emit noise

    dots: list[dict] = []
    for team, mask in (("red", red_mask), ("blue", blue_mask)):
        for cx, cy, px in _components(mask, min_px, max_px):
            # confidence: blob size scaled into [0,1], saturating around a full
            # champion-icon footprint (~60 px at the live 208px crop).
            conf = max(0.0, min(1.0, (px - min_px) / 55.0))
            dots.append({
                "team": team,
                "x_frac": round(float(cx) / W, 4),
                "y_frac": round(float(cy) / H, 4),
                "px": int(px),
                "confidence": round(conf, 3),
            })
    dots.sort(key=lambda d: d["confidence"], reverse=True)
    return dots


def crop_minimap(frame_rgb, minimap_rect: dict, design_w: int = 1920, design_h: int = 1080):
    """Crop the minimap region out of a full game frame.

    `minimap_rect` is the /api/state design-px rect (1920x1080 space). The frame
    is whatever resolution the vision server captured (e.g. 1280x720), so the rect
    is applied as a FRACTION of the frame dimensions, not in absolute px. Returns
    an (h, w, 3) numpy sub-array, or None on bad input.
    """
    if np is None or not isinstance(minimap_rect, dict):
        return None
    try:
        im = np.asarray(frame_rgb)
        FH, FW = im.shape[0], im.shape[1]
        x = float(minimap_rect["x"]) / design_w
        y = float(minimap_rect["y"]) / design_h
        w = float(minimap_rect["w"]) / design_w
        h = float(minimap_rect["h"]) / design_h
    except Exception:  # noqa: BLE001
        return None
    L = max(0, int(round(x * FW)))
    T = max(0, int(round(y * FH)))
    Rr = min(FW, int(round((x + w) * FW)))
    Bb = min(FH, int(round((y + h) * FH)))
    if Rr - L < 3 or Bb - T < 3:
        return None
    return im[T:Bb, L:Rr]


# --- live integration (I/O; the pure detection above stays unit-testable) -----
# The minimap is grabbed and detected on demand. PRIMARY: a NATIVE full-screen
# grab cropped to the minimap by fraction (~416px, 4x the pixels, no JPEG) so
# champion icons are large + artifact-free. FALLBACK: the :8889 coaching frame
# (1280-downscaled JPEG, ~208px). TTL + rect cached so /api/state (2 Hz) never
# re-grabs mid-window; fail-soft everywhere -> [] on any error.
_VISION_URL = "http://127.0.0.1:8889/latest-frame"
_dots_cache: dict = {"wall": 0.0, "rect": None, "dots": [], "good_wall": 0.0}

# Size-threshold baseline: _MIN_PX/_MAX_PX were tuned on the 208px coaching-frame
# crop; _scaled_size_bounds rescales them to the actual crop width so the native
# 416px crop detects the SAME physical footprints (resolution-invariant).
_TUNED_CROP_W = 208.0

# Hold last-good dots across a TRANSIENT grab failure (crop is None / an
# exception) so a momentary miss does not flicker /api/state.zoi (and the
# overlay) to empty ~1 Hz. Strictly greater than the 1.5s TTL so a real
# game-end (persistent failure) still expires the hold within ~2 polls. A
# legit-empty frame (grab succeeded, no champions in view) is NOT held - it
# passes through as [] so the overlay clears when the game genuinely ends.
_HOLD_LAST_GOOD_S = 3.0


def _native_grab_enabled() -> bool:
    """RC_ZOI_NATIVE_GRAB gates the high-res native minimap grab (default ON,
    2026-07-01). The 1280 self-grab downscale + JPEG left champion icons too
    small/blurry for reliable detection; the native grab gives a ~416px crop.
    Set RC_ZOI_NATIVE_GRAB=0 to force the legacy coaching-frame crop."""
    import os
    return os.environ.get("RC_ZOI_NATIVE_GRAB", "1").strip().lower() \
        not in ("0", "false", "no", "off", "")


def _identity_enabled() -> bool:
    """RC_ZOI_IDENTITY gates the per-dot champion identity pass (spec E-1,
    DEFAULT ON since 2026-07-08 - operator asked for minimap identity display).
    Flag off is byte-identical to the pre-identity behavior. Mirrors the
    RC_ZOI_NATIVE_GRAB env pattern above, with the same default (ON).
    Set RC_ZOI_IDENTITY=0 to disable."""
    import os
    return os.environ.get("RC_ZOI_IDENTITY", "1").strip().lower() \
        not in ("0", "false", "no", "off", "")


def _live_roster() -> list:
    """The <=10 champion display names from the Live Client allPlayers list
    (core/vision_tracker.py:307 naming), via the shared liveclient_cache.
    Fail-soft: no game / relay down / malformed payload -> []."""
    try:
        from core.liveclient_cache import get as _lc_get
        snap = _lc_get()
        data = snap.data
        players = data.get("allPlayers") if isinstance(data, dict) else None
        out = []
        for p in players or []:
            if not isinstance(p, dict):
                continue
            champ = p.get("championName")
            if isinstance(champ, str) and champ.strip():
                out.append(champ.strip())
        return out
    except Exception:  # noqa: BLE001 - roster is best-effort, never blocks dots
        return []


def _scaled_size_bounds(crop_w) -> tuple[int, int]:
    """Rescale (_MIN_PX, _MAX_PX) from the 208px tuning baseline to `crop_w` by
    LINEAR ratio (2026-07-08: was area / quadratic, but champion minimap icons
    are FIXED pixel size  -  they don't scale with crop width). A native 416px
    crop (2x linear) has the same ~27px icon; a 568px crop also has ~27px.
    Linear scaling keeps the thresholds anchored to the pixel density, not the
    area, so the same physical objects pass through."""
    try:
        sc = max(1.0, float(crop_w) / _TUNED_CROP_W)
    except (TypeError, ValueError):
        return _MIN_PX, _MAX_PX
    minpx = max(_MIN_PX, int(round(_MIN_PX * sc)))
    maxpx = max(minpx + 1, int(round(_MAX_PX * sc)))
    return minpx, maxpx


def _grab_obs_minimap(minimap_rect):
    """OBS occlusion-proof minimap crop (ZOI plan spec O, 2026-07-05).

    Config-gated on ``obs.frame_source`` (DEFAULT OFF). When enabled, the OBS
    GetSourceScreenshot frame (source-scoped Game Capture - the RC overlay on
    top of the game never appears in it) is decoded and cropped exactly like
    the GDI path. ANY failure (flag off, OBS down, PIL absent, decode error)
    returns None so the caller falls back to the GDI grab - flag off is
    byte-identical to prior behavior."""
    if np is None or not isinstance(minimap_rect, dict):
        return None
    try:
        from core.obs_frame_source import get_obs_frame, obs_frame_source_enabled
        if not obs_frame_source_enabled():
            return None
        raw = get_obs_frame()
        if not raw:
            return None
        import io as _io

        from PIL import Image as _Image
        img = _Image.open(_io.BytesIO(raw)).convert("RGB")
        return crop_minimap(np.asarray(img), minimap_rect)
    except Exception:  # noqa: BLE001 - never let the OBS lane break /api/state
        return None


def _grab_native_minimap(minimap_rect):
    """High-res minimap crop from a NATIVE full-screen grab (no 1280 downscale,
    no JPEG). ~416px vs the 208px coaching-frame crop = 4x the pixels + clearer
    icons. Same single-GDI-BitBlt grab as the vision self-grab
    (vision_server/_frame.py) so there are no new multi-monitor assumptions -
    only the resolution differs. Returns (H, W, 3) uint8 or None (PIL absent /
    headless / grab error / bad rect).

    Spec O (2026-07-05): when config ``obs.frame_source`` is on, the OBS
    occlusion-proof frame is preferred; ANY OBS failure falls back to the GDI
    BitBlt below. Flag off (default) short-circuits inside _grab_obs_minimap
    and this function behaves exactly as before."""
    if np is None or not isinstance(minimap_rect, dict):
        return None
    obs_crop = _grab_obs_minimap(minimap_rect)
    if obs_crop is not None:
        return obs_crop
    try:
        from PIL import ImageGrab
    except Exception:  # noqa: BLE001 - headless / PIL absent
        return None
    try:
        full = ImageGrab.grab()
        if full is None:
            return None
        return crop_minimap(np.asarray(full.convert("RGB")), minimap_rect)
    except Exception:  # noqa: BLE001 - never let a grab hiccup break /api/state
        return None


def _grab_frame_minimap(minimap_rect):
    """Fallback: crop the minimap from the :8889 coaching frame (1280-downscaled
    JPEG, ~208px). Lower fidelity than _grab_native_minimap. Returns (H, W, 3)
    or None on any failure."""
    try:
        import base64 as _b64
        import io as _io
        import json as _json
        import urllib.request as _ur

        from PIL import Image as _Image

        from core.vision_token import get_vision_token as _tok
        req = _ur.Request(_VISION_URL, headers={"X-RC-Token": _tok()})
        with _ur.urlopen(req, timeout=1.5) as r:
            data = _json.loads(r.read())
        b64 = data.get("b64") if isinstance(data, dict) else None
        if not b64:
            return None
        img = _Image.open(_io.BytesIO(_b64.b64decode(b64))).convert("RGB")
        return crop_minimap(np.asarray(img), minimap_rect)
    except Exception:  # noqa: BLE001
        return None


def current_minimap_dots(minimap_rect: Optional[dict], ttl_s: float = 1.5,
                         roster: Optional[list] = None) -> list[dict]:
    """Grab the minimap and detect team dots. Prefers the NATIVE full-res grab
    (RC_ZOI_NATIVE_GRAB, default ON) for 4x the pixels; falls back to the :8889
    coaching-frame crop. TTL + rect cached. Returns [] on any failure (no vision
    server, numpy missing, headless, bad rect) so callers can stamp it blindly.

    Spec E-1 (2026-07-05): when RC_ZOI_IDENTITY is on (DEFAULT OFF), an
    additive champion-identity pass (core/minimap_identity.identify_dots)
    annotates dots with {"champion", "identity_confidence"} scoped to
    `roster` (or, when None, the Live Client allPlayers roster). Flag off is
    byte-identical to prior behavior; an identity failure degrades to the
    plain presence dots, never []."""
    if np is None or not isinstance(minimap_rect, dict):
        return []
    import time as _time
    now = _time.time()
    rect_sig = (minimap_rect.get("x"), minimap_rect.get("y"),
                minimap_rect.get("w"), minimap_rect.get("h"))
    if (now - _dots_cache["wall"]) < ttl_s and _dots_cache["rect"] == rect_sig:
        return _dots_cache["dots"]
    try:
        crop = _grab_native_minimap(minimap_rect) if _native_grab_enabled() else None
        if crop is None:
            crop = _grab_frame_minimap(minimap_rect)
        # crop None (or zero-size) => the GRAB failed (both grabbers return None
        # on failure); a non-None crop that simply detects no champions is a
        # LEGIT-empty frame. These diverge below: a failed grab holds last-good,
        # a legit-empty frame clears.
        grab_failed = crop is None or getattr(crop, "size", 0) == 0
        if grab_failed:
            dots = []
        else:
            minpx, maxpx = _scaled_size_bounds(crop.shape[1])
            dots = detect_team_dots(crop, min_px=minpx, max_px=maxpx)
            if dots and _identity_enabled():
                try:
                    names = roster if roster is not None else _live_roster()
                    if names:
                        from core.minimap_identity import identify_dots as _identify
                        dots = _identify(crop, dots, names)
                except Exception:  # noqa: BLE001 - identity is additive, never blocks presence
                    pass
    except Exception:  # noqa: BLE001 - a grab/detect exception is a failure, not empty
        grab_failed = True
        dots = []

    if dots:
        # Fresh detection: stamp everything incl. the good-frame anchor.
        _dots_cache.update(wall=now, rect=rect_sig, dots=dots, good_wall=now)
        return dots
    if (grab_failed and _dots_cache["dots"]
            and _dots_cache["rect"] == rect_sig
            and (now - _dots_cache["good_wall"]) < _HOLD_LAST_GOOD_S):
        # Transient grab failure within the hold window: serve last-good so a
        # momentary miss does not flicker the overlay to empty. Refresh the TTL
        # wall only - keep good_wall + dots so the window still expires at a
        # real game-end (persistent failure) instead of holding forever.
        _dots_cache["wall"] = now
        return _dots_cache["dots"]
    # Legit-empty frame (grab succeeded, no champions), OR the hold window has
    # elapsed, OR the rect changed: clear.
    _dots_cache.update(wall=now, rect=rect_sig, dots=[])
    return []
