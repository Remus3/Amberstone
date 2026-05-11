"""FU01 — 3-path resolver for /api/minimap-crop bbox lookups.

Resolution order (highest precedence first):

  1. Caller override (handled by the HTTP route — `?bbox=x1,y1,x2,y2` —
     not this module).
  2. Persisted user calibration in `data/vision_regions.json` under
     `_minimap_<mode>` keys (4-int [l, t, r, b] arrays).
  3. Hardcoded fallback (1920×1080 windowed-borderless defaults).

The hardcoded fallback matches what shipped before this resolver existed —
correct for the operator's primary setup but brittle to HUD-scale changes,
left-side minimap toggle, and non-1080p displays. Persisting a per-mode
calibration via the underscore-prefixed key keeps the file's main region
namespace free of non-OCR entries (vision_tesseract's loader strips
`_*`-prefixed keys, so adding these is safe).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.minimap_bbox")
_APP_DIR = Path(__file__).parent.parent
_REGIONS_FILE = _APP_DIR / "data" / "vision_regions.json"

# 1920×1080 windowed-borderless defaults. Arena has no minimap.
_HARDCODED_FALLBACK: dict[str, tuple[int, int, int, int]] = {
    "sr":    (1565, 735, 1905, 1075),
    "aram":  (1565, 735, 1905, 1075),
    "brawl": (1565, 735, 1905, 1075),
}


def supported_modes() -> tuple[str, ...]:
    """Modes for which a minimap exists. Arena is intentionally excluded."""
    return tuple(_HARDCODED_FALLBACK)


def load_persisted(mode: str) -> Optional[tuple[int, int, int, int]]:
    """Return a (l, t, r, b) bbox from `_minimap_<mode>` in the regions file,
    or None if the entry is missing / malformed / the file is unreadable.

    The caller is expected to fall back to the hardcoded default on None.
    """
    key = f"_minimap_{mode}"
    try:
        if not _REGIONS_FILE.exists():
            return None
        data = json.loads(_REGIONS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.warning("vision_regions.json read failed: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get(key)
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        l, t, r, b = (int(v) for v in raw)
    except (TypeError, ValueError):
        _log.warning("bad %s entry shape: %r", key, raw)
        return None
    if r <= l or b <= t:
        _log.warning("bad %s bbox (r<=l or b<=t): %r", key, raw)
        return None
    return (l, t, r, b)


def resolve(mode: str) -> Optional[tuple[int, int, int, int]]:
    """Resolve a minimap bbox for the given mode.

    Order: persisted → hardcoded fallback. Returns None when the mode is
    unsupported (e.g. arena) — the caller should map that to HTTP 404.

    Caller-side `?bbox=` overrides are NOT consulted here; the HTTP route
    parses and validates those before calling this resolver.
    """
    mode = (mode or "").lower()
    if mode not in _HARDCODED_FALLBACK:
        return None
    persisted = load_persisted(mode)
    if persisted is not None:
        return persisted
    return _HARDCODED_FALLBACK[mode]
