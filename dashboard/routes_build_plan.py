# arch: build-plan panel backend (WP-C5) | section=dashboard | frozen=no
"""POST /api/build-plan - the DS -> adaptive-module -> Row1 data contract.

The SEAM that WP-C5 defines (master plan docs/OVERLAY_BUILD_MASTER_PLAN.md
lines 214-224). Composes the read-only DS routes (/api/ds-preview ranked[] +
target_stats + threat + defensive, and /api/build-order order[]) THROUGH the
core.build_planner module (ReplanLoop.tick) into a single ordered ``live[]``
the active_match Row1 panel renders directly.

SPLIT-BRAIN (routes_state.py:548-549, planner.py:12-15): this route reaches DS
ONLY over HTTP. It never imports ``agents.daemon_slayer``. The seed boundary is
a ``seed_fn(champion, owned_ids, mode=...)`` that calls the EXISTING ds-preview
+ build-order route handlers in-process - those handlers are themselves the
HTTP boundary (they POST to core.daemon_slayer_client :8893), so composing them
introduces no second engine. The factory is swappable (``_seed_fn_factory``)
so the contract test injects a fake without a live :8893 or a live game.

P1L4 (tests/test_target_state_caller_p1l4.py:178): live target-stats is routed
THROUGH the module (the seed envelope's ``target_stats``, computed by the
ds-preview handler), so THIS file contains no ``compute_target_stats_from_items``
needle - the guard's expected caller list stays {situational.py,
routes_state.py}.

Request shape (POST):
  {champion, mode?="SR", level?=11, items?=[], archetype?="", enemies?=[],
   knobs?={armor,mr,budget,fight_length}}

  champion : Live Client DISPLAY name or canonical id (ds-preview canonicalizes).
  items    : owned item-id strings (the FIXED prefix - never re-planned).
  enemies  : optional explicit enemy champion names (else live relay / none).
  knobs    : optional UI knob echo (armor/mr/budget/fight_length) - advisory.

Response contract (state in {owned, next, swap, partial, future}):
  {
    "ok":   true,
    "live": [ {item_id, item_name, state, order_idx, component_pips,
               swap_from?} , ... ],     # owned prefix THEN ordered planned tail
    "meta": [ {item_id, item_name, alt_index, n_alts} , ... ],  # alt-build set
    "knobs":     {armor, mr, budget, fight_length},
    "plan_meta": {stage, clock, scorer, target_stats}
  }

Fail-soft (NEVER a raise into the route):
  - blank champion          -> 200 ok=false reason=no_champion.
  - seedless boundary (DS down / no rows) -> 200 ok=true, empty live[]/meta[].
  - any unexpected error     -> 200 ok=false reason=error (logged).

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
import logging

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Default knob echo when the caller sends none - advisory display values only
# (the module reads target_stats from the seed, not these).
_DEFAULT_KNOBS = {"armor": 0, "mr": 0, "budget": 0, "fight_length": 0.0}


def _make_route_seed_fn(*, level: int, archetype: str, enemies: list,
                        target_overrides: dict):
    """Build the seed_fn HTTP boundary.

    Returns ``seed_fn(champion, owned_ids, mode=...) -> dict`` that calls the
    EXISTING /api/ds-preview + /api/build-order route handlers in-process and
    merges their envelopes into the {ranked[], order[], target_stats, scorer,
    threat, defensive} shape the planner consumes. Those handlers are the only
    DS touch-point and they POST to :8893 - no engine import here.

    A handler-level error (DS unreachable -> 503, or a 5xx) degrades that half
    to empty; if BOTH halves are empty the planner gets a seedless envelope and
    returns an empty plan (None-contract).
    """
    # Imported lazily + locally so the module import graph carries no DS symbol
    # and the contract test can monkeypatch _seed_fn_factory before any call.
    from dashboard.routes_state import (
        _serve_ds_preview_post,
        _serve_build_order_post,
    )

    class _Cap:
        """Captures a route handler's ``_send`` - the minimal handler surface
        the ds-preview / build-order handlers touch."""

        def __init__(self) -> None:
            self.status = 0
            self.body = b""

        def _send(self, status, body, content_type):  # noqa: D401 - handler shim
            self.status = status
            self.body = body

        def json(self) -> dict:
            try:
                return json.loads(self.body.decode()) if self.body else {}
            except Exception:  # noqa: BLE001 - malformed body -> empty
                return {}

    def _call(handler_fn, payload: dict) -> dict:
        cap = _Cap()
        try:
            handler_fn(cap, payload)
        except Exception as exc:  # noqa: BLE001 - boundary error -> empty half
            log.debug("build-plan seed half %s: %s", handler_fn.__name__, exc)
            return {}
        if cap.status != 200:
            return {}
        return cap.json()

    # Per-request memo: ReplanLoop.tick calls seed_fn multiple times (the
    # beam plan + the pool rebuild) and the handler calls it once more for
    # plan_meta. Without a memo each call is 2 DS POSTs (ds-preview +
    # build-order) - the memo collapses one request to exactly 2 POSTs.
    _memo: dict = {}

    def seed_fn(champion, owned_ids=None, mode="SR", **_kw) -> dict:
        owned = [str(i) for i in (owned_ids or ()) if str(i).strip()]
        memo_key = (str(champion), str(mode), tuple(owned))
        if memo_key in _memo:
            return _memo[memo_key]
        base = {
            "champion": str(champion),
            "mode": str(mode),
            "level": int(level),
            "items": owned,
        }
        if archetype:
            base["archetype"] = archetype
        if enemies:
            base["enemies"] = list(enemies)
        # target_overrides (explicit armor/mr/hp) let the caller-supplied knobs
        # drive the DS target without re-reading live items in this file.
        base.update(target_overrides)

        ds = _call(_serve_ds_preview_post, dict(base))
        bo = _call(_serve_build_order_post, dict(base))

        ranked = list(ds.get("ranked") or [])
        order = list(bo.get("order") or [])
        # target_stats comes from whichever half computed it (both share the
        # same _resolve_ds_target_stats result; prefer ds-preview's).
        target_stats = ds.get("target_stats") or bo.get("target_stats") or {}
        out = {
            "ok": bool(ranked or order),
            "ranked": ranked,
            "order": order,
            "scorer": str(ds.get("scorer") or "dps"),
            "target_stats": target_stats,
            "threat": ds.get("threat"),
            "defensive": ds.get("defensive") or [],
        }
        _memo[memo_key] = out
        return out

    return seed_fn


# Swappable factory seam - the contract test replaces this to inject a fake
# seed_fn without a live :8893 / live game. Production path builds the
# route-composing boundary above.
_seed_fn_factory = _make_route_seed_fn


def _coerce_knobs(raw) -> dict:
    """Echo the caller's UI knobs, coercing to the contract field types.

    Missing / malformed fields fall back to the default knob (advisory display
    only - they do not drive the engine math, which reads target_stats)."""
    out = dict(_DEFAULT_KNOBS)
    if isinstance(raw, dict):
        for k in ("armor", "mr", "budget"):
            try:
                out[k] = int(raw.get(k, out[k]) or 0)
            except (TypeError, ValueError):
                pass
        try:
            out["fight_length"] = float(raw.get("fight_length", out["fight_length"]) or 0.0)
        except (TypeError, ValueError):
            pass
    return out


def _target_overrides_from_knobs(knobs: dict) -> dict:
    """Map UI armor/mr knobs to the ds-preview explicit-override target fields.

    Only forwarded when a knob is positive - a 0 knob means "use the live /
    mode-curve target" (path 2/3 of _resolve_ds_target_stats), so we do NOT
    clobber it with an explicit zero (which would force the default-zero path).
    """
    out: dict = {}
    if knobs.get("armor", 0) > 0:
        out["target_armor"] = float(knobs["armor"])
    if knobs.get("mr", 0) > 0:
        out["target_mr"] = float(knobs["mr"])
    return out


def _build_live_rows(result, owned_prefix, deferred_set, comp_set,
                     swap_by_id) -> list:
    """Assemble the ordered ``live[]`` from a ReplanResult.

    owned prefix FIRST (state=owned), then the planned tail in plan order. A
    tail id is:
      * ``next``    - the replan loop's single next_item_id.
      * ``swap``    - a swap/sell action targets it (carries swap_from).
      * ``partial`` - component-deferred OR a component of it is already owned.
      * ``future``  - everything else further down the plan.
    ``order_idx`` is the absolute slot (owned occupy 0..k-1, the tail continues
    from k). ``component_pips`` = how many of this item's components are owned
    (a cheap "progress" hint; 0 when unknown).
    """
    rows: list = []
    idx = 0
    for oid in owned_prefix:
        rows.append({
            "item_id": oid,
            "item_name": "",  # owned names live in /api/state owned_items
            "state": "owned",
            "order_idx": idx,
            "component_pips": 0,
        })
        idx += 1

    names = {pi.item_id: pi.item_name for pi in result.plan.items}
    for tail_id in result.plan_tail:
        if tail_id in swap_by_id:
            state = "swap"
        elif tail_id == result.next_item_id:
            state = "next"
        elif tail_id in deferred_set or tail_id in comp_set:
            state = "partial"
        else:
            state = "future"
        row = {
            "item_id": tail_id,
            "item_name": names.get(tail_id, ""),
            "state": state,
            "order_idx": idx,
            "component_pips": 0,
        }
        if state == "swap":
            row["swap_from"] = swap_by_id[tail_id]
        rows.append(row)
        idx += 1
    return rows


def _build_meta_rows(result) -> list:
    """Alt-build set from the beam survivors.

    Each beam survivor is an alternative ordered build; we surface its FIRST
    planned item as the alt entry (the divergent next-purchase), tagged with
    its rank among the survivors. n_alts is the survivor count.
    """
    beam = getattr(result.plan, "beam", None) or []
    n_alts = len(beam)
    out: list = []
    for alt_index, cand in enumerate(beam):
        items = getattr(cand, "items", ()) or ()
        if not items:
            continue
        head = items[0]
        out.append({
            "item_id": head.item_id,
            "item_name": head.item_name,
            "alt_index": alt_index,
            "n_alts": n_alts,
        })
    return out


def _serve_build_plan(h, payload) -> None:
    """POST /api/build-plan handler - composes DS + module into the contract."""
    try:
        payload = payload if isinstance(payload, dict) else {}
        champion = str(payload.get("champion") or "").strip()
        knobs = _coerce_knobs(payload.get("knobs"))

        if not champion:
            h._send(200, json.dumps({
                "ok": False, "reason": "no_champion",
                "live": [], "meta": [], "knobs": knobs,
                "plan_meta": {"stage": "", "clock": 0.0, "scorer": "",
                              "target_stats": {}},
            }).encode("utf-8"), "application/json")
            return

        mode = str(payload.get("mode") or "SR").upper()
        try:
            level = max(1, min(18, int(payload.get("level") or 11)))
        except (TypeError, ValueError):
            level = 11
        owned = [str(i) for i in (payload.get("items") or []) if str(i).strip()]
        archetype = str(payload.get("archetype") or "").strip().lower()
        enemies = [str(x) for x in (payload.get("enemies") or []) if x]
        try:
            clock_s = float(payload.get("clock_s") or 0.0)
        except (TypeError, ValueError):
            clock_s = 0.0

        # Build the seed boundary (route-composing in prod; faked in tests).
        seed_fn = _seed_fn_factory(
            level=level, archetype=archetype, enemies=enemies,
            target_overrides=_target_overrides_from_knobs(knobs),
        )

        # Pull the enemy threat profile THROUGH the module (situational owns the
        # compute_target_stats_from_items needle, never this file). Best-effort:
        # any failure leaves enemy_profile None (the planner stays DPS-only).
        enemy_profile = _resolve_enemy_profile(enemies, level)

        from core.build_planner.replan import ItemOverrideStore, ReplanLoop

        # WP-D3: optional per-item operator overrides snapshot (mirrors the
        # client store web/js/lib/item_overrides.js). A truthy reset_overrides
        # forces an empty store (nothing to honor). Snapshot parsing is wrapped
        # so a malformed payload NEVER raises into the route.
        # NOTE: full cross-tick Defer-Once re-entry timing in the LIVE route is
        # OWED - this per-request loop only sinks a deferred item that tick (no
        # persisted owned-count baseline across requests); shift / keep / silence
        # are honored live now.
        store = None
        try:
            if not payload.get("reset_overrides"):
                ov_snap = payload.get("overrides")
                if isinstance(ov_snap, dict) and ov_snap:
                    store = ItemOverrideStore.from_snapshot(
                        ov_snap, owned_count=len(owned))
        except Exception:  # noqa: BLE001 - bad snapshot -> no overrides honored.
            store = None

        # One re-plan tick. ReplanLoop is per-request (in-memory; no cross-tick
        # hysteresis is meaningful for a single stateless HTTP call - the loop
        # still emits the correct first-tick next/defer/swap classification).
        loop = ReplanLoop()
        result = loop.tick(
            champion=champion, owned_item_ids=owned, seed_fn=seed_fn,
            clock_s=clock_s, enemy_profile=enemy_profile, mode=mode,
            overrides=store,
        )

        # Component-defer + swap maps for the state tagging.
        from core.build_planner.replan import component_ids_of
        comp_set = set(component_ids_of(owned))
        deferred_set = set(result.deferred)
        swap_by_id = {
            a.item_id: (a.swap_to or "")
            for a in result.actions
            if a.kind in ("swap", "sell_boots", "upgrade_trinket")
        }

        # Seed envelope again (cheap; the loop already called it) for scorer +
        # target_stats passthrough into plan_meta. Fail-soft to {}.
        try:
            seed = seed_fn(champion, owned, mode=mode) or {}
        except Exception:  # noqa: BLE001
            seed = {}

        live = _build_live_rows(
            result, result.owned_prefix, deferred_set, comp_set, swap_by_id)
        meta = _build_meta_rows(result)

        h._send(200, json.dumps({
            "ok": True,
            "live": live,
            "meta": meta,
            "knobs": knobs,
            "plan_meta": {
                "stage": result.stage,
                "clock": clock_s,
                "scorer": str(seed.get("scorer") or "dps"),
                "target_stats": seed.get("target_stats") or {},
            },
        }).encode("utf-8"), "application/json")

    except Exception as exc:  # noqa: BLE001 - NEVER raise into the route.
        log.warning("api/build-plan: %s", exc)
        try:
            h._send(200, json.dumps({
                "ok": False, "reason": "error",
                "live": [], "meta": [],
                "knobs": dict(_DEFAULT_KNOBS),
                "plan_meta": {"stage": "", "clock": 0.0, "scorer": "",
                              "target_stats": {}},
            }).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _resolve_enemy_profile(enemies: list, level: int):
    """Best-effort EnemyProfile via the module's IMPURE builder.

    Routes the live enemy compute THROUGH core.build_planner.situational
    (which owns the compute_target_stats_from_items call, per P1L4), so this
    route never holds the needle. Returns None on any failure (DPS-only plan).
    """
    if not enemies:
        return None
    try:
        from core.build_planner.situational import build_enemy_profile
        return build_enemy_profile(enemies, level=level)
    except Exception as exc:  # noqa: BLE001 - no profile -> DPS-only plan
        log.debug("build-plan enemy profile: %s", exc)
        return None


GET_ROUTES: list = []

POST_ROUTES = [
    (equals("/api/build-plan"), _serve_build_plan),
]
