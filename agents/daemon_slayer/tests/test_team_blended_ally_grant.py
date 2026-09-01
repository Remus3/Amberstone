"""Term A - opt-in ally-granted (team_blended) EHP ranking.

rank_items_by_ehp(score_by="team_blended") adds the flat HP an item confers on
TEAMMATES (_item_ally_grant.py, sourced from the curated enchanter_items.json
per-proc block) to the item's EHP delta, amortized by the shipped
_ALLY_SHIELD_HEAL_PROB uptime midpoint and gated on the champion's ally-reach
signal (_champion_ally_reach.py, read from champion_abilities.json "affects").

Motivating defect, measured live at 1.219.0 across build depths 0-3: ds.ehp
prices only the champion's OWN effective HP, so Taric's 69.8%-presence Locket
sat at #25 and Thresh's 88.3%-presence Locket at #20 of a ~140 pool, and NO
shipped build-order variant bought either.

Two invariants: DEFAULT (score_by="blended") byte-identical to the pre-Term-A
ranker, including the new row fields collapsing to their blended identity; and
the gate is load-bearing - a same-cohort champion with no ally reach (Rammus)
must not move a single rank. ASCII only.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION, server
from agents.daemon_slayer._champion_ally_reach import champion_ally_reach
from agents.daemon_slayer._item_ally_grant import (
    ally_grant_hp,
    total_item_ally_grant_hp,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp

_LOCKET = "3190"        # ally shield, 290 + 4.12/lvl, 3 targets
_REDEMPTION = "3107"    # ally heal; grants the BUYER zero health/armor/MR
_KNIGHTS_VOW = "3109"   # documented exclusion - ally-build-dependent
_ZEKES = "3050"         # documented exclusion - no ally grant at 16.14.1
_BANDLEPIPES = "2524"   # documented exclusion - ally attack speed, not EHP

# Tank-routed champions whose kit reaches allies. Each is individually
# justified in the Term A spec; they are NOT certified by count.
_GATE_CHAMPS = (
    "Taric", "Thresh", "Braum", "Shen", "Galio", "TahmKench",
    "Alistar", "Bard", "Rakan", "KSante", "Nunu", "Rell",
)
# Same 28-item build-order cohort, no ally reach. Ornn and Sejuani are strict
# "allies" hits that are deliberately EXCLUDED as parser false positives:
# Ornn P upgrades ITEMS (economy, not durability); Sejuani E's "Allies" means
# allied attacks apply HER frost - the direction of benefit is reversed.
_CONTROL_CHAMPS = ("Rammus", "Malphite", "Amumu", "Ornn", "Sejuani")


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)

    def _rank_of(self, champ, item_id, score_by, level=11):
        res = rank_items_by_ehp(
            self.snap, champ, level, mode="SR", top_n=200, score_by=score_by,
        )
        for i, row in enumerate(res.ranked):
            if row.item_id == item_id:
                return i + 1, row
        return None, None


class ItemAllyGrantRegistryTests(unittest.TestCase):
    def test_locket_per_proc_times_targets(self) -> None:
        # (290 base + 4.12/lvl * 10) * 3 targets. The snapshot's own notes field
        # independently states "per-proc shield at lvl 11 approx 331".
        self.assertAlmostEqual(ally_grant_hp(_LOCKET, 11), 993.6, places=1)

    def test_documented_exclusions_are_zero(self) -> None:
        for iid in (_KNIGHTS_VOW, _ZEKES, _BANDLEPIPES):
            self.assertEqual(ally_grant_hp(iid, 11), 0.0, f"item {iid}")

    def test_unknown_and_blank_fail_soft(self) -> None:
        self.assertEqual(ally_grant_hp("9999", 11), 0.0)
        self.assertEqual(ally_grant_hp("", 11), 0.0)
        self.assertEqual(total_item_ally_grant_hp([], 11), 0.0)
        self.assertEqual(total_item_ally_grant_hp(None, 11), 0.0)

    def test_total_is_additive(self) -> None:
        self.assertAlmostEqual(
            total_item_ally_grant_hp([_LOCKET, _REDEMPTION], 11),
            ally_grant_hp(_LOCKET, 11) + ally_grant_hp(_REDEMPTION, 11),
            places=6,
        )


class ChampionAllyReachGateTests(unittest.TestCase):
    def test_gate_champions_reach_allies(self) -> None:
        for champ in _GATE_CHAMPS:
            self.assertTrue(champion_ally_reach(champ), champ)

    def test_control_champions_do_not(self) -> None:
        for champ in _CONTROL_CHAMPS:
            self.assertFalse(champion_ally_reach(champ), champ)

    def test_display_name_folds_to_ddragon_id(self) -> None:
        # A caller handing over a live-game display name must not silently miss.
        self.assertTrue(champion_ally_reach("Tahm Kench"))
        self.assertTrue(champion_ally_reach("K'Sante"))

    def test_blank_and_unknown_fail_soft(self) -> None:
        self.assertFalse(champion_ally_reach(""))
        self.assertFalse(champion_ally_reach(None))
        self.assertFalse(champion_ally_reach("Nonexistent"))


class TeamBlendedRankingTests(_Base):
    def test_locket_rises_materially_for_taric_and_thresh(self) -> None:
        """The acceptance gate: the two named champions must MOVE, not merely differ."""
        for champ in ("Taric", "Thresh"):
            base, _ = self._rank_of(champ, _LOCKET, "blended")
            team, row = self._rank_of(champ, _LOCKET, "team_blended")
            self.assertIsNotNone(base, f"{champ}: Locket must be a candidate")
            self.assertGreater(base, 15, f"{champ}: precondition - starts buried")
            self.assertLess(team, base, f"{champ}: must rise")
            self.assertGreaterEqual(
                base - team, 10, f"{champ}: rise must be material, not marginal",
            )
            self.assertLessEqual(team, 8, f"{champ}: must reach the buildable head")
            self.assertGreater(row.delta_team_blended_ehp, row.delta_ehp)

    def test_every_gate_champion_rises(self) -> None:
        for champ in _GATE_CHAMPS:
            base, _ = self._rank_of(champ, _LOCKET, "blended")
            team, _ = self._rank_of(champ, _LOCKET, "team_blended")
            self.assertLess(team, base, f"{champ}: gate fired but rank did not move")

    def test_gate_is_load_bearing_controls_do_not_move(self) -> None:
        """Without the champion gate this term would lift Locket for Rammus too."""
        for champ in _CONTROL_CHAMPS:
            base, brow = self._rank_of(champ, _LOCKET, "blended")
            team, trow = self._rank_of(champ, _LOCKET, "team_blended")
            self.assertEqual(base, team, f"{champ}: gate leak - rank moved")
            self.assertEqual(
                trow.delta_team_blended_ehp, trow.delta_ehp,
                f"{champ}: gate leak - delta moved",
            )
            self.assertEqual(brow.delta_ehp, trow.delta_ehp, champ)

    def test_redemption_zero_self_ehp_still_gains(self) -> None:
        """Redemption grants the BUYER nothing, so its self-delta is exactly 0.

        That makes it the cleanest possible proof the term prices ally value and
        not some incidental self-stat.
        """
        for champ in ("Taric", "Thresh"):
            base, brow = self._rank_of(champ, _REDEMPTION, "blended")
            team, trow = self._rank_of(champ, _REDEMPTION, "team_blended")
            self.assertEqual(brow.delta_ehp, 0.0, champ)
            self.assertGreater(trow.delta_team_blended_ehp, 0.0, champ)
            self.assertLess(team, base, champ)

    def test_default_is_byte_identical(self) -> None:
        for champ in ("Taric", "Thresh", "Rammus", "Aatrox", "Ornn"):
            a = rank_items_by_ehp(self.snap, champ, 11, mode="SR", top_n=200)
            b = rank_items_by_ehp(
                self.snap, champ, 11, mode="SR", top_n=200, score_by="blended",
            )
            self.assertEqual(
                [r.item_id for r in a.ranked], [r.item_id for r in b.ranked], champ,
            )
            self.assertEqual(
                [r.delta_ehp for r in a.ranked], [r.delta_ehp for r in b.ranked], champ,
            )

    def test_new_row_fields_collapse_to_blended_identity_when_off(self) -> None:
        for champ in ("Taric", "Rammus", "Janna"):
            res = rank_items_by_ehp(self.snap, champ, 11, mode="SR", top_n=200)
            for row in res.ranked:
                self.assertEqual(
                    row.delta_team_blended_ehp, row.delta_ehp,
                    f"{champ} {row.item_id}",
                )

    def test_rejects_unknown_score_by(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ehp(self.snap, "Taric", 11, mode="SR", score_by="bogus")


class EngineVersionPinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.279.0")


if __name__ == "__main__":
    unittest.main()
