"""
tests/phase2_smoke/test_perf_tracker_ds_snapshot.py
s152 - DS pick snapshot persistence into matches.raw_data.

`performance_tracker._ds_picks_snapshot` reads the per-mode coaching
JSON written by each coach and returns the engine's last DS pick set
so `save_rating` can fold it into matches.raw_data. The wiring lets
calibration analysis read engine recommendations directly from
match_history.db without a JSONL join on (champion, mode, ~ts).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from performance_tracker import _ds_picks_snapshot, _DS_COACH_FILE_BY_CATEGORY


class DsPicksSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.sd = Path(self._tmp.name)
        (self.sd / "data").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, fname: str, payload: dict) -> None:
        (self.sd / "data" / fname).write_text(
            json.dumps(payload), encoding="utf-8")

    def test_returns_picks_for_known_category(self) -> None:
        picks = [
            {"id": "3097", "name": "Stormrazor",
             "delta_dps": 60.7, "gold": 3200},
            {"id": "3087", "name": "Statikk Shiv",
             "delta_dps": 56.7, "gold": 3000},
        ]
        self._write("aram_coaching_data.json", {"daemon_slayer_picks": picks})
        out = _ds_picks_snapshot(str(self.sd), "ARAM")
        self.assertEqual(out, picks)

    def test_returns_empty_when_picks_missing(self) -> None:
        self._write("coaching_data.json", {"action": "push wave"})
        self.assertEqual(_ds_picks_snapshot(str(self.sd), "SR"), [])

    def test_returns_empty_for_unknown_category(self) -> None:
        # TFT has no DS engine wiring; mapping intentionally omits it.
        self.assertEqual(_ds_picks_snapshot(str(self.sd), "TFT"), [])
        self.assertEqual(_ds_picks_snapshot(str(self.sd), ""), [])
        self.assertEqual(_ds_picks_snapshot(str(self.sd), "BOGUS"), [])

    def test_returns_empty_when_file_missing(self) -> None:
        # No file written - snapshot must soft-fail.
        self.assertEqual(_ds_picks_snapshot(str(self.sd), "ARAM"), [])

    def test_returns_empty_when_file_unparseable(self) -> None:
        (self.sd / "data" / "coaching_data.json").write_text(
            "not json at all", encoding="utf-8")
        self.assertEqual(_ds_picks_snapshot(str(self.sd), "SR"), [])

    def test_returns_empty_when_picks_field_wrong_type(self) -> None:
        # A coach mid-flush could leave a string in there; helper must
        # not propagate a non-list to the DB raw_data.
        self._write("brawl_coaching_data.json",
                    {"daemon_slayer_picks": "oops"})
        self.assertEqual(_ds_picks_snapshot(str(self.sd), "BRAWL"), [])

    def test_returns_empty_when_top_level_not_dict(self) -> None:
        (self.sd / "data" / "coaching_data.json").write_text(
            "[1, 2, 3]", encoding="utf-8")
        self.assertEqual(_ds_picks_snapshot(str(self.sd), "SR"), [])

    def test_category_mapping_covers_ds_modes_only(self) -> None:
        # SR / ARAM / ARENA / BRAWL are the four modes where the DS
        # engine fires. TFT has no DPS framework so it's intentionally
        # excluded; this test pins that mapping so a future "wire TFT"
        # change is a deliberate decision and not an accidental drift.
        self.assertEqual(
            set(_DS_COACH_FILE_BY_CATEGORY.keys()),
            {"SR", "ARAM", "ARENA", "BRAWL"},
        )


if __name__ == "__main__":
    unittest.main()
