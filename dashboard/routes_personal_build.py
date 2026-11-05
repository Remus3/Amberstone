"""GET /api/personal-build - personal per-champion build win-rate (read-only).

Serves ``core.personal_build_wr.compute_personal_build`` over the LOCAL
rewind_history.db. Surfaces which completed items the operator actually WINS
with on a champion (confidence-weighted lift vs their own baseline), an additive
"your best build" read alongside the DS engine recommendation - no Riot API, no
Claude. Closes the personal-WR-build-override local-data half from
docs/_archive/COMPETITOR_LIFT_2026-06-16.md.

Request shape:
  GET /api/personal-build?champion=Vayne[&mode=sr|aram|arena]

  champion : required champion display name (e.g. Vayne, Kai'Sa) or numeric
             champion id, 1-40 chars of letters, digits, space, ' . & with at
             least one letter or digit. Empty or malformed -> 400.
  mode     : sr | aram | arena (case-insensitive). Default sr. Anything else
             -> 400.

Response is exactly ``compute_personal_build(...)``'s dict plus ``cached`` (bool)
and ``elapsed_ms`` (int, never negative). See ``core.personal_build_wr._empty``
for the shape. A compute that raises, returns a non-dict or returns a value
that is not strict JSON (NaN / Infinity) is a degraded 503
``{"ok": false, "error": "rewind history unavailable"}``; the body is always
strict JSON.

Cache: 5 min in-process on the MONOTONIC clock (a wall-clock step can neither
pin an entry fresh nor make elapsed_ms negative), keyed by (mode, lowercased
champion), at most ``_CACHE_MAX`` entries. Only a verdict about the data
(``confidence`` ok / thin / insufficient) is cached; a transient empty shell
(read_error from a locked DB, no_db, bad_mode) is recomputed on the next poll.
A cache hit echoes THIS request's champion string. The compute scans the rewind
db; a panel re-polling on a timer would otherwise hot-loop the DB. The cache
lock is never held across the response write.

A raw exception string is NEVER leaked to the client, and a failed response
write (client gone) is not answered with a second response.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import personal_build_wr
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_VALID_MODES = ("sr", "aram", "arena")
# Champion display names: letters/digits/space + the apostrophe/period/ampersand
# that appear in real names (Kai'Sa, Dr. Mundo, Nunu & Willump), or a numeric
# champion id (the champ-select panel sends cs.my_champion). Bounded length, and
# at least one letter or digit so "..." or "&" never reaches the DB scan.
_CHAMP_RE = re.compile(r"(?=[^A-Za-z0-9]*[A-Za-z0-9])[A-Za-z0-9 '.&]{1,40}")
_CHAMP_ERR = (
    "champion query param required: a champion name or numeric id "
    "(1-40 letters, digits, space, ' . &)"
)

_CT_JSON = "application/json"
_UNAVAILABLE = {"ok": False, "error": "rewind history unavailable"}
_INTERNAL = {"ok": False, "error": "internal error - see logs"}

# confidence values that are a verdict about the operator's data; anything else
# (read_error, no_db, bad_mode, an unknown token) is transient or a fault.
_CACHEABLE_CONFIDENCE = frozenset({"ok", "thin", "insufficient"})

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256
_CACHE_EVICT = 64


def _clock() -> float:
    return time.monotonic()


def _elapsed_ms(t0: float) -> int:
    return max(0, int((_clock() - t0) * 1000))


def _dumps(obj: object) -> bytes:
    """Strict JSON bytes; raises ValueError on NaN / Infinity."""
    return json.dumps(obj, allow_nan=False).encode("utf-8")


def _cache_get(key: tuple, now: float) -> dict | None:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is None:
            return None
        age = now - hit[0]
        if not 0.0 <= age < _CACHE_TTL_S:
            _CACHE.pop(key, None)
            return None
        return dict(hit[1])


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return ("sr", None)
    if raw not in _VALID_MODES:
        return ("", f"mode must be one of {', '.join(_VALID_MODES)}")
    return (raw, None)


def _respond(h, t0: float) -> tuple[int, bytes]:
    """Decide the response. Never writes to the handler."""
    qs = parse_qs(urlparse(h.path).query or "")
    champ_raw = (qs.get("champion") or [""])[0].strip()
    mode_raw = (qs.get("mode") or [""])[0].strip().lower()

    if not champ_raw or not _CHAMP_RE.fullmatch(champ_raw):
        return 400, _dumps({"ok": False, "error": _CHAMP_ERR})
    mode, err = _parse_mode(mode_raw)
    if err:
        return 400, _dumps({"ok": False, "error": err})

    key = (mode, champ_raw.lower())
    cached = _cache_get(key, _clock())
    if cached is not None:
        cached["champion"] = champ_raw
        cached["cached"] = True
        cached["elapsed_ms"] = _elapsed_ms(t0)
        return 200, _dumps(cached)

    now = _clock()
    try:
        payload = personal_build_wr.compute_personal_build(champ_raw, mode)
    except Exception as exc:  # noqa: BLE001 - degraded 503, raw text to logs only
        log.warning("api/personal-build compute: %s", exc)
        return 503, _dumps(_UNAVAILABLE)
    if not isinstance(payload, dict):
        log.warning("api/personal-build compute returned %s, not a dict",
                    type(payload).__name__)
        return 503, _dumps(_UNAVAILABLE)

    body = dict(payload)
    body["cached"] = False
    body["elapsed_ms"] = _elapsed_ms(t0)
    try:
        raw = _dumps(body)
    except (ValueError, TypeError, RecursionError) as exc:
        log.warning("api/personal-build payload is not strict JSON: %s", exc)
        return 503, _dumps(_UNAVAILABLE)

    if payload.get("confidence") in _CACHEABLE_CONFIDENCE:
        _cache_put(key, now, dict(payload))
    return 200, raw


def _serve_personal_build(h) -> None:
    t0 = _clock()
    try:
        status, body = _respond(h, t0)
    except Exception as exc:  # noqa: BLE001 - route boundary, never a raw trace
        log.warning("api/personal-build: %s", exc)
        status, body = 500, _dumps(_INTERNAL)
    try:
        h._send(status, body, _CT_JSON)
    except OSError as exc:
        # Client gone mid-write: nothing to answer, and a second response on
        # the same connection would only corrupt it.
        log.debug("api/personal-build send failed: %s", exc)


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/personal-build"), _serve_personal_build),
]
