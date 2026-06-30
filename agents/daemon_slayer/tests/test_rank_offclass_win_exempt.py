"""DSP2 Cluster-B - off-class WIN-exemption seam (DEFAULT-OFF).

The item-213 ranged-marksman off-class deny-set
(``rank.OFFCLASS_MARKSMAN_ITEM_NAMES``) strips Sheen-line / on-hit-caster
items (Trinity Force, Spear of Shojin, Black Cleaver) from EVERY ranged
marksman. The DSP1 WIN-anchor proved that wrong for ability / Sheen
caster-marksmen (Ezreal SR -39 was the single worst outcome-divergent
champ-mode because Trinity Force - his most-built item, ARAM n=219 - was hard
excluded from the candidate pool).

``rank_items(exempt_offclass_by_win=True)`` un-strips an off-class item for a
ranged marksman when the WIN+usage data
(``agents/daemon_slayer/marksman_offclass_exempt.json``, built offline from the
cross-eval empirical block) shows the player base genuinely builds it. The seam
is DEFAULT-OFF and byte-identical when off (the DSV1-4 precedent); the live
default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

These assertions are difference-of-behavior (ON vs OFF, exempt vs crit-ADC),
never fragile cross-item magnitude equality.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer import rank as rank_mod
from agents.daemon_slayer.rank import (
    _load_offclass_exemptions,
    _offclass_win_exemptions,
    rank_items,
)


def _names(res):
    return {r.item_name for r in res.ranked}


def _ids(res):
    return tuple(r.item_id for r in res.ranked)


class ExemptTableShapeTests(unittest.TestCase):
    def test_table_is_name_frozenset_map(self) -> None:
        tbl = _load_offclass_exemptions()
        self.assertIsInstance(tbl, dict)
        self.assertIn("Ezreal", tbl)
        self.assertIsInstance(tbl["Ezreal"], frozenset)
        self.assertIn("Trinity Force", tbl["Ezreal"])
        self.assertIn("Spear of Shojin", tbl["Ezreal"])
        # ASCII hygiene - operator hard rule.
        for champ, names in tbl.items():
            self.assertTrue(champ.isascii(), champ)
            for n in names:
                self.assertTrue(n.isascii(), n)

    def test_every_exempt_name_is_in_the_deny_set(self) -> None:
        # An exemption only makes sense for an item the deny-set would strip.
        tbl = _load_offclass_exemptions()
        for champ, names in tbl.items():
            for n in names:
                self.assertIn(
                    n, rank_mod.OFFCLASS_MARKSMAN_ITEM_NAMES,
                    f"{champ} exempts {n!r} which is not in the deny-set",
                )

    def test_pure_crit_adcs_have_no_exemption(self) -> None:
        tbl = _load_offclass_exemptions()
        for champ in ("Caitlyn", "Jinx", "Ashe", "Sivir"):
            self.assertNotIn(champ, tbl, f"{champ} should not be exempted")


class ExemptHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_resolves_by_id(self) -> None:
        rec = self.snap.champions.get("Ezreal")
        ex = _offclass_win_exemptions("Ezreal", rec)
        self.assertIn("Trinity Force", ex)

    def test_unknown_champ_returns_empty(self) -> None:
        rec = self.snap.champions.get("Caitlyn")
        self.assertEqual(_offclass_win_exemptions("Caitlyn", rec), frozenset())


class ExemptLoaderFailSoftTests(unittest.TestCase):
    def test_missing_file_is_empty(self) -> None:
        orig_path = rank_mod._OFFCLASS_EXEMPT_PATH
        orig_cache = rank_mod._OFFCLASS_EXEMPT_CACHE
        try:
            rank_mod._OFFCLASS_EXEMPT_CACHE = None
            rank_mod._OFFCLASS_EXEMPT_PATH = orig_path.with_name(
                "does_not_exist_marksman_exempt.json"
            )
            self.assertEqual(_load_offclass_exemptions(), {})
        finally:
            rank_mod._OFFCLASS_EXEMPT_PATH = orig_path
            rank_mod._OFFCLASS_EXEMPT_CACHE = None


class OffClassExemptSeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rank(self, champ, mode, exempt, top=None):
        # top_n=None ranks the FULL candidate pool. The seam un-strips an item
        # from the pool (makes it a candidate); where it then ranks is the
        # scorer's call - Spear of Shojin is an ability/Sheen item the
        # auto-DPS scorer ranks low, so a bounded top-N would hide the
        # pool-membership change the seam is actually responsible for.
        return rank_items(
            self.snap, champ, level=13, current_item_ids=[], mode=mode,
            target_armor=80, target_mr=60, target_max_hp=2000,
            target_bonus_hp=600, top_n=top, exempt_offclass_by_win=exempt,
        )

    def test_default_off_preserves_item213(self) -> None:
        # Seam OFF (default): Ezreal still has Trinity Force / Shojin stripped
        # from the entire candidate pool.
        for mode in ("SR", "ARAM"):
            names = _names(self._rank("Ezreal", mode, False))
            self.assertNotIn("Trinity Force", names, mode)
            self.assertNotIn("Spear of Shojin", names, mode)

    def test_seam_on_unstrips_ezreal_winning_items(self) -> None:
        # Both of Ezreal's empirically-built off-class items re-enter the pool.
        for mode in ("SR", "ARAM"):
            names = _names(self._rank("Ezreal", mode, True))
            self.assertIn("Trinity Force", names, mode)
            self.assertIn("Spear of Shojin", names, mode)

    def test_seam_on_unstrips_corki_and_smolder(self) -> None:
        self.assertIn("Trinity Force", _names(self._rank("Corki", "ARAM", True)))
        self.assertIn("Trinity Force", _names(self._rank("Smolder", "ARAM", True)))
        self.assertIn("Black Cleaver", _names(self._rank("Senna", "ARAM", True)))

    def test_crit_adc_unchanged_when_seam_on(self) -> None:
        # Caitlyn is not in the table: ON must be byte-identical to OFF (same
        # full-pool ranking) and must still exclude the off-class items.
        for mode in ("SR", "ARAM"):
            off = self._rank("Caitlyn", mode, False)
            on = self._rank("Caitlyn", mode, True)
            self.assertEqual(_ids(off), _ids(on), f"Caitlyn {mode} drifted")
            self.assertNotIn("Trinity Force", _names(on), mode)

    def test_seam_on_adds_only_exempt_items_for_ezreal(self) -> None:
        # Over the full pool, ON differs from OFF ONLY by adding Ezreal's
        # exempt items - nothing else moves in or out.
        off_ids = set(_ids(self._rank("Ezreal", "SR", False)))
        on_ids = set(_ids(self._rank("Ezreal", "SR", True)))
        self.assertTrue(off_ids.issubset(on_ids))
        on = self._rank("Ezreal", "SR", True)
        added = {r.item_name for r in on.ranked if r.item_id not in off_ids}
        self.assertEqual(added, {"Trinity Force", "Spear of Shojin"})


class EngineVersionPinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.155.0")


if __name__ == "__main__":
    unittest.main()
