# arch: vision server stats + log ring | section=vision | frozen=no
"""Stats tracking for vision/coach/ocr/upload calls.

Split out of moon_vision_server.py during Phase 2.4. Owns:
- ``_stats`` dict (per-kind call/error/latency/byte counters).
- ``_log_ring`` (rolling 80-entry request log).
- ``_latency_ring`` (rolling 60-entry latency series for sparkline).
- ``_record(kind, ms, ok, tokens)`` - the single mutator.
- ``get_stats()`` - snapshot for the /stats endpoint.
- ``_capture_skips`` + ``_record_capture_skip(reason)`` - Y-03 (external
  reference K) fail-closed capture counters. ``CAPTURE_SKIP_REASONS`` is the
  ONE reason vocabulary (locked | not_foreground | blank) the frame path uses;
  a liveness/capability field can reuse it rather than mint a second one.

Sibling modules (``_frame``, ``_relay``) directly mutate ``_stats[kind]["bytes"]``
under ``_stats_lock`` to record upload byte totals. Keep that contract - moving
those mutations behind setters would just create indirection.
"""
from __future__ import annotations

import collections
import sys
import threading
import time

from ._config import COACH_MODEL, VISION_MODEL, _START_TIME, api_key_present, log

_stats_lock = threading.Lock()
_stats: dict = {
    "vision":            {"calls": 0, "errors": 0, "total_ms": 0, "tokens_est": 0},
    "coach":             {"calls": 0, "errors": 0, "total_ms": 0, "tokens_est": 0},
    "ocr":               {"calls": 0, "errors": 0, "total_ms": 0},
    "frame_upload":      {"calls": 0, "errors": 0, "total_ms": 0, "bytes": 0},
    "liveclient_upload": {"calls": 0, "errors": 0, "total_ms": 0, "bytes": 0},
    "lcu_upload":        {"calls": 0, "errors": 0, "total_ms": 0},
}
# Y-03: why a capture was refused. Kept OUT of ``_stats`` (whose entries all
# share the calls/errors/total_ms shape) and exposed as its own top-level key.
CAPTURE_SKIP_REASONS = ("locked", "not_foreground", "blank")
_capture_skips: dict = {r: 0 for r in CAPTURE_SKIP_REASONS}
_capture_skips.update({"last_reason": None, "last_ts": 0.0})
_log_ring = collections.deque(maxlen=80)
_latency_ring = collections.deque(maxlen=60)


def _record(kind: str, ms: int, ok: bool = True, tokens: int = 0) -> None:
    ts = time.strftime("%H:%M:%S")
    with _stats_lock:
        s = _stats.setdefault(kind, {"calls": 0, "errors": 0, "total_ms": 0})
        s["calls"] += 1
        s["total_ms"] += ms
        if not ok:
            s["errors"] += 1
        if tokens:
            s["tokens_est"] = s.get("tokens_est", 0) + tokens
        _log_ring.append({"ts": ts, "kind": kind, "ms": ms, "ok": ok})
        _latency_ring.append({"kind": kind, "ms": ms, "ts": time.time()})


def _record_capture_skip(reason: str) -> None:
    """Count one refused capture. ``reason`` must be in CAPTURE_SKIP_REASONS."""
    if reason not in CAPTURE_SKIP_REASONS:
        raise ValueError(f"unknown capture skip reason: {reason!r}")
    with _stats_lock:
        _capture_skips[reason] += 1
        _capture_skips["last_reason"] = reason
        _capture_skips["last_ts"] = time.time()


def _reset_capture_skips() -> None:
    """Test helper: zero the Y-03 counters."""
    with _stats_lock:
        for r in CAPTURE_SKIP_REASONS:
            _capture_skips[r] = 0
        _capture_skips["last_reason"] = None
        _capture_skips["last_ts"] = 0.0


# RM-272: a missing OCR stack is a static machine fact, not a per-call event.
# Recording it through ``_record`` would flood both rings with a permanent
# condition (and make error-count assertions pass for the wrong reason on a
# stack-less runner), so it is surfaced as a CAPABILITY field on /stats plus
# one latched WARNING in logs/.
_ocr_stack_error: str = ""


def note_ocr_stack_missing(exc: BaseException) -> None:
    """Latch the OCR-stack import failure; log it exactly once per process."""
    global _ocr_stack_error
    with _stats_lock:
        first = not _ocr_stack_error
        _ocr_stack_error = f"{type(exc).__name__}: {exc}"[:200] or "ImportError"
    if first:
        log.warning(
            "OCR stack unavailable (pytesseract/PIL import failed: %s) - "
            "/ocr returns an error until it is installed; /stats "
            "ocr_stack_ok=false", exc,
        )


def ocr_stack_ok() -> bool:
    """True when pytesseract and PIL are importable and no import has failed."""
    import importlib.util
    if _ocr_stack_error:
        return False
    return all(importlib.util.find_spec(m) is not None
               for m in ("pytesseract", "PIL"))


def get_stats() -> dict:
    with _stats_lock:
        stats_copy = {k: dict(v) for k, v in _stats.items()}
        skip_copy = dict(_capture_skips)
        log_copy = [dict(x) for x in list(_log_ring)[-30:]]
        lat_copy = [dict(x) for x in list(_latency_ring)]
        return {
            "uptime_s":     int(time.time() - _START_TIME),
            "stats":        stats_copy,
            "capture_skip": skip_copy,
            "log":          log_copy,
            "latency_60":   lat_copy,
            "python":       sys.version.split()[0],
            "vision_model": VISION_MODEL,
            "coach_model":  COACH_MODEL,
            "api_key_ok":   api_key_present(),
            "ocr_stack_ok": ocr_stack_ok(),
        }
