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

log = logging.getLogger("rc.vision")

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
PROFILES_DIR = _DATA / "vision_profiles"
REFERENCE_DIR = _DATA / "vision_calib_reference"
_LEGACY_REGIONS = _DATA / "vision_regions.json"
_LEGACY_BASE = [1920, 1080]

_LEAGUE_EXE = "league of legends.exe"   # foreground process gate (case-insensitive)


def _safe(config_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(config_key))[:120] or "unknown"


_BASE_MAX = 10000


def validate_base(base):
    """Validate a profile base [width, height]. Returns (ok, err, clean).
    Rejects None, wrong length, non-numeric, non-positive, or huge."""
    if not isinstance(base, (list, tuple)) or len(base) != 2:
        return (False, "base must be [width, height]", None)
    coords = []
    for c in base:
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            return (False, "base coordinates must be numbers", None)
        v = int(c)
        if v <= 0 or v > _BASE_MAX:
            return (False, "base out of range", None)
        coords.append(v)
    return (True, None, coords)


def _game_active() -> bool:
    """True when a real game is live (ops/runtime/health.json has_game). Gates
    the auto reference capture so it never saves a lobby / desktop frame."""
    try:
        d = json.loads((_ROOT / "ops" / "runtime" / "health.json").read_text(encoding="utf-8"))
        return bool(d.get("has_game"))
    except Exception:  # noqa: BLE001
        return False


