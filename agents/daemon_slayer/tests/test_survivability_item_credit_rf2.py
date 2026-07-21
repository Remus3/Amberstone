"""RF2 (enchanter-template) - survivability item-credit seam (hps/enchanter ranker).

The enchanter throughput scorer (``hps.rank_items_by_hps``) defaults
``enchanter_only=True`` - it restricts the candidate pool to the curated
enchanter-throughput formula registry (Echoes of Helia / Ardent Censer / Staff of
Flowing Water / Locket / Knight's Vow / Redemption). So for an enchanter played
front-to-back as a tank-support, the HP / tank survivability items the player base
wins ARAM on (Guardian's Horn / Warmog's Armor / Heartsteel / Fimbulwinter; the
DSP10 hps-lane buried winners) are EXCLUDED from the pool entirely - they add zero
HPS throughput, so they are not in the registry and never appear. The DEFAULT-OFF
``prefer_survivability_by_win`` seam reads the WIN-anchored
``survivability_item_credit_enchanter`` table and, when ON, INJECTS those ids into
the candidate pool and floats them above the generic template BY TABLE MEMBERSHIP.

ROOT-CAUSE distinction from the RF1 hybrid seam (verify-before-redo): RF1's bruiser
scorer ALREADY pools survivability items - its alpha-weighted damage sort merely
buries them, so RF1 only floats. The enchanter scorer is WORSE: enchanter_only
EXCLUDES them, so RF2 must ALSO inject before floating. Cluster A (Zilean/Seraphine
AP-in-ARAM, both with AP buried winners on the hps lane) is operator-gated and NOT
tabled.

Contract (mirrors the RF1 seam convention):

* DEFAULT-OFF: ``prefer_survivability_by_win=False`` is byte-identical to today
  (``survivability_score`` stays 0.0, pool + sort unchanged).
* A champ ABSENT from the table is a no-op even when the flag is ON.
* When ON for a tabled champ, the survivability items - which the enchanter_only
  pool OMITS entirely when OFF - are injected and PARTITIONED to the front (every
  surfaced ``survivability_score==1.0`` row precedes every other row), with model
  order preserved within each tier.

Assertions are partition / membership / pool-injection invariants + computed-quantity
checks, NOT fragile absolute cross-item rank pins.
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer import survivability_credit
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import rank_items_by_hps

_LEVEL = 13
# Rakan's WIN-anchored enchanter survivability winners (terminal, non-boot).
_FIMBULWINTER = "3121"
_HEARTSTEEL = "3084"
_GUARDIANS_HORN = "2051"
_WARMOGS = "3083"
_RAKAN_SURV = {_FIMBULWINTER, _HEARTSTEEL, _GUARDIANS_HORN, _WARMOGS}


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


class TestEnchanterSurvivabilityLoader(unittest.TestCase):
    def setUp(self) -> None:
        survivability_credit.reset_cache()

    def test_rakan_ids(self) -> None:
        ids = survivability_credit.survivability_item_ids_enchanter("Rakan")
        self.assertTrue(_RAKAN_SURV <= ids)

    def test_unknown_and_blank_empty(self) -> None:
        # A real enchanter NOT tabled (Soraka) + blank both yield empty.
        self.assertEqual(
            survivability_credit.survivability_item_ids_enchanter("Soraka"), frozenset()
        )
        self.assertEqual(
            survivability_credit.survivability_item_ids_enchanter(""), frozenset()
        )

    def test_hybrid_table_unaffected(self) -> None:
        # RF2's enchanter table is independent of RF1's hybrid table - Rakan is NOT a
        # hybrid-lane entry and a bruiser is NOT an enchanter-lane entry.
        self.assertEqual(
            survivability_credit.survivability_item_ids("Rakan"), frozenset()
        )
        self.assertEqual(
            survivability_credit.survivability_item_ids_enchanter("Darius"), frozenset()
        )


class TestHpsSeam(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snap()

    def test_off_is_byte_identical(self) -> None:
        a = rank_items_by_hps(self.snap, "Rakan", _LEVEL, mode="ARAM", top_n=40)
        b = rank_items_by_hps(self.snap, "Rakan", _LEVEL, mode="ARAM", top_n=40,
                              prefer_survivability_by_win=False)
        self.assertEqual(_ids(a), _ids(b))
        self.assertTrue(all(r.survivability_score == 0.0 for r in b.ranked))

    def test_on_injects_excluded_items(self) -> None:
        # The defining RF2 property: the enchanter_only pool OMITS the HP/tank
        # survivability items entirely when OFF; the seam must INJECT them. Heartsteel
        # + Warmog's are standard ARAM-legal terminal HP items the throughput scorer
        # never surfaces on its own.
        off = rank_items_by_hps(self.snap, "Rakan", _LEVEL, mode="ARAM", top_n=40)
        on = rank_items_by_hps(self.snap, "Rakan", _LEVEL, mode="ARAM", top_n=40,
                               prefer_survivability_by_win=True)
        off_ids = set(_ids(off))
        self.assertNotIn(_HEARTSTEEL, off_ids)   # excluded by enchanter_only when OFF
        self.assertNotIn(_WARMOGS, off_ids)
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        self.assertIn(_HEARTSTEEL, surfaced)     # injected by the seam when ON
        self.assertIn(_WARMOGS, surfaced)

    def test_on_partitions_and_floats(self) -> None:
        on = rank_items_by_hps(self.snap, "Rakan", _LEVEL, mode="ARAM", top_n=40,
                               prefer_survivability_by_win=True)
        self.assertTrue(_partitioned(on))
        # Every surfaced survivability row is a tabled Rakan item (membership float).
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        self.assertTrue(surfaced)
        self.assertTrue(surfaced <= _RAKAN_SURV)
        # The floated block sits at the very front.
        n_surf = len(surfaced)
        self.assertTrue(all(r.survivability_score == 1.0 for r in on.ranked[:n_surf]))

    def test_on_floats_by_membership_not_throughput(self) -> None:
        # A floated survivability item adds zero HPS throughput (it is not an
        # enchanter item) yet floats above the genuine throughput winners - proving
        # the float is by WIN-table membership, not by the delta_hps sort key.
        off = rank_items_by_hps(self.snap, "Rakan", _LEVEL, mode="ARAM", top_n=40)
        on = rank_items_by_hps(self.snap, "Rakan", _LEVEL, mode="ARAM", top_n=40,
                               prefer_survivability_by_win=True)
        floated = [r for r in on.ranked if r.survivability_score > 0.0]
        self.assertTrue(floated)
        # off's #1 is a real enchanter throughput gain (> 0); each floated item's
        # throughput delta is at or below it (survivability items add no HPS).
        off_top_delta = off.ranked[0].delta_hps
        self.assertTrue(all(r.delta_hps <= off_top_delta for r in floated))

    def test_untabled_enchanter_is_noop(self) -> None:
        off = rank_items_by_hps(self.snap, "Soraka", _LEVEL, mode="ARAM", top_n=30)
        on = rank_items_by_hps(self.snap, "Soraka", _LEVEL, mode="ARAM", top_n=30,
                               prefer_survivability_by_win=True)
        self.assertEqual(_ids(off), _ids(on))
        self.assertTrue(all(r.survivability_score == 0.0 for r in on.ranked))


class TestEnginePin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.233.0")


if __name__ == "__main__":
    unittest.main()
