"""FU01 - 3-path resolver for /api/minimap-crop bbox lookups.

Resolution order (highest precedence first):

  1. Caller override (handled by the HTTP route - `?bbox=x1,y1,x2,y2` -
     not this module; the route validates it with `parse_http_override`).
  2. Persisted user calibration in `data/vision_regions.json` under
     `_minimap_<mode>` keys (4-int [l, t, r, b] arrays).
  3. Hardcoded fallback (1920x1080 windowed-borderless defaults).

The hardcoded fallback matches what shipped before this resolver existed -
correct for the operator's primary setup but brittle to HUD-scale changes,
left-side minimap toggle, and non-1080p displays. Persisting a per-mode
calibration via the underscore-prefixed key keeps the file's main region
namespace free of non-OCR entries (core/vision_tesseract.py's loader skips
`_*`-prefixed keys, so adding these is safe).

CONTRACT (s144 true-audit). A persisted entry and an HTTP override pass the
SAME check (`_validate`): four integer coordinates, each in
[0, `MAX_COORD`], with r > l and b > t. `resolve` and `load_persisted` never
raise on a bad file or entry - they fall back, logging one warning per
distinct problem rather than one per call (the route is polled every ~2 s),
and they let an unexpected exception type surface instead of serving the
fallback over a caller bug. `parse_http_override` raises ValueError, and only
ValueError, on any bad input so the route can answer 400.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.minimap_bbox")
_APP_DIR = Path(__file__).parent.parent
_REGIONS_FILE = _APP_DIR / "data" / "vision_regions.json"

# Upper bound on any coordinate. A box past it would make PIL allocate an
# image of that size on every poll (the crop pads outside the frame).
MAX_COORD = 10000

# Plain ASCII digits only: int() also takes "1_0", "+1" and non-ASCII digits.
_DIGITS = re.compile(r"[0-9]{1,6}")

# Errors a read of the regions file is EXPECTED to raise: a missing, locked
# or directory path (OSError), a non-UTF-8 file (UnicodeDecodeError, a
# ValueError), bad JSON (JSONDecodeError, a ValueError) and very deep
# nesting (RecursionError).
_READ_ERRORS = (OSError, ValueError, RecursionError)

# Longest repr of a bad entry that goes into a log line.
_LOG_REPR_MAX = 120

# 1920x1080 windowed-borderless defaults. Arena has no minimap.
_HARDCODED_FALLBACK: dict[str, tuple[int, int, int, int]] = {
    "sr":    (1565, 735, 1905, 1075),
    "aram":  (1565, 735, 1905, 1075),
    "brawl": (1565, 735, 1905, 1075),
}

_warn_lock = threading.Lock()
_last_warning: dict[str, str] = {}


def _reset_warnings() -> None:
    """Forget every logged warning (tests)."""
    with _warn_lock:
        _last_warning.clear()


def _warn_once(slot: str, message: str) -> None:
    """Log `message` unless it is the last warning logged for `slot`."""
    with _warn_lock:
        if _last_warning.get(slot) == message:
            return
        _last_warning[slot] = message
    _log.warning("%s", message)


def _clear_warning(slot: str) -> None:
    with _warn_lock:
        _last_warning.pop(slot, None)


def _clip(text: str) -> str:
    if len(text) > _LOG_REPR_MAX:
        text = text[:_LOG_REPR_MAX] + "...(truncated)"
    return text


def _short_repr(value: object) -> str:
    return _clip(repr(value))


def _coerce_coord(value: object) -> int:
    """Return `value` as an int coordinate or raise ValueError.

    Accepts an int, an integral finite float (a JSON writer may emit 10.0)
    and a plain ASCII digit string. Rejects bool, a fractional float (int()
    would truncate it and silently move the box), NaN / Infinity, and any
    other type.
    """
    if isinstance(value, bool):
        raise ValueError(f"bool coordinate: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # is_integer() is False for NaN and +/-Infinity too.
        if not value.is_integer():
            raise ValueError(f"non-integral coordinate: {value!r}")
        return int(value)
    if isinstance(value, str):
        if not _DIGITS.fullmatch(value):
            raise ValueError(f"not a plain integer: {_short_repr(value)}")
        return int(value)
    raise ValueError(f"unsupported coordinate type {type(value).__name__}")


def _validate(coords: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Apply the shared bbox contract; raise ValueError on any violation."""
    left, top, right, bottom = coords
    if not all(0 <= c <= MAX_COORD for c in coords):
        raise ValueError(f"coord out of range [0, {MAX_COORD}]: {coords}")
    if right <= left or bottom <= top:
        raise ValueError(f"r<=l or b<=t: {coords}")
    return coords


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
        # utf-8-sig: a file saved by PowerShell 5.1 or an editor may carry a
        # BOM, which plain utf-8 leaves in and json.loads rejects.
        data = json.loads(_REGIONS_FILE.read_text(encoding="utf-8-sig"))
    except _READ_ERRORS as exc:
        _warn_once(
            "file",
            f"vision_regions.json read failed: {type(exc).__name__}: "
            f"{_clip(str(exc))}",
        )
        return None
    if not isinstance(data, dict):
        _warn_once("file", "vision_regions.json top level is not an object")
        return None
    _clear_warning("file")
    if key not in data:
        _clear_warning(key)
        return None
    raw = data[key]
    try:
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            raise ValueError("expected a 4-element array")
        coords = tuple(_coerce_coord(v) for v in raw)
        result = _validate(coords)  # type: ignore[arg-type]
    except ValueError as exc:
        # The message can carry the coerced ints, which JSON lets be huge.
        _warn_once(key, f"bad {key} entry ({_clip(str(exc))}): {_short_repr(raw)}")
        return None
    _clear_warning(key)
    return result


def parse_http_override(raw: str) -> tuple[int, int, int, int]:
    """Parse and validate a `?bbox=x1,y1,x2,y2` query-string value.

    Enforces the same contract as `load_persisted` (`_validate`): r>l, b>t,
    and each coordinate in [0, MAX_COORD]. Each part is plain ASCII digits,
    optionally padded with spaces. Raises `ValueError` - and only that - with
    a descriptive message on any violation so the caller can return HTTP 400.
    """
    if not isinstance(raw, str):
        raise ValueError(f"bbox must be a string, got {type(raw).__name__}")
    parts = raw.split(",")
    # Arity first, so a huge comma list is refused before any conversion.
    if len(parts) != 4:
        raise ValueError(f"expected 4 elements, got {len(parts)}")
    stripped = [p.strip(" ") for p in parts]
    for p in stripped:
        if not _DIGITS.fullmatch(p):
            raise ValueError(f"not a plain integer: {_short_repr(p)}")
    left, top, right, bottom = (int(p) for p in stripped)
    return _validate((left, top, right, bottom))


def resolve(mode: str) -> Optional[tuple[int, int, int, int]]:
    """Resolve a minimap bbox for the given mode.

    Order: persisted -> hardcoded fallback. Returns None when the mode is
    unsupported (e.g. arena) or not a string - the caller should map that
    to HTTP 404. The mode is matched case-insensitively, ignoring
    surrounding whitespace.

    Caller-side `?bbox=` overrides are NOT consulted here; the HTTP route
    parses and validates those before calling this resolver.
    """
    if not isinstance(mode, str):
        return None
    mode = mode.strip().lower()
    if mode not in _HARDCODED_FALLBACK:
        return None
    persisted = load_persisted(mode)
    if persisted is not None:
        return persisted
    return _HARDCODED_FALLBACK[mode]
