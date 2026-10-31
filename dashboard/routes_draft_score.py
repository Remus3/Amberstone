"""GET /api/draft-score - deterministic five-layer draft-quality score
(read-only).

Serves core.draft_score.compute_draft_score over the LOCAL rewind_history.db
participant corpus + owned DS/101qq primitives: one bounded 42-58 score for an
ally composition (optionally vs an enemy composition) fusing lane-matchup,
pairwise synergy, damage balance, early-late scaling coherence, and base WR,
with a HIGH/MED/LOW confidence tier. Computed entirely over owned data (no
global / Riot / Claude dependency) - the Haiku-to-ZERO north star. The
snapshot / champ-select card polls this thin HTTP surface.

The damage-balance layer is wired to a DS kit-mix damage-class resolver and
the scaling layer to a DS spike-curve power-timing resolver
(_SpikeScalingResolver, below). Both are cheap + fail-soft per champion.

Request shape:
  GET /api/draft-score?ally=64,22,1,2,3[&enemy=42,67,69,55,12][&queue=420,440]

  ally  : exactly 5 ally champion ids (Riot integer key), comma-separated.
  enemy : optional 5 enemy champion ids for the matchup layer.
  queue : optional comma-separated queue-id filter (default the SR ranked set).

Response is compute_draft_score(...)'s dict plus cached (bool) and elapsed_ms
(int).

Cache: 5min in-process (monotonic clock) keyed by (sorted ally, sorted enemy,
sorted queue set) - mirrors routes_draft_elo so a re-polling card does not turn
the corpus scan into a DB hot loop. A cached payload is copied per request and
echoes THAT request's ally / enemy / queue order; no response is written while
the cache lock is held.

Validation (the trust boundary - this module is the only gate between the
query string and the SQLite binds in core.draft_elo_db):
  - every id is 1-6 ASCII digits (int() alone accepted a sign, "_"
    separators and non-ASCII digits, and an over-long id reached SQLite as an
    OverflowError the scorer's sqlite3.Error catches miss, so every layer went
    inert and a fake neutral 50 was answered 200 and cached);
  - a champion id is >= 1. A repeated champion is legal within a team (One
    for All, queue 1020, sends five identical ids: the champ-select card
    classifies it as "sr") and across teams (blind pick allows a mirror);
  - queue is 1-16 distinct ids when given; a value with no id ("queue=,") is
    a 400, never a silent fall back to the default set;
  - each parameter may appear once.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad / wrong-length ids or a duplicate queue id -> 400 with a short clear
    error; a rejected token is clipped before it is echoed
  - any other exception -> 500 structured error; the traceback is logged, and
    a failed 500 send is logged instead of swallowed.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import draft_score
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256
_CACHE_EVICT = 64

# A Riot champion key or queue id: plain ASCII digits, bounded so it always
# fits a SQLite INTEGER bind. re's [0-9] is ASCII-only for str patterns.
_ID_RE = re.compile(r"[0-9]{1,6}")
_TEAM_SIZE = 5
_MAX_QUEUE_IDS = 16
_ERR_TOKEN_MAX = 24
_PARAMS = ("ally", "enemy", "queue")


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _clip(token: str) -> str:
    """Bound a rejected token before it is echoed in an error body."""
    if len(token) > _ERR_TOKEN_MAX:
        token = token[:_ERR_TOKEN_MAX] + "..."
    return repr(token)


def _parse_ids(raw: str, expected, *, min_value: int = 1, unique: bool = False):
    """Parse a comma-separated id list, in the caller's order. Blank parts
    are skipped. expected=None allows 1.._MAX_QUEUE_IDS ids; an int enforces
    exactly that many. Every id is 1-6 ASCII digits and >= min_value;
    unique=True also refuses a repeated id. Returns (ids|None, err|None)."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if expected is None:
        if not parts or len(parts) > _MAX_QUEUE_IDS:
            return (None, f"expected 1-{_MAX_QUEUE_IDS} ids, got {len(parts)}")
    elif len(parts) != expected:
        return (None, f"expected {expected} ids, got {len(parts)}")
    ids: list[int] = []
    for p in parts:
        if not _ID_RE.fullmatch(p):
            return (None, f"invalid id {_clip(p)}")
        value = int(p)
        if value < min_value:
            return (None, f"invalid id {value}")
        if unique and value in ids:
            return (None, f"duplicate id {value}")
        ids.append(value)
    return (ids, None)


