"""Numerical-robustness / degenerate-input hardening for the public DS scorers.

Lane P1-L12 (ENGINE_VERSION 1.7.0). The engine math is heavily verified for
NORMAL inputs elsewhere. This file is the EXTREME-but-reachable-input contract:
every public Daemon Slayer scorer entrypoint must, on degenerate input, either

  * return a FINITE, sanely-bounded result (no NaN, no +/-inf), OR
  * raise the engine's OWN defined ``ValueError`` / ``TypeError``

and must NEVER leak a bare ``ZeroDivisionError`` / ``IndexError`` /
``AttributeError`` / ``KeyError`` from arithmetic on a boundary value, and must
be deterministic (same degenerate input N times -> identical output).

Public in-process engine entrypoints under test (the 7 pure-math scorers; the
HTTP-client dispatcher ``core.daemon_slayer_client.rank_for_primary_archetype``
needs a running :8893 server and is out of scope for a unit fuzz):

  * ``engine.build_champion``        - stat resolver feeding every scorer
  * ``stats.clamp_level``            - shared level validator (raises, not clamps)
  * ``dps.compute_dps``              - auto-attack DPS (carry)
  * ``ehp.compute_ehp``              - effective HP (tank)
  * ``hps.compute_hps``              - heal+shield throughput (enchanter)
  * ``burst.compute_burst_damage``   - one-combo burst (assassin)
  * ``hybrid.compute_hybrid``        - DPS+EHP blend (bruiser)
  * ``ability_dps.compute_ability_dps`` - ability DPS (mage)
  * ``rank.rank_items``              - per-slot DPS-delta ranker

No hardcoded magic-number expectations and no fragile cross-item comparison
asserts: every assertion is on a robustness invariant (finiteness, a defined
exception type, a clamp being applied, determinism, monotone direction the
formula demands), never on an exact engine output value.

NOTE on terminology: ``stats.clamp_level`` is a misnomer - it VALIDATES and
raises ``ValueError`` for out-of-[1,18] input rather than clamping. That is
still a DEFINED, deterministic error, which this lane accepts as correct
hardening behavior (the contract is "clamp OR defined error", not "must
clamp").

ROBUSTNESS GAP FOUND BY THIS FUZZ - NOW FIXED (P1 iter4 integration):

  Attack speed was NOT capped at League's 2.5 hard cap. A reachable 6-item
  attack-speed build yielded ``stats['as'] ~= 3.47`` and ``compute_dps``
  consumed it raw, inflating DPS past anything achievable in-game. Fixed via
  ``engine.ATTACK_SPEED_CAP`` (clamped in ``_combine_items`` + the
  ``build_champion`` augment block, plus a defensive re-clamp after
  conditional AS in ``dps.py``). ``XXX_FlaggedRobustnessGaps`` is now the
  passing regression lock for the cap.
"""

import math
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import _armor_factor, compute_dps
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.hps import compute_hps
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.hybrid import compute_hybrid
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.rank import rank_items
from agents.daemon_slayer.engine import build_champion
from agents.daemon_slayer.stats import LEVEL_MAX, LEVEL_MIN, clamp_level


# Stable snapshot fixtures - confirmed present in patch 16.10.1 and chosen so
# the test does not depend on any specific numeric output, only on robustness
# invariants. Champions span the scorer archetypes; items are common
# AS/crit/pen terminals.
CARRY = "Aatrox"
TANK = "Malphite"
ENCHANTER = "Soraka"
ASSASSIN = "Zed"
MAGE = "Lux"

IE = "3031"            # Infinity Edge (crit)
PHANTOM_DANCER = "3046"  # Phantom Dancer (crit + attack speed)
ZHONYAS = "3157"       # Zhonya's Hourglass
LDR = "3036"           # Lord Dominik's Regards (target-bonus-HP amp)

# A maximal 6-slot identical-item build (the engine's worst-case stack path).
SIX_AS_ITEMS = [PHANTOM_DANCER] * 6
SIX_CRIT_ITEMS = [IE] * 6


