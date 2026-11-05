"""GET /api/playstyle-labels - deterministic per-champion playstyle fingerprint
(read-only).

Serves core.playstyle_labels.compute_playstyle_labels over the LOCAL
rewind_history.db: for each champion the tracked player has enough games on, a
set of SELF-RELATIVE VERDICT labels (dies more/less than your own norm,
kill-focused, team-involved, consistent / coinflip) plus the honest WR.
Computed entirely over the operator's own corpus (no global / Riot / Claude
dependency) - the Haiku-to-ZERO north star. The snapshot card polls this thin
HTTP surface.

Request shape:
  GET /api/playstyle-labels[?queue=450[,420]][&min_games=5]

  queue     : optional comma-separated queue-id filter, 1.._MAX_QUEUE_IDS ids,
              each 1-6 ASCII digits (bare int() also took a sign, "_"
              separators and non-ASCII digits, and an id past SQLite's 64-bit
              INTEGER raised OverflowError in the core - a 500). Absent or
              blank = every queue; a value that is present but holds no id
              (queue=,) is refused, it used to become an EMPTY filter served
              and cached as an empty corpus. Ids are de-duplicated and sorted,
              so 420,450 / 450,420 / 420,450,420 share one scan and one cache
              entry. Bad value -> 400.
  min_games : optional games floor for surfacing WR + labels, ASCII digits in
              1..1000. Bad value -> 400.

Every 400 names the parameter and the expected shape, never the caller's value
(RM-1255).

Response is compute_playstyle_labels(...)'s dict plus cached (bool) and
elapsed_ms (int). Value boundary: a non-finite float anywhere in the payload
reads as null (a bare NaN / Infinity token makes JSON.parse reject the WHOLE
body; an Infinity tracked_kp row reaches the kp means), and a label whose value
or baseline is non-finite is dropped, because its verdict was built on a
non-number. The body is serialised with allow_nan=False as the belt.

Cache: 5min in-process keyed by (queue tuple, min_games) - mirrors
routes_duration_winrate so a re-polling card does not turn the corpus scan
into a DB hot loop. The TTL and elapsed_ms run on time.monotonic (a wall-clock
step back must neither freeze an entry past its TTL nor report a negative
elapsed_ms), and the socket write happens AFTER _CACHE_LOCK is released (one
stalled client must not block every other request on this route).

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad queue / min_games token -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import playstyle_labels
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_clock = time.monotonic

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 64
_CACHE_EVICT = 16

# Riot queue ids are small non-negative integers (0 custom .. 2400 Mayhem);
# six digits is generous and keeps every id far inside SQLite's INTEGER.
_QUEUE_ID_RE = re.compile(r"[0-9]{1,6}")
_MAX_QUEUE_IDS = 16
_MIN_GAMES_RE = re.compile(r"[0-9]+")
_MIN_GAMES_MAX = 1000

_ERR_QUEUE = "queue must be comma-separated integers"
_ERR_QUEUE_COUNT = f"queue takes at most {_MAX_QUEUE_IDS} ids"
_ERR_MIN_INT = "min_games must be an integer"
_ERR_MIN_RANGE = f"min_games must be between 1 and {_MIN_GAMES_MAX}"


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_queue(raw: str):
    """(sorted unique id tuple | None, error | None). Blank = every queue."""
    if not raw:
        return (None, None)
    parts = [tok.strip() for tok in raw.split(",") if tok.strip()]
    if not parts:
        return (None, _ERR_QUEUE)
    if len(parts) > _MAX_QUEUE_IDS:
        return (None, _ERR_QUEUE_COUNT)
    ids = set()
    for tok in parts:
        if not _QUEUE_ID_RE.fullmatch(tok):
            return (None, _ERR_QUEUE)
        ids.add(int(tok))
    return (tuple(sorted(ids)), None)


def _parse_min_games(raw: str):
    if not raw:
        return (playstyle_labels.MIN_GAMES, None)
    if not _MIN_GAMES_RE.fullmatch(raw):
        return (None, _ERR_MIN_INT)
    digits = raw.lstrip("0")
    if len(digits) > len(str(_MIN_GAMES_MAX)):
        return (None, _ERR_MIN_RANGE)
    val = int(digits or "0")
    if not 1 <= val <= _MIN_GAMES_MAX:
        return (None, _ERR_MIN_RANGE)
    return (val, None)


def _finite(value) -> bool:
    return not (isinstance(value, float) and not math.isfinite(value))


def _scrub(value):
    """A copy of value with every non-finite float replaced by None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _clean_payload(payload: dict) -> dict:
    """Drop labels built on a non-finite value / baseline, then null every
    remaining non-finite float. Shapes other than the documented ones pass
    through untouched (the scrub still applies)."""
    out = dict(payload)
    champions = out.get("champions")
    if isinstance(champions, list):
        kept = []
        for champ in champions:
            labels = champ.get("labels") if isinstance(champ, dict) else None
            if isinstance(labels, list):
                champ = dict(champ)
                champ["labels"] = [
                    lb for lb in labels
                    if not isinstance(lb, dict)
                    or (_finite(lb.get("value")) and _finite(lb.get("baseline")))
                ]
            kept.append(champ)
        out["champions"] = kept
    return _scrub(out)


def _elapsed_ms(t0: float) -> int:
    return max(0, int((_clock() - t0) * 1000))


def _body(payload: dict) -> bytes:
    return json.dumps(payload, allow_nan=False).encode("utf-8")


def _serve_playstyle_labels(h) -> None:
    t0 = _clock()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        queue_raw = (qs.get("queue") or [""])[0].strip()
        min_raw = (qs.get("min_games") or [""])[0].strip()

        queue_ids, err = _parse_queue(queue_raw)
        if err:
            h._send(400, _body({"ok": False, "error": err}), "application/json")
            return
        min_games, err = _parse_min_games(min_raw)
        if err:
            h._send(400, _body({"ok": False, "error": err}), "application/json")
            return

        key = (queue_ids, min_games)
        now = _clock()
        hit = None
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and 0.0 <= (now - cached[0]) < _CACHE_TTL_S:
                hit = dict(cached[1])
        if hit is not None:
            hit["cached"] = True
            hit["elapsed_ms"] = _elapsed_ms(t0)
            h._send(200, _body(hit), "application/json")
            return

        payload = _clean_payload(playstyle_labels.compute_playstyle_labels(
            min_games=min_games, queue_ids=queue_ids))
        payload.pop("cached", None)
        payload.pop("elapsed_ms", None)
        _cache_put(key, now, dict(payload))
        payload["cached"] = False
        payload["elapsed_ms"] = _elapsed_ms(t0)

        h._send(200, _body(payload), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/playstyle-labels: %s", exc)
        try:
            h._send(500, _body(
                {"ok": False, "error": "internal error - see logs"}),
                "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/playstyle-labels"), _serve_playstyle_labels),
]
