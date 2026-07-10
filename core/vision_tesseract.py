# arch: OCR pipeline (Tesseract) | section=vision | frozen=no
"""
core/vision_tesseract.py - Local Tesseract OCR for cheap League fields.

Replaces Sonnet vision for fields that are just numbers or fixed-format text
(gold, HP, mana, level, timer, CS, KDA). Drops latency from ~2s+cost to
~50ms+free per field. Sonnet still handles full-scene understanding.

Region bboxes live in data/vision_regions.json (created on first read from
defaults). Edit that file to recalibrate without code changes; call
reload_regions() to pick up edits live.

Usage from coaches:
    from core.vision_tesseract import read_fast_fields
    fields = read_fast_fields(latest_frame_b64, fields=["gold", "level", "timer"])
    # -> {"gold": 1542, "level": 11, "timer": "14:38"}
"""
import base64
import io
import json
import logging
import os.path
from pathlib import Path
from typing import Iterable, Optional

_log = logging.getLogger("rc.vision_tesseract")
_APP_DIR = Path(__file__).parent.parent

_TESSERACT_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# Optional env override for a non-default Tesseract install (portability;
# refactor-plan P4.2). When set, RC_TESSERACT_CMD is tried before the
# hardcoded default so a clean-machine / bundled install can point at its own
# binary with no code edit. Unset -> behavior is unchanged.
_TESSERACT_ENV = "RC_TESSERACT_CMD"
_REGIONS_FILE = _APP_DIR / "data" / "vision_regions.json"

# Hard ceiling on a single tesseract.exe invocation (deep-audit P2-W1-E,
# 2026-06-11). pytesseract's default timeout=0 waits on the child process
# UNBOUNDED; one hung tesseract.exe would pin a read_fast_fields pool
# thread forever and they accumulate across coach ticks. On expiry
# pytesseract kills the child and raises RuntimeError, which the existing
# per-field except paths absorb (field omitted for that tick). Normal OCR
# is ~50ms; 10s is a generous loaded-box margin, not a tuning knob.
_TESS_TIMEOUT_S = 10.0

# AUDIT 2026-04-28 (proposal 1.6): regions are calibrated against this base
# resolution; bboxes scale proportionally for any other detected frame size.
# Override per-deployment by adding a top-level `_base: [W, H]` entry in
# data/vision_regions.json (e.g., for an ultrawide-native calibration).
BASE_W, BASE_H = 1920, 1080

# Best-guess defaults for League at 1920x1080 borderless.
# CALIBRATE against a real in-game frame and persist to vision_regions.json.
# Format: [left, top, right, bottom]
_DEFAULT_REGIONS = {
    "timer": [905, 0,    1015, 32],     # top center MM:SS
    "level": [754, 1031, 802,  1075],   # bottom-left of portrait
    "hp":    [880, 996,  1100, 1018],   # HP bar text overlay
    "mana":  [880, 1020, 1100, 1042],   # mana bar text overlay
    "gold":  [1380, 1054, 1450, 1078],  # below items
    "cs":    [1700, 705,  1760, 730],   # near minimap top
    "kda":   [1620, 705,  1700, 730],   # near minimap top
}

_REGIONS_CACHE: Optional[dict] = None
_BASE_CACHE: tuple = (BASE_W, BASE_H)


