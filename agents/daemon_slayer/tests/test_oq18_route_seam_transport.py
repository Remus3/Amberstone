"""OQ18 - live-input wiring across the DS HTTP boundary (item-638 pattern).

Proves the server route handlers now READ + thread the producer-only-orphan
live inputs so each live-gated eyeball (LIVE_GAME_GATED_SYNC B31-B33, B4, B12)
becomes a pure HTTP flag flip, and stay BEHAVIOR-PRESERVING: a body that omits
an input is byte-identical to today, while a supplied input DIVERGES. In-process
(route functions take a body dict + read the module ``_CACHE``); no HTTP.

Wired inputs:
  * ``_route_antitank`` gains ``level`` (R17/R39 ramp seam, B12) + ``item_ids`` /
    ``augments`` (P3.2 ``compute_antitank_live`` live build, B4). Omitting both is
    byte-identical to the static ``compute_antitank(champion, mode)`` today.
  * NEW ``_route_summoner_fight_adj`` -> dsp_live_consumers.summoner_fight_adjustments
    (DSP5, B31): player + enemy live summoner sets.
  * NEW ``_route_enemy_rune_threat`` -> dsp_live_consumers.enemy_rune_threat
    (DSP6, B32): enemy live rune set.
  * NEW ``_route_ally_protected_ehp`` -> dsp_live_consumers.ally_protected_ehp
    (DSP7, B33): live ally team's enchanter grants folded into an ally's EHP.

Confirmed API surface before scaffolding:
  * server._route_antitank + server._CACHE.set - agents/daemon_slayer/server.py.
  * compute_antitank(champion, mode, stats, level) + compute_antitank_live(
    snapshot, champion, level, item_ids, mode, augments) - antitank.py:639/731.
  * summoner_fight_adjustments / enemy_rune_threat / ally_protected_ehp -
    dsp_live_consumers.py.
  * Ramp-seeded champ (Aatrox P 4:8) is disjoint from the P3.2 seeded champ
    (Gwen P ap_ratio); Heal id 7, Ignite id 14, Press the Attack rune 8005,
    Janna flat-HP granter - verified against summoners.py / enemy_runes.py /
    _passive_ally_grant_overrides.py.

NO ENGINE_VERSION assertion here (the bump is stamped separately).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.antitank import compute_antitank
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


def setUpModule() -> None:
    server._CACHE.set(_SNAP)


class AntiTankRouteSeamTests(unittest.TestCase):
    """/anti-tank: level ramp seam (B12) + P3.2 live-build seam (B4)."""

    def test_default_off_byte_identical(self):
        # No level / no item_ids -> the static compute_antitank result verbatim.
        route = server._route_antitank({"champion": "Aatrox", "mode": "SR"})
        direct = compute_antitank("Aatrox", mode="SR").to_dict()
        self.assertEqual(route, direct)

    def test_level_ramp_diverges_and_l18_matches_default(self):
        base = server._route_antitank({"champion": "Aatrox", "mode": "SR"})
        l3 = server._route_antitank({"champion": "Aatrox", "mode": "SR", "level": 3})
        l18 = server._route_antitank({"champion": "Aatrox", "mode": "SR", "level": 18})
        # Aatrox P ramps 4%:8% - level 3 discounts toward the early endpoint.
        self.assertLess(l3["antitank_score"], l18["antitank_score"])
        # level 18 == level None (the docstring parity contract).
        self.assertAlmostEqual(l18["antitank_score"], base["antitank_score"])

    def test_live_build_scales_seeded_row(self):
        # Gwen P carries an ap_ratio - a Rabadon's (3089) build resolves AP and
        # scales the %max-HP magnitude above the naked build.
        naked = server._route_antitank({"champion": "Gwen", "mode": "SR", "level": 11})
        built = server._route_antitank(
            {"champion": "Gwen", "mode": "SR", "level": 11, "item_ids": ["3089"]}
        )
        self.assertGreater(built["antitank_score"], naked["antitank_score"])

    def test_empty_item_ids_byte_identical(self):
        # An empty item_ids list stays on the static path (no live build).
        base = server._route_antitank({"champion": "Gwen", "mode": "SR"})
        empty = server._route_antitank(
            {"champion": "Gwen", "mode": "SR", "item_ids": []}
        )
        self.assertEqual(empty, base)


class SummonerFightAdjRouteTests(unittest.TestCase):
    """/summoner-fight-adj -> DSP5 (B31)."""

    def test_self_heal_ehp_bonus(self):
        r = server._route_summoner_fight_adj(
            {"self_spell_ids": [7], "level": 11}
        )
        self.assertGreater(r["self_ehp_bonus"], 0.0)

    def test_enemy_ignite_antiheal(self):
        r = server._route_summoner_fight_adj({"enemy_spell_ids": [14]})
        self.assertGreater(r["enemy_antiheal_pct"], 0.0)

    def test_empty_noop(self):
        r = server._route_summoner_fight_adj({})
        self.assertEqual(r["self_ehp_bonus"], 0.0)
        self.assertEqual(r["self_cc_discount_pct"], 0.0)
        self.assertEqual(r["enemy_antiheal_pct"], 0.0)


class EnemyRuneThreatRouteTests(unittest.TestCase):
    """/enemy-rune-threat -> DSP6 (B32)."""

    def test_press_the_attack_incoming_amp(self):
        r = server._route_enemy_rune_threat({"enemy_rune_ids": [8005], "level": 11})
        self.assertAlmostEqual(r["incoming_amp_pct"], 0.08)
        self.assertGreater(r["ehp_divisor"], 1.0)

    def test_empty_noop(self):
        r = server._route_enemy_rune_threat({})
        self.assertEqual(r["incoming_amp_pct"], 0.0)
        self.assertEqual(r["ehp_divisor"], 1.0)


class AllyProtectedEhpRouteTests(unittest.TestCase):
    """/ally-protected-ehp -> DSP7 (B33)."""

    def test_ally_grant_uplift(self):
        solo = server._route_ally_protected_ehp(
            {"champion": "Ashe", "level": 11, "mode": "SR"}
        )
        protected = server._route_ally_protected_ehp(
            {
                "champion": "Ashe",
                "level": 11,
                "mode": "SR",
                "ally_grant_champions": ["Janna"],
            }
        )
        # Janna E folds a flat-HP shield -> higher blended EHP than solo.
        self.assertGreater(protected["blended_ehp"], solo["blended_ehp"])

    def test_solo_no_grant(self):
        solo = server._route_ally_protected_ehp(
            {"champion": "Ashe", "level": 11, "mode": "SR"}
        )
        self.assertGreater(solo["blended_ehp"], 0.0)


if __name__ == "__main__":
    unittest.main()
