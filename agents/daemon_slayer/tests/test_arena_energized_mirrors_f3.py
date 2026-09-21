"""Arena Energized-family mirrors credit their OWN DDragon line (doctrine B).

F3 (16.18.1 validation, pre-dating the refresh): Arena Stormrazor 223095
modelled a "Stormraider" PHYSICAL proc (0.75 * bonus AD every 30s) - a
mechanic the item no longer has. Its own DDragon 223095 description, at
BOTH 16.15.1 and 16.18.1, reads Energized "Bolt": the Energized Attack
applies bonus MAGIC damage, and "Energized stacks twice as fast in
Arena". DDragon carries no Bolt magnitude (RM-323 class: the <stats>
block is base stats only), so the magnitude rides the SR twin (3095,
Meraki 100 magic) while the cadence is the Arena-stated one: SR 4.0s
halved to 2.0s.

Sibling: Arena Rapid Firecannon 223094. Its own DDragon line states
"Your Energized Attack applies 200 bonus magic damage" (16.15.1 and
16.18.1), against SR 3094's "deals 40 bonus magic damage". The row
inherited SR's 40 because the Meraki audit mirrored it (Meraki has no
223094 entry); doctrine B makes the explicitly-stated Arena value win.

Assertions are on the computed proc quantity, never a cross-item DPS
comparison.
"""

import unittest

from agents.daemon_slayer.effects import ITEM_EFFECTS, MAGICAL, CallContext

_CTX = CallContext(base_ad=70.0, bonus_ad=100.0, level=13)


def _proc(item_id: str):
    e = ITEM_EFFECTS[item_id]
    assert len(e.periodics) == 1, item_id
    return e.periodics[0]


class ArenaStormrazorEnergizedBoltTests(unittest.TestCase):
    def test_223095_is_energized_bolt_magic(self) -> None:
        p = _proc("223095")
        self.assertEqual(p.name, "Energized Bolt")
        self.assertEqual(p.damage_type, MAGICAL)

    def test_223095_magnitude_rides_sr_twin(self) -> None:
        self.assertEqual(
            _proc("223095").resolve_damage(_CTX),
            _proc("3095").resolve_damage(_CTX),
        )
        self.assertEqual(_proc("223095").resolve_damage(_CTX), 100.0)

    def test_223095_charges_twice_as_fast_as_sr(self) -> None:
        self.assertAlmostEqual(
            _proc("223095").every_n_seconds,
            _proc("3095").every_n_seconds / 2.0,
            places=6,
        )

    def test_223095_does_not_scale_with_bonus_ad(self) -> None:
        lo = _proc("223095").resolve_damage(CallContext(base_ad=70.0, bonus_ad=0.0, level=13))
        hi = _proc("223095").resolve_damage(CallContext(base_ad=70.0, bonus_ad=300.0, level=13))
        self.assertEqual(lo, hi)

    def test_223095_note_carries_ddragon_25_as(self) -> None:
        note = ITEM_EFFECTS["223095"].note
        self.assertIn("25% AS", note)
        self.assertNotIn("20% AS", note)
        self.assertNotIn("Stormraider", note)


class ArenaRapidFirecannonSharpshooterTests(unittest.TestCase):
    def test_223094_credits_arena_stated_200_magic(self) -> None:
        p = _proc("223094")
        self.assertEqual(p.damage_type, MAGICAL)
        self.assertEqual(p.resolve_damage(_CTX), 200.0)

    def test_223094_cadence_unchanged_from_sr(self) -> None:
        # The Arena line states no faster charge for Firecannon.
        self.assertEqual(_proc("223094").every_n_seconds, _proc("3094").every_n_seconds)

    def test_sr_3094_unchanged(self) -> None:
        self.assertEqual(_proc("3094").resolve_damage(_CTX), 40.0)


if __name__ == "__main__":
    unittest.main()
