"""Post-game Win Probability Added (WPA) phases-that-mattered route.

GET /api/post-game-wpa?match_id=<id>

Reads the match timeline from ``data/rewind_history.db``, replays
strong events through the WPA estimator, returns per-event probability
deltas plus the top-3 phases ranked by absolute WPA. Designed for the
post-game review (S2 reframe) where the operator sees the moments that
swung the match instead of a flat scoreboard.

Response shape:

    {
      "ok": true,
      "match_id": "NA1_1234567890",
      "events": [
        {
          "game_time": 245,
          "type": "CHAMPION_KILL",
          "wpa": 0.0312,
          "prob_before": 0.5421,
          "prob_after": 0.5733,
          "actor": 5,
          "actor_team": 100,
          "victim": 7,
          "subtype": null
        },
        ...
      ],
      "top_phases": [...top 3 by abs(wpa)...],
      "frame_count": 23,
      "event_count": 48,
      "model": "trained" | "fallback",
      "elapsed_ms": 27
    }

Failures:

    400 - match_id missing, empty, given more than once, or not 1-64
          characters of A-Z / a-z / 0-9 / "_" / "-" starting with a letter
          or digit (the value is never echoed back)
    404 - match_id not found in matches table
    503 - rewind_history.db not present on disk, or a SQLite read failed
          (locked, malformed, missing table) - safe to retry
    500 - anything else; logged with its traceback, generic body

Every body is strict JSON (``allow_nan=False``): a NaN or Infinity token
would make the browser's ``response.json()`` throw and blank the panel.

Model: loaded lazily and re-loaded when the file's (inode, mtime_ns, size)
stamp changes, so a fresh train does not need an RC restart. A model file that
cannot be loaded, or whose weights are not ``WPA_FEATURE_COUNT`` finite
numbers, is logged once per file version and treated as absent - the
response then honestly says ``"model": "fallback"`` (a wrong-length model
made ``WpaModel.predict_prob`` answer a constant 0.5, so every event read
wpa 0.0 under a "trained" label).

Caching: 5 minute monotonic TTL keyed on (match_id, model signature,
model load generation). The generation moves on every re-load, so a
retrain that keeps the same version and n_samples still invalidates the
cache. Cache reads and writes hold ``_CACHE_LOCK`` (ThreadingHTTPServer);
an unserialisable payload is never cached.

s144 true-audit cycle 86 hardened every line above; the tests are
tests/test_routes_post_game_wpa_audit_s144.py.
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

from core.post_game_score import (
    WPA_FEATURE_COUNT,
    WPA_MODEL_VERSION,
    WpaModel,
    compute_match_wpa,
    load_model,
)
from dashboard._context import APP_DIR as _APP_DIR

log = logging.getLogger("rc.web_dashboard")

# Anchored on APP_DIR (not the CWD) so a non-root working directory does
# not silently 503 - mirrors routes_replay_events (audit cycle 8 slice E).
_REWIND_DB = _APP_DIR / "data" / "rewind_history.db"
_MODEL_PATH = _APP_DIR / "data" / "post_game_wpa_model.json"

# Riot match ids are "<PLATFORM>_<gameId>" ("NA1_1234567890", 14 chars in
# the live DB); bare gameIds and test ids ("TEST_M1") also pass. ASCII
# only by construction of the character class.
_MATCH_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_MATCH_ID_ERROR = ("match_id must be 1-64 characters of A-Z, a-z, 0-9, "
                   "_ or -, starting with a letter or digit")

# Cache: {(match_id, model_sig, model_gen): (monotonic_ts, payload)}
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_S = 300.0
_CACHE_MAX = 256
_CACHE_EVICT = 64

# Lazy-loaded model with file-stamp tracking. "mtime" holds the
# (st_ino, st_mtime_ns, st_size) stamp of the loaded file (None = no file);
# "gen" counts re-loads and is part of the response-cache key.
_MODEL_CACHE: dict[str, object] = {"mtime": None, "model": None, "gen": 0}
_MODEL_LOCK = threading.Lock()

# load_model() catches OSError / ValueError and from_json_dict's
# TypeError / ValueError, but a list- or string-shaped document raises
# AttributeError, an overflowing n_samples OverflowError and a too-deep
# document RecursionError - each escaped and 500'd every request until
# the file changed.
_MODEL_LOAD_ERRORS = (AttributeError, OverflowError, RecursionError,
                      TypeError, ValueError, OSError)


def _json_body(obj: dict) -> bytes:
    """Strict JSON bytes; raises ValueError on a NaN / Infinity value."""
    return json.dumps(obj, allow_nan=False).encode("utf-8")


def _send_json(h, status: int, obj: dict) -> None:
    h._send(status, _json_body(obj), "application/json")


def _model_stamp() -> tuple[tuple[int, int, int] | None, bool]:
    """(stamp, ok). stamp None = no model file. ok False = a transient
    stat failure, in which case the caller keeps what it already has."""
    try:
        st = _MODEL_PATH.stat()
    except FileNotFoundError:
        return None, True
    except OSError as exc:
        log.warning("api/post-game-wpa: model stat failed, keeping the "
                    "loaded model: %s: %s", type(exc).__name__, exc)
        return None, False
    # st_ino: save_model replaces the file atomically, so a retrain is a
    # new file even inside one clock tick at the same size.
    return (st.st_ino, st.st_mtime_ns, st.st_size), True


def _load_usable_model(path: Path) -> WpaModel | None:
    """The model at ``path`` if it can drive predictions, else None.

    Logs (once per file version, since the caller records the stamp
    whatever the outcome) why a present file was not used."""
    try:
        model = load_model(path)
    except _MODEL_LOAD_ERRORS as exc:
        log.warning("api/post-game-wpa: model file unloadable, using the "
                    "fallback estimator: %s", type(exc).__name__,
                    exc_info=not isinstance(exc, RecursionError))
        return None
    if model is None:
        # load_model already logged the reason.
        return None
    if not isinstance(model, WpaModel):
        log.warning("api/post-game-wpa: model loader returned %s, using "
                    "the fallback estimator", type(model).__name__)
        return None
    if len(model.weights) != WPA_FEATURE_COUNT:
        log.warning("api/post-game-wpa: model has %d weights, expected %d "
                    "- using the fallback estimator",
                    len(model.weights), WPA_FEATURE_COUNT)
        return None
    if not all(math.isfinite(w) for w in model.weights):
        log.warning("api/post-game-wpa: model has non-finite weights - "
                    "using the fallback estimator")
        return None
    return model


def _current_model_entry() -> tuple[WpaModel | None, str, int]:
    """(model or None, signature, load generation), re-loading when the
    model file's stamp changes. Thread-safe."""
    with _MODEL_LOCK:
        stamp, ok = _model_stamp()
        if ok and stamp != _MODEL_CACHE["mtime"]:
            _MODEL_CACHE["model"] = (_load_usable_model(_MODEL_PATH)
                                     if stamp is not None else None)
            _MODEL_CACHE["mtime"] = stamp
            _MODEL_CACHE["gen"] = int(_MODEL_CACHE.get("gen") or 0) + 1
        model = _MODEL_CACHE["model"]
        gen = int(_MODEL_CACHE.get("gen") or 0)
    if isinstance(model, WpaModel):
        return model, f"v{model.version}.n{model.n_samples}", gen
    return None, "fallback", gen


