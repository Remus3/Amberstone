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
    """The LIVE HUD config signature (re-read each call -> on-the-fly switching).

    Also installs the live HUD color layer (colorblind palette + gamma/brightness/
    contrast) into core.vision_tesseract each call (R95), so bar detection + OCR
    preprocessing adapt to the same settings that drive region selection. Additive
    + fail-soft (the except returns "unknown")."""
    try:
        from core.hud_settings import read_hud_settings
        from core.vision_tesseract import configure_hud_color
        h = read_hud_settings()
        configure_hud_color(h)
        return h.get("config_key", "unknown")
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


_RES_KEY_RE = re.compile(r"^(\d{1,5})x(\d{1,5})$")


def _res_key(width, height):
    """``"WxH"`` for a valid base, else None (shares validate_base's limits)."""
    ok, _err, clean = validate_base([width, height])
    if not ok:
        return None
    return f"{clean[0]}x{clean[1]}"


def _resolution_key_from_config_key(config_key):
    """The resolution-only key implied by a config_key STRING, or None.

    Format proved from core/hud_settings.py:133-134 - read_hud_settings builds
    ``config_key = "|".join([f"{width}x{height}"] + layout parts)``, so the
    leading pipe-delimited token is always ``WxH``. Anything else (notably the
    ``"unknown"`` sentinel at hud_settings.py:136) yields None."""
    head = str(config_key or "").split("|", 1)[0].strip()
    m = _RES_KEY_RE.match(head)
    if not m:
        return None
    return _res_key(int(m.group(1)), int(m.group(2)))


def _live_resolution_key():
    """The resolution-only key from the LIVE settings, or None. Preferred over
    the string parse because ``read_hud_settings`` exposes real integer
    ``width`` / ``height`` fields (core/hud_settings.py:121-122, 148-149) rather
    than a formatted key. Fail-soft: never raises."""
    try:
        from core.hud_settings import read_hud_settings
        h = read_hud_settings()
        if not h.get("ok"):
            return None
        return _res_key(h.get("width"), h.get("height"))
    except Exception:  # noqa: BLE001
        return None


def load_profile(config_key=None) -> dict:
    """Return the active (or given) profile: ``{config_key, base:[w,h],
    regions:{name:[x1,y1,x2,y2]}, source}``, resolved in three tiers:

      1. ``"profile"`` - the exact profile file for this full config_key (a
         real calibration for this resolution AND HUD toggle set).
      2. ``"resolution_seed"`` - the resolution-only profile file keyed
         ``"WxH"``, which is how ``seed_profiles`` writes the shipped seeds.
         A live config_key carries the HUD toggles too (see
         core/hud_settings.py:133-134), so without this tier a seeded machine
         never matched its own seed and fell to tier 3. The resolution is taken
         from the live ``read_hud_settings`` width/height when available and
         from the key's leading ``WxH`` token otherwise; the response also
         carries ``resolution_key`` and ``seed_origin`` (``"file"``).
      2b. ``"resolution_seed"`` with ``seed_origin == "derived"`` - no seed
         FILE exists but the live base is in ``SEED_BASES``, so the same
         rectangles are derived in memory. ``seed_profiles()`` has no
         production caller and data/vision_profiles/ is gitignored +
         per-machine, so without this an ultrawide first run still cropped
         unscaled 1080p boxes even though tier 2 existed. Read-only: no disk
         write on the lookup path.
      3. ``"legacy_seed"`` - the hand-calibrated data/vision_regions.json at
         base 1920x1080, the last resort. Reached for 1920x1080 itself (the
         authoring base is deliberately NOT in ``SEED_BASES``) and for any
         resolution nobody seeded.

    PRECEDENCE, which must never invert: a PARSEABLE tier 1 is a real
    calibration and always wins; a seed - file or derived - is only ever
    consulted when no readable exact profile exists. A seeded approximation
    shadowing a calibrated profile would be strictly worse than falling
    through to legacy. Note the qualifier: an unparseable or zero-byte tier-1
    file is treated as ABSENT and falls through to the seed (the pre-tier-2b
    code did the same, falling through to a tier-2 seed FILE), so the rule is
    about a readable profile, not about the path existing.

    NOTE ON WHAT A SEED CHANGES. It does NOT move any OCR crop rectangle.
    core.vision_tesseract._scale_bbox already rescales by frame / _BASE_CACHE,
    so 1080p boxes at base [1920,1080] and W/1920-prescaled boxes at base
    [W,H] produce byte-identical crops (measured: 0 of 21 regions differ at
    native and half-frame; 1 px on a 1920x1080 downscale, from double int()
    truncation). What it changes is the reported BASE, which is what
    ingest_reference_from_path validates an operator still against - that is
    the real effect. Do not read a seed as a cropping fix.

    KNOWN LIMIT of tier 2: a seed is a proportional scale of the 1080p
    baseline, and League edge-anchors much of its HUD instead of stretching it.
    The 16:9 2560x1440 seed is therefore materially more accurate than the 21:9
    (2560x1080 / 3440x1440 / 3840x1600) and 32:9 (5120x1440) seeds, whose boxes
    are stretched horizontally away from the real anchored elements. Tier 2 is
    a plausible STARTING POINT for a calibration pass, NOT parity across aspect
    ratios - an ultrawide profile still needs a live tuning pass before the OCR
    path should trust its boxes."""
    ck = config_key or active_config_key()
    p = profile_path(ck)
    try:
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return {"config_key": ck, "base": d.get("base", _LEGACY_BASE),
                    "regions": d.get("regions", {}), "source": "profile"}
    except Exception:  # noqa: BLE001
        log.debug("profile read failed for %s", ck)
    res_ck = _live_resolution_key() if config_key is None else None
    if res_ck is None:
        res_ck = _resolution_key_from_config_key(ck)
    if res_ck and res_ck != ck:
        rp = profile_path(res_ck)
        try:
            if rp.exists():
                d = json.loads(rp.read_text(encoding="utf-8"))
                return {"config_key": ck, "base": d.get("base", _LEGACY_BASE),
                        "regions": d.get("regions", {}),
                        "source": "resolution_seed", "resolution_key": res_ck,
                        "seed_origin": "file"}
        except Exception:  # noqa: BLE001
            log.debug("resolution seed read failed for %s", res_ck)
        # Tier 2b: no seed FILE, but this base is one we ship a seed for.
        # seed_profiles() has no production caller and data/vision_profiles/ is
        # gitignored + per-machine, so tier 2 would otherwise find nothing on a
        # fresh machine and an ultrawide first run would still crop unscaled
        # 1080p boxes. Derive the same rectangles in memory instead - identical
        # arithmetic to the generator, no disk write, no hot-path I/O.
        try:
            if [int(res_ck.split("x")[0]), int(res_ck.split("x")[1])] in SEED_BASES:
                prof = derive_profile([int(res_ck.split("x")[0]),
                                       int(res_ck.split("x")[1])],
                                      config_key=res_ck)
                return {"config_key": ck, "base": prof["base"],
                        "regions": prof["regions"],
                        "source": "resolution_seed", "resolution_key": res_ck,
                        "seed_origin": "derived"}
        except Exception:  # noqa: BLE001
            log.debug("resolution seed derive failed for %s", res_ck)
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


