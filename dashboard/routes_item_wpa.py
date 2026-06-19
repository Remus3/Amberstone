"""Per-item WPA route over RC's own rewind corpus.

GET /api/item-wpa?min_n=20&queue_id=&patch=

Reads ``data/rewind_history.db`` read-only, decomposes each completed-
legendary item's local winrate into expected (the WPA model's win-prob at
the purchase frame) vs observed, returns the selection-bias-corrected
residual (``wpa``) plus a shrink-damped ``wpa_shrunk`` sorted descending.
Backs the post-game review (S2 reframe): which of the operator's habitual
legendary buys actually pull their weight.

Response shape:

    {
      "ok": true,
      "patch": null,
      "queue_id": null,
      "min_n": 20,
      "items": [
        {
          "item_id": 3031,
          "name": "Infinity Edge",
          "n": 184,
          "observed_winrate": 0.5870,
          "expected_winrate": 0.5512,
          "wpa": 0.0358,
          "wpa_shrunk": 0.0348,
          "avg_purchase_time_s": 1042.3
        },
        ...
      ],
      "elapsed_ms": 41,
      "cached": false
    }

HONEST FRAMING - descriptive personal-corpus lens, NOT a global meta
winrate and NOT a redistributable stat. Per-item N is modest, so the
shrink + min_n gate are load-bearing.

Failures:

    503 - rewind_history.db not present on disk
    ok=false (200) - compute raised / DB unavailable

Caching: 5 minute TTL keyed on (min_n, queue_id, patch, model_signature).
The model file is loaded once per process (lazy) and re-checked when its
mtime changes so a fresh train does not require an RC restart.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import parse_qs, urlparse

from core.item_wpa import compute_item_wpa
from core.post_game_score import WpaModel, load_model
from dashboard._context import APP_DIR as _APP_DIR

log = logging.getLogger("rc.web_dashboard")

# Anchored on APP_DIR (not the CWD) so a non-root working directory does
# not silently 503 - mirrors routes_replay_events (audit cycle 8 slice E).
_REWIND_DB = _APP_DIR / "data" / "rewind_history.db"
_MODEL_PATH = _APP_DIR / "data" / "post_game_wpa_model.json"

# Cache: {(min_n, queue_id, patch, model_sig): (timestamp, payload)}
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL_S = 300.0

# Lazy-loaded singleton with mtime tracking (mirrors routes_post_game_wpa).
_MODEL_CACHE: dict[str, object] = {"mtime": None, "model": None}


def _current_model() -> tuple[WpaModel | None, str]:
    """Active WPA model (or None) plus a cache-key signature; reloads on
    file mtime change."""
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
    if len(_CACHE) > 128:
        victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:32]
        for k, _ in victims:
            _CACHE.pop(k, None)


def _int_or_none(qs: dict, key: str) -> int | None:
    raw = (qs.get(key) or [""])[0].strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _serve_item_wpa(h) -> None:
    """GET /api/item-wpa?min_n=20&queue_id=&patch="""
    try:
        qs = parse_qs(urlparse(h.path).query)
        min_n = _int_or_none(qs, "min_n")
        if min_n is None:
            min_n = 20
        min_n = max(0, min_n)
        queue_id = _int_or_none(qs, "queue_id")
        patch = (qs.get("patch") or [""])[0].strip() or None

        if not _REWIND_DB.exists():
            h._send(503, json.dumps({
                "ok": False, "error": "rewind_history.db missing",
            }).encode(), "application/json")
            return

        t0 = time.time()
        model, model_sig = _current_model()
        cache_key = (min_n, queue_id, patch, model_sig)
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["elapsed_ms"] = int((time.time() - t0) * 1000)
            payload["cached"] = True
            h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return

        import sqlite3
        conn = sqlite3.connect(
            f"file:{_REWIND_DB}?mode=ro", uri=True, timeout=5.0
        )
        try:
            body = compute_item_wpa(
                conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
            )
        finally:
            conn.close()

        payload = dict(body)
        payload["model"] = "trained" if model is not None else "fallback"
        # Cache the enriched payload (model field included) so a cached
        # hit serves the same shape as a fresh response.
        if body.get("ok"):
            _cache_put(cache_key, dict(payload))
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        payload["cached"] = False

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        log.warning("api/item-wpa: %s", exc)
        try:
            # Raw exception text can leak file paths - log it, never
            # render it (same policy as dashboard/_handler.do_POST).
            h._send(500, json.dumps({
                "ok": False, "error": "internal error - see logs",
            }).encode(), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _equals(p: str):
    """Local matcher mirroring routes_post_game_wpa._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/item-wpa"), _serve_item_wpa),
]

POST_ROUTES: list = []
