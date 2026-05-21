"""Per-role grading rubric route.

GET /api/post-game-rubric?match_id=<id>

First live consumer of ``core/post_game_rubric.py`` (item 131 Slice A,
commit be14388). Reads the operator's participant row from
``data/rewind_history.db`` for the given match_id (operator PUUID is
loaded from ``data/rewind_catchup.state.json``), runs the per-role
rubric, and returns the role-aware S+/S/A/B/C/D grade alongside the
raw 0-100 total_score and the component breakdown.

Response shape:

    {
      "ok": true,
      "match_id": "NA1_1234567890",
      "role": "ADC",
      "total_score": 64.3,
      "components": {
        "kda": 18.6, "cs_per_min": 12.7, "obj_participation": 4.2,
        "vision": 1.1, "dpm": 8.9
      },
      "percentile_grade": "A",
      "weights_used": {"kda": 2.1, "cs_per_min": 0.85, ...},
      "elapsed_ms": 7,
      "cached": false
    }

Failures:

    400 - match_id missing or empty
    404 - match_id not found OR no operator row in participants
    503 - rewind_history.db missing OR state.json missing or
          carries no PUUID

The 5-minute TTL cache mirrors ``routes_post_game_wpa``; SQLite is
opened read-only via the ``mode=ro`` URI.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.post_game_rubric import _DEFAULT_WEIGHTS, _normalize_role, compute_role_grade

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = Path("data") / "rewind_history.db"
_STATE_JSON = Path("data") / "rewind_catchup.state.json"

# Cache: {match_id: (timestamp, payload)}
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_S = 300.0


def _cache_get(key: str) -> dict | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if (time.time() - ts) > _CACHE_TTL_S:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: str, payload: dict) -> None:
    _CACHE[key] = (time.time(), payload)
    if len(_CACHE) > 256:
        victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:64]
        for k, _ in victims:
            _CACHE.pop(k, None)


def _load_operator_puuid() -> tuple[str | None, str | None]:
    """Return (current_puuid, stale_puuid) from state.json.

    Either may be None. Fail-soft: malformed JSON or missing file yields
    (None, None) so the route can raise 503 cleanly.
    """
    try:
        raw = _STATE_JSON.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    cur = data.get("puuid") or data.get("current_puuid")
    stale = data.get("stale_puuid")
    cur = cur if isinstance(cur, str) and cur else None
    stale = stale if isinstance(stale, str) and stale else None
    return cur, stale


def _fetch_match_and_row(conn: sqlite3.Connection, match_id: str,
                        puuids: tuple[str, ...]) -> tuple[bool, dict | None]:
    """Return (match_exists, operator_row_or_None).

    Operator row is the participant whose puuid matches any of the
    candidates (current first, then stale - PUUID rotation per
    reference_riot_puuid_rotation memory).
    """
    cur = conn.execute(
        "SELECT game_duration_s FROM matches WHERE match_id=? LIMIT 1",
        (match_id,),
    )
    match_row = cur.fetchone()
    if match_row is None:
        return False, None
    game_duration_s = int(match_row[0] or 0)

    for puuid in puuids:
        if not puuid:
            continue
        cur = conn.execute(
            "SELECT puuid, team_position, kills, deaths, assists, "
            "total_minions_killed, neutral_minions_killed, vision_score, "
            "total_damage_dealt_to_champs "
            "FROM participants WHERE match_id=? AND puuid=? LIMIT 1",
            (match_id, puuid),
        )
        row = cur.fetchone()
        if row is None:
            continue
        cs = int(row[5] or 0) + int(row[6] or 0)
        return True, {
            "puuid": row[0],
            "team_position": row[1] or "",
            "kills": int(row[2] or 0),
            "deaths": int(row[3] or 0),
            "assists": int(row[4] or 0),
            "cs": cs,
            "vision_score": int(row[7] or 0),
            "damage_dealt_to_champions": int(row[8] or 0),
            "game_duration_s": game_duration_s,
        }
    return True, None


def _weights_dict(role: str) -> dict[str, float]:
    """Return the canonical weights for a role as a plain dict."""
    w = _DEFAULT_WEIGHTS.get(role)
    if w is None:
        return {}
    return {
        "kda": w.kda,
        "cs_per_min": w.cs_per_min,
        "obj_participation": w.obj_participation,
        "vision_score": w.vision_score,
        "damage_per_min": w.damage_per_min,
    }


def _serve_post_game_rubric(h) -> None:
    """GET /api/post-game-rubric?match_id=<id>"""
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

        cur_puuid, stale_puuid = _load_operator_puuid()
        if not cur_puuid and not stale_puuid:
            h._send(503, json.dumps({
                "ok": False, "error": "rewind_catchup state missing",
            }).encode(), "application/json")
            return

        t0 = time.time()
        cached = _cache_get(match_id)
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
            exists, row = _fetch_match_and_row(
                conn, match_id, (cur_puuid or "", stale_puuid or ""),
            )
        finally:
            conn.close()

        if not exists:
            h._send(404, json.dumps({
                "ok": False, "error": "match_id not found",
                "match_id": match_id,
            }).encode(), "application/json")
            return
        if row is None:
            h._send(404, json.dumps({
                "ok": False, "error": "operator participant row not found",
                "match_id": match_id,
            }).encode(), "application/json")
            return

        # core.post_game_rubric.compute_role_grade expects game_time_s
        # (NOT game_duration_minutes - the spec wording diverged from the
        # shipped module API; the module is the source of truth).
        # obj_participation_pct is not stored as a column - kept at 0
        # for the initial slice; future enrichment can fold in
        # objectives_stolen / dragon_kills / baron_kills for a rough
        # participation proxy.
        stats = {
            "kills": row["kills"],
            "deaths": row["deaths"],
            "assists": row["assists"],
            "cs": row["cs"],
            "game_time_s": row["game_duration_s"],
            "vision_score": row["vision_score"],
            "damage_dealt_to_champions": row["damage_dealt_to_champions"],
            "obj_participation_pct": 0.0,
        }
        result = compute_role_grade(stats, row["team_position"])

        payload = {
            "ok": True,
            "match_id": match_id,
            "role": result["role"],
            "total_score": result["total_score"],
            "components": result["components"],
            "percentile_grade": result["percentile_grade"],
            "weights_used": _weights_dict(result["role"]),
            "elapsed_ms": int((time.time() - t0) * 1000),
            "cached": False,
        }
        _cache_put(match_id, {
            "ok": True,
            "match_id": match_id,
            "role": result["role"],
            "total_score": result["total_score"],
            "components": result["components"],
            "percentile_grade": result["percentile_grade"],
            "weights_used": payload["weights_used"],
        })

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        log.warning("api/post-game-rubric: %s", exc)
        try:
            h._send(500, json.dumps({"ok": False, "error": str(exc)[:200]}).encode(),
                    "application/json")
        except Exception:
            pass


def _equals(p: str):
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


# Suppress unused-import warning for _normalize_role - kept available
# so importers can call the same canonicalizer the route uses.
_ = _normalize_role


GET_ROUTES = [
    (_equals("/api/post-game-rubric"), _serve_post_game_rubric),
]

POST_ROUTES: list = []
