# arch: parse League game.cfg HUD/resolution settings for region hardening | section=vision | frozen=no
"""Read the live League ``game.cfg`` so OCR region positions can be HARDENED
against the actual in-game settings (resolution + HUD scale + layout) instead of
hardcoded 1920x1080 pixels.

Root cause this addresses (memory reference_vision_ocr_capture_pipeline): the
operator plays 2560x1440 with a custom HUD, so 1920-calibrated boxes miss. The
durable fix is to key region sets by the settings that actually move the HUD -
resolution + GlobalScale + flip flags - so a config change re-selects the right
boxes rather than silently misreading. This module is the settings reader; the
per-config region scaffold + multi-resolution fill is a later session.

Lenient INI-ish parse (League's game.cfg is ``[Section]`` + ``key=value`` with
no spaces around ``=``). Missing file / section -> ``{"ok": False}``; never raises.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("rc.vision")

_DEFAULT_GAME_CFG = Path(r"C:\Riot Games\League of Legends\Config\game.cfg")

# HUD keys worth recording for a config signature (the ones that move / rescale
# HUD elements). Extend as the multi-config scaffold needs more.
_HUD_KEYS = ("GlobalScale", "FlipMiniMap", "MinimapScale", "ShopScale",
             "ShowAllChampsOnMinimap", "MinimapNeutralJungleColor")


def _parse_cfg(text: str) -> dict:
    section = None
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.setdefault(section, {})
            continue
        if "=" in line and section is not None:
            k, v = line.split("=", 1)
            out[section][k.strip()] = v.strip()
    return out


def _as_int(d: dict, key, default=None):
    try:
        return int(float(d.get(key, default)))
    except (TypeError, ValueError):
        return default


def _as_float(d: dict, key, default=None):
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


def read_hud_settings(path=None) -> dict:
    """Return the settings that determine HUD element placement:
    ``{"ok", "width", "height", "global_scale", "flip_minimap", "hud",
    "config_key"}``. ``config_key`` is a stable string signature of the
    placement-affecting settings, used to key per-config region sets."""
    p = Path(path) if path is not None else _DEFAULT_GAME_CFG
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "game.cfg not readable", "config_key": "unknown"}
    cfg = _parse_cfg(text)
    gen = cfg.get("General", {})
    hud = cfg.get("HUD", {})
    width = _as_int(gen, "Width")
    height = _as_int(gen, "Height")
    scale = _as_float(hud, "GlobalScale")
    flip = _as_int(hud, "FlipMiniMap")
    hud_sel = {k: hud[k] for k in _HUD_KEYS if k in hud}
    ok = bool(width and height)
    config_key = f"{width}x{height}@scale{scale}@flip{flip}" if ok else "unknown"
    return {
        "ok": ok,
        "width": width,
        "height": height,
        "global_scale": scale,
        "flip_minimap": flip,
        "hud": hud_sel,
        "config_key": config_key,
    }
