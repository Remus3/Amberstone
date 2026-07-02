"""OQ17 - /rank* HTTP-boundary seam transport (item-638 pattern).

Proves the server route handlers now READ + thread the engine-only default-OFF
seams so each becomes a pure HTTP flag flip, and stay BEHAVIOR-PRESERVING: a
body that omits a flag is byte-identical to the default-off result, while a
flag turned ON DIVERGES. In-process (route functions take a body dict + read
the module ``_CACHE``); no HTTP.

Route homes (chosen where each seam actually has effect):
  * ``_route_burst`` (compute_burst_damage direct; also gains ``runes`` parsing)
    - assume_takedown (DSV2), assume_ability_amp (DSV4), score_completion_runes
      (DSP4), gate_target_hp_amp (R51), gate_caster_hp_amp + caster_current_hp_pct
      (R53). The three rune-gate seams are /burst-scoped (single-build burst
      NUMBER) exactly like R30 assume_magic_burst: a flat keystone amp washes out
      of the ranker delta, so it only reads meaningfully on the direct route.
  * ``_route_rank_assassin`` (rank_items_by_burst, already forwards these) -
    assume_takedown (DSV2), assume_squishy_target (DSV3), assume_ability_amp
    (DSV4), target_preset (DSP8).
  * ``_route_dps`` (compute_dps direct, /dps-scoped like R7/R12) -
    apply_melee_aa_gate (B1).

R50 apply_all_out_bonus is EXCLUDED from OQ17: it is a load-time
AbilitiesSnapshot flag, not a per-call compute param, so it is not a pure
flag-flip and needs per-request snapshot construction (separate task).

Confirmed API surface before scaffolding:
  * server._route_burst / _route_rank_assassin / _route_dps + server._CACHE.set
    - agents/daemon_slayer/server.py.
  * compute_burst_damage accepts runes / assume_takedown / assume_ability_amp /
    score_completion_runes / gate_target_hp_amp / gate_caster_hp_amp /
    caster_current_hp_pct - burst.py:461-492.
  * rank_items_by_burst forwards assume_takedown / assume_squishy_target /
    assume_ability_amp / target_preset - burst.py:1596-1628.
  * compute_dps accepts apply_melee_aa_gate - dps.py:628.
  * BurstRankResult.to_dict exposes target_armor / target_mr - burst.py.
  * Divergence scenarios lifted from the engine seam tests:
    Shield Bash 8401 (DSP4), Last Stand 8299 (R53), Cut Down 8017 (R51),
    Veigar+Shojin 3161 (DSV4), Runaan's 3085 melee gate (B1), Zed squishy (DSV3),
    tank preset resists (DSP8).

NO ENGINE_VERSION assertion here (the bump is stamped separately).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.burst import _assumed_squishy_target_armor
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()

# Representative burst target (matches the engine seam tests).
_TGT = dict(target_armor=80.0, target_mr=60.0, target_max_hp=2000.0,
            target_bonus_hp=600.0)


def setUpModule() -> None:
    server._CACHE.set(_SNAP)


class BurstRouteSeamTests(unittest.TestCase):
    """/burst: runes + the six compute-direct seams (DSV2/DSV4/DSP4/R51/R53)."""

    def test_default_off_byte_identical(self):
        body = {"champion": "Leona", "level": 11, "mode": "SR", **_TGT}
        a = server._route_burst(dict(body))
        off = server._route_burst(dict(
            body, assume_takedown=False, assume_ability_amp=False,
            score_completion_runes=False, gate_target_hp_amp=False,
            gate_caster_hp_amp=False))
        self.assertEqual(a, off)

    def test_assume_takedown_execute_diverges(self):
        # DSV2: Collector (6676) kill-state execute (5% target max HP true) lands
        # when the build carries Collector and target_max_hp is supplied.
        body = {"champion": "Zed", "level": 11, "mode": "SR",
                "items": ["6676"], **_TGT}
        off = server._route_burst(dict(body))["total_burst_damage"]
        on = server._route_burst(dict(body, assume_takedown=True))["total_burst_damage"]
        self.assertGreater(on, off)

    def test_assume_ability_amp_diverges(self):
        # DSV4: Spear of Shojin (3161) ability amp raises Veigar's ability damage.
        body = {"champion": "Veigar", "level": 11, "mode": "SR", "items": ["3161"],
                "target_mr": 60.0, "target_max_hp": 2000.0}
        off = server._route_burst(dict(body))["total_burst_damage"]
        on = server._route_burst(dict(body, assume_ability_amp=True))["total_burst_damage"]
        self.assertGreater(on, off)

    def test_score_completion_runes_diverges(self):
        # DSP4: Shield Bash 8401 is a completion rune, skipped unless flagged.
        # Requires the route to parse runes (new in OQ17).
        body = {"champion": "Leona", "level": 11, "mode": "SR",
                "runes": [8401], **_TGT}
        off = server._route_burst(dict(body))["total_burst_damage"]
        on = server._route_burst(dict(body, score_completion_runes=True))["total_burst_damage"]
        self.assertGreater(on, off)

    def test_gate_target_hp_amp_diverges(self):
        # R51: Cut Down 8017 amps targets ABOVE 60% HP. OFF applies it
        # unconditionally (1.08); ON at 30% target HP does not -> OFF > ON.
        body = {"champion": "Leona", "level": 11, "mode": "SR",
                "runes": [8017], "target_current_hp_pct": 0.30, **_TGT}
        off = server._route_burst(dict(body))["total_burst_damage"]
        on = server._route_burst(dict(body, gate_target_hp_amp=True))["total_burst_damage"]
        self.assertGreater(off, on)

    def test_gate_caster_hp_amp_diverges(self):
        # R53: Last Stand 8299 amps by caster HP. OFF feeds full HP (no amp);
        # ON feeds caster_current_hp_pct=0.30 -> 1.11 amp.
        body = {"champion": "Garen", "level": 11, "mode": "SR",
                "runes": [8299], "caster_current_hp_pct": 0.30, **_TGT}
        off = server._route_burst(dict(body))["total_burst_damage"]
        on = server._route_burst(dict(body, gate_caster_hp_amp=True))["total_burst_damage"]
        self.assertGreater(on, off)


class RankAssassinRouteSeamTests(unittest.TestCase):
    """/rank-assassin: DSV2/DSV3/DSV4/DSP8 (already forwarded by the ranker)."""

    BODY = {"champion": "Zed", "level": 11, "mode": "SR", "top": 20}

    def test_default_off_byte_identical(self):
        a = server._route_rank_assassin(dict(self.BODY))
        off = server._route_rank_assassin(dict(
            self.BODY, assume_takedown=False, assume_squishy_target=False,
            assume_ability_amp=False))
        self.assertEqual(a, off)

    def test_assume_squishy_target_substitutes_armor(self):
        # DSV3: substitutes the squishy-carry armor curve for the absent target.
        off = server._route_rank_assassin(dict(self.BODY))
        on = server._route_rank_assassin(dict(self.BODY, assume_squishy_target=True))
        self.assertEqual(off["target_armor"], 0.0)
        self.assertAlmostEqual(on["target_armor"], _assumed_squishy_target_armor(11))

    def test_target_preset_substitutes_both_resists(self):
        # DSP8: the tank preset substitutes both armor and MR (L11 = 180 / 110).
        off = server._route_rank_assassin(dict(self.BODY))
        on = server._route_rank_assassin(dict(self.BODY, target_preset="tank"))
        self.assertEqual((off["target_armor"], off["target_mr"]), (0.0, 0.0))
        self.assertAlmostEqual(on["target_armor"], 180.0)
        self.assertAlmostEqual(on["target_mr"], 110.0)

    def test_takedown_and_ability_amp_accepted(self):
        # DSV2 / DSV4 thread through the ranker without error (their ranking-delta
        # divergence is champ/build specific and owned by /burst + engine tests).
        out = server._route_rank_assassin(dict(
            self.BODY, assume_takedown=True, assume_ability_amp=True))
        self.assertIn("ranked", out)


class DpsRouteMeleeGateTests(unittest.TestCase):
    """/dps: apply_melee_aa_gate (B1), /dps-scoped like R7/R12."""

    def test_default_off_byte_identical(self):
        body = {"champion": "Briar", "level": 11, "mode": "SR", "items": ["3085"]}
        a = server._route_dps(dict(body))
        off = server._route_dps(dict(body, apply_melee_aa_gate=False))
        self.assertEqual(a, off)

    def test_melee_gate_drops_ranged_bolt_credit(self):
        # B1: Runaan's 3085 Wind's Fury bolts are ranged_only; the gate drops
        # them on a melee champ (Briar, 125 attackrange).
        body = {"champion": "Briar", "level": 11, "mode": "SR", "items": ["3085"]}
        off = server._route_dps(dict(body))["weighted_dps"]
        on = server._route_dps(dict(body, apply_melee_aa_gate=True))["weighted_dps"]
        self.assertGreater(off, on)


if __name__ == "__main__":
    unittest.main()
