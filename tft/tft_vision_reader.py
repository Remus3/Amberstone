"""
tft/tft_vision_reader.py

Claude vision extraction for live TFT game state. Only reads YOUR units, not
enemy.

The frame comes from the loopback vision relay (modes.shared_vision), which
serves the primary monitor downscaled to 1280 wide (vision_server/_frame.py
_SELF_GRAB_MAX_WIDTH). Four HUD strips are cut from it - regions authored at
_BASE_SIZE and scaled to the frame actually received - and stacked top to
bottom into one image for the model.

STRATEGY: Read TRAITS panel first (always accurate), then bench/shop
(named cards), then deduce board units from trait counts + visible info.
Never rely on identifying tiny unit models during combat.

The model's JSON is untrusted: read() returns None for a non-object reply and
coerces every known field to the shape tft/tft_live_analysis.py reads.
"""

import base64
import io
import json
import logging
import re
import time
from typing import Optional

logger = logging.getLogger("rc.tft.vision")

# RM-314: per-request bound on the local-fallback Anthropic call in
# `_extract_local`. Without it the request inherits the SDK default of 600s.
# Sized BELOW the two Sonnet-class sites deliberately: this reader is Haiku
# (tft/tft_live_analysis.py:220 forwards a model defaulting to
# claude-haiku-4-5) and `_CROP_REGIONS` cuts the payload to a fraction of the
# image tiles of a full frame, so it does not need their headroom. 15s
# equals the TFT scan cadence (tft/tft_live_analysis.py:223
# _vision_interval = 15.0) so a hung extract cannot outlive the round it was
# scanning, and it still clears the p99 (10.95s) of the one measured latency
# distribution in the repo (data/coach_trace.jsonl, n=200).
_REQUEST_TIMEOUT_S = 15

# Size the crop regions are authored at: the relay frame size. A native
# 1920x1080 or 2560x1440 frame scales to the same HUD boxes. The regions used
# to be authored at 1600x900 against a 1280x720 frame, and PIL pads an
# out-of-frame crop with black instead of raising, so the bench + shop strip
# was 92 percent black on every live frame (measured on the s134 tft_qa
# recorder frames).
_BASE_SIZE = (1280, 720)
# A frame whose aspect ratio is further than this from _BASE_SIZE's is refused
# (same rule as tft/tft_ocr_reader.py).
_ASPECT_TOLERANCE = 0.02
# Mean grey level of the traits crop below which the frame is treated as
# "game not visible" (loading screen, black relay frame).
_DARK_MEAN = 8

_EXTRACT_PROMPT = """You are analyzing a TFT (Teamfight Tactics) game image made of 4 screen strips
stacked top to bottom: 1) the traits panel from the left edge, 2) the bench row
and the shop row from the bottom of the screen, 3) your half of the board (the
augment cards when an augment choice is open), 4) the player HP column from the
right edge.
Focus ONLY on what requires visual AI: unit names on cards, bench, and board.
Numbers (round, HP, level, gold) are handled separately - skip them.

\u2550\u2550\u2550 READ IN THIS ORDER \u2550\u2550\u2550

STEP 1 - TRAITS PANEL (STRIP 1):
Read the vertical traits panel. Each row: trait icon, name, count (e.g. "N.O.V.A. 3").
List ALL visible traits with their counts. This is ground truth.

STEP 2 - SHOP (BOTTOM ROW OF STRIP 2, 5 CARDS):
Read the 5 champion cards. Use the NAME TEXT printed on the card, not the portrait.

STEP 3 - BENCH (ROW ABOVE THE SHOP IN STRIP 2):
Read bench slots. Named champions or "empty".

STEP 4 - BOARD UNITS (STRIP 3, YOUR SIDE ONLY):
During COMBAT ignore enemy units. Identify YOUR units using nameplates + traits cross-reference.
Include star level when visible. If unsure use "unknown".

STEP 5 - AUGMENTS (YOUR AUGMENT BAR ONLY):
Read your augment slots if visible. Full name required (e.g. "Vanguard Heart", "Rogue Crest").
Never infer augments from trait counts. If unreadable return [].
If augment SELECT screen visible: set is_augment_select=true, list choices in augment_choices.

\u2550\u2550\u2550 CRITICAL RULES \u2550\u2550\u2550
- board_units MUST match traits. Never output trait names as unit names.
- Shop: read the bold champion NAME, not the trait tags below it.
- If spectating someone else's board: board_units=["SPECTATING"].

\u2550\u2550\u2550 OUTPUT FORMAT \u2550\u2550\u2550
Return ONLY valid JSON, no markdown:
{
  "traits_active":  ["N.O.V.A. 3", "Bastion 2"],
  "board_units":    ["Aatrox 2-star", "Caitlyn", "Maokai"],
  "bench_units":    ["Kindred", "empty", "empty"],
  "shop_units":     ["Akali", "Leona", "unknown", "Corki", "empty"],
  "items_equipped": {"Aatrox": ["Warmog's Armor"]},
  "items_on_bench": [],
  "augments":       ["N.O.V.A. Crest"],
  "gold":           null,
  "hp":             null,
  "level":          null,
  "stage_round":    null,
  "is_augment_select": false,
  "augment_choices":   [],
  "last_round_result": null,
  "round_damage":      null
}
Note: gold, hp, level, stage_round should be null - OCR handles these for free.
"""

