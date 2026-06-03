"""Regression pins for the GAP phantom-damage residual correction (1.75.0).

The item-238 ``NON_DAMAGE_BLOCKS`` registry flips blocks the Meraki extractor
mislabeled ``attribute_kind="damage"`` (the attribute NAME contains "Damage")
but which are actually a self-AD grant / steroid / shield - phantom damage that
inflates DPS. The 1.75.0 residual sweep added 2 more confirmed phantoms
(DrMundo E, Twitch R) and DELIBERATELY left a near-miss (Mel R) unflipped.

These pins lock:
  - DrMundo E f0 block[0] "Bonus Attack Damage" flipped to "other"; the form's
    real damage (block[1]/[2]) survives.
  - Twitch R f0 block[0] "Bonus Attack Damage" flipped to "other" (R's only
    block -> 0 cast damage, correct: R empowers basic attacks).
  - Mel R f0 block[0] "Increased Stored Damage" NOT flipped (it is routed away
    from by the block-index registry, so flipping it would only break the
    forced-block-0 delta baseline with no default-path benefit).
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.abilities import AbilitiesSnapshot


def _kind(form, attribute: str) -> str | None:
    """Return the attribute_kind of the block named ``attribute``, or None."""
    for b in form.damage_blocks:
        if b.attribute == attribute:
            return b.attribute_kind
    return None


class PhantomResidualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load()

    def test_drmundo_e_ad_grant_flipped_to_other(self) -> None:
        form = self.snap.get_ability("DrMundo", "E", 0)
        self.assertEqual(_kind(form, "Bonus Attack Damage"), "other",
                         "DrMundo E block[0] AD grant should be flipped to 'other'")

    def test_drmundo_e_real_damage_survives(self) -> None:
        form = self.snap.get_ability("DrMundo", "E", 0)
        dmg = {b.attribute for b in form.damage_blocks_only()}
        self.assertIn("Minimum Bonus Physical Damage", dmg)
        self.assertIn("Maximum Bonus Physical Damage", dmg)
        self.assertNotIn("Bonus Attack Damage", dmg)

    def test_twitch_r_steroid_flipped_to_other(self) -> None:
        form = self.snap.get_ability("Twitch", "R", 0)
        self.assertEqual(_kind(form, "Bonus Attack Damage"), "other",
                         "Twitch R steroid should be flipped to 'other'")
        # R is an AA-empowerment - after the flip it has no cast-damage block.
        self.assertEqual(len(form.damage_blocks_only()), 0)

    def test_mel_r_storage_block_NOT_flipped(self) -> None:
        form = self.snap.get_ability("Mel", "R", 0)
        self.assertEqual(_kind(form, "Increased Stored Damage"), "damage",
                         "Mel R block[0] is intentionally left unflipped "
                         "(block-index routes Mel R to block 2)")

    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.101.0")

    def test_module_is_ascii(self) -> None:
        with open(__file__, "rb") as fh:
            fh.read().decode("ascii")


if __name__ == "__main__":
    unittest.main()
