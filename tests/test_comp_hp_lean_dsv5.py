"""DSV5 (P6-G5 residual: AP-DoT-vs-burst EHP-gating).

Premise verified live before building (see docs/LEDGER.md): DSV1 already values
ability-burn DoTs proportional to ``target_max_hp`` and the primary coach path
(coach_integration.archetype_dispatch) already feeds ``enemy_stats.max_hp`` into
the item ranking. The gap was that ``compute_enemy_stats`` derived ``max_hp``
from a comp-BLIND mode/level curve, so the burn valuation fired at a constant
value regardless of how tanky the enemy comp actually was.

A rewind_history.db WIN-anchored measurement (30,164 participants; winning AP
carries bucketed by explicit enemy tank/bruiser count) confirmed the residual is
real: vs 0 tanks winners build burst over DoT by -6.2pt, but vs 2+ tanks they
build DoT over burst by +12.0pt (burst usage halves, 44%% -> 21%%). DSV5 closes
the loop with a DEFAULT-OFF comp-conditioned max-HP seam: a tank-heavy comp
scales ``max_hp`` up so DSV1's already-shipped burn / %max-HP valuation tilts the
RANKING toward DoT vs tanks (agreeing with the core.ds_antitank_hint text hint
that previously had no ranking effect). Seam OFF == byte-identical flat curve;
the live flip is the ``RC_COMP_HP_LEAN`` env gate (operator-gated, see
docs/LIVE_GAME_GATED_SYNC.md). No engine file is touched -> no ENGINE_VERSION
bump.
"""
from __future__ import annotations

import os
import unittest

from coach_integration.enemy_stats import (
    _COMP_HP_SCALE_HI,
    _COMP_HP_SCALE_LO,
    _COMP_HP_STEP,
    compute_enemy_stats,
)

# Clear tanks / bruisers vs clear squishy carries. Used only to drive the
# classifier; the math assertions derive the expected scale from the RETURNED
# tanky_count so a single registry reclassification cannot silently break them.
_TANK_COMP = ["Ornn", "Malphite", "Sion", "Sejuani", "Maokai"]
_SQUISHY_COMP = ["Lux", "Caitlyn", "Veigar", "Ahri", "Jinx"]


def _expected_scale(tanky_count: int) -> float:
    scale = 1.0 + _COMP_HP_STEP * (tanky_count - 1)
    return round(max(_COMP_HP_SCALE_LO, min(_COMP_HP_SCALE_HI, scale)), 4)


class SeamDefaultOffByteIdentical(unittest.TestCase):
    """OFF (no kwarg, no env) leaves max_hp byte-identical to the flat curve."""

    def setUp(self) -> None:
        # Guarantee the env gate is OFF for the default-behavior assertions.
        self._saved = os.environ.pop("RC_COMP_HP_LEAN", None)

    def tearDown(self) -> None:
        if self._saved is not None:
            os.environ["RC_COMP_HP_LEAN"] = self._saved

    def test_no_comp_no_scale(self) -> None:
        s = compute_enemy_stats("sr", level=11)
        # SR @ 11: 1000 + 110*11 = 2210, untouched.
        self.assertEqual(s.max_hp, 2210.0)
        self.assertEqual(s.hp_scale, 1.0)
        self.assertEqual(s.tanky_count, 0)

    def test_tank_comp_but_seam_off_is_identical(self) -> None:
        off = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP)
        flat = compute_enemy_stats("sr", level=11)
        self.assertEqual(off.max_hp, flat.max_hp)
        self.assertEqual(off.hp_scale, 1.0)
        # tanky_count is still observed (display/trace) even with the seam OFF.
        self.assertGreaterEqual(off.tanky_count, 2)

    def test_explicit_false_overrides_env_on(self) -> None:
        os.environ["RC_COMP_HP_LEAN"] = "1"
        s = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP,
                                comp_hp_lean=False)
        self.assertEqual(s.hp_scale, 1.0)
        self.assertEqual(s.max_hp, 2210.0)


