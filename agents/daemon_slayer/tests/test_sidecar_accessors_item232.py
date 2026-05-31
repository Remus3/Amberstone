"""Item 232 - data_loader sidecar accessors (geometry / recharge / mode_modifier).

Foundation layer: new accessors over the cdragon_spell_stats geometry bucket,
the wiki_ability_stats recharge bucket (newly loaded), and the wiki_stats
mode_modifiers bucket. Accessors are pure reads - byte-identical engine output.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import (
    DataSnapshot,
    _WIKI_MODE_ALIASES,
)


class SidecarAccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_wiki_ability_stats_loaded(self) -> None:
        # The new field loads from wiki_ability_stats.json (item 232).
        self.assertIsInstance(self.snap.wiki_ability_stats, dict)
        self.assertGreater(len(self.snap.wiki_ability_stats), 0)

    def test_spell_geometry_present(self) -> None:
        # Aatrox W (Infernal Chains) is a line skillshot -> non-null line_width.
        geo = self.snap.spell_geometry("Aatrox", "W")
        self.assertIsInstance(geo, dict)
        # Line skillshot: non-null line_width. cast_radius_conflated only
        # appears on radial spells, so the key set is shape-dependent.
        self.assertIn("line_width", geo)
        self.assertIsNotNone(geo["line_width"])
        self.assertIn("cast_radius", geo)

    def test_spell_geometry_absent_returns_none(self) -> None:
        self.assertIsNone(self.snap.spell_geometry("Aatrox", "ZZ"))
        self.assertIsNone(self.snap.spell_geometry("NotAChamp", "Q"))

    def test_spell_geometry_null_slot_returns_none(self) -> None:
        # Aatrox Q carries no geometry block (null) -> None.
        self.assertIsNone(self.snap.spell_geometry("Aatrox", "Q"))

    def test_ability_recharge_present(self) -> None:
        # Caitlyn Yordle Snap Trap is a charge ability -> recharge_ranks list.
        rr = self.snap.ability_recharge("Caitlyn", "Yordle Snap Trap")
        self.assertIsInstance(rr, list)
        self.assertGreater(len(rr), 0)
        for v in rr:
            self.assertIsInstance(v, (int, float))

    def test_ability_recharge_absent_returns_none(self) -> None:
        self.assertIsNone(self.snap.ability_recharge("Aatrox", "Nope"))
        self.assertIsNone(self.snap.ability_recharge("NotAChamp", "X"))

    def test_mode_modifier_multiplier_mode(self) -> None:
        # Ahri URF carries dmg_dealt/dmg_taken MULTIPLIERS.
        urf = self.snap.mode_modifier("Ahri", "urf")
        self.assertIsInstance(urf, dict)
        self.assertIn("dmg_dealt", urf)
        self.assertIsInstance(urf["dmg_dealt"], (int, float))

    def test_mode_modifier_arena_alias(self) -> None:
        # ARENA engine string bridges to wiki "ar" key (addend mode).
        self.assertEqual(_WIKI_MODE_ALIASES["arena"], "ar")
        ar = self.snap.mode_modifier("Akali", "ARENA")
        self.assertIsInstance(ar, dict)
        self.assertIn("hp_lvl", ar)

    def test_mode_modifier_absent_returns_none(self) -> None:
        self.assertIsNone(self.snap.mode_modifier("Ahri", "doesnotexist"))
        self.assertIsNone(self.snap.mode_modifier("NotAChamp", "urf"))

    def test_absent_sidecar_byte_identical(self) -> None:
        # An empty snapshot (no sidecars) yields None for every accessor -
        # the byte-identical fallback contract.
        empty = DataSnapshot(
            patch="x",
            manifest={},
            champions={"Aatrox": {}},
            items={},
            scenarios_by_id={},
            scenarios_by_lolmath={},
            arena_augments_by_id={},
            arena_augments_by_api={},
            data_root=self.snap.data_root,
        )
        self.assertIsNone(empty.spell_geometry("Aatrox", "Q"))
        self.assertIsNone(empty.ability_recharge("Aatrox", "X"))
        self.assertIsNone(empty.mode_modifier("Aatrox", "urf"))
        self.assertEqual(empty.wiki_ability_stats, {})


if __name__ == "__main__":
    unittest.main()
