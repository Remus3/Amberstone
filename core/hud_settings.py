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

Path resolution (same as core.league_settings): explicit ``game_cfg`` ->
``RC_LEAGUE_CONFIG`` env -> the known install path, read at CALL time.
PersistedSettings.json defaults to the sibling of whichever game.cfg was
resolved, so the minimap and the OCR never read two different installs.

Hardening (s144 true-audit): a Width / Height outside 1..10000 (the
core.vision_profiles base ceiling) or non-finite is not a resolution, and a
non-finite or bool color value is not a setting - ``inf`` used to raise
OverflowError, so active_config_key lost the region set AND the color layer.
Both files are read as bytes, capped at ``_MAX_FILE_BYTES`` and decoded
``utf-8-sig`` (a BOM used to hide ``[General]`` and blank the JSON). The
PersistedSettings walk is iterative (json accepts nesting the old recursive
walk could not). A file that is PRESENT but unusable is warned once per streak,
naming the file kind only; a missing file is the normal off-Legion state and
stays silent.
"""
from __future__ import annotations

import json
import logging
import math
import os
import stat
import threading
from pathlib import Path

log = logging.getLogger("rc.vision")

_CFG_DIR = Path(r"C:\Riot Games\League of Legends\Config")
_DEFAULT_GAME_CFG = _CFG_DIR / "game.cfg"
_PERSISTED_NAME = "PersistedSettings.json"
_DEFAULT_PERSISTED = _CFG_DIR / _PERSISTED_NAME

# A real game.cfg is a few KB and PersistedSettings.json well under 1 MiB; a
# mis-pointed RC_LEAGUE_CONFIG must not pull a huge file into every OCR tick.
_MAX_FILE_BYTES = 4 * 1024 * 1024
# Same ceiling as core.vision_profiles._BASE_MAX, checked on the raw value.
_RES_MAX = 10000

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

# Warn-once-per-streak state: a key is added when a degraded state is warned
# and dropped when that file reads clean again. active_config_key runs on every
# OCR tick, so a plain warning would flood the log.
_WARNED: set[str] = set()
_WARN_LOCK = threading.Lock()


def _warn_once(key: str, msg: str, *args) -> None:
    with _WARN_LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    log.warning(msg, *args)


def _clear_warn(key: str) -> None:
    with _WARN_LOCK:
        _WARNED.discard(key)


def _reset_warnings() -> None:
    """Test hook: forget every warned streak."""
    with _WARN_LOCK:
        _WARNED.clear()


def _as_path(v):
    """``Path(v)``, or None for a value that is not a path (int, float, NUL).
    A foreign ``__fspath__`` that raises anything else is a caller bug and
    propagates by design (same ruling as core.relay_age's foreign __float__)."""
    try:
        return Path(v)
    except (TypeError, ValueError):
        return None


def _resolve_paths(game_cfg, persisted):
    """``(game_cfg_path, persisted_path)``; either is None when unusable."""
    if game_cfg is not None:
        g = _as_path(game_cfg)
    else:
        env = os.environ.get("RC_LEAGUE_CONFIG", "").strip()
        g = Path(env) if env else _DEFAULT_GAME_CFG
    if persisted is not None:
        p = _as_path(persisted)
    elif g is None:
        p = None
    else:
        try:
            p = g.with_name(_PERSISTED_NAME)
        except ValueError:  # a name-less path ("", ".", a drive root)
            p = None
    return g, p


def _read_capped(path: Path) -> str:
    """Decoded text of ``path``. Raises FileNotFoundError when absent, OSError
    when unreadable or over ``_MAX_FILE_BYTES``, ValueError for a path the OS
    cannot take (an embedded NUL). Anything but a regular file is refused
    BEFORE it is opened: a device name (``CON``, ``COM1``) given as the path
    or as RC_LEAGUE_CONFIG used to block the OCR tick forever on the read."""
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise OSError("not a regular file")
    with open(path, "rb") as fh:
        data = fh.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        raise OSError(f"over {_MAX_FILE_BYTES} bytes")
    return data.decode("utf-8-sig", errors="ignore")


def _parse_cfg(text: str) -> dict:
    section = None
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            out.setdefault(section, {})
            continue
        if "=" in line and section is not None:
            k, v = line.split("=", 1)
            out[section][k.strip()] = v.strip()
    return out


def _flatten(doc) -> dict:
    """{name: value} for every ``{"name": str, "value": scalar}`` node, first
    seen in document order wins (a node's own pair before its children).
    Iterative, so any nesting json.loads accepts is walked."""
    flat: dict = {}
    stack = [doc]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            name, val = o.get("name"), o.get("value")
            if isinstance(name, str) and val is not None and not isinstance(val, (list, dict)):
                flat.setdefault(name, val)
            stack.extend(v for v in reversed(list(o.values())) if isinstance(v, (list, dict)))
        elif isinstance(o, list):
            stack.extend(v for v in reversed(o) if isinstance(v, (list, dict)))
    return flat


def _read_persisted_flat(path) -> dict:
    """Flatten PersistedSettings.json (nested files/sections/settings with
    name/value) to {name: value}. {} on any read/parse failure; a present but
    unusable file is warned once per streak."""
    key = "persisted"
    p = _as_path(path) if path is not None else None
    if p is None:
        return {}
    try:
        text = _read_capped(p)
    except FileNotFoundError:
        _clear_warn(key)
        return {}
    except (OSError, ValueError) as exc:
        _warn_once(key, "PersistedSettings.json not readable (%s); HUD color layer off",
                   type(exc).__name__)
        return {}
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError) as exc:
        _warn_once(key, "PersistedSettings.json not parseable (%s); HUD color layer off",
                   type(exc).__name__)
        return {}
    _clear_warn(key)
    return _flatten(doc)