class SeamOnScalesByTankCount(unittest.TestCase):
    """ON: max_hp scales up for tank-heavy comps, down for all-squishy."""

    def test_tank_comp_scales_up(self) -> None:
        s = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP,
                                comp_hp_lean=True)
        self.assertGreaterEqual(s.tanky_count, 2)
        self.assertEqual(s.hp_scale, _expected_scale(s.tanky_count))
        self.assertGreater(s.hp_scale, 1.0)
        self.assertAlmostEqual(s.max_hp, round(2210.0 * s.hp_scale, 1), places=1)

    def test_squishy_comp_scales_down(self) -> None:
        s = compute_enemy_stats("sr", level=11, enemy_champions=_SQUISHY_COMP,
                                comp_hp_lean=True)
        self.assertEqual(s.tanky_count, 0)
        # 0 tanks -> 1 + 0.10*(0-1) = 0.90.
        self.assertEqual(s.hp_scale, 0.9)
        self.assertLess(s.max_hp, 2210.0)

    def test_tankier_comp_outscales_squishier(self) -> None:
        tanky = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP,
                                    comp_hp_lean=True)
        squishy = compute_enemy_stats("sr", level=11,
                                      enemy_champions=_SQUISHY_COMP,
                                      comp_hp_lean=True)
        self.assertGreater(tanky.tanky_count, squishy.tanky_count)
        self.assertGreater(tanky.hp_scale, squishy.hp_scale)
        self.assertGreater(tanky.max_hp, squishy.max_hp)

    def test_no_comp_info_on_is_neutral(self) -> None:
        # Seam ON but NO enemy_champions -> "no data" is NOT "all squishy".
        # Must stay the flat curve (1.0) so the champ-select / preview routes
        # (routes_state ds-preview Path 3, ds-knobs, ds-relscore, ds-statcheck)
        # that call compute_enemy_stats(mode, level) with no comp are
        # byte-identical when the seam is flipped ON. Pre-fix this returned 0.90
        # (tanky_count=0 -> 1 + 0.10*(0-1)), silently de-rating every no-comp
        # preview by 10% and contradicting the _comp_hp_scale docstring.
        s = compute_enemy_stats("sr", level=11, comp_hp_lean=True)
        self.assertEqual(s.tanky_count, 0)
        self.assertEqual(s.hp_scale, 1.0)
        self.assertEqual(s.max_hp, 2210.0)

    def test_blank_only_comp_is_no_info(self) -> None:
        # A comp of only blank/empty ids carries no signal -> treated as
        # no-comp-info (1.0), never the all-squishy floor.
        s = compute_enemy_stats("sr", level=11, enemy_champions=["", "  "],
                                comp_hp_lean=True)
        self.assertEqual(s.tanky_count, 0)
        self.assertEqual(s.hp_scale, 1.0)
        self.assertEqual(s.max_hp, 2210.0)

    def test_known_squishy_still_discounts_vs_no_info_neutral(self) -> None:
        # The distinction the no-info guard preserves: a REAL all-squishy comp
        # (>=1 classifiable champ, 0 tanky) keeps the intended 0.90 discount,
        # while no-comp-info stays neutral 1.0. Same tanky_count=0, different
        # scale - "all squishy" is a judgement from real data, "no data" is not.
        known = compute_enemy_stats("sr", level=11,
                                    enemy_champions=_SQUISHY_COMP,
                                    comp_hp_lean=True)
        noinfo = compute_enemy_stats("sr", level=11, comp_hp_lean=True)
        self.assertEqual(known.tanky_count, 0)
        self.assertEqual(noinfo.tanky_count, 0)
        self.assertEqual(known.hp_scale, 0.9)
        self.assertEqual(noinfo.hp_scale, 1.0)
        self.assertLess(known.max_hp, noinfo.max_hp)

    def test_scale_clamped_to_ceiling(self) -> None:
        # A 5-tank comp: 1 + 0.10*4 = 1.40 -> clamped to HI (1.30).
        s = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP,
                                comp_hp_lean=True)
        if s.tanky_count >= 5:
            self.assertEqual(s.hp_scale, _COMP_HP_SCALE_HI)
        self.assertLessEqual(s.hp_scale, _COMP_HP_SCALE_HI)