def _league_is_foreground() -> bool:
    """True iff the current Windows foreground window belongs to
    ``League of Legends.exe``. Gates the auto base-reference grab so an alt-tab
    (has_game still True, but the desktop is focused) cannot clobber the
    calibrated base still with a desktop frame. Fail-soft: returns False on any
    error or on a non-Windows / headless host (never raises). Injectable seam -
    tests monkeypatch this function directly."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        # PROCESS_QUERY_LIMITED_INFORMATION (0x1000) - available without full
        # rights and enough for QueryFullProcessImageNameW.
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return False
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(
                    h, 0, buf, ctypes.byref(size)):
                return False
            name = buf.value.rsplit("\\", 1)[-1].lower()
            return name == _LEAGUE_EXE
        finally:
            kernel32.CloseHandle(h)
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


def reference_path(config_key: str, state=None) -> Path:
    """Reference-still path for a config. ``state`` in {None,"","base"} keeps the
    backward-compatible ``<safe(ck)>.jpg`` (byte-for-byte the old 1-arg path);
    any other label yields ``<safe(ck)>__<safe(state)>.jpg`` (a named state)."""
    if state in (None, "", "base"):
        return REFERENCE_DIR / f"{_safe(config_key)}.jpg"
    return REFERENCE_DIR / f"{_safe(config_key)}__{_safe(state)}.jpg"


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


def save_reference_image(img, config_key=None, force: bool = False, state=None) -> bool:
    """Persist an already-grabbed PIL image as this profile's native reference.
    ``state`` selects a named reference file (None/base = the legacy base still).
    Called from the grab hot path - never raises, returns False on skip/failure.

    AUTO path (``force=False``) saves ONCE PER CONFIG and only when it is safe:
    (a) a real game is live (``_game_active`` / health.json has_game), AND
    (b) League is the Windows foreground window (``_league_is_foreground``), so an
        alt-tab to the desktop cannot clobber the calibrated base, AND
    (c) no reference file exists yet for this config_key + state.
    Condition (c) retires the old 60s re-grab cadence - a settings change mints a
    NEW config_key with no reference, which re-triggers a single foreground-gated
    grab. ``force=True`` (capture_reference / the manual refresh path) bypasses all
    three and always overwrites."""
    now = time.time()
    try:
        ck = config_key or active_config_key()
    except Exception:  # noqa: BLE001
        return False
    if not force:
        # only persist in-game references, not a lobby / desktop frame
        if not _game_active():
            return False
        # only while League actually holds foreground (alt-tab clobber guard)
        if not _league_is_foreground():
            return False
        # once per config: never re-grab over an existing reference
        try:
            if reference_path(ck, state).exists():
                return False
        except Exception:  # noqa: BLE001
            return False
    try:
        REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        p = reference_path(ck, state)
        tmp = p.with_name(p.name + ".tmp")
        img.convert("RGB").save(tmp, format="JPEG", quality=92, optimize=True)
        tmp.replace(p)
        meta = {"config_key": ck, "width": img.width, "height": img.height,
                "ts": now, "state": state or "base"}
        mp = p.with_suffix(".json")
        mtmp = mp.with_name(mp.name + ".tmp")
        mtmp.write_text(json.dumps(meta), encoding="utf-8")
        mtmp.replace(mp)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("reference save failed: %s", exc)
        return False


def capture_reference(config_key=None, _grabber=None, state=None) -> dict:
    """Grab a FRESH native frame now + save it as the profile reference (force).
    ``state`` selects a named reference file (None/base = the legacy base still).
    Returns ``{ok, config_key, width, height}``."""
    try:
        if _grabber is None:
            from PIL import ImageGrab
            _grabber = ImageGrab.grab
        img = _grabber()
        if img is None:
            return {"ok": False, "error": "grab returned no image"}
        ck = config_key or active_config_key()
        ok = save_reference_image(img, config_key=ck, force=True, state=state)
        return {"ok": ok, "config_key": ck, "width": img.width, "height": img.height}
    except Exception as exc:  # noqa: BLE001
        log.debug("capture_reference failed: %s", exc)
        return {"ok": False, "error": "capture failed"}


def load_reference(config_key=None, state=None) -> dict:
    """Load the saved native reference for the active (or given) profile as
    ``{ok, b64, width, height, age_s, config_key}`` or ``{ok: False}``. ``state``
    selects a named reference file (None/base = the legacy base still)."""
    import base64
    ck = config_key or active_config_key()
    p = reference_path(ck, state)
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


def list_reference_states(config_key=None) -> list:
    """Sorted list of reference state names present for the active (or given)
    config: always ``"base"`` when the base still exists, plus each ingested
    ``<safe(ck)>__<state>.jpg`` (state parsed back off the filename). Returns
    ``[]`` when none exist. Fail-soft - never raises."""
    ck = config_key or active_config_key()
    states = []
    try:
        safe = _safe(ck)
        if (REFERENCE_DIR / f"{safe}.jpg").exists():
            states.append("base")
        prefix = f"{safe}__"
        for f in REFERENCE_DIR.glob(f"{safe}__*.jpg"):
            name = f.name[:-len(".jpg")]
            if name.startswith(prefix):
                st = name[len(prefix):]
                if st and st != "base":
                    states.append(st)
    except Exception:  # noqa: BLE001
        return sorted(set(states))
    return sorted(set(states))


def ingest_reference_from_path(src_path, state, config_key=None) -> dict:
    """Ingest an operator-provided full-screen native screenshot as a NAMED
    reference state. ``state`` must be a non-empty label other than ``base``
    (base is the auto-grab). The image must match the profile base dims exactly
    (prevents silent miscalibration). Returns ``{ok, width, height, state,
    config_key}`` on success or ``{ok: False, error}``."""
    from PIL import Image
    st = (state or "").strip()
    if not st or st == "base":
        return {"ok": False,
                "error": "state must be a non-empty label other than base"}
    try:
        img = Image.open(src_path).convert("RGB")
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "cannot read image at that path"}
    ck = config_key or active_config_key()
    base = load_profile(ck).get("base", list(_LEGACY_BASE))
    exp_w = base[0] if base else _LEGACY_BASE[0]
    exp_h = base[1] if base and len(base) > 1 else _LEGACY_BASE[1]
    if (img.width, img.height) != (exp_w, exp_h):
        return {"ok": False,
                "error": (f"image is {img.width}x{img.height} but the profile "
                          f"base is {exp_w}x{exp_h} - a full-screen native "
                          f"capture at base resolution is required"),
                "width": img.width, "height": img.height}
    save_reference_image(img, config_key=ck, state=st, force=True)
    return {"ok": True, "width": img.width, "height": img.height,
            "state": st, "config_key": ck}


def _load_legacy_regions() -> dict:
    """The operator's hand-calibrated 1920x1080 baseline regions read from the
    legacy data/vision_regions.json. Fail-soft: returns {} on any read / parse
    error so a derive call never raises on a missing or malformed baseline."""
    try:
        return json.loads(_LEGACY_REGIONS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def derive_scaled_regions(regions: dict, src_base, dst_base) -> dict:
    """Resolution-scale a region map from src_base to dst_base.

    WHY: byte-exact with core.vision_tesseract._scale_bbox so a derived
    native-base profile crops the identical rectangle the crop-time scaler
    produces for a native frame, persisted at the true base so there is no
    downscale drift. One ratio per axis, the same int() truncation toward zero.
    Returns a NEW dict and never mutates the input; an entry whose box is not a
    list / tuple of length 4 is skipped."""
    sx = int(dst_base[0]) / int(src_base[0])
    sy = int(dst_base[1]) / int(src_base[1])
    out = {}
    for name, box in regions.items():
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        l, t, r, b = box
        out[name] = [int(l * sx), int(t * sy), int(r * sx), int(b * sy)]
    return out


def derive_profile(dst_base, config_key=None, source_regions=None,
                   source_base=None) -> dict:
    """Pure derivation of a full profile dict at dst_base from a source region
    map (defaults to the legacy 1920x1080 baseline). No disk write.

    Scales every region via derive_scaled_regions (byte-exact with the live
    crop-time _scale_bbox), so persisting the result yields a native-base
    profile with no downscale drift. Raises ValueError on an invalid dst_base."""
    ok, err, clean = validate_base(dst_base)
    if not ok:
        raise ValueError(err)
    if source_regions is not None:
        src_regions = source_regions
    else:
        src_regions = _load_legacy_regions()
    src_base = source_base if source_base is not None else list(_LEGACY_BASE)
    regions = derive_scaled_regions(src_regions, src_base, clean)
    ck = config_key or f"{clean[0]}x{clean[1]}"
    return {"config_key": ck, "base": [clean[0], clean[1]],
            "regions": regions, "source": "derived"}
