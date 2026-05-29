"""Post Game Review (a.k.a. Last Match) view routes.

GET  /api/last-match          - operator's most-recent non-TFT match + Quick
                                Review (right / wrong-team / chronic patterns).
POST /api/last-match/ingest   - receives the full LCU match detail JSON +
                                operator's puuid (pushed by the Game-PC
                                LCU agent on EndOfGame phase transition;
                                also callable on-demand from the frontend
                                Refresh button). Stashes the payload into
                                the matching match_history.db row's
                                raw_data["lcu_match_detail"] so the
                                builder can surface team comp + items +
                                runes + win/loss + damage breakdown.

Source of truth: data/match_history.db. The raw_data column carries
the LCU payload verbatim - no normalization-on-write, parse-on-read.
Audit later if other pages start reading the same blob.

Item 211 row-match contract (2026-05-28):
  - PRIMARY:  matches.game_id == match_detail.gameId
  - FALLBACK: matches.game_id == 0 AND |gameCreation+gameDuration - matches.timestamp|
              <= INGEST_TS_WINDOW_S  (180s)
  - QUEUE:    no row matches yet -> append to _INGEST_RETRY_QUEUE with
              deadline now+INGEST_RETRY_DEADLINE_S (60s) + respond 202.
              Background daemon thread drains every INGEST_RETRY_TICK_S (10s).
  Pre-fix `ORDER BY timestamp DESC LIMIT 1` raced the local
  performance_tracker writer and attached the new game's items to the
  PREVIOUS row, leaving the new row item-less. Home Recent-5 then
  rendered items off-by-one against the champion/grade columns.
"""
import json
import logging
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime

from dashboard.builders import _build_last_match
from dashboard._context import APP_DIR as _APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Bound the payload - the LCU detail for one game is typically 50-120 KB.
_MAX_INGEST_BYTES = 2 * 1024 * 1024  # 2 MB hard cap

# Item 211 row-match knobs - operator-tunable; not currently surfaced in
# settings. Keep at module scope so tests can monkeypatch without import games.
INGEST_TS_WINDOW_S = 180          # gameEnd-vs-row-timestamp fallback tolerance
INGEST_RETRY_DEADLINE_S = 60      # drop queued ingest after this many seconds
INGEST_RETRY_TICK_S = 10          # background drain cadence

_INGEST_RETRY_QUEUE: deque = deque()  # entries: (deadline_unix, body_dict)
_INGEST_RETRY_LOCK = threading.Lock()
_INGEST_RETRY_THREAD_STARTED = False


def _row_match_by_game_id(conn: sqlite3.Connection, game_id: int):
    """Returns (id, raw_data_str) for the non-TFT row with this game_id,
    or None. game_id == 0 (unknown / legacy) is intentionally skipped."""
    if not game_id:
        return None
    cur = conn.execute(
        "SELECT id, raw_data FROM matches "
        "WHERE mode != 'TFT' AND game_id = ? LIMIT 1",
        (int(game_id),),
    )
    return cur.fetchone()


def _row_match_by_timestamp_window(conn: sqlite3.Connection,
                                   game_creation_ms: int,
                                   game_duration_s: int):
    """Fallback for legacy / pre-stamp rows: match by gameEnd unix vs the
    row's timestamp column within +/- INGEST_TS_WINDOW_S. Restricted to
    game_id = 0 rows so we never poach a row that's already keyed to a
    different game."""
    if not game_creation_ms:
        return None
    game_end_unix = (int(game_creation_ms) + int(game_duration_s or 0) * 1000) // 1000
    cur = conn.execute(
        "SELECT id, raw_data, timestamp FROM matches "
        "WHERE mode != 'TFT' AND game_id = 0 "
        "ORDER BY timestamp DESC LIMIT 50"
    )
    best = None
    best_delta = None
    for mid, rd, ts in cur:
        try:
            ts_unix = int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp())
        except (TypeError, ValueError):
            continue
        delta = abs(ts_unix - game_end_unix)
        if delta <= INGEST_TS_WINDOW_S and (best_delta is None or delta < best_delta):
            best = (mid, rd)
            best_delta = delta
    return best


def _stamp_row(conn: sqlite3.Connection, mid: int, raw_data_str: str,
               match_detail: dict, tracked_puuid: str) -> None:
    """Merge the LCU detail into the row's raw_data blob + stamp game_id."""
    try:
        rd = json.loads(raw_data_str) if raw_data_str else {}
    except (TypeError, json.JSONDecodeError):
        rd = {}
    rd["lcu_match_detail"] = match_detail
    rd["tracked_puuid"]    = tracked_puuid
    rd["lcu_ingested_at"]  = datetime.now().isoformat(timespec="seconds")
    new_raw = json.dumps(rd, default=str, ensure_ascii=False)
    gid = 0
    try:
        gid = int(match_detail.get("gameId") or 0)
    except (TypeError, ValueError):
        gid = 0
    conn.execute(
        "UPDATE matches SET raw_data = ?, game_id = ? WHERE id = ?",
        (new_raw, gid, mid),
    )


