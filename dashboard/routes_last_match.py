"""Post Game Review (a.k.a. Last Match) view routes.

GET  /api/last-match          - operator's most-recent non-TFT match + Quick
                                Review (right / wrong-team / chronic patterns).
POST /api/last-match/ingest   - receives the full LCU match detail JSON +
                                operator's puuid (pushed by the Legion
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

Trust boundary (s144 true-audit cycle 80): the ingest POST is LAN-reachable
with no auth header (tools/lcu_agent.py; it is not a control endpoint), so
_validate_ingest_body asserts the body's shape before any DB work - a
string tracked_puuid of at most TRACKED_PUUID_MAX_LEN printable ASCII
characters, a positive int64 gameId (an int or ASCII-digit string, never a
bool), non-negative int64 gameCreation / gameDuration, a non-empty
participants LIST and an optional participantIdentities LIST. Anything else
is a 400, never a 500. The retry queue holds at most INGEST_RETRY_QUEUE_MAX
games, one entry per gameId (a re-post replaces the body), and a full queue
answers 503. A match-store (sqlite / OS) failure is a degraded 503; any
other failure is a traceback-logged 500. Neither echoes the raw error.
"""
import json
import logging
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime

from dashboard.builders import _build_last_match, _clamp_baseline
from dashboard._context import APP_DIR as _APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Payload bound: the LCU detail for one game is typically 50-120 KB; the
# global POST cap in dashboard/_handler.py (_MAX_POST_BYTES, 1 MiB) is the
# enforcing layer. (A dead local 2 MB constant that contradicted it was
# removed in audit cycle 8 slice E.)

# Item 211 row-match knobs - operator-tunable; not currently surfaced in
# settings. Keep at module scope so tests can monkeypatch without import games.
INGEST_TS_WINDOW_S = 180          # gameEnd-vs-row-timestamp fallback tolerance
INGEST_RETRY_DEADLINE_S = 60      # drop queued ingest after this many seconds
INGEST_RETRY_TICK_S = 10          # background drain cadence

# At most this many distinct games wait in the retry queue. Each entry holds
# a body of up to the 1 MiB POST cap for INGEST_RETRY_DEADLINE_S, and real
# traffic is one game at a time (EndOfGame plus the odd Refresh click), so
# the bound is a memory ceiling, not a throughput knob.
INGEST_RETRY_QUEUE_MAX = 16
# A Riot puuid is 78 characters; anything past this is not a puuid.
TRACKED_PUUID_MAX_LEN = 128
# match_ts is "YYYY-MM-DD HH:MM:SS" (19 chars); this is a length ceiling
# for the cache key, not a format check (the builder answers found=False
# for a timestamp no row carries).
MATCH_TS_MAX_LEN = 32
_INT64_MAX = 2 ** 63 - 1

# Entries: (deadline_monotonic, body_dict), at most one per gameId.
_INGEST_RETRY_QUEUE: deque = deque()
_INGEST_RETRY_LOCK = threading.Lock()
_INGEST_RETRY_THREAD_STARTED = False
_INGEST_RETRY_THREAD_LOCK = threading.Lock()

_STORE_UNAVAILABLE = {"error": "match store unavailable - retry shortly"}
_INTERNAL_ERROR = {"error": "internal error - see logs"}

