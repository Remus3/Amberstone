"""GET /api/draft-elo - team-vs-team draft scoring.

Closes the FUTURE entry from the draft tool L (the community fork) triage (BACKLOG): the
team-vs-team draft layer the existing pickban backend lacks. Composes
``core.draft_elo`` (pure math) with ``core.draft_elo_db`` (rewind
history queries) over ``core.smoothed_rates`` (Laplace smoothing).

Request shape:
  GET /api/draft-elo?ally=22,64,55,22,12&enemy=42,67,69,22,89[&queue=420][&breakdown=1]

  ally      : 5 ally champion ids (Riot integer ``key``), comma-separated.
  enemy     : 5 enemy champion ids.
  queue     : optional queue id; defaults to the SR ranked set
              (400/420/430/440/490).
  breakdown : optional flag (any truthy: ``1``, ``true``, ``yes``).
              When set, the response carries an additional
              ``top_contributions`` list (top-3 contributions by
              absolute Elo-rating delta) - used by the frontend hover
              strip to surface which ally-pair / enemy-pair / matchup
              moved predicted WR the most. Without the flag the field
              is omitted to keep payload small.

Response shape:
  {
    "ok":       true,
    "ally":     {"champs": [...], "champ_ratings": [...],
                 "pair_ratings": [...], "matchup_ratings": [...],
                 "total": ...},
    "enemy":    {"champs": [...], "champ_ratings": [...],
                 "pair_ratings": [...], "total": ...},
    "team_score":      ...,        # ally - enemy rating delta
    "predicted_wr":    0.0..1.0,   # logistic of team_score
    "sample":          {"min_solo": N, "min_pair": N, "min_matchup": N},
    "queue_ids":       [...],
    "top_contributions": [          # only when ?breakdown=1
        {"kind": "ally-pair"|"enemy-pair"|"matchup",
         "a":    <champ_id>,
         "b":    <champ_id>,
         "delta": <signed_rating>,  # ally-team perspective
         "n":    <sample_games>},
        ...up to 3 entries...
    ],
    "cached":          false,
    "elapsed_ms":      N,
  }

Cache: 5min in-process LRU keyed by (sorted ally + sorted enemy + queue
tuple). The lookup is ~50 queries against the read-only rewind db; a
champ-select session can re-hit the route on every state tick without
that turning into a DB hot loop.

Failure modes:
  - missing / wrong-length ids -> 400 with a clear error
  - non-integer ids -> 400
  - DB unavailable -> 503 with a structured error
  - any other exception -> 500 + structured error; never raises
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
# Cycle-8 audit: entries were never evicted (TTL only gates serving),
# so long uptimes grew the dict without bound. Cap + drop-oldest.
_CACHE_MAX = 256
_CACHE_EVICT = 64


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(),
                             key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_int_list(raw: str, expected: int) -> tuple[list[int], str | None]:
    if not raw:
        return ([], f"missing required ids (expected {expected})")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != expected:
        return ([], f"expected {expected} ids, got {len(parts)}")
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
    ids: list[int] = []
    for p in parts:
        try:
            ids.append(int(p))
        except ValueError:
            return (None, f"non-integer queue id {p!r}")
    return (tuple(ids), None)


def _cache_key(ally: list[int], enemy: list[int],
               queues: tuple[int, ...] | None) -> tuple:
    # ``breakdown`` is NOT part of the cache key. The breakdown list is
    # always computed (cheap pure-Python aggregate over data we already
    # pulled) and stripped before serving when the caller did not ask
    # for it. This keeps the cache hit rate identical across the two
    # request shapes - a hover-strip-curious client does not invalidate
    # the cache for the bulk consumer next door.
    return (
        tuple(sorted(ally)),
        tuple(sorted(enemy)),
        tuple(sorted(queues)) if queues else None,
    )


def _truthy(raw: str) -> bool:
    if not raw:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _compute(ally: list[int], enemy: list[int],
             queues: tuple[int, ...] | None) -> dict:
    """Pull priors from rewind_history.db, transform to ratings, return
    the structured payload."""
    conn = draft_elo_db.open_ro()
    try:
        qids = queues if queues is not None else draft_elo_db.DEFAULT_SR_QUEUES

        # Solo ratings + raw counts per champ.
        ally_solo = [draft_elo_db.solo_winrate(conn, c, qids) for c in ally]
        enemy_solo = [draft_elo_db.solo_winrate(conn, c, qids) for c in enemy]
        ally_champ_ratings = tuple(draft_elo.winrate_to_rating(r[2]) for r in ally_solo)
        enemy_champ_ratings = tuple(draft_elo.winrate_to_rating(r[2]) for r in enemy_solo)

        # Ally + enemy pair ratings (10 each).
        ally_pairs = draft_elo.unordered_pairs(tuple(ally))
        enemy_pairs = draft_elo.unordered_pairs(tuple(enemy))
        ally_pair_data = [
            draft_elo_db.pair_winrate(conn, a, b, qids, side="ally")
            for (a, b) in ally_pairs
        ]
        enemy_pair_data = [
            draft_elo_db.pair_winrate(conn, a, b, qids, side="ally")
            for (a, b) in enemy_pairs
        ]
        ally_pair_ratings = tuple(
            draft_elo.winrate_to_rating(r[2]) for r in ally_pair_data
        )
        enemy_pair_ratings = tuple(
            draft_elo.winrate_to_rating(r[2]) for r in enemy_pair_data
        )

        # Matchup ratings (25 cross-pairs; ally x enemy).
        cross = draft_elo.cross_pairs(tuple(ally), tuple(enemy))
        matchup_data = [
            draft_elo_db.matchup_winrate(conn, a, e, qids)
            for (a, e) in cross
        ]
        matchup_ratings = tuple(
            draft_elo.winrate_to_rating(r[2]) for r in matchup_data
        )

        ally_side = draft_elo.DraftSide(
            champ_ratings=ally_champ_ratings,
            pair_ratings=ally_pair_ratings,
            matchup_ratings=matchup_ratings,
        )
        enemy_side = draft_elo.DraftSide(
            champ_ratings=enemy_champ_ratings,
            pair_ratings=enemy_pair_ratings,
        )

        team_rating = draft_elo.team_score(ally_side, enemy_side)
        predicted_wr = draft_elo.rating_to_winrate(team_rating)

        # Sample-density floors so the caller can decide whether to
        # trust the prediction. Min over all the inputs that fed it.
        min_solo = min(r[1] for r in ally_solo + enemy_solo) if ally_solo or enemy_solo else 0
        min_pair = min(r[1] for r in ally_pair_data + enemy_pair_data) if ally_pair_data or enemy_pair_data else 0
        min_matchup = min(r[1] for r in matchup_data) if matchup_data else 0

        # Top-3 contributions to team_score by abs(delta) for the
        # hover-strip overlay. Always computed (cheap aggregate over
        # data we already pulled); the serve layer strips the field
        # when ``?breakdown=1`` was not requested.
        contributions = draft_elo.top_contributions(
            ally_pairs=ally_pairs,
            enemy_pairs=enemy_pairs,
            matchup_cross=cross,
            ally_pair_ratings=ally_pair_ratings,
            enemy_pair_ratings=enemy_pair_ratings,
            matchup_ratings=matchup_ratings,
            ally_pair_counts=[r[1] for r in ally_pair_data],
            enemy_pair_counts=[r[1] for r in enemy_pair_data],
            matchup_counts=[r[1] for r in matchup_data],
            limit=3,
        )

        return {
            "ok":    True,
            "ally":  {
                "champs":          list(ally),
                "solo_counts":     [(w, g) for (w, g, _) in ally_solo],
                "champ_ratings":   list(ally_champ_ratings),
                "pair_ratings":    list(ally_pair_ratings),
                "matchup_ratings": list(matchup_ratings),
                "total":           ally_side.total,
            },
            "enemy": {
                "champs":          list(enemy),
                "solo_counts":     [(w, g) for (w, g, _) in enemy_solo],
                "champ_ratings":   list(enemy_champ_ratings),
                "pair_ratings":    list(enemy_pair_ratings),
                "total":           sum(enemy_champ_ratings) + sum(enemy_pair_ratings),
            },
            "team_score":   team_rating,
            "predicted_wr": predicted_wr,
            "sample":       {
                "min_solo":    min_solo,
                "min_pair":    min_pair,
                "min_matchup": min_matchup,
            },
            "queue_ids":    list(qids),
            "top_contributions": [
                {"kind": c.kind, "a": c.a, "b": c.b,
                 "delta": c.delta, "n": c.n}
                for c in contributions
            ],
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _serve_draft_elo(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        ally_raw = (qs.get("ally") or [""])[0].strip()
        enemy_raw = (qs.get("enemy") or [""])[0].strip()
        queue_raw = (qs.get("queue") or [""])[0].strip()
        breakdown = _truthy((qs.get("breakdown") or [""])[0])

        ally_ids, err = _parse_int_list(ally_raw, 5)
        if err:
            h._send(400, json.dumps({"ok": False, "error": f"ally: {err}"})
                    .encode("utf-8"), "application/json")
            return
        enemy_ids, err = _parse_int_list(enemy_raw, 5)
        if err:
            h._send(400, json.dumps({"ok": False, "error": f"enemy: {err}"})
                    .encode("utf-8"), "application/json")
            return
        queue_ids, err = _parse_queues(queue_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = _cache_key(ally_ids, enemy_ids, queue_ids)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                if not breakdown:
                    payload.pop("top_contributions", None)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        try:
            payload = _compute(ally_ids, enemy_ids, queue_ids)
        except Exception as exc:
            log.warning("api/draft-elo compute: %s", exc)
            h._send(503, json.dumps(
                {"ok": False, "error": "rewind history unavailable"}
            ).encode("utf-8"), "application/json")
            return

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        if not breakdown:
            payload.pop("top_contributions", None)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/draft-elo: %s", exc)
        try:
            # Raw exception text stays in the log only.
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"})
                .encode("utf-8"), "application/json")
        except Exception:
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/draft-elo"), _serve_draft_elo),
]