def _try_ingest_once(body: dict) -> tuple[str, dict]:
    """Resolve a row + stamp the LCU detail. Returns (verdict, info).

    verdict is one of:
      "ok"      - row matched + stamped; info carries match_id + champion_db.
      "queue"   - no row matched yet; caller should queue + 202 the request.
      "error"   - structural problem; info carries error+http_status.
      "no_db"   - match_history.db missing; info carries error+http_status.
    """
    if not isinstance(body, dict):
        return ("error", {"error": "body must be a JSON object", "http_status": 400})
    tracked_puuid = str(body.get("tracked_puuid") or "").strip()
    match_detail = body.get("match_detail")
    if not tracked_puuid:
        return ("error", {"error": "tracked_puuid required", "http_status": 400})
    if not isinstance(match_detail, dict):
        return ("error",
                {"error": "match_detail must be a JSON object", "http_status": 400})
    if not match_detail.get("gameId"):
        return ("error", {"error": "match_detail.gameId required", "http_status": 400})
    if not match_detail.get("participants"):
        return ("error",
                {"error": "match_detail.participants required", "http_status": 400})

    db_path = _APP_DIR / "data" / "match_history.db"
    if not db_path.exists():
        return ("no_db", {"error": "match_history.db missing", "http_status": 503})

    # Resolve operator's participant championId in the LCU payload - used
    # as a soft sanity check + included in the response body.
    lcu_champion_id = None
    me_pid = None
    for ident in (match_detail.get("participantIdentities") or []):
        player = ident.get("player") or {}
        if str(player.get("puuid") or "").strip() == tracked_puuid:
            me_pid = ident.get("participantId")
            break
    if me_pid is not None:
        for p in (match_detail.get("participants") or []):
            if p.get("participantId") == me_pid:
                lcu_champion_id = p.get("championId")
                break

    gid = int(match_detail.get("gameId") or 0)
    game_creation_ms = int(match_detail.get("gameCreation") or 0)
    game_duration_s  = int(match_detail.get("gameDuration") or 0)

    conn = sqlite3.connect(str(db_path))
    try:
        # Primary: gameId keyed match.
        row = _row_match_by_game_id(conn, gid)
        # Fallback: timestamp window for legacy / unstamped rows.
        if row is None:
            row = _row_match_by_timestamp_window(
                conn, game_creation_ms, game_duration_s,
            )
        if row is None:
            # No row yet - caller defers + retries.
            return ("queue", {"game_id": gid})

        mid, raw_data_str = row[0], row[1]
        # Fetch champion col for response payload (read-only).
        cur = conn.execute(
            "SELECT champion FROM matches WHERE id = ?", (mid,),
        )
        db_champion = (cur.fetchone() or [""])[0] or ""

        _stamp_row(conn, mid, raw_data_str, match_detail, tracked_puuid)
        conn.commit()
    finally:
        conn.close()

    return ("ok", {
        "match_id":          int(mid),
        "game_id":           gid,
        "champion_db":       db_champion,
        "champion_lcu_id":   lcu_champion_id,
        "participant_count": len(match_detail.get("participants") or []),
    })


def _ensure_retry_thread() -> None:
    """Lazy-start the background retry-drain thread. Idempotent."""
    global _INGEST_RETRY_THREAD_STARTED
    if _INGEST_RETRY_THREAD_STARTED:
        return
    _INGEST_RETRY_THREAD_STARTED = True

    def _loop():
        while True:
            try:
                time.sleep(INGEST_RETRY_TICK_S)
                _drain_ingest_queue_once()
            except Exception as exc:  # never let the thread die
                log.warning("ingest retry drain: %s", exc)

    t = threading.Thread(target=_loop, name="rc-last-match-ingest-drain",
                         daemon=True)
    t.start()


def _drain_ingest_queue_once() -> int:
    """Walk the retry queue. For each entry: if its deadline passed, drop
    it; otherwise retry the ingest. Returns the count of ingests that
    completed (not retried, not dropped) this tick. Test-callable."""
    completed = 0
    now = time.time()
    # Snapshot under lock so producers can append while we walk.
    with _INGEST_RETRY_LOCK:
        snapshot = list(_INGEST_RETRY_QUEUE)
        _INGEST_RETRY_QUEUE.clear()
    keep = []
    for deadline, body in snapshot:
        if deadline <= now:
            # Aged out. Drop without retrying.
            continue
        verdict, _info = _try_ingest_once(body)
        if verdict == "ok":
            completed += 1
            continue
        if verdict == "queue":
            keep.append((deadline, body))
            continue
        # error / no_db - drop; nothing to retry against.
    if keep:
        with _INGEST_RETRY_LOCK:
            _INGEST_RETRY_QUEUE.extend(keep)
    return completed


def _serve_last_match(h) -> None:
    try:
        # s220: optional ?baseline=N (operator-set in Settings; clamped
        # in _build_last_match). Defaults to 20 - pre-s220 behavior.
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(h.path).query or "")
        try:
            baseline = int((qs.get("baseline") or ["20"])[0])
        except (TypeError, ValueError):
            baseline = 20
        h._send(200, json.dumps(_build_last_match(baseline)).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/last-match: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")


def _serve_last_match_ingest(h, body) -> None:
    """POST /api/last-match/ingest - see module docstring for row-match contract."""
    try:
        verdict, info = _try_ingest_once(body)
        if verdict == "ok":
            resp = {"ok": True, **info}
            h._send(200, json.dumps(resp).encode(), "application/json")
            return
        if verdict in ("error", "no_db"):
            status = info.pop("http_status", 400)
            h._send(status, json.dumps(info).encode(), "application/json")
            return
        # verdict == "queue" - no row matched, defer.
        deadline = time.time() + INGEST_RETRY_DEADLINE_S
        with _INGEST_RETRY_LOCK:
            _INGEST_RETRY_QUEUE.append((deadline, body))
        _ensure_retry_thread()
        resp = {"ok": True, "queued": True,
                "game_id": info.get("game_id", 0),
                "retry_deadline_s": INGEST_RETRY_DEADLINE_S}
        h._send(202, json.dumps(resp).encode(), "application/json")
    except Exception as exc:
        log.warning("api/last-match/ingest: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")


GET_ROUTES = [
    (equals("/api/last-match"), _serve_last_match),
]

POST_ROUTES = [
    (equals("/api/last-match/ingest"), _serve_last_match_ingest),
]
