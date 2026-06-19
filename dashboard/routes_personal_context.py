"""Personal context surface route (ADR-007 phase 2 follow-up; CLAUDE.md item 124).

GET /api/personal-context

Surfaces the same top-3 death patterns the mode coaches inject into their
system prompts (via core.death_patterns_loader.personal_context_block).
Reads data/coaching/death_patterns.json (written by scripts/postmortem_
analyze.py) and returns a structured payload the dashboard panel can
render alongside the coach output.

Response shape (populated):

    {
      "ok": true,
      "generated_at": "2026-05-21T03:14:15Z",
      "total_deaths": 28236,
      "total_matches": 2838,
      "top3": [
        {
          "key": "solo_pickoff",
          "label": "Solo pickoffs",
          "description": "...",
          "count": 16595,
          "rate": 0.5877,
          "confidence": 0.9997
        },
        ...
      ],
      "role_grades": {
        "total_matches_scored": 624,
        "overall": {"count": 624, "median_score": 41,
                    "tier_distribution": {"S+": 0, "S": 8, "A": 56, ...}},
        "by_role": {
          "ADC": {"count": 177, "median_score": 41,
                  "tier_distribution": {...}},
          ...
        }
      }
    }

The role_grades block is OMITTED from the payload when schema_version=1
files (no role_grades section) are loaded. Frontend treats missing key
the same as zero-count.

Response shape (empty / missing data):

    {"ok": false, "reason": "no_data"}

The empty path returns HTTP 200 (not 404) so the frontend panel renders
the muted empty-state chip instead of treating it as a fetch error.
That matches the loader's fail-soft contract (top_patterns() returns []
on missing/malformed JSON).

Caching: 60 second in-process TTL keyed on the JSON file's mtime so a
fresh analyzer run is picked up without an RC restart. When the file is
absent the TTL still applies so re-checks aren't free-form FS hits.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from core.death_patterns_loader import (
    report_summary,
    role_grades_summary,
    top_patterns,
)

log = logging.getLogger("rc.web_dashboard")

_DEATH_PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "coaching" / "death_patterns.json"
)

_CACHE_TTL_S = 60.0
# {"mtime": float | None, "expires_at": float, "payload": dict}
_CACHE: dict = {"mtime": None, "expires_at": 0.0, "payload": None}


def _current_mtime() -> float | None:
    try:
        return _DEATH_PATTERNS_PATH.stat().st_mtime
    except OSError:
        return None


def _build_payload() -> dict:
    """Compose the response payload off the loader helpers.

    Returns the ok=false {"reason": "no_data"} envelope when the top-3 is
    empty (missing file, malformed JSON, or zero-count patterns).
    """
    patterns = top_patterns(_DEATH_PATTERNS_PATH)
    if not patterns:
        return {"ok": False, "reason": "no_data"}
    summary = report_summary(_DEATH_PATTERNS_PATH)
    payload: dict = {"ok": True, "top3": patterns}
    if "generated_at" in summary:
        payload["generated_at"] = summary["generated_at"]
    payload["total_deaths"] = summary.get("total_deaths", 0)
    payload["total_matches"] = summary.get("total_matches", 0)
    rg = role_grades_summary(_DEATH_PATTERNS_PATH)
    if rg:
        payload["role_grades"] = rg
    return payload


def _cache_hit(now: float) -> dict | None:
    """Return the cached payload if still fresh + mtime unchanged."""
    if _CACHE["payload"] is None:
        return None
    if now >= _CACHE["expires_at"]:
        return None
    mtime = _current_mtime()
    if mtime != _CACHE["mtime"]:
        return None
    return _CACHE["payload"]


def _cache_store(payload: dict, now: float) -> None:
    _CACHE["payload"] = payload
    _CACHE["mtime"] = _current_mtime()
    _CACHE["expires_at"] = now + _CACHE_TTL_S


def _serve_personal_context(h) -> None:
    """GET /api/personal-context"""
    try:
        now = time.time()
        cached = _cache_hit(now)
        if cached is not None:
            h._send(200, json.dumps(cached).encode("utf-8"), "application/json")
            return
        payload = _build_payload()
        _cache_store(payload, now)
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        log.warning("api/personal-context: %s", exc)
        try:
            # Raw exception text stays in the log only.
            h._send(
                500,
                json.dumps({"ok": False,
                            "error": "internal error - see logs"})
                .encode("utf-8"),
                "application/json",
            )
        except Exception:  # noqa: BLE001
            pass


def _equals(p: str):
    """Local matcher mirroring routes_replay_events._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/personal-context"), _serve_personal_context),
]

POST_ROUTES: list = []
