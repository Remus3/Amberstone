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

  ally       : 5 ally champion ids (locked picks).
  enemy      : 0-5 enemy champion ids (commits so far).
  candidates : list of champion ids to evaluate as ban candidates.
               Each candidate is scored independently. 5-30 is typical.
  queue      : optional queue id filter (default SR set).

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
        "min_solo_n":       int,    # sample-density floor
        "min_pair_n":       int,
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
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import draft_elo, draft_elo_db
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _parse_int_list(raw: str, min_count: int, max_count: int
                    ) -> tuple[list[int], str | None]:
    if not raw:
        return ([], "missing required ids")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) < min_count or len(parts) > max_count:
        return ([], f"expected {min_count}-{max_count} ids, got {len(parts)}")
    ids: list[int] = []
    for p in parts:
        try:
            ids.append(int(p))
        except ValueError:
            return ([], f"non-integer id {p!r}")
    return (ids, None)


def _parse_queues(raw: str) -> tuple[tuple[int, ...] | None, str | None]:
    if not raw:
        return (None, None)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            return (None, f"non-integer queue id {p!r}")
    return (tuple(out), None)


def _cache_key(ally: list[int], enemy: list[int], cands: list[int],
               queues: tuple[int, ...] | None) -> tuple:
    return (
        tuple(sorted(ally)),
        tuple(sorted(enemy)),
        tuple(sorted(cands)),
        tuple(sorted(queues)) if queues else None,
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

    min_pair_n = min(hurts_pair_n + helps_pair_n) if (hurts_pair_n or helps_pair_n) else 0

    return {
        "champ_id":         cand,
        "solo_rating":      solo_rating,
        "solo_n":           g_solo,
        "hurts_them_score": hurts_them_score,
        "helps_us_score":   helps_us_score,
        "min_solo_n":       g_solo,
        "min_pair_n":       min_pair_n,
    }


def _mean_or_neutral(values: list[float]) -> float:
    if not values:
        return 0.5
    return sum(values) / len(values)


def _compute(ally: list[int], enemy: list[int], candidates: list[int],
             queues: tuple[int, ...] | None) -> dict:
    conn = draft_elo_db.open_ro()
    try:
        qids = queues if queues is not None else draft_elo_db.DEFAULT_SR_QUEUES
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
        except Exception:
            pass


def _serve_ban_suggest(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        ally_raw = (qs.get("ally") or [""])[0].strip()
        enemy_raw = (qs.get("enemy") or [""])[0].strip()
        cand_raw = (qs.get("candidates") or [""])[0].strip()
        queue_raw = (qs.get("queue") or [""])[0].strip()

        ally_ids, err = _parse_int_list(ally_raw, 1, 5)
        if err:
            h._send(400, json.dumps({"ok": False, "error": f"ally: {err}"})
                    .encode("utf-8"), "application/json")
            return
        enemy_ids, err = _parse_int_list(enemy_raw, 0, 5) if enemy_raw else ([], None)
        if err:
            h._send(400, json.dumps({"ok": False, "error": f"enemy: {err}"})
                    .encode("utf-8"), "application/json")
            return
        cand_ids, err = _parse_int_list(cand_raw, 1, 30)
        if err:
            h._send(400, json.dumps({"ok": False, "error": f"candidates: {err}"})
                    .encode("utf-8"), "application/json")
            return
        queue_ids, err = _parse_queues(queue_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = _cache_key(ally_ids, enemy_ids, cand_ids, queue_ids)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        try:
            payload = _compute(ally_ids, enemy_ids, cand_ids, queue_ids)
        except Exception as exc:
            log.warning("api/ban-suggest compute: %s", exc)
            h._send(503, json.dumps(
                {"ok": False, "error": "rewind history unavailable"}
            ).encode("utf-8"), "application/json")
            return

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        with _CACHE_LOCK:
            cacheable = dict(payload)
            cacheable.pop("cached", None)
            cacheable.pop("elapsed_ms", None)
            _CACHE[key] = (now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/ban-suggest: %s", exc)
        try:
            h._send(500, json.dumps({"ok": False, "error": str(exc)[:200]})
                    .encode("utf-8"), "application/json")
        except Exception:
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/ban-suggest"), _serve_ban_suggest),
]
