"""DSP4 self-rune completion seam - Shield Bash 8401 + COMPLETION_RUNE_IDS.

Shield Bash (Resolve row1) is the one previously-unmodeled LIVE, pickable rune
that deals direct champion damage on a proc. DDragon 16.12.1 runesReforged.json
longDesc verbatim: "Whenever you gain a new shield, your next basic attack
against a champion deals 5 - 30 (+2.5% Bonus Health) (+15.0% New Shield Amount)
bonus adaptive damage."

"adaptive" is the damage TYPE (physical when bonus AD >= bonus AP else magic),
NOT a stat-scaled coefficient - the scaling sources are bonus health + the new
shield amount, so there is NO AD/AP coefficient. The burst scorer has no live
shield signal, so it passes shield_amount=0.0 and scores the shield-independent
5-30 + 2.5% bonus HP floor (best-case-shielded approximation); a future live
caster-stat producer supplies the shield amount for the +15% term.

NO ENGINE_VERSION assertions here (the orchestrator owns the bump).
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import rune_procs as rp
from agents.daemon_slayer.rune_procs import (
    COMPLETION_RUNE_IDS,
    RUNE_PROCS,
    compute_rune_proc_damage,
)


def _lerp(low, high, level):
    """Mirror the module's 1..18 17-step ramp for hand-recompute."""
    lvl = max(1, min(18, int(level)))
    return low + (high - low) * (lvl - 1) / 17.0


class ShieldBashRegistryTests(unittest.TestCase):
    def test_present(self):
        self.assertIn(8401, RUNE_PROCS)

    def test_name_tree_type(self):
        proc = RUNE_PROCS[8401]
        self.assertEqual(proc.name, "Shield Bash")
        self.assertEqual(proc.tree, "Resolve")
        self.assertEqual(proc.proc_type, "on_proc_burst")

    def test_condition_shield_gated(self):
        self.assertEqual(RUNE_PROCS[8401].condition, "shield_gated")


class ShieldBashComputeTests(unittest.TestCase):
    def test_level1_floor_no_extras(self):
        # 5 - 30 by level; level 1 -> 5.0, no shield / bonus HP.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=1), 5.0, places=4
        )

    def test_level18_floor(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=18), 30.0, places=4
        )

    def test_midlevel_lerp(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=9),
            _lerp(5.0, 30.0, 9), places=4,
        )

    def test_bonus_hp_term(self):
        # +2.5% bonus health; 0.025 * 1000 = 25 on top of the 5.0 floor.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=1, bonus_hp=1000.0),
            5.0 + 25.0, places=4,
        )

    def test_shield_amount_term(self):
        # +15% of the new shield amount; 0.15 * 400 = 60 on top of the floor.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=1, shield_amount=400.0),
            5.0 + 60.0, places=4,
        )

    def test_all_terms(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(
                8401, level=1, bonus_hp=1000.0, shield_amount=400.0
            ),
            5.0 + 25.0 + 60.0, places=4,
        )

    def test_no_ad_ap_scaling(self):
        # "adaptive" is the damage TYPE, not a coefficient: ad/ap do not change it.
        base = compute_rune_proc_damage(8401, level=7)
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=7, ad=300.0, ap=300.0),
            base, places=4,
        )

    def test_failsoft_bad_bonus_hp(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=1, bonus_hp=None),
            5.0, places=4,
        )

    def test_failsoft_bad_shield_amount(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8401, level=1, shield_amount=None),
            5.0, places=4,
        )


class CompletionRuneIdsTests(unittest.TestCase):
    def test_shield_bash_in_completion_set(self):
        self.assertIn(8401, COMPLETION_RUNE_IDS)

    def test_is_frozenset(self):
        self.assertIsInstance(COMPLETION_RUNE_IDS, frozenset)

    def test_original_runes_not_in_completion_set(self):
        # The pre-DSP4 runes are unconditionally consumed (NOT seam-gated), so
        # they must stay out of the completion set or the seam would silently
        # gate live behaviour.
        for rid in (8112, 8005, 8010, 8214, 8437, 8439, 9923, 8008):
            self.assertNotIn(rid, COMPLETION_RUNE_IDS)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self):
        with open(rp.__file__, "rb") as fh:
            raw = fh.read()
        self.assertEqual(
            [b for b in raw if b > 0x7F], [],
            "rune_procs.py must contain 0 non-ASCII bytes",
        )

    def test_test_module_ascii(self):
        with open(__file__, "rb") as fh:
            raw = fh.read()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
