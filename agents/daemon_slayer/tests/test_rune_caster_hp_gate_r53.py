"""R53 (ENGINE 1.164.0): caster_hp gate seam for Last Stand 8299.

Last Stand 8299 is a Precision slot-4 ``stacking_amp`` whose amp scales with the
CASTER's current health (DDragon 16.13.1 runesReforged.json longDesc, verbatim):

  "Deal 5% - 11% increased damage to champions while you are below 60% health.
   Max damage gained at 30% health."

Item 232 already modeled that ramp inside ``keystone_amp`` via ``_last_stand_amp``
(1.0 at/above 60% caster HP -> 1.11 at/below 30%). The BURST scorer, however,
always fed ``caster_hp_pct`` (live default 1.0) so Last Stand contributed NOTHING
to the burst total. R53 adds the DEFAULT-OFF caster_hp gate seam so a scenario
eval can credit the honest low-HP amp WITHOUT disturbing the live default:

  * ``keystone_amp(..., gate_caster_hp=False)`` - accepted for signature parity
    alongside the burst seam; the 8299 ramp is single-sourced through
    ``_last_stand_amp(caster_hp_pct)`` and is BYTE-IDENTICAL regardless of the
    flag (the item-232 direct-call behavior is untouched).
  * ``compute_burst_damage(..., gate_caster_hp_amp=False, caster_current_hp_pct)``
    - OFF (default) feeds Last Stand ``caster_hp_pct`` exactly as the pre-R53
    engine (live callers pass 1.0 -> no amp -> byte-identical). ON feeds
    ``caster_current_hp_pct`` so the honest low-HP amp lands in the burst total.

The live default-ON flip is EXCLUDED (do-not-flip-blind) and operator-gated in
docs/LIVE_GAME_GATED_SYNC.md; this run ships the seam OFF only. Boundary math
(0.60 strict-no-amp / 0.30 max) matches data/meta_build/ddragon/16.13.1.

NO ENGINE_VERSION assertions here (the orchestrator owns the bump); the pin lives
in the engine test-pin set.
"""

from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rune_procs import keystone_amp

_LAST_STAND = 8299
_SNAP = DataSnapshot.load()
_TGT = dict(
    target_armor=80.0, target_mr=60.0, target_max_hp=2000.0, target_bonus_hp=600.0
)


def _burst(champ, *, runes=None, gate=False, caster_hp=1.0, level=11):
    return compute_burst_damage(
        _SNAP, champ, level, item_ids=[], mode="SR", runes=runes,
        gate_caster_hp_amp=gate, caster_current_hp_pct=caster_hp, **_TGT,
    )


class KeystoneAmpParityTests(unittest.TestCase):
    """gate_caster_hp is byte-identical: it never alters the 8299 ramp."""

    def test_flag_parity_across_hp(self):
        for hp in (1.0, 0.60, 0.45, 0.30, 0.10, 0.0):
            off = keystone_amp(_LAST_STAND, 100.0, caster_hp_pct=hp)
            on = keystone_amp(_LAST_STAND, 100.0, caster_hp_pct=hp, gate_caster_hp=True)
            self.assertAlmostEqual(off, on, places=9, msg=f"hp={hp}")

    def test_item232_ramp_unchanged(self):
        # Regression: the item-232 honest ramp is preserved verbatim.
        self.assertAlmostEqual(keystone_amp(_LAST_STAND, 100.0, caster_hp_pct=1.0), 100.0, places=6)
        self.assertAlmostEqual(keystone_amp(_LAST_STAND, 100.0, caster_hp_pct=0.60), 100.0, places=6)
        self.assertAlmostEqual(keystone_amp(_LAST_STAND, 100.0, caster_hp_pct=0.45), 108.0, places=6)
        self.assertAlmostEqual(keystone_amp(_LAST_STAND, 100.0, caster_hp_pct=0.30), 111.0, places=6)
        self.assertAlmostEqual(keystone_amp(_LAST_STAND, 100.0, caster_hp_pct=0.10), 111.0, places=6)

    def test_default_no_flag_is_full_hp_no_amp(self):
        self.assertAlmostEqual(keystone_amp(_LAST_STAND, 100.0), 100.0, places=6)


class BurstSeamDefaultOffTests(unittest.TestCase):
    """gate_caster_hp_amp=False -> Last Stand contributes nothing (byte-identical)."""

    def test_last_stand_off_byte_identical(self):
        base = _burst("Garen", runes=None)
        off = _burst("Garen", runes=[_LAST_STAND], gate=False, caster_hp=0.30)
        # OFF: even a low caster_current_hp_pct is inert (seam not flipped).
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_default_kwarg_is_off(self):
        # Omitting the seam kwargs == passing gate_caster_hp_amp=False.
        omitted = compute_burst_damage(
            _SNAP, "Garen", 11, item_ids=[], mode="SR", runes=[_LAST_STAND], **_TGT
        )
        base = _burst("Garen", runes=None)
        self.assertEqual(omitted.total_burst_damage, base.total_burst_damage)


class BurstSeamOnTests(unittest.TestCase):
    """gate_caster_hp_amp=True -> honest low-HP amp lands in the burst total."""

    def test_low_hp_amps_burst(self):
        base = _burst("Garen", runes=None)
        on = _burst("Garen", runes=[_LAST_STAND], gate=True, caster_hp=0.30)
        # Max amp at 30% caster HP -> total scales by 1.11.
        self.assertAlmostEqual(
            on.total_burst_damage, base.total_burst_damage * 1.11, places=3
        )

    def test_mid_hp_partial_amp(self):
        base = _burst("Garen", runes=None)
        on = _burst("Garen", runes=[_LAST_STAND], gate=True, caster_hp=0.45)
        self.assertAlmostEqual(
            on.total_burst_damage, base.total_burst_damage * 1.08, places=3
        )

    def test_boundary_60pct_no_amp(self):
        # "below 60%" is strict -> exactly 0.60 caster HP is NOT amped.
        base = _burst("Garen", runes=None)
        on = _burst("Garen", runes=[_LAST_STAND], gate=True, caster_hp=0.60)
        self.assertEqual(on.total_burst_damage, base.total_burst_damage)

    def test_full_hp_on_no_amp(self):
        base = _burst("Garen", runes=None)
        on = _burst("Garen", runes=[_LAST_STAND], gate=True, caster_hp=1.0)
        self.assertEqual(on.total_burst_damage, base.total_burst_damage)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self):
        raw = pathlib.Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
