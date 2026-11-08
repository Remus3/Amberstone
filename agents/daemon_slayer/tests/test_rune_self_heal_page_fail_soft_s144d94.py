"""S144-D-94: pin ``sum_rune_self_heal``'s whole-page fail-soft contract.

OFFLINE ONLY - no DS :8860 call, no network. The r142 FailSoftTests cover None,
[], a non-iterable int, None / garbage entries and bad pools. They never reach
the ``except Exception`` branch, and never hand in a rune page whose own
truthiness raises.

Defect pinned: the ``if not rune_ids`` guard sat OUTSIDE the ``try``, so a page
whose ``__bool__`` / ``__len__`` raises (an array-like with ambiguous truth, a
broken container) escaped as an exception, although the docstring promises
"Returns 0.0 on an empty / None / non-iterable argument ... or any lookup
failure". The guard now runs inside the ``try``. The rest pins existing
behaviour: a failure part-way through the page discards the WHOLE page (the
branch returns 0.0, not a partial total), and ``is_ranged`` is a no-op for
Second Wind (its longDesc has no ranged clause).
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._rune_self_heal import sum_rune_self_heal

_POOL = 3000.0


class _AmbiguousTruth:
    """Iterable whose truthiness raises, like a multi-element array."""

    def __bool__(self) -> bool:
        raise ValueError("truth value is ambiguous")

    def __iter__(self):
        return iter(["8444"])


class _BrokenLen:
    def __len__(self) -> int:
        raise RuntimeError("len unavailable")

    def __iter__(self):
        return iter(["8444"])


class _BadStr:
    def __str__(self) -> str:
        raise RuntimeError("no str")


def _raises_mid_page():
    yield "8444"
    raise RuntimeError("page source failed")


class PageTruthinessTests(unittest.TestCase):
    def test_raising_bool_returns_zero_not_raise(self):
        self.assertEqual(sum_rune_self_heal(_AmbiguousTruth(), max_health=_POOL), 0.0)

    def test_raising_len_returns_zero_not_raise(self):
        self.assertEqual(sum_rune_self_heal(_BrokenLen(), max_health=_POOL), 0.0)


class ExceptBranchTests(unittest.TestCase):
    def test_iterator_raising_mid_page_discards_the_whole_page(self):
        self.assertEqual(sum_rune_self_heal(_raises_mid_page(), max_health=_POOL), 0.0)

    def test_entry_whose_str_raises_discards_the_whole_page(self):
        self.assertEqual(
            sum_rune_self_heal([_BadStr(), "8444"], max_health=_POOL), 0.0
        )

    def test_generator_page_is_consumed_once_and_credited(self):
        once = sum_rune_self_heal(["8444"], max_health=_POOL)
        self.assertGreater(once, 0.0)
        self.assertAlmostEqual(
            sum_rune_self_heal((rid for rid in ["8444"]), max_health=_POOL), once
        )


class RangedTests(unittest.TestCase):
    def test_is_ranged_is_a_no_op_for_second_wind(self):
        self.assertEqual(
            sum_rune_self_heal(["8444"], max_health=_POOL, is_ranged=True),
            sum_rune_self_heal(["8444"], max_health=_POOL, is_ranged=False),
        )


if __name__ == "__main__":
    unittest.main()
