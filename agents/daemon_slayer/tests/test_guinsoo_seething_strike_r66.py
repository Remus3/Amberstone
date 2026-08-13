"""R66 (2026-07-03) - Guinsoo's Rageblade "Seething Strike" conditional AS.

Meraki 16.13.1 item 3124 passive "Seething Strike": basic attacks grant
8% bonus attack speed for 3 seconds, stacking up to 4 times (32% total).
Modeled on the EXISTING ungated conditional-AS lane (``bonus_as_conditional``,
the same field Yun Tal Flurry carries at 0.08 with NO flag - see
test_conditional_as_base_fold_r42.py:11), pinned at the full-stack
steady state per repo convention (Black Cleaver 5-stack shred, Mejai's
full-stack AP): a Guinsoo carry auto-attacking continuously in a
sustained fight sits at 4 stacks. Gemini director approved UNGATED -
no new seam, no flag.

The fold itself is the R42 base_as-scaled fold (dps.py cond_as block:
cond_as is a bonus-AS FRACTION folded as ``innate_base_as * cond_as``
onto final AS, re-clamped at the 2.5 League hard cap), so the DPS
characterization here mirrors test_conditional_as_base_fold_r42.py:
Guinsoo's two periodics (Wrath flat 30 magic on-hit, Phantom Hit every
3rd attack) are per-attack, so ``weighted_dps`` stays exactly affine in
rotation AS and Dagger (1042, pure +AS) calibrates the AS-to-DPS slope.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest import mock

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import total_conditional_as

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)


class EngineVersion(unittest.TestCase):
    def test_engine_version_pinned(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.277.1")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.277.1")


class SeethingStrikeRegistryPins(unittest.TestCase):
    """Full-stack steady-state pin: 8% x 4 stacks = 0.32 bonus-AS fraction."""

    def test_guinsoo_sr_bonus_as_conditional(self) -> None:
        eff = ITEM_EFFECTS.get("3124")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.bonus_as_conditional, 0.32, places=3)

    def test_guinsoo_arena_bonus_as_conditional(self) -> None:
        eff = ITEM_EFFECTS.get("223124")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.bonus_as_conditional, 0.32, places=3)

    def test_guinsoo_periodics_untouched(self) -> None:
        # Wrath + Phantom Hit predate R66 and must survive the field add.
        for item_id in ("3124", "223124"):
            names = {p.name for p in ITEM_EFFECTS[item_id].periodics}
            self.assertEqual(names, {"Wrath", "Phantom Hit"})


class SeethingStrikeMerakiTruth(unittest.TestCase):
    """Hermetic drift guard: registry value derives from the vendored
    Meraki 16.13.1 snapshot text, so a future patch changing the per-stack
    pct or the stack cap fails HERE instead of silently drifting.
    """

    def test_registry_matches_meraki_per_stack_times_cap(self) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        passives = doc["items"]["3124"]["passives"]
        seething = next(
            (p for p in passives if p.get("name") == "Seething Strike"),
            None,
        )
        self.assertIsNotNone(
            seething, "Meraki 3124 has no 'Seething Strike' passive"
        )
        text = seething["effects"]
        # Meraki wiki-markup shape: "grant {{as|8% '''bonus''' attack
        # speed}} ... stacking up to 4 times".
        m_pct = re.search(r"grant \{\{as\|(\d+)%", text)
        m_cap = re.search(r"stacking up to (\d+) times", text)
        self.assertIsNotNone(m_pct, f"per-stack pct not found in: {text!r}")
        self.assertIsNotNone(m_cap, f"stack cap not found in: {text!r}")
        pct = int(m_pct.group(1))
        cap = int(m_cap.group(1))
        self.assertEqual(pct, 8)
        self.assertEqual(cap, 4)
        eff = ITEM_EFFECTS.get("3124")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(
            eff.bonus_as_conditional, pct / 100.0 * cap, places=6
        )


class SeethingStrikeCondAsFold(unittest.TestCase):
    """The 0.32 rides the R42 base_as-scaled cond_as fold in compute_dps.

    Counterfactual built by monkeypatching ``dps.total_conditional_as``
    to 0.0 (identical resolved stats, only the fold differs), exactly as
    test_conditional_as_base_fold_r42.py does for Yun Tal.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_guinsoo_gain_matches_base_as_scaled_fraction(self) -> None:
        cid, level = "Caitlyn", 11  # marksman, base AS < 1, pure-AA rotation
        gb = ["3124"]                # Guinsoo carries cond_as
        gb_dagger = ["3124", "1042"]  # + pure-AS calibration point
        with mock.patch(
            "agents.daemon_slayer.dps.total_conditional_as", return_value=0.0
        ):
            off = compute_dps(self.snap, cid, level=level, item_ids=gb,
                              target_armor=80)
            cal = compute_dps(self.snap, cid, level=level, item_ids=gb_dagger,
                              target_armor=80)
        on = compute_dps(self.snap, cid, level=level, item_ids=gb,
                         target_armor=80)
        a0 = off.stats["as"]
        a_cal = cal.stats["as"]
        base_as = float(
            (self.snap.champion(cid).get("stats") or {}).get("attackspeed", 0.0)
        )
        cond = total_conditional_as([ITEM_EFFECTS["3124"]])
        # Preconditions (fail loudly if the fixture stops exercising the path).
        self.assertGreater(cond, 0.0)
        self.assertGreater(base_as, 0.0)
        self.assertLess(base_as, 1.0)
        self.assertGreater(a_cal, a0)             # Dagger really raised AS
        self.assertNotEqual(on.weighted_dps, off.weighted_dps)  # fold fired
        self.assertLess(a0 + base_as * cond, 2.5)  # under the AS hard cap
        # weighted_dps = c0 + c1*AS; c1 from the pure-AS calibration build.
        c1 = (cal.weighted_dps - off.weighted_dps) / (a_cal - a0)
        predicted_correct = off.weighted_dps + c1 * (base_as * cond)
        predicted_wrong = off.weighted_dps + c1 * cond  # raw-fraction bug
        self.assertAlmostEqual(
            on.weighted_dps, predicted_correct,
            delta=abs(predicted_correct) * 0.005,
        )
        self.assertLess(
            abs(on.weighted_dps - predicted_correct),
            abs(on.weighted_dps - predicted_wrong),
        )


class SiblingGuards(unittest.TestCase):
    """Yun Tal keeps its own uptime-weighted 0.08; sums stay per-item."""

    def test_yun_tal_sr_unchanged(self) -> None:
        self.assertAlmostEqual(
            ITEM_EFFECTS["3032"].bonus_as_conditional, 0.08, places=3
        )

    def test_yun_tal_arena_unchanged(self) -> None:
        self.assertAlmostEqual(
            ITEM_EFFECTS["223032"].bonus_as_conditional, 0.08, places=3
        )

    def test_total_conditional_as_over_guinsoo_effect(self) -> None:
        self.assertAlmostEqual(
            total_conditional_as([ITEM_EFFECTS["3124"]]), 0.32, places=6
        )


if __name__ == "__main__":
    unittest.main()