# Per-region anchor classification for the RM-26 anchor model.
#
# THIS IS A MODEL, NOT A MEASUREMENT. It states where League pins each HUD
# element. It CANNOT be validated on this machine: at 16:9 the width ratio
# equals the height ratio, so left / center / right all yield the identical
# box, and every reference still in data/vision_calib_reference is 2560x1440.
# One native full-screen 21:9 or 32:9 capture is the only thing that can
# confirm or refute any row below. Until then the model is DEFAULT-OFF.
REGION_ANCHORS = {
    # Top-right info bar. League pins this cluster to the top-right corner.
    "timer": ("right", "top"),
    "kda": ("right", "top"),
    "cs": ("right", "top"),
    "ping": ("right", "top"),
    "fps": ("right", "top"),
    "score_blue": ("right", "top"),
    "score_red": ("right", "top"),
    # Bottom-centre champion frame. Centred on the screen midline.
    "level": ("center", "bottom"),
    "hp": ("center", "bottom"),
    "mana": ("center", "bottom"),
    "gold": ("center", "bottom"),
    # Left ally team frames. Pinned to the left edge.
    "ally_1_hp": ("left", "top"),
    "ally_2_hp": ("left", "top"),
    "ally_3_hp": ("left", "top"),
    "ally_4_hp": ("left", "top"),
    "ally_1_mana": ("left", "top"),
    "ally_2_mana": ("left", "top"),
    "ally_3_mana": ("left", "top"),
    "ally_4_mana": ("left", "top"),
    "ally_ults": ("left", "top"),
    "ally_levels": ("left", "top"),
}


def classify_anchor(name, box, src_base) -> tuple:
    """Return ``(horizontal, vertical)`` for a region.

    Prefers the explicit REGION_ANCHORS entry. Falls back to geometric thirds
    over ``src_base`` so a region added to the JSON without a registry entry
    still derives instead of raising."""
    known = REGION_ANCHORS.get(name)
    if known:
        return known
    try:
        src_w, src_h = int(src_base[0]), int(src_base[1])
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
    except Exception:  # noqa: BLE001
        return ("left", "top")
    if cx < src_w / 3.0:
        horiz = "left"
    elif cx > src_w * 2.0 / 3.0:
        horiz = "right"
    else:
        horiz = "center"
    return (horiz, "top" if cy < src_h / 2.0 else "bottom")


def _anchor_x(x, horiz, s, src_w, dst_w) -> int:
    if horiz == "right":
        return int(dst_w - (src_w - x) * s)
    if horiz == "center":
        return int(dst_w / 2.0 + (x - src_w / 2.0) * s)
    return int(x * s)


def _anchor_y(y, vert, s, src_h, dst_h) -> int:
    # NOTE: under scale-by-height these two branches are the SAME map -
    # dst_h - (src_h - y) * (dst_h/src_h) reduces to y * (dst_h/src_h). The
    # branch is kept because it documents intent and would diverge under any
    # future non-height-based vertical scale. A test pins the equivalence so
    # nobody "discovers" it as a bug.
    if vert == "bottom":
        return int(dst_h - (src_h - y) * s)
    return int(y * s)


