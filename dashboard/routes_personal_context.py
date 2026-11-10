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

Caching: 60 second in-process TTL keyed on the JSON file's stat signature
(mtime in ns, size, file id) so a fresh analyzer run is picked up without
an RC restart. When the file is absent the TTL still applies so re-checks
aren't free-form FS hits.

Hardening contract (s144 true-audit cycle 216, S144-T-609):
- The signature is taken BEFORE the build and again after it. A file
  replaced mid-build (the loader reads it three times) is rebuilt once; a
  payload is cached only under the signature it was read at, so an old
  payload is never pinned under a new file's signature, and one payload
  never mixes two file versions.
- The TTL runs on time.monotonic; an entry stamped further ahead than one
  TTL (it cannot be, unless the clock or the cache was tampered with) is
  never served.
- role_grades is rebuilt to the producer's shape
  (scripts/postmortem_analyze.aggregate_role_grades): known keys only,
  counts are non-negative ints, median_score an int in [0, 100], the six
  tiers always present; a wrong-typed value reads 0 and a non-dict bucket
  is dropped.
- The body is encoded with allow_nan=False and cached as bytes; a payload
  that cannot be strict JSON is the fixed 500 and is not cached.
- The last-resort path is dashboard._errors.send_error (fixed body, cause
  logged once with its type name, control characters escaped). Only an
  OSError while sending that 500 (the client went away) is swallowed.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path

from core.death_patterns_loader import (
    report_summary,
    role_grades_summary,
    top_patterns,
)
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

_DEATH_PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "coaching" / "death_patterns.json"
)

_CACHE_TTL_S = 60.0
# {"sig": tuple | None, "expires_at": float (time.monotonic), "payload": bytes | None}
# Read and written only under _CACHE_LOCK; the build runs outside it.
_CACHE: dict = {"sig": None, "expires_at": 0.0, "payload": None}
_CACHE_LOCK = threading.Lock()

# Mirrors scripts/postmortem_analyze._CANONICAL_ROLES / _TIER_ORDER.
_ROLES = ("ADC", "SUP", "JG", "MID", "TOP")
_TIERS = ("S+", "S", "A", "B", "C", "D")
# Far past any real match count; a larger number is corruption.
_MAX_COUNT = 10 ** 9
_MAX_SCORE = 100


def _signature() -> tuple | None:
    """(mtime_ns, size, file id) of the report, or None when it is absent."""
    try:
        st = _DEATH_PATTERNS_PATH.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _count(value) -> int:
    """A non-negative integral count, else 0 (bool and fractional are 0)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if 0 <= value <= _MAX_COUNT else 0


def _score(value) -> int:
    """A median score in [0, 100] as an int, else 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    if not 0 <= value <= _MAX_SCORE:
        return 0
    return round(value)


def _bucket(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    tiers = value.get("tier_distribution")
    if not isinstance(tiers, dict):
        tiers = {}
    return {
        "count": _count(value.get("count")),
        "median_score": _score(value.get("median_score")),
        "tier_distribution": {t: _count(tiers.get(t)) for t in _TIERS},
    }


def _role_grades(rg: dict) -> dict:
    """Rebuild the role_grades section to the producer's shape."""
    out: dict = {"total_matches_scored": _count(rg.get("total_matches_scored"))}
    overall = _bucket(rg.get("overall"))
    if overall is not None:
        out["overall"] = overall
    by_role = rg.get("by_role")
    if isinstance(by_role, dict):
        roles = {}
        for role in _ROLES:
            bucket = _bucket(by_role.get(role))
            if bucket is not None:
                roles[role] = bucket
        out["by_role"] = roles
    return out


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
        payload["role_grades"] = _role_grades(rg)
    return payload


def _cache_hit(now: float, sig: tuple | None) -> bytes | None:
    """The cached body if it is fresh and was read at the same signature."""
    with _CACHE_LOCK:
        body = _CACHE["payload"]
        expires_at = _CACHE["expires_at"]
        cached_sig = _CACHE.get("sig")
    if body is None or not now < expires_at <= now + _CACHE_TTL_S:
        return None
    if cached_sig != sig:
        return None
    return body


def _cache_store(body: bytes, sig: tuple | None, now: float) -> None:
    with _CACHE_LOCK:
        _CACHE["payload"] = body
        _CACHE["sig"] = sig
        _CACHE["expires_at"] = now + _CACHE_TTL_S


def _build_consistent() -> tuple[dict, tuple | None, bool]:
    """Build the payload from one file version.

    Returns (payload, signature it was read at, stable). A file replaced
    mid-build is rebuilt once; if it moves again the payload is still
    served but not cached (stable=False).
    """
    for _attempt in range(2):
        before = _signature()
        payload = _build_payload()
        if _signature() == before:
            return payload, before, True
    return payload, None, False


def _serve_personal_context(h) -> None:
    """GET /api/personal-context."""
    try:
        now = time.monotonic()
        cached = _cache_hit(now, _signature())
        if cached is not None:
            h._send(200, cached, "application/json")
            return
        payload, sig, stable = _build_consistent()
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        if stable:
            _cache_store(body, sig, now)
        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001 - last-resort 500 wrapper
        try:
            send_error(h, exc, fields={"ok": False}, log_traceback=True)
        except OSError as send_exc:
            # The client went away; nothing left to tell it.
            log.debug("api/personal-context: 500 not sent: %s",
                      type(send_exc).__name__)


def _equals(p: str):
    """Local matcher mirroring routes_replay_events._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/personal-context"), _serve_personal_context),
]

POST_ROUTES: list = []
