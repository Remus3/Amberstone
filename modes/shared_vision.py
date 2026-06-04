"""
modes/shared_vision.py

Shared screen-capture + Claude Sonnet vision extraction base used by
ARAM, Arena, Brawl, and other non-TFT game modes.

Each mode subclasses GameVisionReader and provides its own extraction prompt.
"""

import base64
import io
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rc.vision")

# League window dimensions (Game-PC native). Used by region-aware vision only;
# screenshots themselves come from the Game-PC screen agent (full screen).
GAME_W, GAME_H = 1920, 1080

_VISION_SERVER = "http://127.0.0.1:8889"
# AUDIT (2026-04-22): token now resolved via core.vision_token -
# env var RC_VISION_TOKEN, then config/vision_token.txt, then
# legacy hardcoded default for backward compat.
from core.vision_token import get_vision_token as _get_vision_token
_AUTH_TOKEN    = _get_vision_token()
_FRAME_TIMEOUT = 3.0
_FRAME_MAX_AGE_S = 8.0   # warn if cached frame older than this
_FRAME_HARD_AGE_S = 90.0 # skip clearly stale frames so a wedged relay does not
                         # feed minutes-old game state into vision

# AUDIT (2026-04-22): track consecutive failures so we escalate from
# DEBUG to WARNING after the issue persists - a silent debug-only log
# made "Game-PC agent is dead" invisible until someone spotted the
# absence of frames in the dashboard.
_FRAME_FAIL_WARN_STREAK = 3
_fail_streak = 0


def _capture_screen() -> Optional[str]:
    """Fetch the latest screenshot from the local vision-server cache.

    Post 1-PC (ADR-011, 2026-05-29): RC runs on a single Legion machine.
    The screen agent (`tools/gamepc_screen_agent.py`, a 2-PC-era name now
    running Legion-local) pushes frames to `/upload-frame`; this function
    pulls the latest from `/latest-frame`.
    """
    global _fail_streak
    try:
        import json as _j
        import urllib.request
        req = urllib.request.Request(
            f"{_VISION_SERVER}/latest-frame",
            headers={"X-RC-Token": _AUTH_TOKEN},
        )
        with urllib.request.urlopen(req, timeout=_FRAME_TIMEOUT) as r:
            data = _j.loads(r.read())
        b64 = data.get("b64")
        if not b64:
            logger.debug("latest-frame: empty payload")
            return None
        age = max(0.0, time.time() - float(data.get("ts", 0)))
        if age > _FRAME_HARD_AGE_S:
            # Skip a clearly stale frame; coach loops skip the vision tick
            # this turn rather than analyze minutes-old game state.
            logger.warning(
                "latest-frame skipped: age=%.1fs > cap %.0fs (relay stalled?)",
                age, _FRAME_HARD_AGE_S,
            )
            _fail_streak += 1
            return None
        if age > _FRAME_MAX_AGE_S:
            logger.warning("latest-frame stale: age=%.1fs (relay stalled?)", age)
        _fail_streak = 0
        return b64
    except Exception as exc:
        _fail_streak += 1
        if _fail_streak >= _FRAME_FAIL_WARN_STREAK:
            logger.warning(
                "latest-frame fetch failed %d× in a row: %s "
                "(Game-PC agent or vision server likely down)",
                _fail_streak, exc,
            )
        else:
            logger.debug("latest-frame fetch failed (streak=%d): %s",
                         _fail_streak, exc)
        return None


# AUDIT 2026-04-28 (suggestion 5.6): Haiku model for cheap pre-screens
# that gate the expensive Sonnet vision call. Subclasses can pass a
# `state_summary` to read() so the pre-screen skips Sonnet when the
# summary hasn't drifted from the last successful extraction.
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"