def _finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def assertFiniteScore(self, value: float, label: str) -> None:
        self.assertTrue(
            _finite(value),
            f"{label}: expected a finite score, got {value!r}",
        )

    def assertAllFinite(self, stats: dict, label: str) -> None:
        for k, v in stats.items():
            if isinstance(v, (int, float)):
                self.assertTrue(
                    math.isfinite(v),
                    f"{label}: stat {k!r}={v!r} is non-finite",
                )


# --------------------------------------------------------------------------
# clamp_level - the shared level validator. Defined ValueError/TypeError, not
# a bare exception, on every out-of-range / wrong-type input.
# --------------------------------------------------------------------------
class ClampLevelBoundaryTests(unittest.TestCase):
    def test_in_range_passthrough(self) -> None:
        for lv in (LEVEL_MIN, 6, 11, LEVEL_MAX):
            self.assertEqual(clamp_level(lv), lv)

    def test_out_of_range_raises_value_error(self) -> None:
        for lv in (0, -1, LEVEL_MAX + 1, 100, -999):
            with self.assertRaises(ValueError):
                clamp_level(lv)

    def test_non_int_raises_type_error_not_bare(self) -> None:
        # float / None / str must raise the engine's TypeError, never a bare
        # arithmetic blow-up downstream.
        for bad in (1.0, None, "5", 7.5):
            with self.assertRaises((TypeError, ValueError)):
                clamp_level(bad)  # type: ignore[arg-type]

    def test_deterministic(self) -> None:
        self.assertEqual([clamp_level(11) for _ in range(5)], [11] * 5)


# --------------------------------------------------------------------------
# _armor_factor - the recently-fixed negative-resist amp 2 - 100/(100 - R).
# Must stay finite and bounded as R -> very negative, and never divide by
# zero at R = -100 (the old buggy form 2 - 100/(100 + R) blew up there).
# --------------------------------------------------------------------------
class ArmorFactorRobustnessTests(unittest.TestCase):
    def test_zero_is_unity(self) -> None:
        self.assertEqual(_armor_factor(0), 1.0)

    def test_minus_100_is_finite_not_div_zero(self) -> None:
        # Old buggy 2 - 100/(100 + R) would ZeroDivisionError here.
        f = _armor_factor(-100)
        self.assertTrue(math.isfinite(f))
        self.assertGreater(f, 1.0)  # it IS an amplification
        self.assertLess(f, 2.0)     # but still bounded below the asymptote

    def test_very_negative_resist_stays_bounded_below_two(self) -> None:
        prev = _armor_factor(-100)
        for r in (-1_000.0, -1e6, -1e9, -1e12, -1e15):
            f = _armor_factor(r)
            self.assertTrue(math.isfinite(f), f"R={r}: non-finite {f!r}")
            # Monotone increasing toward the 2.0 asymptote, never reaching it.
            self.assertGreaterEqual(f, prev)
            self.assertLess(f, 2.0)
            prev = f

    def test_huge_positive_resist_approaches_zero_not_negative(self) -> None:
        for r in (1e6, 1e9, 1e12):
            f = _armor_factor(r)
            self.assertTrue(math.isfinite(f))
            self.assertGreater(f, 0.0)
            self.assertLess(f, 1e-3)

    def test_deterministic(self) -> None:
        for r in (-1e9, -100, 0, 100, 1e9):
            self.assertEqual(len({_armor_factor(r) for _ in range(5)}), 1)


