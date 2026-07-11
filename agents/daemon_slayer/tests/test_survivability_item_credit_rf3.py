"""RF3 (tank-template) - survivability item-credit seam (ehp/tank ranker).

The EHP / tank scorer (``ehp.rank_items_by_ehp``) pools EVERY purchasable
mode-legal terminal item and sorts PURELY by ``delta_ehp`` (blind to win-rate), so
the WIN-correlated mid-tier resist / HP items the player base wins ARAM on (KSante:
Thornmail / Iceborn Gauntlet; Rell: Fimbulwinter - the DSP10 consolidated buried
winners on the ``ehp`` scorer lane) sink below the maximal raw-EHP stackers. The
DEFAULT-OFF ``prefer_survivability_by_win`` seam reads the WIN-anchored
``survivability_item_credit_tank`` table and, when ON, FLOATS those items above the
generic max-EHP ordering BY TABLE MEMBERSHIP.

ROOT-CAUSE distinction (verify-before-redo):
  * RF1 (hybrid lane) - the bruiser scorer's alpha-weighted damage sort buries
    pooled survivability items; RF1 floats by membership. RF3 is the SAME float
    defect in the EHP scorer (pooled, raw-EHP-max sort buries) so it mirrors RF1.
  * RF2 (enchanter lane) - the enchanter_only pool EXCLUDES HP/tank items, so RF2
    INJECTS then floats. The EHP scorer pools them ALREADY, so RF3 does NOT inject
    - the defining contrast asserted in ``test_floated_items_were_pooled_when_off``.
  * DSP6 (enemy-runes) / DSP8 (burst-target preset) alter the ENEMY damage profile
    feeding compute_ehp - every item's EHP magnitude shifts under the same context,
    so the relative SELF order is unchanged: the win items stay buried under any
    preset. RF3 is the SELF ranking-order float, orthogonal to those.

Contract (mirrors the RF1 seam convention):

* DEFAULT-OFF: ``prefer_survivability_by_win=False`` is byte-identical to today
  (``survivability_score`` stays 0.0, sort unchanged).
* A champ ABSENT from the table is a no-op even when the flag is ON.
* When ON for a tabled champ, the ranking is PARTITIONED: every surfaced
  survivability row (``survivability_score==1.0``) precedes every other row, with
  model order preserved within each tier.

Assertions are partition / membership / already-pooled invariants + computed-
quantity checks, NOT fragile absolute cross-item rank pins.
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer import survivability_credit
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp

_LEVEL = 13
_TOP = 200  # >= the ARAM terminal-item pool so nothing truncates out

# KSante's WIN-anchored tank survivability winners (terminal, non-boot).
_THORNMAIL = "3075"
_ICEBORN = "6662"
_KSANTE_SURV = {_THORNMAIL, _ICEBORN}
# Rell's WIN-anchored tank survivability winner.
_FIMBULWINTER = "3121"
_RELL_SURV = {_FIMBULWINTER}


def _snap() -> DataSnapshot:
    reset_default_cache()
    survivability_credit.reset_cache()
    return DataSnapshot.load()


def _ids(res) -> list[str]:
    return [r.item_id for r in res.ranked]


def _partitioned(res) -> bool:
    """True iff all survivability_score==1.0 rows precede all 0.0 rows."""
    seen_zero = False
    for r in res.ranked:
        if r.survivability_score <= 0.0:
            seen_zero = True
        elif seen_zero:
            return False
    return True


class TestTankSurvivabilityLoader(unittest.TestCase):
    def setUp(self) -> None:
        survivability_credit.reset_cache()

    def test_ksante_ids(self) -> None:
        ids = survivability_credit.survivability_item_ids_tank("KSante")
        self.assertTrue(_KSANTE_SURV <= ids)

    def test_rell_ids(self) -> None:
        ids = survivability_credit.survivability_item_ids_tank("Rell")
        self.assertTrue(_RELL_SURV <= ids)

    def test_unknown_and_blank_empty(self) -> None:
        # A real tank NOT tabled (Malphite) + blank both yield empty.
        self.assertEqual(
            survivability_credit.survivability_item_ids_tank("Malphite"), frozenset()
        )
        self.assertEqual(
            survivability_credit.survivability_item_ids_tank(""), frozenset()
        )

    def test_independent_of_other_tables(self) -> None:
        # RF3's tank table is independent of RF1's hybrid + RF2's enchanter tables.
        # KSante is a tank-lane entry only; Darius is a hybrid-lane entry only.
        self.assertEqual(
            survivability_credit.survivability_item_ids("KSante"), frozenset()
        )
        self.assertEqual(
            survivability_credit.survivability_item_ids_enchanter("KSante"), frozenset()
        )
        self.assertEqual(
            survivability_credit.survivability_item_ids_tank("Darius"), frozenset()
        )


class TestEhpSeam(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snap()

    def test_off_is_byte_identical(self) -> None:
        a = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP)
        b = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP,
                              prefer_survivability_by_win=False)
        self.assertEqual(_ids(a), _ids(b))
        self.assertTrue(all(r.survivability_score == 0.0 for r in b.ranked))

    def test_on_partitions_and_floats(self) -> None:
        on = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        self.assertTrue(_partitioned(on))
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        self.assertTrue(surfaced)
        # Every surfaced row is a tabled KSante item (membership float).
        self.assertTrue(surfaced <= _KSANTE_SURV)
        # The floated block sits at the very front.
        n_surf = len(surfaced)
        self.assertTrue(all(r.survivability_score == 1.0 for r in on.ranked[:n_surf]))

    def test_floated_items_were_pooled_when_off(self) -> None:
        # The defining RF3-vs-RF2 property: the EHP scorer ALREADY pools these
        # resist/HP items (it never EXCLUDES them like the enchanter_only pool) -
        # they are merely buried by the raw-EHP-max sort. So every surfaced item is
        # ALSO present in the OFF ranking; the seam floats, it does not inject.
        off = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP)
        on = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        off_ids = set(_ids(off))
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        self.assertTrue(surfaced)
        for iid in surfaced:
            self.assertIn(iid, off_ids)  # pooled when OFF, not injected

    def test_on_floats_by_membership_not_delta(self) -> None:
        # A floated survivability item floats even though its delta_ehp is NOT the
        # top of the pool (the raw-EHP-max sort rates the maximal stacker higher).
        off = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP)
        on = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        off_top_delta = off.ranked[0].delta_ehp
        floated = [r for r in on.ranked if r.survivability_score > 0.0]
        self.assertTrue(floated)
        self.assertTrue(any(r.delta_ehp < off_top_delta for r in floated))

    def test_untabled_tank_is_noop(self) -> None:
        off = rank_items_by_ehp(self.snap, "Malphite", _LEVEL, mode="ARAM", top_n=_TOP)
        on = rank_items_by_ehp(self.snap, "Malphite", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        self.assertEqual(_ids(off), _ids(on))
        self.assertTrue(all(r.survivability_score == 0.0 for r in on.ranked))


class TestEnginePin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.199.0")


if __name__ == "__main__":
    unittest.main()
