# arch: profile-based hot-reloadable OCR region + reference-frame store | section=vision | frozen=no
"""Profile-based, on-the-fly OCR region + native-reference store.

A PROFILE is the set of OCR regions calibrated for one HUD config, keyed by the
settings signature ``core.hud_settings.read_hud_settings()['config_key']``
(resolution + layout toggles like ShowTeamFramesOnLeft). The ACTIVE profile is
resolved LIVE from the current settings every call, so changing resolution / HUD
layout swaps the region set on the fly with no restart - and a save just rewrites
the profile file, which consumers re-read.

``save_reference_image`` / ``capture_reference`` persist a NATIVE full-resolution
frame per profile DURING a game (the vision self-grab arms it), so a single-screen
operator - who only sees the game - can recalibrate against that saved still later.
See memory reference_vision_ocr_capture_pipeline. Everything is fail-soft: the
reference save runs on the grab hot path and must never raise.
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from pathlib import Path
from threading import RLock

log = logging.getLogger("rc.vision")

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
PROFILES_DIR = _DATA / "vision_profiles"
REFERENCE_DIR = _DATA / "vision_calib_reference"
_LEGACY_REGIONS = _DATA / "vision_regions.json"
_LEGACY_BASE = [1920, 1080]

_REF_MIN_INTERVAL_S = 60.0   # throttle auto reference captures on the grab hot path
_last_ref_save = 0.0
_lock = RLock()


def _safe(config_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(config_key))[:120] or "unknown"


def _game_active() -> bool:
    """True when a real game is live (ops/runtime/health.json has_game). Gates
    the auto reference capture so it never saves a lobby / desktop frame."""
    try:
        d = json.loads((_ROOT / "ops" / "runtime" / "health.json").read_text(encoding="utf-8"))
        return bool(d.get("has_game"))
    except Exception:  # noqa: BLE001
        return False


def active_config_key() -> str:
    """The LIVE HUD config signature (re-read each call -> on-the-fly switching)."""
    try:
        from core.hud_settings import read_hud_settings
        return read_hud_settings().get("config_key", "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def profile_path(config_key: str) -> Path:
    return PROFILES_DIR / f"{_safe(config_key)}.json"


def reference_path(config_key: str) -> Path:
    return REFERENCE_DIR / f"{_safe(config_key)}.jpg"


def load_profile(config_key=None) -> dict:
    """Return the active (or given) profile: ``{config_key, base:[w,h],
    regions:{name:[x1,y1,x2,y2]}, source}``. Falls back to seeding from the
    legacy data/vision_regions.json (base 1920x1080) when no profile exists yet."""
    ck = config_key or active_config_key()
    p = profile_path(ck)
    try:
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return {"config_key": ck, "base": d.get("base", _LEGACY_BASE),
                    "regions": d.get("regions", {}), "source": "profile"}
    except Exception:  # noqa: BLE001
        log.debug("profile read failed for %s", ck)
    try:
        regions = json.loads(_LEGACY_REGIONS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        regions = {}
    return {"config_key": ck, "base": list(_LEGACY_BASE),
            "regions": regions, "source": "legacy_seed"}


def save_profile(config_key, regions: dict, base) -> dict:
    """Atomic-write a profile. Returns ``{ok, count, config_key}``. Caller is
    responsible for region validation (routes_vision_calibrator.validate_regions)."""
    ck = config_key or active_config_key()
    try:
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"config_key": ck, "base": list(base), "regions": regions,
                   "saved_ts": None}
        p = profile_path(ck)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
        return {"ok": True, "count": len(regions), "config_key": ck}
    except Exception as exc:  # noqa: BLE001
        log.warning("profile save failed for %s: %s", ck, exc)
        return {"ok": False, "count": 0, "config_key": ck}


def save_reference_image(img, config_key=None, force: bool = False) -> bool:
    """Persist an already-grabbed PIL image as this profile's native reference,
    throttled. Called from the grab hot path - never raises, returns False on
    skip/failure."""
    global _last_ref_save
    now = time.time()
    if not force:
        with _lock:
            if (now - _last_ref_save) < _REF_MIN_INTERVAL_S:
                return False
        if not _game_active():   # only persist in-game references, not lobby/desktop
            return False
    try:
        ck = config_key or active_config_key()
        REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        p = reference_path(ck)
        tmp = p.with_name(p.name + ".tmp")
        img.convert("RGB").save(tmp, format="JPEG", quality=92, optimize=True)
        tmp.replace(p)
        meta = {"config_key": ck, "width": img.width, "height": img.height, "ts": now}
        mp = p.with_suffix(".json")
        mtmp = mp.with_name(mp.name + ".tmp")
        mtmp.write_text(json.dumps(meta), encoding="utf-8")
        mtmp.replace(mp)
        with _lock:
            _last_ref_save = now
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("reference save failed: %s", exc)
        return False


def capture_reference(config_key=None, _grabber=None) -> dict:
    """Grab a FRESH native frame now + save it as the profile reference (force).
    Returns ``{ok, config_key, width, height}``."""
    try:
        if _grabber is None:
            from PIL import ImageGrab
            _grabber = ImageGrab.grab
        img = _grabber()
        if img is None:
            return {"ok": False, "error": "grab returned no image"}
        ck = config_key or active_config_key()
        ok = save_reference_image(img, config_key=ck, force=True)
        return {"ok": ok, "config_key": ck, "width": img.width, "height": img.height}
    except Exception as exc:  # noqa: BLE001
        log.debug("capture_reference failed: %s", exc)
        return {"ok": False, "error": "capture failed"}


def load_reference(config_key=None) -> dict:
    """Load the saved native reference for the active (or given) profile as
    ``{ok, b64, width, height, age_s, config_key}`` or ``{ok: False}``."""
    import base64
    ck = config_key or active_config_key()
    p = reference_path(ck)
    try:
        raw = p.read_bytes()
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "no reference captured yet", "config_key": ck}
    meta = {}
    try:
        meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "b64": base64.b64encode(raw).decode("ascii"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "age_s": round(time.time() - float(meta.get("ts", 0) or 0), 1),
        "config_key": ck,
        "format": "jpeg",
    }
