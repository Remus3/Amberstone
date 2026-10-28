"""Reader for League of Legends' local game.cfg HUD settings.

The single source of truth for the on-screen minimap geometry: League stores the
minimap scale + side toggle in `[HUD]` of game.cfg (live-confirmed 2026-06-21:
MinimapScale=1.6200, FlipMiniMap=0), and the native render size in `[General]`.
Reads are LOCAL + free (no API). This module composes the geometry rect for the
overlay; the pure math lives in core.minimap_geometry.

Fail-soft is mandatory: a clean checkout / CI / non-Legion host has no game.cfg,
so every entry point returns None rather than raising. A hand-rolled INI scan
(not configparser) sidesteps interpolation + leading-key edge cases entirely.

Path resolution: explicit arg (str or PathLike) -> RC_LEAGUE_CONFIG env (a
blank value counts as unset, same as core.hud_settings) -> the known Legion
path, read at CALL time.

Hardening (s144 true-audit): the file is read as bytes, capped at
``_MAX_FILE_BYTES`` and decoded through its BOM (UTF-8 or UTF-16; a UTF-8 BOM
used to hide the first section header). A Width / Height outside 1..10000 or
non-finite is not a native size (``inf`` used to raise OverflowError), and a
non-finite MinimapScale degrades to the default 1.0 like any other junk. A
path that is not a str / PathLike, or that the OS cannot take (an embedded
NUL), returns None. A file that is PRESENT but unusable is warned once per
streak, naming the file kind only; a missing file is the normal off-Legion
state and stays silent.
ASCII only (repo hard rule).
"""
from __future__ import annotations

import logging
import math
import os
import stat
import threading
from dataclasses import dataclass
from typing import Optional

from core.minimap_geometry import compute_minimap_rect

log = logging.getLogger(__name__)

# The operator's live config (confirmed 2026-06-21). Overridable via env so a
# non-default install / a test / a peer host can point elsewhere.
_DEFAULT_CFG = r"C:\Riot Games\League of Legends\Config\game.cfg"

# overlay design canvas - widgets are authored in 1920x1080 and the overlay
# body-zoom scales them to the live window (web/js/lib/overlay_layout.js).
_DESIGN_W = 1920
_DESIGN_H = 1080

# A real game.cfg is a few KB; a mis-pointed RC_LEAGUE_CONFIG must not pull a
# huge file into the /api/state build. Same cap as core.hud_settings.
_MAX_FILE_BYTES = 4 * 1024 * 1024
# Native size ceiling, same as core.hud_settings._RES_MAX (checked on the raw
# value, so 10000.5 is not truncated into range).
_RES_MAX = 10000
# Parse-cache entries kept (production reads ONE path; this only bounds a
# process that is handed many).
_CACHE_MAX = 16

_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")

# Warn-once-per-streak state for a present-but-unusable game.cfg: set when the
# degraded state is warned, cleared on the next clean read or a missing file.
# read_hud_settings runs about once a second, so a plain warning would flood.
_WARNED = False
_WARN_LOCK = threading.Lock()


def _warn_once(reason: str) -> None:
    global _WARNED
    with _WARN_LOCK:
        if _WARNED:
            return
        _WARNED = True
    log.warning("game.cfg not usable (%s); overlay minimap outline off", reason)


def _clear_warn() -> None:
    global _WARNED
    with _WARN_LOCK:
        _WARNED = False


def _reset_warnings() -> None:
    """Test hook: forget the warned streak."""
    _clear_warn()


@dataclass(frozen=True)
class LeagueHudSettings:
    minimap_scale: float
    flip_minimap: bool
    native_w: Optional[int]
    native_h: Optional[int]


# Per-resolved-path parse cache for read_hud_settings, keyed on the file's
# (st_mtime_ns, st_size). WHY mtime-guarded and NOT process-lifetime: game.cfg
# is live operator HUD settings, not patch-static - the operator can change
# MinimapScale mid-session, so a lifetime cache would serve a stale minimap. The
# mtime bump on any edit invalidates the entry and forces a fresh parse. Guarded
# by a lock because read_hud_settings runs on the dashboard build_state path
# (concurrent /api/state polls, about once a second). A cached value of None is
# valid (a readable file with no [HUD] section); a transient read error is never
# cached, so a hiccup does not poison the entry.
_CACHE: dict[str, tuple[int, int, Optional[LeagueHudSettings]]] = {}
_CACHE_LOCK = threading.Lock()


def _cfg_path(path) -> Optional[str]:
    """The game.cfg path as a str, or None for an argument that is not a path.

    An int is refused before os.stat sees it (os.stat(3) stats file descriptor
    3), and so are bytes and anything else os.fspath cannot turn into a str.
    """
    if path is None or path == "":
        env = os.environ.get("RC_LEAGUE_CONFIG", "").strip()
        return env or _DEFAULT_CFG
    try:
        p = os.fspath(path)  # TypeError for an int, a float, any non-path
    except TypeError:
        return None
    return p if isinstance(p, str) and p else None