# --------------------------------------------------------------------------
# compute_dps - carry scorer. Level / target_armor / target_mr / target_hp
# boundary sweep + empty/maximal item lists + determinism.
# --------------------------------------------------------------------------
class ComputeDpsBoundaryTests(_SnapBase):
    def test_level_out_of_range_raises_defined_value_error(self) -> None:
        for lv in (0, -1, 19, 99):
            with self.assertRaises(ValueError):
                compute_dps(self.snap, CARRY, level=lv)

    def test_level_endpoints_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            r = compute_dps(self.snap, CARRY, level=lv)
            self.assertFiniteScore(r.weighted_dps, f"dps L{lv}")
            self.assertGreaterEqual(r.weighted_dps, 0.0)

    def test_extreme_target_armor_finite_and_monotone(self) -> None:
        # Lower armor must never reduce DPS; higher armor must never raise it.
        a_neg = compute_dps(self.snap, CARRY, level=11, target_armor=-1e9)
        a_zero = compute_dps(self.snap, CARRY, level=11, target_armor=0.0)
        a_huge = compute_dps(self.snap, CARRY, level=11, target_armor=1e9)
        for tag, r in (("neg", a_neg), ("zero", a_zero), ("huge", a_huge)):
            self.assertFiniteScore(r.weighted_dps, f"dps armor={tag}")
            self.assertGreaterEqual(r.weighted_dps, 0.0)
        self.assertGreaterEqual(a_neg.weighted_dps, a_zero.weighted_dps)
        self.assertGreaterEqual(a_zero.weighted_dps, a_huge.weighted_dps)
        # armor = -100 is the divide-by-zero candidate for the amp formula.
        r_m100 = compute_dps(self.snap, CARRY, level=11, target_armor=-100.0)
        self.assertFiniteScore(r_m100.weighted_dps, "dps armor=-100")

    def test_extreme_target_mr_and_hp_finite(self) -> None:
        for kw in (
            {"target_mr": -1e9},
            {"target_mr": -100.0},
            {"target_mr": 1e9},
            {"target_max_hp": 0.0},
            {"target_max_hp": 1e9, "target_bonus_hp": 1e9},
            {"target_bonus_hp": -1e9},
        ):
            r = compute_dps(self.snap, CARRY, level=11, **kw)
            self.assertFiniteScore(r.weighted_dps, f"dps {kw}")
            self.assertGreaterEqual(r.weighted_dps, 0.0)

    def test_empty_and_maximal_item_lists_finite(self) -> None:
        r_empty = compute_dps(self.snap, CARRY, level=11, item_ids=[])
        r_none = compute_dps(self.snap, CARRY, level=11, item_ids=None)
        r_six = compute_dps(self.snap, CARRY, level=18, item_ids=SIX_CRIT_ITEMS)
        for tag, r in (("empty", r_empty), ("none", r_none), ("6xIE", r_six)):
            self.assertFiniteScore(r.weighted_dps, f"dps items={tag}")
            self.assertGreaterEqual(r.weighted_dps, 0.0)

    def test_unknown_champion_raises_keyerror_not_bare_arith(self) -> None:
        # Unknown id is a documented KeyError from DataSnapshot.champion -
        # a DEFINED contract, not a NaN or a bare ZeroDivisionError.
        with self.assertRaises(KeyError):
            compute_dps(self.snap, "NotAChampion", level=11)

    def test_invalid_phase_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            compute_dps(self.snap, CARRY, level=11, phase="midgame")

    def test_six_identical_crit_items_clamp_crit_to_one(self) -> None:
        # 6 crit items would sum > 100% crit; the engine MUST clamp to 1.0.
        rs = build_champion(self.snap, CARRY, level=18, item_ids=SIX_CRIT_ITEMS)
        self.assertLessEqual(rs.stats.get("crit", 0.0), 1.0 + 1e-9)
        r = compute_dps(self.snap, CARRY, level=18, item_ids=SIX_CRIT_ITEMS)
        self.assertFiniteScore(r.weighted_dps, "dps 6xIE")

    def test_determinism_under_repetition(self) -> None:
        outs = [
            compute_dps(
                self.snap, CARRY, level=11,
                target_armor=-1e9, item_ids=[PHANTOM_DANCER] * 3,
            ).weighted_dps
            for _ in range(6)
        ]
        self.assertEqual(len(set(outs)), 1, f"non-deterministic: {outs}")


# --------------------------------------------------------------------------
# build_champion - the stat resolver. All resolved stats must be finite for
# every degenerate level/item combination, and crit clamped.
# --------------------------------------------------------------------------
class BuildChampionRobustnessTests(_SnapBase):
    def test_naked_endpoints_all_stats_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            rs = build_champion(self.snap, CARRY, level=lv, item_ids=[])
            self.assertAllFinite(rs.stats, f"build naked L{lv}")

    def test_six_identical_items_all_stats_finite_crit_clamped(self) -> None:
        rs = build_champion(self.snap, CARRY, level=18, item_ids=SIX_AS_ITEMS)
        self.assertAllFinite(rs.stats, "build 6xPD")
        self.assertLessEqual(rs.stats.get("crit", 0.0), 1.0 + 1e-9)

    def test_level_out_of_range_raises(self) -> None:
        for lv in (0, 19, -5):
            with self.assertRaises(ValueError):
                build_champion(self.snap, CARRY, level=lv)

    def test_determinism(self) -> None:
        sig = lambda: tuple(
            sorted(
                (k, round(v, 9))
                for k, v in build_champion(
                    self.snap, CARRY, level=13, item_ids=SIX_AS_ITEMS
                ).stats.items()
                if isinstance(v, (int, float))
            )
        )
        self.assertEqual(len({sig() for _ in range(4)}), 1)


