"""GET /api/draft-score - deterministic five-layer draft-quality score
(read-only).

Serves core.draft_score.compute_draft_score over the LOCAL rewind_history.db
participant corpus + owned DS/101qq primitives: one bounded 42-58 score for an
ally composition (optionally vs an enemy composition) fusing lane-matchup,
pairwise synergy, damage balance, early-late scaling coherence, and base WR,
with a HIGH/MED/LOW confidence tier. Computed entirely over owned data (no
global / Riot / Claude dependency) - the Haiku-to-ZERO north star. The
snapshot / champ-select card polls this thin HTTP surface.

The damage-balance layer is wired to a DS kit-mix damage-class resolver; the
scaling layer stays inert (no per-champ power-timing primitive yet - see the
core module docstring). Both are cheap + fail-soft.

Request shape:
  GET /api/draft-score?ally=64,22,1,2,3[&enemy=42,67,69,55,12][&queue=420,440]

  ally  : exactly 5 ally champion ids (Riot integer key), comma-separated.
  enemy : optional 5 enemy champion ids for the matchup layer.
  queue : optional comma-separated queue-id filter (default the SR ranked set).

Response is compute_draft_score(...)'s dict plus cached (bool) and elapsed_ms
(int).

Cache: 5min in-process keyed by (sorted ally, sorted enemy, queue tuple) -
mirrors routes_draft_elo so a re-polling card does not turn the corpus scan
into a DB hot loop.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad / wrong-length ids -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
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


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_ids(raw: str, expected):
    """Parse a comma-separated int list. expected=None allows any length
    (>=0); an int enforces exactly that many. Returns (ids|None, err|None)."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    ids = []
    for p in parts:
        try:
            ids.append(int(p))
        except ValueError:
            return (None, f"non-integer id {p!r}")
    if expected is not None and len(ids) != expected:
        return (None, f"expected {expected} ids, got {len(ids)}")
    return (ids, None)


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


def _serve_draft_score(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        ally_raw = (qs.get("ally") or [""])[0].strip()
        enemy_raw = (qs.get("enemy") or [""])[0].strip()
        queue_raw = (qs.get("queue") or [""])[0].strip()

        if not ally_raw:
            h._send(400, json.dumps({"ok": False, "error": "ally: 5 ids required"})
                    .encode("utf-8"), "application/json")
            return
        ally, err = _parse_ids(ally_raw, 5)
        if err:
            h._send(400, json.dumps({"ok": False, "error": f"ally: {err}"})
                    .encode("utf-8"), "application/json")
            return
        enemy = None
        if enemy_raw:
            enemy, err = _parse_ids(enemy_raw, 5)
            if err:
                h._send(400, json.dumps({"ok": False, "error": f"enemy: {err}"})
                        .encode("utf-8"), "application/json")
                return
        queue_ids = None
        if queue_raw:
            queue_ids, err = _parse_ids(queue_raw, None)
            if err:
                h._send(400, json.dumps({"ok": False, "error": f"queue: {err}"})
                        .encode("utf-8"), "application/json")
                return

        key = (tuple(sorted(ally)),
               tuple(sorted(enemy)) if enemy else None,
               tuple(queue_ids) if queue_ids else None)
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

        payload = draft_score.compute_draft_score(
            ally, enemy_ids=enemy, queue_ids=queue_ids,
            damage_class_resolver=_default_damage_resolver(),
            duo_synergy_lookup=_default_duo_lookup,
            champ_name_resolver=_default_name_resolver,
        )
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/draft-score: %s", exc)
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
    _KitDamageResolver._snapshot = None


GET_ROUTES = [
    (equals("/api/draft-score"), _serve_draft_score),
]
