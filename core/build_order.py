# arch: contextual DS-backed build-ORDER planner | section=coaching | frozen=no
"""Contextual, match-specific item BUILD-ORDER planner (2026-05-17).

Closes the long-standing "always the same items, not match-specific"
complaint and enforces the hard rule: **never recommend two items that
share a unique passive** (Sheen/Spellblade family - Trinity Force +
Essence Reaver invalid together; also Lifeline and Immolate families).

Why the old path produced "always the same items"
-------------------------------------------------
``daemon_slayer_client.rank_for_primary_archetype`` (and the six
underlying ``rank_items_by_*`` scorers) does *greedy single-item
marginal* scoring: for a fixed ``item_ids`` it scores every candidate's
delta when added *alone*, sorts, returns a flat top-N. Coaches surface
that flat list (``coach_integration.archetype_dispatch.display_rows``).
There is no *sequenced* build anywhere - with a near-naked champion the
#1 item is deterministic per (champion, level), so every game shows the
same item. And because dedup only filters candidates colliding with an
*already-owned* item, the flat list can itself contain Trinity Force
**and** Essence Reaver (both ``unique_passive_key="spellblade"``) - a
forbidden double the moment the list is read as a build.

How this layer fixes both
-------------------------
Pure orchestration over the existing, tested engine - *no engine change*:

1. **Order = iterative forward selection.** Call the ranker once per
   slot, appending the chosen item to ``item_ids`` before the next call.
   Each slot is therefore scored against the *accumulated* build + the
   real enemy context (``target_armor/mr/max_hp/bonus_hp`` already
   plumbed from ``enemy_stats``), so the sequence genuinely adapts to
   the match instead of being six copies of "best single item".

2. **No-double rule is engine-authoritative.** ``rank_for_primary_
   archetype`` threads ``filter_shared_uniques=True`` (its default) to
   the DS server, whose ``collect_effects`` / ``current_unique_keys``
   dedup is the source of truth for the 3 unique-passive families
   (spellblade / lifeline / immolate, incl. Arena mirrors). Once slot 1
   is e.g. Trinity Force and it is in ``item_ids``, *every* later slot's
   ranking has ``spellblade`` locked → all other spellblade candidates
   are filtered server-side. Enforcing iteratively means we inherit that
   guarantee for the whole sequence without duplicating the family map
   here (which would invite the s173 anti-drift trap). A planner-side
   belt-and-suspenders skip of any ``shares_dead_unique`` row covers the
   off-default (``filter_shared_uniques=False``) caller too, and the
   ``unique_passive_safe`` invariant is then True by construction.

Engine-down / empty-champion semantics mirror ``dispatch_for_coach``:
return ``None`` so callers fall back to "unavailable" without writing
partial state.

Headless-testable: inject ``rank_fn`` (defaults to the real dispatcher)
so the planner can be exercised with a fake engine - no live DS server.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

logger = logging.getLogger("rc.core.build_order")

# Full build is 6 item slots in every mode RC coaches for.
DEFAULT_SLOTS = 6

# Scorer → human unit, mirrors archetype_dispatch._UNIT_SUFFIX. Kept as a
# tiny independent copy on purpose: this module must not import the coach
# layer (coaches import *this*), and the table is a stable 6-row constant,
# not drift-prone engine data.
_UNIT_SUFFIX: dict[str, str] = {
    "dps":     "dps",
    "ehp":     "ehp",
    "hybrid":  "%",
    "ability": "adps",
    "burst":   "burst",
    "hps":     "hps",
}


@dataclass(frozen=True)
class BuildStep:
    """One slot in the planned order (counts NEW picks only - owned items
    are excluded from the sequence)."""

    slot: int                 # 1-based position among the new picks
    item_id: str
    item_name: str
    delta: float              # scorer delta gained at THIS step vs the
                              # accumulated build immediately before it
    gold: int
    scorer: str               # dps|ehp|hybrid|ability|burst|hps
    unit: str                 # display unit for ``delta``
    # Family of a candidate the engine *excluded* at this slot because its
    # unique passive was already taken (engine-supplied via dead_unique_key
    # - populated opportunistically, never fabricated). Empty when nothing
    # was excluded for a family reason at this slot.
    excluded_family: str = ""
    excluded_example: str = ""

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "item_id": self.item_id,
            "item_name": self.item_name,
            "delta": round(self.delta, 2),
            "gold": self.gold,
            "scorer": self.scorer,
            "unit": self.unit,
            "excluded_family": self.excluded_family,
            "excluded_example": self.excluded_example,
        }


@dataclass
class BuildOrderResult:
    champion: str
    archetype: str
    scorer: str
    mode: str
    level: int
    owned: list[str]
    order: list[BuildStep] = field(default_factory=list)
    # The enemy context actually used - proves the order is match-specific
    # (flip these and the order changes; see tests).
    context: dict = field(default_factory=dict)
    # True iff every accepted pick had shares_dead_unique == False, i.e.
    # the hard no-double rule held for the whole sequence. By construction
    # under the default engine dedup; the flag makes it machine-checkable.
    unique_passive_safe: bool = True
    notes: list[str] = field(default_factory=list)

    def order_str(self) -> str:
        """Compact ``Item1 > Item2 > ...`` with per-step delta + gold -
        the form a coach prompt / dashboard pill wants."""
        if not self.order:
            return "none"
        return " > ".join(
            f"{s.item_name}(+{s.delta:.0f}{s.unit},{s.gold}g)"
            for s in self.order
        )

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "archetype": self.archetype,
            "scorer": self.scorer,
            "mode": self.mode,
            "level": self.level,
            "owned": list(self.owned),
            "order": [s.to_dict() for s in self.order],
            "order_str": self.order_str(),
            "context": dict(self.context),
            "unique_passive_safe": self.unique_passive_safe,
            "notes": list(self.notes),
        }


def _pick_top_safe(rows: list[dict]) -> tuple[Optional[dict], str, str]:
    """Return (chosen_row, excluded_family, excluded_example).

    Chosen row is the highest-ranked candidate that does NOT share a dead
    unique (rows are already engine-sorted). With the engine default
    (``filter_shared_uniques=True``) no row is flagged, so this is just
    ``rows[0]``; the skip path only matters if a caller turned the engine
    filter off. The first skipped-for-family row's engine-supplied
    ``dead_unique_key`` / ``item_name`` are surfaced as the slot's
    exclusion example (no family map fabricated here).
    """
    excluded_family = ""
    excluded_example = ""
    for r in rows:
        if r.get("shares_dead_unique"):
            if not excluded_family:
                excluded_family = str(r.get("dead_unique_key") or "")
                excluded_example = str(r.get("item_name") or "")
            continue
        return r, excluded_family, excluded_example
    return None, excluded_family, excluded_example


def plan_build_order(
    champion: str,
    archetype: str,
    *,
    level: int,
    owned_item_ids: Iterable[str],
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    slots: int = DEFAULT_SLOTS,
    augments: Optional[Iterable[str]] = None,
    sort_by: str = "delta",
    timeout: Optional[float] = None,
    rank_kwargs: Optional[dict] = None,
    rank_fn: Optional[Callable[..., Optional[dict]]] = None,
) -> Optional[BuildOrderResult]:
    """Plan a contextual, match-specific item ORDER for the remaining slots.

    ``owned_item_ids`` is the build so far (already-purchased). The order
    fills the remaining ``slots - len(owned)`` positions by greedy
    forward selection: each slot is the highest-delta legal item *given
    everything picked so far + the enemy context*, with the unique-passive
    no-double rule enforced by the engine's own dedup (see module docstring).

    Returns ``None`` when the engine is unreachable or ``champion`` is
    blank (mirrors ``dispatch_for_coach``). An engine that is up but has
    nothing left to recommend yields a result with a short ``order`` and
    an explanatory note - not ``None``.

    ``rank_fn`` defaults to
    ``core.daemon_slayer_client.rank_for_primary_archetype`` and is
    injectable for headless tests. ``rank_kwargs`` is splatted into every
    ranker call for scorer-specific extras (``enemy_ad_share`` /
    ``alpha`` / ``max_priority`` / ``combo_sequence`` / ``only_item_ids``
    / ...); the dispatcher silently ignores knobs irrelevant to the
    routed scorer.
    """
    if not champion or not str(champion).strip():
        return None

    if rank_fn is None:
        try:
            from core.daemon_slayer_client import rank_for_primary_archetype as rank_fn  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_order: cannot import rank_for_primary_archetype: %s", exc)
            return None

    arch = (archetype or "carry").strip().lower() or "carry"
    owned: list[str] = [str(i) for i in (owned_item_ids or ()) if str(i).strip()]
    extra: dict = dict(rank_kwargs or {})

    context = {
        "target_armor": float(target_armor),
        "target_mr": float(target_mr),
        "target_max_hp": float(target_max_hp),
        "target_bonus_hp": float(target_bonus_hp),
        "mode": str(mode),
    }
    result = BuildOrderResult(
        champion=str(champion),
        archetype=arch,
        scorer="",
        mode=str(mode),
        level=int(level),
        owned=list(owned),
        context=context,
    )

    remaining = int(slots) - len(owned)
    if remaining <= 0:
        result.notes.append(
            f"build already full ({len(owned)}/{slots}) - no order to plan"
        )
        return result

    accumulated: list[str] = list(owned)
    picked_ids: set[str] = set(owned)

    for slot_i in range(1, remaining + 1):
        call_kwargs = dict(
            level=int(level),
            item_ids=list(accumulated),
            mode=str(mode),
            target_armor=float(target_armor),
            target_mr=float(target_mr),
            target_max_hp=float(target_max_hp),
            target_bonus_hp=float(target_bonus_hp),
            sort_by=str(sort_by),
            # Hard rule lives here: the engine's source-of-truth dedup
            # excludes any candidate whose unique-passive family is
            # already in ``accumulated``. Iterating means it holds for
            # the whole sequence. Never flip this off in the planner.
            filter_shared_uniques=True,
        )
        if augments:
            call_kwargs["augments"] = list(augments)
        if timeout is not None:
            call_kwargs["timeout"] = float(timeout)
        call_kwargs.update(extra)
        # Caller-supplied rank_kwargs must never weaken the rule.
        call_kwargs["filter_shared_uniques"] = True

        try:
            out = rank_fn(champion, arch, **call_kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_order: rank_fn raised at slot %d: %s", slot_i, exc)
            out = None

        if out is None:
            if slot_i == 1:
                # Engine unreachable before any pick - same contract as
                # dispatch_for_coach: signal None so callers fall back.
                return None
            result.notes.append(
                f"engine stopped responding after slot {slot_i - 1}; "
                f"order truncated"
            )
            break

        scorer = str(out.get("scorer") or "dps")
        if not result.scorer:
            result.scorer = scorer
        rows = [r for r in (out.get("ranked") or []) if r.get("item_id")]
        # Defensive: the engine already skips owned ids, but never let a
        # duplicate slip into the sequence.
        rows = [r for r in rows if str(r.get("item_id")) not in picked_ids]
        if not rows:
            result.notes.append(
                f"no further legal items after slot {slot_i - 1} "
                f"(scorer={scorer}) - order complete at "
                f"{len(result.order)} new item(s)"
            )
            break

        chosen, excl_family, excl_example = _pick_top_safe(rows)
        if chosen is None:
            result.notes.append(
                f"slot {slot_i}: all candidates collide with a locked "
                f"unique passive - order complete"
            )
            break
        if chosen.get("shares_dead_unique"):
            # Should be impossible (filter on) - record + stop rather
            # than emit a rule-violating pick.
            result.unique_passive_safe = False
            result.notes.append(
                f"slot {slot_i}: engine returned only dead-unique rows "
                f"despite filter - aborting to honor no-double rule"
            )
            break

        item_id = str(chosen.get("item_id"))
        delta = float(chosen.get("delta", chosen.get("delta_dps", 0.0)) or 0.0)
        step = BuildStep(
            slot=slot_i,
            item_id=item_id,
            item_name=str(chosen.get("item_name") or item_id),
            delta=delta,
            gold=int(chosen.get("gold", 0) or 0),
            scorer=scorer,
            unit=_UNIT_SUFFIX.get(scorer, "delta"),
            excluded_family=excl_family,
            excluded_example=excl_example,
        )
        result.order.append(step)
        accumulated.append(item_id)
        picked_ids.add(item_id)

    if not result.scorer:
        result.scorer = "dps"
    if result.order:
        result.notes.append(
            f"planned {len(result.order)} item(s) by greedy forward "
            f"selection (scorer={result.scorer}, "
            f"context armor={context['target_armor']:.0f}/"
            f"mr={context['target_mr']:.0f}/"
            f"hp={context['target_max_hp']:.0f}); unique-passive no-double "
            f"{'held' if result.unique_passive_safe else 'VIOLATED'}"
        )
    return result
