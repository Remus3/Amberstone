"""Personal-vs threat tags (champ-select UX win).

GET /api/personal-vs?champ_id=X[&days=30][&queue=420,400]

Returns the operator's personal lifetime record vs a single enemy
champion, scoped by an optional rolling-day window. Designed for the
champ-select panel which fires one fetch per enemy slot in parallel
(5 enemies) on each LCU update tick.

Response shape:

  {
    "ok": true,
    "champ_id": 64,
    "champ_name": "Lee Sin",
    "days": 30,
    "sample_n": 7,
    "wins":     4,
    "losses":   3,
    "wr_pct":   57,
    "threat_band": "green" | "amber" | "red" | "unknown",
    "recent": [
      {"match_id": "NA1_...", "ts": 1746000000, "result": "WIN"|"LOSS"},
      ...up to 5
    ],
    "elapsed_ms": 4
  }

Threat band rules:
  - sample_n < 5  -> "unknown" (override - small samples aren't trustworthy)
  - wr_pct < 40   -> "red"
  - 40 <= wr <= 55 -> "amber"
  - wr_pct > 55   -> "green"

The route uses an in-process 60s TTL cache keyed on
``(puuid, champ_id, days_bucket, queue_signature)``. days_bucket is the
raw day count so cache entries never collide across windows.

Reuses the s170 ``_resolve_operator_puuid`` pattern (most-frequent
puuid in participants - mirrors routes_pickban/routes_lobby_aux).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = Path("data") / "rewind_history.db"

# Default SR queue set - same constant as routes_pickban._DEFAULT_SR_QUEUES.
# Duplicated locally to avoid a cross-module import (mirrors how other route
# modules treat shared constants).
_DEFAULT_SR_QUEUES: tuple[int, ...] = (400, 420, 430, 440, 490)

# Cache: {(puuid, champ_id, days, queue_sig): (timestamp, payload_dict)}
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL_S = 60.0

# Band thresholds. Documented in module docstring; values are also pinned
# in tests/test_routes_personal_vs.py so a future tuning needs a test bump.
_BAND_MIN_SAMPLE = 5
_BAND_RED_MAX_EXCLUSIVE = 40
_BAND_AMBER_MAX_INCLUSIVE = 55


def _resolve_operator_puuid(conn: sqlite3.Connection) -> str | None:
    """Most-frequent puuid in participants is the operator's. Mirrors
    routes_pickban._resolve_operator_puuid and routes_lobby_aux to keep
    cross-module surface area minimal."""
    # ``puuid ASC`` tertiary keeps a COUNT(*) tie deterministic across
    # requests (mirrors routes_pickban._resolve_operator_puuid - without
    # it SQLite tie order is undefined and "who is the operator" could
    # flip between calls).
    cur = conn.execute(
        "SELECT puuid FROM participants "
        "WHERE puuid IS NOT NULL AND puuid != '' "
        "GROUP BY puuid ORDER BY COUNT(*) DESC, puuid ASC LIMIT 1"
    )
    row = cur.fetchone()
    return row[0] if row else None


def _classify_band(sample_n: int, wr_pct: int) -> str:
    """Map (sample_n, wr_pct) to a threat band. Small-sample override
    fires BEFORE the wr_pct buckets so a 0-0 record never flashes
    green by virtue of wr_pct=0 falling in 'red'."""
    if sample_n < _BAND_MIN_SAMPLE:
        return "unknown"
    if wr_pct < _BAND_RED_MAX_EXCLUSIVE:
        return "red"
    if wr_pct <= _BAND_AMBER_MAX_INCLUSIVE:
        return "amber"
    return "green"


def _parse_queue_filter(raw: str) -> tuple[int, ...]:
    """Parse ?queue=420 -> (420,); ?queue=400,420 -> (400,420). Falls
    back to the default SR set on parse errors or empty input."""
    if not raw:
        return _DEFAULT_SR_QUEUES
    try:
        out = tuple(int(x) for x in raw.split(",") if x.strip())
    except ValueError:
        return _DEFAULT_SR_QUEUES
    return out or _DEFAULT_SR_QUEUES


def _query_personal_vs(conn: sqlite3.Connection, puuid: str, champ_id: int,
                       days: int, queue_ids: tuple[int, ...]) -> dict:
    """Aggregate operator's record in matches where ``champ_id`` was on
    the OPPOSING team, within the last ``days`` calendar days, filtered
    by ``queue_ids``. Pulls up to 5 recent matches for the response.

    ``days <= 0`` means no date filter (lifetime).
    """
    placeholders = ",".join("?" * len(queue_ids))
    # game_creation_ts is Unix milliseconds (per schema comment).
    since_ms = 0
    if days > 0:
        since_ms = int((time.time() - days * 86400) * 1000)

    # Aggregate row.
    sql_agg = f"""
        SELECT
          (SELECT champion_name FROM participants
             WHERE champion_id = ? LIMIT 1) AS champ_name,
          COUNT(*) AS games,
          SUM(CASE WHEN op.win=1 THEN 1 ELSE 0 END) AS wins
        FROM participants op
        JOIN matches m ON m.match_id = op.match_id
        WHERE op.puuid = ?
          AND m.queue_id IN ({placeholders})
          AND COALESCE(m.game_creation_ts, 0) >= ?
          AND EXISTS (
            SELECT 1 FROM participants e
            WHERE e.match_id = op.match_id
              AND e.team_id != op.team_id
              AND e.champion_id = ?
          )
    """
    row = conn.execute(sql_agg, (champ_id, puuid, *queue_ids, since_ms, champ_id)).fetchone()
    name, games, wins = row if row else (None, 0, 0)
    games = int(games or 0)
    wins = int(wins or 0)
    losses = games - wins
    wr_pct = int(round(100 * wins / games)) if games else 0
    band = _classify_band(games, wr_pct)

    # Recent 5 matches.
    sql_recent = f"""
        SELECT op.match_id, m.game_creation_ts, op.win
        FROM participants op
        JOIN matches m ON m.match_id = op.match_id
        WHERE op.puuid = ?
          AND m.queue_id IN ({placeholders})
          AND COALESCE(m.game_creation_ts, 0) >= ?
          AND EXISTS (
            SELECT 1 FROM participants e
            WHERE e.match_id = op.match_id
              AND e.team_id != op.team_id
              AND e.champion_id = ?
          )
        ORDER BY m.game_creation_ts DESC
        LIMIT 5
    """
    cur = conn.execute(sql_recent, (puuid, *queue_ids, since_ms, champ_id))
    recent: list[dict] = []
    for r in cur.fetchall():
        match_id, ts_ms, win = r
        recent.append({
            "match_id": str(match_id or ""),
            "ts": int((ts_ms or 0) // 1000),  # seconds (ms in DB)
            "result": "WIN" if win else "LOSS",
        })

    return {
        "champ_id":     int(champ_id),
        "champ_name":   str(name or ""),
        "sample_n":     games,
        "wins":         wins,
        "losses":       losses,
        "wr_pct":       wr_pct,
        "threat_band":  band,
        "recent":       recent,
    }


def _cache_get(key: tuple) -> dict | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if (time.time() - ts) > _CACHE_TTL_S:
        # Stale - drop and miss.
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple, payload: dict) -> None:
    _CACHE[key] = (time.time(), payload)
    # Hard cap to keep the dict bounded across long sessions; LRU is
    # overkill here - the natural champion pool is ~172 and the TTL is
    # 60s, so capacity is the safety net not the policy.
    if len(_CACHE) > 1024:
        # Drop the oldest 256 entries by timestamp.
        victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:256]
        for k, _ in victims:
            _CACHE.pop(k, None)


def _serve_personal_vs(h) -> None:
    """GET /api/personal-vs?champ_id=X[&days=30][&queue=420,400]

    Per-champion personal record probe for the champ-select threat tags.
    """
    try:
        qs = parse_qs(urlparse(h.path).query)

        # champ_id required - bare/zero rejects with 400.
        raw_cid = (qs.get("champ_id") or qs.get("champId") or [""])[0].strip()
        try:
            champ_id = int(raw_cid)
        except ValueError:
            champ_id = 0
        if champ_id <= 0:
            h._send(400, json.dumps({
                "ok": False, "error": "champ_id required (positive int)",
            }).encode(), "application/json")
            return

        # days optional - default 30, clamp to [0, 3650].
        raw_days = (qs.get("days") or ["30"])[0].strip()
        try:
            days = int(raw_days)
        except ValueError:
            days = 30
        if days < 0:
            days = 0
        if days > 3650:
            days = 3650

        queue_ids = _parse_queue_filter((qs.get("queue") or [""])[0])

        if not _REWIND_DB.exists():
            h._send(503, json.dumps({
                "ok": False, "error": "rewind_history.db missing",
            }).encode(), "application/json")
            return

        t0 = time.time()
        # Open ro-mode + uri so concurrent writes from rewind_catchup
        # don't block (DB has WAL anyway, defensive).
        conn = sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True, timeout=2.0)
        try:
            puuid = _resolve_operator_puuid(conn)
            if not puuid:
                h._send(503, json.dumps({
                    "ok": False, "error": "no operator puuid in rewind_history.db",
                }).encode(), "application/json")
                return

            cache_key = (puuid, champ_id, days, queue_ids)
            cached = _cache_get(cache_key)
            if cached is not None:
                # Reuse but freshen elapsed_ms / days fields if they
                # weren't in the cached blob (forward-compat).
                payload = dict(cached)
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                payload["cached"] = True
                payload["ok"] = True
                payload["days"] = days
                payload["queue_ids"] = list(queue_ids)
                h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
                return

            body = _query_personal_vs(conn, puuid, champ_id, days, queue_ids)
        finally:
            conn.close()

        payload = dict(body)
        payload["ok"] = True
        payload["days"] = days
        payload["queue_ids"] = list(queue_ids)
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        payload["cached"] = False
        _cache_put(cache_key, dict(body))

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        log.warning("api/personal-vs: %s", exc)
        try:
            # Raw exception text stays in the log only.
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"}).encode(),
                "application/json")
        except Exception:  # noqa: BLE001
            pass


def _equals(p: str):
    """Local matcher mirroring routes_pickban._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/personal-vs"), _serve_personal_vs),
]

POST_ROUTES: list = []