def _regions() -> dict:
    """Load region config from disk, falling back to defaults.

    A top-level `_base: [W, H]` key, if present, declares the resolution
    the bboxes were calibrated against (used by `_scale_bbox` to scale at
    crop time for frames of other sizes). Other underscore-prefixed keys
    are reserved metadata and are stripped from the returned region dict.
    """
    global _REGIONS_CACHE, _BASE_CACHE
    if _REGIONS_CACHE is not None:
        return _REGIONS_CACHE
    # Prefer the ACTIVE per-HUD profile (native-res calibration) when one exists.
    # This wires the profile store (core/vision_profiles) into the OCR hot path so
    # a 2560x1440 native calibration is used at its own base (no 1920->native
    # scaling drift, no halved-frame tiny-text; memory
    # reference_vision_ocr_capture_pipeline). Fail-soft: any error or an empty /
    # legacy-seed profile falls through to the legacy vision_regions.json path.
    try:
        from core.vision_profiles import load_profile
        prof = load_profile()
        regions = prof.get("regions") if isinstance(prof, dict) else None
        if prof.get("source") == "profile" and regions:
            base = prof.get("base") or [BASE_W, BASE_H]
            _BASE_CACHE = (int(base[0]), int(base[1]))
            _REGIONS_CACHE = {
                k: list(v) for k, v in regions.items()
                if isinstance(v, (list, tuple)) and len(v) == 4
            }
            return _REGIONS_CACHE
    except Exception as exc:  # noqa: BLE001
        _log.debug("vision profile load failed, using legacy regions: %s", exc)
    if _REGIONS_FILE.exists():
        try:
            data = json.loads(_REGIONS_FILE.read_text(encoding="utf-8"))
            base = data.get("_base")
            if isinstance(base, (list, tuple)) and len(base) == 2:
                _BASE_CACHE = (int(base[0]), int(base[1]))
            _REGIONS_CACHE = {
                k: list(v) for k, v in data.items()
                if not k.startswith("_") and isinstance(v, (list, tuple))
            }
        except Exception as exc:  # noqa: BLE001
            _log.warning("vision_regions.json load failed: %s - using defaults", exc)
            _REGIONS_CACHE = dict(_DEFAULT_REGIONS)
            _BASE_CACHE = (BASE_W, BASE_H)
    else:
        _REGIONS_CACHE = dict(_DEFAULT_REGIONS)
        _BASE_CACHE = (BASE_W, BASE_H)
        try:
            # Atomic tmp+replace (deep-audit P2-W1-E): the file is read by
            # other threads/processes (reload_regions, calibration tools);
            # a bare write_text could expose a partial file.
            from core.polled_json import atomic_write_json
            atomic_write_json(_REGIONS_FILE, _REGIONS_CACHE)
        except Exception as exc:  # noqa: BLE001
            _log.debug("vision_regions.json defaults write failed: %s", exc)
    return _REGIONS_CACHE


def _scale_bbox(bbox, frame_w: int, frame_h: int) -> tuple:
    """Scale a bbox calibrated at _BASE_CACHE resolution to the actual
    frame size. No-op when the frame matches the base."""
    base_w, base_h = _BASE_CACHE
    if frame_w == base_w and frame_h == base_h:
        return tuple(bbox)
    sx = frame_w / base_w
    sy = frame_h / base_h
    l, t, r, b = bbox
    return (int(l * sx), int(t * sy), int(r * sx), int(b * sy))


def reload_regions() -> None:
    global _REGIONS_CACHE, _BASE_CACHE
    _REGIONS_CACHE = None
    _BASE_CACHE = (BASE_W, BASE_H)


def _tesseract_candidates() -> list:
    """Ordered tesseract.exe candidates: the ``RC_TESSERACT_CMD`` env override
    first (if set), then the hardcoded default install path."""
    out = []
    env = os.environ.get(_TESSERACT_ENV)
    if env:
        out.append(env)
    out.append(_TESSERACT_DEFAULT)
    return out


def _ensure_tesseract() -> None:
    """Pin pytesseract to a valid tesseract.exe if not already resolvable.

    Resolution order: a cmd already set on pytesseract (PATH) wins; otherwise
    the first existing candidate from ``_tesseract_candidates`` (env override,
    then default) is pinned. A non-default install points at its own binary via
    ``RC_TESSERACT_CMD`` with no code edit (refactor-plan P4.2 portability)."""
    import pytesseract
    cmd = pytesseract.pytesseract.tesseract_cmd
    if cmd and os.path.isfile(cmd):
        return
    for cand in _tesseract_candidates():
        if cand and os.path.isfile(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            return


def _decode_img(img_b64: str):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(img_b64)))