def _current_model() -> tuple[WpaModel | None, str]:
    """Return the active model (or None) plus its signature string."""
    model, sig, _gen = _current_model_entry()
    return model, sig


def _cache_get(key: tuple) -> dict | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        ts, payload = entry
        if (now - ts) > _CACHE_TTL_S:
            _CACHE.pop(key, None)
            return None
        return payload


def _cache_put(key: tuple, payload: dict) -> None:
    now = time.monotonic()
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        # Bound the cache size; mirrors routes_personal_vs.
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in victims[:_CACHE_EVICT]:
                _CACHE.pop(k, None)


def _match_exists(conn: sqlite3.Connection, match_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM matches WHERE match_id=? LIMIT 1", (match_id,)
    )
    return cur.fetchone() is not None


def _open_rewind_db_ro() -> sqlite3.Connection:
    """Read-only connection. ``Path.as_uri`` percent-encodes the path, so
    a '#', '%' or '?' in the checkout path no longer truncates the URI
    (an f-string ``file:{path}?mode=ro`` opened the wrong file)."""
    uri = Path(_REWIND_DB).absolute().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


_LANE_END_S = 900  # 15:00 - standard laning-phase boundary (aggregator G lane-vs-full split)


def _wpa_totals(events: list, lane_end_s: int = _LANE_END_S) -> dict:
    """Lane-phase vs full-game WPA totals (aggregator G lane-vs-full lift).

    Pure sum over the per-event ``wpa`` already in the response - no new data
    source. ``net_wpa`` is the signed swing (the +/-), ``abs_wpa`` the total
    magnitude of swing, ``lane_share`` the fraction of total magnitude that
    landed at or before the laning-phase boundary. Events with a non-numeric,
    non-finite or absent ``wpa`` are skipped; an absent ``game_time`` counts
    as lane.
    """
    lane_net = lane_abs = full_net = full_abs = 0.0
    lane_n = full_n = 0
    for ev in events:
        w = ev.get("wpa")
        if not isinstance(w, (int, float)) or isinstance(w, bool):
            continue
        if not math.isfinite(w):
            continue
        full_n += 1
        full_net += w
        full_abs += abs(w)
        if (ev.get("game_time") or 0) <= lane_end_s:
            lane_n += 1
            lane_net += w
            lane_abs += abs(w)
    lane_share = (lane_abs / full_abs) if full_abs else 0.0
    return {
        "lane_end_s": lane_end_s,
        "lane": {"events": lane_n, "net_wpa": round(lane_net, 4), "abs_wpa": round(lane_abs, 4)},
        "full": {"events": full_n, "net_wpa": round(full_net, 4), "abs_wpa": round(full_abs, 4)},
        "lane_share": round(lane_share, 4),
    }


