"""GET /api/personal-build - personal per-champion build win-rate (read-only).

Serves ``core.personal_build_wr.compute_personal_build`` over the LOCAL
rewind_history.db. Surfaces which completed items the operator actually WINS
with on a champion (confidence-weighted lift vs their own baseline), an additive
"your best build" read alongside the DS engine recommendation - no Riot API, no
Claude. Closes the personal-WR-build-override local-data half from
docs/COMPETITOR_LIFT_2026-06-16.md.

Request shape:
  GET /api/personal-build?champion=Vayne[&mode=sr|aram|arena]

  champion : required champion display name (e.g. Vayne, Kai'Sa). Empty or
             malformed -> 400.
  mode     : sr | aram | arena. Default sr. Anything else -> 400.

Response is exactly ``compute_personal_build(...)``'s dict plus ``cached`` (bool)
and ``elapsed_ms`` (int). See ``core.personal_build_wr._empty`` for the shape.

Cache: 5min in-process, keyed by (mode, champion). The compute scans the rewind
db; a panel re-polling on a timer would otherwise hot-loop the DB.

A raw exception string is NEVER leaked to the client.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import personal_build_wr
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_VALID_MODES = ("sr", "aram", "arena")
# Champion display names: letters/digits/space + the apostrophe/period/ampersand
# that appear in real names (Kai'Sa, Dr. Mundo, Nunu & Willump). Bounded length.
_CHAMP_RE = re.compile(r"^[A-Za-z0-9 '.&]{1,40}$")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256
_CACHE_EVICT = 64


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return ("sr", None)
    if raw not in _VALID_MODES:
        return ("", f"mode must be one of {', '.join(_VALID_MODES)}")
    return (raw, None)


def _serve_personal_build(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        champ_raw = (qs.get("champion") or [""])[0].strip()
        mode_raw = (qs.get("mode") or [""])[0].strip().lower()

        if not champ_raw or not _CHAMP_RE.match(champ_raw):
            h._send(400, json.dumps(
                {"ok": False, "error": "champion query param required"}
            ).encode("utf-8"), "application/json")
            return
        mode, err = _parse_mode(mode_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (mode, champ_raw.lower())
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        try:
            payload = personal_build_wr.compute_personal_build(champ_raw, mode)
        except Exception as exc:  # noqa: BLE001
            log.warning("api/personal-build compute: %s", exc)
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

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/personal-build: %s", exc)
        try:
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"})
                .encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/personal-build"), _serve_personal_build),
]
