"""S144-D-102: ``sum_rune_hsp_pct`` honours its documented FAIL-SOFT contract.

OFFLINE ONLY - no DS :8860 call, no network. The r136 tests pin the Revitalize
0.05 magnitude, dedup and the None / empty / non-iterable cases.

Defect pinned (measured before the fix): the ``if not rune_ids`` emptiness
check ran OUTSIDE the ``try``, so a page whose truthiness raises (an
array-like with an ambiguous ``__bool__``) propagated its exception out of
``ehp.compute_ehp``'s ``apply_rune_hsp_amp`` seam instead of returning 0.0 -
the S144-D-94 / D-96 defect in this sibling.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._rune_hsp_amp import sum_rune_hsp_pct


class _RaisingTruthPage:
    def __bool__(self) -> bool:
        raise ValueError("truth value of a page is ambiguous")

    def __iter__(self):
        return iter(["8453"])


class FailSoftTests(unittest.TestCase):
    def test_raising_truthiness_reads_zero(self) -> None:
        self.assertEqual(sum_rune_hsp_pct(_RaisingTruthPage()), 0.0)

    def test_documented_fail_soft_cases_still_zero(self) -> None:
        for page in (None, [], (), 5):
            with self.subTest(page=page):
                self.assertEqual(sum_rune_hsp_pct(page), 0.0)

    def test_finite_parity(self) -> None:
        self.assertEqual(sum_rune_hsp_pct(["8453"]), 0.05)
        self.assertEqual(sum_rune_hsp_pct([8453, "8453"]), 0.05)
        self.assertEqual(sum_rune_hsp_pct(["8005", "8453", None, ""]), 0.05)


if __name__ == "__main__":
    unittest.main()