# --------------------------------------------------------------------------
# compute_ehp - tank scorer. Enemy-share validation + the R=-100 / HP=0
# divide-by-zero guard on the EHP term.
# --------------------------------------------------------------------------
class ComputeEhpBoundaryTests(_SnapBase):
    def test_level_out_of_range_raises(self) -> None:
        for lv in (0, 19):
            with self.assertRaises(ValueError):
                compute_ehp(self.snap, TANK, level=lv)

    def test_share_out_of_range_raises_value_error(self) -> None:
        for kw in (
            {"enemy_ad_share": 1.5},
            {"enemy_ad_share": -0.1},
            {"enemy_ap_share": 1.5},
            {"enemy_ap_share": -0.01},
            {"enemy_ad_share": 0.8, "enemy_ap_share": 0.8},  # sum > 1
        ):
            with self.assertRaises(ValueError):
                compute_ehp(self.snap, TANK, level=11, **kw)

    def test_pure_true_damage_split_finite(self) -> None:
        # ad=ap=0 -> 100% true share; the true_ehp branch must stay finite.
        r = compute_ehp(
            self.snap, TANK, level=11, enemy_ad_share=0.0, enemy_ap_share=0.0
        )
        for label, v in (
            ("physical", r.physical_ehp),
            ("magical", r.magical_ehp),
            ("true", r.true_ehp),
            ("blended", r.blended_ehp),
        ):
            self.assertFiniteScore(v, f"ehp {label}")
            self.assertGreater(v, 0.0)

    def test_endpoints_and_maximal_items_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            r = compute_ehp(self.snap, TANK, level=lv, item_ids=[ZHONYAS] * 6)
            self.assertFiniteScore(r.blended_ehp, f"ehp L{lv} 6xZ")
            self.assertGreater(r.blended_ehp, 0.0)

    def test_armor_factor_at_minus_100_keeps_ehp_finite(self) -> None:
        # Direct guard on the divide-by-zero candidate the EHP term divides
        # by: HP / (_armor_factor(R) * mult). factor(-100)=1.5 != 0.
        self.assertNotEqual(_armor_factor(-100.0), 0.0)
        self.assertTrue(math.isfinite(1.0 / _armor_factor(-100.0)))

    def test_determinism(self) -> None:
        outs = [
            compute_ehp(self.snap, TANK, level=11, item_ids=[ZHONYAS] * 2).blended_ehp
            for _ in range(5)
        ]
        self.assertEqual(len(set(outs)), 1, f"non-deterministic: {outs}")


# --------------------------------------------------------------------------
# compute_hps - enchanter scorer. targets_per_proc_override boundary
# (0 / negative / huge) must not produce NaN/inf or a bare exception.
# --------------------------------------------------------------------------
class ComputeHpsBoundaryTests(_SnapBase):
    def test_level_out_of_range_raises(self) -> None:
        for lv in (0, 19):
            with self.assertRaises(ValueError):
                compute_hps(self.snap, ENCHANTER, level=lv)

    def test_endpoints_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            r = compute_hps(self.snap, ENCHANTER, level=lv)
            self.assertFiniteScore(r.total_throughput, f"hps L{lv}")
            self.assertGreaterEqual(r.total_throughput, 0.0)

    def test_targets_per_proc_override_extremes_finite(self) -> None:
        for ov in (0.0, -5.0, 1e9):
            r = compute_hps(
                self.snap, ENCHANTER, level=11, targets_per_proc_override=ov
            )
            self.assertFiniteScore(
                r.total_throughput, f"hps tpp_override={ov}"
            )
            # zero/negative targets => no positive throughput credit, but
            # the result must stay finite (no NaN) and non-negative for the
            # zero case.
            if ov == 0.0:
                self.assertGreaterEqual(r.total_throughput, 0.0)

    def test_maximal_items_finite(self) -> None:
        r = compute_hps(self.snap, ENCHANTER, level=18, item_ids=[ZHONYAS] * 6)
        self.assertFiniteScore(r.total_throughput, "hps 6xZ")

    def test_determinism(self) -> None:
        outs = [
            compute_hps(self.snap, ENCHANTER, level=11).total_throughput
            for _ in range(5)
        ]
        self.assertEqual(len(set(outs)), 1, f"non-deterministic: {outs}")


