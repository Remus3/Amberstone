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
# AUDIT (2026-04-22): token now resolved via core.vision_token —
# env var RC_VISION_TOKEN, then config/vision_token.txt, then
# legacy hardcoded default for backward compat.
from core.vision_token import get_vision_token as _get_vision_token
_AUTH_TOKEN    = _get_vision_token()
_FRAME_TIMEOUT = 3.0
_FRAME_MAX_AGE_S = 8.0   # warn if cached frame older than this
_FRAME_HARD_AGE_S = 30.0 # REJECT if older than this — prevents API credit
                         # waste when Game-PC agent is down (relay still
                         # serves the last cached frame indefinitely)

# AUDIT (2026-04-22): track consecutive failures so we escalate from
# DEBUG to WARNING after the issue persists — a silent debug-only log
# made "Game-PC agent is dead" invisible until someone spotted the
# absence of frames in the dashboard.
_FRAME_FAIL_WARN_STREAK = 3
_fail_streak = 0


def _capture_screen() -> Optional[str]:
    """Fetch the latest Game-PC screenshot from the local vision-server cache.

    Post-2026-04-19: RC runs on Legion; the local screen has no League window.
    The Game-PC agent (`tools/gamepc_screen_agent.py`) pushes frames to
    `/upload-frame`; this function pulls the latest from `/latest-frame`.
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
            # Reject outright — Sonnet would burn credits analyzing a
            # game state that's 30+ s old. Treat as if the frame doesn't
            # exist; coach loops should skip the vision tick this turn.
            logger.warning(
                "latest-frame REJECTED: age=%.1fs > hard cap %.0fs (Game-PC agent down?)",
                age, _FRAME_HARD_AGE_S,
            )
            _fail_streak += 1
            return None
        if age > _FRAME_MAX_AGE_S:
            logger.warning("latest-frame stale: age=%.1fs (Game-PC agent down?)", age)
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


class GameVisionReader:
    """
    Base class for screen extraction.
    Subclasses provide PROMPT and override _postprocess(raw_dict).
    Always uses claude-sonnet-4-6 for best small-text OCR.
    """

    # Subclasses MUST override
    PROMPT: str = ""

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model  = "claude-sonnet-4-6"
        self._last   = {}

    def read(self) -> Optional[dict]:
        img = _capture_screen()
        if not img:
            return None
        raw = self._extract(img)
        if raw:
            raw = self._postprocess(raw)
            self._last = raw
        return raw

    def last(self) -> dict:
        return self._last

    # ── Private ───────────────────────────────────────────────────────────

    def _extract(self, img_b64: str) -> Optional[dict]:
        # AUDIT-OPUS BUG-5 fix: route vision through core.moon_proxy.MoonProxy
        # singleton (unified Moon-PC client) instead of lan_bridge.  lan_bridge
        # is an HTTPServer module whose import-time `serve_forever()` call
        # blocks (or raises OSError if port 8888 is already bound by the
        # running lan_bridge process) — it was never a functioning client.
        # AUDIT 2026-04-28 (5.1 + 5.4): gate every vision call on (a) the
        # daily spend cap and (b) a token-bucket rate limit so a chaotic
        # teamfight can't spike calls per second.
        try:
            from core.cost_tracker import get_tracker as _gt
            _ct = _gt()
            if not _ct.allow_call():
                logger.warning("Vision call blocked: daily budget exceeded")
                return None
            if not _ct.acquire_vision_token():
                logger.debug("Vision call rate-limited")
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
