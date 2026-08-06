"""RM-158 regression: the ARENA laning-scenario table must not be an SR copy.

MEASURED DEFECT (shipped 16.13.1): hashed from the ``"scenarios":`` offset to
EOF, ``laning_scenarios_sr.json`` and ``laning_scenarios_arena.json`` are
SHA-256 identical over 66,961,516 bytes - two real distinct files differing only
in the header ``mode`` value and a ~5-second ``generated_at``. ARAM DOES differ
(its engine branch + its registered gold-income row), so the sweep is capable of
per-mode output; ARENA specifically had ZERO mode-dependent inputs.

MECHANISM the tests below pin:
  * ``core.lead_projection._GOLD_EARNED_PER_MIN`` carried rows for SR + ARAM
    ONLY, so ``gold_income_per_min("ARENA")`` silently returned the SR default
    and every ARENA ``economy`` block (the ONE per-cell field the generator can
    differentiate without a DS engine change) was the SR block.
  * The DS burst/matchup path applies mode modifiers for ARAM only
    (``agents/daemon_slayer/engine.py`` ``_apply_mode_modifiers`` early-returns
    when ``mode != "ARAM"``; ``burst.py`` folds ``aramDamageDealt`` only), so the
    COMBAT half of an itemless ARENA cell equals SR by engine design. That
    residual is documented, not asserted away here - see the ARENA-vs-SR
    scenarios assertion, which only requires the tables to DIFFER, not that
    every field differ.

The generation runs through the real ``main()`` entry point on a TINY scope
(2 champions, one level band) so the whole file is seconds, not a 190 MB regen.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.laning_scenario_precompute as lsp  # noqa: E402
from core import lead_projection as lp  # noqa: E402


class ArenaGoldIncomeRegisteredTests(unittest.TestCase):
    """The income authority must carry an ARENA row (root cause, unit level)."""

    def test_arena_gold_income_is_not_the_sr_default(self) -> None:
        # An UNREGISTERED mode is supposed to fall back to SR (that contract is
        # pinned by tests/test_lead_projection_economy.py for URF). ARENA is a
        # SHIPPED generator mode, so falling back is the defect.
        self.assertNotEqual(
            lp.gold_income_per_min("ARENA"),
            lp.gold_income_per_min("SR"),
            "ARENA has no registered gross-income row, so the laning "
            "precompute's economy block silently reads SR's",
        )

    def test_arena_gold_income_is_positive_and_finite(self) -> None:
        rate = lp.gold_income_per_min("ARENA")
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 10000.0)

    def test_unregistered_mode_still_falls_back_to_sr(self) -> None:
        # Guard the fix against over-reach: adding ARENA must not turn the
        # unknown-mode fallback into something else.
        self.assertEqual(
            lp.gold_income_per_min("TOTALLY_NOT_A_MODE"),
            lp.gold_income_per_min("SR"),
        )


class ModeFidelityGateTests(unittest.TestCase):
    """main() must REFUSE a mode it cannot differentiate, not write an SR copy."""

    def test_every_shipped_generator_mode_has_an_income_row(self) -> None:
        # If this ever fails the gate below starts silently skipping a real
        # mode, which is the opposite failure.
        for key in lsp._MODE_KEYS:
            ds_mode = lsp._DS_MODE_BY_KEY[key]
            with self.subTest(mode=key):
                self.assertTrue(
                    lp.gold_income_is_registered(ds_mode),
                    f"generator mode {key!r} ({ds_mode}) has no gross-income row",
                )

    def test_unregistered_mode_is_skipped_and_exits_nonzero(self) -> None:
        rows = {k: v for k, v in lp._GOLD_EARNED_PER_MIN.items() if k != "ARENA"}
        with mock.patch.object(lp, "_GOLD_EARNED_PER_MIN", rows):
            # Assert the mutation ACTUALLY applied before trusting the result -
            # a patch that silently no-ops would make this test vacuous.
            self.assertFalse(lp.gold_income_is_registered("ARENA"))
            with tempfile.TemporaryDirectory() as tmp:
                rc = lsp.main([
                    "--mode", "arena",
                    "--champions", "Garen",
                    "--bands", "L2",
                    "--out", tmp,
                ])
                self.assertEqual(rc, 2)
                self.assertFalse(
                    (Path(tmp) / "laning_scenarios_arena.json").exists(),
                    "an undifferentiable mode must not be written at all",
                )
        # And the patch is gone: the real ARENA row is back.
        self.assertTrue(lp.gold_income_is_registered("ARENA"))

    def test_registered_mode_still_writes_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc = lsp.main([
                "--mode", "arena",
                "--champions", "Garen",
                "--bands", "L2",
                "--out", tmp,
            ])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp) / "laning_scenarios_arena.json").is_file())


class ArenaEconomyCellTests(unittest.TestCase):
    """economy_cell is pure - it must honor the ARENA mode without the engine."""

    def test_arena_economy_cell_differs_from_sr(self) -> None:
        for band in ("L2", "L6", "L11"):
            with self.subTest(band=band):
                sr = lsp.economy_cell(band, "full", mode="SR")
                arena = lsp.economy_cell(band, "full", mode="ARENA")
                self.assertNotEqual(
                    sr, arena,
                    f"ARENA economy cell at {band} is byte-identical to SR",
                )

    def test_arena_economy_cell_gold_exceeds_sr(self) -> None:
        sr = lsp.economy_cell("L6", "full", mode="SR")
        arena = lsp.economy_cell("L6", "full", mode="ARENA")
        self.assertGreater(arena["gold_at_band"], sr["gold_at_band"])


class GeneratedTableModeFidelityTests(unittest.TestCase):
    """End-to-end through main(): three modes, three DISTINCT scenario blobs.

    This is the characterization of the shipped-artifact defect. Scope is tiny
    (2 champions x 1 band) - the point is per-mode DIVERGENCE, not coverage.
    """

    payloads: dict = {}
    tmpdir: tempfile.TemporaryDirectory | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.TemporaryDirectory()
        rc = lsp.main([
            "--mode", "all",
            "--champions", "Garen,Annie",
            "--bands", "L2",
            "--out", cls.tmpdir.name,
        ])
        if rc != 0:
            cls.tmpdir.cleanup()
            cls.tmpdir = None
            raise AssertionError(f"laning precompute main() returned {rc}")
        out = Path(cls.tmpdir.name)
        for key in ("sr", "aram", "arena"):
            path = out / f"laning_scenarios_{key}.json"
            cls.payloads[key] = json.loads(path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.tmpdir is not None:
            cls.tmpdir.cleanup()
            cls.tmpdir = None

    def _blob(self, key: str) -> str:
        return json.dumps(self.payloads[key]["scenarios"], sort_keys=True)

    def test_every_mode_wrote_a_non_empty_table(self) -> None:
        for key in ("sr", "aram", "arena"):
            with self.subTest(mode=key):
                self.assertEqual(self.payloads[key]["mode"], key)
                self.assertTrue(self.payloads[key]["scenarios"])
                self.assertGreater(lsp._count_leaves(self.payloads[key]), 0)

    def test_arena_scenarios_are_not_an_sr_copy(self) -> None:
        self.assertNotEqual(
            self._blob("arena"), self._blob("sr"),
            "ARENA scenarios blob is byte-identical to SR - the shipped "
            "16.13.1 RM-158 defect",
        )

    def test_arena_header_income_is_not_srs(self) -> None:
        sr_income = self.payloads["sr"]["dimensions"]["economy"]["income_per_min"]
        arena_income = (
            self.payloads["arena"]["dimensions"]["economy"]["income_per_min"]
        )
        self.assertNotEqual(arena_income, sr_income)

    def test_aram_scenarios_are_not_an_sr_copy(self) -> None:
        # Control: ARAM already diverged before the fix. If this ever fails the
        # whole mode-threading story is broken, not just ARENA.
        self.assertNotEqual(self._blob("aram"), self._blob("sr"))

    def test_arena_scenarios_are_not_an_aram_copy(self) -> None:
        # The fix derives ARENA's income from the ARAM profile, so guard that
        # ARENA does not simply become the ARAM table either.
        self.assertNotEqual(self._blob("arena"), self._blob("aram"))

    def test_all_three_modes_are_pairwise_distinct(self) -> None:
        blobs = {key: self._blob(key) for key in ("sr", "aram", "arena")}
        self.assertEqual(
            len(set(blobs.values())), 3,
            f"expected 3 distinct scenario blobs, got "
            f"{len(set(blobs.values()))}",
        )


if __name__ == "__main__":
    unittest.main()
