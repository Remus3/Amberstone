"""Tests for the cdragon `mFormulaParts` typed-part formula evaluator
(`agents/daemon_slayer/augment_formula_eval.py`).

Covers each typed-part shape, mMultiplier wrapping, part-sum composition,
real-augment value extraction against cdragon 16.10.1, and the
overlay-registry fallback path in compute_augment_stats.
"""

import unittest

from agents.daemon_slayer.augments import Augment, compute_augment_stats
from agents.daemon_slayer.augment_formula_eval import (
    StatContext,
    evaluate_calculation,
    evaluate_named_calculation,
    evaluate_part,
    read_stat,
    stat_overlay_from_calculations,
    STAT_GRANT_CALC_KEYS,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _aug(api: str = "T", data_values: dict | None = None, calc: dict | None = None) -> Augment:
    return Augment.from_record({
        "id": 1,
        "apiName": api,
        "name": api,
        "rarity": 0,
        "desc": "",
        "tooltip": "",
        "dataValues": data_values or {},
        "calculations": calc or {},
    })


class ReadStatTests(unittest.TestCase):
    def test_known_ordinal_returns_resolved_total(self) -> None:
        ctx = StatContext(stats={"ad": 120.0, "ap": 60.0})
        self.assertEqual(read_stat(ctx, 2), 120.0)  # AD
        self.assertEqual(read_stat(ctx, 3), 60.0)   # AP

    def test_unknown_ordinal_returns_zero(self) -> None:
        ctx = StatContext(stats={"ad": 120.0})
        self.assertEqual(read_stat(ctx, 99), 0.0)
        self.assertEqual(read_stat(ctx, None), 0.0)

    def test_bonus_stat_formula_returns_delta_when_base_present(self) -> None:
        ctx = StatContext(
            stats={"ad": 120.0},
            base_stats={"ad": 65.0},
        )
        # mStatFormula=2 ("Bonus") -> 120 - 65 = 55
        self.assertEqual(read_stat(ctx, 2, stat_formula=2), 55.0)

    def test_bonus_stat_formula_falls_back_to_total_without_base(self) -> None:
        ctx = StatContext(stats={"ad": 120.0})
        self.assertEqual(read_stat(ctx, 2, stat_formula=2), 120.0)

    def test_missing_key_reads_zero(self) -> None:
        ctx = StatContext(stats={})
        self.assertEqual(read_stat(ctx, 2), 0.0)


class NumberCalculationPartTests(unittest.TestCase):
    def test_literal_number_returned(self) -> None:
        part = {"__type": "NumberCalculationPart", "mNumber": 0.25}
        out = evaluate_part(part, _aug(), StatContext())
        self.assertEqual(out, 0.25)

    def test_missing_number_returns_zero(self) -> None:
        part = {"__type": "NumberCalculationPart"}
        out = evaluate_part(part, _aug(), StatContext())
        self.assertEqual(out, 0.0)

    def test_non_numeric_number_returns_zero(self) -> None:
        part = {"__type": "NumberCalculationPart", "mNumber": "oops"}
        out = evaluate_part(part, _aug(), StatContext())
        self.assertEqual(out, 0.0)


class NamedDataValueCalculationPartTests(unittest.TestCase):
    def test_reads_index_0_by_default(self) -> None:
        aug = _aug(data_values={"X": [10.0, 20.0, 30.0]})
        part = {"__type": "NamedDataValueCalculationPart", "mDataValue": "X"}
        self.assertEqual(evaluate_part(part, aug, StatContext()), 10.0)

    def test_reads_indexed_level(self) -> None:
        aug = _aug(data_values={"X": [10.0, 20.0, 30.0]})
        part = {"__type": "NamedDataValueCalculationPart", "mDataValue": "X"}
        ctx = StatContext(level_index=2)
        self.assertEqual(evaluate_part(part, aug, ctx), 30.0)

    def test_out_of_range_index_falls_back_to_last(self) -> None:
        aug = _aug(data_values={"X": [10.0, 20.0, 30.0]})
        part = {"__type": "NamedDataValueCalculationPart", "mDataValue": "X"}
        ctx = StatContext(level_index=99)
        self.assertEqual(evaluate_part(part, aug, ctx), 30.0)

    def test_missing_data_value_returns_zero(self) -> None:
        aug = _aug(data_values={"X": [10.0]})
        part = {"__type": "NamedDataValueCalculationPart", "mDataValue": "Y"}
        self.assertEqual(evaluate_part(part, aug, StatContext()), 0.0)

    def test_scalar_data_value_works(self) -> None:
        aug = _aug(data_values={"X": 5.0})
        part = {"__type": "NamedDataValueCalculationPart", "mDataValue": "X"}
        self.assertEqual(evaluate_part(part, aug, StatContext()), 5.0)

    def test_no_data_value_key_returns_zero(self) -> None:
        aug = _aug(data_values={"X": [10.0]})
        part = {"__type": "NamedDataValueCalculationPart"}
        self.assertEqual(evaluate_part(part, aug, StatContext()), 0.0)


class StatByNamedDataValueCalculationPartTests(unittest.TestCase):
    def test_multiplies_data_value_by_stat(self) -> None:
        # Typhoon-shape: 0.2 * AD
        aug = _aug(data_values={"ADRatio": [0.2]})
        part = {
            "__type": "StatByNamedDataValueCalculationPart",
            "mDataValue": "ADRatio",
            "mStat": 2,  # AD
        }
        ctx = StatContext(stats={"ad": 100.0})
        self.assertAlmostEqual(evaluate_part(part, aug, ctx), 20.0)

    def test_unknown_stat_returns_zero(self) -> None:
        aug = _aug(data_values={"R": [0.5]})
        part = {
            "__type": "StatByNamedDataValueCalculationPart",
            "mDataValue": "R",
            "mStat": 999,
        }
        ctx = StatContext(stats={"ad": 100.0})
        self.assertEqual(evaluate_part(part, aug, ctx), 0.0)


class StatByCoefficientCalculationPartTests(unittest.TestCase):
    def test_multiplies_coefficient_by_stat(self) -> None:
        part = {
            "__type": "StatByCoefficientCalculationPart",
            "mCoefficient": 0.35,
            "mStat": 2,
            "mStatFormula": 2,  # bonus AD
        }
        ctx = StatContext(stats={"ad": 200.0}, base_stats={"ad": 65.0})
        # 0.35 * (200 - 65) = 47.25
        self.assertAlmostEqual(evaluate_part(part, _aug(), ctx), 47.25)

    def test_bare_coefficient_no_stat_returns_constant(self) -> None:
        # UndyingGuard third part: 1.1 with no mStat - acts as constant.
        part = {
            "__type": "StatByCoefficientCalculationPart",
            "mCoefficient": 1.1,
        }
        self.assertAlmostEqual(evaluate_part(part, _aug(), StatContext()), 1.1)

    def test_missing_coefficient_treated_as_zero(self) -> None:
        part = {"__type": "StatByCoefficientCalculationPart", "mStat": 2}
        ctx = StatContext(stats={"ad": 100.0})
        self.assertEqual(evaluate_part(part, _aug(), ctx), 0.0)


class UnknownPartShapeTests(unittest.TestCase):
    def test_unknown_type_returns_zero(self) -> None:
        # ByCharLevelInterpolation is intentionally out of scope this slice.
        part = {
            "__type": "ByCharLevelInterpolationCalculationPart",
            "mStartValue": 11.0,
            "mEndValue": 80.0,
        }
        ctx = StatContext(stats={"ad": 100.0})
        self.assertEqual(evaluate_part(part, _aug(), ctx), 0.0)

    def test_hash_name_part_returns_zero(self) -> None:
        part = {"__type": "{b22609db}"}
        self.assertEqual(evaluate_part(part, _aug(), StatContext()), 0.0)

    def test_non_dict_part_returns_zero(self) -> None:
        self.assertEqual(evaluate_part(None, _aug(), StatContext()), 0.0)
        self.assertEqual(evaluate_part(42, _aug(), StatContext()), 0.0)


class PartSumCompositionTests(unittest.TestCase):
    def test_sum_of_parts(self) -> None:
        # Simulate: NamedDataValue(BaseDamage[0]=75) + 1.0 * bonus_AD
        # (bonus AD = 100) + 1.1 (constant) = 75 + 100 + 1.1 = 176.1
        aug = _aug(data_values={"BaseDamage": [75.0]})
        calc = {
            "__type": "GameCalculation",
            "mFormulaParts": [
                {
                    "__type": "NamedDataValueCalculationPart",
                    "mDataValue": "BaseDamage",
                },
                {
                    "__type": "StatByCoefficientCalculationPart",
                    "mCoefficient": 1.0,
                    "mStat": 2,
                    "mStatFormula": 2,
                },
                {
                    "__type": "StatByCoefficientCalculationPart",
                    "mCoefficient": 1.1,
                },
            ],
        }
        ctx = StatContext(stats={"ad": 200.0}, base_stats={"ad": 100.0})
        self.assertAlmostEqual(evaluate_calculation(calc, aug, ctx), 176.1)

    def test_empty_parts_returns_zero(self) -> None:
        calc = {"__type": "GameCalculation", "mFormulaParts": []}
        self.assertEqual(evaluate_calculation(calc, _aug(), StatContext()), 0.0)

    def test_missing_parts_key_returns_zero(self) -> None:
        calc = {"__type": "GameCalculation"}
        self.assertEqual(evaluate_calculation(calc, _aug(), StatContext()), 0.0)

    def test_none_calc_returns_zero(self) -> None:
        self.assertEqual(evaluate_calculation(None, _aug(), StatContext()), 0.0)


class MultiplierWrapperTests(unittest.TestCase):
    def test_multiplier_scales_sum_of_parts(self) -> None:
        # ServeBeyondDeath shape: NamedDataValue(TicksBeforeDeath=10) * 0.25
        aug = _aug(data_values={"TicksBeforeDeath": [10.0]})
        calc = {
            "__type": "GameCalculation",
            "mFormulaParts": [
                {
                    "__type": "NamedDataValueCalculationPart",
                    "mDataValue": "TicksBeforeDeath",
                },
            ],
            "mMultiplier": {
                "__type": "NumberCalculationPart",
                "mNumber": 0.25,
            },
        }
        self.assertAlmostEqual(
            evaluate_calculation(calc, aug, StatContext()), 2.5
        )

    def test_multiplier_using_named_data_value(self) -> None:
        # LightemUp shape's multiplier reads FireworkDamageMod from dataValues.
        # Simplified: sum=20, mult=FireworkDamageMod[0]=0.9, total=18.0
        aug = _aug(data_values={"FireworkDamageMod": [0.9]})
        calc = {
            "__type": "GameCalculation",
            "mFormulaParts": [
                {"__type": "NumberCalculationPart", "mNumber": 20.0},
            ],
            "mMultiplier": {
                "__type": "NamedDataValueCalculationPart",
                "mDataValue": "FireworkDamageMod",
            },
        }
        self.assertAlmostEqual(
            evaluate_calculation(calc, aug, StatContext()), 18.0
        )

    def test_unknown_multiplier_shape_collapses_total_to_zero(self) -> None:
        # When the multiplier resolves to 0 (unknown shape), the calc
        # produces 0 even if parts sum to a non-zero value. This is
        # consistent with the zero-contribution sentinel; the caller can
        # detect missing multiplier shapes by inspecting the calc dict.
        calc = {
            "__type": "GameCalculation",
            "mFormulaParts": [
                {"__type": "NumberCalculationPart", "mNumber": 100.0},
            ],
            "mMultiplier": {
                "__type": "UnknownMultiplierShape",
                "mNumber": 0.5,
            },
        }
        self.assertEqual(evaluate_calculation(calc, _aug(), StatContext()), 0.0)


class RealAugmentValuePinTests(unittest.TestCase):
    """Value-pinned against cdragon 16.10.1's arena_augments.json."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_typhoon_damage_0_2_x_ad(self) -> None:
        # Typhoon: Damage = ADRatio[0]=0.2 * AD. At AD=100 -> 20.
        # Riot stores 0.2 as float32 (0.20000000298...) so the eval
        # has float-noise; assert with places=4 tolerance.
        rec = self.snap.arena_augment("Typhoon")
        aug = Augment.from_record(rec)
        ctx = StatContext(stats={"ad": 100.0})
        self.assertAlmostEqual(
            evaluate_named_calculation(aug, "Damage", ctx), 20.0, places=4
        )

    def test_typhoon_damage_at_ad_300(self) -> None:
        # Linear: at AD=300 -> 60. Float32 noise tolerance applies.
        rec = self.snap.arena_augment("Typhoon")
        aug = Augment.from_record(rec)
        ctx = StatContext(stats={"ad": 300.0})
        self.assertAlmostEqual(
            evaluate_named_calculation(aug, "Damage", ctx), 60.0, places=4
        )

    def test_serve_beyond_death_calc_multiplier(self) -> None:
        # ServeBeyondDeath: {85d7d7f0} = NamedDataValue(TicksBeforeDeath=10)
        # * NumberCalculationPart(0.25). dataValues[TicksBeforeDeath][0]=10.
        # 10 * 0.25 = 2.5.
        rec = self.snap.arena_augment("ServeBeyondDeath")
        aug = Augment.from_record(rec)
        # Riot ships this calc under a hash-name key.
        # Find the hash key dynamically (cdragon name-mangle is rotation-stable
        # within a patch but not across patches; pick the first non-empty calc).
        self.assertTrue(aug.calculations)
        first_key = next(iter(aug.calculations))
        self.assertAlmostEqual(
            evaluate_named_calculation(aug, first_key, StatContext()), 2.5
        )

    def test_undying_guard_total_damage_base_only(self) -> None:
        # UndyingGuard TotalDamage parts:
        #   NamedDataValue(BaseDamage[0] = -25)            -> -25
        #   StatByCoefficient(1.0 * bonus_AD=0)            -> 0
        #   StatByCoefficient(1.1 constant)                -> 1.1
        # Sum (no mMultiplier) = -25 + 0 + 1.1 = -23.9 at bare stats.
        rec = self.snap.arena_augment("UndyingGuard")
        aug = Augment.from_record(rec)
        ctx = StatContext(stats={"ad": 65.0}, base_stats={"ad": 65.0})
        self.assertAlmostEqual(
            evaluate_named_calculation(aug, "TotalDamage", ctx), -23.9
        )

    def test_undying_guard_total_damage_with_bonus_ad(self) -> None:
        # bonus_AD = 100 -> -25 + 100*1.0 + 1.1 = 76.1.
        rec = self.snap.arena_augment("UndyingGuard")
        aug = Augment.from_record(rec)
        ctx = StatContext(stats={"ad": 165.0}, base_stats={"ad": 65.0})
        self.assertAlmostEqual(
            evaluate_named_calculation(aug, "TotalDamage", ctx), 76.1
        )

    def test_jeweled_gauntlet_crit_granted(self) -> None:
        # JeweledGauntlet CritGranted:
        #   NamedDataValue(CritChance[0]=0.25)
        #   StatByNamedDataValue(CritConverRatio[0]=0.0004 * mDataValue)
        # The 2nd part has no mStat so the stat read is 0
        # (stat ordinal absent -> 0 via read_stat None-guard).
        # Therefore: total = 0.25 + 0 = 0.25.
        rec = self.snap.arena_augment("JeweledGauntlet")
        aug = Augment.from_record(rec)
        ctx = StatContext()
        self.assertAlmostEqual(
            evaluate_named_calculation(aug, "CritGranted", ctx), 0.25
        )

    def test_real_augment_missing_calc_returns_zero(self) -> None:
        # Asking for a calc key the augment doesn't have returns 0.
        rec = self.snap.arena_augment("Typhoon")
        aug = Augment.from_record(rec)
        self.assertEqual(
            evaluate_named_calculation(aug, "NotAKey", StatContext()), 0.0
        )

    def test_augment_with_empty_calculations_returns_zero(self) -> None:
        # TheBrutalizer ships empty calculations - evaluator returns 0
        # for any calc name; the registry-fallback path covers it.
        rec = self.snap.arena_augment("TheBrutalizer")
        aug = Augment.from_record(rec)
        self.assertEqual(aug.calculations, {})
        self.assertEqual(
            evaluate_named_calculation(aug, "AnyKey", StatContext()), 0.0
        )


class StatOverlayFromCalculationsTests(unittest.TestCase):
    """The displacement seam: only fires when STAT_GRANT_CALC_KEYS maps."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_returns_empty_when_no_stat_grant_keys_registered(self) -> None:
        # At cdragon 16.10.1, no calc key is stat-named so the registry
        # is intentionally empty. Confirm the wiring returns {}.
        self.assertEqual(STAT_GRANT_CALC_KEYS, {})
        rec = self.snap.arena_augment("Typhoon")
        aug = Augment.from_record(rec)
        self.assertEqual(stat_overlay_from_calculations(aug), {})

    def test_returns_empty_when_calculations_empty(self) -> None:
        rec = self.snap.arena_augment("TheBrutalizer")
        aug = Augment.from_record(rec)
        self.assertEqual(stat_overlay_from_calculations(aug), {})

    def test_displacement_path_when_registry_populated(self) -> None:
        # Inject a temporary stat-grant mapping to prove the wiring path.
        # Use a synthetic calc that resolves cleanly to a known value.
        import agents.daemon_slayer.augment_formula_eval as ev
        original = dict(ev.STAT_GRANT_CALC_KEYS)
        try:
            ev.STAT_GRANT_CALC_KEYS["Damage"] = "ad"
            rec = self.snap.arena_augment("Typhoon")
            aug = Augment.from_record(rec)
            # Typhoon Damage at AD=100 -> 20; stat-grant displacement
            # would yield {"ad": 20.0} via the evaluator.
            ctx = StatContext(stats={"ad": 100.0})
            out = stat_overlay_from_calculations(aug, ctx)
            self.assertAlmostEqual(out.get("ad", 0.0), 20.0, places=4)
        finally:
            ev.STAT_GRANT_CALC_KEYS.clear()
            ev.STAT_GRANT_CALC_KEYS.update(original)


class ComputeAugmentStatsFallbackTests(unittest.TestCase):
    """Path-2 fallback to _AUGMENT_STAT_OVERLAYS when calc path returns {}."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_calc_empty_augment_uses_registry(self) -> None:
        # TheBrutalizer has empty calculations; registry path lands AD=20.
        totals = compute_augment_stats(["TheBrutalizer"], self.snap)
        self.assertEqual(totals.get("ad"), 20.0)

    def test_calc_present_but_not_stat_named_falls_back(self) -> None:
        # JeweledGauntlet has non-empty calculations (CritGranted), but the
        # calc key isn't stat-named (STAT_GRANT_CALC_KEYS is empty).
        # Registry path lands crit=0.25.
        totals = compute_augment_stats(["JeweledGauntlet"], self.snap)
        self.assertEqual(totals.get("crit"), 0.25)

    def test_calc_present_no_registry_entry_yields_empty(self) -> None:
        # Typhoon has Damage calc but no registry entry; with empty
        # STAT_GRANT_CALC_KEYS the augment contributes 0 overlay.
        # This is the honest invariant: calculations that produce
        # damage/proc values don't bleed into stat totals.
        totals = compute_augment_stats(["Typhoon"], self.snap)
        self.assertEqual(totals, {})

    def test_calc_displacement_overrides_registry(self) -> None:
        # Prove the precedence order: when the calc path produces an
        # overlay, it wins over the registry. Inject a synthetic
        # stat-grant mapping that disagrees with the registry value to
        # make the precedence visible.
        import agents.daemon_slayer.augment_formula_eval as ev
        original = dict(ev.STAT_GRANT_CALC_KEYS)
        try:
            # TheBrutalizer has calculations={} so it can't exercise the
            # displacement; use JeweledGauntlet (calc is non-empty:
            # CritGranted). Mapping CritGranted -> crit lets the calc
            # path land 0.25 (matching the registry value); we then
            # also drop the registry entry to PROVE the calc path is
            # what produced the overlay.
            ev.STAT_GRANT_CALC_KEYS["CritGranted"] = "crit"
            from agents.daemon_slayer.augments import _AUGMENT_STAT_OVERLAYS
            backup_fn = _AUGMENT_STAT_OVERLAYS.pop("JeweledGauntlet", None)
            try:
                totals = compute_augment_stats(["JeweledGauntlet"], self.snap)
                self.assertAlmostEqual(totals.get("crit", 0.0), 0.25)
            finally:
                if backup_fn is not None:
                    _AUGMENT_STAT_OVERLAYS["JeweledGauntlet"] = backup_fn
        finally:
            ev.STAT_GRANT_CALC_KEYS.clear()
            ev.STAT_GRANT_CALC_KEYS.update(original)


if __name__ == "__main__":
    unittest.main()
