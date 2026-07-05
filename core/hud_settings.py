# arch: parse League game.cfg + PersistedSettings for OCR region + color hardening | section=vision | frozen=no
"""Read the live League settings so HUD OCR can be HARDENED against them instead
of hardcoded 1920x1080 pixels + assumed colors.

Two independent layers the settings drive (memory
reference_vision_ocr_capture_pipeline):

  POSITION - resolution + HUD scale + layout toggles decide WHERE each element
  is. Notably ``ShowTeamFramesOnLeft`` (the operator has it 0, which is why the
  ally/enemy portraits sit on the RIGHT), ``MirroredScoreboard``, ``FlipMiniMap``,
  ``MinimapScale``, ``GlobalScale``. These form ``config_key`` so a settings
  change re-selects the right region set rather than silently misreading.

  COLOR - ``ColorBrightness / ColorContrast / ColorGamma / ColorLevel /
  ColorPalette`` (in PersistedSettings.json) shift the rendered frame's colors +
  gamma. When non-default, OCR should inverse-correct the crop before Tesseract,
  and a non-zero ColorPalette (color-blind mode) changes HP/mana bar colors that
  ``core.vision_tesseract._bar_fill_pct`` hard-matches - so bar detection must
  adapt. ``color_correction_needed`` / ``colorblind`` flag that.

The FULL game.cfg (every section) is returned under ``cfg`` so any other
toggle (quality, godray, eye-candy, effects) is available to a correction step.
Lenient parse; missing files -> friendly zeros, never raises.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("rc.vision")

_CFG_DIR = Path(r"C:\Riot Games\League of Legends\Config")
_DEFAULT_GAME_CFG = _CFG_DIR / "game.cfg"
_DEFAULT_PERSISTED = _CFG_DIR / "PersistedSettings.json"

# Settings that MOVE / RESIZE HUD elements -> part of the position signature.
_LAYOUT_KEYS = ("GlobalScale", "ShowTeamFramesOnLeft", "MirroredScoreboard",
                "FlipMiniMap", "MinimapScale")
# Broader OCR-relevant HUD context (surfaced, not part of the key).
_HUD_CONTEXT_KEYS = _LAYOUT_KEYS + (
    "DrawHealthBars", "ShowFPSAndLatency", "ShowPlayerStats",
    "NumericCooldownFormat", "ShowSummonerNames", "ShopScale")
# Color / gamma correction settings (PersistedSettings.json).
_COLOR_KEYS = ("ColorBrightness", "ColorContrast", "ColorGamma",
               "ColorLevel", "ColorPalette")
_COLOR_SLIDER_DEFAULT = 0.5  # neutral midpoint for the 4 sliders (ColorPalette default 0)


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


def _read_persisted_flat(path) -> dict:
    """Flatten PersistedSettings.json (nested files/sections/settings with
    name/value) to {name: value}. {} on any read/parse failure."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except Exception:  # noqa: BLE001
        return {}
    flat: dict = {}

    def _walk(o):
        if isinstance(o, dict):
            name, val = o.get("name"), o.get("value")
            if isinstance(name, str) and val is not None and not isinstance(val, (list, dict)):
                flat.setdefault(name, val)
            for v in o.values():
                if isinstance(v, (list, dict)):
                    _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(d)
    return flat


def _as_int(d: dict, key, default=None):
    try:
        return int(float(d.get(key, default)))
    except (TypeError, ValueError):
        return default


def _as_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def read_hud_settings(game_cfg=None, persisted=None) -> dict:
    """Return the position + color settings that drive HUD OCR:
    ``{ok, width, height, config_key, layout, color, color_correction_needed,
    colorblind, cfg}``."""
    p = Path(game_cfg) if game_cfg is not None else _DEFAULT_GAME_CFG
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "game.cfg not readable", "config_key": "unknown",
                "layout": {}, "color": {}, "color_correction_needed": False,
                "colorblind": False, "cfg": {}}

    cfg = _parse_cfg(text)
    gen = cfg.get("General", {})
    hud = cfg.get("HUD", {})
    width = _as_int(gen, "Width")
    height = _as_int(gen, "Height")
    ok = bool(width and height)

    layout = {k: hud[k] for k in _HUD_CONTEXT_KEYS if k in hud}
    if "RelativeTeamColors" in gen:
        layout["RelativeTeamColors"] = gen["RelativeTeamColors"]

    pflat = _read_persisted_flat(persisted if persisted is not None else _DEFAULT_PERSISTED)
    color = {k: pflat[k] for k in _COLOR_KEYS if k in pflat}

    if ok:
        parts = [f"{width}x{height}"] + [f"{k}={hud.get(k, '?')}" for k in _LAYOUT_KEYS]
        config_key = "|".join(parts)
    else:
        config_key = "unknown"

    needs = False
    for k in ("ColorBrightness", "ColorContrast", "ColorGamma", "ColorLevel"):
        cv = _as_float(color.get(k))
        if cv is not None and abs(cv - _COLOR_SLIDER_DEFAULT) > 0.01:
            needs = True
    palette = _as_int(color, "ColorPalette", 0) or 0
    colorblind = bool(palette)

    return {
        "ok": ok,
        "width": width,
        "height": height,
        "config_key": config_key,
        "layout": layout,
        "color": color,
        "color_correction_needed": needs or colorblind,
        "colorblind": colorblind,
        "cfg": cfg,
    }
