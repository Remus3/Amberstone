# arch: ds relative-score bar backend | section=dashboard | frozen=no
"""GET /api/ds-relscore - relative-power bar over the DS DPS ranking.

Competitor lift #3 (DEPTH spec docs/COMPETITOR_LIFT_2026-05-30.md "Lift 3",
Aggregator P relative-score bars). Thin READ-ONLY dashboard wire over
``agents.daemon_slayer.rank.rank_items`` - the carry/DPS-scorer ranker. NO
new compute, NO ENGINE math change, NO schema lift; this route READS the
existing ranker and re-expresses each row's ``delta_dps`` as a percent of
the best row's delta (a relative-power bar, NOT a control surface).

This is the long-HELD competitor lift #3 surface: item 200 deleted the old
DS-top-picks render row, so the relative-score bar needed a NEW home. It
ships as its OWN champ-select panel - the same pattern the 4 item-219 lifts
used (each a NEW route + NEW panel). Unlike /api/ds-knobs (the operator-knob
sibling), this route takes NO operator overrides: it ALWAYS auto-resolves
the enemy resist curve so the bar reads "relative item power for the
auto-resolved fight model" with zero operator input.

Request shape:
  GET /api/ds-relscore?champion=<champ>[&mode=SR][&items=<id,id>][&level=11]

  champion : canonical DDragon id ("Caitlyn", "Jinx"). REQUIRED.
  mode     : SR / ARAM / ARENA / BRAWL (default SR). Drives the per-mode
             item-legality filter + the auto resist curve.
  items    : comma-separated owned-item ids (the build-so-far). Blank
             entries skipped; trinkets + consumables dropped (they hold no
             inventory slot); ranker scores the next slot on top.
  level    : optional int 1..18 (default 11). Clamped.

Response shape:
  {
    "ok":         true,
    "champion":   "Caitlyn",
    "target": {
      "armor": 80.0,    # auto-resolved (mode/level curve, never override)
      "mr":    52.0,
      "level": 11,
      "mode":  "SR"
    },
    "rows": [
      {"item_id":"3031","name":"Infinity Edge","delta_dps":210.4,
       "score_pct":100.0,"gold":3450},
      {"item_id":"3036","name":"Lord Dominik's","delta_dps":168.3,
       "score_pct":80.0,"gold":3000},
      ...
    ],
    "count":      <int>,
    "elapsed_ms": <int>,
    "cached":     <bool>
  }

  score_pct = round(delta_dps / top_delta_dps * 100, 1) where top_delta_dps
  is the MAX positive delta_dps among rows. Rows arrive sorted desc by
  delta (sort_by="delta"), so row 0 is the best and reads 100.0. When the
  top delta is <= 0 (degenerate; itemless build with no positive pick) all
  rows read 0.0.

Failure modes:
  - 400  champion param literally missing OR present-but-blank.
  - 200  ok=false reason=no_rows when the ranker returns zero candidates.
  - 200  ok=false reason=build_full when six inventory slots are occupied,
         so there is no next slot to rank. An expected terminal state, NOT
         an error - it is cached like any success (see Don't-redo below).
  - 503  rank_items / DataSnapshot import or compute fails.

5-min TTL in-process cache keyed on (champion, mode, sorted items, level).
Mirrors routes_ds_knobs cache discipline (minus the operator knobs).

Don't-redo:
  * This route is READ-ONLY - it takes NO target_armor / target_mr / budget
    override. The enemy resist curve is ALWAYS auto-resolved via
    compute_enemy_stats (the same source /api/ds-preview uses in
    champ-select with no live game). The operator-knob variant is the
    separate /api/ds-knobs route.
  * score_pct is a percent of the BEST row's delta_dps (relative power),
    NOT an absolute 0-100 score - row 0 is always 100.0 (or 0.0 when the
    top delta is non-positive).
  * A full six-slot inventory answers 200 / reason=build_full and is NOT
    routed through the 503 branch. It used to be: the engine precondition
    ValueError landed on the catch-all, which logs WARNING and never caches,
    and the browser discards a non-ok response, so a deterministic outcome
    recomputed and re-logged on every poll. Measured 2026-08-02: that single
    line was 765 of 823 WARNINGs (93.0 pct) in one day's log. Do NOT restore
    the 503, and do NOT add a negative cache instead - the terminal answer
    belongs in the normal success cache, whose key already carries the item
    list, so a sold item is a different key and cannot be served stale.
  * The catch-all 503 + WARNING is deliberately kept for GENUINE faults, and
    those are still uncached so recovery is immediate rather than pinned for
    the TTL. Do not widen the demotion to cover it.
  * Trinkets + consumables are dropped from ``items`` before the cache key is
    built (s156, core/daemon_slayer_resolver.py:144-151). Callers pass the raw
    Live-Client inventory, which lists them inline with shop items.
  * The DataSnapshot is loaded once + memoized at module scope (immutable
    per patch). A patch bump re-points current.txt; call _reset_caches()
    (test-only) or restart RC to pick up a new patch snapshot.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_ds_knobs / routes_cooldown_watch.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

# DataSnapshot is immutable per patch - load once + reuse across requests.
_SNAPSHOT = None
_SNAPSHOT_LOCK = threading.Lock()

_DEFAULT_LEVEL = 11
_DEFAULT_TOP_N = 12

# The DS engine ranks the NEXT of six inventory slots, so a build holding six
# of them has no slot left to score. Mirrors the engine-side precondition
# (agents/daemon_slayer/onhit_dps.py:434 and its per-scorer twins).
_INVENTORY_SLOTS = 6


def _get_snapshot():
    """Lazy-load + memoize the DS DataSnapshot (current.txt patch)."""
    global _SNAPSHOT
    with _SNAPSHOT_LOCK:
        if _SNAPSHOT is None:
            from agents.daemon_slayer.data_loader import DataSnapshot
            _SNAPSHOT = DataSnapshot.load()
        return _SNAPSHOT


def _parse_item_list(raw: str) -> list[str]:
    """Split a comma-separated item-id list, strip blanks."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _drop_non_inventory(items: list[str]) -> list[str]:
    """Drop trinkets + consumables, which occupy no inventory slot.

    The caller feeds the raw Live-Client inventory, which serializes the
    trinket and consumable rows inline with shop items (see
    dashboard/_liveclient.py owned_item_ids, which applies no filter). Left
    unfiltered they inflate the count past the six rankable slots, so a build
    of five items plus a ward trinket read as full and the panel went dark in
    the slot where last-item advice matters most. This is the s156 defect
    documented at core/daemon_slayer_resolver.py:144-151; reuse that canonical
    id set rather than forking a second copy of it.
    """
    from core.daemon_slayer_resolver import NON_INVENTORY_IDS

    return [i for i in items if i not in NON_INVENTORY_IDS]


