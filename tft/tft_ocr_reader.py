"""
tft/tft_ocr_reader.py

Free OCR-based reader for TFT structured UI data.
Replaces Claude vision for: stage/round, level, gold and your own HP.
Uses Tesseract 5.x - zero API cost.

Live path (TftOcrReader.read / read_stage_round_only, the TftStateReader OCR
thread): since TFT-04 the crops come from the resolution-relative region
profile ``config/tft_regions/2560x1440.json`` through
``tft.cv.ocr_fields.read_frame``, scaled to whatever frame the relay serves
(1280x720 today, 1920x1080, 2560x1440) and gated by the layout classifier, so a
hidden panel yields no value; a frame of any other aspect ratio (a stitched
multi-monitor grab) has no profile and reads absent. Match-3 QA N7
(2026-10-25): the old absolute boxes were authored at 1600x900 (Set 17) and on
the 1280x720 relay frame the stage box saw only the phase timer - 0 of 12 stage
reads right, a latched 6-2 and a false "new game". Gold and own HP on the live
path come from the cv profile's own boxes, not from the legacy boxes below.

Legacy helpers (``_REGIONS`` / ``_grab_region`` / ``_ocr_*``; used by
``save_debug_crops`` and their own timeout tests, NOT by the live reads): the
regions are authored against the 1280x720 frame the vision relay serves
(vision_server/_frame.py _SELF_GRAB_MAX_WIDTH) and scaled to the size of the
frame actually received. A frame that is not 16:9 is refused rather than
misread, and a box that falls outside the frame yields no crop: PIL pads an
out-of-frame crop with black instead of raising, which is how the 1600x900
boxes went silently inert (s134 true-audit: 0 of 80 recorded live frames
yielded any field before the recalibration). The legacy gold box and the
"brightest row" HP locator are gone: the centred coin glyph bled into the
gold digits (24 read as 5, 52 as 520), and the HP fallback returned the first
number in the panel, i.e. the TOP-ranked player's HP, not yours.
"""

import logging
import re
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rc.tft.ocr")

# -- Tesseract path (default install dir; PATH is the fallback) --------------
_TESS_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# -- UI regions, authored at _BASE_SIZE ---------------------------------------
# Format: (left, top, right, bottom). Calibrated 2026-10-25 against the s134
# tft_qa recorder's 1280x720 live game frames (current HUD: the stage text sits
# right of the stage icon in the top bar; "Lvl. N" sits above the shop, left).
# Adjust at runtime via calibrate(), in the same _BASE_SIZE coordinates.
_BASE_SIZE = (1280, 720)
_REGIONS = {
    "stage_round": (509, 2, 552, 22),    # "4-5" right of the stage icon
    "level":       (160, 585, 225, 606),  # "Lvl. 8" above the shop, left
}

# A frame whose aspect ratio is further than this from _BASE_SIZE's is refused.
_ASPECT_TOLERANCE = 0.02

# Upscale factor for small text regions (Tesseract works best at ~150dpi+)
_SCALE = 4

# Grayscale cut: HUD text is light on a dark panel, so a pixel at or above
# this is text. 140 at x4 read every sampled stage right on the recorded
# frames; 110 / 170, or x6, misread a 3 as a 5.
_THRESHOLD = 140

# Fields the live OCR thread reads every tick through tft.cv.ocr_fields (cheap:
# about four Tesseract calls; shop / scoreboard / traits belong to the TFT-07
# capture bursts, not the 2 s poll).
_LIVE_FIELDS = ("stage", "level", "gold", "own_hp")

# How often to try OCR (seconds). Vision already runs every round; OCR runs faster.
_OCR_INTERVAL = 2.0

# Hard cap (seconds) on a single tesseract child. Without it a stuck/zombie
# tesseract.exe blocks the background OCR thread (tft_state_reader._ocr_loop)
# indefinitely - the loop is daemon but never yields fresh round/HP/level/gold.
# pytesseract passes this to the subprocess and raises RuntimeError on expiry,
# which the per-call try/except already swallows back to a missing field.
_OCR_TIMEOUT = 8


def _resolve_tesseract_cmd() -> Optional[str]:
    """The tesseract executable to run, or None when none is installed."""
    if Path(_TESS_CMD).is_file():
        return _TESS_CMD
    return shutil.which("tesseract")