# GET /api/last-match response cache, keyed (clamped baseline, match_ts) -
# the full set of request inputs the body varies with (_serve_last_match reads
# nothing else off the handler, and _build_last_match takes exactly those two
# args) - plus, on the live path only, the RM-616 TFT store marker
# (_tft_store_marker), so a TFT game stored after a fetch is not hidden for
# the TTL. The baseline is normalized through _clamp_baseline first so the many
# raw values that clamp to the same window share one entry.
# Rebuilding cost 320ms measured 2026-08-06 against 8-27ms for every other
# dashboard route, and the frontend refires this on PGR activation, historical
# PGR activation and every baseline toggle.
#
# 30s rather than the 300s most sibling routes use: the default (no match_ts)
# key resolves "newest non-TFT row", and match rows are INSERTed by
# performance_tracker, which is not a call path this module can hook. The TTL
# is therefore the staleness bound for a brand-new row, while the LCU detail
# ingest - the write that actually fills the Post Game Review - invalidates
# explicitly in _try_ingest_once.
#
# Stamps are time.monotonic(): a wall-clock step back would otherwise make an
# entry immortal. _CACHE_GEN is bumped by every _cache_clear, and a build
# that started before an invalidation does not store its body (a GET that
# straddles an ingest would otherwise pin the pre-ingest review for the TTL).
_CACHE_TTL_S = 30.0
_CACHE: dict[tuple, tuple[float, bytes]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256
_CACHE_EVICT = 64
_CACHE_GEN = 0


def _cache_get(key: tuple, now: float) -> bytes | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        stamped, body = entry
        if (now - stamped) >= _CACHE_TTL_S:
            _CACHE.pop(key, None)
            return None
        return body


def _cache_generation() -> int:
    with _CACHE_LOCK:
        return _CACHE_GEN


def _cache_put(key: tuple, now: float, body: bytes,
               gen: int | None = None) -> None:
    """Store `body`. With `gen`, store only if no invalidation happened
    since that generation was read (the build is not stale)."""
    with _CACHE_LOCK:
        if gen is not None and gen != _CACHE_GEN:
            return
        _CACHE[key] = (now, body)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _cache_clear() -> None:
    global _CACHE_GEN
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_GEN += 1


def _tft_store_marker():
    """Cache-key component that changes when a TFT record lands. Fail-soft:
    an unreadable store keys as None (the TTL still bounds staleness)."""
    try:
        from tft import tft_placement
        return tft_placement.store_marker()
    except Exception as exc:  # noqa: BLE001
        log.debug("api/last-match: TFT store marker unavailable: %s", exc)
        return None


def _is_printable_ascii(text: str) -> bool:
    """True when every character is printable 7-bit ASCII (space to tilde)."""
    return all(" " <= ch <= "~" for ch in text)


def _coerce_nonneg_int64(value):
    """An int (never a bool) or an ASCII-digit string in [0, 2**63 - 1],
    else None. SQLite INTEGER is int64, so a larger id raised OverflowError
    deep in the row match and answered 500."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    elif isinstance(value, str):
        s = value.strip()
        if not s or len(s) > 19 or not s.isascii() or not s.isdigit():
            return None
        n = int(s)
    else:
        return None
    if n < 0 or n > _INT64_MAX:
        return None
    return n


def _validate_ingest_body(body):
    """Assert the ingest body's shape at the trust boundary.

    Returns (error, None) or (None, parsed) where parsed carries
    tracked_puuid, match_detail, game_id, game_creation_ms,
    game_duration_s, identities and participants."""
    if not isinstance(body, dict):
        return ("body must be a JSON object", None)
    raw_puuid = body.get("tracked_puuid")
    if raw_puuid is not None and not isinstance(raw_puuid, str):
        return ("tracked_puuid must be a string", None)
    tracked_puuid = (raw_puuid or "").strip()
    if not tracked_puuid:
        return ("tracked_puuid required", None)
    if (len(tracked_puuid) > TRACKED_PUUID_MAX_LEN
            or not _is_printable_ascii(tracked_puuid)):
        return (f"tracked_puuid must be at most {TRACKED_PUUID_MAX_LEN} "
                "printable ASCII characters", None)
    match_detail = body.get("match_detail")
    if not isinstance(match_detail, dict):
        return ("match_detail must be a JSON object", None)
    raw_gid = match_detail.get("gameId")
    if raw_gid is None or raw_gid == "":
        return ("match_detail.gameId required", None)
    game_id = _coerce_nonneg_int64(raw_gid)
    if not game_id:
        return ("match_detail.gameId must be a positive integer", None)
    numbers = {}
    for field in ("gameCreation", "gameDuration"):
        raw = match_detail.get(field)
        n = 0 if raw is None else _coerce_nonneg_int64(raw)
        if n is None:
            return (f"match_detail.{field} must be a non-negative integer",
                    None)
        numbers[field] = n
    participants = match_detail.get("participants")
    if not participants:
        return ("match_detail.participants required", None)
    if not isinstance(participants, list):
        return ("match_detail.participants must be a list", None)
    identities = match_detail.get("participantIdentities")
    if identities is None:
        identities = []
    elif not isinstance(identities, list):
        return ("match_detail.participantIdentities must be a list", None)
    return (None, {
        "tracked_puuid": tracked_puuid,
        "match_detail": match_detail,
        "game_id": game_id,
        "game_creation_ms": numbers["gameCreation"],
        "game_duration_s": numbers["gameDuration"],
        "identities": identities,
        "participants": participants,
    })


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


def _stamp_row(conn: sqlite3.Connection, mid: int, raw_data_str,
               match_detail: dict, tracked_puuid: str) -> None:
    """Merge the LCU detail into the row's raw_data blob + stamp game_id.

    A blob that is not a JSON object (undecodable, or a list / scalar) is
    never discarded: it is carried verbatim under "prior_raw_data" so the
    stamp cannot destroy bytes performance_tracker wrote."""
    rd = {}
    if raw_data_str:
        try:
            parsed = json.loads(raw_data_str)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            rd = parsed
        else:
            prior = raw_data_str
            if isinstance(prior, (bytes, bytearray)):
                prior = bytes(prior).decode("utf-8", "replace")
            log.warning("api/last-match/ingest: row %s raw_data is not a JSON "
                        "object; kept under prior_raw_data", mid)
            rd = {"prior_raw_data": str(prior)}
    rd["lcu_match_detail"] = match_detail
    rd["tracked_puuid"]    = tracked_puuid
    rd["lcu_ingested_at"]  = datetime.now().isoformat(timespec="seconds")
    new_raw = json.dumps(rd, default=str, ensure_ascii=False)
    gid = _coerce_nonneg_int64(match_detail.get("gameId")) or 0
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

    A sqlite / OS failure while matching or stamping RAISES; the callers
    classify it (503 for the POST, keep-until-deadline for the drain).
    """
    error, parsed = _validate_ingest_body(body)
    if error is not None:
        return ("error", {"error": error, "http_status": 400})
    match_detail = parsed["match_detail"]
    tracked_puuid = parsed["tracked_puuid"]
    gid = parsed["game_id"]

    db_path = _APP_DIR / "data" / "match_history.db"
    if not db_path.exists():
        return ("no_db", {"error": "match_history.db missing", "http_status": 503})

    # Resolve operator's participant championId in the LCU payload - used
    # as a soft sanity check + included in the response body. Entries that
    # are not objects are skipped, never dereferenced.
    lcu_champion_id = None
    me_pid = None
    for ident in parsed["identities"]:
        if not isinstance(ident, dict):
            continue
        player = ident.get("player")
        if not isinstance(player, dict):
            continue
        puuid = player.get("puuid")
        if isinstance(puuid, str) and puuid.strip() == tracked_puuid:
            me_pid = ident.get("participantId")
            break
    if me_pid is not None:
        for p in parsed["participants"]:
            if isinstance(p, dict) and p.get("participantId") == me_pid:
                lcu_champion_id = p.get("championId")
                break

    conn = sqlite3.connect(str(db_path))
    try:
        # Primary: gameId keyed match.
        row = _row_match_by_game_id(conn, gid)
        # Fallback: timestamp window for legacy / unstamped rows.
        if row is None:
            row = _row_match_by_timestamp_window(
                conn, parsed["game_creation_ms"], parsed["game_duration_s"],
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

    # Single invalidation point for BOTH ingest callers - the POST handler
    # and the background retry drain - since this is the only place a row's
    # raw_data actually changes.
    _cache_clear()

    return ("ok", {
        "match_id":          int(mid),
        "game_id":           gid,
        "champion_db":       db_champion,
        "champion_lcu_id":   lcu_champion_id,
        "participant_count": len(parsed["participants"]),
    })


def _queued_game_id(body):
    """The gameId a queued body is keyed by, or None."""
    detail = body.get("match_detail") if isinstance(body, dict) else None
    if not isinstance(detail, dict):
        return None
    return _coerce_nonneg_int64(detail.get("gameId"))


def _enqueue_retry(body: dict, game_id: int, deadline: float) -> bool:
    """Queue `body` for the retry drain, one entry per gameId: a re-post of
    a queued game replaces its body and deadline. Returns False (nothing
    queued) when the queue already holds INGEST_RETRY_QUEUE_MAX games."""
    with _INGEST_RETRY_LOCK:
        for i, (_deadline, queued) in enumerate(_INGEST_RETRY_QUEUE):
            if _queued_game_id(queued) == game_id:
                _INGEST_RETRY_QUEUE[i] = (deadline, body)
                return True
        if len(_INGEST_RETRY_QUEUE) >= INGEST_RETRY_QUEUE_MAX:
            return False
        _INGEST_RETRY_QUEUE.append((deadline, body))
        return True


def _retry_thread_should_start() -> bool:
    return not _INGEST_RETRY_THREAD_STARTED


def _ensure_retry_thread() -> None:
    """Lazy-start the background retry-drain thread. Idempotent and
    thread-safe: POST handlers run on concurrent server threads, so the
    check and the start happen under one lock. The flag is set only after
    a successful start, so a failed start is retried by the next POST."""
    global _INGEST_RETRY_THREAD_STARTED
    with _INGEST_RETRY_THREAD_LOCK:
        if not _retry_thread_should_start():
            return

        def _loop():
            while True:
                try:
                    time.sleep(INGEST_RETRY_TICK_S)
                    _drain_ingest_queue_once()
                except Exception:  # never let the thread die
                    log.warning("ingest retry drain failed", exc_info=True)

        # Daemon: the drain holds no resource across ticks (each ingest
        # opens and closes its own connection), so dying with the process
        # loses only queued retries, which expire in 60 s anyway.
        t = threading.Thread(target=_loop, name="rc-last-match-ingest-drain",
                             daemon=True)
        t.start()
        _INGEST_RETRY_THREAD_STARTED = True


def _drain_ingest_queue_once() -> int:
    """Walk the retry queue. For each entry: if its deadline passed, drop
    it; otherwise retry the ingest. Returns the count of ingests that
    completed (not retried, not dropped) this tick. Test-callable.

    One entry that raises (a locked database, a bug) is logged and kept
    until its deadline; it never costs the other entries their retry. A
    kept entry whose game was re-posted while the drain ran is dropped in
    favour of the newer body. Kept entries go back in front of anything
    queued meanwhile, so the queue can hold up to twice
    INGEST_RETRY_QUEUE_MAX for one tick; enqueue refuses until it drains."""
    completed = 0
    now = time.monotonic()
    # Snapshot under lock so producers can append while we walk.
    with _INGEST_RETRY_LOCK:
        snapshot = list(_INGEST_RETRY_QUEUE)
        _INGEST_RETRY_QUEUE.clear()
    keep = []
    for deadline, body in snapshot:
        if deadline <= now:
            # Aged out. Drop without retrying.
            continue
        try:
            verdict, _info = _try_ingest_once(body)
        except Exception:  # one entry must not cost the rest
            log.warning("ingest retry drain: game %s failed; kept until its "
                        "deadline", _queued_game_id(body), exc_info=True)
            keep.append((deadline, body))
            continue
        if verdict == "ok":
            completed += 1
            continue
        if verdict == "queue":
            keep.append((deadline, body))
            continue
        # error / no_db - drop; nothing to retry against.
    if keep:
        with _INGEST_RETRY_LOCK:
            requeued = {_queued_game_id(b) for _d, b in _INGEST_RETRY_QUEUE}
            survivors = [e for e in keep if _queued_game_id(e[1]) not in requeued]
            _INGEST_RETRY_QUEUE.extendleft(reversed(survivors))
    return completed


def _json(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _last_match_response(path: str) -> tuple[int, bytes]:
    # s220: optional ?baseline=N (operator-set in Settings), clamped by
    # the shared _clamp_baseline. Defaults to 20 - pre-s220 behavior.
    # HIST2: optional ?match_ts="YYYY-MM-DD HH:MM:SS" pins a specific
    # historical row (History / Session row click -> detached PGR).
    # Absent -> the live "latest non-TFT row" path is unchanged.
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(path).query or "")
    # Clamped BEFORE keying: the builder clamps to the same range, so
    # keying the raw value split identical bodies across a key per
    # out-of-range integer the frontend or a hand-edited URL can send.
    baseline = _clamp_baseline((qs.get("baseline") or ["20"])[0])
    # Normalized BEFORE keying the same way the builder normalizes it
    # (strip; blank = the live path), and bounded: a caller-chosen string
    # must not become an unbounded cache key or a control-character key.
    match_ts = (qs.get("match_ts") or [None])[0]
    if match_ts is not None:
        match_ts = match_ts.strip() or None
    if match_ts is not None and (len(match_ts) > MATCH_TS_MAX_LEN
                                 or not _is_printable_ascii(match_ts)):
        return (400, _json({"error": "match_ts must be a "
                                     "YYYY-MM-DD HH:MM:SS timestamp"}))
    # RM-616 / s134 QA D4: the live path can serve a TFT game from the
    # store, which lands seconds after the game-end fetch. Keying on the
    # store marker lets the main.js 10 s post-game retry see it instead
    # of a cached stale match. The historical path never reads the store.
    key = (baseline, match_ts, _tft_store_marker() if match_ts is None else None)
    now = time.monotonic()
    body = _cache_get(key, now)
    if body is None:
        gen = _cache_generation()
        built = _build_last_match(baseline, match_ts)
        body = json.dumps(built).encode("utf-8")
        # A degraded build (db missing / sqlite error) returns 200 with
        # an "error" key rather than raising, so it reaches here. Serve
        # it, but never store it: the condition is transient and the
        # sqlite branch drops its poisoned connection on the way out, so
        # storing would pin a degraded Post Game Review for the full TTL
        # when the next build would likely succeed.
        if not (isinstance(built, dict) and built.get("error")):
            _cache_put(key, now, body, gen)
    return (200, body)


def _serve_last_match(h) -> None:
    # The response is built inside the try and sent outside it, so a client
    # that disconnects mid-send (an OSError) is never mistaken for a match
    # store failure. Raw exception text can leak file paths - log it,
    # never render it.
    try:
        status, payload = _last_match_response(h.path)
    except (sqlite3.Error, OSError):
        log.warning("api/last-match: match store unavailable", exc_info=True)
        status, payload = 503, _json(_STORE_UNAVAILABLE)
    except Exception:
        log.exception("api/last-match: unexpected failure")
        status, payload = 500, _json(_INTERNAL_ERROR)
    h._send(status, payload, "application/json")


def _ingest_response(body) -> tuple[int, dict]:
    verdict, info = _try_ingest_once(body)
    if verdict == "ok":
        return (200, {"ok": True, **info})
    if verdict in ("error", "no_db"):
        status = info.pop("http_status", 400)
        return (status, info)
    # verdict == "queue" - no row matched, defer.
    game_id = info.get("game_id", 0)
    deadline = time.monotonic() + INGEST_RETRY_DEADLINE_S
    if not _enqueue_retry(body, game_id, deadline):
        log.warning("api/last-match/ingest: retry queue full (%d games); "
                    "game %s refused", INGEST_RETRY_QUEUE_MAX, game_id)
        return (503, {"error": "ingest retry queue full - retry shortly"})
    _ensure_retry_thread()
    return (202, {"ok": True, "queued": True, "game_id": game_id,
                  "retry_deadline_s": INGEST_RETRY_DEADLINE_S})


def _serve_last_match_ingest(h, body) -> None:
    """POST /api/last-match/ingest - see module docstring for row-match contract."""
    try:
        status, payload = _ingest_response(body)
        out = _json(payload)
    except (sqlite3.Error, OSError):
        log.warning("api/last-match/ingest: match store unavailable",
                    exc_info=True)
        status, out = 503, _json(_STORE_UNAVAILABLE)
    except Exception:
        log.exception("api/last-match/ingest: unexpected failure")
        status, out = 500, _json(_INTERNAL_ERROR)
    h._send(status, out, "application/json")


GET_ROUTES = [
    (equals("/api/last-match"), _serve_last_match),
]

POST_ROUTES = [
    (equals("/api/last-match/ingest"), _serve_last_match_ingest),
]
