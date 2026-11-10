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
      {"match_id": "NA1_...", "ts": 1746000000,
       "result": "WIN"|"LOSS"|"REMAKE"|"UNKNOWN"},
      ...up to 5
    ],
    "games_total": 8,
    "wr_display": "57%" | "-",
    "elapsed_ms": 4
  }

RM-610: sample_n, wins, losses and wr_pct count RESOLVED games only
(known result, not a remake) via core.resolved_wr; games_total counts
every matching game.

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

Query parameters come from the request line and are untrusted
(true-audit s144 S144-T-771..776,
tests/test_routes_personal_vs_true_audit_s144.py):

  champ_id  1-10 ASCII digits (surrounding whitespace stripped), value
            1 .. 2**31 - 1 (the JS caller sends ``champId | 0``);
            anything else is the 400. ``champId`` is an alias.
  days      ASCII digits with an optional sign, at most 9 digits, clamped
            to [0, 3650]; anything else is the default 30.
  queue     comma list of queue ids, each 1-9 ASCII digits, duplicates
            dropped in order, at most ``_MAX_QUEUE_IDS``; anything else
            (or nothing) is the default SR set. Bare ``int()`` would take
            Arabic-Indic / fullwidth digits, ``_`` and a sign, and an id
            past the SQLite INTEGER range or too many ids raised inside
            the query (a 500).

A ``game_creation_ts`` that is not a finite number in [0, 2100-01-01]
reads as ``ts`` 0 in ``recent`` instead of failing the whole reply.

The cache is shared by the ThreadingHTTPServer's request threads and is
only touched under ``_CACHE_LOCK``. The reply is written OUTSIDE the
catch-all: a failure while writing it (the client went away) propagates
to the dispatcher, which closes the connection, instead of a second
status line being written onto the same response. Any other failure is
``dashboard._errors.send_error``'s fixed 500 line; the cause is logged
scrubbed, with its type name.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.resolved_wr import classify, resolution_select, resolved_wr, wr_pct
from dashboard._errors import GENERIC_ERROR, send_error

log = logging.getLogger("rc.web_dashboard")

# Anchored to the repo root, never the CWD (RM-1022).
_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"

# Default SR queue set - same constant as routes_pickban._DEFAULT_SR_QUEUES.
# Duplicated locally to avoid a cross-module import (mirrors how other route
# modules treat shared constants).
_DEFAULT_SR_QUEUES: tuple[int, ...] = (400, 420, 430, 440, 490)

# Request-line validation (S144-T-771..773). ASCII classes only: a bare
# \d (and int()) also takes Arabic-Indic / fullwidth digits.
_CHAMP_ID_RE = re.compile(r"[0-9]{1,10}")
_CHAMP_ID_MAX = 2**31 - 1
_DAYS_RE = re.compile(r"[+-]?[0-9]{1,9}")
_DAYS_DEFAULT = 30
_DAYS_MAX = 3650
_QUEUE_ID_RE = re.compile(r"[0-9]{1,9}")
# Riot has a few dozen live queues; a longer list is not a real filter, and
# each id is one SQL variable (SQLite refuses past 32766).
_MAX_QUEUE_IDS = 32

# game_creation_ts is Unix ms; a stored value outside [0, 2100-01-01] is
# not a game time and reads as ts 0 (S144-T-776).
_TS_MAX_S = 4_102_444_800

_BAD_CHAMP_ID = "champ_id required (positive int)"

# Cache: {(puuid, champ_id, days, queue_sig): (timestamp, payload_dict)}
# Entries are (time.monotonic() stamp, payload): the stamp never leaves the process, and a wall-clock step
# must not expire or revive an entry (S144-P-368).
# Every read, write and eviction holds _CACHE_LOCK: the dashboard is a
# ThreadingHTTPServer and the eviction iterates the dict (S144-T-774).
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_S = 60.0
_CACHE_MAX = 1024
_CACHE_EVICT = 256

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


def _parse_champ_id(raw: str) -> int | None:
    """The canonical champion id, or None (the caller answers 400)."""
    text = raw.strip()
    if not _CHAMP_ID_RE.fullmatch(text):
        return None
    value = int(text)
    return value if 1 <= value <= _CHAMP_ID_MAX else None


def _parse_days(raw: str) -> int:
    """Rolling-day window clamped to [0, _DAYS_MAX]; junk is the default."""
    text = raw.strip()
    if not _DAYS_RE.fullmatch(text):
        return _DAYS_DEFAULT
    return min(max(int(text), 0), _DAYS_MAX)


def _parse_queue_filter(raw: str) -> tuple[int, ...]:
    """Parse ?queue=420 -> (420,); ?queue=400,420 -> (400,420). Falls
    back to the default SR set on parse errors, empty input or more
    than ``_MAX_QUEUE_IDS`` distinct ids; duplicates are dropped in
    order so equivalent filters share one cache entry."""
    if not raw:
        return _DEFAULT_SR_QUEUES
    out: dict[int, None] = {}
    for token in raw.split(","):
        text = token.strip()
        if not text:
            continue
        if not _QUEUE_ID_RE.fullmatch(text):
            return _DEFAULT_SR_QUEUES
        out[int(text)] = None
        if len(out) > _MAX_QUEUE_IDS:
            return _DEFAULT_SR_QUEUES
    return tuple(out) or _DEFAULT_SR_QUEUES


