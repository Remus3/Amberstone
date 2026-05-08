# arch: OCR pipeline (Tesseract) | section=vision | frozen=no
"""
core/vision_tesseract.py — Local Tesseract OCR for cheap League fields.

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
_REGIONS_FILE = _APP_DIR / "data" / "vision_regions.json"

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
        except Exception as exc:
            _log.warning("vision_regions.json load failed: %s — using defaults", exc)
            _REGIONS_CACHE = dict(_DEFAULT_REGIONS)
            _BASE_CACHE = (BASE_W, BASE_H)
    else:
        _REGIONS_CACHE = dict(_DEFAULT_REGIONS)
        _BASE_CACHE = (BASE_W, BASE_H)
        try:
            _REGIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _REGIONS_FILE.write_text(
                json.dumps(_REGIONS_CACHE, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
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


def _ensure_tesseract() -> None:
    """Pin pytesseract to the default install path if not in PATH."""
    import pytesseract
    cmd = pytesseract.pytesseract.tesseract_cmd
    if not cmd or not os.path.isfile(cmd):
        if os.path.isfile(_TESSERACT_DEFAULT):
            pytesseract.pytesseract.tesseract_cmd = _TESSERACT_DEFAULT


def _decode_img(img_b64: str):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(img_b64)))


def _crop(img, bbox):
    return img.crop(bbox)


def _preprocess(img, scale: int = 4, threshold: int = 180):
    """Upscale + hard binarize. Tuned for League's white HUD text on
    colored bars (HP green, mana blue) where contrast-only preprocessing
    leaves the foreground too thin for Tesseract."""
    from PIL import Image
    g = img.convert("L").resize((img.width * scale, img.height * scale), Image.LANCZOS)
    return g.point(lambda p: 255 if p > threshold else 0)


def _ocr_int(img, allowlist: str = "0123456789") -> Optional[int]:
    import pytesseract
    s = pytesseract.image_to_string(
        _preprocess(img),
        config=f"--oem 3 --psm 7 -c tessedit_char_whitelist={allowlist}",
    ).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else None


def _ocr_timer(img) -> Optional[str]:
    """League MM:SS clock; tolerates leading/trailing junk."""
    import pytesseract
    s = pytesseract.image_to_string(
        _preprocess(img),
        config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789:",
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
    ).strip()
    parts = [p for p in s.split("/") if p.isdigit()]
    if parts:
        v = int(parts[0])
        if 0 <= v <= 99999:
            return v
    return None


def _bar_fill_pct(img, color: str = "green") -> Optional[int]:
    """Estimate bar fill percentage by counting matching color pixels per
    column. Walks left->right; the rightmost column with >=30% matching
    pixels marks the fill edge. Returns 0-100 (None if bar not detected)."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    if w < 4 or h < 2:
        return None
    px = rgb.load()

    def is_match(r, g, b):
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
    bleed into the strip — those are excluded by sampling only the
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


def configure_drop_fields(names: Iterable[str]) -> None:
    """Skip OCR on these fields (caller has authoritative truth elsewhere,
    typically from Live Client API relay). Pass empty set to clear."""
    global _DROP_FIELDS
    _DROP_FIELDS = set(names)


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


def _parse_field(name: str, crop, hp_known: Optional[int] = None):
    """Single-field parse logic — extracted so it can run in a thread pool."""
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
    if name == "enemy_deaths":
        return _ocr_int_stack(crop, channel="R", threshold=130) or None
    if name == "level":
        v = _ocr_int(crop)
        return v if v is not None and 1 <= v <= 18 else None
    if name == "gold":
        v = _ocr_int(crop)
        return v if v is not None and 0 <= v <= 99999 else None
    if name.endswith("_cd"):
        # Skip if no text signal — icon is off-cooldown.
        if not _has_text_signal(crop):
            return None
        return _ocr_cooldown(crop)
    if name == "death_timer":
        # Skip if alive (hp_known > 0) — death timer only renders when dead.
        if hp_known is not None and hp_known > 0:
            return None
        if not _has_text_signal(crop, threshold=150):
            return None
        v = _ocr_colored_int(crop, channel="R", threshold=130)
        return v if v is not None and 0 <= v <= 99 else None
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
      - conditional skip: skill_*_cd skipped when icon shows no text;
        death_timer skipped when self hp > 0
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

    # Pre-pass: own hp (used to skip death_timer). Cheap, just one OCR.
    hp_known = None
    for name, crop in work:
        if name == "hp":
            try:
                hp_known = _ocr_hp_mana(crop)
            except Exception:
                hp_known = None
            break

    out: dict = {}
    if parallel and len(work) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_to_name = {
                ex.submit(_parse_field, name, crop, hp_known): name
                for name, crop in work
            }
            for fut in as_completed(future_to_name):
                name = future_to_name[fut]
                try:
                    v = fut.result()
                    if v is not None:
                        out[name] = v
                except Exception as exc:
                    _log.debug("ocr %s: %s", name, exc)
    else:
        for name, crop in work:
            try:
                v = _parse_field(name, crop, hp_known)
                if v is not None:
                    out[name] = v
            except Exception as exc:
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
