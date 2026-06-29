"""Per-champion kit-weight derivation (core.build_planner.champ_kit_data).

Expands the WP-C1 kit-synergy model from ~6 hand-curated champions to a
genuinely PER-CHAMPION weight vector derived from champions.json ground truth
(damage_distribution + roles/tags + attackrange + attackspeedperlevel +
healing/shielding ratings). The headline guarantee: every one of the 173
champions gets a DISTINCT vector (the WP-C1 fallback collapsed all champs of an
archetype onto a single flat vector).

Ordinal / structural assertions only, per the operator's data-fragile-comparison
rule - never a fragile exact float. ASCII only - use " - " for a clause break.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.archetype_picks import get_archetype_for  # noqa: F401 - parity import
from core.build_planner.champ_kit_data import _AXES, derive_kit_weights
from core.build_planner.kit_synergy import AXES as SYN_AXES
from core.build_planner.kit_synergy import kit_weights

REPO = Path(__file__).resolve().parent.parent
_DS = REPO / "data" / "daemon_slayer"


def _roster():
    patch = (_DS / "current.txt").read_text(encoding="utf-8").strip()
    data = json.loads(
        (_DS / patch / "champions.json").read_text(encoding="utf-8")
    ).get("data", {})
    return [(c.get("name") or cid) for cid, c in data.items()]


class AxisContract(unittest.TestCase):
    def test_axes_match_kit_synergy(self):
        # Anti-drift: the leaf module's axis order MUST equal kit_synergy.AXES so
        # the derived vector is a valid kit_weights base.
        self.assertEqual(_AXES, SYN_AXES)

    def test_dense_over_axes(self):
        w = derive_kit_weights("Miss Fortune")
        self.assertIsNotNone(w)
        self.assertEqual(set(w.keys()), set(_AXES))

    def test_blank_and_unknown_return_none(self):
        # None lets kit_synergy fall back to the archetype base (empty/unknown).
        self.assertIsNone(derive_kit_weights(""))
        self.assertIsNone(derive_kit_weights("NotARealChampion"))


class PerChampionDistinct(unittest.TestCase):
    """The headline guarantee - every champion gets a distinct weight vector."""

    def setUp(self):
        self.roster = _roster()

    def test_full_roster_present(self):
        # Guards a clean-checkout stub silently making the distinctness vacuous.
        self.assertGreater(len(self.roster), 150)

    def test_all_champions_distinct(self):
        sigs = {}
        for nm in self.roster:
            w = derive_kit_weights(nm)
            self.assertIsNotNone(w, nm)
            sigs[nm] = tuple(round(w[a], 4) for a in _AXES)
        distinct = len(set(sigs.values()))
        # Effectively all distinct - allow a tiny slack for two champs with a
        # genuinely identical ground-truth profile.
        self.assertGreaterEqual(
            distinct, len(self.roster) - 3,
            f"only {distinct}/{len(self.roster)} distinct per-champ vectors")

    def test_within_archetype_variation(self):
        # Two carries with different magical share / attack range differ - the
        # WP-C1 model gave both the identical flat carry vector.
        mf = derive_kit_weights("Miss Fortune")
        cait = derive_kit_weights("Caitlyn")
        self.assertNotEqual([mf[a] for a in _AXES], [cait[a] for a in _AXES])


class KnownProfiles(unittest.TestCase):
    """Ordinal sanity of the derived weights for archetype exemplars."""

    def test_crit_marksman(self):
        w = derive_kit_weights("Jinx")  # pure-physical ranged marksman
        self.assertGreater(w["crit"], 0.9)
        self.assertGreater(w["AD"], 0.9)
        self.assertLess(w["AP"], 0.2)

    def test_onhit_marksman(self):
        w = derive_kit_weights("Kog'Maw")  # magical-share marksman -> on-hit
        self.assertGreater(w["on-hit"], w["crit"])
        self.assertGreater(w["AS"], 0.7)

    def test_burst_mage(self):
        w = derive_kit_weights("Annie")
        self.assertGreater(w["AP"], 0.9)
        self.assertLess(w["AD"], 0.2)
        self.assertEqual(w["crit"], 0.0)

    def test_assassin_bonus_ad(self):
        w = derive_kit_weights("Zed")
        self.assertGreaterEqual(w["bonusAD"], 0.6)
        self.assertGreater(w["AD"], 0.8)
        self.assertLess(w["AP"], 0.3)

    def test_tank_hp_offense(self):
        w = derive_kit_weights("Malphite")
        self.assertGreater(w["HP-scaling"], 0.9)

    def test_enchanter_ah(self):
        w = derive_kit_weights("Soraka")
        self.assertGreater(w["AH"], 0.7)
        self.assertLess(w["crit"], 0.1)


class WiredIntoKitWeights(unittest.TestCase):
    """The derived base flows through kit_weights for a non-curated champ."""

    def test_noncurated_champ_uses_derived(self):
        # Annie is NOT in _KIT_TRAITS, so kit_weights == derived (no override,
        # and no gate touches her axes; the >=0 clamp is identity here).
        derived = derive_kit_weights("Annie")
        kw = kit_weights("Annie")
        for a in _AXES:
            self.assertAlmostEqual(kw[a], derived[a], places=6, msg=a)


if __name__ == "__main__":
    unittest.main()