def _crop(img, bbox):
    return img.crop(bbox)


def _color_correct(img):
    """Native-res color-correction: histogram-stretch the grayscale so dim HUD
    glyphs (a native 2560x1440 crop lit by a colored bar or a dark scene behind
    it can leave the white text well under a fixed 180 threshold) are pulled
    toward 255 before binarize. autocontrast is monotonic - it never inverts
    polarity, so bright-on-dark stays bright-on-dark. Fail-soft: on any PIL
    error the input grayscale is returned unchanged."""
    g = img.convert("L")
    try:
        from PIL import ImageOps
        return ImageOps.autocontrast(g, cutoff=1)
    except Exception:  # noqa: BLE001
        return g


def _preprocess(img, scale: int = 4, threshold: int = 180, settings: Optional[dict] = None):
    """Color-correct + upscale + hard binarize. Tuned for League's white HUD
    text on colored bars (HP green, mana blue) where contrast-only
    preprocessing leaves the foreground too thin for Tesseract. The
    color-correct step (native-res enhancement, memory
    reference_vision_ocr_capture_pipeline) stretches dim glyphs above the
    threshold before binarize so a native crop is not dropped.

    When the active HUD settings flag ``color_correction_needed`` (a non-neutral
    ColorBrightness/Contrast/Gamma), the frame is first inverse-corrected toward
    neutral (R95). ``settings`` overrides the process-wide default installed via
    ``configure_hud_color``; None uses that default. On the neutral path the body
    stays byte-identical to the pre-R95 behavior (no correction call)."""
    from PIL import Image
    s = settings if settings is not None else _HUD_COLOR
    if s.get("color_correction_needed"):
        img = _apply_color_correction(img, s.get("color") or {})
    g = _color_correct(img).resize((img.width * scale, img.height * scale), Image.LANCZOS)
    return g.point(lambda p: 255 if p > threshold else 0)


def _apply_color_correction(img, color: dict):
    """Inverse-correct League ColorBrightness/ColorContrast/ColorGamma (0.0-1.0,
    0.5 neutral) so a game-shifted frame is pulled toward neutral before OCR
    (R95). Each slider's deviation from 0.5 maps to an inverse enhancement factor
    (0.5 -> 1.0, i.e. no change); factors are clamped to a modest [0.3, 3.0].
    Brightness + contrast go through PIL ImageEnhance, gamma through a .point()
    LUT on the RGB image. Neutral / absent sliders are an effective no-op (the
    input is returned untouched). Fail-soft: returns ``img`` unchanged on any
    PIL error."""
    neutral = 0.5  # League slider midpoint (ColorPalette default 0 handled elsewhere)
    try:
        from PIL import ImageEnhance

        def _slider(key):
            try:
                return float(color.get(key))
            except (TypeError, ValueError):
                return neutral

        def _factor(val):
            # deviation-from-neutral -> inverse gain (brighter game -> darker fix)
            f = 1.0 - 2.0 * (val - neutral)
            return max(0.3, min(3.0, f))

        bright = _factor(_slider("ColorBrightness"))
        contrast = _factor(_slider("ColorContrast"))
        gdev = _slider("ColorGamma") - neutral
        if abs(bright - 1.0) <= 1e-6 and abs(contrast - 1.0) <= 1e-6 and abs(gdev) <= 1e-6:
            return img  # all-neutral / absent -> true no-op
        out = img.convert("RGB")
        if abs(bright - 1.0) > 1e-6:
            out = ImageEnhance.Brightness(out).enhance(bright)
        if abs(contrast - 1.0) > 1e-6:
            out = ImageEnhance.Contrast(out).enhance(contrast)
        if abs(gdev) > 1e-6:
            exp = max(0.3, min(3.0, 1.0 + 2.0 * gdev))
            lut = [max(0, min(255, int(round(((i / 255.0) ** exp) * 255)))) for i in range(256)]
            out = out.point(lut * 3)
        return out
    except Exception:  # noqa: BLE001
        return img