def _ts_seconds(value: object) -> int:
    """Unix seconds from a stored game_creation_ts (ms); anything that is
    not a finite number in [0, _TS_MAX_S] seconds reads as 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    secs = int(value // 1000)
    return secs if 0 <= secs <= _TS_MAX_S else 0


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

    # RM-610: one row per game, judged by the shared resolved-WR helper
    # (known result, not a remake) instead of COUNT(*) / SUM(win).
    extra = resolution_select(conn, "m")
    name_row = conn.execute(
        "SELECT champion_name FROM participants WHERE champion_id = ? LIMIT 1",
        (champ_id,)).fetchone()
    name = name_row[0] if name_row else None
    sql_agg = f"""
        SELECT op.win AS win{extra}
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
    cur = conn.execute(sql_agg, (puuid, *queue_ids, since_ms, champ_id))
    cols = [d[0] for d in cur.description]
    game_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    total_games = len(game_rows)
    wins, games, wr_display = resolved_wr(game_rows)
    losses = games - wins
    pct = wr_pct(wins, games, 0) or 0
    band = _classify_band(games, pct)

    # Recent 5 matches.
    sql_recent = f"""
        SELECT op.match_id, m.game_creation_ts, op.win{extra}
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
    rcols = [d[0] for d in cur.description]
    recent: list[dict] = []
    for r in cur.fetchall():
        row = dict(zip(rcols, r))
        # Unresolved games stay listed, badged REMAKE / UNKNOWN instead
        # of being read as a loss.
        recent.append({
            "match_id": str(row["match_id"] or ""),
            "ts": _ts_seconds(row["game_creation_ts"]),  # s (ms in DB)
            "result": {"win": "WIN", "loss": "LOSS", "remake": "REMAKE"}.get(
                classify(row), "UNKNOWN"),
        })

    return {
        "champ_id":     int(champ_id),
        "champ_name":   str(name or ""),
        "sample_n":     games,
        "wins":         wins,
        "losses":       losses,
        "wr_pct":       pct,
        "threat_band":  band,
        "recent":       recent,
        "games_total":  total_games,
        "wr_display":   wr_display,
    }


def _cache_get(key: tuple) -> dict | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        ts, payload = entry
        if (time.monotonic() - ts) > _CACHE_TTL_S:
            # Stale - drop and miss.
            _CACHE.pop(key, None)
            return None
        return payload


def _cache_put(key: tuple, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), payload)
        # Hard cap to keep the dict bounded across long sessions; LRU is
        # overkill here - the natural champion pool is ~172 and the TTL is
        # 60s, so capacity is the safety net not the policy.
        if len(_CACHE) > _CACHE_MAX:
            # Drop the oldest entries by timestamp.
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _open_ro() -> sqlite3.Connection:
    """Read-only connection to the rewind DB. ``as_uri()`` percent-encodes
    the path, so a checkout path holding ``#``, ``%`` or a space opens
    the right file (a raw ``file:{path}`` URI does not); read-only so
    concurrent writes from rewind_catchup don't block (the DB has WAL
    anyway, defensive)."""
    return sqlite3.connect(_REWIND_DB.resolve().as_uri() + "?mode=ro",
                           uri=True, timeout=2.0)


def _json(status: int, payload: dict) -> tuple[int, bytes]:
    return status, json.dumps(payload).encode("utf-8")


def _build_reply(h) -> tuple[int, bytes]:
    """(status, JSON body) for one request. Writes nothing."""
    qs = parse_qs(urlparse(h.path).query)

    # champ_id required - bare/zero/junk rejects with 400.
    champ_id = _parse_champ_id(
        (qs.get("champ_id") or qs.get("champId") or [""])[0])
    if champ_id is None:
        return _json(400, {"ok": False, "error": _BAD_CHAMP_ID})

    # days optional - default 30, clamp to [0, 3650].
    days = _parse_days((qs.get("days") or [str(_DAYS_DEFAULT)])[0])

    queue_ids = _parse_queue_filter((qs.get("queue") or [""])[0])

    if not _REWIND_DB.exists():
        return _json(503, {"ok": False, "error": "rewind_history.db missing"})

    # Duration only: monotonic, so a wall-clock step cannot make it
    # negative.
    t0 = time.monotonic()
    conn = _open_ro()
    try:
        puuid = _resolve_operator_puuid(conn)
        if not puuid:
            return _json(503, {
                "ok": False, "error": "no operator puuid in rewind_history.db",
            })

        cache_key = (puuid, champ_id, days, queue_ids)
        cached = _cache_get(cache_key)
        if cached is None:
            body = _query_personal_vs(conn, puuid, champ_id, days, queue_ids)
            _cache_put(cache_key, dict(body))
    finally:
        conn.close()

    payload = dict(body if cached is None else cached)
    payload["ok"] = True
    payload["days"] = days
    payload["queue_ids"] = list(queue_ids)
    payload["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    payload["cached"] = cached is not None
    return _json(200, payload)


def _serve_personal_vs(h) -> None:
    """GET /api/personal-vs?champ_id=X[&days=30][&queue=420,400]

    Per-champion personal record probe for the champ-select threat tags.
    """
    try:
        status, body = _build_reply(h)
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        # The raw exception text stays in the log only, scrubbed, with its
        # type name. A failure to write this reply propagates to the
        # dispatcher.
        send_error(h, exc, public_msg=GENERIC_ERROR, fields={"ok": False},
                   log_traceback=True)
        return
    # Outside the catch-all: a failed write reaches the dispatcher, which
    # closes the connection, instead of a second status line.
    h._send(status, body, "application/json")


def _equals(p: str):
    """Local matcher mirroring routes_pickban._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/personal-vs"), _serve_personal_vs),
]

POST_ROUTES: list = []
