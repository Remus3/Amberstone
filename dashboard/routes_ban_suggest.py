"""GET /api/ban-suggest - HURTS-THEM / HELPS-US ban suggestion ratings.

Closes the "genuine market gap" surfaced by the 2026-05-20 research wave:
every other tool (Aggregator C / Overlay App E / Overlay App F / Draft Tool L / Draft Tool Z15 /
Draft Tool Z8) silently picks one logic and never tells the user which.
This endpoint surfaces BOTH ratings per candidate and lets the caller
display the toggle explicitly.

Composes on:
  - core.draft_elo            (winrate_to_rating)
  - core.draft_elo_db         (solo, pair, matchup queries)
  - core.smoothed_rates       (Laplace prior)

Request shape:
  GET /api/ban-suggest?ally=22,64,55,89,12&enemy=42,67,69,33,99
       &candidates=8,1,103,202,432[&queue=420]

  ally       : 1-5 ally champion ids (locked picks so far).
  enemy      : 0-5 enemy champion ids (commits so far).
  candidates : 1-30 champion ids to evaluate as ban candidates.
               Each candidate is scored independently.
  queue      : optional comma list of 1-16 queue ids (default: the
               draft_elo_db.DEFAULT_SR_QUEUES set).

  Validation (the trust boundary; any violation is a 400 naming the
  field): every id is 1-6 ASCII decimal digits (no sign, no
  underscore, no non-ASCII digit); champion ids are >= 1, queue ids
  >= 0; no id repeats within one list. The 400 names the field and
  the expected shape only, never the caller's token (RM-1233).

Response shape:
  {
    "ok":         true,
    "ally":       [...],
    "enemy":      [...],
    "candidates": [
      {
        "champ_id":         int,
        "solo_rating":      float,
        "hurts_them_score": float,  # rating of candidate's avg
                                    # ENEMY-pair WR with current allies +
                                    # candidate's avg matchup-WR vs allies
        "helps_us_score":   float,  # rating of candidate's avg
                                    # ALLY-pair WR with current allies
        "solo_n":           int,    # games behind solo_rating
        "min_solo_n":       int,    # sample-density floor (== solo_n)
        "min_pair_n":       int,    # min games over the same-team
                                    # pair queries (0 if none ran)
        "min_matchup_n":    int,    # min games over the cross-team
                                    # matchup queries (0 if none ran)
      },
      ...
    ],
    "queue_ids":   [...],
    "cached":      false,
    "elapsed_ms":  N,
  }

A LARGE positive ``hurts_them_score`` means this candidate is a threat
to OUR team (high matchup advantage vs us). Banning HURTS THEM by
removing one of their stronger options.

A LARGE positive ``helps_us_score`` means we WOULD benefit from this
candidate on our team (they pair well with our locked allies). Banning
HELPS US by preventing the enemy from picking it before we can.

Mode-selection logic lives on the CALLER (the frontend toggle); the
backend always returns both scores.

Status codes: 400 for invalid input; 503 "rewind history unavailable"
only when the rewind DB cannot be read (sqlite3.Error / OSError); 500
"internal error - see logs" for anything else, logged with a
traceback. Raw exception text never reaches the response body.

Caching: responses are cached for _CACHE_TTL_S on a MONOTONIC clock,
keyed on the order-insensitive id sets plus the RESOLVED queue set. A
cache hit still echoes the caller's own ally / enemy order and returns
candidates in the caller's order. No response is written while the
cache lock is held.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import draft_elo, draft_elo_db
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
# Cycle-8 audit: entries were never evicted (TTL only gates serving),
# so long uptimes grew the dict without bound. Cap + drop-oldest.
_CACHE_MAX = 256
_CACHE_EVICT = 64

# Input bounds (s144 true-audit cycle 79). An id is 1-6 ASCII digits:
# champion ids are 3 digits today and queue ids 4, and the cap keeps
# every accepted value far inside SQLite's int64 (an unbounded int()
# used to reach SQLite as an OverflowError and come back as a 503).
_ID_RE = re.compile(r"[0-9]{1,6}")
_MAX_QUEUE_IDS = 16

# 400 texts (RM-1233). Each names the expected shape and never the
# caller's token or value; the route prefixes the parameter name. Was
# ``invalid id '<clipped repr>'``, ``id <n> is below <m>`` and
# ``duplicate id <n>``, the same echo the sibling /api/post-game-wpa 400
# had dropped (its ``_MATCH_ID_ERROR``).
_ERR_BAD_TOKEN = "each id must be 1-6 ASCII digits"
_ERR_DUPLICATE = "duplicate ids are not allowed"


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(),
                             key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_ids(raw: str, min_count: int, max_count: int, *,
               min_value: int) -> tuple[list[int], str | None]:
    """Parse a comma list of ids. Returns (ids, error-or-None).

    Order is preserved. Every token must match ``_ID_RE`` (ASCII digits
    only - ``int()`` alone accepts a sign, ``_`` separators and
    non-ASCII digits) and be >= ``min_value``; duplicates are refused.
    An error names the expected shape only, never a token (RM-1233).
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) < min_count or len(parts) > max_count:
        return ([], f"expected {min_count}-{max_count} comma-separated ids")
    ids: list[int] = []
    seen: set[int] = set()
    for p in parts:
        if not _ID_RE.fullmatch(p):
            return ([], _ERR_BAD_TOKEN)
        value = int(p)
        if value < min_value:
            return ([], f"each id must be {min_value} or more")
        if value in seen:
            return ([], _ERR_DUPLICATE)
        seen.add(value)
        ids.append(value)
    return (ids, None)