def _ocr_int(img, allowlist: str = "0123456789") -> Optional[int]:
    import pytesseract
    s = pytesseract.image_to_string(
        _preprocess(img),
        config=f"--oem 3 --psm 7 -c tessedit_char_whitelist={allowlist}",
        timeout=_TESS_TIMEOUT_S,
    ).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else None


def _ocr_timer(img) -> Optional[str]:
    """League MM:SS clock; tolerates leading/trailing junk."""
    import pytesseract
    s = pytesseract.image_to_string(
        _preprocess(img),
        config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789:",
        timeout=_TESS_TIMEOUT_S,
    ).strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            mm, ss = int(parts[0]), int(parts[1])
            if 0 <= mm < 100 and 0 <= ss < 60:
                return f"{mm}:{ss:02d}"
    return None


def _ocr_kda(img) -> Optional[str]:
    """KDA in 'K/D/A' format. Returns the literal string or None."""
    import pytesseract
    s = pytesseract.image_to_string(
        _preprocess(img),
        config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/",
        timeout=_TESS_TIMEOUT_S,
    ).strip()
    parts = [p for p in s.split("/") if p.isdigit()]
    if len(parts) == 3:
        k, d, a = (int(p) for p in parts)
        if all(0 <= x <= 99 for x in (k, d, a)):
            return f"{k}/{d}/{a}"
    return None


def _ocr_hp_mana(img) -> Optional[int]:
    """HP/mana bar text format 'CURR / MAX'. Returns CURR (current value)."""
    import pytesseract
    s = pytesseract.image_to_string(
        _preprocess(img),
        config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/",
        timeout=_TESS_TIMEOUT_S,
    ).strip()
    parts = [p for p in s.split("/") if p.isdigit()]
    if parts:
        v = int(parts[0])
        if 0 <= v <= 99999:
            return v
    return None


