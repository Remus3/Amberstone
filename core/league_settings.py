"""Reader for League of Legends' local game.cfg HUD settings.

The single source of truth for the on-screen minimap geometry: League stores the
minimap scale + side toggle in `[HUD]` of game.cfg (live-confirmed 2026-06-21:
MinimapScale=1.6200, FlipMiniMap=0), and the native render size in `[General]`.
Reads are LOCAL + free (no API). This module composes the geometry rect for the
overlay; the pure math lives in core.minimap_geometry.

Fail-soft is mandatory: a clean checkout / CI / non-Legion host has no game.cfg,
so every entry point returns None rather than raising. A hand-rolled INI scan
(not configparser) sidesteps interpolation + leading-key edge cases entirely.

Path resolution: explicit arg -> RC_LEAGUE_CONFIG env -> the known Legion path.
ASCII only (repo hard rule).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.minimap_geometry import compute_minimap_rect

# The operator's live config (confirmed 2026-06-21). Overridable via env so a
# non-default install / a test / a peer host can point elsewhere.
_DEFAULT_CFG = r"C:\Riot Games\League of Legends\Config\game.cfg"

# overlay design canvas - widgets are authored in 1920x1080 and the overlay
# body-zoom scales them to the live window (web/js/lib/overlay_layout.js).
_DESIGN_W = 1920
_DESIGN_H = 1080


@dataclass(frozen=True)
class LeagueHudSettings:
    minimap_scale: float
    flip_minimap: bool
    native_w: Optional[int]
    native_h: Optional[int]


def _cfg_path(path: Optional[str]) -> str:
    if path:
        return path
    return os.environ.get("RC_LEAGUE_CONFIG", _DEFAULT_CFG)


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
            # strip an inline comment after the value (game.cfg has none, but
            # be defensive): keep it simple - only trailing ' ;' style.
            sections.setdefault(cur, {})[k.strip()] = v.strip()
    return sections


def read_hud_settings(path: Optional[str] = None) -> Optional[LeagueHudSettings]:
    """Parse [HUD] + [General] from game.cfg. None if absent/unparseable.

    None is also returned when there is no [HUD] section (we cannot ground the
    minimap without it). A present-but-non-numeric MinimapScale degrades to the
    League default 1.0 rather than failing the whole read.
    """
    p = _cfg_path(path)
    try:
        if not Path(p).is_file():
            return None
        raw = Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    sections = _parse_ini(raw)
    hud = sections.get("HUD")
    if not hud:
        return None

    def _flt(section: dict[str, str], key: str, default: float) -> float:
        v = section.get(key)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def _int(name: str) -> Optional[int]:
        v = sections.get("General", {}).get(name)
        if v is None:
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    scale = _flt(hud, "MinimapScale", 1.0)
    flip = str(hud.get("FlipMiniMap", "0")).strip() in ("1", "true", "True")
    return LeagueHudSettings(
        minimap_scale=scale,
        flip_minimap=flip,
        native_w=_int("Width"),
        native_h=_int("Height"),
    )


def minimap_rect_payload(
    path: Optional[str] = None,
    target_w: int = _DESIGN_W,
    target_h: int = _DESIGN_H,
) -> Optional[dict]:
    """Overlay-facing minimap rect, in design px, for /api/state.

    Returns None when game.cfg is unreadable or the geometry fails its sanity
    check - the overlay then simply does not paint the minimap outline.
    """
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