def _parse_int_list(raw: str, min_count: int, max_count: int
                    ) -> tuple[list[int], str | None]:
    """Champion-id list (ids >= 1). A blank value is a missing field."""
    if not raw:
        return ([], "missing required ids")
    return _parse_ids(raw, min_count, max_count, min_value=1)


def _parse_queues(raw: str) -> tuple[tuple[int, ...] | None, str | None]:
    """Queue-id list (ids >= 0). Blank = use the default queue set.

    A value that is present but holds no id (``queue=,``) is refused:
    it used to become an EMPTY filter, which dropped the queue clause
    from every query and cached the all-queues answer under the
    default-queue key.
    """
    if not raw:
        return (None, None)
    ids, err = _parse_ids(raw, 1, _MAX_QUEUE_IDS, min_value=0)
    if err:
        return (None, err)
    return (tuple(ids), None)


def _resolve_queues(queues: tuple[int, ...] | None) -> tuple[int, ...]:
    return queues if queues is not None else draft_elo_db.DEFAULT_SR_QUEUES


def _cache_key(ally: list[int], enemy: list[int], cands: list[int],
               queues: tuple[int, ...] | None) -> tuple:
    """Order-insensitive key over the id sets and the RESOLVED queues."""
    return (
        tuple(sorted(ally)),
        tuple(sorted(enemy)),
        tuple(sorted(cands)),
        tuple(sorted(_resolve_queues(queues))),
    )


def _candidate_scores(conn, cand: int, ally: list[int], enemy: list[int],
                      queues) -> dict:
    """Compute solo + hurts_them + helps_us ratings for one candidate."""
    # Solo prior: cand's lifetime smoothed WR -> rating.
    w_solo, g_solo, r_solo = draft_elo_db.solo_winrate(conn, cand, queues)
    solo_rating = draft_elo.winrate_to_rating(r_solo)

    # HURTS-THEM signal:
    #   - candidate paired with each ENEMY (same-team) -> if those pair WRs
    #     are high, this candidate strengthens the enemy roster
    #   - candidate cross-team vs each ALLY -> if those matchup WRs are
    #     high from the candidate's perspective, they're a threat to us
    #
    # Average both; convert mean WR to a rating. Sample density is the min
    # across the contributing queries.
    hurts_pair_rates: list[float] = []
    hurts_pair_n: list[int] = []
    for e in enemy:
        if e == cand:
            continue
        _, n, r = draft_elo_db.pair_winrate(conn, cand, e, queues, side="ally")
        hurts_pair_rates.append(r)
        hurts_pair_n.append(n)
    hurts_matchup_rates: list[float] = []
    hurts_matchup_n: list[int] = []
    for a in ally:
        if a == cand:
            continue
        # cand's WR when they appear on enemy team vs `a` on ally side.
        # core.draft_elo_db.matchup_winrate returns the FIRST-arg
        # perspective; passing (cand, a) gives candidate's win-rate when
        # they faced `a`. A high value here means cand BEATS `a`.
        _, n, r = draft_elo_db.matchup_winrate(conn, cand, a, queues)
        hurts_matchup_rates.append(r)
        hurts_matchup_n.append(n)
    hurts_them_rate = _mean_or_neutral(hurts_pair_rates + hurts_matchup_rates)
    hurts_them_score = draft_elo.winrate_to_rating(hurts_them_rate)

    # HELPS-US signal:
    #   candidate paired with each ALLY (same-team) -> if those pair WRs
    #   are high, this candidate strengthens OUR roster if we pick them.
    helps_pair_rates: list[float] = []
    helps_pair_n: list[int] = []
    for a in ally:
        if a == cand:
            continue
        _, n, r = draft_elo_db.pair_winrate(conn, cand, a, queues, side="ally")
        helps_pair_rates.append(r)
        helps_pair_n.append(n)
    helps_us_rate = _mean_or_neutral(helps_pair_rates)
    helps_us_score = draft_elo.winrate_to_rating(helps_us_rate)

    pair_ns = hurts_pair_n + helps_pair_n
    min_pair_n = min(pair_ns) if pair_ns else 0
    min_matchup_n = min(hurts_matchup_n) if hurts_matchup_n else 0

    return {
        "champ_id":         cand,
        "solo_rating":      solo_rating,
        "solo_n":           g_solo,
        "hurts_them_score": hurts_them_score,
        "helps_us_score":   helps_us_score,
        "min_solo_n":       g_solo,
        "min_pair_n":       min_pair_n,
        "min_matchup_n":    min_matchup_n,
    }