# --------------------------------------------------------------------------
# compute_burst_damage - assassin scorer. target_current_hp_pct + block
# strategy validation; extreme target stats stay finite.
# --------------------------------------------------------------------------
class ComputeBurstBoundaryTests(_SnapBase):
    def test_level_out_of_range_raises(self) -> None:
        for lv in (0, 19):
            with self.assertRaises(ValueError):
                compute_burst_damage(self.snap, ASSASSIN, level=lv)

    def test_target_current_hp_pct_out_of_range_raises(self) -> None:
        for pct in (-1.0, -0.01, 1.5, 5.0):
            with self.assertRaises(ValueError):
                compute_burst_damage(
                    self.snap, ASSASSIN, level=11, target_current_hp_pct=pct
                )

    def test_hp_pct_endpoints_finite(self) -> None:
        for pct in (0.0, 1.0):
            r = compute_burst_damage(
                self.snap, ASSASSIN, level=11, target_current_hp_pct=pct
            )
            self.assertFiniteScore(r.total_burst_damage, f"burst hp%={pct}")
            self.assertGreaterEqual(r.total_burst_damage, 0.0)

    def test_bad_block_strategy_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            compute_burst_damage(
                self.snap, ASSASSIN, level=11, block_strategy="nonsense"
            )

    def test_extreme_target_stats_finite(self) -> None:
        for kw in (
            {"target_armor": -1e9},
            {"target_armor": 1e9},
            {"target_armor": -100.0},
            {"target_mr": -1e9},
            {"target_max_hp": 1e9, "target_bonus_hp": 1e9},
        ):
            r = compute_burst_damage(self.snap, ASSASSIN, level=11, **kw)
            self.assertFiniteScore(r.total_burst_damage, f"burst {kw}")
            self.assertGreaterEqual(r.total_burst_damage, 0.0)

    def test_endpoints_and_maximal_items_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            r = compute_burst_damage(
                self.snap, ASSASSIN, level=lv, item_ids=[LDR] * 6
            )
            self.assertFiniteScore(r.total_burst_damage, f"burst L{lv} 6xLDR")

    def test_determinism(self) -> None:
        outs = [
            compute_burst_damage(
                self.snap, ASSASSIN, level=11, target_armor=-1e9
            ).total_burst_damage
            for _ in range(5)
        ]
        self.assertEqual(len(set(outs)), 1, f"non-deterministic: {outs}")


# --------------------------------------------------------------------------
# compute_hybrid - bruiser scorer. alpha/beta weight extremes; the blend
# must stay finite (it is a weighted sum of finite DPS + EHP).
# --------------------------------------------------------------------------
class ComputeHybridBoundaryTests(_SnapBase):
    def test_level_out_of_range_raises(self) -> None:
        for lv in (0, 19):
            with self.assertRaises(ValueError):
                compute_hybrid(self.snap, CARRY, level=lv)

    def test_endpoints_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            r = compute_hybrid(self.snap, CARRY, level=lv)
            self.assertFiniteScore(r.hybrid_score, f"hybrid L{lv}")

    def test_zero_weights_yield_finite_zero(self) -> None:
        r = compute_hybrid(self.snap, CARRY, level=11, alpha=0.0, beta=0.0)
        self.assertFiniteScore(r.hybrid_score, "hybrid alpha=beta=0")
        self.assertEqual(r.hybrid_score, 0.0)

    def test_extreme_weights_finite(self) -> None:
        for a, b in ((-1e9, 1e9), (1e9, -1e9), (1e12, 1e12)):
            r = compute_hybrid(self.snap, CARRY, level=11, alpha=a, beta=b)
            self.assertFiniteScore(r.hybrid_score, f"hybrid a={a} b={b}")

    def test_extreme_target_and_share_inputs(self) -> None:
        # DPS-side extreme stays finite; EHP-side share validation still
        # raises the defined ValueError through the hybrid wrapper.
        r = compute_hybrid(self.snap, CARRY, level=11, target_armor=-1e9)
        self.assertFiniteScore(r.hybrid_score, "hybrid armor=-1e9")
        with self.assertRaises(ValueError):
            compute_hybrid(
                self.snap, CARRY, level=11, enemy_ad_share=0.9, enemy_ap_share=0.9
            )

    def test_determinism(self) -> None:
        outs = [
            compute_hybrid(self.snap, CARRY, level=11).hybrid_score
            for _ in range(5)
        ]
        self.assertEqual(len(set(outs)), 1, f"non-deterministic: {outs}")


