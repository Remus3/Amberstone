import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot, SnapshotNotFound


class DataSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_pointer_resolves_patch(self) -> None:
        self.assertTrue(self.snap.patch)
        self.assertRegex(self.snap.patch, r"^\d+\.\d+\.\d+$")

    def test_champion_count_matches_manifest(self) -> None:
        self.assertEqual(
            len(self.snap.champions),
            self.snap.manifest["ddragon_champion_count"],
        )

    def test_item_count_matches_manifest(self) -> None:
        self.assertEqual(
            len(self.snap.items),
            self.snap.manifest["ddragon_item_count"],
        )

    def test_known_champion_lookup(self) -> None:
        a = self.snap.champion("Aatrox")
        self.assertEqual(a["name"], "Aatrox")
        self.assertIn("stats", a)

    def test_known_item_lookup_by_int_or_str(self) -> None:
        as_int = self.snap.item(3072)
        as_str = self.snap.item("3072")
        self.assertIs(as_int, as_str)
        self.assertEqual(as_int["name"], "Bloodthirster")

    def test_missing_champion_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.snap.champion("Notarealchamp")

    def test_missing_patch_raises(self) -> None:
        with self.assertRaises(SnapshotNotFound):
            DataSnapshot.load(patch="0.0.0")

    def test_scenarios_present_for_all_champions(self) -> None:
        missing = [cid for cid in self.snap.champions if not self.snap.scenarios(cid)]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
