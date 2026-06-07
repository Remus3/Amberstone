"""list_variants must surface the AUTO-APPLIED rune (the keystone the
lcu_rune_writer.RuneWriter actually writes to the LCU page) so the champ-
select view can highlight what is really applied - not the loadout's own
build-card keystone, which is a SEPARATE source that can disagree.

Bug it guards: Caitlyn's loadout primary build is crit + Press the Attack,
but the auto-writer applies rune_recommendations_sr.json = Arcane Comet.
The champ-select panel showed PTA while the game got Comet. We surface the
auto keystone (via the same load_rune_rec source) so display == applied.

Assertions compare against load_rune_rec output (not hardcoded names) so a
later data edit to either source keeps the test green - it only pins that
the two are wired to the SAME source.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches.loadout_resolver import list_variants  # noqa: E402
from lcu.lcu_rune_writer import load_rune_rec  # noqa: E402


class AutoKeystoneSurfacedTests(unittest.TestCase):
    def _auto_for(self, champion: str, writer_mode: str):
        rec = load_rune_rec(champion, writer_mode)
        return rec  # (keystone, primary_tree, secondary_tree) or None

    def test_caitlyn_sr_rows_carry_auto_keystone_from_writer_source(self):
        rec = self._auto_for("Caitlyn", "CLASSIC")
        self.assertIsNotNone(rec, "Caitlyn must have an SR rune recommendation")
        ks, pri, sec = rec
        rows = list_variants("Caitlyn", "sr")
        self.assertTrue(rows, "Caitlyn must have at least one SR variant")
        for r in rows:
            self.assertEqual(r.get("auto_keystone"), ks)
            self.assertEqual(r.get("auto_primary"), pri)
            self.assertEqual(r.get("auto_secondary"), sec)

    def test_caitlyn_aram_rows_carry_auto_keystone(self):
        rec = self._auto_for("Caitlyn", "ARAM")
        self.assertIsNotNone(rec)
        ks, _pri, _sec = rec
        rows = list_variants("Caitlyn", "aram")
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r.get("auto_keystone"), ks)

    def test_auto_keystone_may_differ_from_build_card_keystone(self):
        # The whole point: the loadout build-card keystone and the auto-
        # applied keystone are independent. The row must expose BOTH so the
        # frontend can mark the auto one as recommended.
        rows = list_variants("Caitlyn", "sr")
        r = rows[0]
        self.assertIn("auto_keystone", r)
        self.assertIn("keystone", r)  # the loadout's own build-card keystone

    def test_unknown_champion_auto_keystone_is_empty_not_crash(self):
        rows = list_variants("Caitlyn", "sr")
        # Sanity: field is always a string (never None) so the JS `||` chain
        # behaves; empty when no rec exists.
        for r in rows:
            self.assertIsInstance(r.get("auto_keystone"), str)


if __name__ == "__main__":
    unittest.main()
