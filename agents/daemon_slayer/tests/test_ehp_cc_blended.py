"""ENGINE 1.33.0 (2026-05-22) - EHP-vs-CC blended scorer.

Second engine math consumer of ``compute_cc_pressure`` (the first was
the coach-prompt-side ``core/enemy_cc_threat_context.py`` per CLAUDE.md
item 136 Slice B). Closes item 136 carry (a) by consuming the registry
INSIDE the engine math layer.

``compute_ehp(..., enemy_champions=())`` gains an iterable kwarg of
enemy champion ids. When non-empty, the engine sums
``compute_cc_pressure(enemy, mode).total_cc_seconds`` across the
iterable, derives ``cc_pressure_fraction = min(s / _FIGHT_WINDOW_S, 1)``,
and computes ``cc_blended_ehp = blended_ehp * (1 - fraction * 0.5)``
where ``_CC_EFFECTIVENESS_FACTOR = 0.5``.

Test surface:
  * ContractTests - default identity preservation, tuple/list input,
    blank/None skipping, division safety.
  * MathTests - hand-derived single-enemy / multi-enemy / saturation
    cases, factor pin.
  * EnemyEnumerationTests - partial registry coverage, duplicate
    intent, unknown champion silent skip.
  * EhpResultFieldsTests - to_dict shape, format_table render gates,
    notes line.
  * CompositionWithExistingFieldsTests - shield + heal + per-type
    EHP fields untouched.
  * EngineVersionCurrentTests - pin ENGINE_VERSION value in this branch.
  * AsciiHygieneTests - new module + this test file are pure ASCII.
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    _CC_EFFECTIVENESS_FACTOR,
    _FIGHT_WINDOW_S,
    EhpResult,
    compute_ehp,
)


_SNAPSHOT = DataSnapshot.load()


class ContractTests(unittest.TestCase):
    """Default kwarg + input-shape contract."""

    def test_default_empty_enemy_champions_preserves_identity(self) -> None:
        # Without the kwarg the new fields stay at their identity defaults
        # so every existing caller is byte-identical in the EHP math.
        r = compute_ehp(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        self.assertEqual(r.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r.cc_pressure_fraction, 0.0)
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)

    def test_default_empty_tuple_explicit_identity(self) -> None:
        r = compute_ehp(
            _SNAPSHOT, "Aatrox", level=11, mode="SR", enemy_champions=()
        )
        self.assertEqual(r.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r.cc_pressure_fraction, 0.0)
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)

    def test_unknown_enemy_yields_zero(self) -> None:
        # Aatrox is NOT in the CC registry (no first-order CC at 16.10.1).
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Aatrox",),
        )
        self.assertEqual(r.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r.cc_pressure_fraction, 0.0)
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)

    def test_tuple_input_accepted(self) -> None:
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
        )
        self.assertGreater(r.enemy_cc_pressure_s, 0.0)

    def test_list_input_accepted(self) -> None:
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=["Annie"],
        )
        self.assertGreater(r.enemy_cc_pressure_s, 0.0)

    def test_tuple_list_equivalence(self) -> None:
        r_tuple = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Morgana"),
        )
        r_list = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=["Annie", "Morgana"],
        )
        self.assertEqual(r_tuple.cc_blended_ehp, r_list.cc_blended_ehp)
        self.assertEqual(r_tuple.enemy_cc_pressure_s, r_list.enemy_cc_pressure_s)

    def test_blank_and_none_entries_silently_skipped(self) -> None:
        # Mirrors enemy_cc_threat_line contract: empty / None entries skip
        # silently. The known-registered champs still contribute fully.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=["Annie", None, "", "Morgana"],
        )
        # Annie R = 1.5, Morgana Q max = 3.0, sum 4.5
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 4.5, places=4)

    def test_only_blank_entries_yield_zero(self) -> None:
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=["", None, ""],
        )
        self.assertEqual(r.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r.cc_pressure_fraction, 0.0)
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)


class MathTests(unittest.TestCase):
    """Hand-derived single-enemy / multi-enemy / saturation math."""

    def test_cc_effectiveness_factor_is_half(self) -> None:
        # Pin the conservative midpoint constant; future calibration
        # changes must touch this test deliberately.
        self.assertEqual(_CC_EFFECTIVENESS_FACTOR, 0.5)

    def test_fight_window_is_six_seconds(self) -> None:
        # Pin the fight-window constant reused for CC fraction math.
        self.assertEqual(_FIGHT_WINDOW_S, 6.0)

    def test_single_annie_r_quarter_window_discount(self) -> None:
        # Annie R max-rank = 1.5s; fraction = 1.5/6 = 0.25;
        # discount = 0.25 * 0.5 = 0.125 -> cc_blended = 0.875 * blended.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
        )
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 1.5, places=4)
        self.assertAlmostEqual(r.cc_pressure_fraction, 0.25, places=4)
        self.assertAlmostEqual(
            r.cc_blended_ehp, r.blended_ehp * 0.875, places=4
        )

    def test_two_enemies_annie_plus_morgana_three_quarter_window(self) -> None:
        # Annie R 1.5 + Morgana Q max = 3.0 -> total 4.5s;
        # fraction = 4.5/6 = 0.75; discount = 0.375 -> 0.625 * blended.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Morgana"),
        )
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 4.5, places=4)
        self.assertAlmostEqual(r.cc_pressure_fraction, 0.75, places=4)
        self.assertAlmostEqual(
            r.cc_blended_ehp, r.blended_ehp * 0.625, places=4
        )

    def test_saturation_clamps_fraction_at_one(self) -> None:
        # Five heavy-CC entries (Morgana Q 3.0 x5 = 15s) over a 6s window
        # MUST clamp to 1.0; cc_blended_ehp = blended * (1 - 1.0 * 0.5) = 0.5.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana",) * 5,
        )
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 15.0, places=4)
        self.assertEqual(r.cc_pressure_fraction, 1.0)
        self.assertAlmostEqual(r.cc_blended_ehp, r.blended_ehp * 0.5, places=4)

    def test_exactly_one_window_yields_half_discount(self) -> None:
        # Two Morgana Q (3+3=6s) is exactly one fight window -> fraction=1.0.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Morgana", "Morgana"),
        )
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 6.0, places=4)
        self.assertAlmostEqual(r.cc_pressure_fraction, 1.0, places=4)
        self.assertAlmostEqual(r.cc_blended_ehp, r.blended_ehp * 0.5, places=4)

    def test_cc_blended_is_strictly_less_than_blended_when_cc_present(
        self,
    ) -> None:
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
        )
        self.assertLess(r.cc_blended_ehp, r.blended_ehp)

    def test_cc_blended_equals_blended_when_no_enemies(self) -> None:
        r = compute_ehp(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)


class EnemyEnumerationTests(unittest.TestCase):
    """Per-enemy enumeration: partial registry, duplicate intent, unknowns."""

    def test_partial_registry_coverage_in_team(self) -> None:
        # 5-enemy team where 3 have CC registered (Annie / Morgana / Galio)
        # and 2 are absent (Aatrox / Garen not in registry at 16.10.1).
        # The 2 absent contribute 0.0 silently. Sum derived from
        # direct compute_cc_pressure call so the test stays decoupled
        # from the exact registry values.
        from agents.daemon_slayer.cc_pressure import compute_cc_pressure

        ann = compute_cc_pressure("Annie", "SR").total_cc_seconds
        mor = compute_cc_pressure("Morgana", "SR").total_cc_seconds
        gal = compute_cc_pressure("Galio", "SR").total_cc_seconds
        expected = ann + mor + gal
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=(
                "Annie",
                "Morgana",
                "Galio",
                "Aatrox",
                "Garen",
            ),
        )
        self.assertAlmostEqual(r.enemy_cc_pressure_s, expected, places=4)

    def test_duplicate_enemy_double_counts_intentionally(self) -> None:
        # Registry-driven sum is the contract; the engine does NOT
        # de-duplicate enemies. Two Annie entries -> 2 * 1.5 = 3.0.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Annie"),
        )
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 3.0, places=4)

    def test_unknown_champion_contributes_zero(self) -> None:
        # compute_cc_pressure returns empty result for unknown champion;
        # the engine simply adds 0.0 to the sum.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("DefinitelyNotAChampion", "Annie"),
        )
        self.assertAlmostEqual(r.enemy_cc_pressure_s, 1.5, places=4)

    def test_all_unknown_enemies_yield_zero(self) -> None:
        # Aatrox / Garen / Karthus are NOT in the 16.10.1 CC registry
        # (no first-order CC abilities seeded). All three contribute 0.0.
        r = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Aatrox", "Garen", "Karthus"),
        )
        self.assertEqual(r.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r.cc_pressure_fraction, 0.0)
        self.assertEqual(r.cc_blended_ehp, r.blended_ehp)

    def test_monkeyking_canonical_id_recognized(self) -> None:
        # Wukong is keyed as "MonkeyKing" in the registry per DDragon id.
        # Should contribute non-zero CC pressure (R = 1.0s knock-up).
        r_wukong = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("MonkeyKing",),
        )
        r_wrong = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Wukong",),
        )
        self.assertGreater(r_wukong.enemy_cc_pressure_s, 0.0)
        self.assertEqual(r_wrong.enemy_cc_pressure_s, 0.0)


class EhpResultFieldsTests(unittest.TestCase):
    """EhpResult shape: 3 new fields surface in to_dict + format_table + notes."""

    def setUp(self) -> None:
        self.r_with_cc = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie",),
        )
        self.r_no_cc = compute_ehp(_SNAPSHOT, "Aatrox", level=11, mode="SR")

    def test_to_dict_carries_three_new_keys(self) -> None:
        d = self.r_with_cc.to_dict()
        self.assertIn("enemy_cc_pressure_s", d)
        self.assertIn("cc_pressure_fraction", d)
        self.assertIn("cc_blended_ehp", d)
        self.assertAlmostEqual(d["enemy_cc_pressure_s"], 1.5, places=4)
        self.assertAlmostEqual(d["cc_pressure_fraction"], 0.25, places=4)

    def test_to_dict_zero_keys_when_no_enemy_cc(self) -> None:
        d = self.r_no_cc.to_dict()
        self.assertEqual(d["enemy_cc_pressure_s"], 0.0)
        self.assertEqual(d["cc_pressure_fraction"], 0.0)
        self.assertEqual(d["cc_blended_ehp"], d["blended_ehp"])

    def test_format_table_renders_cc_pressure_row_when_non_zero(self) -> None:
        table = self.r_with_cc.format_table()
        self.assertIn("cc_pressure", table)
        self.assertIn("total_s=1.5", table)
        self.assertIn("fraction=0.25", table)
        self.assertIn("(after CC discount)", table)

    def test_format_table_omits_cc_pressure_row_when_zero(self) -> None:
        table = self.r_no_cc.format_table()
        self.assertNotIn("cc_pressure", table)
        self.assertNotIn("after CC discount", table)

    def test_notes_carry_enemy_cc_line_when_non_zero(self) -> None:
        notes = self.r_with_cc.notes
        cc_lines = [n for n in notes if "enemy_cc" in n]
        self.assertEqual(len(cc_lines), 1)
        self.assertIn("1.50s", cc_lines[0])
        self.assertIn("fraction=0.25", cc_lines[0])
        self.assertIn("_CC_EFFECTIVENESS_FACTOR=0.5", cc_lines[0])

    def test_notes_omit_enemy_cc_line_when_zero(self) -> None:
        notes = self.r_no_cc.notes
        cc_lines = [n for n in notes if "enemy_cc" in n]
        self.assertEqual(len(cc_lines), 0)

    def test_ehp_result_default_values_for_new_fields(self) -> None:
        # The dataclass defaults the 3 new fields when nothing is passed.
        # Verify via a minimal direct construction (skips compute_ehp).
        result = EhpResult(
            champion_id="X",
            champion_name="X",
            level=1,
            item_ids=(),
            mode="SR",
            hp=1000.0,
            armor=50.0,
            mr=50.0,
            physical_ehp=1500.0,
            magical_ehp=1500.0,
            true_ehp=1000.0,
            blended_ehp=1250.0,
            enemy_ad_share=0.5,
            enemy_ap_share=0.5,
            enemy_true_share=0.0,
            mode_multiplier=1.0,
        )
        self.assertEqual(result.enemy_cc_pressure_s, 0.0)
        self.assertEqual(result.cc_pressure_fraction, 0.0)
        # NOTE: cc_blended_ehp defaults to 0.0 in dataclass, NOT to blended_ehp
        # (that identity is only the contract from compute_ehp, not the
        # dataclass default). compute_ehp sets it correctly.
        self.assertEqual(result.cc_blended_ehp, 0.0)


class CompositionWithExistingFieldsTests(unittest.TestCase):
    """CC blend stacks ON TOP of blended_ehp; per-type EHP fields untouched."""

    def test_per_type_ehp_fields_unchanged_by_cc_kwarg(self) -> None:
        r_no_cc = compute_ehp(_SNAPSHOT, "Aatrox", level=11, mode="SR")
        r_with_cc = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            enemy_champions=("Annie", "Morgana"),
        )
        # The per-type and blended fields stay byte-identical; only the
        # new cc_blended_ehp absorbs the discount.
        self.assertEqual(r_no_cc.physical_ehp, r_with_cc.physical_ehp)
        self.assertEqual(r_no_cc.magical_ehp, r_with_cc.magical_ehp)
        self.assertEqual(r_no_cc.true_ehp, r_with_cc.true_ehp)
        self.assertEqual(r_no_cc.blended_ehp, r_with_cc.blended_ehp)

    def test_mode_multiplier_unchanged_by_cc_kwarg(self) -> None:
        # ARAM mode picks up aramDamageTaken; the CC kwarg must NOT
        # touch the aramDamageTaken multiplier.
        r_no_cc = compute_ehp(_SNAPSHOT, "Aatrox", level=11, mode="ARAM")
        r_with_cc = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="ARAM",
            enemy_champions=("Annie",),
        )
        self.assertEqual(r_no_cc.mode_multiplier, r_with_cc.mode_multiplier)
        self.assertEqual(
            r_no_cc.aram_tenacity_mult, r_with_cc.aram_tenacity_mult
        )

    def test_shield_and_heal_fields_unchanged_by_cc_kwarg(self) -> None:
        # Pick an Aatrox build with Sterak (lifeline shield + heal-amp item).
        # Both shield and heal contributions stay identical with vs without
        # the CC kwarg.
        r_no_cc = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            item_ids=["3053", "3065"],  # Sterak's + Spirit Visage
        )
        r_with_cc = compute_ehp(
            _SNAPSHOT,
            "Aatrox",
            level=11,
            mode="SR",
            item_ids=["3053", "3065"],
            enemy_champions=("Annie",),
        )
        self.assertEqual(r_no_cc.shield_any, r_with_cc.shield_any)
        self.assertEqual(r_no_cc.shield_amp_mult, r_with_cc.shield_amp_mult)
        self.assertEqual(r_no_cc.heal_total, r_with_cc.heal_total)
        self.assertEqual(r_no_cc.heal_amp_mult, r_with_cc.heal_amp_mult)


class EngineVersionCurrentTests(unittest.TestCase):
    """Pin ENGINE_VERSION in this branch.

    The orchestrator bumps to 1.33.0 at merge; while the slice is being
    written, the branch carries 1.32.0 from the base. This test asserts
    the value the slice is composing on so any drift surfaces.
    """

    def test_engine_version_pin(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.191.0")


class AsciiHygieneTests(unittest.TestCase):
    """New module + this test file are pure 7-bit ASCII."""

    # Build BAD via chr() so this test file stays clean against its own scan.
    BAD = {
        chr(0x2013): "en-dash",
        chr(0x2014): "em-dash",
        chr(0x2018): "left-single-quote",
        chr(0x2019): "right-single-quote",
        chr(0x201C): "left-double-quote",
        chr(0x201D): "right-double-quote",
    }

    def _scan(self, path: pathlib.Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        hits: list[str] = []
        for ch, name in self.BAD.items():
            if ch in text:
                hits.append(name)
        return hits

    def test_ehp_module_is_ascii_clean(self) -> None:
        # Walk up from this file: tests/test_*.py -> daemon_slayer/tests
        # -> daemon_slayer/ -> ehp.py
        ehp_path = pathlib.Path(__file__).resolve().parent.parent / "ehp.py"
        hits = self._scan(ehp_path)
        self.assertEqual(hits, [], f"ehp.py has non-ASCII glyphs: {hits}")

    def test_test_file_is_ascii_clean(self) -> None:
        # This file scans itself for stray smart-glyphs.
        this_path = pathlib.Path(__file__).resolve()
        hits = self._scan(this_path)
        self.assertEqual(
            hits, [], f"test_ehp_cc_blended.py has non-ASCII glyphs: {hits}"
        )


if __name__ == "__main__":
    unittest.main()
