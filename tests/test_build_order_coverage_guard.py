"""Lane B precomputed build-order COVERAGE guard.

WHY THIS EXISTS
---------------
Lane B of the Haiku-elimination program wants build coaching to be a LOOKUP into
a precomputed Daemon Slayer table instead of a live LLM call. The dangerous
state is a precompute that is silently PARTIAL: every consumer of these tables
in this repo fails SOFT, so an uncovered champion is indistinguishable from a
covered one until a live game renders a blank NEXT BUY row.

    core/precomputed_build_coach.py:172   `if not rec: return []`
    core/next_buy_fallback.py:171         total, returns [] on any miss
    dashboard/_deterministic_coaching.py:225  `_next_build_item` -> None
    core/laning_verdicts.py:194           `return None`

Not one of them raises. Nothing in the suite asserted the tables were COMPLETE
either: the pre-existing on-disk guards (tests/test_build_order_precompute.py:
`for champ, variants in bo.items()`, tests/test_build_order_variants.py:445,
tests/test_hz_precompute_canonical_keyspace.py) iterate the artifact and check
the shape of whatever they find. A table regenerated with 10 of 173 champions
passes every one of them - the artifact defines its own universe, which is the
circular consumer-side enumeration this guard deliberately avoids.

WHAT IT PINS
------------
The universe is derived entirely from the PRODUCER side (see
tools/build_order_coverage.py): modes from each producer's `--mode all` tuple,
champions from `build_order_precompute.full_roster()` (canonical families) and
`daemon_slayer_build_orders_generate.load_champions()` (display family), axes
from COMP_ARCHETYPES / VARIANTS / ENEMY_COMP_CLASSES, slots from `_SLOTS`, patch
from data/daemon_slayer/current.txt. Nothing is hardcoded, so a roster change,
a new comp archetype, or a new mode raises the expected cell count on its own
and the guard goes red until the tables are regenerated.

COVERAGE FLOOR = 1.0 (100 percent). MEASURED 2026-07-30 at patch 16.14.1 /
ENGINE 1.267.0: 4671 of 4671 cells populated across all three families and all
three modes. Full coverage IS today's state, so the floor is not a concession -
there is no known gap to grandfather. Modes sr / aram / arena are the whole
scope: ARAM Mayhem (raw gameMode KIWI) maps onto the aram tables via
core.mode_capabilities.district_config and is not a fourth keyspace; TFT and
brawl have no build tables by design (core/next_buy_fallback.py:66).
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import build_order_precompute as bop
from core import build_order_variants as bov
from tools import build_order_coverage as cov
from tools import daemon_slayer_build_orders_generate as gen

# The measured floor. Deliberately 1.0 - see the module docstring. Lowering this
# is a decision that needs a recorded reason, not a green-suite convenience.
COVERAGE_FLOOR = 1.0


class ProducerDerivedUniverseTests(unittest.TestCase):
    """The expected universe comes from the producers, not from the artifacts.

    If any of these regress to reading the table on disk the coverage number
    becomes self-fulfilling, so they are asserted directly rather than implied.
    """

    def test_modes_come_from_each_producer(self):
        self.assertEqual(cov.expected_modes(cov.FAMILY_COMP),
                         tuple(bop._MODE_KEYS))
        self.assertEqual(cov.expected_modes(cov.FAMILY_VARIANT),
                         tuple(bov.DS_MODE_KEYS))
        self.assertEqual(cov.expected_modes(cov.FAMILY_FLAT),
                         tuple(gen.MODES))

    def test_axes_come_from_each_producer(self):
        self.assertEqual(cov.expected_axes(cov.FAMILY_COMP),
                         tuple(bop.COMP_ARCHETYPES))
        self.assertEqual(cov.expected_axes(cov.FAMILY_VARIANT),
                         tuple(bov.VARIANTS))
        self.assertEqual(cov.expected_axes(cov.FAMILY_FLAT),
                         tuple(gen.ENEMY_COMP_CLASSES))

    def test_rosters_come_from_each_producer_and_are_two_keyspaces(self):
        canonical = cov.expected_roster(cov.FAMILY_COMP)
        self.assertEqual(canonical, tuple(bop.full_roster()))
        self.assertEqual(cov.expected_roster(cov.FAMILY_VARIANT), canonical)
        display = cov.expected_roster(cov.FAMILY_FLAT)
        self.assertEqual(display, tuple(gen.load_champions()))
        # Two DISTINCT key-spaces of the SAME roster size. If these ever became
        # the same set someone collapsed the keyspaces and the flat consumers
        # (which look up raw display names) would start missing.
        self.assertEqual(len(canonical), len(display))
        self.assertNotEqual(set(canonical), set(display))

    def test_slot_count_comes_from_the_generator(self):
        self.assertEqual(cov.expected_slots(), gen._SLOTS)

    def test_patch_comes_from_current_txt(self):
        self.assertEqual(cov.resolve_patch(), bop.resolve_patch())


class LiveCoverageTests(unittest.TestCase):
    """The committed tables cover the producer-derived universe."""

    @classmethod
    def setUpClass(cls):
        cls.report = cov.measure_all()

    def test_every_family_mode_table_exists(self):
        absent = [
            f"{t['family']}/{t['mode']} -> {t['path']}"
            for t in self.report["tables"] if not t["exists"]
        ]
        self.assertFalse(absent, (
            f"patch {self.report['patch']}: build-order tables absent: {absent}. "
            "Regen: python -m core.build_order_precompute --static --mode all "
            "--champions all; python -m core.build_order_variants --static "
            "--mode all --champions all; python "
            "tools/daemon_slayer_build_orders_generate.py --mode all"
        ))

    def test_no_table_reports_a_read_error(self):
        broken = [
            f"{t['family']}/{t['mode']}: {t['error']}"
            for t in self.report["tables"] if t["error"]
        ]
        self.assertFalse(broken, f"unreadable build-order tables: {broken}")

    def test_no_champion_missing_from_any_table(self):
        for t in self.report["tables"]:
            with self.subTest(family=t["family"], mode=t["mode"]):
                self.assertEqual(
                    t["missing_champions"], [],
                    f"{t['family']}/{t['mode']} ({t['keyspace']} keyspace): "
                    f"{len(t['missing_champions'])} champions in the producer "
                    f"roster have NO row, e.g. {t['missing_champions'][:5]}. "
                    "A partial regeneration leaves the live coach silently "
                    "blank for these champions.",
                )

    def test_no_empty_or_short_cells(self):
        for t in self.report["tables"]:
            with self.subTest(family=t["family"], mode=t["mode"]):
                self.assertEqual(
                    t["empty_cells"], [],
                    f"{t['family']}/{t['mode']}: {len(t['empty_cells'])} cells "
                    f"have an empty order, e.g. {t['empty_cells'][:5]}. An empty "
                    "order is what the producers emit when the DS engine is "
                    "down - the table was generated against a dead :8860.",
                )
                self.assertEqual(
                    t["short_cells"], [],
                    f"{t['family']}/{t['mode']}: {len(t['short_cells'])} cells "
                    f"are shorter than {self.report['slots']} slots, e.g. "
                    f"{t['short_cells'][:5]}.",
                )

    def test_no_stale_keys_outside_the_producer_roster(self):
        for t in self.report["tables"]:
            with self.subTest(family=t["family"], mode=t["mode"]):
                self.assertEqual(
                    t["extra_keys"], [],
                    f"{t['family']}/{t['mode']} carries {len(t['extra_keys'])} "
                    f"keys the producer would not emit, e.g. "
                    f"{t['extra_keys'][:5]} - either a stale roster or a "
                    "key-space drift (canonical vs display).",
                )

    def test_overall_coverage_meets_the_floor(self):
        self.assertGreaterEqual(
            self.report["ratio"], COVERAGE_FLOOR,
            f"precomputed build-order coverage is "
            f"{self.report['covered']}/{self.report['expected']} "
            f"({100.0 * self.report['ratio']:.2f}%), below the {COVERAGE_FLOOR} "
            "floor measured 2026-07-30. Lane B assumes a lookup always hits; "
            "every consumer degrades SILENTLY on a miss.",
        )

    def test_the_universe_is_not_trivially_small(self):
        """A floor over an empty universe passes at zero coverage.

        Guards against a producer constant being emptied (roster fail-soft to a
        10-champ seed, a mode tuple truncated) turning the ratio assertion into
        a tautology.
        """
        self.assertEqual(len(self.report["tables"]), 9)
        self.assertGreaterEqual(
            self.report["expected"], 4000,
            "expected-cell universe collapsed - check full_roster() did not "
            "fail soft to SEED_CHAMPIONS and the mode tuples are intact",
        )


class MeasurementHasTeethTests(unittest.TestCase):
    """Mutating a COPY of a real table must move the numbers.

    Proves the measurement is not vacuous. The producer-side roster stays
    unpatched, so dropping champions from the artifact is a real miss rather
    than a smaller universe.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bo_cov_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.patch = cov.resolve_patch()
        self.real = cov.table_path(cov.FAMILY_COMP, "sr", self.patch)
        # Deliberately NOT a skipTest: the comp/sr table is committed, so an
        # absent one is the regression this whole file exists to catch, not an
        # absent environment capability (tests/test_skip_condition_hygiene.py).
        self.assertTrue(
            self.real.is_file(),
            f"no committed comp/sr table at {self.real} - regen with "
            "python -m core.build_order_precompute --static --mode all "
            "--champions all",
        )
        self.payload = json.loads(self.real.read_text(encoding="utf-8"))

    def _measure_mutated(self, payload: dict) -> dict:
        target = self.tmp / "build_orders_sr.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch.object(cov, "table_path", return_value=target):
            return cov.measure_table(cov.FAMILY_COMP, "sr", self.patch)

    def test_unmutated_copy_is_still_full(self):
        got = self._measure_mutated(self.payload)
        self.assertEqual(got["covered"], got["expected"])
        self.assertEqual(got["missing_champions"], [])

    def test_dropping_champions_is_detected(self):
        payload = json.loads(json.dumps(self.payload))
        dropped = sorted(payload["build_orders"])[:5]
        for champ in dropped:
            del payload["build_orders"][champ]
        got = self._measure_mutated(payload)
        self.assertEqual(sorted(got["missing_champions"]), dropped)
        self.assertEqual(
            got["covered"],
            got["expected"] - len(dropped) * len(cov.expected_axes(cov.FAMILY_COMP)),
        )
        self.assertLess(got["covered"] / got["expected"], COVERAGE_FLOOR)

    def test_emptying_an_order_is_detected(self):
        payload = json.loads(json.dumps(self.payload))
        champ = sorted(payload["build_orders"])[0]
        axis = cov.expected_axes(cov.FAMILY_COMP)[0]
        payload["build_orders"][champ][axis]["order"] = []
        got = self._measure_mutated(payload)
        self.assertEqual(got["empty_cells"], [f"{champ}/{axis}"])
        self.assertEqual(got["covered"], got["expected"] - 1)

    def test_truncating_an_order_is_detected(self):
        payload = json.loads(json.dumps(self.payload))
        champ = sorted(payload["build_orders"])[0]
        axis = cov.expected_axes(cov.FAMILY_COMP)[0]
        payload["build_orders"][champ][axis]["order"] = ["3153", "3111"]
        got = self._measure_mutated(payload)
        self.assertEqual(got["short_cells"], [f"{champ}/{axis}:2"])

    def test_display_keyed_regression_is_detected(self):
        """The canonical family regenerated in the DISPLAY keyspace reads as a
        near-total miss, not as a pass. This is the item-439 failure mode."""
        payload = json.loads(json.dumps(self.payload))
        payload["build_orders"] = {
            "Nunu & Willump": payload["build_orders"]["Nunu"],
        }
        got = self._measure_mutated(payload)
        self.assertEqual(got["covered"], 0)
        self.assertIn("Nunu & Willump", got["extra_keys"])

    def test_absent_table_is_zero_not_skipped(self):
        missing = self.tmp / "does_not_exist.json"
        with mock.patch.object(cov, "table_path", return_value=missing):
            got = cov.measure_table(cov.FAMILY_COMP, "sr", self.patch)
        self.assertFalse(got["exists"])
        self.assertEqual(got["covered"], 0)
        self.assertGreater(got["expected"], 0)
        self.assertEqual(got["error"], "table absent")

    def test_corrupt_table_is_zero_not_an_exception(self):
        target = self.tmp / "corrupt.json"
        target.write_text("{not json", encoding="utf-8")
        with mock.patch.object(cov, "table_path", return_value=target):
            got = cov.measure_table(cov.FAMILY_COMP, "sr", self.patch)
        self.assertEqual(got["covered"], 0)
        self.assertTrue(got["error"].startswith("unreadable"))


class CliTests(unittest.TestCase):
    """The CLI floor flag exits non-zero below the threshold."""

    def test_min_floor_passes_at_current_coverage(self):
        self.assertEqual(cov.main(["--json", "--min", str(COVERAGE_FLOOR)]), 0)

    def test_min_floor_fails_when_unreachable(self):
        self.assertEqual(cov.main(["--json", "--min", "1.5"]), 1)


if __name__ == "__main__":
    unittest.main()
