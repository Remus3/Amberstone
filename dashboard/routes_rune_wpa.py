"""Per-rune (keystone + minor) WPA route over RC's own rewind corpus.

GET /api/rune-wpa?min_n=20&queue_id=&patch=

The pre-game analog of /api/item-wpa and /api/skill-wpa. Reads
``data/rewind_history.db`` read-only, decomposes each ``(rune, slot_kind)``
local winrate into expected (the WPA model's win-prob at the EARLIEST
timeline frame - the start-of-game pre-game baseline) vs observed, returns
the selection-bias-corrected residual (``wpa``) plus a shrink-damped
``wpa_shrunk`` sorted descending. Feeds the post-game review reframe
alongside item-WPA and skill-WPA.

Response shape mirrors /api/item-wpa with rune fields::

    {
      "ok": true, "patch": null, "queue_id": null, "min_n": 20,
      "items": [
        {"rune_id": 8112, "name": "Electrocute", "slot_kind": "keystone",
         "n": 41, "observed_winrate": 0.56, "expected_winrate": 0.50,
         "wpa": 0.06, "wpa_shrunk": 0.059},
        ...
      ],
      "elapsed_ms": 38, "cached": false
    }

HONEST FRAMING - descriptive personal-corpus lens; runes are an even weaker
signal than items (a keystone is largely champion-fixed), so shrink + min_n
are load-bearing. Stat shards are excluded (not named runes); the keystone
vs minor split keeps a keystone residual from being diluted by minors.

Failures:
    503 - rewind_history.db not present
    ok=false (200) - compute raised

Caching: 5 minute TTL keyed on (min_n, queue_id, patch, model_signature),
mirroring routes_item_wpa / routes_skill_wpa.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.post_game_score import WpaModel, load_model
from core.rune_wpa import compute_rune_wpa

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = Path("data") / "rewind_history.db"
_MODEL_PATH = Path("data") / "post_game_wpa_model.json"

_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL_S = 300.0
_MODEL_CACHE: dict[str, object] = {"mtime": None, "model": None}


def _current_model() -> tuple[WpaModel | None, str]:
    """Active WPA model plus a cache-key signature; reloads on mtime change."""
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


def _serve_rune_wpa(h) -> None:
    """GET /api/rune-wpa?min_n=20&queue_id=&patch="""
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
            body = compute_rune_wpa(
                conn, min_n=min_n, queue_id=queue_id, patch=patch, model=model
            )
        finally:
            conn.close()

        payload = dict(body)
        payload["model"] = "trained" if model is not None else "fallback"
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        payload["cached"] = False
        if body.get("ok"):
            _cache_put(cache_key, dict(body))

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        log.warning("api/rune-wpa: %s", exc)
        try:
            h._send(500, json.dumps({"ok": False, "error": str(exc)[:200]}).encode(),
                    "application/json")
        except Exception:
            pass


def _equals(p: str):
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/rune-wpa"), _serve_rune_wpa),
]

POST_ROUTES: list = []
