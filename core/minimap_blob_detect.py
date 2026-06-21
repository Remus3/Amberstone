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
_MASK_CAP = 6000       # if either mask exceeds this, the frame is garbage -> bail


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
    if int(red_mask.sum()) > _MASK_CAP or int(blue_mask.sum()) > _MASK_CAP:
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
# The vision server (:8889) holds the current game frame in-process; we GET it,
# crop the minimap by fraction, and detect. TTL-cached + keyed on the frame ts so
# /api/state (2 Hz) never re-detects the same frame and a slow/absent vision
# server can never stall the state build. Fail-soft: any error -> [].
_VISION_URL = "http://127.0.0.1:8889/latest-frame"
_dots_cache: dict = {"wall": 0.0, "frame_ts": None, "rect": None, "dots": []}


def current_minimap_dots(minimap_rect: Optional[dict], ttl_s: float = 1.5) -> list[dict]:
    """Fetch the live frame, crop the minimap, and detect team dots. Cached for
    `ttl_s` and skipped when the frame ts is unchanged. Returns [] on any failure
    (no vision server, numpy missing, bad rect) so callers can stamp it blindly."""
    if np is None or not isinstance(minimap_rect, dict):
        return []
    import time as _time
    now = _time.time()
    rect_sig = (minimap_rect.get("x"), minimap_rect.get("y"),
                minimap_rect.get("w"), minimap_rect.get("h"))
    if (now - _dots_cache["wall"]) < ttl_s and _dots_cache["rect"] == rect_sig:
        return _dots_cache["dots"]
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
            _dots_cache.update(wall=now, rect=rect_sig, dots=[])
            return []
        frame_ts = data.get("ts")
        if frame_ts is not None and frame_ts == _dots_cache["frame_ts"] \
                and _dots_cache["rect"] == rect_sig:
            _dots_cache["wall"] = now
            return _dots_cache["dots"]
        img = _Image.open(_io.BytesIO(_b64.b64decode(b64))).convert("RGB")
        crop = crop_minimap(np.asarray(img), minimap_rect)
        dots = detect_team_dots(crop) if crop is not None else []
    except Exception:  # noqa: BLE001 - never let a vision hiccup break /api/state
        dots = _dots_cache["dots"]  # serve last good rather than flicker to []
        _dots_cache["wall"] = now
        return dots
    _dots_cache.update(wall=now, frame_ts=frame_ts, rect=rect_sig, dots=dots)
    return dots