def _you_flagged(match_id: str) -> list[dict]:
    """RM-638: the player's in-game "mark this moment" pins for this match
    (core/moment_marks.py). ADDITIVE field, read per request (never cached);
    any failure is an empty list."""
    try:
        from core.moment_marks import pins_for_match
        return pins_for_match(match_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("api/post-game-wpa: you_flagged unavailable: %s", exc)
        return []


def _parse_match_id(path: str) -> tuple[str | None, str | None]:
    """(match_id, None) or (None, error message for a 400)."""
    qs = parse_qs(urlparse(path).query, keep_blank_values=True)
    values = qs.get("match_id") or []
    if len(values) > 1:
        return None, "match_id given more than once"
    # Not stripped: a padded or newline-terminated id is malformed.
    match_id = values[0] if values else ""
    if not match_id:
        return None, "match_id required"
    if not _MATCH_ID_RE.fullmatch(match_id):
        return None, _MATCH_ID_ERROR
    return match_id, None


def _serve_post_game_wpa(h) -> None:
    """GET /api/post-game-wpa?match_id=<id>"""
    try:
        match_id, err = _parse_match_id(h.path)
        if err is not None:
            _send_json(h, 400, {"ok": False, "error": err})
            return

        if not _REWIND_DB.exists():
            _send_json(h, 503, {"ok": False,
                                "error": "rewind_history.db missing"})
            return

        t0 = time.perf_counter()
        model, model_sig, model_gen = _current_model_entry()
        model_label = "trained" if model is not None else "fallback"
        cache_key = (match_id, model_sig, model_gen)
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            payload["cached"] = True
            payload["you_flagged"] = _you_flagged(match_id)
            _send_json(h, 200, payload)
            return

        try:
            conn = _open_rewind_db_ro()
            try:
                found = _match_exists(conn, match_id)
                body = (compute_match_wpa(conn, match_id, model=model)
                        if found else None)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            log.warning("api/post-game-wpa: rewind_history.db read failed "
                        "for %s: %s: %s", match_id, type(exc).__name__, exc)
            _send_json(h, 503, {
                "ok": False,
                "error": "rewind history unavailable - retry shortly",
            })
            return

        if body is None:
            _send_json(h, 404, {
                "ok": False, "error": "match_id not found",
                "match_id": match_id,
            })
            return

        payload = dict(body)
        if not payload.get("ok"):
            # no_timeline or similar - still 200 so the frontend can
            # render an empty state rather than treat it as an outage.
            # Not cached.
            payload["match_id"] = match_id
        payload["model"] = model_label
        payload["model_version"] = WPA_MODEL_VERSION
        payload["totals"] = _wpa_totals(payload.get("events", []))
        # Cache the enriched payload (model fields included) so a cached
        # hit serves the same shape as a fresh response; only the
        # per-request fields (elapsed_ms / cached / you_flagged) are
        # recomputed.
        cacheable = dict(payload) if payload.get("ok") else None
        payload["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        payload["cached"] = False
        payload["you_flagged"] = _you_flagged(match_id)
        # Serialise BEFORE caching: a NaN that json.dumps would refuse
        # must not be cached and replayed as a 500 for five minutes.
        raw = _json_body(payload)
        if cacheable is not None:
            _cache_put(cache_key, cacheable)
        h._send(200, raw, "application/json")
    except Exception:  # generic 500 wrapper
        log.exception("api/post-game-wpa: unexpected failure")
        try:
            # Raw exception text can leak file paths - log it, never
            # render it (same policy as dashboard/_handler.do_POST).
            _send_json(h, 500, {"ok": False,
                                "error": "internal error - see logs"})
        except OSError as send_exc:
            log.warning("api/post-game-wpa: could not send the 500: %s: %s",
                        type(send_exc).__name__, send_exc)


def _equals(p: str):
    """Local matcher mirroring routes_personal_vs._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/post-game-wpa"), _serve_post_game_wpa),
]

POST_ROUTES: list = []
