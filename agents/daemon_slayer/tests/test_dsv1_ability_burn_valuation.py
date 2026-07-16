"""DSV1 (P6-G5 residual 1): AP damage-over-time burn valuation.

Root cause characterized: ``compute_ability_dps`` (the mage / ability scorer)
mirrors ``compute_dps``'s item AMP + PEN handling (ability_dps.py:950-965) but
NEVER folded the item PERIODIC procs - so the ability-triggered AP burn DoTs
(Liandry's Torment, Blackfire's Baleful Blaze, Demonic Embrace's Azakana's
Gaze) were invisible to the mage item ranking even though ``compute_dps`` (the
auto-attack scorer) has valued them via ``_periodic_proc_dps`` since Phase 4.
P6-G5 logged this as the "AP DoT burn vs single-rotation ability model" gap
(Lux Liandry's ranked #23). DSV1 completes the mirror: the same time-based item
procs now flow into the ability DPS total under the established "always-active
convention" (sustained over the fight, re-applied on every ability cast).

Two data fixes ride along, both anchored to verbatim 16.12.1 Meraki:
  * Liandry's Torment (6653 / Arena 226653) gains its missing Torment burn
    periodic - 6% target max HP total magic over 3s = 2% max HP / s sustained
    (the exact sibling of Azakana's Gaze 1% / s). Suffering (damage_amp 0.06)
    is unchanged.
  * Blackfire Torch (2503 / Arena 222503) Baleful Blaze is re-pinned to the
    Meraki total - 60 (+6% AP) magic over 3s across 6 ticks = 10 (+1% AP) per
    0.5s tick. The prior 6 (+6% AP)/tick mis-read the wiki ``{{ap|60/6}}``
    tick-count (60 total over 6 ticks) as a melee/ranged split, which
    over-scaled AP by 6x at the per-tick level.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_types import CallContext, MAGICAL
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import _armor_factor
from agents.daemon_slayer.effects import ITEM_EFFECTS


def _ctx(ap: float = 0.0, target_max_hp: float = 0.0) -> CallContext:
    return CallContext(base_ad=0.0, bonus_ad=0.0, level=11, ap=ap,
                       target_max_hp=target_max_hp)


class LiandryTormentPeriodicData(unittest.TestCase):
    """6653 + Arena 226653 carry the Torment %max-HP burn periodic."""

    def _assert_torment(self, item_id: str) -> None:
        eff = ITEM_EFFECTS[item_id]
        torment = [p for p in eff.periodics if p.name == "Torment"]
        self.assertEqual(len(torment), 1, f"{item_id} missing Torment periodic")
        proc = torment[0]
        self.assertEqual(proc.damage_type, MAGICAL)
        self.assertGreater(proc.every_n_seconds, 0.0)
        # 2% of target max HP per second sustained: at every_n_seconds the
        # per-proc value times (1/interval) must equal 0.02 * max_hp.
        per_proc = proc.resolve_damage(_ctx(target_max_hp=2500.0))
        sustained = per_proc / proc.every_n_seconds
        self.assertAlmostEqual(sustained, 0.02 * 2500.0, places=4)
        # Suffering damage amp is untouched by the Torment add.
        self.assertAlmostEqual(eff.damage_amp_pct, 0.06, places=4)

    def test_sr_liandry_torment(self) -> None:
        self._assert_torment("6653")

    def test_arena_liandry_torment(self) -> None:
        self._assert_torment("226653")


class BlackfireBalefulMerakiPin(unittest.TestCase):
    """2503 + Arena 222503 Baleful Blaze == Meraki 60 (+6% AP) over 3s."""

    def _assert_baleful(self, item_id: str) -> None:
        eff = ITEM_EFFECTS[item_id]
        baleful = [p for p in eff.periodics if p.name == "Baleful Blaze"]
        self.assertEqual(len(baleful), 1)
        proc = baleful[0]
        self.assertEqual(proc.damage_type, MAGICAL)
        self.assertAlmostEqual(proc.every_n_seconds, 0.5, places=4)
        # per-tick (every 0.5s, 6 ticks over 3s): 10 (+1% AP).
        self.assertAlmostEqual(proc.resolve_damage(_ctx(ap=0.0)), 10.0, places=4)
        self.assertAlmostEqual(proc.resolve_damage(_ctx(ap=300.0)), 13.0, places=4)
        # 6-tick total over 3s == Meraki 60 (+6% AP): at 300 AP -> 78.
        total_3s = proc.resolve_damage(_ctx(ap=300.0)) * 6
        self.assertAlmostEqual(total_3s, 60.0 + 0.06 * 300.0, places=2)

    def test_sr_blackfire(self) -> None:
        self._assert_baleful("2503")

    def test_arena_blackfire(self) -> None:
        self._assert_baleful("222503")


class AbilityScorerValuesItemBurn(unittest.TestCase):
    """compute_ability_dps folds the time-based item burn proc DPS."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_liandry_torment_lifts_ability_dps_by_mitigated_burn(self) -> None:
        # Liandry's Torment is the ONLY target-max-HP-dependent term on a
        # Veigar + Liandry build (no Giant Slayer / LDR), so toggling
        # target_max_hp isolates the burn. Expected delta = 2% max HP / s
        # mitigated by MR (no magic pen on Liandry), SR mode_mult 1.0.
        without = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["6653"],
                                      mode="SR", target_mr=30.0, target_max_hp=0.0)
        with_hp = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["6653"],
                                      mode="SR", target_mr=30.0, target_max_hp=2500.0)
        delta = with_hp.total_ability_dps - without.total_ability_dps
        expected = 0.02 * 2500.0 * _armor_factor(30.0)
        self.assertAlmostEqual(delta, expected, places=1)

    def test_demonic_azakana_sibling_also_seen(self) -> None:
        # Sibling-complete: the same code path values Demonic Embrace's
        # Azakana's Gaze (1% max HP / s) for the ability scorer too.
        without = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["4637"],
                                      mode="SR", target_mr=30.0, target_max_hp=0.0)
        with_hp = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["4637"],
                                      mode="SR", target_mr=30.0, target_max_hp=2500.0)
        delta = with_hp.total_ability_dps - without.total_ability_dps
        expected = 0.01 * 2500.0 * _armor_factor(30.0)
        self.assertAlmostEqual(delta, expected, places=1)

    def test_no_burn_build_unchanged_by_target_max_hp(self) -> None:
        # A pure-stat AP item (Rabadon's 3089) carries no periodic, so the
        # ability DPS is target_max_hp-independent (byte-identical) - proves
        # the fold only fires for items that actually have a burn proc.
        a = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3089"],
                                mode="SR", target_mr=30.0, target_max_hp=0.0)
        b = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3089"],
                                mode="SR", target_mr=30.0, target_max_hp=2500.0)
        self.assertAlmostEqual(a.total_ability_dps, b.total_ability_dps, places=4)


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.215.0")


if __name__ == "__main__":
    unittest.main()
