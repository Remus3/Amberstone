"""GET /api/session-hygiene - deterministic tilt / readiness analytics (read-only).

Serves core.session_hygiene.compute_session_hygiene over the LOCAL
rewind_history.db: the tracked player's own win-rate conditioned on session
context (position in session, hour, weekday, rust, same-champ requeue) plus a
bounded 0-100 "Should I Queue" readiness odds-shift. Computed entirely over
the operator's own corpus (no global / Riot / Claude dependency) - the
Haiku-to-ZERO north star. The panel polls this thin HTTP surface.

Request shape:
  GET /api/session-hygiene[?queue=450[,420]]

  queue : optional comma-separated list of 1-16 queue ids (e.g. 450 for
          ARAM, 420 for ranked solo). Omitted, blank or whitespace-only ->
          all games.

  Validation (the trust boundary; any violation is a 400 whose error
  starts with "queue:"): every id is 1-6 ASCII decimal digits (no sign,
  no "_" separator, no non-ASCII digit - int() alone accepts all three);
  no id repeats; a value that holds no id at all ("queue=,") is refused.
  A rejected token is never echoed in the error body (RM-1255: the text
  names the expected shape only; it was a clipped repr). (s144 true-audit cycle
  84: an over-long id reached SQLite as an OverflowError - not a
  sqlite3.Error, so it escaped the core's "never raises" catch - and
  came back as a 500; "queue=," became an EMPTY filter the core answers
  with an empty corpus, a 200 that reads as "no games played"; and a
  long list could reach SQLite's bound-variable limit, which the core
  also turns into a silent empty corpus.)

Response is compute_session_hygiene(...)'s dict plus cached (bool) and
elapsed_ms (int). readiness.score is NULL (JSON null) with
readiness.state == "unknown" when no context bucket has enough games (Y-04);
readiness.state / flags / basis are appended after the older keys. This route
passes the dict through untouched, so no transform here may coerce the null.

Cache: 5min in-process on a MONOTONIC clock, keyed by the SORTED queue set
(so "450,420" and "420,450" share an entry) - mirrors routes_duration_winrate
so a re-polling panel does not turn the corpus scan into a DB hot loop. now_ms
is NOT part of the key: readiness is context-at-request, so a fresh compute on
cache miss reads the wall clock and a cached hit is at most 5min stale, which
is well within the 2h session gap. The stored entry is never mutated, and no
response is written while the cache lock is held.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad queue value -> 400 with a short clear error
  - any other exception -> 500 "internal error - see logs"; the failure is
    logged with its traceback.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import session_hygiene
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 64
_CACHE_EVICT = 16

# Input bounds (s144 true-audit cycle 84). Queue ids are 1-4 digits today;
# 6 keeps every accepted value far inside SQLite's int64.
_ID_RE = re.compile(r"[0-9]{1,6}")
_MAX_QUEUE_IDS = 16
# A rejected token is never echoed in a 400 (RM-1255 / RM-1233): the text
# names the expected shape only, and the handler prefixes the parameter.
_ERR_BAD_TOKEN = "each id must be 1-6 ASCII digits"
_ERR_DUPLICATE = "duplicate ids are not allowed"


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_queue(raw: str) -> tuple[tuple[int, ...] | None, str | None]:
    """(None, None) when omitted / blank (= all games); (ids, None) when
    valid, in the caller's order; (None, error) otherwise."""
    if not raw:
        return (None, None)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts or len(parts) > _MAX_QUEUE_IDS:
        return (None, f"expected 1-{_MAX_QUEUE_IDS} queue ids, "
                      f"got {len(parts)}")
    ids: list[int] = []
    for p in parts:
        if not _ID_RE.fullmatch(p):
            return (None, _ERR_BAD_TOKEN)
        value = int(p)
        if value in ids:
            return (None, _ERR_DUPLICATE)
        ids.append(value)
    return (tuple(ids), None)


def _send_json(h, status: int, payload: dict) -> None:
    h._send(status, json.dumps(payload).encode("utf-8"), "application/json")


def _respond(stored: dict, *, cached: bool, t0: float) -> dict:
    """A per-request copy of a stored payload; the stored dict is never
    mutated."""
    out = dict(stored)
    out["cached"] = cached
    out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def _serve_session_hygiene(h) -> None:
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        queue_raw = (qs.get("queue") or [""])[0].strip()

        queue_ids, err = _parse_queue(queue_raw)
        if err:
            _send_json(h, 400, {"ok": False, "error": f"queue: {err}"})
            return

        key = (None if queue_ids is None else tuple(sorted(queue_ids)),)
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        # The response is written OUTSIDE the lock: a slow client must not
        # stall every other session-hygiene request.
        if cached and (now - cached[0]) < _CACHE_TTL_S:
            _send_json(h, 200, _respond(cached[1], cached=True, t0=t0))
            return

        payload = session_hygiene.compute_session_hygiene(queue_ids=queue_ids)
        stored = dict(payload)
        stored.pop("cached", None)
        stored.pop("elapsed_ms", None)
        _cache_put(key, now, stored)

        _send_json(h, 200, _respond(stored, cached=False, t0=t0))
    except Exception:  # route boundary: always answer
        log.exception("api/session-hygiene: unexpected failure")
        try:
            # Raw exception text stays in the log only.
            _send_json(h, 500, {"ok": False,
                                "error": "internal error - see logs"})
        except OSError as exc:
            log.debug("api/session-hygiene: 500 send failed: %s", exc)


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/session-hygiene"), _serve_session_hygiene),
]
