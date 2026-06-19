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

    400 - match_id missing or empty
    404 - match_id not found in matches table
    503 - rewind_history.db not present on disk

Caching: 5 minute TTL keyed on (match_id, model_signature). The model
file is loaded once per process (lazy) and re-checked when its mtime
changes so a fresh train doesn't require an RC restart.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from urllib.parse import parse_qs, urlparse

from core.post_game_score import (
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

# Cache: {(match_id, model_sig): (timestamp, payload)}
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL_S = 300.0

# Lazy-loaded singleton with mtime tracking.
_MODEL_CACHE: dict[str, object] = {"mtime": None, "model": None}


def _current_model() -> tuple[WpaModel | None, str]:
    """Return the active model (or None) plus a signature string used
    for cache keys. Re-loads when the file mtime changes."""
    try:
        mtime = _MODEL_PATH.stat().st_mtime if _MODEL_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _MODEL_CACHE["mtime"]:
        _MODEL_CACHE["model"] = load_model(_MODEL_PATH) if mtime else None
        _MODEL_CACHE["mtime"] = mtime
    model = _MODEL_CACHE["model"]
    if isinstance(model, WpaModel):
        sig = f"v{model.version}.n{model.n_samples}"
    else:
        sig = "fallback"
    return model if isinstance(model, WpaModel) else None, sig


def _cache_get(key: tuple) -> dict | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if (time.time() - ts) > _CACHE_TTL_S:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple, payload: dict) -> None:
    _CACHE[key] = (time.time(), payload)
    # Bound the cache size; mirrors routes_personal_vs.
    if len(_CACHE) > 256:
        victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:64]
        for k, _ in victims:
            _CACHE.pop(k, None)


def _match_exists(conn: sqlite3.Connection, match_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM matches WHERE match_id=? LIMIT 1", (match_id,)
    )
    return cur.fetchone() is not None


_LANE_END_S = 900  # 15:00 - standard laning-phase boundary (aggregator G lane-vs-full split)


def _wpa_totals(events: list, lane_end_s: int = _LANE_END_S) -> dict:
    """Lane-phase vs full-game WPA totals (aggregator G lane-vs-full lift).

    Pure sum over the per-event ``wpa`` already in the response - no new data
    source. ``net_wpa`` is the signed swing (the +/-), ``abs_wpa`` the total
    magnitude of swing, ``lane_share`` the fraction of total magnitude that
    landed at or before the laning-phase boundary. Events with a non-numeric
    or absent ``wpa`` are skipped; an absent ``game_time`` counts as lane.
    """
    lane_net = lane_abs = full_net = full_abs = 0.0
    lane_n = full_n = 0
    for ev in events:
        w = ev.get("wpa")
        if not isinstance(w, (int, float)) or isinstance(w, bool):
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


def _serve_post_game_wpa(h) -> None:
    """GET /api/post-game-wpa?match_id=<id>"""
    try:
        qs = parse_qs(urlparse(h.path).query)
        match_id = (qs.get("match_id") or [""])[0].strip()
        if not match_id:
            h._send(400, json.dumps({
                "ok": False, "error": "match_id required",
            }).encode(), "application/json")
            return

        if not _REWIND_DB.exists():
            h._send(503, json.dumps({
                "ok": False, "error": "rewind_history.db missing",
            }).encode(), "application/json")
            return

        t0 = time.time()
        model, model_sig = _current_model()
        cache_key = (match_id, model_sig)
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["elapsed_ms"] = int((time.time() - t0) * 1000)
            payload["cached"] = True
            h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return

        conn = sqlite3.connect(
            f"file:{_REWIND_DB}?mode=ro", uri=True, timeout=2.0
        )
        try:
            if not _match_exists(conn, match_id):
                h._send(404, json.dumps({
                    "ok": False, "error": "match_id not found",
                    "match_id": match_id,
                }).encode(), "application/json")
                return
            body = compute_match_wpa(conn, match_id, model=model)
        finally:
            conn.close()

        if not body.get("ok"):
            # no_timeline or similar - still 200 so the frontend can
            # render an empty state rather than treat it as an outage.
            body["match_id"] = match_id
            body["model"] = "trained" if model is not None else "fallback"
            body["model_version"] = WPA_MODEL_VERSION
            body["totals"] = _wpa_totals(body.get("events", []))
            body["elapsed_ms"] = int((time.time() - t0) * 1000)
            body["cached"] = False
            h._send(200, json.dumps(body).encode("utf-8"), "application/json")
            return

        payload = dict(body)
        payload["model"] = "trained" if model is not None else "fallback"
        payload["model_version"] = WPA_MODEL_VERSION
        payload["totals"] = _wpa_totals(payload.get("events", []))
        # Cache the enriched payload (model fields included) so a cached
        # hit serves the same shape as a fresh response; only the
        # per-request fields (elapsed_ms / cached) are recomputed.
        _cache_put(cache_key, dict(payload))
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        payload["cached"] = False

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        log.warning("api/post-game-wpa: %s", exc)
        try:
            # Raw exception text can leak file paths - log it, never
            # render it (same policy as dashboard/_handler.do_POST).
            h._send(500, json.dumps({
                "ok": False, "error": "internal error - see logs",
            }).encode(), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _equals(p: str):
    """Local matcher mirroring routes_personal_vs._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/post-game-wpa"), _serve_post_game_wpa),
]

POST_ROUTES: list = []
