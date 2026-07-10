"""R88 - Armored Advance (3174) Plating basic-attack DR (sibling of R80 3047).

Armored Advance (item 3174) is the tier-3 upgrade boot of Plated Steelcaps and
carries the IDENTICAL DDragon 16.13.1 "Plating" passive that R80 modeled on
Plated Steelcaps (3047): "Reduces incoming damage from Attacks by 10%". Its
registry entry was a bare ``defensive_only`` NOTE with ZERO EHP credit for the
plating, though the item's +armor already counted - a sibling-carrier gap.

R88 sets the EXISTING ``basic_attack_damage_reduction`` field (added by R80,
defaults 0.0) to 0.10 so the plating earns EHP credit through the SAME
default-OFF ``assume_item_aa_dr`` physical-denominator lane
(``item_aa_dr_multiplier``). No new field, no new flag, no engine wiring - a
one-item data refinement that mirrors 3047 exactly.

DEFAULT-OFF stays byte-identical: ``assume_item_aa_dr=False`` short-circuits to
the identity 1.0 before any item is inspected. The item's separate "Noxian
Endurance" physical-shield passive is intentionally UNMODELED (conditional, out
of scope).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import item_aa_dr_multiplier

ARMORED_ADVANCE = "3174"
STEELCAPS = "3047"
AA_DR = 0.10


class ArmoredAdvancePlatingTests(unittest.TestCase):
    def test_armored_advance_field_pinned(self):
        # (a) 3174 now carries the same 10% Plating basic-attack DR as 3047.
        self.assertAlmostEqual(
            ITEM_EFFECTS[ARMORED_ADVANCE].basic_attack_damage_reduction, AA_DR
        )

    def test_itemeffect_default_field_zero(self):
        # (b) Regression guard: the field still defaults 0.0 on a bare entry, so
        # every non-carrier item stays byte-identical.
        self.assertEqual(
            ItemEffect(item_id="x", name="x").basic_attack_damage_reduction, 0.0
        )

    def test_multiplier_matches_steelcaps_when_armed(self):
        # (c) Both boots carry Plating 0.10 -> IDENTICAL armed multiplier, and it
        # is a real reduction (< 1.0), not a silent no-op.
        aa = item_aa_dr_multiplier([ARMORED_ADVANCE], assume_item_aa_dr=True)
        steelcaps = item_aa_dr_multiplier([STEELCAPS], assume_item_aa_dr=True)
        self.assertAlmostEqual(aa, steelcaps)
        self.assertLess(aa, 1.0)

    def test_off_is_byte_identical(self):
        # (d) DEFAULT-OFF short-circuits to identity 1.0 before any item is read.
        self.assertEqual(
            item_aa_dr_multiplier([ARMORED_ADVANCE], assume_item_aa_dr=False), 1.0
        )

    def test_plating_credited_in_note(self):
        # (e) The note documents the newly-credited Plating mechanic.
        self.assertIn("Plating", ITEM_EFFECTS[ARMORED_ADVANCE].note)


if __name__ == "__main__":
    unittest.main()
