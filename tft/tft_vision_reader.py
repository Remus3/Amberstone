"""
tft/tft_vision_reader.py

Screenshot + Claude vision extraction for live TFT game state.
Captures 1600x900 game window. Only reads YOUR units, not enemy.

STRATEGY: Read TRAITS panel first (always accurate), then bench/shop
(named cards), then deduce board units from trait counts + visible info.
Never rely on identifying tiny unit models during combat.
"""

import base64
import io
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rc.tft.vision")

GAME_W, GAME_H = 1600, 900

_EXTRACT_PROMPT = """You are analyzing a TFT (Teamfight Tactics) screenshot at 1600x900.
Focus ONLY on what requires visual AI: unit names on cards, bench, and board.
Numbers (round, HP, level, gold) are handled separately - skip them.

═══ READ IN THIS ORDER ═══

STEP 1 - TRAITS PANEL (LEFT SIDE):
Read the vertical traits panel on the LEFT edge. Each row: trait icon, name, count (e.g. "N.O.V.A. 3").
List ALL visible traits with their counts. This is ground truth.

STEP 2 - SHOP (BOTTOM ROW, 5 CARDS):
Read the 5 champion cards at the very bottom. Use the NAME TEXT printed on the card, not the portrait.

STEP 3 - BENCH (ROW ABOVE SHOP):
Read bench slots. Named champions or "empty".

STEP 4 - BOARD UNITS (YOUR SIDE - bottom half only):
During COMBAT ignore enemy top half. Identify YOUR units using nameplates + traits cross-reference.
Include star level when visible. If unsure use "unknown".

STEP 5 - AUGMENTS (YOUR AUGMENT BAR ONLY):
Read 3 augment slots above bench. Full name required (e.g. "Vanguard Heart", "Rogue Crest").
Never infer augments from trait counts. If unreadable return [].
If augment SELECT screen visible: set is_augment_select=true, list choices in augment_choices.

═══ CRITICAL RULES ═══
- board_units MUST match traits. Never output trait names as unit names.
- Shop: read the bold champion NAME, not the trait tags below it.
- If spectating someone else's board: board_units=["SPECTATING"].

═══ OUTPUT FORMAT ═══
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


class TftVisionReader:
    # Cropped regions to send instead of full 1600x900 screen.
    # Sonnet image cost = tiles of ~32x32px. Full screen = ~1400 tiles.
    # These 4 strips total ~350 tiles = 75% image token reduction.
    # Format: (left, top, right, bottom)
    _CROP_REGIONS = [
        (0,    0,   200, 850),   # traits panel - full left strip
        (0,    700, 1600, 900),  # bench + shop - full bottom strip
        (100,  440, 1200, 710),  # board - your side (bottom half of hex grid)
        (1200, 100, 1600, 700),  # player HP panel - right edge
    ]

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model  = model   # haiku by default - use sonnet only if haiku quality is poor
        self._last_state: Optional[dict] = None
        self._last_capture = 0.0
        logger.info("TftVisionReader using model=%s", self._model)

    def read(self, force: bool = False) -> Optional[dict]:
        img_b64 = self._capture_game()
        if not img_b64:
            return None
        state = self._extract(img_b64)
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
        Game-PC's full-screen PNG from the loopback vision server, decode,
        then apply the TFT-specific crop regions client-side.
        """
        try:
            from PIL import Image
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
            # bbox from _CROP_REGIONS is Game-PC absolute (1920x1080);
            # PIL.Image.crop expects a 4-tuple.
            try:
                crops.append(full_img.crop(bbox))
            except Exception as exc:  # noqa: BLE001
                logger.debug("TFT vision: crop %s failed: %s", bbox, exc)
                return None

        # Validate: first crop (traits panel) should not be near-black.
        arr = crops[0].getdata()
        sample = [arr[i] for i in range(0, min(len(arr), 2000), 20)]
        avg_brightness = sum(sum(p[:3]) / 3 for p in sample) / max(len(sample), 1)
        if avg_brightness < 8:
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

    def _extract(self, img_b64: str) -> Optional[dict]:
        # Try Moon-PC remote first - falls back to local automatically
        try:
            from core.moon_proxy import moon_proxy
            result = moon_proxy.extract_vision(img_b64, model=self._model)
            if result is not None:
                return result
        except Exception:  # noqa: BLE001
            pass
        return self._extract_local(img_b64)

    def _extract_local(self, img_b64: str) -> Optional[dict]:
        try:
            t0 = time.time()
            response = self._client.messages.create(
                model=self._model, max_tokens=1400,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": img_b64}},
                    {"type": "text", "text": _EXTRACT_PROMPT}
                ]}])
            # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker on
            # local-fallback path. moon_proxy primary records via vision_server.
            # tft_vision_reader is SONNET tier - the most expensive
            # untracked cadence in the audit (polling vision local fallback).
            try:
                from core.cost_tracker import record_anthropic_response
                record_anthropic_response(response, model=self._model, purpose="tft_vision")
            except Exception as _exc:  # noqa: BLE001
                logger.debug("cost_tracker record: %s", _exc)
            latency = int((time.time() - t0) * 1000)
            raw = response.content[0].text.strip()
            logger.debug("Vision extract in %dms (%d chars)", latency, len(raw))
            if not raw:
                logger.warning("Vision returned empty response")
                return None
            # Robust JSON extraction: try multiple approaches
            # 1. Direct parse
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            # 2. Strip markdown fences: ```json ... ```
            stripped = raw.strip("`").strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
            # 3. Find first { ... last } in response
            first_brace = raw.find("{")
            last_brace = raw.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                try:
                    return json.loads(raw[first_brace:last_brace + 1])
                except json.JSONDecodeError:
                    pass
            logger.warning("Vision: could not extract JSON from %d-char response: %.100s...", len(raw), raw)
            return None
        except json.JSONDecodeError:
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vision extract failed: %s", exc)
            return None

    def _validate_units(self, state: dict) -> dict:
        """Post-process: flag mismatches between traits and board units."""
        traits = state.get("traits_active", [])
        units = state.get("board_units", [])
        if not traits or not units:
            return state
        level = state.get("level", 0)
        if level and len(units) > level + 1:
            logger.warning("Vision returned %d units but level %d - possible enemy contamination",
                          len(units), level)
            state["_unit_warning"] = f"Got {len(units)} units at level {level}"
        if units and units[0] == "SPECTATING":
            state["board_units"] = []
        return state