def _parse_level(raw: str) -> int:
    """Parse the champion level; clamp [1, 18]; fall to default."""
    if not raw:
        return _DEFAULT_LEVEL
    try:
        lv = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LEVEL
    return max(1, min(18, lv))


def _cache_key(champion, mode, items, level) -> tuple:
    return (champion, mode, tuple(sorted(items)), level)


def _resolve_target(mode, level) -> dict:
    """Auto-resolve target_armor / target_mr from the mode/level curve.

    NO operator overrides - this is the read-only relative-power view, so
    the resist curve is always the s170 mode/level enemy-stat curve (the
    same source /api/ds-preview uses for champ-select with no live game).
    """
    from coach_integration.enemy_stats import compute_enemy_stats

    es = compute_enemy_stats(mode.lower(), level=float(level))
    return {
        "armor": round(float(es.armor), 1),
        "mr":    round(float(es.mr), 1),
        "level": level,
        "mode":  mode,
    }


def _compute(champion, mode, items, level) -> dict:
    """Build the response payload from scratch (no cache)."""
    from agents.daemon_slayer.rank import rank_items

    target = _resolve_target(mode, level)

    # A full inventory is an EXPECTED terminal answer, not an engine fault.
    # Answering it here keeps the ranker's precondition ValueError off the
    # error path, so it flows through the normal success cache below and the
    # 300 s TTL actually applies. Safe against a mid-TTL sell: the cache key
    # carries this same filtered item list, so a changed inventory is a
    # different key and this answer can never be served as live advice.
    if len(items) >= _INVENTORY_SLOTS:
        return {
            "ok":       False,
            "reason":   "build_full",
            "champion": champion,
            "target":   target,
            "rows":     [],
            "count":    0,
        }

    snapshot = _get_snapshot()
    result = rank_items(
        snapshot,
        champion_id=champion,
        level=level,
        current_item_ids=items,
        mode=mode,
        target_armor=target["armor"],
        target_mr=target["mr"],
        budget=None,
        top_n=_DEFAULT_TOP_N,
        sort_by="delta",
    )
    ranked = list(result.ranked)
    if not ranked:
        return {
            "ok":       False,
            "reason":   "no_rows",
            "champion": champion,
            "target":   target,
            "rows":     [],
            "count":    0,
        }

    # Relative bar: each row's delta as a percent of the BEST row's delta.
    # Rows arrive sorted desc by delta, so ranked[0] is the max. Guard a
    # non-positive top delta (degenerate itemless build) -> all rows 0.0.
    top_delta = float(ranked[0].delta_dps)
    rows = []
    for r in ranked:
        delta = round(float(r.delta_dps), 1)
        if top_delta > 0.0:
            score_pct = round(float(r.delta_dps) / top_delta * 100.0, 1)
        else:
            score_pct = 0.0
        rows.append({
            "item_id":   r.item_id,
            "name":      r.item_name,
            "delta_dps": delta,
            "score_pct": score_pct,
            "gold":      int(r.gold),
        })
    return {
        "ok":       True,
        "champion": champion,
        "target":   target,
        "rows":     rows,
        "count":    len(rows),
    }


def _serve_ds_relscore(h) -> None:
    """GET /api/ds-relscore handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        champion = (qs.get("champion") or [""])[0].strip()
        if not champion:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        mode = (qs.get("mode") or ["SR"])[0].strip().upper() or "SR"
        items = _drop_non_inventory(
            _parse_item_list((qs.get("items") or [""])[0].strip()))
        level = _parse_level((qs.get("level") or [""])[0].strip())

        key = _cache_key(champion, mode, items, level)
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
            payload = _compute(champion, mode, items, level)
        except ImportError as exc:
            log.warning("api/ds-relscore import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("api/ds-relscore compute: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        with _CACHE_LOCK:
            _CACHE[key] = (now, dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:  # noqa: BLE001
        log.warning("api/ds-relscore: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache + memoized snapshot."""
    global _SNAPSHOT
    with _CACHE_LOCK:
        _CACHE.clear()
    with _SNAPSHOT_LOCK:
        _SNAPSHOT = None


GET_ROUTES = [
    (equals("/api/ds-relscore"), _serve_ds_relscore),
]

POST_ROUTES: list = []