def derive_anchored_regions(regions: dict, src_base, dst_base,
                            anchors=None) -> dict:
    """Scale a region map by HEIGHT and re-anchor each box to its own screen
    edge, instead of stretching it by one ratio per axis.

    WHY: League scales HUD art by screen height and anchors most of it to an
    edge, so proportional width scaling over-stretches every box on an
    ultrawide. Measured best-anchor error vs each region's own true width:
    16:9 2560x1440 exactly 0.00x, 21:9 median 0.45x max ~4.9x, 32:9
    5120x1440 median 1.32x max 14.19x (LEDGER 1227).

    IDENTITY AT MATCHING ASPECT: when dst_w/src_w == dst_h/src_h every anchor
    class collapses to ``x * s``, so this is byte-identical to
    derive_scaled_regions on any same-aspect base. That is also why no 16:9
    frame can validate the CLASSIFICATION - the model is unverified until a
    native 21:9 or 32:9 still exists, which is why derive_profile still
    defaults to the proportional path.

    Returns a NEW dict, never mutates the input; a box that is not a list /
    tuple of length 4 is skipped, matching derive_scaled_regions."""
    src_w, src_h = int(src_base[0]), int(src_base[1])
    dst_w, dst_h = int(dst_base[0]), int(dst_base[1])
    s = dst_h / src_h
    out = {}
    for name, box in regions.items():
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        if anchors is not None and name in anchors:
            horiz, vert = anchors[name]
        else:
            horiz, vert = classify_anchor(name, box, (src_w, src_h))
        l, t, r, b = box
        out[name] = [
            _anchor_x(l, horiz, s, src_w, dst_w),
            _anchor_y(t, vert, s, src_h, dst_h),
            _anchor_x(r, horiz, s, src_w, dst_w),
            _anchor_y(b, vert, s, src_h, dst_h),
        ]
    return out


def derive_profile(dst_base, config_key=None, source_regions=None,
                   source_base=None, anchor_model: bool = False) -> dict:
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
    if anchor_model:
        regions = derive_anchored_regions(src_regions, src_base, clean)
        source = "derived_anchored"
    else:
        regions = derive_scaled_regions(src_regions, src_base, clean)
        source = "derived"
    ck = config_key or f"{clean[0]}x{clean[1]}"
    return {"config_key": ck, "base": [clean[0], clean[1]],
            "regions": regions, "source": source}


# Seed targets: the 1440p + ultrawide bases worth shipping an untuned starting
# profile for. The 1920x1080 authoring base is deliberately ABSENT - it is the
# SOURCE (data/vision_regions.json), and seeding it would be an identity write
# that could only ever clobber the operator's hand calibration.
SEED_BASES = [
    [2560, 1440],   # 16:9  1440p
    [2560, 1080],   # 21:9  ultrawide 1080p
    [3440, 1440],   # 21:9  ultrawide 1440p
    [3840, 1600],   # 21:9  ultrawide 1600p
    [5120, 1440],   # 32:9  super ultrawide
]


def seed_profiles(bases=None, force: bool = False) -> dict:
    """Derive + persist an untuned SEED profile per base from the 1920x1080
    baseline. Returns ``{ok, written, skipped, written_keys, skipped_keys,
    errors}``.

    A seed is a STARTING POINT, not a calibration. Boxes are pure proportional
    scales of the hand-calibrated 1080p baseline, which is right for the 16:9
    bases and only approximate on ultrawide - League anchors much of the HUD to
    the screen edges rather than stretching it, so the ultrawide boxes still
    need a live tuning pass before the OCR path should trust them. Seeding
    exists so that first pass starts from plausible rectangles instead of
    unscaled 1080p ones.

    ADDITIVE by default: a base whose profile file already exists is SKIPPED,
    never overwritten, so this is safe to re-run and can never destroy a tuned
    profile. ``force=True`` rewrites (calibration-reset path only). Writes go
    through save_profile, which is atomic. Never raises.
    """
    targets = SEED_BASES if bases is None else bases
    src_regions = _load_legacy_regions()
    written, skipped, errors = [], [], []
    for base in targets:
        ok, err, clean = validate_base(base)
        if not ok:
            errors.append({"base": base, "error": err})
            continue
        ck = f"{clean[0]}x{clean[1]}"
        try:
            if not force and profile_path(ck).exists():
                skipped.append(ck)
                continue
            prof = derive_profile(clean, config_key=ck,
                                  source_regions=src_regions)
            res = save_profile(ck, prof["regions"], prof["base"])
            if res.get("ok"):
                written.append(ck)
            else:
                errors.append({"base": base, "error": "save failed"})
        except Exception as exc:  # noqa: BLE001
            log.warning("seed failed for %s: %s", ck, exc)
            errors.append({"base": base, "error": "seed failed"})
    return {"ok": not errors, "written": len(written), "skipped": len(skipped),
            "written_keys": written, "skipped_keys": skipped, "errors": errors}