def _bar_fill_pct(img, color: str = "green", settings: Optional[dict] = None) -> Optional[int]:
    """Estimate bar fill percentage by counting matching color pixels per
    column. Walks left->right; the rightmost column with >=30% matching
    pixels marks the fill edge. Returns 0-100 (None if bar not detected).

    When the active HUD settings flag ``colorblind`` (a non-zero ColorPalette
    re-hues the HP/mana bars), RELAXED thresholds are used so a hue-shifted bar
    still registers (R95); the strict thresholds are unchanged otherwise.
    ``settings`` overrides the process-wide default installed via
    ``configure_hud_color``; None uses that default."""
    s = settings if settings is not None else _HUD_COLOR
    colorblind = bool(s.get("colorblind"))
    rgb = img.convert("RGB")
    w, h = rgb.size
    if w < 4 or h < 2:
        return None
    px = rgb.load()

    def is_match(r, g, b):
        if colorblind:
            # relaxed: lower absolute floor + smaller channel-dominance deltas so
            # a palette-shifted bar still registers.
            if color == "green":
                return g > 90 and g >= r - 5 and g > b + 5
            if color == "blue":
                return b > 90 and b >= g - 5 and r < 140
            if color == "red":
                return r > 100 and r >= g - 5 and r >= b - 5
            return False
        if color == "green":
            return g > 110 and g > r + 20 and g > b + 20
        if color == "blue":
            return b > 110 and b > r + 10 and b > g - 20 and r < 120
        if color == "red":
            return r > 120 and r > g + 30 and r > b + 30
        return False

    last_filled_col = -1
    any_match = False
    for x in range(w):
        col_match = 0
        for y in range(h):
            r, g, b = px[x, y]
            if is_match(r, g, b):
                col_match += 1
        if col_match >= max(1, h // 3):
            last_filled_col = x
            any_match = True
    if not any_match:
        return 0
    return int(round((last_filled_col + 1) * 100 / w))


def _ally_ults_strip(img, slots: int = 4) -> Optional[list]:
    """Scan a vertical strip containing N stacked ult icons. For each slot,
    check the center sub-square for saturated/bright pixels. Returns a
    list of bools of length N, True = ult ready (icon lit), False = on CD
    or icon dim. Robust against the rectangular HP/mana bars that may
    bleed into the strip - those are excluded by sampling only the
    center 60% width of each slot's vertical band (icons are circular,
    bars span the full width)."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    if w < 6 or h < slots * 6:
        return None
    px = rgb.load()
    band_h = h // slots
    out = []
    for i in range(slots):
        y0 = i * band_h
        y1 = (i + 1) * band_h
        cx0, cx1 = int(w * 0.1), int(w * 0.9)
        cy0, cy1 = y0 + band_h // 3, y1 - band_h // 3
        if cx1 <= cx0 or cy1 <= cy0:
            out.append(False)
            continue
        total = 0
        green = 0
        for y in range(cy0, cy1):
            for x in range(cx0, cx1):
                r, g, b = px[x, y]
                total += 1
                if g > 110 and g > r + 25 and g > b + 15:
                    green += 1
        ratio = green / total if total else 0
        out.append(ratio >= 0.18)
    return out


def _ult_pct(img) -> Optional[int]:
    """League ult cooldown is a clockwise-filling pie inside a circular
    icon. Counts saturated/bright pixels inside the inscribed circle and
    returns 0-100 (0 = on CD just used, 100 = ready). Same parser whether
    the user wants a binary check (>=95 = up) or a partial fill display."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    if w < 6 or h < 6:
        return None
    px = rgb.load()
    cx, cy = w / 2.0, h / 2.0
    r2 = (min(w, h) / 2.0) ** 2
    total = 0
    lit = 0
    for y in range(h):
        for x in range(w):
            if (x - cx) ** 2 + (y - cy) ** 2 > r2:
                continue
            total += 1
            r, g, b = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx > 110 and (mx - mn) > 25:
                lit += 1
    if total == 0:
        return None
    return int(round(lit * 100 / total))


def _ocr_int_stack(img, channel: Optional[str] = None,
                   threshold: int = 130) -> Optional[list]:
    """Multi-line numeric OCR for vertically-stacked timers.
    Returns list of ints in top-to-bottom order. Empty if no digits.

    channel=None  -> grayscale + standard preprocess (default).
    channel='R'/'G'/'B' -> isolate that channel before binarize, useful
    when the digits are colored (red enemy death timer, gold own timer)
    and grayscale conversion dims them below the standard threshold."""
    import pytesseract
    if channel is None:
        pp = _preprocess(img)
    else:
        from PIL import Image
        rgb = img.convert("RGB")
        ch = {"R": 0, "G": 1, "B": 2}[channel]
        chimg = rgb.split()[ch]
        big = chimg.resize((chimg.width * 4, chimg.height * 4), Image.LANCZOS)
        pp = big.point(lambda p: 255 if p > threshold else 0)
    s = pytesseract.image_to_string(
        pp, config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789",
        timeout=_TESS_TIMEOUT_S,
    ).strip()
    out = []
    for line in s.splitlines():
        digits = "".join(ch for ch in line if ch.isdigit())
        if digits:
            v = int(digits)
            if 0 <= v <= 99:
                out.append(v)
    return out


def _ocr_colored_int(img, channel: str = "B", threshold: int = 130) -> Optional[int]:
    """OCR colored digits (e.g., team-score blue/red) by isolating one RGB
    channel before binarize. Grayscale convert dims color text below the
    standard threshold; per-channel keeps it bright."""
    import pytesseract
    from PIL import Image
    r, g, b = img.convert("RGB").split()
    ch = {"R": r, "G": g, "B": b}[channel]
    big = ch.resize((ch.width * 4, ch.height * 4), Image.LANCZOS)
    bw = big.point(lambda p: 255 if p > threshold else 0)
    s = pytesseract.image_to_string(
        bw, config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789",
        timeout=_TESS_TIMEOUT_S,
    ).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else None


def _ocr_cooldown(img) -> Optional[float]:
    """Cooldown overlay on a spell/summoner icon: '12', '12.5', '4.7', etc.
    Returns float seconds, or None if icon shows no cooldown (ready)."""
    import pytesseract
    s = pytesseract.image_to_string(
        _preprocess(img),
        config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.",
        timeout=_TESS_TIMEOUT_S,
    ).strip()
    s = s.replace(" ", "")
    if not s or s == "." or all(c == "." for c in s):
        return None
    try:
        v = float(s)
    except ValueError:
        digits = "".join(ch for ch in s if ch.isdigit())
        if not digits:
            return None
        v = float(digits)
    if 0 <= v <= 999:
        return v
    return None


# Slow-changing fields read every Nth call instead of every call.
_SLOW_FIELDS = {"timer", "score_blue", "score_red", "cs", "ping", "fps"}
_SLOW_MODULO = 5
# Atomic counter for slow-field cadence. itertools.count is GIL-safe per
# CPython implementation, avoiding the read-modify-write race that the
# previous `_slow_tick += 1` had when /api/ocr and a coach call
# `read_fast_fields()` concurrently.
import itertools as _itertools
_slow_tick_counter = _itertools.count()
_slow_cache: dict = {}

# Drop set: fields the caller has authoritative truth for elsewhere
# (e.g., Live Client relay). Set via configure_drop_fields().
_DROP_FIELDS: set = set()

# Active HUD color layer (core.hud_settings.read_hud_settings output). Installed
# live by core.vision_profiles.active_config_key() so bar detection + OCR
# preprocessing adapt to the colorblind palette + gamma/brightness/contrast
# sliders. Empty -> neutral (identical to pre-R95 hardcoded behavior).
_HUD_COLOR: dict = {}


def configure_drop_fields(names: Iterable[str]) -> None:
    """Skip OCR on these fields (caller has authoritative truth elsewhere,
    typically from Live Client API relay). Pass empty set to clear."""
    global _DROP_FIELDS
    _DROP_FIELDS = set(names)


def configure_hud_color(settings: Optional[dict]) -> None:
    """Install active HUD color settings (core.hud_settings.read_hud_settings
    output) so bar detection + OCR preprocessing adapt to colorblind palette +
    gamma/brightness/contrast. None/empty clears to neutral (identical to
    pre-R95 hardcoded behavior)."""
    global _HUD_COLOR
    _HUD_COLOR = dict(settings) if settings else {}


def _has_text_signal(crop, threshold: int = 180, min_lit_pct: float = 0.02) -> bool:
    """Cheap pre-check: does the crop contain ANY text-bright pixels?
    Returns False on icons that are fully lit (off-cooldown spell),
    saving ~60ms of Tesseract for empty regions."""
    g = crop.convert("L")
    px = g.getdata()
    n = len(px)
    if n == 0:
        return False
    lit = sum(1 for p in px if p > threshold)
    return lit >= max(3, int(n * min_lit_pct))


def _parse_field(name: str, crop):
    """Single-field parse logic - extracted so it can run in a thread pool."""
    if name == "timer":
        return _ocr_timer(crop)
    if name == "kda":
        return _ocr_kda(crop)
    if name in ("hp", "mana"):
        return _ocr_hp_mana(crop)
    if name.startswith("ally_") and name.endswith("_hp"):
        return _bar_fill_pct(crop, color="green")
    if name.startswith("ally_") and name.endswith("_mana"):
        return _bar_fill_pct(crop, color="blue")
    if name == "ally_ults":
        return _ally_ults_strip(crop, slots=4)
    if name == "ally_levels":
        lst = _ocr_int_stack(crop)
        return [x for x in lst if 1 <= x <= 18] if lst else None
    if name == "level":
        v = _ocr_int(crop)
        return v if v is not None and 1 <= v <= 18 else None
    if name == "gold":
        v = _ocr_int(crop)
        return v if v is not None and 0 <= v <= 99999 else None
    if name.endswith("_cd"):
        # Skip if no text signal - icon is off-cooldown.
        if not _has_text_signal(crop):
            return None
        return _ocr_cooldown(crop)
    if name == "score_blue":
        v = _ocr_colored_int(crop, channel="B")
        return v if v is not None and 0 <= v <= 99 else None
    if name == "score_red":
        v = _ocr_colored_int(crop, channel="R")
        return v if v is not None and 0 <= v <= 99 else None
    if name == "ping" or name == "fps":
        import pytesseract
        s = pytesseract.image_to_string(
            _preprocess(crop), config="--oem 3 --psm 7",
            timeout=_TESS_TIMEOUT_S,
        ).strip()
        lead = ""
        for ch in s:
            if ch.isdigit():
                lead += ch
            elif lead:
                break
        return int(lead) if lead else None
    return _ocr_int(crop)


def read_fast_fields(img_b64: str, fields: Optional[Iterable[str]] = None,
                     parallel: bool = True, max_workers: int = 8) -> dict:
    """Run OCR on selected fields in parallel via thread pool.

    Optimizations:
      - parallel Tesseract (up to max_workers concurrent calls)
      - tiered cadence: slow fields (timer, score, cs, ping, fps) read
        every Nth call, cached otherwise
      - conditional skip: skill_*_cd skipped when icon shows no text
      - drop set: caller can pre-mark fields satisfied by Live Client API

    Failed fields are omitted (None values not returned).
    """
    _ensure_tesseract()
    regions = _regions()
    targets = list(fields) if fields else list(regions.keys())
    img = _decode_img(img_b64)
    fw, fh = img.size

    # Tier split + drop-set filter (atomic increment via itertools.count)
    skip_slow_this_tick = (next(_slow_tick_counter) % _SLOW_MODULO) != 0
    work = []  # list of (name, crop)
    for name in targets:
        if name in _DROP_FIELDS:
            continue
        if skip_slow_this_tick and name in _SLOW_FIELDS:
            continue
        bbox = regions.get(name)
        if not bbox:
            continue
        work.append((name, _crop(img, _scale_bbox(bbox, fw, fh))))

    out: dict = {}
    if parallel and len(work) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_to_name = {
                ex.submit(_parse_field, name, crop): name
                for name, crop in work
            }
            for fut in as_completed(future_to_name):
                name = future_to_name[fut]
                try:
                    v = fut.result()
                    if v is not None:
                        out[name] = v
                except Exception as exc:  # noqa: BLE001
                    _log.debug("ocr %s: %s", name, exc)
    else:
        for name, crop in work:
            try:
                v = _parse_field(name, crop)
                if v is not None:
                    out[name] = v
            except Exception as exc:  # noqa: BLE001
                _log.debug("ocr %s: %s", name, exc)

    # Slow-field cache: serve from cache on skip ticks, refresh on read ticks.
    if not skip_slow_this_tick:
        for k in _SLOW_FIELDS:
            if k in out:
                _slow_cache[k] = out[k]
    for k, v in _slow_cache.items():
        out.setdefault(k, v)

    return out


def crop_png_b64(img_b64: str, field: str) -> Optional[str]:
    """Return the cropped region as base64 PNG. For visual region verification."""
    regions = _regions()
    bbox = regions.get(field)
    if not bbox:
        return None
    img = _decode_img(img_b64)
    crop = _crop(img, _scale_bbox(bbox, img.width, img.height))
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
