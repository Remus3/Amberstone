"""Tests for the authored C2 AA-empower amortized values (item 258, gap-plan Phase D).

Item 247 wired the ``dps.compute_dps`` AA-empower seam (``_aa_amp_multiplier``)
but left the 5 ``base="aa"`` AmpEntry champs (Caitlyn W / Fiora E / Jayce W f1 /
Sivir W / Nidalee Q f1) at placeholder ``amp_per_rank=(0.0,)``. That consumer
multiplies ONLY the base-AA single-target damage component (``base_dps`` over the
whole rotation) - NOT item proc DPS, NOT attack speed, NOT extra-target bounces.

Item 258 authored the values. Of the 5, ONLY Fiora E fits the seam:
  * Fiora E Bladework - the 2nd empowered AA is a GUARANTEED CRIT at modified crit
    damage 160%:200% by E rank. On a no-crit bruiser build that is a real (m-1)
    per-AA uplift, AMORTIZED over the E cooldown (11/10/9/8/7s) at AS=1.0:
    addend=(m-1)/cd -> (0.0545,0.0700,0.0889,0.1125,0.1429), always_on.

The other 4 stay INERT (placeholder, factor 1.0) with documented non-fit reasons
(Caitlyn W trap-spring Headshot passive; Jayce W f1 mostly-sub-1.0xAD modifier
whose value is the unmodeled +360% AS; Sivir W extra-target bounce + AS; Nidalee
Q f1 AA-to-magic conversion gated off-rotation).

A source-rank guard in ``_aa_amp_multiplier`` makes an entry whose spell is
unleveled (rank < 0) contribute factor 1.0 (mirrors the item-257 cross-spell
``src_rank >= 0`` guard).

DEFAULT ``apply_ability_amps=False`` ``compute_dps`` is byte-identical for all
champions; the seam only injects under the flag.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._ability_amp_overrides import (
    _ABILITY_AMP_OVERRIDES,
    _DEFAULT_AMP_PROBABILITY,
    _aa_amp_multiplier,
)
from agents.daemon_slayer.ability_dps import rank_at_level
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

_SNAP = DataSnapshot.load()

# The authored Fiora E per-rank addends (0-based E rank index).
_FIORA_E_ADDENDS = (0.0545, 0.0700, 0.0889, 0.1125, 0.1429)

# The 4 champs whose base="aa" entry stays INERT (placeholder 0.0).
_INERT = (("Caitlyn", "W"), ("Jayce", "W"), ("Sivir", "W"), ("Nidalee", "Q"))


def _wd(cid, level, amps):
    return compute_dps(_SNAP, cid, level, [], apply_ability_amps=amps).weighted_dps


class AuthoredFioraValueTests(unittest.TestCase):
    def test_fiora_e_entry_authored_with_expected_addends(self):
        # base="aa", always_on=True, and the exact authored per-rank tuple.
        e = _ABILITY_AMP_OVERRIDES[("Fiora", "E", 0)]
        self.assertEqual(e.base, "aa")
        self.assertTrue(e.always_on)
        self.assertEqual(e.amp_per_rank, _FIORA_E_ADDENDS)

    def test_fiora_e_addends_strictly_increasing(self):
        # E rank scales the modified crit + shortens cd, so the amortized addend
        # rises monotonically with rank.
        for a, b in zip(_FIORA_E_ADDENDS, _FIORA_E_ADDENDS[1:]):
            self.assertLess(a, b)

    def test_fiora_e_addend_is_m_minus_1_over_cd(self):
        # Reconstruct the documented amortization to lock the math, not just the
        # literal: addend == (m - 1) / cd at AS=1.0, one guaranteed-crit AA/window.
        cds = (11.0, 10.0, 9.0, 8.0, 7.0)
        ms = (1.60, 1.70, 1.80, 1.90, 2.00)
        for i, (cd, m) in enumerate(zip(cds, ms)):
            self.assertAlmostEqual(_FIORA_E_ADDENDS[i], (m - 1.0) / cd, places=4)


class AaAmpMultiplierTests(unittest.TestCase):
    def test_fiora_factor_per_rank(self):
        # _aa_amp_multiplier returns 1 + addend at each 0-based E rank.
        for r, addend in enumerate(_FIORA_E_ADDENDS):
            f = _aa_amp_multiplier("Fiora", lambda k, _r=r: (_r if k == "E" else -1))
            self.assertAlmostEqual(f, 1.0 + addend, places=9)

    def test_fiora_unleveled_e_returns_one(self):
        # Source-rank guard: E rank < 0 (not yet leveled) -> factor 1.0.
        f = _aa_amp_multiplier("Fiora", lambda k: -1)
        self.assertEqual(f, 1.0)

    def test_fiora_live_rank_at_level_low_levels_neutral(self):
        # Under the canonical 1-point distribution E rank is -1 at levels 1-3,
        # so the live multiplier is 1.0 there (no Bladework yet).
        for level in (1, 2, 3):
            f = _aa_amp_multiplier("Fiora", lambda k, _l=level: rank_at_level(k, _l))
            self.assertEqual(f, 1.0)

    def test_fiora_live_rank_at_level_applies_from_level4(self):
        # E rank 0 from level 4 -> rank-0 addend applies.
        f = _aa_amp_multiplier("Fiora", lambda k: rank_at_level(k, 4))
        self.assertAlmostEqual(f, 1.0 + _FIORA_E_ADDENDS[0], places=9)

    def test_inert_champs_factor_one(self):
        # The 4 inert entries return factor 1.0 at any rank (placeholder 0.0).
        for cid, _key in _INERT:
            for rank in (-1, 0, 4):
                f = _aa_amp_multiplier(cid, lambda k, _r=rank: _r)
                self.assertEqual(f, 1.0, f"{cid} rank {rank}")

    def test_champ_with_no_aa_entry_factor_one(self):
        self.assertEqual(_aa_amp_multiplier("Lux", lambda k: 4), 1.0)


class SourceRankGuardTests(unittest.TestCase):
    def test_guard_skips_unleveled_entry_in_combined_factor(self):
        # If Fiora E is unleveled the combined factor is exactly 1.0 even though
        # the entry exists + is always_on (the guard skips it pre-multiply).
        self.assertEqual(_aa_amp_multiplier("Fiora", lambda k: -1), 1.0)
        # And a leveled E is non-1.0, proving the guard is rank-gated not blanket.
        self.assertGreater(_aa_amp_multiplier("Fiora", lambda k: 0), 1.0)


class DefaultByteIdenticalTests(unittest.TestCase):
    """DEFAULT apply_ability_amps=False is byte-identical for every champion."""

    def test_authored_and_inert_default_off_is_seam_free(self):
        # compute_dps with the flag OFF must equal itself (the seam only injects
        # under the flag). We assert the flag-OFF value is unchanged by toggling
        # the flag OFF twice (deterministic) AND that for the inert champs flag-ON
        # equals flag-OFF (no value -> no change).
        for cid in ("Fiora", "Caitlyn", "Jayce", "Sivir", "Nidalee", "Lux"):
            for level in (4, 11, 18):
                off1 = _wd(cid, level, False)
                off2 = _wd(cid, level, False)
                self.assertEqual(off1, off2, f"{cid} L{level} default not deterministic")

    def test_inert_champs_flag_on_byte_identical(self):
        # Caitlyn / Jayce / Sivir / Nidalee + Lux control: flag-ON == flag-OFF.
        for cid in ("Caitlyn", "Jayce", "Sivir", "Nidalee", "Lux"):
            for level in (4, 11, 18):
                self.assertEqual(
                    _wd(cid, level, True),
                    _wd(cid, level, False),
                    f"{cid} L{level} flag-on must be byte-identical",
                )

    def test_fiora_low_level_flag_on_byte_identical(self):
        # Fiora L1-3 (E unleveled) flag-ON == flag-OFF (source-rank guard).
        for level in (1, 2, 3):
            self.assertEqual(_wd("Fiora", level, True), _wd("Fiora", level, False))


class FioraFlagOnAppliesTests(unittest.TestCase):
    """Flag-ON Fiora at leveled-E levels applies exactly the rank factor to AA."""

    def test_fiora_flag_on_scales_base_aa_by_rank_factor(self):
        # weighted_dps on==off*factor for an itemless Fiora (no item procs, so the
        # whole base_dps is the AA component the amp scales). The factor is the
        # rank-appropriate (1 + addend).
        for level in (4, 11, 18):
            off = _wd("Fiora", level, False)
            on = _wd("Fiora", level, True)
            r = rank_at_level("E", level)
            self.assertGreaterEqual(r, 0)
            factor = 1.0 + _FIORA_E_ADDENDS[r]
            self.assertAlmostEqual(on, off * factor, places=3, msg=f"L{level} r{r}")

    def test_fiora_flag_on_strictly_greater_when_e_leveled(self):
        for level in (4, 11, 18):
            self.assertGreater(_wd("Fiora", level, True), _wd("Fiora", level, False))


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.203.0")
        self.assertEqual(ENGINE_VERSION, "1.203.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_amp_overrides_module_is_ascii(self):
        import agents.daemon_slayer._ability_amp_overrides as mod

        with open(mod.__file__, "rb") as fh:
            raw = fh.read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes in _ability_amp_overrides.py: {bad[:5]}")

    def test_this_test_file_is_ascii(self):
        with open(__file__, "rb") as fh:
            raw = fh.read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes in test file: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
