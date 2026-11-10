"""Per-item WPA route over RC's own rewind corpus.

GET /api/item-wpa?min_n=20&queue_id=&patch=

Reads ``data/rewind_history.db`` read-only, decomposes each completed-
legendary item's local winrate into expected (the WPA model's win-prob at
the purchase frame) vs observed, returns the selection-bias-corrected
residual (``wpa``) plus a shrink-damped ``wpa_shrunk`` sorted descending.
Backs the post-game review (S2 reframe): which of the operator's habitual
legendary buys actually pull their weight.

Query (each parameter at most once; an empty value is the same as absent):

    min_n     1-6 ASCII digits, default 20 (0 shows every item)
    queue_id  1-6 ASCII digits (0 = custom games), default no filter
    patch     "<major>.<minor>" or "<major>.<minor>.<build>" in ASCII
              digits ("14.24", "16.11.1"), default no filter

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
      "model": "trained" | "fallback",
      "elapsed_ms": 41,
      "cached": false
    }

HONEST FRAMING - descriptive personal-corpus lens, NOT a global meta
winrate and NOT a redistributable stat. Per-item N is modest, so the
shrink + min_n gate are load-bearing.

Failures:

    400 - a malformed or repeated min_n / queue_id / patch (the value is
          never echoed back; a typo in queue_id used to drop the filter
          and serve the whole corpus as if unfiltered)
    503 - rewind_history.db not present on disk, or a SQLite read failed
          (locked, malformed, missing table) - safe to retry
    500 - anything else; logged with its traceback, generic body

Every body is strict JSON (``allow_nan=False``): a NaN or Infinity token
would make the browser's ``response.json()`` throw and blank the panel.

Model: loaded lazily and re-loaded when the file's (inode, mtime_ns, size)
stamp changes, so a fresh train does not need an RC restart; a transient
stat failure keeps the loaded model. A model file that cannot be loaded,
or whose weights are not ``WPA_FEATURE_COUNT`` finite numbers, is logged
once per file version and treated as absent - the response then honestly
says ``"model": "fallback"`` (a wrong-length model made
``WpaModel.predict_prob`` answer a constant 0.5 under a "trained" label).

Caching: 5 minute monotonic TTL keyed on (min_n, queue_id, patch, model
signature, model load generation). The generation moves on every
re-load, so a retrain that keeps the same version and n_samples still
invalidates the cache. Cache reads and writes hold ``_CACHE_LOCK``
(ThreadingHTTPServer); a not-ok or unserialisable payload is never cached.

s144 true-audit cycle 87 hardened every line above; the tests are
tests/test_routes_item_wpa_audit_s144.py.
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

from core.item_wpa import compute_item_wpa
from core.post_game_score import WPA_FEATURE_COUNT, WpaModel, load_model
from dashboard._context import APP_DIR as _APP_DIR

log = logging.getLogger("rc.web_dashboard")

# Anchored on APP_DIR (not the CWD) so a non-root working directory does
# not silently 503 - mirrors routes_replay_events (audit cycle 8 slice E).
_REWIND_DB = _APP_DIR / "data" / "rewind_history.db"
_MODEL_PATH = _APP_DIR / "data" / "post_game_wpa_model.json"

_DEFAULT_MIN_N = 20

# ``[0-9]`` (not ``\d``) so only ASCII digits pass; int() alone accepted a
# sign, "_" separators, surrounding whitespace and non-ASCII digits, and an
# unbounded queue_id reached the SQLite bind as an OverflowError.
_COUNT_RE = re.compile(r"[0-9]{1,6}")
_PATCH_RE = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,4})?")
_QUERY_ERRORS = {
    "min_n": "min_n must be 1-6 ASCII digits",
    "queue_id": "queue_id must be 1-6 ASCII digits",
    "patch": ("patch must be <major>.<minor> or <major>.<minor>.<build> "
              "in ASCII digits"),
}

# Cache: {(min_n, queue_id, patch, model_sig, model_gen): (monotonic, payload)}
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_S = 300.0
_CACHE_MAX = 128
_CACHE_EVICT = 32

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
        log.warning("api/item-wpa: model stat failed, keeping the loaded "
                    "model: %s: %s", type(exc).__name__, exc)
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
        log.warning("api/item-wpa: model file unloadable, using the "
                    "fallback estimator: %s", type(exc).__name__,
                    exc_info=not isinstance(exc, RecursionError))
        return None
    if model is None:
        # load_model already logged the reason.
        return None
    if not isinstance(model, WpaModel):
        log.warning("api/item-wpa: model loader returned %s, using the "
                    "fallback estimator", type(model).__name__)
        return None
    if len(model.weights) != WPA_FEATURE_COUNT:
        log.warning("api/item-wpa: model has %d weights, expected %d - "
                    "using the fallback estimator",
                    len(model.weights), WPA_FEATURE_COUNT)
        return None
    if not all(math.isfinite(w) for w in model.weights):
        log.warning("api/item-wpa: model has non-finite weights - using "
                    "the fallback estimator")
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
    """Active WPA model (or None) plus its signature string."""
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
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in victims[:_CACHE_EVICT]:
                _CACHE.pop(k, None)


def _parse_query(path: str) -> tuple[tuple[int, int | None, str | None] | None,
                                     str | None]:
    """((min_n, queue_id, patch), None) or (None, error for a 400).

    Values are not stripped: a padded or newline-terminated value is
    malformed, and no rejected value is echoed in the error."""
    qs = parse_qs(urlparse(path).query, keep_blank_values=True)
    vals: dict[str, str] = {}
    for key in ("min_n", "queue_id", "patch"):
        got = qs.get(key) or []
        if len(got) > 1:
            return None, f"{key} given more than once"
        raw = got[0] if got else ""
        if raw:
            regex = _PATCH_RE if key == "patch" else _COUNT_RE
            if not regex.fullmatch(raw):
                return None, _QUERY_ERRORS[key]
        vals[key] = raw
    min_n = int(vals["min_n"]) if vals["min_n"] else _DEFAULT_MIN_N
    queue_id = int(vals["queue_id"]) if vals["queue_id"] else None
    patch = vals["patch"] or None
    return (min_n, queue_id, patch), None


def _open_rewind_db_ro() -> sqlite3.Connection:
    """Read-only connection. ``Path.as_uri`` percent-encodes the path, so
    a '#', '%' or '?' in the checkout path no longer truncates the URI
    (an f-string ``file:{path}?mode=ro`` opened the wrong file)."""
    uri = Path(_REWIND_DB).absolute().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)


def _serve_item_wpa(h) -> None:
    """GET /api/item-wpa?min_n=20&queue_id=&patch= (query params)."""
    try:
        query, err = _parse_query(h.path)
        if err is not None:
            _send_json(h, 400, {"ok": False, "error": err})
            return
        min_n, queue_id, patch = query

        if not _REWIND_DB.exists():
            _send_json(h, 503, {"ok": False,
                                "error": "rewind_history.db missing"})
            return

        t0 = time.perf_counter()
        model, model_sig, model_gen = _current_model_entry()
        cache_key = (min_n, queue_id, patch, model_sig, model_gen)
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            payload["cached"] = True
            _send_json(h, 200, payload)
            return

        try:
            conn = _open_rewind_db_ro()
            try:
                body = compute_item_wpa(
                    conn, min_n=min_n, queue_id=queue_id, patch=patch,
                    model=model,
                )
            finally:
                conn.close()
        except sqlite3.Error as exc:
            log.warning("api/item-wpa: rewind_history.db read failed: "
                        "%s: %s", type(exc).__name__, exc)
            _send_json(h, 503, {
                "ok": False,
                "error": "rewind history unavailable - retry shortly",
            })
            return

        payload = dict(body)
        payload["model"] = "trained" if model is not None else "fallback"
        # Cache the enriched payload (model field included) so a cached
        # hit serves the same shape as a fresh response.
        cacheable = dict(payload) if payload.get("ok") else None
        payload["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        payload["cached"] = False
        # Serialise BEFORE caching: a NaN that json.dumps would refuse
        # must not be cached and replayed as a 500 for five minutes.
        raw = _json_body(payload)
        if cacheable is not None:
            _cache_put(cache_key, cacheable)
        h._send(200, raw, "application/json")
    except Exception:  # generic 500 wrapper
        log.exception("api/item-wpa: unexpected failure")
        try:
            # Raw exception text can leak file paths - log it, never
            # render it (same policy as dashboard/_handler.do_POST).
            _send_json(h, 500, {"ok": False,
                                "error": "internal error - see logs"})
        except OSError as send_exc:
            log.warning("api/item-wpa: could not send the 500: %s: %s",
                        type(send_exc).__name__, send_exc)


def _equals(p: str):
    """Local matcher mirroring routes_post_game_wpa._equals."""
    def m(path: str) -> bool:
        return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/item-wpa"), _serve_item_wpa),
]

POST_ROUTES: list = []
