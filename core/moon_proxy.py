# arch: vision server proxy | section=core | frozen=yes
"""
core/moon_proxy.py - Transparent proxy to the local vision server.
RC calls this instead of calling Claude directly for vision + coaching.

Post-2026-04-19: vision server is in-process on Legion at 127.0.0.1:8889
(historically Moon-PC at 192.168.8.230). Falls back to local (direct Claude
API) automatically if the vision server is offline. Availability check cached
for 30s so no hot-path penalty.
"""
import json
import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Optional

log = logging.getLogger("rc.moon_proxy")

MOON_HOST    = "127.0.0.1"
MOON_PORT    = 8889
MOON_BASE    = f"http://{MOON_HOST}:{MOON_PORT}"
# AUDIT (2026-04-22): token resolved via core.vision_token; see docstring.
from core.vision_token import get_vision_token as _get_vision_token
AUTH_TOKEN   = _get_vision_token()
AUTH_HEADER  = "X-RC-Token"
TIMEOUT_S    = 8       # per-request timeout
CHECK_TTL    = 30.0    # re-check availability every 30s
CONNECT_TTL  = 5.0     # availability check timeout


class MoonProxy:
    """
    Singleton proxy that routes vision / coach / OCR calls to Moon-PC.
    Thread-safe. Falls back to None if Moon-PC is unavailable.
    """

    def __init__(self):
        self._lock          = threading.Lock()
        self._available:  Optional[bool] = None
        self._last_check  = 0.0
        self._fail_count  = 0

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if self._available is None or (now - self._last_check) > CHECK_TTL:
                self._last_check = now
                self._available  = self._ping()
                if self._available:
                    self._fail_count = 0
                    log.info("Moon-PC available at %s:%d", MOON_HOST, MOON_PORT)
                else:
                    log.debug("Moon-PC unavailable")
            return bool(self._available)

    def _ping(self) -> bool:
        # AUDIT P-rc-frozen-moon_proxy-except-breadth (2026-04-22): narrow
        # the catch-all so SystemExit / KeyboardInterrupt propagate during
        # shutdown. Health probe only cares about network + parse errors.
        try:
            req = urllib.request.Request(f"{MOON_BASE}/health")
            with urllib.request.urlopen(req, timeout=CONNECT_TTL) as r:
                data = json.loads(r.read().decode())
                return bool(data.get("alive")) and bool(data.get("api_key_ok"))
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError, UnicodeDecodeError):
            return False

    def _mark_failed(self):
        with self._lock:
            self._fail_count += 1
            if self._fail_count >= 2:
                self._available = False
                self._last_check = time.monotonic()  # will re-check after TTL

    # ── Vision ────────────────────────────────────────────────────────────────

    def extract_vision(self, img_b64: str, model: str = "") -> Optional[dict]:
        """Send base64 PNG to Moon-PC /vision. Returns parsed game-state dict or None."""
        if not self.is_available():
            return None
        # AUDIT 2026-04-28 (5.5): coalesce duplicate calls within a short
        # TTL. Two coach loops can fetch the exact same /latest-frame
        # within milliseconds; this skips the redundant Sonnet round-trip.
        try:
            import hashlib as _hashlib
            from core.cost_tracker import get_tracker as _gt
            _key = "vision:" + _hashlib.sha1(
                (img_b64 + "|" + (model or "")).encode("utf-8")
            ).hexdigest()
            _cached = _gt().vision_dedupe_get(_key)
            if _cached is not None:
                log.debug("Moon vision dedupe hit (%s...)", _key[7:15])
                return _cached
        # AUDIT 2026-04-28 (deferred-frozen): narrowed from bare Exception.
        except (ImportError, AttributeError, TypeError, OSError, ValueError):
            _key = ""
        try:
            payload = json.dumps({
                "image_b64": img_b64,
                **({"model": model} if model else {}),
            }).encode()
            req = urllib.request.Request(
                f"{MOON_BASE}/vision", data=payload,
                headers={"Content-Type": "application/json", AUTH_HEADER: AUTH_TOKEN},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                resp = json.loads(r.read().decode())
            if resp.get("ok"):
                log.debug("Moon vision OK (%dms)", resp.get("latency_ms", -1))
                result = resp.get("result")
                if _key and result is not None:
                    try:
                        from core.cost_tracker import get_tracker as _gt
                        _gt().vision_dedupe_put(_key, result, ttl_s=2.0)
                    except (OSError, TypeError, AttributeError):
                        pass
                return result
            log.warning("Moon vision error: %s", resp.get("error"))
            self._mark_failed()
            return None
        except urllib.error.URLError as e:
            log.debug("Moon vision network: %s", e)
            self._mark_failed()
            return None
        # AUDIT 2026-04-28 (deferred-frozen): narrowed from bare Exception
        # so SystemExit/KeyboardInterrupt propagate during shutdown.
        except (OSError, TimeoutError, json.JSONDecodeError,
                UnicodeDecodeError, ValueError) as e:
            log.warning("Moon vision exception: %s", e)
            self._mark_failed()
            return None

    # ── Coach ─────────────────────────────────────────────────────────────────

    def get_coaching(self, prompt: str, context: str = "", model: str = "") -> Optional[str]:
        """Send coaching prompt to Moon-PC /coach. Returns response text or None."""
        if not self.is_available():
            return None
        try:
            payload = json.dumps({
                "prompt":  prompt,
                "context": context,
                **({"model": model} if model else {}),
            }).encode()
            req = urllib.request.Request(
                f"{MOON_BASE}/coach", data=payload,
                headers={"Content-Type": "application/json", AUTH_HEADER: AUTH_TOKEN},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                resp = json.loads(r.read().decode())
            if resp.get("ok"):
                log.debug("Moon coach OK (%dms)", resp.get("latency_ms", -1))
                return resp.get("text")
            log.warning("Moon coach error: %s", resp.get("error"))
            self._mark_failed()
            return None
        except urllib.error.URLError as e:
            log.debug("Moon coach network: %s", e)
            self._mark_failed()
            return None
        # AUDIT 2026-04-28 (deferred-frozen): narrowed from bare Exception.
        except (OSError, TimeoutError, json.JSONDecodeError,
                UnicodeDecodeError, ValueError) as e:
            log.warning("Moon coach exception: %s", e)
            self._mark_failed()
            return None

    # ── OCR ───────────────────────────────────────────────────────────────────

    def ocr_crops(self, crops_b64: dict) -> Optional[dict]:
        """Send crop dict to Moon-PC /ocr. Returns {stage_round, level, gold, hp} or None."""
        if not self.is_available():
            return None
        try:
            payload = json.dumps({"crops": crops_b64}).encode()
            req = urllib.request.Request(
                f"{MOON_BASE}/ocr", data=payload,
                headers={"Content-Type": "application/json", AUTH_HEADER: AUTH_TOKEN},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                resp = json.loads(r.read().decode())
            if resp.get("ok"):
                return resp.get("result")
            return None
        # AUDIT 2026-04-28 (deferred-frozen): narrowed from bare Exception.
        except (urllib.error.URLError, OSError, TimeoutError,
                json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            log.debug("Moon OCR: %s", e)
            return None

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "available":  self._available,
            "fail_count": self._fail_count,
            "host":       MOON_HOST,
            "port":       MOON_PORT,
        }

# Module-level singleton
moon_proxy = MoonProxy()
