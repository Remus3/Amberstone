"""DS build-suggestion stability, fix (a) - deterministic tie ordering.

PD -> Kraken instability (2026-07-06 spec): the rank sort key was a float
tuple with NO stable tiebreak, so two items with an EXACT-tie metric ordered by
whatever order the candidate dict happened to iterate - which varies across a
:8860 / process restart (dict iteration order). This flipped the top build
suggestion between byte-identical runs.

Fix: _rank_sort_key appends the item_id as a STABLE final tiebreak on every
branch, so exact ties order deterministically and cannot flip across a restart.
Non-tie ordering stays byte-identical (item_id is only ever consulted when the
metric tuple is exactly equal). The same ranker feeds champ-select AND the
in-game LIVE/META rows, so one fix cures both consumers.
"""
import dataclasses
import unittest

from agents.daemon_slayer.rank import RankedItem, _rank_sort_key


def _item(item_id: str, delta: float, eff: float = 0.0) -> RankedItem:
    return RankedItem(
        item_id=item_id,
        item_name=f"i{item_id}",
        gold=3000,
        delta_dps=delta,
        new_dps=delta,
        dps_per_1k_gold=eff,
        is_terminal=True,
        tags=(),
    )


_FLAGS = {"reweight": False, "sort_by": "delta", "mana_reweight": False}


class RankSortKeyTiebreakTests(unittest.TestCase):
    def test_exact_ties_order_independent_of_input_order(self):
        # Two items identical on every metric: the key must impose a TOTAL order
        # so the reverse-sort output is the same regardless of input order (the
        # old float-only key left ties to the stable-sort input order = the
        # cross-restart flip).
        a = _item("3033", 100.0, 5.0)
        b = _item("6694", 100.0, 5.0)
        key = lambda r: _rank_sort_key(r, **_FLAGS)  # noqa: E731
        from_ab = [r.item_id for r in sorted([a, b], key=key, reverse=True)]
        from_ba = [r.item_id for r in sorted([b, a], key=key, reverse=True)]
        self.assertEqual(from_ab, from_ba, "exact-tie order must not depend on input order")

    def test_tiebreak_never_disturbs_a_real_delta_winner(self):
        # A clear delta winner still wins even with a "smaller" item_id.
        hi = _item("1001", 200.0, 5.0)
        lo = _item("9999", 100.0, 5.0)
        key = lambda r: _rank_sort_key(r, **_FLAGS)  # noqa: E731
        ranked = [r.item_id for r in sorted([lo, hi], key=key, reverse=True)]
        self.assertEqual(ranked, ["1001", "9999"], "higher delta must win over item_id")

    def test_tiebreak_holds_across_all_four_metric_branches(self):
        a = dataclasses.replace(
            _item("3033", 100.0, 5.0), effective_score=50.0, mana_adjusted_score=50.0
        )
        b = dataclasses.replace(
            _item("6694", 100.0, 5.0), effective_score=50.0, mana_adjusted_score=50.0
        )
        branches = [
            {"reweight": True, "sort_by": "delta", "mana_reweight": False},
            {"reweight": False, "sort_by": "efficiency", "mana_reweight": False},
            {"reweight": False, "sort_by": "delta", "mana_reweight": True},
            {"reweight": False, "sort_by": "delta", "mana_reweight": False},
        ]
        for flags in branches:
            key = lambda r, f=flags: _rank_sort_key(r, **f)  # noqa: E731
            self.assertEqual(
                [r.item_id for r in sorted([a, b], key=key, reverse=True)],
                [r.item_id for r in sorted([b, a], key=key, reverse=True)],
                f"branch {flags} must break exact ties by item_id",
            )


if __name__ == "__main__":
    unittest.main()
