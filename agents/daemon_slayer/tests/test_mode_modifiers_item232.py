"""Item 232 - mode_modifiers sidecar OPT-IN wire into compute_dps + compute_ehp.

The wiki_stats.json sidecar carries per-champ per-mode balance modifiers for
the non-ARAM modes:

  - urf / ofa / usb / nb  -> dmg_dealt / dmg_taken MULTIPLIERS
  - ar (Arena/CHERRY) / swift (Swiftplay) -> hp_lvl / dam_lvl ADDEND
    stat-overrides

ARAM keeps its authoritative legacy lolmath path (aramDamageDealt /
aramDamageTaken); the wiki sidecar is the source ONLY for the other modes,
behind a single OPT-IN flag ``apply_mode_modifiers`` (default False).

BYTE-IDENTICAL CONTRACT: ``apply_mode_modifiers=False`` (the default) MUST
yield identical compute_dps / compute_ehp output to before for ALL modes
including ARAM. This mirrors item 231's ``gate_ammo`` opt-in precedent: the
flag is the established gated-data pattern so the live /rank stays
byte-identical until the operator validates.

STATS.PY ADDEND DEFERRED: the ar/swift per-level stat addend (hp_lvl /
dam_lvl) was NOT wired this slice - the base-stat scaling helper is
``engine._scale_champion_base`` (engine.py:88), a file outside this slice's
disjoint set, and ``_scale_champion_base(champ_stats, level)`` carries no
mode/snapshot param to thread the override through cleanly. ARENA therefore
stays BYTE-IDENTICAL with the flag on (Arena has no dmg_dealt/dmg_taken in
the sidecar - only the deferred hp_lvl/dam_lvl addend), pinned below.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.ehp import compute_ehp


# Probed live at 16.11.1 (verify on a patch bump per
# reference_patch_refresh_workflow):
#   Aatrox URF  -> {"dmg_dealt": 1.15, "dmg_taken": 0.7}
#   Ahri  USB   -> {"dmg_taken": 0.95}          (no dmg_dealt)
#   Jinx  ARENA -> {"dam_lvl": 0.6, "hp_lvl": 10.0}  (addend-only, deferred)
_URF_CHAMP = "Aatrox"
_URF_ITEM = "3078"          # Trinity Force - a real owned AD item
_URF_DMG_DEALT = 1.15
_URF_DMG_TAKEN = 0.7

_USB_CHAMP = "Ahri"
_USB_ITEM = "3157"          # Zhonya's - a real owned AP item
_USB_DMG_TAKEN = 0.95

_ARENA_CHAMP = "Jinx"
_ARENA_ITEM = "3031"        # Infinity Edge


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()


class ByteIdenticalDefaultTests(_SnapBase):
    """The default (flag absent) MUST equal apply_mode_modifiers=False for
    every mode incl. ARAM (legacy lolmath path untouched)."""

    def test_dps_default_equals_flag_false_all_modes(self):
        for mode in ("SR", "ARAM", "URF", "OFA", "USB", "NB", "ARENA"):
            with self.subTest(mode=mode):
                d_default = compute_dps(
                    self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode=mode
                ).weighted_dps
                d_false = compute_dps(
                    self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode=mode,
                    apply_mode_modifiers=False,
                ).weighted_dps
                self.assertEqual(d_default, d_false)

    def test_ehp_default_equals_flag_false_all_modes(self):
        for mode in ("SR", "ARAM", "URF", "OFA", "USB", "NB", "ARENA"):
            with self.subTest(mode=mode):
                e_default = compute_ehp(
                    self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode=mode
                ).blended_ehp
                e_false = compute_ehp(
                    self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode=mode,
                    apply_mode_modifiers=False,
                ).blended_ehp
                self.assertEqual(e_default, e_false)


class AramLegacyUnchangedTests(_SnapBase):
    """ARAM MUST keep the legacy lolmath path even with the flag ON - the
    wiki sidecar carries ARAM modifiers too, but routing ARAM through it
    would double-count against the authoritative lolmath aram_modifiers."""

    def test_aram_dps_unchanged_with_flag_on(self):
        off = compute_dps(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="ARAM",
            apply_mode_modifiers=False,
        ).weighted_dps
        on = compute_dps(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="ARAM",
            apply_mode_modifiers=True,
        ).weighted_dps
        self.assertEqual(off, on)

    def test_aram_ehp_unchanged_with_flag_on(self):
        off = compute_ehp(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="ARAM",
            apply_mode_modifiers=False,
        ).blended_ehp
        on = compute_ehp(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="ARAM",
            apply_mode_modifiers=True,
        ).blended_ehp
        self.assertEqual(off, on)


class UrfDmgDealtDpsTests(_SnapBase):
    """URF dmg_dealt MULTIPLIER on weighted DPS when the flag is ON."""

    def test_urf_dps_scales_by_dmg_dealt(self):
        off = compute_dps(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="URF",
            apply_mode_modifiers=False,
        ).weighted_dps
        on = compute_dps(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="URF",
            apply_mode_modifiers=True,
        ).weighted_dps
        self.assertGreater(off, 0.0)
        self.assertAlmostEqual(on / off, _URF_DMG_DEALT, places=9)

    def test_urf_mode_multiplier_field_reflects_dmg_dealt(self):
        r = compute_dps(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="URF",
            apply_mode_modifiers=True,
        )
        self.assertAlmostEqual(r.mode_multiplier, _URF_DMG_DEALT, places=9)


class UrfDmgTakenEhpTests(_SnapBase):
    """URF dmg_taken MULTIPLIER on EHP when the flag is ON. dmg_taken < 1.0
    means the champ takes less damage so EHP scales UP by 1/dmg_taken."""

    def test_urf_ehp_scales_by_inverse_dmg_taken(self):
        off = compute_ehp(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="URF",
            apply_mode_modifiers=False,
        ).blended_ehp
        on = compute_ehp(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="URF",
            apply_mode_modifiers=True,
        ).blended_ehp
        self.assertGreater(off, 0.0)
        self.assertAlmostEqual(on / off, 1.0 / _URF_DMG_TAKEN, places=6)

    def test_urf_ehp_mode_multiplier_field_reflects_dmg_taken(self):
        r = compute_ehp(
            self.snap, _URF_CHAMP, 11, item_ids=[_URF_ITEM], mode="URF",
            apply_mode_modifiers=True,
        )
        self.assertAlmostEqual(r.mode_multiplier, _URF_DMG_TAKEN, places=9)


class DmgTakenOnlyModeTests(_SnapBase):
    """A mode with dmg_taken but NO dmg_dealt (Ahri USB) changes EHP but
    leaves DPS byte-identical even with the flag ON."""

    def test_usb_ehp_changes_dps_does_not(self):
        e_off = compute_ehp(
            self.snap, _USB_CHAMP, 11, item_ids=[_USB_ITEM], mode="USB",
            apply_mode_modifiers=False,
        ).blended_ehp
        e_on = compute_ehp(
            self.snap, _USB_CHAMP, 11, item_ids=[_USB_ITEM], mode="USB",
            apply_mode_modifiers=True,
        ).blended_ehp
        self.assertAlmostEqual(e_on / e_off, 1.0 / _USB_DMG_TAKEN, places=6)

        d_off = compute_dps(
            self.snap, _USB_CHAMP, 11, item_ids=[_USB_ITEM], mode="USB",
            apply_mode_modifiers=False,
        ).weighted_dps
        d_on = compute_dps(
            self.snap, _USB_CHAMP, 11, item_ids=[_USB_ITEM], mode="USB",
            apply_mode_modifiers=True,
        ).weighted_dps
        self.assertEqual(d_off, d_on)


class ArenaAddendDeferredTests(_SnapBase):
    """Arena carries ONLY hp_lvl / dam_lvl addend (no dmg_dealt / dmg_taken
    multiplier). The addend wire was DEFERRED (engine._scale_champion_base
    is a non-owned file with no mode param), so ARENA stays BYTE-IDENTICAL
    with the flag ON. This pins the deferred-state contract: when the
    addend is later wired, this test should be replaced by a level>1
    EHP-rises assertion."""

    def test_arena_dps_byte_identical_with_flag_on(self):
        off = compute_dps(
            self.snap, _ARENA_CHAMP, 11, item_ids=[_ARENA_ITEM], mode="ARENA",
            apply_mode_modifiers=False,
        ).weighted_dps
        on = compute_dps(
            self.snap, _ARENA_CHAMP, 11, item_ids=[_ARENA_ITEM], mode="ARENA",
            apply_mode_modifiers=True,
        ).weighted_dps
        self.assertEqual(off, on)

    def test_arena_ehp_byte_identical_with_flag_on(self):
        off = compute_ehp(
            self.snap, _ARENA_CHAMP, 11, item_ids=[_ARENA_ITEM], mode="ARENA",
            apply_mode_modifiers=False,
        ).blended_ehp
        on = compute_ehp(
            self.snap, _ARENA_CHAMP, 11, item_ids=[_ARENA_ITEM], mode="ARENA",
            apply_mode_modifiers=True,
        ).blended_ehp
        self.assertEqual(off, on)


class AsciiHygieneTests(unittest.TestCase):
    def test_source_is_ascii(self):
        with open(__file__, "rb") as fh:
            raw = fh.read()
        for i, b in enumerate(raw):
            self.assertLess(
                b, 128, f"non-ASCII byte 0x{b:02x} at offset {i}"
            )


if __name__ == "__main__":
    unittest.main()
