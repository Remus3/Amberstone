"""core.build_planner.replan - owned-aware re-plan loop + sell/swap + hysteresis (WP-C4).

Sits ABOVE the WP-C2 planner (core/build_planner/planner.py). Given the live
owned-item set, the seed boundary, the game clock, and an optional enemy threat
profile, it re-plans the remaining build each tick WITHOUT whiplash:

  * owned ids are a FIXED prefix - never re-planned, never in plan_tail.
  * STICKINESS (next-item hysteresis) compares single-item ``score_build([id])``
    totals, NOT the collapsing beam map. At depth >= 2 the beam prunes + dedupes
    every survivor down to the higher-ordering set, so a close incumbent is
    ABSENT from the beam - a beam-map gate would flip every tick. The single-item
    totals are stable + monotone, so a challenger inside the stickiness margin
    keeps the incumbent (no whiplash); a big-swing challenger flips.
  * component-defer drops a planned id whose effect is already owned (the id is a
    transitive ``from``-component of a finished owned item) from the next-item
    choice while keeping it in plan_tail for display.
  * sell / swap actions are gated (surplus, rate-limit, just-bought lock) and the
    free trinket upgrade bypasses every gate.
  * the Schmitt-trigger counter-build pivot is a banded hysteresis (low < high
    enforced, inclusive boundaries, no flicker inside the band, denom guarded).

Master plan: docs/OVERLAY_BUILD_MASTER_PLAN.md WP-C4 (lines 202-212).

PURITY boundary (mirrors situational.py + planner.py):

  * imports ONLY stdlib + core.build_planner.{planner,scoring,situational}; reads
    data/meta/ddragon_items.json LAZILY once for the recipe(``from``)/boots graph.
    NEVER ``import agents.daemon_slayer...`` - the split-brain guard
    (tests/test_planner_beam_search.py StructuralGuardTests) ast-scans this file.
  * NO unique-passive family literal anywhere (the no-double rule is inherited via
    the planner) - the guard greps the 7 banned literals in this source.
  * ALL tick state is in-memory. The only disk write is the OPT-IN
    ``end_match(path=...)`` save via atomic ``tmp.write_text(...); tmp.replace``.
  * the time source is the game clock ``clock_s`` passed to ``tick`` - no wall-clock.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.build_planner.planner import BuildPlan, plan_build
from core.build_planner.scoring import score_build, stage_for
from core.build_planner.situational import classify_item

# --------------------------------------------------------------------------- #
# Lazy recipe / boots catalog - the same ddragon_items.json situational.py
# reads, parsed ONCE for the ``from``-closure + 'Boots' tag graph.
# --------------------------------------------------------------------------- #
_ITEMS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "meta" / "ddragon_items.json"
_RECIPE: dict | None = None  # id_str -> {"from": tuple[str, ...], "tags": frozenset}

# Base-boots id - the from-closure fallback for finished boots that still chain
# back to it ('Boots' tag is the primary signal; this covers any tag drift).
_BASE_BOOTS_ID = "1001"

# Stage ordinal for the gate comparisons (early < mid < late).
_STAGE_ORDER = {"early": 0, "mid": 1, "late": 2}

# Trinket ids (data/meta/ddragon_items.json: 3340 Stealth Ward, 3363 Farsight
# Alteration). The free Stealth -> Farsight upgrade at mid+.
_STEALTH_WARD_ID = "3340"
_FARSIGHT_ID = "3363"


def _load_recipe() -> dict:
    """Read ddragon_items.json ONCE -> {id_str: {"from", "tags"}}.

    Any load failure degrades to an empty dict so ``component_ids_of`` returns an
    empty closure and ``is_boots`` falls back to the tag-only check (both safe).
    """
    global _RECIPE
    if _RECIPE is not None:
        return _RECIPE
    out: dict = {}
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        for item_id, entry in data.items():
            comps = entry.get("from") or ()
            out[str(item_id)] = {
                "from": tuple(str(c) for c in comps),
                "tags": frozenset(entry.get("tags") or ()),
            }
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 - any parse failure -> empty recipe graph
        pass
    _RECIPE = out
    return out


def _stage_order(stage: str) -> int:
    return _STAGE_ORDER.get(str(stage), 1)


# --------------------------------------------------------------------------- #
# Pure recipe helpers (lazy catalog read).
# --------------------------------------------------------------------------- #
def component_ids_of(owned_ids) -> frozenset:
    """Transitive ``from``-closure of every owned id -> frozenset of component ids.

    BFS/worklist over each item's ``from`` list, visited-set dedupe, terminating
    on a None/missing recipe. Multi-level: 3036 -> {3035, 6670, 1036, ...}; the
    3035.from == ['1036', '1036'] duplicate component is deduped by the visited
    set. The owned ids THEMSELVES are not in the result (only their components).
    """
    recipe = _load_recipe()
    owned = [str(i) for i in (owned_ids or ()) if str(i).strip()]
    out: set[str] = set()
    work: deque[str] = deque(owned)
    seen: set[str] = set(owned)
    while work:
        cur = work.popleft()
        for comp in recipe.get(cur, {}).get("from", ()):  # () when missing/None
            if comp not in seen:
                seen.add(comp)
                out.add(comp)
                work.append(comp)
    return frozenset(out)


def is_boots(item_id) -> bool:
    """True if the item carries the 'Boots' tag OR its from-closure reaches 1001.

    Dual-path so both base boots (1001, 'Boots' tag) and a finished boots
    (Plated Steelcaps 3047, 'Boots' tag + from-includes-1001) classify True while
    a non-boots damage item (Lord Dominik's 3036) classifies False.
    """
    iid = str(item_id)
    recipe = _load_recipe()
    entry = recipe.get(iid)
    if entry is not None and "Boots" in entry["tags"]:
        return True
    if iid == _BASE_BOOTS_ID:
        return True
    return _BASE_BOOTS_ID in component_ids_of([iid])


# --------------------------------------------------------------------------- #
# Pure hysteresis primitive - test directly.
# --------------------------------------------------------------------------- #
def schmitt(prev_on: bool, value: float, *, high: float, low: float) -> bool:
    """Schmitt-trigger band: prev_on stays on while value >= low; else turns on
    only when value >= high. Boundaries are INCLUSIVE (>=): value == high from
    off turns ON; value == low while on STAYS on. ``low < high`` is enforced by
    the ReplanConfig band-invariant guard (this primitive trusts the caller).
    """
    return (value >= low) if prev_on else (value >= high)


# --------------------------------------------------------------------------- #
# Config + result dataclasses (LOCKED surface).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReplanConfig:
    stickiness_margin: float = 1.10       # challenger must beat incumbent single-item total by > this
    just_bought_lock_s: float = 30.0      # no sell within this many game-seconds of a detected purchase
    schmitt_add: float = 1.20             # pivot turns ON only when pressure >= this (high threshold)
    schmitt_drop: float = 0.90            # pivot stays ON until pressure < this (low threshold)
    sell_min_surplus_gold: int = 0        # generic sell needs surplus_gold >= this
    boots_sell_min_surplus_gold: int = 1000  # boots-sell needs at least this surplus
    boots_sell_min_items: int = 6         # boots-sell only at full inventory
    trinket_upgrade_min_stage: str = "mid"   # free Stealth -> Farsight upgrade gated to mid+

    def __post_init__(self):
        # Band-invariant guard: schmitt_drop < schmitt_add must hold or the
        # hysteresis degenerates into latch-everything / latch-nothing.
        if self.schmitt_drop >= self.schmitt_add:
            raise ValueError("schmitt_drop must be < schmitt_add")


@dataclass(frozen=True)
class SwapAction:
    kind: str            # "sell_boots" | "upgrade_trinket" | "swap" | "defer"
    item_id: str         # the owned item acted on (or the deferred planned id)
    reason: str
    swap_to: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "item_id": self.item_id,
            "reason": self.reason,
            "swap_to": self.swap_to,
        }


@dataclass
class ReplanResult:
    champion: str
    next_item_id: Optional[str]          # None when there is no non-deferred tail id
    next_item_name: str                  # "" when next_item_id is None
    owned_prefix: tuple                   # owned ids verbatim - the FIXED prefix
    plan_tail: tuple                      # planned remaining ids (excludes owned) - FULL for display
    actions: tuple                        # sell/swap/upgrade suggestions emitted THIS tick (gated)
    deferred: tuple                       # component-deferred planned ids (effect already owned)
    sticky: bool                          # True when hysteresis suppressed a next-item flip
    pivot_active: bool                    # current Schmitt-trigger counter-build pivot state
    stage: str
    notes: tuple
    plan: BuildPlan                       # underlying beam result (breakdown passthrough)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "next_item_id": self.next_item_id,
            "next_item_name": self.next_item_name,
            "owned_prefix": list(self.owned_prefix),
            "plan_tail": list(self.plan_tail),
            "actions": [a.to_dict() for a in self.actions],
            "deferred": list(self.deferred),
            "sticky": self.sticky,
            "pivot_active": self.pivot_active,
            "stage": self.stage,
            "notes": list(self.notes),
            "plan": self.plan.to_dict(),
        }


# --------------------------------------------------------------------------- #
# ReplanLoop - the stateful tick driver.
# --------------------------------------------------------------------------- #
class ReplanLoop:
    """Owned-aware re-plan loop with stickiness + Schmitt pivot + gated sells.

    All state lives on the instance and is in-memory. ``tick`` writes NOTHING to
    disk; only the opt-in ``end_match(path=...)`` save touches the filesystem.
    """

    def __init__(self, *, config: Optional[ReplanConfig] = None):
        self.config = config or ReplanConfig()
        self._prev_owned = None           # sentinel - first-ever tick = no phantom purchase
        self._last_purchase_clock_s = None
        self._last_stage = None
        self._sells_this_stage = 0
        self._incumbent = None
        self._pivot_active = False
        self.action_log: list[dict] = []

    # ------------------------------------------------------------------- #
    # internal helpers
    # ------------------------------------------------------------------- #
    @staticmethod
    def _seed_pool_rows(seed: dict, owned_set: set) -> list[dict]:
        """Rebuild the planner's candidate ROW pool from the seed envelope.

        Mirrors planner._candidate_pool's id-set (ranked[] UNION order[], minus
        owned) but keeps the FULL ranked row dicts so a single-item score_build
        finds each candidate's delta_dps / gold / unique_passive_key. Used for
        the stickiness gate + the pivot pressure call.
        """
        rows: list[dict] = []
        seen: set[str] = set()
        for row in (seed.get("ranked") or []):
            iid = row.get("item_id")
            if iid is None:
                continue
            iid = str(iid)
            if iid in owned_set or iid in seen:
                continue
            seen.add(iid)
            rows.append(dict(row))
        for step in (seed.get("order") or []):
            iid = step.get("item_id")
            if iid is None:
                continue
            iid = str(iid)
            if iid in owned_set or iid in seen:
                continue
            seen.add(iid)
            rows.append({
                "item_id": iid,
                "item_name": step.get("item_name", ""),
                "delta_dps": float(step.get("delta", 0.0) or 0.0),
                "gold": int(step.get("gold", 0) or 0),
                "unique_passive_key": str(step.get("locked_family") or ""),
            })
        return rows

    def _single_total(self, item_id, champion, pool, *, clock_s, owned_count,
                      stage, enemy_profile=None):
        """Single-item ``score_build([id]).total`` - the stickiness/pivot scalar."""
        return score_build(
            [item_id], champion, pool,
            clock_s=clock_s, owned_count=owned_count, stage=stage,
            enemy_profile=enemy_profile,
        ).total

    def _pivot_pressure(self, pool, champion, enemy_profile, *, clock_s,
                        owned_count, stage):
        """Counter-build pressure for the Schmitt pivot (DIRECT score_build).

        plan_build cannot thread enemy_profile into its scorer (scoring.py:324
        forces the situational term to 0.0 when enemy_profile is None), so the
        pivot pressure is a direct score_build call that DOES pass enemy_profile.
        pressure = best counter total (resist/health/antiheal item) / best dps
        total. A non-positive denominator clamps pressure to 0.0 (penalty-
        dominated early builds give negative totals - the pivot must stay OFF).
        """
        if enemy_profile is None:
            return 0.0
        counter_best = None
        dps_best = None
        for row in pool:
            cid = str(row.get("item_id"))
            if not cid:
                continue
            props = classify_item(cid)
            relevant = (props.is_armor or props.is_magic_resist
                        or props.is_health or props.is_antiheal)
            if relevant:
                t = self._single_total(
                    cid, champion, pool, clock_s=clock_s,
                    owned_count=owned_count, stage=stage,
                    enemy_profile=enemy_profile)
                if counter_best is None or t > counter_best:
                    counter_best = t
            d = self._single_total(
                cid, champion, pool, clock_s=clock_s,
                owned_count=owned_count, stage=stage, enemy_profile=None)
            if dps_best is None or d > dps_best:
                dps_best = d
        if counter_best is None or dps_best is None or dps_best <= 0.0:
            return 0.0
        return max(0.0, counter_best / dps_best)

    def _gate_sell(self, action, *, stg, clock_s, surplus_gold, off_build):
        """Apply the SELL-class gates (just-bought lock + surplus + rate-limit).

        Returns the action if it passes all gates (and increments the per-stage
        sell counter), else None. ``off_build`` True == matchup-invalidated, which
        may bypass the just-bought lock at mid+.
        """
        cfg = self.config
        # rate-limit: at most 1 sell-class action per stage.
        if self._sells_this_stage >= 1:
            return None
        # just-bought lock.
        if self._last_purchase_clock_s is not None:
            within = (clock_s - self._last_purchase_clock_s) < cfg.just_bought_lock_s
            if within:
                allow = off_build and _stage_order(stg) >= _stage_order("mid")
                if not allow:
                    return None
        # surplus gate.
        if action.kind == "sell_boots":
            if surplus_gold < cfg.boots_sell_min_surplus_gold:
                return None
        else:
            if surplus_gold < cfg.sell_min_surplus_gold:
                return None
        self._sells_this_stage += 1
        return action

    # ------------------------------------------------------------------- #
    # the deterministic tick
    # ------------------------------------------------------------------- #
    def tick(self, *, champion, owned_item_ids, seed_fn,
             clock_s=0.0, enemy_profile=None, ally_state=None,
             surplus_gold=0, stage=None, mode="SR",
             beam_width=6, depth=6) -> ReplanResult:
        cfg = self.config
        notes: list[str] = []

        # 1. owned normalization + count-based purchase detection (trinket-safe).
        owned = [str(i) for i in (owned_item_ids or ()) if str(i).strip()]
        owned_prefix = tuple(owned)
        owned_set = set(owned)
        if self._prev_owned is not None and len(owned_set) > len(self._prev_owned):
            self._last_purchase_clock_s = clock_s
            notes.append("purchase detected")
        self._prev_owned = owned_set

        # 2. stage + per-stage sell-counter reset on a stage change.
        stg = stage or stage_for(clock_s, len(owned))
        if stg != self._last_stage:
            self._sells_this_stage = 0
            self._last_stage = stg

        # 3. re-plan the remaining build (owned excluded from the pool already).
        plan = plan_build(
            champion, seed_fn=seed_fn, owned_item_ids=owned, clock_s=clock_s,
            beam_width=beam_width, depth=depth, mode=mode)
        plan_tail = tuple(pi.item_id for pi in plan.items)

        # Rebuild the candidate row pool for the single-item gate + pivot.
        try:
            seed = seed_fn(str(champion), owned, mode=mode) or {}
        except Exception:  # noqa: BLE001 - boundary down -> empty pool
            seed = {}
        pool = self._seed_pool_rows(seed, owned_set)
        pool_ids = {str(r.get("item_id")) for r in pool}
        owned_count = len(owned)

        # 4. component-defer: drop planned ids whose effect is already owned.
        comp = component_ids_of(owned)
        deferred = tuple(i for i in plan_tail if i in comp)
        non_deferred_tail = [i for i in plan_tail if i not in comp]

        # 5. stickiness (next-item hysteresis via single-item totals).
        challenger = non_deferred_tail[0] if non_deferred_tail else None
        if challenger is None:
            # EMPTY / ALL-DEFERRED branch - nothing to flip to.
            next_id = None
            sticky = False
        else:
            incumbent = self._incumbent
            viable = (incumbent is not None and incumbent not in owned_set
                      and incumbent in pool_ids)
            if incumbent is None or incumbent == challenger or not viable:
                next_id = challenger
                sticky = False
            else:
                inc_t = self._single_total(
                    incumbent, champion, pool, clock_s=clock_s,
                    owned_count=owned_count, stage=stg)
                chal_t = self._single_total(
                    challenger, champion, pool, clock_s=clock_s,
                    owned_count=owned_count, stage=stg)
                if chal_t > inc_t * cfg.stickiness_margin:
                    next_id = challenger
                    sticky = False
                else:
                    next_id = incumbent
                    sticky = True
            self._incumbent = next_id

        # Resolve the planned name for next_id (from plan.items).
        next_name = ""
        if next_id is not None:
            for pi in plan.items:
                if pi.item_id == next_id:
                    next_name = pi.item_name
                    break

        # 6. Schmitt counter-build pivot (direct score_build pressure).
        pressure = self._pivot_pressure(
            pool, champion, enemy_profile, clock_s=clock_s,
            owned_count=owned_count, stage=stg)
        self._pivot_active = schmitt(
            self._pivot_active, pressure,
            high=cfg.schmitt_add, low=cfg.schmitt_drop)

        # 7. build candidate actions.
        actions: list[SwapAction] = []

        # 7a. trinket upgrade (FREE - bypasses every gate).
        if (_STEALTH_WARD_ID in owned_set
                and _stage_order(stg) >= _stage_order(cfg.trinket_upgrade_min_stage)):
            actions.append(SwapAction(
                kind="upgrade_trinket", item_id=_STEALTH_WARD_ID,
                swap_to=_FARSIGHT_ID, reason="free trinket upgrade"))

        # 7b + 7c. assemble SELL-class candidates, then gate (at most one fires).
        sell_candidates: list[tuple[SwapAction, bool]] = []

        # 7b. boots-sell (endgame slot reclaim).
        if len(owned) >= cfg.boots_sell_min_items:
            for oid in owned:
                if is_boots(oid):
                    sell_candidates.append((SwapAction(
                        kind="sell_boots", item_id=oid,
                        reason="endgame slot - sell boots for a damage item"),
                        False))
                    break  # one boots-sell candidate is enough.

        # 7c. true swap - matchup-invalidated owned item (enemy_profile required).
        # AT MOST ONE swap action per owned item even if it satisfies BOTH
        # predicates (antiheal-wasted + %armor-pen-wasted) - 3033 is both.
        if enemy_profile is not None:
            for oid in owned:
                props = classify_item(oid)
                wasted = False
                why = ""
                if props.is_antiheal and getattr(enemy_profile, "heal_sources", 0) == 0:
                    wasted = True
                    why = "antiheal wasted - enemy has no sustain"
                elif (props.is_percent_armor_pen
                      and getattr(enemy_profile, "kill_target_armor", 0.0) < 100.0):
                    wasted = True
                    why = "percent armor pen wasted - kill target is squishy"
                if wasted:
                    sell_candidates.append((SwapAction(
                        kind="swap", item_id=oid, reason=why), True))

        # 8. gate the SELL-class candidates (at most one passes the rate-limit).
        for cand, off_build in sell_candidates:
            gated = self._gate_sell(
                cand, stg=stg, clock_s=clock_s,
                surplus_gold=surplus_gold, off_build=off_build)
            if gated is not None:
                actions.append(gated)
                break  # the rate-limit allows only one this stage.

        return ReplanResult(
            champion=str(champion),
            next_item_id=next_id,
            next_item_name=next_name,
            owned_prefix=owned_prefix,
            plan_tail=plan_tail,
            actions=tuple(actions),
            deferred=deferred,
            sticky=sticky,
            pivot_active=self._pivot_active,
            stage=stg,
            notes=tuple(notes),
            plan=plan,
        )

    # ------------------------------------------------------------------- #
    # action log + opt-in atomic save
    # ------------------------------------------------------------------- #
    def accept(self, action: SwapAction) -> None:
        """Append ``action.to_dict()`` to the in-memory action log."""
        self.action_log.append(action.to_dict())

    def end_match(self, path=None) -> list:
        """Return the action log. Write ONLY when ``path`` is given (atomic).

        Atomic save: write a sibling ``.tmp`` then ``replace`` it onto the target
        so a mid-write reader never sees a partial file (repo hard rule).
        """
        if path is not None:
            target = Path(path)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(
                json.dumps(self.action_log, ensure_ascii=True, indent=2),
                encoding="utf-8")
            tmp.replace(target)
        return self.action_log
