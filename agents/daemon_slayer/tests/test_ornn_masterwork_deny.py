# arch: Ornn-masterwork pool deny | section=daemon_slayer | frozen=no
"""Ornn masterwork items must NEVER enter the DS candidate pool.

Operator report (2026-07-06): the in-game BUILD panel recommended "artifact
level" items that are not attainable in a normal game - Wooglet's Witchcap
(228002) surfaced in an ARAM from-scratch optimal build.

Root cause: Wooglet's Witchcap is an ORNN MASTERWORK item - only obtainable when
an Ornn ally upgrades your legendary, NEVER purchasable from the shop. But
DDragon marks it ``gold.purchasable=True`` + ``gold.total=6000`` and legal on
map 12 (Howling Abyss / ARAM) and map 30, so it slipped past ``_is_purchasable``
+ ``_is_legal_in_mode`` and entered the pool. The definitive masterwork marker is
the ``<ornnBonus>`` stat tag in the description (present on every masterwork,
absent on every buyable item); the 228xxx id namespace is NOT safe - it also holds
Arena 22-mirror ids (228001 Anathema's Chains, 228009, 228020) which are buyable.

These tests pin: (1) the LEAK PRECONDITION still holds in the snapshot (Wooglet's
is purchasable + ARAM-legal in the raw data - so a future data change that fixes
it upstream fails HERE loudly rather than silently voiding the guard), and (2)
``_filter_candidates`` excludes EVERY Ornn masterwork item in EVERY mode.

No ENGINE_VERSION bump (mirrors the 2026-07-02 ranged-only deny ca1c9015: a
pool-correctness deny of a never-buyable item, bump deferred).
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    _filter_candidates,
    _is_legal_in_mode,
    _is_purchasable,
)

# Wooglet's Witchcap - the operator-reported masterwork (Ornn-upgraded Rabadon's).
_WOOGLET = "228002"


def _ornn_ids(snap) -> set:
    """Every Ornn masterwork id in the snapshot, by the definitive marker: the
    <ornnBonus> stat tag (present on every masterwork, absent on every buyable
    item). NOT the 228xxx id namespace - that ALSO holds Arena 22-mirror ids
    (228001 Anathema's Chains = "22" + 8001, 228009, 228020) which ARE buyable and
    must stay in the pool."""
    out = set()
    for iid, rec in snap.items.items():
        if "<ornnBonus>" in str((rec or {}).get("description") or ""):
            out.add(str(iid))
    return out


class OrnnMasterworkDenyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_leak_precondition_still_holds(self) -> None:
        # If this fails, DDragon fixed the purchasable/map flags upstream and the
        # deny is moot - re-verify before trusting the guard below.
        woog = self.snap.item(_WOOGLET)
        self.assertIsNotNone(woog, "Wooglet's Witchcap 228002 present in snapshot")
        self.assertTrue(
            _is_purchasable(woog),
            "precondition: DDragon marks Wooglet's gold.purchasable=True",
        )
        self.assertTrue(
            _is_legal_in_mode(woog, "ARAM"),
            "precondition: Wooglet's is map-12 (ARAM) legal in the raw data",
        )
        self.assertIn("<ornnBonus>", str(woog.get("description") or ""),
                      "precondition: Wooglet's carries the <ornnBonus> masterwork tag")

    def test_wooglet_excluded_from_aram_pool(self) -> None:
        cands = _filter_candidates(self.snap, "ARAM", set(), None, False, None)
        ids = {iid for iid, _ in cands}
        self.assertNotIn(
            _WOOGLET, ids,
            "Wooglet's Witchcap (Ornn masterwork) must not enter the ARAM pool",
        )

    def test_all_ornn_masterwork_excluded_every_mode(self) -> None:
        ornn = _ornn_ids(self.snap)
        self.assertIn(_WOOGLET, ornn, "the 228xxx/ornnBonus scan finds Wooglet's")
        for mode in ("SR", "ARAM", "ARENA"):
            cands = _filter_candidates(self.snap, mode, set(), None, False, None)
            ids = {iid for iid, _ in cands}
            leaked = ornn & ids
            self.assertEqual(
                set(), leaked,
                f"Ornn masterwork ids leaked into the {mode} pool: {sorted(leaked)}",
            )

    def test_include_components_does_not_readmit_ornn(self) -> None:
        # component-inclusive pool (build-order intermediate slots) must also deny.
        cands = _filter_candidates(self.snap, "ARAM", set(), None, True, None)
        ids = {iid for iid, _ in cands}
        self.assertNotIn(_WOOGLET, ids)


if __name__ == "__main__":
    unittest.main()