class EnvGateTurnsSeamOn(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.get("RC_COMP_HP_LEAN")

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop("RC_COMP_HP_LEAN", None)
        else:
            os.environ["RC_COMP_HP_LEAN"] = self._saved

    def test_env_on_scales_without_kwarg(self) -> None:
        os.environ["RC_COMP_HP_LEAN"] = "1"
        s = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP)
        self.assertGreater(s.hp_scale, 1.0)

    def test_env_off_value_is_identity(self) -> None:
        os.environ["RC_COMP_HP_LEAN"] = "0"
        s = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP)
        self.assertEqual(s.hp_scale, 1.0)

    def test_env_on_no_comp_is_byte_identical(self) -> None:
        # The live flip mechanism is the env var. With it ON but no comp (the
        # champ-select / preview route shape), max_hp must be byte-identical to
        # the OFF flat curve - the no-info guard's whole purpose. This is the
        # safety contract that lets the operator flip RC_COMP_HP_LEAN=1 without
        # silently shifting every preview ranking.
        os.environ["RC_COMP_HP_LEAN"] = "1"
        on = compute_enemy_stats("sr", level=11)
        os.environ["RC_COMP_HP_LEAN"] = "0"
        off = compute_enemy_stats("sr", level=11)
        self.assertEqual(on.max_hp, off.max_hp)
        self.assertEqual(on.hp_scale, 1.0)


class DoTValuationTiltsWithCompHp(unittest.TestCase):
    """The win-data-anchored payoff: a tank comp's scaled max_hp raises DSV1's
    Liandry's burn valuation, tilting the ability DPS toward DoT vs tanks."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    def test_liandry_burn_dps_rises_with_comp_scaled_hp(self) -> None:
        from agents.daemon_slayer.ability_dps import compute_ability_dps

        flat = compute_enemy_stats("sr", level=11, comp_hp_lean=False)
        tanky = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP,
                                    comp_hp_lean=True)
        self.assertGreater(tanky.max_hp, flat.max_hp)

        dps_flat = compute_ability_dps(
            self.snap, "Veigar", 11, item_ids=["6653"], mode="SR",
            target_mr=30.0, target_max_hp=flat.max_hp)
        dps_tanky = compute_ability_dps(
            self.snap, "Veigar", 11, item_ids=["6653"], mode="SR",
            target_mr=30.0, target_max_hp=tanky.max_hp)
        # Liandry's Torment is the only %max-HP term on Veigar+Liandry, so the
        # comp uplift cleanly raises the burn-fed ability DPS.
        self.assertGreater(dps_tanky.total_ability_dps,
                           dps_flat.total_ability_dps)

    def test_pure_stat_ap_item_unaffected_by_comp_hp(self) -> None:
        # Rabadon's (3089) carries no %max-HP term -> comp scaling must NOT
        # change its ability DPS (proves the tilt only rides %max-HP items).
        from agents.daemon_slayer.ability_dps import compute_ability_dps

        flat = compute_enemy_stats("sr", level=11, comp_hp_lean=False)
        tanky = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP,
                                    comp_hp_lean=True)
        a = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3089"],
                                mode="SR", target_mr=30.0,
                                target_max_hp=flat.max_hp)
        b = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3089"],
                                mode="SR", target_mr=30.0,
                                target_max_hp=tanky.max_hp)
        self.assertAlmostEqual(a.total_ability_dps, b.total_ability_dps,
                               places=4)


class CoachTraceRecordsAppliedModifier(unittest.TestCase):
    """The deterministic-verification plumb: record_enemy_target round-trips."""

    def test_record_enemy_target_roundtrips(self) -> None:
        from core import coach_trace

        tanky = compute_enemy_stats("sr", level=11, enemy_champions=_TANK_COMP,
                                    comp_hp_lean=True)
        flat = compute_enemy_stats("sr", level=11, comp_hp_lean=False)
        coach_trace.record_enemy_target(
            mode="SR", champion="Veigar",
            base_max_hp=flat.max_hp, applied_max_hp=tanky.max_hp,
            hp_scale=tanky.hp_scale, tanky_count=tanky.tanky_count,
            bonus_hp=tanky.bonus_hp,
        )
        recent = coach_trace.read_recent(limit=10)
        hits = [r for r in recent
                if (r.get("extra") or {}).get("kind") == "enemy_target"
                and (r.get("extra") or {}).get("champion") == "Veigar"]
        self.assertTrue(hits)
        ex = hits[-1]["extra"]
        self.assertEqual(ex["applied_max_hp"], round(tanky.max_hp, 1))
        self.assertGreater(ex["applied_max_hp"], ex["base_max_hp"])
        self.assertEqual(ex["tanky_count"], tanky.tanky_count)


if __name__ == "__main__":
    unittest.main()