def _send_json(h, status: int, payload: dict) -> None:
    h._send(status, json.dumps(payload).encode("utf-8"), "application/json")


def _bad_request(h, error: str) -> None:
    _send_json(h, 400, {"ok": False, "error": error})


def _default_damage_resolver():
    """DS kit-mix damage-class resolver: champ_id -> physical|magical|mixed|None.

    Classifies from the champion's kit-only damage mix (no items) via
    core.damage_mix. Lazily loads + memoizes the DS snapshot; fail-soft to
    None per-champ so a missing snapshot leaves the damage layer inert rather
    than raising."""
    return _KitDamageResolver()


class _KitDamageResolver:
    _snapshot = None
    _lock = threading.Lock()

    def _snap(self):
        with self._lock:
            if _KitDamageResolver._snapshot is None:
                from agents.daemon_slayer.data_loader import DataSnapshot
                _KitDamageResolver._snapshot = DataSnapshot.load()
            return _KitDamageResolver._snapshot

    def __call__(self, champ_id):
        try:
            from core.damage_mix import compute_damage_mix
            mix, _ = compute_damage_mix(self._snap(), champ_id, [], level=11)
            phys = mix.physical_dps + mix.on_hit_dps
            mag = mix.magical_dps
            tot = phys + mag
            if tot <= 0:
                return None
            fp = phys / tot
            if fp >= 0.65:
                return "physical"
            if fp <= 0.35:
                return "magical"
            return "mixed"
        except Exception:  # noqa: BLE001 - kit resolution is best-effort
            return None


def _default_duo_lookup(name_a, name_b):
    """101qq duo-synergy rate for a (bot, sup) pair, or None (fail-soft)."""
    try:
        from core.smoothed_rates_101qq import pair_synergy
        rec = pair_synergy(name_a, name_b)
        return rec.doublewinrate if rec is not None else None
    except Exception:  # noqa: BLE001
        return None


def _default_name_resolver(champ_id):
    try:
        from core.archetype_picks import champion_name_by_key
        return champion_name_by_key(champ_id) or None
    except Exception:  # noqa: BLE001
        return None


# Power-spike threshold: the fraction of a champ's own end-game potential at
# which it is judged "online". Mirrors routes_spike_curve._PEAK_THRESHOLD so
# the draft-score scaling timing and the spike-curve peak marker key off the
# SAME crossing (kept as a local constant so the pure helper below imports
# without pulling in the DS engine).
_SCALING_PEAK_THRESHOLD = 0.70


def _peak_timing(curve, threshold=_SCALING_PEAK_THRESHOLD):
    """Per-champ power-timing (0=early .. 1=late) as a fraction of the curve's
    timeline: the FIRST index crossing ``threshold`` of the curve's own max,
    divided by the last index. This is the spike-curve "comes online" minute,
    normalized - a carry that crosses 70% at minute ~25 reads ~0.6; a tank
    that only crosses at ~38 reads ~0.95.

    Returns None on a degenerate curve (empty / all-zero) so the scaling layer
    stays inert rather than crediting a champ with no computable spike.
    """
    if not curve:
        return None
    vals = [float(v) for v in curve]
    mx = max(vals)
    if mx <= 0.0:
        return None
    thr = mx * threshold
    n = len(vals)
    for i, v in enumerate(vals):
        if v >= thr:
            return (i / (n - 1)) if n > 1 else 0.0
    return 1.0