# Field shapes the consumer (tft/tft_live_analysis.py _run_cycle /
# _run_analysis / _publish) reads. Only keys PRESENT in the reply are coerced;
# an absent key stays absent.
_STR_LIST_FIELDS = ("traits_active", "board_units", "bench_units", "shop_units",
                    "items_on_bench", "augments")
# (min, max) for each integer field; anything else becomes None.
_INT_FIELDS = {"level": (1, 10), "hp": (0, 100), "gold": (0, 999),
               "round_damage": (0, 100)}
_STAGE_ROUND_RE = re.compile(r"^\d{1,2}-\d{1,2}$")
_SPECTATING = "SPECTATING"


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


def _as_int(value, lo: int, hi: int) -> Optional[int]:
    """An int (or a digit string) inside [lo, hi], else None. bool is refused."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and lo <= value <= hi:
        return value
    return None


def _normalize_state(raw) -> Optional[dict]:
    """Coerce a model reply to the shapes the consumer reads.

    None for anything but a JSON object. Present list fields keep only
    non-blank strings (augment_choices also keeps the {name, description}
    dicts the consumer handles); a wrong-typed field becomes empty.
    """
    if not isinstance(raw, dict):
        logger.warning("Vision: reply is %s, not a JSON object - dropped",
                       type(raw).__name__)
        return None
    state = dict(raw)
    for key in _STR_LIST_FIELDS:
        if key in state:
            value = state[key]
            state[key] = ([v.strip() for v in value if isinstance(v, str) and v.strip()]
                          if isinstance(value, list) else [])
    if "augment_choices" in state:
        value = state["augment_choices"]
        state["augment_choices"] = (
            [v for v in value
             if isinstance(v, dict) or (isinstance(v, str) and v.strip())]
            if isinstance(value, list) else [])
    if "items_equipped" in state and not isinstance(state["items_equipped"], dict):
        state["items_equipped"] = {}
    if "is_augment_select" in state:
        state["is_augment_select"] = state["is_augment_select"] is True
    for key, (lo, hi) in _INT_FIELDS.items():
        if key in state:
            state[key] = _as_int(state[key], lo, hi)
    if "stage_round" in state:
        value = state["stage_round"]
        state["stage_round"] = (value.strip() if isinstance(value, str)
                                and _STAGE_ROUND_RE.match(value.strip()) else None)
    if "last_round_result" in state and not isinstance(state["last_round_result"], str):
        state["last_round_result"] = None
    return state


def _first_text(response) -> str:
    """Text of the first content block that carries text (a thinking or
    tool block has none), or "" when there is none."""
    for block in getattr(response, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text.strip()
    return ""


def _parse_reply(raw: str):
    """Parse the model's JSON: direct, then fence-stripped, then the outermost
    {...} span. None when no form parses."""
    stripped = raw.strip("`").strip()
    if stripped.startswith("json"):
        stripped = stripped[4:].strip()
    candidates = [raw, stripped]
    first_brace, last_brace = raw.find("{"), raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidates.append(raw[first_brace:last_brace + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


class TftVisionReader:
    # HUD strips sent instead of the whole frame, authored at _BASE_SIZE
    # (calibrated on the s134 tft_qa recorder frames, 1280x720 relay):
    # Format: (left, top, right, bottom)
    _CROP_REGIONS = [
        (0,    150, 200,  540),  # traits panel - left edge, up to 10 rows
        (150,  460, 1000, 720),  # bench row + shop
        (230,  250, 1040, 480),  # board - your half; also the augment cards
        (1100, 90,  1280, 540),  # player HP column - right edge
    ]

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com")
        self._model  = model   # haiku by default - use sonnet only if haiku quality is poor
        self._last_state: Optional[dict] = None
        self._last_capture = 0.0
        logger.info("TftVisionReader using model=%s", self._model)

    def read(self, force: bool = False) -> Optional[dict]:
        img_b64 = self._capture_game()
        if not img_b64:
            return None
        state = _normalize_state(self._extract(img_b64))
        if state:
            state = self._validate_units(state)
            self._last_state = state
            self._last_capture = time.time()
        return state

    def last_state(self) -> Optional[dict]:
        return self._last_state

    def _capture_game(self) -> Optional[str]:
        """AUDIT (2026-04-22): post-migration, RC runs on Legion which has
        no League window - ``PIL.ImageGrab`` here was always capturing the
        RC dashboard instead of the game. Route through the same
        `/latest-frame` relay that `modes/shared_vision.py` uses: pull
        the full-screen PNG from the loopback vision server, decode,
        then apply the TFT-specific crop regions client-side.

        None when there is no frame, the frame is not 16:9, or the traits
        crop is near-black (game not visible).
        """
        try:
            from PIL import Image, ImageStat
        except ImportError:
            logger.error("PIL not available for screenshot capture")
            return None

        try:
            from modes.shared_vision import _capture_screen as _relay_capture
            full_b64 = _relay_capture()
        except Exception as exc:  # noqa: BLE001
            logger.debug("TFT vision: relay fetch failed: %s", exc)
            return None
        if not full_b64:
            return None

        try:
            full_img = Image.open(io.BytesIO(base64.b64decode(full_b64))).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            logger.warning("TFT vision: relay frame decode failed: %s", exc)
            return None

        crops = []
        for bbox in self._CROP_REGIONS:
            box = _scaled_bbox(bbox, full_img.size)
            if box is None:
                logger.debug("TFT vision: frame %dx%d cannot hold region %s",
                             full_img.size[0], full_img.size[1], bbox)
                return None
            crops.append(full_img.crop(box))

        # Validate: the traits panel crop should not be near-black.
        avg_brightness = ImageStat.Stat(crops[0].convert("L")).mean[0]
        if avg_brightness < _DARK_MEAN:
            logger.debug("TFT vision: relay frame too dark (avg=%.1f) - game not visible",
                         avg_brightness)
            return None

        total_w = max(c.size[0] for c in crops)
        total_h = sum(c.size[1] for c in crops)
        combined = Image.new("RGB", (total_w, total_h))
        y = 0
        for c in crops:
            combined.paste(c, (0, y))
            y += c.size[1]

        buf = io.BytesIO()
        combined.save(buf, format="PNG", optimize=True)
        logger.debug("TFT vision crop (relay): %dx%d px", total_w, total_h)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _extract(self, img_b64: str):
        # Try Moon-PC remote first - falls back to local automatically
        try:
            from core.moon_proxy import moon_proxy
            result = moon_proxy.extract_vision(img_b64, model=self._model)
            if result is not None:
                return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("TFT vision: moon_proxy extract failed, using local: %s", exc)
        return self._extract_local(img_b64)

    def _extract_local(self, img_b64: str):
        try:
            t0 = time.time()
            response = self._client.messages.create(
                model=self._model, max_tokens=1400,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": img_b64}},
                    {"type": "text", "text": _EXTRACT_PROMPT}
                ]}],
                timeout=_REQUEST_TIMEOUT_S)
            # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker on
            # local-fallback path. moon_proxy primary records via vision_server.
            # Tier note corrected 2026-07-29: this reader is NOT Sonnet. Its
            # only construction site is tft/tft_live_analysis.py:220, which
            # forwards a model defaulting to claude-haiku-4-5 (:139), so the
            # old "SONNET tier - the most expensive untracked cadence" comment
            # sent every cost auditor chasing a surface that does not exist.
            try:
                from core.cost_tracker import record_anthropic_response
                record_anthropic_response(response, model=self._model, purpose="tft_vision")
            except Exception as _exc:  # noqa: BLE001
                logger.debug("cost_tracker record: %s", _exc)
            latency = int((time.time() - t0) * 1000)
            raw = _first_text(response)
            logger.debug("Vision extract in %dms (%d chars)", latency, len(raw))
            if not raw:
                logger.warning("Vision returned empty response")
                return None
            parsed = _parse_reply(raw)
            if parsed is None:
                logger.warning("Vision: could not extract JSON from %d-char response: %.100s...",
                               len(raw), raw)
            return parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vision extract failed: %s", exc)
            return None

    def _validate_units(self, state: dict) -> dict:
        """Post-process: keep the SPECTATING sentinel the consumer skips on
        (tft/tft_live_analysis.py _run_cycle), and flag more board units than
        the level allows."""
        units = state.get("board_units") or []
        if any(u.upper() == _SPECTATING for u in units):
            state["board_units"] = [_SPECTATING]
            return state
        level = state.get("level")
        if state.get("traits_active") and level and len(units) > level + 1:
            logger.warning("Vision returned %d units but level %d - possible enemy contamination",
                           len(units), level)
            state["_unit_warning"] = f"Got {len(units)} units at level {level}"
        return state
