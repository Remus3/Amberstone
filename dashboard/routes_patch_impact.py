"""GET /api/patch-impact - what this patch changed for the champions you play.

Serves core.patch_impact.compute_patch_impact: the cross-patch Daemon Slayer
snapshot diff (RM-110) intersected with the tracked player's own
rewind_history.db play counts. Fully local - no Riot, no Claude, no network.
Live client: web/js/panels/patch_impact.js (no query; it reads the defaults).

Request shape:
  GET /api/patch-impact[?mode=sr|aram|arena][&top=12][&min_games=5]
                       [&old=16.13.1][&new=16.14.1]

  Every value has ASCII blanks (space, tab, CR, LF, FF, VT) stripped from
  both ends, never Unicode ones (S144-T-626: str.strip() also ate U+3000).
  mode      : sr | aram | arena. Default aram (the ARAM-dominant corpus).
              Anything else -> 400.
  top       : 1..50 champions to return, default 12.
  min_games : 1..500 games before a champion counts as yours, default 5.
              Both are an optional ASCII sign then ASCII digits, else 400
              "<name> must be an integer" ("1_0" and non-ASCII digits are
              refused); a well-formed value outside the range, however
              long, is 400 "<name> must be between 1 and <hi>".
  old / new : optional patch pair. A value is first shape-checked (ASCII
              digits: 1-4 groups of 1-4 digits joined by dots) and
              then checked against the snapshot dirs actually on disk; either
              failure is 400 "<name> is not a snapshot on disk", never a path
              handed to the diff tool (its _resolve() would happily take a
              directory). The snapshot dirs are listed only when old or new
              is given.

  No 400 echoes the caller's value.

Response is compute_patch_impact(...)'s dict plus cached (bool) and elapsed_ms
(int, perf_counter, never negative). A non-finite number anywhere in it (the
diffed snapshot values come from JSON files that may carry NaN / Infinity
tokens) is served as null - the panel renders null as "-" - and the body is
dumped with allow_nan=False, so anything that still is not strict JSON is the
fixed 500 below, never a bare NaN token the browser's JSON.parse rejects.

Cache: 5min in-process keyed by (mode, top, min_games, old, new) - the diff
walks two full snapshots, so a re-polling panel must not re-run it per tick.
Timed on time.monotonic (a wall-clock step never keeps an entry fresh; an
entry stamped in the future is never served). Only a payload with no stated
reason is cached: a degraded answer (the diff failed, no readable match
history yet, ...) is recomputed on the next request, so one transient
failure does not blank the card for the whole TTL. A response is written to
the socket after the cache lock is released, so a client that stops reading
never holds other requests behind the lock.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode / top / min_games / patch name -> 400 with a short fixed error
  - any other exception -> the fixed 500 {"ok": false, "error": "internal
    error - see logs"} through dashboard._errors.send_error (cause logged
    once with its type name, scrubbed, with the traceback); not cached.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import patch_impact
from dashboard._dispatch import equals
from dashboard._errors import GENERIC_ERROR, send_error

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
# (mode, top, min_games, old, new) -> (stamped at, on time.monotonic; payload
# without the per-request cached / elapsed_ms fields). Never mutated after
# insert, so a reader may use an entry after releasing the lock.
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 128
_CACHE_EVICT = 32

MAX_TOP = 50
MAX_MIN_GAMES = 500

_FIXED_500_BODY = json.dumps(
    {"ok": False, "error": GENERIC_ERROR}).encode("utf-8")

# S144-T-626: ASCII-only parsing. str.strip() with no argument also strips
# Unicode blanks, and int() reads "1_0" and non-ASCII digits.
_ASCII_BLANKS = " \t\r\n\f\v"
_INT_RE = re.compile(r"[+-]?[0-9]+")
# Significant digits (sign and leading zeros dropped) past this are out of
# range without asking int(), which refuses past 4300 digits and would call
# a long well-formed value "not an integer". Every bound here has <= 3.
_INT_MAX_DIGITS = 6
# A DS snapshot dir name: dot-separated ASCII digit groups ("16.14.1"); the
# group bounds cap the length at 19 characters.
_PATCH_RE = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,4}){0,3}")


def _first(qs: dict, name: str) -> str:
    return (qs.get(name) or [""])[0].strip(_ASCII_BLANKS)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (patch_impact.DEFAULT_MODE, None)
    if raw not in patch_impact.VALID_MODES:
        return ("", f"mode must be one of {', '.join(patch_impact.VALID_MODES)}")
    return (raw, None)


def _parse_int(raw: str, name: str, default: int, hi: int) -> tuple[int, str | None]:
    if not raw:
        return (default, None)
    if not _INT_RE.fullmatch(raw):
        return (0, f"{name} must be an integer")
    digits = raw.lstrip("+-").lstrip("0") or "0"
    if len(digits) > _INT_MAX_DIGITS:
        return (0, f"{name} must be between 1 and {hi}")
    value = -int(digits) if raw[0] == "-" else int(digits)
    if not (1 <= value <= hi):
        return (0, f"{name} must be between 1 and {hi}")
    return (value, None)


def _parse_patches(old_raw: str, new_raw: str
                   ) -> tuple[tuple[str | None, str | None], str | None]:
    """((old, new), None) or ((None, None), fixed 400 message).

    old is judged before new, as before. A value is shape-checked first, so
    junk never costs a directory listing; the snapshot dirs are listed at
    most once, and only when a well-shaped value needs the membership check
    (with neither given, compute lists them itself).
    """
    known: list | None = None
    out: list[str | None] = []
    for raw, name in ((old_raw, "old"), (new_raw, "new")):
        if not raw:
            out.append(None)
            continue
        if not _PATCH_RE.fullmatch(raw):
            return ((None, None), f"{name} is not a snapshot on disk")
        if known is None:
            known = patch_impact.available_patches()
        if raw not in known:
            return ((None, None), f"{name} is not a snapshot on disk")
        out.append(raw)
    return ((out[0], out[1]), None)


def _parse_query(path: str) -> tuple[tuple | None, str | None]:
    """(cache key, None) or (None, fixed 400 message)."""
    qs = parse_qs(urlparse(path).query or "")
    mode, err = _parse_mode(_first(qs, "mode"))
    if err:
        return (None, err)
    top, err = _parse_int(_first(qs, "top"), "top",
                          patch_impact.DEFAULT_TOP_N, MAX_TOP)
    if err:
        return (None, err)
    min_games, err = _parse_int(_first(qs, "min_games"), "min_games",
                                patch_impact.DEFAULT_MIN_GAMES, MAX_MIN_GAMES)
    if err:
        return (None, err)
    (old, new), err = _parse_patches(_first(qs, "old"), _first(qs, "new"))
    if err:
        return (None, err)
    return ((mode, top, min_games, old, new), None)


def _json_safe(obj):
    """A copy of ``obj`` with every non-finite float replaced by None.

    Dicts and lists / tuples are walked (a tuple becomes a list, as
    json.dumps would emit it); every other value is returned as is, so a
    finite payload serialises to the same bytes as before.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _elapsed_ms(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


def _cache_get(key: tuple, now: float) -> dict | None:
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None and 0.0 <= now - cached[0] < _CACHE_TTL_S:
        return cached[1]
    return None


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _send_json(h, status: int, payload: dict) -> None:
    h._send(status, json.dumps(payload, allow_nan=False).encode("utf-8"),
            "application/json")


def _serve_patch_impact(h) -> None:
    t0 = time.perf_counter()
    try:
        key, err = _parse_query(h.path)
        if err:
            _send_json(h, 400, {"ok": False, "error": err})
            return

        now = time.monotonic()
        cached = _cache_get(key, now)
        if cached is not None:
            payload = dict(cached)
            payload["cached"] = True
            payload["elapsed_ms"] = _elapsed_ms(t0)
            _send_json(h, 200, payload)
            return

        mode, top, min_games, old, new = key
        payload = _json_safe(patch_impact.compute_patch_impact(
            mode=mode, old_patch=old, new_patch=new, top_n=top,
            min_games=min_games))
        cacheable = dict(payload)
        payload["cached"] = False
        payload["elapsed_ms"] = _elapsed_ms(t0)
        # Dumped before anything is cached: a body that is not strict JSON
        # goes to the fixed 500 below and is never stored.
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        if cacheable.get("reason") is None:
            _cache_put(key, now, cacheable)
        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001 - last resort: fixed 500, cause logged
        try:
            send_error(h, exc, fields={"ok": False}, log_traceback=True)
        except OSError:
            # The client went away while the error was being sent.
            pass
        except Exception:  # noqa: BLE001 - send_error failed before sending
            # (an exception whose str() raises): same fixed 500 body.
            log.warning("api/patch-impact: error envelope failed")
            try:
                h._send(500, _FIXED_500_BODY, "application/json")
            except OSError:
                pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/patch-impact"), _serve_patch_impact),
]