# --------------------------------------------------------------------------
# compute_ability_dps - mage scorer. Boundary level + extreme target stats.
# --------------------------------------------------------------------------
class ComputeAbilityDpsBoundaryTests(_SnapBase):
    def test_level_out_of_range_raises(self) -> None:
        for lv in (0, 19):
            with self.assertRaises(ValueError):
                compute_ability_dps(self.snap, MAGE, level=lv)

    def test_endpoints_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            r = compute_ability_dps(self.snap, MAGE, level=lv)
            self.assertFiniteScore(r.total_ability_dps, f"abilitydps L{lv}")
            self.assertGreaterEqual(r.total_ability_dps, 0.0)

    def test_extreme_target_stats_finite_and_monotone(self) -> None:
        lo = compute_ability_dps(self.snap, MAGE, level=11, target_mr=-1e9)
        mid = compute_ability_dps(self.snap, MAGE, level=11, target_mr=0.0)
        hi = compute_ability_dps(self.snap, MAGE, level=11, target_mr=1e9)
        for tag, r in (("mr=-1e9", lo), ("mr=0", mid), ("mr=1e9", hi)):
            self.assertFiniteScore(r.total_ability_dps, f"abilitydps {tag}")
            self.assertGreaterEqual(r.total_ability_dps, 0.0)
        # Less MR never reduces magic ability DPS; more never raises it.
        self.assertGreaterEqual(lo.total_ability_dps, mid.total_ability_dps)
        self.assertGreaterEqual(mid.total_ability_dps, hi.total_ability_dps)

    def test_bad_block_strategy_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            compute_ability_dps(
                self.snap, MAGE, level=11, block_strategy="bogus"
            )

    def test_maximal_items_finite(self) -> None:
        r = compute_ability_dps(self.snap, MAGE, level=18, item_ids=[ZHONYAS] * 6)
        self.assertFiniteScore(r.total_ability_dps, "abilitydps 6xZ")

    def test_determinism(self) -> None:
        outs = [
            compute_ability_dps(
                self.snap, MAGE, level=11, target_mr=-1e9
            ).total_ability_dps
            for _ in range(5)
        ]
        self.assertEqual(len(set(outs)), 1, f"non-deterministic: {outs}")


