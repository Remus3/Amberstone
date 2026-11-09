# arch: ward-coverage heat strip backend | section=dashboard | frozen=no
"""GET /api/ward-heat - rolling-window ward placements + uncovered lanes.

UX research recommended a "Ward-Coverage Heat Strip" panel (UX-3 in
the pitch deck) - a 24px horizontal band below the active-match
minimap showing the last 90 seconds of ward placements per lane
(top/mid/bot/jg), colored by ward type. This module is the BACKEND
half - it does NOT render anything; the canvas is a separate UX
follow-up.

Request shape:
  GET /api/ward-heat[?window_s=90]

  window_s : optional number, rolling-window length in seconds. Default
             90 (also for a blank value). ASCII text that float() reads
             as a finite number in [5, 600], else a fixed 400 (never
             clamped). A digit outside ASCII, an underscore ("1_0"), a
             non-ASCII blank or an ASCII separator U+001C..U+001F is
             refused as not numeric; ASCII blanks (space, tab, CR, LF,
             FF, VT) around the value are ignored.

Response shape:
  {
    "ok":     true,
    "now_s":  <unix epoch seconds, when this snapshot was taken>,
    "window_s": 90.0,
    "wards":  [
      {"ts": 1755..., "side": "ally", "lane": "mid", "ward_type": "yellow"},
      ...
    ],
    "counts": {
      "ally":  {"top": 3, "mid": 2, "bot": 0, "jg": 1, "unknown": 0},
      "enemy": {"top": 0, "mid": 1, "bot": 0, "jg": 0, "unknown": 0}
    },
    "lanes_uncovered_ally":  ["bot"],
    "lanes_uncovered_enemy": ["top", "bot", "jg"],
    "buffer_size":           7,
    "cached":                false,
    "elapsed_ms":            1
  }

  wards, counts and both lanes_uncovered lists come from ONE read of the
  ward buffer (S144-T-619): counts and uncovered are derived from the
  wards list itself, so a ward the producer records mid-request can never
  appear in one part of a body and not another. lanes_uncovered uses the
  last min(window_s, 60) seconds of that same list. buffer_size is a
  separate read of the buffer occupancy (a debug field; it counts entries
  outside the window too).

Cache:
  2-second response cache keyed by ``window_s``, timed on the monotonic
  clock (a wall-clock step never keeps an entry fresh, and an entry
  stamped in the future is never served). The dashboard ticks at ~500ms;
  a 2s cache cuts the recompute load 4x without making the UX-3 strip
  look stale (90s of dots, 2s freshness on the head). The response is
  sent AFTER the cache lock is released, so a peer that stops reading its
  socket never holds other requests behind the lock.

Event source:
  ``core/ward_producer.py`` infers placements from Live Client inventory
  deltas and calls ``core.ward_events.record_ward`` (the Live Client
  event stream exposes no WARD_PLACED). Outside a game the buffer is
  empty and this route returns an empty rolling window.

Failure modes:
  - window_s not numeric -> 400 {"ok": false, "error": "window_s must be
    numeric"}; not finite (nan / inf) or out of range -> 400 with
    "window_s must be in [5, 600]". The caller's value is never echoed.
  - a body that is not strict JSON (a non-finite number) or any other
    unexpected exception -> the fixed 500 {"ok": false, "error":
    "internal error - see logs"} through dashboard._errors.send_error
    (cause logged once with its type name, scrubbed, with the
    traceback); nothing is cached.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import ward_events
from dashboard._dispatch import equals
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

# Cache parameters.
_CACHE_TTL_S = 2.0
_WINDOW_MIN_S = 5.0
_WINDOW_MAX_S = 600.0
_DEFAULT_WINDOW_S = 90.0
# The UX-3 'uncovered lane' view never looks back further than this.
_UNCOVERED_MAX_S = 60.0

_NUMERIC_ERROR = "window_s must be numeric"
_FIXED_500_BODY = json.dumps(
    {"ok": False, "error": "internal error - see logs"}).encode("utf-8")
_RANGE_ERROR = f"window_s must be in [{_WINDOW_MIN_S:.0f}, {_WINDOW_MAX_S:.0f}]"

# S144-T-619: str.strip() with no argument also eats Unicode blanks
# (U+3000, U+00A0) and the ASCII separators U+001C..U+001F, and float()
# reads non-ASCII digits and "1_0". Strip ASCII blanks only, and let only
# ASCII letters, digits, '.', '+' and '-' reach float() - the letters keep
# "nan" / "inf" / "1e400" on the range error they already answer.
_ASCII_BLANKS = " \t\r\n\f\v"
_WINDOW_CHARS_RE = re.compile(r"[0-9A-Za-z.+-]+")

# Cache: (window_s,) -> (cached_at on time.monotonic, payload). Size-bounded:
# window_s is a client-supplied float, so distinct values would otherwise
# grow the dict without limit (audit cycle 8 slice E).
_CACHE: dict[tuple[float], tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 64


def _parse_window(qs: dict) -> tuple[float, str | None]:
    """Parse / validate the ``window_s`` query param.

    Returns ``(window_s, error)``. ``error`` is None on success;
    otherwise a fixed user-facing message (never the caller's value) and
    the route should 400.
    """
    raw = (qs.get("window_s") or [""])[0].strip(_ASCII_BLANKS)
    if not raw:
        return _DEFAULT_WINDOW_S, None
    if not _WINDOW_CHARS_RE.fullmatch(raw):
        return 0.0, _NUMERIC_ERROR
    try:
        val = float(raw)
    except ValueError:
        return 0.0, _NUMERIC_ERROR
    # NaN compares False against both bounds, so it must be refused
    # explicitly (RM-1325): it would echo as a bare NaN token the
    # browser's JSON.parse rejects, and as a cache key it never equals
    # itself, so every request would insert a fresh entry.
    if not math.isfinite(val) or val < _WINDOW_MIN_S or val > _WINDOW_MAX_S:
        return 0.0, _RANGE_ERROR
    return val, None


def _build_payload(window_s: float, now_s: float) -> dict:
    """Shape ONE rolling-window snapshot from ``core.ward_events``.

    The buffer is read once (``recent_wards``); counts and the uncovered
    lists are derived from that list with the store's own rules
    (``counts_by_lane`` / ``lanes_uncovered``), so the body is internally
    consistent even while the producer records wards (S144-T-619 - it
    used to read the buffer five times). No HTTP / I/O here.
    """
    wards = ward_events.recent_wards(now_s=now_s, window_s=window_s)
    counts: dict[str, dict[str, int]] = {
        "ally":  dict.fromkeys(ward_events.LANES, 0),
        "enemy": dict.fromkeys(ward_events.LANES, 0),
    }
    # The 'uncovered lane' semantic uses a 60s window per UX-3 spec,
    # clamped to MIN(window_s, 60) so a caller asking for window_s=30
    # sees the uncovered list relative to their own narrower view. Same
    # cutoff expression as recent_wards (now - window <= ts); every ward
    # here is already <= now_s.
    uncovered_cutoff = now_s - min(window_s, _UNCOVERED_MAX_S)
    seen: dict[str, set[str]] = {"ally": set(), "enemy": set()}
    for ev in wards:
        side = ev.get("side")
        lane = ev.get("lane", "unknown")
        if side in counts and lane in counts[side]:
            counts[side][lane] += 1
        if (side in seen and lane in ward_events.NAMED_LANES
                and ev.get("ts") >= uncovered_cutoff):
            seen[side].add(lane)
    return {
        "ok":       True,
        "now_s":    round(now_s, 3),
        "window_s": window_s,
        "wards":    wards,
        "counts":   counts,
        "lanes_uncovered_ally":  [
            lane for lane in ward_events.NAMED_LANES
            if lane not in seen["ally"]],
        "lanes_uncovered_enemy": [
            lane for lane in ward_events.NAMED_LANES
            if lane not in seen["enemy"]],
        "buffer_size": ward_events.buffer_size(),
    }


def _elapsed_ms(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


def _serve_ward_heat(h) -> None:
    """GET /api/ward-heat - route entry point."""
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        window_s, err = _parse_window(qs)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err}).encode("utf-8"),
                    "application/json")
            return

        cache_key = (window_s,)
        mono = time.monotonic()
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
        # Sent outside the lock: a stalled socket write must not hold
        # every other request behind _CACHE_LOCK (S144-T-619). The cached
        # dict is never mutated after insert, so reading it here is safe.
        if cached is not None and 0.0 <= mono - cached[0] < _CACHE_TTL_S:
            payload = dict(cached[1])
            payload["cached"] = True
            payload["elapsed_ms"] = _elapsed_ms(t0)
            h._send(200, json.dumps(payload, allow_nan=False).encode("utf-8"),
                    "application/json")
            return

        payload = _build_payload(window_s, time.time())
        # Cache the payload WITHOUT the per-request fields so a cache
        # hit always reports its own elapsed_ms + cached=True.
        cacheable = dict(payload)
        payload["cached"] = False
        payload["elapsed_ms"] = _elapsed_ms(t0)
        # allow_nan=False: a non-finite number becomes the fixed 500
        # below, before anything is cached, never a bare NaN token the
        # browser's JSON.parse rejects for the whole body.
        body = json.dumps(payload, allow_nan=False).encode("utf-8")

        with _CACHE_LOCK:
            _CACHE[cache_key] = (mono, cacheable)
            if len(_CACHE) > _CACHE_MAX:
                victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:16]
                for k, _ in victims:
                    _CACHE.pop(k, None)

        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001
        # RM-835: a fixed body (same bytes as before); send_error logs the
        # cause once with its type name, scrubbed, with the traceback. Raw
        # exception text never reaches the client.
        try:
            send_error(h, exc, fields={"ok": False}, log_traceback=True)
        except OSError:
            # The client went away while the error was being sent;
            # nothing left to tell it.
            pass
        except Exception:  # noqa: BLE001
            # send_error itself failed before sending (an exception whose
            # str() raises): still answer the same fixed 500 body.
            log.warning("api/ward-heat: error envelope failed")
            try:
                h._send(500, _FIXED_500_BODY, "application/json")
            except OSError:
                pass


def _reset_caches() -> None:
    """Test-only: clear the response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/ward-heat"), _serve_ward_heat),
]