def _decode(data: bytes) -> str:
    """Text of a game.cfg through its BOM: UTF-16 when it opens with a UTF-16
    BOM, else UTF-8 with an optional BOM. Never raises."""
    if data.startswith(_UTF16_BOMS):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def _read_cfg(p: str) -> str:
    """Decoded text of ``p``, read as at most ``_MAX_FILE_BYTES + 1`` bytes.
    Raises OSError when unreadable or over the cap."""
    with open(p, "rb") as fh:
        data = fh.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        raise OSError("over the size cap")
    return _decode(data)


def _parse_ini(raw: str) -> dict[str, dict[str, str]]:
    """Minimal, exception-free INI scanner.

    Keys before the first section land under "". Comments (; or #) and blank
    lines are skipped. No interpolation, no duplicate-key error.
    """
    sections: dict[str, dict[str, str]] = {"": {}}
    cur = ""
    for line in raw.splitlines():
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1].strip()
            sections.setdefault(cur, {})
            continue
        if "=" in s:
            k, _, v = s.partition("=")
            # The value is taken verbatim: game.cfg carries no inline comments,
            # so a trailing ' ; note' stays part of the value (and a numeric
            # key carrying one degrades like any other junk).
            sections.setdefault(cur, {})[k.strip()] = v.strip()
    return sections


def _finite(v: Optional[str]) -> Optional[float]:
    """A finite float from a setting value, else None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _resolution(v: Optional[str]) -> Optional[int]:
    """Width / Height as an int in 1.._RES_MAX, else None."""
    f = _finite(v)
    if f is None or f > _RES_MAX:
        return None
    n = int(f)
    return n if n >= 1 else None


def read_hud_settings(path=None) -> Optional[LeagueHudSettings]:
    """Parse [HUD] + [General] from game.cfg. None if absent/unparseable.

    None is also returned when there is no [HUD] section (we cannot ground the
    minimap without it). A present-but-non-numeric or non-finite MinimapScale
    degrades to the League default 1.0 rather than failing the whole read; a
    junk Width / Height is None for that dimension only.

    The result is cached per resolved path, keyed on the file's (st_mtime_ns,
    st_size); the common file-unchanged call skips the read + INI scan. See the
    _CACHE comment for why the guard is mtime-based, not process-lifetime.
    """
    p = _cfg_path(path)
    if p is None:
        return None
    # os.stat replaces the old is_file() check: a missing file raises OSError
    # here (fail soft -> None) and the S_ISREG guard keeps "regular files only"
    # (a directory / device name yields None BEFORE it is opened, so a CON or
    # COM1 path never blocks the read). ValueError = an embedded NUL.
    try:
        st = os.stat(p)
    except FileNotFoundError:
        _clear_warn()
        return None
    except (OSError, ValueError) as exc:
        _warn_once(type(exc).__name__)
        return None
    if not stat.S_ISREG(st.st_mode):
        _warn_once("not a regular file")
        return None
    if st.st_size > _MAX_FILE_BYTES:
        _warn_once("over the size cap")
        return None

    cache_key = (st.st_mtime_ns, st.st_size)
    with _CACHE_LOCK:
        cached = _CACHE.get(p)
        hit = cached is not None and cached[:2] == cache_key
    if hit:
        _clear_warn()  # a cached clean read ends a warned streak too
        return cached[2]

    try:
        raw = _read_cfg(p)
    except OSError as exc:
        # Transient read error (League holding the file, a size race): fail
        # soft, but do NOT cache (do not poison the entry).
        _warn_once(type(exc).__name__)
        return None
    _clear_warn()

    sections = _parse_ini(raw)
    general = sections.get("General", {})
    hud = sections.get("HUD")
    result: Optional[LeagueHudSettings]
    if not hud:
        result = None
    else:
        scale = _finite(hud.get("MinimapScale"))
        flip = str(hud.get("FlipMiniMap", "0")).strip() in ("1", "true", "True")
        result = LeagueHudSettings(
            minimap_scale=1.0 if scale is None else scale,
            flip_minimap=flip,
            native_w=_resolution(general.get("Width")),
            native_h=_resolution(general.get("Height")),
        )

    with _CACHE_LOCK:
        _CACHE.pop(p, None)
        while _CACHE and len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))  # oldest insertion first
        _CACHE[p] = (st.st_mtime_ns, st.st_size, result)
    return result


def _target(v) -> bool:
    """A usable target size: a finite number in (0, _RES_MAX], not a bool or a
    string (an int too big for a float would overflow the geometry)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        f = float(v)
    except OverflowError:
        return False
    return math.isfinite(f) and 0 < f <= _RES_MAX


def minimap_rect_payload(
    path=None,
    target_w: int = _DESIGN_W,
    target_h: int = _DESIGN_H,
) -> Optional[dict]:
    """Overlay-facing minimap rect, in design px, for /api/state.

    Returns None when game.cfg is unreadable, a target size is not a finite
    positive number, or the geometry fails its sanity check - the overlay then
    simply does not paint the minimap outline.
    """
    if not (_target(target_w) and _target(target_h)):
        return None
    s = read_hud_settings(path)
    if s is None:
        return None
    rect = compute_minimap_rect(s.minimap_scale, s.flip_minimap, target_w, target_h)
    if rect is None:
        return None
    return {
        "x": rect.x,
        "y": rect.y,
        "w": rect.w,
        "h": rect.h,
        "flip": rect.flip,
        "source": "settings",
        "native_w": s.native_w,
        "native_h": s.native_h,
    }