# --------------------------------------------------------------------------
# rank_items - per-slot DPS-delta ranker. Degenerate current build / target
# stats / sort key; every ranked delta finite; deterministic ordering.
# --------------------------------------------------------------------------
class RankItemsBoundaryTests(_SnapBase):
    def test_level_out_of_range_raises(self) -> None:
        for lv in (0, 19):
            with self.assertRaises(ValueError):
                rank_items(self.snap, CARRY, level=lv)

    def test_bad_sort_key_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            rank_items(self.snap, CARRY, level=11, sort_by="not-a-key")

    def test_full_build_leaves_no_slot_raises_value_error(self) -> None:
        # current_item_ids filling every slot is a defined ValueError, not
        # an IndexError from slot arithmetic.
        with self.assertRaises(ValueError):
            rank_items(
                self.snap, CARRY, level=11,
                current_item_ids=[IE, IE, IE, IE, IE, IE],
                slot_count=6,
            )

    def test_extreme_target_armor_all_deltas_finite(self) -> None:
        for ta in (-1e9, -100.0, 0.0, 1e9):
            res = rank_items(
                self.snap, CARRY, level=11, target_armor=ta, top_n=8
            )
            self.assertFiniteScore(res.baseline_dps, f"rank baseline armor={ta}")
            for ri in res.ranked:
                self.assertTrue(
                    math.isfinite(ri.delta_dps) and math.isfinite(ri.new_dps),
                    f"rank armor={ta}: {ri.item_id} delta={ri.delta_dps} "
                    f"new={ri.new_dps} non-finite",
                )

    def test_endpoints_finite(self) -> None:
        for lv in (LEVEL_MIN, LEVEL_MAX):
            res = rank_items(self.snap, CARRY, level=lv, top_n=5)
            self.assertFiniteScore(res.baseline_dps, f"rank L{lv}")
            for ri in res.ranked:
                self.assertTrue(math.isfinite(ri.delta_dps))

    def test_determinism_of_ranked_order(self) -> None:
        def sig() -> tuple:
            return tuple(
                (ri.item_id, round(ri.delta_dps, 6))
                for ri in rank_items(self.snap, CARRY, level=11, top_n=8).ranked
            )

        self.assertEqual(len({sig() for _ in range(3)}), 1)


# --------------------------------------------------------------------------
# FLAGGED ROBUSTNESS GAPS - documented as xfail so the suite stays green.
# Engine source edits are owned by a PARALLEL lane (concurrent edits would
# conflict); this lane is TEST-ONLY. Each xfail precisely pins the gap so
# the engine owner can act on it.
# --------------------------------------------------------------------------
class XXX_FlaggedRobustnessGaps(_SnapBase):
    """Robustness gaps surfaced by the P1-L12 fuzz. The 2.5 attack-speed
    cap gap was FIXED in the P1 iter4 integration; the test below is now a
    passing regression lock that guards the cap from re-regressing."""

    def test_attack_speed_must_be_capped_at_2_5(self) -> None:
        """REGRESSION LOCK: League 2.5 attack-speed hard cap.

        Was a P1-L12 flagged gap; FIXED in the P1 iter4 integration
        (engine.ATTACK_SPEED_CAP applied in _combine_items + the
        build_champion augment block, plus a defensive re-clamp after
        conditional AS in dps.py). This now passes and guards the cap.

        Repro: ``build_champion('Aatrox', level=18, item_ids=['3046']*6)``
        (six Phantom Dancers - a reachable 6-slot build) resolves
        ``stats['as'] ~= 3.47``. ``compute_dps`` then consumes it raw at
        ``agents/daemon_slayer/dps.py:436`` (``eff_as = float(stats.get(
        "as", 0.0))`` in ``_rotation_attack_dps``) and again at
        ``dps.py:708``, with NO ``min(2.5, eff_as)`` anywhere in
        ``engine._combine_items`` or the DPS layer.

        Observed: ``stats['as'] == 3.4666...`` and the weighted DPS scales
        linearly off that uncapped value (~214 vs the ~ value a 2.5-capped
        build would yield). The output is FINITE - so this is not a
        NaN/inf/crash defect - but it is NOT sanely bounded to game
        reality: League hard-caps attack speed at 2.5 attacks/sec, so the
        engine over-states DPS for any build that stacks past 2.5 AS.

        Expected clamp: resolved ``stats['as']`` (or ``eff_as`` at the DPS
        consumption sites) clamped to <= 2.5, mirroring the existing
        ``crit`` clamp to 1.0 in ``_combine_items`` and the defensive
        ``min(crit, 1.0)`` at ``dps.py:441``.

        Not fixed here: P1-L12 is test-only; a parallel lane owns engine
        edits and concurrent source edits would conflict. This xfail
        documents the gap and asserts the post-fix invariant.
        """
        rs = build_champion(
            self.snap, CARRY, level=18, item_ids=[PHANTOM_DANCER] * 6
        )
        # Six Phantom Dancers resolves ~3.47 AS uncapped; the engine now
        # clamps it to 2.5 (mirrors the crit -> 1.0 clamp).
        self.assertLessEqual(
            rs.stats.get("as", 0.0),
            2.5 + 1e-9,
            f"attack speed {rs.stats.get('as')!r} exceeds League's 2.5 cap",
        )


if __name__ == "__main__":
    unittest.main()
