# arch: DS item-legality adapter - builds the relax recommender HARD predicate | section=coaching | frozen=no
"""core.build_planner_legality - DS item legality as an injectable predicate.

Adapter for core/build_planner/relax.py (P2-10). The relax recommender must not
import the DS engine (build_planner split-brain guard), so it takes patch/mode
legality as an injected ``legal(candidate) -> bool``. This module builds that
predicate from the SINGLE source of item legality - the DS pool filter
``agents.daemon_slayer.rank._filter_candidates`` (purchasable, non-coachable /
Ornn-masterwork / SR- and ARAM-exclude denies, per-mode ``maps`` legality,
alias dedup) - so no legality rule is duplicated here.

The candidate contract: a single item ``{"item_id": "3031"}`` or a
combination ``{"item_ids": [...]}``; a combination is legal only when it is
non-empty and EVERY member is legal. Anything else is illegal.

Lives OUTSIDE core/build_planner/ on purpose: the package must reach DS only
through injected callables.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

from typing import Callable, Mapping

from agents.daemon_slayer.data_loader import canonical_mode
from agents.daemon_slayer.rank import _filter_candidates


def legal_item_ids(snapshot, mode: str, *,
                   champion_is_melee: bool = False) -> frozenset:
    """Every item id the DS pool filter admits for ``mode`` (components
    included, no budget, nothing owned)."""
    rows = _filter_candidates(
        snapshot, canonical_mode(mode), set(), None, True, None,
        champion_is_melee=champion_is_melee,
    )
    return frozenset(str(item_id) for item_id, _rec in rows)


def item_legality(snapshot, mode: str, *,
                  champion_is_melee: bool = False
                  ) -> Callable[[Mapping], bool]:
    """Return the relax HARD legality predicate for ``snapshot`` + ``mode``."""
    legal_ids = legal_item_ids(snapshot, mode,
                               champion_is_melee=champion_is_melee)

    def legal(candidate: Mapping) -> bool:
        if "item_ids" in candidate:
            ids = [str(i) for i in (candidate.get("item_ids") or ())]
        elif "item_id" in candidate:
            ids = [str(candidate["item_id"])]
        else:
            return False
        return bool(ids) and all(i in legal_ids for i in ids)

    return legal