def _as_number(v):
    """A finite float from a setting value, else None. A bool is not a number."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _as_int(d: dict, key, default=None):
    f = _as_number(d.get(key, default))
    return int(f) if f is not None else default


def _as_float(v, default=None):
    f = _as_number(v)
    return f if f is not None else default


def _as_resolution(v):
    """Width / Height as an int in 1.._RES_MAX, else None. The ceiling is
    checked on the raw value so 10000.5 is not truncated into range."""
    f = _as_number(v)
    if f is None or f > _RES_MAX:
        return None
    n = int(f)
    return n if n >= 1 else None


def _not_readable(error: str) -> dict:
    return {"ok": False, "error": error, "width": None, "height": None,
            "config_key": "unknown", "layout": {}, "color": {},
            "color_correction_needed": False, "colorblind": False, "cfg": {}}


def read_hud_settings(game_cfg=None, persisted=None) -> dict:
    """Return the position + color settings that drive HUD OCR:
    ``{ok, width, height, config_key, layout, color, color_correction_needed,
    colorblind, cfg}`` (plus ``error`` when game.cfg is not readable)."""
    p, persisted_path = _resolve_paths(game_cfg, persisted)
    if p is None:
        return _not_readable("game.cfg not readable")
    try:
        text = _read_capped(p)
    except FileNotFoundError:
        _clear_warn("game_cfg")
        return _not_readable("game.cfg not readable")
    except (OSError, ValueError) as exc:
        _warn_once("game_cfg", "game.cfg not readable (%s); HUD config_key unknown",
                   type(exc).__name__)
        return _not_readable("game.cfg not readable")

    cfg = _parse_cfg(text)
    gen = cfg.get("General", {})
    hud = cfg.get("HUD", {})
    width = _as_resolution(gen.get("Width"))
    height = _as_resolution(gen.get("Height"))
    ok = width is not None and height is not None
    if ok:
        _clear_warn("game_cfg")
    else:
        _warn_once("game_cfg", "game.cfg has no usable [General] Width/Height; "
                   "HUD config_key unknown")

    layout = {k: hud[k] for k in _HUD_CONTEXT_KEYS if k in hud}
    if "RelativeTeamColors" in gen:
        layout["RelativeTeamColors"] = gen["RelativeTeamColors"]

    pflat = _read_persisted_flat(persisted_path)
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
