"""
tft/tft_ocr_reader.py

Free OCR-based reader for TFT structured UI data.
Replaces Claude vision for: stage/round, HP, level, gold.
Uses Tesseract 5.x via pytesseract - zero API cost.

TFT 1600x900 UI coordinates (calibrated):
  Stage/Round:  top-center, white text on dark bg  ~(680, 8, 920, 42)
  HP:           right panel, per-player rows        ~(1455, 140, 1595, 690)
  Level:        bottom-left HUD                     ~(10, 855, 100, 890)
  Gold:         bottom-center HUD                   ~(755, 858, 855, 888)
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rc.tft.ocr")

# ── Tesseract path (not on PATH, point directly) ─────────────────────────────
_TESS_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── UI regions at 1600x900 ───────────────────────────────────────────────────
# Format: (left, top, right, bottom)
# Calibrated from TFT Set 17 1600x900. Adjust via calibrate() if needed.
_REGIONS = {
    "stage_round": (640, 4,  960, 46),   # "3-6" white text, top center -- widened Phase 7 P1-B
    "level":       (8,   853, 98,  890),  # "Lvl 8" bottom left
    "gold":        (748, 855, 858, 890),  # "51" bottom center HUD
    "hp_panel":    (1448,138, 1598, 695), # player list right edge (multi-row)
}

# Upscale factor for small text regions (Tesseract works best at ~150dpi+)
_SCALE = 3

# How often to try OCR (seconds). Vision already runs every round; OCR runs faster.
_OCR_INTERVAL = 2.0


def _init_tesseract():
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = _TESS_CMD
        return pytesseract
    except ImportError:
        logger.warning("pytesseract not available - OCR disabled")
        return None


def _capture_full_frame():
    """Fetch the full Game-PC frame from the loopback vision relay.
    Returns a PIL Image, or None on failure (relay down, no frame yet).

    AUDIT (cycle 11, 2026-04-25): post-migration RC runs on Legion which
    has no League window. Local `PIL.ImageGrab.grab()` was capturing the
    dashboard browser instead of the game. `tft_vision_reader._capture_game`
    was already migrated to the relay; this OCR sibling was missed.
    """
    try:
        import base64 as _b64
        import io as _io
        from PIL import Image as _Image
        from modes.shared_vision import _capture_screen as _relay_capture
        full_b64 = _relay_capture()
        if not full_b64:
            return None
        return _Image.open(_io.BytesIO(_b64.b64decode(full_b64))).convert("RGB")
    except Exception as exc:
        logger.debug("TFT OCR: relay fetch failed: %s", exc)
        return None


def _grab_region(bbox, full_img=None):
    """Crop a region from the (cached) full frame.

    If `full_img` is given (preferred), crop from it - the caller has
    already paid the relay round-trip cost. If None, fetch a fresh full
    frame ourselves (slower; one HTTP call per crop).
    """
    if full_img is None:
        full_img = _capture_full_frame()
        if full_img is None:
            return None
    try:
        return full_img.crop(bbox)
    except Exception:
        return None


def _preprocess(img, scale=_SCALE, invert=False):
    """
    Upscale + threshold for Tesseract.
    TFT uses white/yellow text on dark backgrounds.
    """
    from PIL import Image, ImageFilter, ImageEnhance
    # Upscale
    w, h = img.size
    img = img.resize((w * scale, h * scale), Image.LANCZOS)
    # Convert to grayscale
    img = img.convert("L")
    # Enhance contrast
    img = ImageEnhance.Contrast(img).enhance(2.5)
    if invert:
        from PIL import ImageOps
        img = ImageOps.invert(img)
    return img


def _ocr_digits(img, tess) -> str:
    """OCR optimised for digit-only output (gold, HP numbers)."""
    processed = _preprocess(img)
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    try:
        text = tess.image_to_string(processed, config=cfg).strip()
        return re.sub(r"[^0-9]", "", text)
    except Exception as e:
        logger.debug("OCR digits error: %s", e)
        return ""


def _ocr_stage_round(img, tess) -> Optional[str]:
    """
    OCR the stage-round counter: expects format like '3-6' or '4-2'.
    TFT shows this as white bold text, top-center, e.g. '3-6'.
    """
    processed = _preprocess(img, scale=4)
    # Allow digits and hyphen only
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789-"
    try:
        text = tess.image_to_string(processed, config=cfg).strip()
        # Normalise: remove spaces, keep digits and hyphen
        text = re.sub(r"[^0-9\-]", "", text)
        # Match X-Y pattern
        m = re.match(r"^([1-9])-([1-7])$", text)
        if m:
            stage, rnd = int(m.group(1)), int(m.group(2))
            # Set 17: max stage 7, max round 7, stage 1 max round 4
            max_rnd = 4 if stage == 1 else 7
            if 1 <= stage <= 7 and 1 <= rnd <= max_rnd:
                return f"{stage}-{rnd}"
        # Heuristic fallback: only accept if both digits are plausible
        digits = re.findall(r"\d", text)
        if len(digits) == 2:
            s, r = int(digits[0]), int(digits[1])
            max_rnd = 4 if s == 1 else 7
            if 1 <= s <= 7 and 1 <= r <= max_rnd:
                return f"{s}-{r}"
        return None
    except Exception as e:
        logger.debug("OCR stage_round error: %s", e)
        return None


def _ocr_level(img, tess) -> Optional[int]:
    """
    OCR the level display. TFT shows 'Lvl 8' or just '8' bottom-left.
    """
    processed = _preprocess(img, scale=3)
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=Llv0123456789 "
    try:
        text = tess.image_to_string(processed, config=cfg).strip()
        m = re.search(r"\d+", text)
        if m:
            val = int(m.group())
            if 1 <= val <= 10:
                return val
        return None
    except Exception as e:
        logger.debug("OCR level error: %s", e)
        return None


def _ocr_gold(img, tess) -> Optional[int]:
    """OCR the gold counter. Shows 0-99 typically."""
    text = _ocr_digits(img, tess)
    if text:
        val = int(text)
        if 0 <= val <= 999:
            return val
    return None


def _ocr_hp(img, tess) -> Optional[int]:
    """
    OCR YOUR HP from the right player list panel.
    The player list shows 8 rows. Your row is highlighted (brighter).
    Strategy: scan the full panel, find all numbers, return the one
    in a highlighted row (higher luminance than neighbors).
    Falls back to the first valid HP value found.
    """
    from PIL import Image
    import numpy as np

    try:
        arr = np.array(img.convert("L"))  # grayscale
        h, w = arr.shape

        # Find the brightest row (your HP row is highlighted)
        row_brightness = arr.mean(axis=1)
        # Your row is brighter than avg - find rows significantly above mean
        mean_b = row_brightness.mean()
        bright_rows = [i for i, b in enumerate(row_brightness) if b > mean_b * 1.3]

        if bright_rows:
            # Average bright row position
            mid = int(sum(bright_rows) / len(bright_rows))
            pad = max(10, h // 10)
            top = max(0, mid - pad)
            bot = min(h, mid + pad)
            your_row = img.crop((0, top, w, bot))
        else:
            your_row = img  # fallback: use whole panel

        text = _ocr_digits(your_row, tess)
        if text:
            val = int(text)
            if 1 <= val <= 100:
                return val

        # Fallback: OCR entire panel, return first valid HP
        full_text = tess.image_to_string(
            _preprocess(img), config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789 "
        ).strip()
        nums = [int(n) for n in re.findall(r"\d+", full_text) if 1 <= int(n) <= 100]
        return nums[0] if nums else None
    except Exception as e:
        logger.debug("OCR hp error: %s", e)
        return None


class TftOcrReader:
    """
    Fast, free OCR reader for TFT structured UI data.
    Replaces Claude vision for: stage_round, level, gold, hp.

    Usage:
        reader = TftOcrReader()
        data = reader.read()  # -> {"stage_round": "3-6", "level": 8, "gold": 51, "hp": 65}
    """

    def __init__(self):
        self._tess = _init_tesseract()
        self._last_read = 0.0
        self._cache: dict = {}
        self._region_overrides: dict = {}  # allow runtime calibration
        self._available = self._tess is not None
        if self._available:
            logger.info("TftOcrReader ready (Tesseract %s)", _TESS_CMD)
        else:
            logger.warning("TftOcrReader: pytesseract unavailable, OCR disabled")

    @property
    def available(self) -> bool:
        return self._available

    def calibrate(self, field: str, bbox: tuple):
        """Override a region bbox at runtime for fine-tuning."""
        self._region_overrides[field] = bbox
        logger.info("OCR calibrated: %s -> %s", field, bbox)

    def _region(self, field: str) -> tuple:
        return self._region_overrides.get(field, _REGIONS[field])

    def read(self, force: bool = False) -> dict:
        """
        Read all OCR fields. Returns dict with keys:
          stage_round, level, gold, hp
        Missing/failed fields are omitted from the dict.
        Cached for _OCR_INTERVAL seconds unless force=True.
        """
        if not self._available:
            return {}
        now = time.time()
        if not force and (now - self._last_read) < _OCR_INTERVAL:
            return dict(self._cache)

        result = {}
        # Fetch the full frame once and crop from it for each region.
        # Cuts the per-tick relay round-trips from 4 to 1.
        full_img = _capture_full_frame()
        if full_img is None:
            logger.debug("OCR read: no relay frame available")
            self._cache = {}
            self._last_read = now
            return result
        try:
            # Stage/Round
            img = _grab_region(self._region("stage_round"), full_img)
            if img is not None:
                sr = _ocr_stage_round(img, self._tess)
                if sr:
                    result["stage_round"] = sr
                    logger.debug("OCR stage_round=%s", sr)

            # Level
            img = _grab_region(self._region("level"), full_img)
            if img is not None:
                lv = _ocr_level(img, self._tess)
                if lv:
                    result["level"] = lv
                    logger.debug("OCR level=%d", lv)

            # Gold
            img = _grab_region(self._region("gold"), full_img)
            if img is not None:
                gd = _ocr_gold(img, self._tess)
                if gd is not None:
                    result["gold"] = gd
                    logger.debug("OCR gold=%d", gd)

            # HP (more expensive - skip if game not started)
            if result.get("stage_round"):  # only try HP if we got a valid round
                img = _grab_region(self._region("hp_panel"), full_img)
                if img is not None:
                    hp = _ocr_hp(img, self._tess)
                    if hp:
                        result["hp"] = hp
                        logger.debug("OCR hp=%d", hp)

        except Exception as e:
            logger.warning("OCR read error: %s", e)

        self._cache = dict(result)
        self._last_read = now
        return result

    def read_stage_round_only(self) -> Optional[str]:
        """Fastest path - just the round counter. One relay round-trip."""
        if not self._available:
            return None
        try:
            img = _grab_region(self._region("stage_round"))
            if img is None:
                return None
            return _ocr_stage_round(img, self._tess)
        except Exception:
            return None

    def save_debug_crops(self, out_dir: str = r"C:\Riot Commander\data\ocr_debug"):
        """Save all region crops for manual inspection/calibration."""
        from PIL import ImageDraw
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        screen_full = _capture_full_frame()
        if screen_full is None:
            logger.warning("save_debug_crops: relay frame unavailable")
            return
        draw = screen_full.copy()

        for field, bbox in {**_REGIONS, **self._region_overrides}.items():
            crop = screen_full.crop(bbox)
            # Save raw crop
            crop.save(f"{out_dir}/{field}_raw.png")
            # Save preprocessed
            _preprocess(crop).save(f"{out_dir}/{field}_processed.png")
            logger.info("OCR debug saved: %s %s", field, bbox)

        screen_full.save(f"{out_dir}/full_screen.png")
        logger.info("OCR debug crops saved to %s", out_dir)
