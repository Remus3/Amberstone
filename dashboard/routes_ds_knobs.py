# arch: ds-engine-knobs control panel backend | section=dashboard | frozen=no
"""GET /api/ds-knobs - re-rank DS items for an operator-chosen fight model.

Competitor lift #1 (DEPTH spec docs/COMPETITOR_LIFT_2026-05-30.md "Lift 1",
lolsolved.gg engine-knobs UX). Thin dashboard wire over
``agents.daemon_slayer.rank.rank_items`` - the carry/DPS-scorer ranker that
already accepts ``target_armor`` / ``target_mr`` / ``budget`` as first-class
args. NO new compute, NO ENGINE math change, NO schema lift; every knob maps
to an EXISTING ranker parameter.

The operator overrides the enemy resist curve + gold cap and the build
re-ranks for that chosen fight model, instead of accepting the single
auto-resolved enemy curve that ``/api/ds-preview`` threads in. Where
``/api/ds-preview`` resolves target stats from LIVE enemy items (or a
mode/level curve) and routes per-archetype through the :8860 DS engine
server, THIS route runs the DPS ranker IN-PROCESS (no network) with the
operator-supplied knobs - the simplest path that exposes ``budget`` cleanly
(the :8860 dispatcher ``rank_for_primary_archetype`` does not take a budget
arg; see the "deviations" note in the ship report).

Exposes FOUR knobs (item 219 C follow-up shipped the 4th):
  target_armor : enemy armor the DPS rotation is mitigated against.
  target_mr    : enemy magic resist.
  budget       : build-cost cap (``rank_items(budget=...)`` -> candidate
                 gold filter). Omit / blank / <=0 means no cap.
  fight_length : fight duration in seconds. ``rank_items(fight_length=...)``
                 reweights candidates by total damage over a fight of that
                 length (burst + sustained); omit / blank / <=0 means no
                 reweight (pure delta-DPS ranking, byte-identical default).
The fight-length-reweight knob does NOT need an ENGINE_VERSION bump: it threads
an OPTIONAL arg into ``rank_items`` which reweights IN-PROCESS and is
byte-identical when omitted, and the :8860 DS dispatcher never serves
``rank_items`` (it uses ``rank_for_primary_archetype``, which has no
budget/fight_length args).

Request shape:
  GET /api/ds-knobs?champion=<champ>[&mode=SR][&items=<id,id>]
      [&target_armor=<f>][&target_mr=<f>][&budget=<int>][&fight_length=<f>]
      [&level=<1..18>]

  champion     : canonical DDragon id ("Caitlyn", "Jinx"). REQUIRED.
  mode         : SR / ARAM / ARENA / BRAWL (default SR). Drives the
                 per-mode item-legality filter + the auto resist curve.
  items        : comma-separated owned-item ids (the build-so-far). Blank
                 entries skipped; ranker scores the next slot on top.
  target_armor : optional float override. Omitted -> auto curve for mode.
  target_mr    : optional float override. Omitted -> auto curve for mode.
  budget       : optional int gold cap. Omitted / <=0 -> no cap.
  fight_length : optional float seconds. Omitted / blank / <=0 -> no reweight.
  level        : optional int 1..18 (default 11). Clamped.

Response shape:
  {
    "ok":         true,
    "champion":   "Caitlyn",
    "knobs": {
      "target_armor":   80.0,    # resolved value (override or auto)
      "target_mr":      52.0,
      "budget":         null,    # null when uncapped
      "fight_length":   null,    # null when no reweight; else seconds (float)
      "level":          11,
      "mode":           "SR",
      "armor_source":   "override" | "auto",
      "mr_source":      "override" | "auto"
    },
    "rows": [
      {"item_id":"3031","name":"Infinity Edge","delta_dps":210.4,
       "new_dps":612.1,"gold":3450,"scorer":"dps"},
      ...
    ],
    "count":      <int>,
    "elapsed_ms": <int>,
    "cached":     <bool>
  }

Failure modes:
  - 400  champion param literally missing OR present-but-blank.
  - 200  ok=false reason=no_rows when the ranker returns zero candidates
         (e.g. budget so low nothing qualifies, or a Yunara-in-ARAM
         zero-multiplier build).
  - 503  rank_items / DataSnapshot import or compute fails.

5-min TTL in-process cache keyed on (champion, mode, sorted items,
target_armor, target_mr, budget, fight_length, level). Mirrors
routes_cooldown_watch cache discipline.

Don't-redo:
  * This route uses ``rank_items`` (in-process DPS scorer) NOT
    ``rank_for_primary_archetype`` (:8860 HTTP, per-archetype, no budget
    arg). The DPS lens is the right one for "re-rank by fight model" - it
    is the surface that visibly shifts toward armor-pen weighting when the
    operator raises target_armor (proven in the test suite).
  * The fight-length-reweight knob is SHIPPED (item 219 C follow-up). It
    threads an OPTIONAL ``fight_length`` into ``rank_items`` which re-ranks by
    ``burst_delta + delta_dps * fight_length`` (burst from
    ``compute_burst_damage``). NO ENGINE bump: ``rank_items`` is byte-identical
    when ``fight_length`` is omitted and the :8860 dispatcher never serves it.
  * The DataSnapshot is loaded once + memoized at module scope (immutable
    per patch). A patch bump re-points current.txt; call _reset_caches()
    (test-only) or restart RC to pick up a new patch snapshot.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_cooldown_watch exactly.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

# DataSnapshot is immutable per patch - load once + reuse across requests.
_SNAPSHOT = None
_SNAPSHOT_LOCK = threading.Lock()

_DEFAULT_LEVEL = 11
_DEFAULT_TOP_N = 8


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


def _parse_float(raw: str):
    """Parse an optional float knob; None when blank / non-numeric / non-finite.

    nan/inf are rejected: nan poisons the cache key (nan != nan -> every
    request recomputes + inserts a fresh entry) and both serialize to
    non-standard JSON (NaN / Infinity) that browser JSON.parse rejects.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _parse_budget(raw: str):
    """Parse an optional gold cap; None when blank / non-numeric / <=0.

    OverflowError covers int(float('inf')) - pre-fix budget=inf escaped to
    the outer 500 handler.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        b = int(float(s))
    except (TypeError, ValueError, OverflowError):
        return None
    return b if b > 0 else None


def _parse_level(raw: str) -> int:
    """Parse the champion level; clamp [1, 18]; fall to default."""
    if not raw:
        return _DEFAULT_LEVEL
    try:
        lv = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LEVEL
    return max(1, min(18, lv))


def _cache_key(champion, mode, items, armor, mr, budget, level,
               fight_length=None) -> tuple:
    return (
        champion,
        mode,
        tuple(sorted(items)),
        armor,
        mr,
        budget,
        level,
        fight_length,
    )


def _resolve_knobs(mode, level, armor_override, mr_override) -> dict:
    """Resolve target_armor / target_mr from overrides or the auto curve.

    Omitted knobs fall back to the s170 mode/level enemy-stat curve
    (the same source /api/ds-preview uses for champ-select with no live
    game). Echoes which source won per knob.
    """
    from coach_integration.enemy_stats import compute_enemy_stats

    es = compute_enemy_stats(mode.lower(), level=float(level))
    armor = armor_override if armor_override is not None else float(es.armor)
    mr = mr_override if mr_override is not None else float(es.mr)
    return {
        "target_armor": round(float(armor), 1),
        "target_mr":    round(float(mr), 1),
        "armor_source": "override" if armor_override is not None else "auto",
        "mr_source":    "override" if mr_override is not None else "auto",
    }


def _compute(champion, mode, items, level, armor_override, mr_override,
             budget, fight_length=None) -> dict:
    """Build the response payload from scratch (no cache)."""
    from agents.daemon_slayer.rank import rank_items

    knobs = _resolve_knobs(mode, level, armor_override, mr_override)
    snapshot = _get_snapshot()
    result = rank_items(
        snapshot,
        champion_id=champion,
        level=level,
        current_item_ids=items,
        mode=mode,
        target_armor=knobs["target_armor"],
        target_mr=knobs["target_mr"],
        budget=budget,
        top_n=_DEFAULT_TOP_N,
        sort_by="delta",
        fight_length=fight_length,
    )
    rows = [
        {
            "item_id":         r.item_id,
            "name":            r.item_name,
            "delta_dps":       round(float(r.delta_dps), 1),
            "new_dps":         round(float(r.new_dps), 1),
            "gold":            int(r.gold),
            "scorer":          "dps",
            "effective_score": round(float(r.effective_score), 1),
        }
        for r in result.ranked
    ]
    if not rows:
        return {
            "ok":       False,
            "reason":   "no_rows",
            "champion": champion,
            "knobs":    {
                "target_armor": knobs["target_armor"],
                "target_mr":    knobs["target_mr"],
                "budget":       budget,
                "fight_length": fight_length,
                "level":        level,
                "mode":         mode,
                "armor_source": knobs["armor_source"],
                "mr_source":    knobs["mr_source"],
            },
            "rows":     [],
            "count":    0,
        }
    return {
        "ok":       True,
        "champion": champion,
        "knobs":    {
            "target_armor": knobs["target_armor"],
            "target_mr":    knobs["target_mr"],
            "budget":       budget,
            "fight_length": fight_length,
            "level":        level,
            "mode":         mode,
            "armor_source": knobs["armor_source"],
            "mr_source":    knobs["mr_source"],
        },
        "rows":     rows,
        "count":    len(rows),
    }


def _serve_ds_knobs(h) -> None:
    """GET /api/ds-knobs handler."""
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
        items = _parse_item_list((qs.get("items") or [""])[0].strip())
        armor_override = _parse_float((qs.get("target_armor") or [""])[0])
        mr_override = _parse_float((qs.get("target_mr") or [""])[0])
        budget = _parse_budget((qs.get("budget") or [""])[0])
        fight_length = _parse_float((qs.get("fight_length") or [""])[0])
        # Non-positive fight_length means "no reweight" -> normalize to None so
        # the cache key + echoed knob reflect the byte-identical default path.
        if fight_length is not None and fight_length <= 0.0:
            fight_length = None
        level = _parse_level((qs.get("level") or [""])[0].strip())

        # A full build has no open slot to rank a next item into - rank_items
        # raises ValueError for it. That is a normal late-game state, not a
        # server error, so return a graceful 200 instead of a 503 (the overlay
        # re-requests every ~4s and spammed the console once the build was
        # complete). Mirrors the no_rows ok=false shape.
        from agents.daemon_slayer.rank import DEFAULT_SLOT_COUNT
        if len(items) >= DEFAULT_SLOT_COUNT:
            h._send(200, json.dumps({
                "ok":         False,
                "reason":     "build_complete",
                "champion":   champion,
                "rows":       [],
                "count":      0,
                "cached":     False,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }).encode("utf-8"), "application/json")
            return

        key = _cache_key(
            champion, mode, items, armor_override, mr_override,
            budget, level, fight_length,
        )
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
            payload = _compute(champion, mode, items, level, armor_override,
                               mr_override, budget, fight_length)
        except ImportError as exc:
            log.warning("api/ds-knobs import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("api/ds-knobs compute: %s", exc)
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
        log.warning("api/ds-knobs: %s", exc)
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
    (equals("/api/ds-knobs"), _serve_ds_knobs),
]

POST_ROUTES: list = []