class _SpikeScalingResolver:
    """DS spike-derived per-champ power-timing resolver (0=early .. 1=late)
    for the draft-score scaling layer. Reuses routes_spike_curve's cached
    per-champ power curve (fraction of end-game potential over minutes 0..40)
    and reports the normalized 70%-crossing minute. Fail-soft to None per
    champ so a missing slug / snapshot leaves that champ out of the coherence
    blend rather than raising."""

    def __call__(self, champ_id):
        try:
            from dashboard.routes_spike_curve import (
                _build_champ_curve, _load_id_to_slug, _resolve_archetype,
            )
            slug = _load_id_to_slug().get(int(champ_id))
            if not slug:
                return None
            archetype = _resolve_archetype(slug)
            curve = _build_champ_curve(slug, archetype, "SR")
            return _peak_timing(curve)
        except Exception:  # noqa: BLE001 - scaling timing is best-effort
            return None


def _default_scaling_resolver():
    return _SpikeScalingResolver()


def _serve_draft_score(h) -> None:
    t0 = time.monotonic()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        raw = {}
        for name in _PARAMS:
            values = qs.get(name) or [""]
            if len(values) > 1:
                _bad_request(h, f"{name}: given more than once")
                return
            raw[name] = values[0].strip()

        if not raw["ally"]:
            _bad_request(h, "ally: 5 ids required")
            return
        ally, err = _parse_ids(raw["ally"], _TEAM_SIZE)
        if err:
            _bad_request(h, f"ally: {err}")
            return
        enemy = None
        if raw["enemy"]:
            enemy, err = _parse_ids(raw["enemy"], _TEAM_SIZE)
            if err:
                _bad_request(h, f"enemy: {err}")
                return
        queue_ids = None
        if raw["queue"]:
            queue_ids, err = _parse_ids(raw["queue"], None, min_value=0,
                                        unique=True)
            if err:
                _bad_request(h, f"queue: {err}")
                return

        key = (tuple(sorted(ally)),
               tuple(sorted(enemy)) if enemy else None,
               tuple(sorted(queue_ids)) if queue_ids else None)
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached is not None and (now - cached[0]) < _CACHE_TTL_S:
            _send_json(h, 200, _respond(cached[1], ally, enemy, queue_ids,
                                        cached=True, t0=t0))
            return

        stored = dict(draft_score.compute_draft_score(
            ally, enemy_ids=enemy, queue_ids=queue_ids,
            damage_class_resolver=_default_damage_resolver(),
            duo_synergy_lookup=_default_duo_lookup,
            champ_name_resolver=_default_name_resolver,
            scaling_resolver=_default_scaling_resolver(),
        ))
        stored.pop("cached", None)
        stored.pop("elapsed_ms", None)
        if stored.get("ok") is True:
            _cache_put(key, now, stored)
        _send_json(h, 200, _respond(stored, ally, enemy, queue_ids,
                                    cached=False, t0=t0))
    except Exception:  # noqa: BLE001 - route boundary: never leak, always log
        log.exception("api/draft-score: unexpected failure")
        try:
            _send_json(h, 500, {"ok": False, "error": "internal error - see logs"})
        except Exception as send_exc:  # noqa: BLE001 - the client may be gone
            log.warning("api/draft-score: failed to send the 500: %s",
                        type(send_exc).__name__)


def _respond(stored: dict, ally, enemy, queue_ids, *, cached: bool,
             t0: float) -> dict:
    """A per-request copy of a stored payload that echoes THIS request's ids
    in its own order; the stored dict is never mutated."""
    payload = dict(stored)
    payload["ally"] = list(ally)
    payload["enemy"] = list(enemy) if enemy else None
    payload["queue_ids"] = list(queue_ids) if queue_ids else None
    payload["cached"] = cached
    payload["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return payload


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()
    _KitDamageResolver._snapshot = None


GET_ROUTES = [
    (equals("/api/draft-score"), _serve_draft_score),
]