def _mean_or_neutral(values: list[float]) -> float:
    if not values:
        return 0.5
    return sum(values) / len(values)


def _compute(ally: list[int], enemy: list[int], candidates: list[int],
             queues: tuple[int, ...] | None) -> dict:
    conn = draft_elo_db.open_ro()
    try:
        qids = _resolve_queues(queues)
        cand_payloads = [
            _candidate_scores(conn, c, ally, enemy, qids) for c in candidates
        ]
        return {
            "ok":         True,
            "ally":       list(ally),
            "enemy":      list(enemy),
            "candidates": cand_payloads,
            "queue_ids":  list(qids),
        }
    finally:
        try:
            conn.close()
        except sqlite3.Error as exc:
            log.debug("api/ban-suggest: close failed: %s", exc)


def _send_json(h, status: int, payload: dict) -> None:
    h._send(status, json.dumps(payload).encode("utf-8"), "application/json")


def _bad_request(h, error: str) -> None:
    _send_json(h, 400, {"ok": False, "error": error})


def _respond(payload: dict, ally: list[int], enemy: list[int],
             cands: list[int], *, cached: bool, t0: float) -> dict:
    """Shape a stored payload for THIS request.

    The cache key is order-insensitive, so a stored payload carries the
    first caller's ordering; the echo and the candidate order are
    rebuilt from the current request. The stored payload is never
    mutated.
    """
    by_id = {c["champ_id"]: c for c in payload["candidates"]}
    out = dict(payload)
    out["ally"] = list(ally)
    out["enemy"] = list(enemy)
    out["candidates"] = [by_id[c] for c in cands]
    out["cached"] = cached
    out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def _serve_ban_suggest(h) -> None:
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        ally_raw = (qs.get("ally") or [""])[0].strip()
        enemy_raw = (qs.get("enemy") or [""])[0].strip()
        cand_raw = (qs.get("candidates") or [""])[0].strip()
        queue_raw = (qs.get("queue") or [""])[0].strip()

        ally_ids, err = _parse_int_list(ally_raw, 1, 5)
        if err:
            _bad_request(h, f"ally: {err}")
            return
        enemy_ids, err = (_parse_ids(enemy_raw, 0, 5, min_value=1)
                          if enemy_raw else ([], None))
        if err:
            _bad_request(h, f"enemy: {err}")
            return
        cand_ids, err = _parse_int_list(cand_raw, 1, 30)
        if err:
            _bad_request(h, f"candidates: {err}")
            return
        queue_ids, err = _parse_queues(queue_raw)
        if err:
            _bad_request(h, f"queue: {err}")
            return

        key = _cache_key(ally_ids, enemy_ids, cand_ids, queue_ids)
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        # The response is written OUTSIDE the lock: a slow client must
        # not stall every other ban-suggest request.
        if cached and (now - cached[0]) < _CACHE_TTL_S:
            _send_json(h, 200, _respond(cached[1], ally_ids, enemy_ids,
                                        cand_ids, cached=True, t0=t0))
            return

        try:
            payload = _compute(ally_ids, enemy_ids, cand_ids, queue_ids)
        except (sqlite3.Error, OSError) as exc:
            log.warning("api/ban-suggest compute: %s: %s",
                        type(exc).__name__, exc)
            _send_json(h, 503, {"ok": False,
                                "error": "rewind history unavailable"})
            return

        _cache_put(key, now, payload)
        _send_json(h, 200, _respond(payload, ally_ids, enemy_ids, cand_ids,
                                    cached=False, t0=t0))
    except Exception:  # route boundary: always answer
        log.exception("api/ban-suggest: unexpected failure")
        try:
            # Raw exception text stays in the log only.
            _send_json(h, 500, {"ok": False,
                                "error": "internal error - see logs"})
        except OSError as exc:
            log.debug("api/ban-suggest: 500 send failed: %s", exc)


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/ban-suggest"), _serve_ban_suggest),
]
