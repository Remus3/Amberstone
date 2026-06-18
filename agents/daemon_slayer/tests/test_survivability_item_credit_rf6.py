"""RF6 (tank-template INJECT) - ehp/tank survivability item-credit inject seam.

RF3 added a FLOAT-only ``prefer_survivability_by_win`` seam to the EHP scorer
(``ehp.rank_items_by_ehp``): it reorders POOLED items by WIN-table membership.
RF4 then found that float is a NO-OP for Rell - its sole tabled winner Fimbulwinter
3121 is the non-purchasable mana-line transform of Winter's Approach
(``gold.purchasable``=False), so ``_filter_candidates`` EXCLUDES it from the pool
and there is nothing for the RF3 float to lift (RF4 verified in_pool=False). RF3's
"the EHP scorer ALREADY pools these resist/HP items" premise holds for KSante
(Thornmail 3075 / Iceborn 6662 both pooled + floated) but is FALSE for Rell.

RF6 adds an INJECT mode (RF2's enchanter-inject intent, extended): the ehp lane now
force-admits the tabled WIN-anchored ids past the ``_is_purchasable`` gate via the
new ``_filter_candidates(inject_ids=...)`` param, so a not-pooled transform like
Fimbulwinter enters the pool and the existing RF3 float lifts it.

ROOT-CAUSE distinction (verify-before-redo):
  * RF3 (this same lane) FLOATS already-pooled ids. RF6 is the SAME lane but covers
    the tabled ids the pool DROPS - it INJECTS, then RF3's float prefix lifts them.
  * RF2 (enchanter lane) injects via ``only_ids |= surv_ids`` - but that union still
    runs through ``_is_purchasable``, so it could NOT surface a non-purchasable
    transform (Rakan's tabled 3121 is silently dropped today). RF6's force-admit
    clears the purchasable gate the RF2 union could not.

Contract (mirrors the RF1/RF3 seam convention):

* DEFAULT-OFF: ``prefer_survivability_by_win=False`` is byte-identical to today
  (``survivability_score`` stays 0.0; the pool - ``inject_ids`` None - and the sort
  are unchanged).
* A champ ABSENT from the table is a no-op even when the flag is ON.
* When ON for a tabled champ whose winner the pool DROPS (Rell / Fimbulwinter), the
  injected id surfaces (``survivability_score==1.0``) and PARTITIONS to the front -
  the defining RF6-vs-RF3 property: it is NOT present in the OFF ranking.
* RF3's already-pooled float (KSante) is unbroken - inject is a superset of float.

Assertions are partition / membership / injected-not-pooled invariants, NOT fragile
absolute cross-item rank pins.
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer import survivability_credit
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.rank import _filter_candidates, _is_purchasable

_LEVEL = 13
_TOP = 200  # >= the ARAM terminal-item pool so nothing truncates out

# Rell's WIN-anchored tank survivability winner - the non-purchasable transform.
_FIMBULWINTER = "3121"
_RELL_SURV = {_FIMBULWINTER}
# KSante's WIN-anchored winners (already pooled; RF3 float still applies).
_THORNMAIL = "3075"
_ICEBORN = "6662"
_KSANTE_SURV = {_THORNMAIL, _ICEBORN}


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


class TestFilterCandidatesInject(unittest.TestCase):
    """The RF6 force-admit param on the shared _filter_candidates."""

    def setUp(self) -> None:
        self.snap = _snap()

    def test_fimbulwinter_is_non_purchasable(self) -> None:
        # The premise: 3121 carries gold.purchasable=False (it transforms from
        # Winter's Approach), so the normal pool gate drops it.
        rec = self.snap.items.get(_FIMBULWINTER)
        self.assertIsNotNone(rec)
        self.assertFalse(_is_purchasable(rec))

    def test_inject_none_is_byte_identical(self) -> None:
        a = _filter_candidates(
            self.snap, mode="ARAM", current_ids=set(), budget=None,
            include_components=False, only_ids=None,
        )
        b = _filter_candidates(
            self.snap, mode="ARAM", current_ids=set(), budget=None,
            include_components=False, only_ids=None, inject_ids=None,
        )
        self.assertEqual([i for i, _ in a], [i for i, _ in b])
        # And 3121 is NOT admitted on the default path (purchasable gate).
        self.assertNotIn(_FIMBULWINTER, {i for i, _ in a})

    def test_inject_force_admits_non_purchasable(self) -> None:
        out = _filter_candidates(
            self.snap, mode="ARAM", current_ids=set(), budget=None,
            include_components=False, only_ids=None, inject_ids={_FIMBULWINTER},
        )
        self.assertIn(_FIMBULWINTER, {i for i, _ in out})

    def test_inject_still_respects_mode_legality(self) -> None:
        # 3121 is map30=False (Arena); even forced it must not surface in ARENA.
        out = _filter_candidates(
            self.snap, mode="ARENA", current_ids=set(), budget=None,
            include_components=False, only_ids=None, inject_ids={_FIMBULWINTER},
        )
        self.assertNotIn(_FIMBULWINTER, {i for i, _ in out})


class TestRellInjectSeam(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snap()

    def test_rell_ids(self) -> None:
        ids = survivability_credit.survivability_item_ids_tank("Rell")
        self.assertTrue(_RELL_SURV <= ids)

    def test_off_is_byte_identical(self) -> None:
        a = rank_items_by_ehp(self.snap, "Rell", _LEVEL, mode="ARAM", top_n=_TOP)
        b = rank_items_by_ehp(self.snap, "Rell", _LEVEL, mode="ARAM", top_n=_TOP,
                              prefer_survivability_by_win=False)
        self.assertEqual(_ids(a), _ids(b))
        self.assertTrue(all(r.survivability_score == 0.0 for r in b.ranked))
        # The RF4-verified premise: 3121 is NOT pooled when the seam is OFF.
        self.assertNotIn(_FIMBULWINTER, set(_ids(a)))

    def test_on_injects_and_floats_fimbulwinter(self) -> None:
        on = rank_items_by_ehp(self.snap, "Rell", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        # The directive deliverable: Rell's Fimbulwinter floats ON.
        self.assertIn(_FIMBULWINTER, surfaced)
        self.assertTrue(surfaced <= _RELL_SURV)
        self.assertTrue(_partitioned(on))
        n_surf = len(surfaced)
        self.assertTrue(all(r.survivability_score == 1.0 for r in on.ranked[:n_surf]))

    def test_injected_item_was_not_pooled_when_off(self) -> None:
        # The defining RF6-vs-RF3 property: unlike RF3's KSante (already pooled, only
        # floated), Rell's Fimbulwinter is ABSENT from the OFF ranking and only
        # appears ON - it is INJECTED, not merely floated.
        off = rank_items_by_ehp(self.snap, "Rell", _LEVEL, mode="ARAM", top_n=_TOP)
        on = rank_items_by_ehp(self.snap, "Rell", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        off_ids = set(_ids(off))
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        self.assertIn(_FIMBULWINTER, surfaced)
        self.assertNotIn(_FIMBULWINTER, off_ids)  # injected, not pooled-when-off


class TestKSanteFloatStillWorks(unittest.TestCase):
    """RF6's inject is a superset of RF3's float - already-pooled KSante is unbroken."""

    def setUp(self) -> None:
        self.snap = _snap()

    def test_ksante_off_byte_identical(self) -> None:
        a = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP)
        b = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP,
                              prefer_survivability_by_win=False)
        self.assertEqual(_ids(a), _ids(b))

    def test_ksante_on_floats_pooled_winners(self) -> None:
        off = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP)
        on = rank_items_by_ehp(self.snap, "KSante", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        off_ids = set(_ids(off))
        surfaced = {r.item_id for r in on.ranked if r.survivability_score > 0.0}
        self.assertTrue(surfaced)
        self.assertTrue(surfaced <= _KSANTE_SURV)
        self.assertTrue(_partitioned(on))
        # KSante's winners were ALREADY pooled when OFF (RF3 float, not inject).
        for iid in surfaced:
            self.assertIn(iid, off_ids)


class TestUntabledTankIsNoop(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snap()

    def test_malphite_noop(self) -> None:
        off = rank_items_by_ehp(self.snap, "Malphite", _LEVEL, mode="ARAM", top_n=_TOP)
        on = rank_items_by_ehp(self.snap, "Malphite", _LEVEL, mode="ARAM", top_n=_TOP,
                               prefer_survivability_by_win=True)
        self.assertEqual(_ids(off), _ids(on))
        self.assertTrue(all(r.survivability_score == 0.0 for r in on.ranked))


class TestEnginePin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.141.0")


if __name__ == "__main__":
    unittest.main()