def _init_tesseract():
    """pytesseract pointed at a real binary, or None (OCR disabled).

    pytesseract importing is not enough: without the binary every call raised
    TesseractNotFoundError, swallowed at debug level, while `available` said
    True and the state reader logged "OCR subsystem started".
    """
    try:
        import pytesseract
    except ImportError:
        logger.warning("pytesseract not available - OCR disabled")
        return None
    cmd = _resolve_tesseract_cmd()
    if cmd is None:
        logger.warning("tesseract executable not found (%s, PATH) - OCR disabled",
                       _TESS_CMD)
        return None
    pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def _capture_full_frame():
    """Fetch the full screen frame from the loopback vision relay.
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
    except Exception as exc:  # noqa: BLE001
        logger.debug("TFT OCR: relay fetch failed: %s", exc)
        return None


def _scaled_bbox(bbox, size) -> Optional[tuple]:
    """Scale a _BASE_SIZE bbox to a frame of `size` (w, h).

    None when the frame is not 16:9 within _ASPECT_TOLERANCE, or the scaled
    box is empty or not wholly inside the frame.
    """
    w, h = size
    base_w, base_h = _BASE_SIZE
    if w <= 0 or h <= 0:
        return None
    if abs((w / h) / (base_w / base_h) - 1.0) > _ASPECT_TOLERANCE:
        return None
    sx, sy = w / base_w, h / base_h
    left, top, right, bottom = bbox
    box = (int(round(left * sx)), int(round(top * sy)),
           int(round(right * sx)), int(round(bottom * sy)))
    if not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h):
        return None
    return box


def _grab_region(bbox, full_img=None):
    """Crop a _BASE_SIZE region, scaled to the (cached) full frame.

    If `full_img` is given (preferred), crop from it - the caller has
    already paid the relay round-trip cost. If None, fetch a fresh full
    frame ourselves (slower; one HTTP call per crop). None when there is no
    frame or the frame cannot hold the box (see _scaled_bbox).
    """
    if full_img is None:
        full_img = _capture_full_frame()
        if full_img is None:
            return None
    box = _scaled_bbox(bbox, full_img.size)
    if box is None:
        return None
    return full_img.crop(box)


def _preprocess(img, scale=_SCALE, threshold=_THRESHOLD):
    """
    Grayscale + upscale + binarise for Tesseract: the light HUD text becomes
    black on a white page (Tesseract's native polarity), with a white margin
    so a glyph touching the crop edge is not dropped.
    """
    from PIL import Image, ImageOps
    img = img.convert("L")
    w, h = img.size
    img = img.resize((w * scale, h * scale), Image.LANCZOS)
    img = img.point(lambda v: 0 if v >= threshold else 255)
    return ImageOps.expand(img, border=10, fill=255)


def _ocr_digits(img, tess) -> str:
    """OCR optimised for digit-only output (the gold parse half)."""
    processed = _preprocess(img)
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    try:
        text = tess.image_to_string(processed, config=cfg, timeout=_OCR_TIMEOUT).strip()
        return re.sub(r"[^0-9]", "", text)
    except Exception as e:  # noqa: BLE001
        logger.debug("OCR digits error: %s", e)
        return ""


def _ocr_stage_round(img, tess) -> Optional[str]:
    """
    OCR the stage-round counter: expects format like '3-6' or '4-2'.
    TFT shows this as white bold text, top-center, e.g. '3-6'.
    """
    processed = _preprocess(img)
    # Allow digits and hyphen only
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789-"
    try:
        text = tess.image_to_string(processed, config=cfg, timeout=_OCR_TIMEOUT).strip()
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
    except Exception as e:  # noqa: BLE001
        logger.debug("OCR stage_round error: %s", e)
        return None


def _ocr_level(img, tess) -> Optional[int]:
    """
    OCR the level display. TFT shows 'Lvl. 8' above the shop, left.
    """
    processed = _preprocess(img)
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=Lvl.0123456789"
    try:
        text = tess.image_to_string(processed, config=cfg, timeout=_OCR_TIMEOUT).strip()
        # The LAST number: "Lvl" can OCR as "Lv1", whose 1 is not the level.
        nums = re.findall(r"\d+", text)
        if nums:
            val = int(nums[-1])
            if 1 <= val <= 10:
                return val
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug("OCR level error: %s", e)
        return None


def _ocr_gold(img, tess) -> Optional[int]:
    """OCR the gold counter. Shows 0-99 typically.

    NOT called by TftOcrReader.read(): no region is validated for it (module
    docstring). Kept as the parse half for when one is.
    """
    text = _ocr_digits(img, tess)
    if text:
        val = int(text)
        if 0 <= val <= 999:
            return val
    return None


class TftOcrReader:
    """
    Fast, free OCR reader for TFT structured UI data.
    Replaces Claude vision for: stage_round, level, gold, hp.

    Usage:
        reader = TftOcrReader()
        data = reader.read()  # -> {"stage_round": "3-6", "level": 8, "gold": 51, "hp": 65}

    ``engine`` / ``profile`` are seams for tests; by default the Tesseract CLI
    engine of ``tft.cv.ocr_fields`` and the region profile for the resolution
    the local client is configured to (``load_client_profile``).
    """

    def __init__(self, engine=None, profile=None) -> None:
        self._tess = _init_tesseract()  # legacy helpers (save_debug_crops) only
        self._last_read = 0.0
        self._cache: dict = {}
        self._region_overrides: dict = {}  # legacy save_debug_crops calibration
        self._engine = engine
        self._profile = profile
        self._profile_loaded = profile is not None
        if self._engine is None:
            try:
                from tft.cv.ocr_fields import TesseractEngine
                self._engine = TesseractEngine()
            except Exception as exc:  # noqa: BLE001
                logger.warning("TftOcrReader: OCR engine unavailable: %s", exc)
        check = getattr(self._engine, "available", None)
        self._available = self._engine is not None and (check() if callable(check) else True)
        if self._available:
            logger.info("TftOcrReader ready (resolution-relative TFT regions)")
        else:
            logger.warning("TftOcrReader: Tesseract unavailable, OCR disabled")

    @property
    def available(self) -> bool:
        return self._available

    def calibrate(self, field: str, bbox: tuple) -> None:
        """Override a legacy region bbox (``save_debug_crops`` only; the live
        reads take their regions from config/tft_regions).

        `bbox` is (left, top, right, bottom) in _BASE_SIZE coordinates, like
        _REGIONS. Raises ValueError on an unknown field or a box that is not
        four ints forming a non-empty rectangle inside _BASE_SIZE - a bad box
        used to be stored and then crop nothing (or black) forever.
        """
        if field not in _REGIONS:
            raise ValueError(f"unknown OCR field {field!r}")
        if (not isinstance(bbox, (tuple, list)) or len(bbox) != 4
                or not all(isinstance(v, int) and not isinstance(v, bool)
                           for v in bbox)):
            raise ValueError(f"bbox must be four ints, got {bbox!r}")
        left, top, right, bottom = bbox
        if not (0 <= left < right <= _BASE_SIZE[0]
                and 0 <= top < bottom <= _BASE_SIZE[1]):
            raise ValueError(f"bbox {bbox!r} is empty or outside {_BASE_SIZE}")
        self._region_overrides[field] = tuple(bbox)
        logger.info("OCR calibrated: %s -> %s", field, bbox)

    def _region(self, field: str) -> tuple:
        return self._region_overrides.get(field, _REGIONS[field])

    def _get_profile(self):
        if not self._profile_loaded:
            self._profile_loaded = True
            try:
                from tft.cv.profile import load_client_profile
                self._profile = load_client_profile()
            except Exception as exc:  # noqa: BLE001
                logger.warning("TftOcrReader: region profile load failed: %s", exc)
                self._profile = None
            if self._profile is None:
                logger.warning("TftOcrReader: no TFT region profile for this client "
                               "resolution; OCR fields read absent")
        return self._profile

    def read_frame_fields(self, full_img, fields=_LIVE_FIELDS) -> dict:
        """The live-path mapping: one frame -> {stage_round, level, gold, hp}.

        Absent fields are omitted (never 0); any frame size of the profile's
        aspect ratio works (1280x720 relay, 1920x1080, 2560x1440)."""
        prof = self._get_profile()
        if full_img is None or prof is None:
            return {}
        from tft.cv.ocr_fields import read_frame
        fr = read_frame(full_img, profile=prof, engine=self._engine, fields=fields)
        result = {}
        for src, dst in (("label", "stage_round"), ("level", "level"), ("gold", "gold"),
                         ("own_hp", "hp")):
            fv = fr.fields.get(src)
            if fv is not None and fv.present:
                result[dst] = fv.value
        return result

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
        # One relay frame per tick; every field crops from it.
        full_img = _capture_full_frame()
        if full_img is None:
            logger.debug("OCR read: no relay frame available")
            self._cache = {}
            self._last_read = now
            return result
        try:
            result = self.read_frame_fields(full_img)
            logger.debug("OCR read: %s", result)
        except Exception as e:  # noqa: BLE001
            logger.warning("OCR read error: %s", e)
            result = {}

        self._cache = dict(result)
        self._last_read = now
        return result

    def read_stage_round_only(self) -> Optional[str]:
        """Fastest path - just the round counter. One relay round-trip."""
        if not self._available:
            return None
        try:
            return self.read_frame_fields(_capture_full_frame(), ("stage",)).get("stage_round")
        except Exception:  # noqa: BLE001
            return None

    def save_debug_crops(self, out_dir: str = str(Path(__file__).resolve().parent.parent / "data" / "ocr_debug")) -> None:
        """Save all region crops for manual inspection/calibration."""
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        screen_full = _capture_full_frame()
        if screen_full is None:
            logger.warning("save_debug_crops: relay frame unavailable")
            return
        for field, bbox in {**_REGIONS, **self._region_overrides}.items():
            crop = _grab_region(bbox, screen_full)
            if crop is None:
                logger.warning("OCR debug: %s %s does not fit frame %s",
                               field, bbox, screen_full.size)
                continue
            # Save raw crop
            crop.save(f"{out_dir}/{field}_raw.png")
            # Save preprocessed
            _preprocess(crop).save(f"{out_dir}/{field}_processed.png")
            logger.info("OCR debug saved: %s %s", field, bbox)

        screen_full.save(f"{out_dir}/full_screen.png")
        logger.info("OCR debug crops saved to %s", out_dir)