class GameVisionReader:
    """
    Base class for screen extraction.
    Subclasses provide PROMPT and override _postprocess(raw_dict).
    Always uses claude-sonnet-4-6 for best small-text OCR.

    AUDIT 2026-04-28 (5.6): pass `state_summary` to read() - a short
    text snapshot of HUD-relevant facts the LCU/live-client API
    already gives us (gold bucket, level, dead-count, items hash, etc.)
    When that summary equals the previous successful read's, the cached
    result is returned without firing Sonnet. This is the cheap
    state-key dedupe sister to 5.5 (image-key dedupe).

    Tiered routing: set TIERED_FIELDS + TIERED_VALIDATORS on an instance
    (or subclass) and call read_tiered() instead of read().  OCR runs
    first via core.vision_routing.read_or_escalate; Sonnet fires only for
    fields OCR couldn't validate.  Fields with no region entry in
    vision_regions.json will always miss OCR → escalate to Sonnet, so the
    system degrades gracefully when calibration is incomplete.
    """

    # Subclasses MUST override
    PROMPT: str = ""

    # Tiered-routing configuration - set per-instance or per-subclass.
    # TIERED_FIELDS: all fields the mode needs (OCR-able + semantic).
    # TIERED_VALIDATORS: {field: callable(value) -> bool} overrides on top
    #   of vision_routing.DEFAULT_VALIDATORS.  Semantic fields should use
    #   permissive validators (any non-None / correct type is OK).
    TIERED_FIELDS: list = []
    TIERED_VALIDATORS: dict = {}

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model  = SONNET_MODEL
        self._last   = {}
        # Cache of (last successful state_summary, last result) for the
        # 5.6 pre-screen short-circuit.
        self._last_state_summary: Optional[str] = None
        self._last_result: Optional[dict] = None

    def read(self, state_summary: Optional[str] = None) -> Optional[dict]:
        # AUDIT 2026-04-28 (5.6): cheap state-summary pre-screen. If the
        # caller supplies a summary identical to the one paired with the
        # last successful extraction, return the cached result and skip
        # the entire vision call. No Anthropic API hit.
        if state_summary and state_summary == self._last_state_summary \
                and self._last_result is not None:
            logger.debug("Vision pre-screen skip: state_summary unchanged")
            return self._last_result
        img = _capture_screen()
        if not img:
            return None
        raw = self._extract(img)
        if raw:
            raw = self._postprocess(raw)
            self._last = raw
            if state_summary:
                self._last_state_summary = state_summary
                self._last_result = raw
        return raw

    def read_tiered(self, state_summary: Optional[str] = None) -> Optional[dict]:
        """Tiered read: OCR first, Sonnet escalation for semantic misses.

        Routes through core.vision_routing.read_or_escalate using
        self.TIERED_FIELDS and self.TIERED_VALIDATORS.  Sonnet is the
        escalate_fn - it runs in bulk for all fields OCR couldn't validate,
        using self.PROMPT unchanged.  Results are merged (OCR wins for
        numeric fields it validates; Sonnet fills the rest).

        Falls back to full read() if TIERED_FIELDS is empty.
        """
        _last_summary = getattr(self, "_last_state_summary", None)
        _last_result  = getattr(self, "_last_result", None)
        if state_summary and state_summary == _last_summary and _last_result:
            logger.debug("Vision pre-screen skip (tiered): state_summary unchanged")
            return _last_result

        if not self.TIERED_FIELDS:
            return self.read(state_summary=state_summary)

        img = _capture_screen()
        if not img:
            return None

        from core.vision_routing import read_or_escalate, DEFAULT_VALIDATORS

        validators = {**DEFAULT_VALIDATORS, **(self.TIERED_VALIDATORS or {})}
        reader_self = self  # closure capture

        def _escalate(img_b64: str, _missing: list) -> Optional[dict]:
            return reader_self._extract(img_b64)

        raw = read_or_escalate(
            img,
            fields=self.TIERED_FIELDS,
            escalate_fn=_escalate,
            validators=validators,
        )
        if raw:
            raw = self._postprocess(raw)
            self._last = raw
            if state_summary:
                self._last_state_summary = state_summary
                self._last_result = raw
        return raw

    def last(self) -> dict:
        return self._last

    # ── Private ───────────────────────────────────────────────────────────

    def _extract(self, img_b64: str) -> Optional[dict]:
        # AUDIT-OPUS BUG-5 fix: route vision through core.moon_proxy.MoonProxy
        # singleton (unified Moon-PC client) instead of lan_bridge.  lan_bridge
        # is an HTTPServer module whose import-time `serve_forever()` call
        # blocks (or raises OSError if port 8888 is already bound by the
        # running lan_bridge process) - it was never a functioning client.
        # AUDIT 2026-04-28 (5.4): keep the daily spend cap as the cost
        # backstop. The per-second token-bucket rate limit is removed so
        # vision is unrestricted during live gameplay (the coach vision
        # loop interval already paces calls).
        try:
            from core.cost_tracker import get_tracker as _gt
            _ct = _gt()
            if not _ct.allow_call():
                logger.warning("Vision call blocked: daily budget exceeded")
                return None
        except Exception:
            pass
        try:
            from core.moon_proxy import moon_proxy as _mp
            t0 = time.time()
            result = _mp.extract_vision(img_b64, self._model)
            if result is not None:
                ms = int((time.time() - t0) * 1000)
                logger.debug("Vision via Moon-PC (moon_proxy) in %dms", ms)
                # moon_proxy returns a dict directly; no JSON string to strip
                return result if isinstance(result, dict) else None
        except Exception as _e:
            logger.debug("moon_proxy vision routing failed, falling back: %s", _e)
        # Fallback: call Anthropic directly
        try:
            t0 = time.time()
            resp = self._client.messages.create(
                model      = self._model,
                max_tokens = 900,
                messages   = [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": ("image/jpeg" if img_b64.startswith("/9j/")
                                           else "image/png"),
                            "data": img_b64}},
                        {"type": "text", "text": self.PROMPT}
                    ]
                }]
            )
            ms  = int((time.time() - t0) * 1000)
            raw = resp.content[0].text.strip()
            logger.debug("Vision direct (fallback) in %dms", ms)
            # AUDIT 2026-04-28 (5.8): record direct-fallback Sonnet calls.
            try:
                from core.cost_tracker import get_tracker as _gt
                u = getattr(resp, "usage", None)
                if u is not None:
                    _gt().record_call(
                        model=self._model,
                        input_tokens=getattr(u, "input_tokens", 0) or 0,
                        output_tokens=getattr(u, "output_tokens", 0) or 0,
                        cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                        cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
                        purpose="vision_direct",
                    )
            except Exception:
                pass
            raw = re.sub(r'^```(?:json)?', '', raw).strip().strip('`')
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Vision JSON parse failed: %s", exc)
        except Exception as exc:
            logger.warning("Vision extract failed: %s", exc)
        return None

    def _postprocess(self, d: dict) -> dict:
        return d
