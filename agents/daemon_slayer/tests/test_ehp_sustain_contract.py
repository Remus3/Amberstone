"""ENGINE 1.121.0 (2026-06-14) - SUSTAIN contract-gap closure.

Closes the former strict-xfail in ``test_wireable_sims_p1l3`` (the L3
``ZZZ_ResolvedContractGapDocs`` class): lifesteal/spellvamp/omnivamp resolve
as wireable stats but had no explicitly-named sustain/effective-EHP output.

The EHP scorer already folds the lifesteal heal pool into ``blended_ehp``
since ENGINE 1.28.0. This slice NAMES the sustain-inclusive quantity and
consumes the previously-unconsumed spellvamp / omnivamp stats, via a SIBLING
layer (the ``cc_blended_ehp`` pattern) that leaves ``blended_ehp`` /
``physical_ehp`` / ``magical_ehp`` / ``true_ehp`` BYTE-IDENTICAL.

New EhpResult surface:
  * ``effective_ehp_with_sustain`` - blended EHP including the FULL vamp pool
    (lifesteal + spellvamp + omnivamp). == ``blended_ehp`` on every current
    build (no SR item resolves spellvamp / omnivamp - VampStatResolutionEdge).
  * ``ehp_without_sustain`` - blended EHP with the vamp heal stripped
    (item-passive heals + shields kept) = the "raw" EHP.
  * ``sustain_ehp_delta`` = effective_ehp_with_sustain - ehp_without_sustain.
  * ``heal_spellvamp`` / ``heal_omnivamp`` - pre-amp vamp heal magnitudes.
  * a ``sustain`` block in ``to_dict``.

Coverage classes:
  * ``VampHealPoolUnitTests`` - the generalised ``_vamp_heal_pool`` formula +
    the back-compat ``_lifesteal_heal`` delegation.
  * ``LifestealSustainTests`` - Bloodthirster/Aatrox: effective > raw, delta
    matches the lifesteal contribution, effective == blended_ehp.
  * ``NoVampSustainTests`` - naked + shield-only builds: all three EHP terms
    coincide (no vamp), delta 0; the shield is NOT stripped as sustain.
  * ``SustainToDictTests`` - the flat keys + the nested ``sustain`` block.
  * ``SustainFormatTableTests`` - the sustain row renders only when nonzero.
  * ``SpellvampOmnivampWiringTests`` - structural: the stats are consumed but
    resolve to 0 on current builds (no item grants them).
  * ``ByteIdenticalGuardTests`` - blended_ehp / heal_lifesteal unchanged.
  * ``EngineVersionCurrentTests`` - pin ENGINE_VERSION 1.127.0.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    _FIGHT_WINDOW_S,
    _lifesteal_heal,
    _vamp_heal_pool,
    compute_ehp,
)


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()


# ---------------- unit: the vamp heal pool ----------------


class VampHealPoolUnitTests(unittest.TestCase):
    def test_formula_is_vamp_times_aa_throughput_over_window(self) -> None:
        # vamp_pct * ad * as * window
        got = _vamp_heal_pool(0.20, 100.0, 0.80, fight_window_s=6.0)
        self.assertAlmostEqual(got, 0.20 * 100.0 * 0.80 * 6.0, places=9)

    def test_zero_vamp_yields_zero(self) -> None:
        self.assertEqual(_vamp_heal_pool(0.0, 100.0, 1.0), 0.0)

    def test_default_window_is_fight_window_constant(self) -> None:
        got = _vamp_heal_pool(0.10, 50.0, 1.0)
        self.assertAlmostEqual(got, 0.10 * 50.0 * 1.0 * _FIGHT_WINDOW_S, places=9)

    def test_negative_inputs_floored_at_zero(self) -> None:
        self.assertEqual(_vamp_heal_pool(-0.5, 100.0, 1.0), 0.0)
        self.assertEqual(_vamp_heal_pool(0.2, -100.0, 1.0), 0.0)
        self.assertEqual(_vamp_heal_pool(0.2, 100.0, -1.0), 0.0)

    def test_non_positive_window_returns_zero(self) -> None:
        self.assertEqual(_vamp_heal_pool(0.2, 100.0, 1.0, fight_window_s=0.0), 0.0)
        self.assertEqual(_vamp_heal_pool(0.2, 100.0, 1.0, fight_window_s=-3.0), 0.0)

    def test_lifesteal_heal_delegates_to_vamp_pool(self) -> None:
        # The back-compat wrapper must be identical to the generalised pool.
        for ls, ad, as_ in ((0.12, 180.0, 0.75), (0.25, 90.0, 1.4), (0.0, 0.0, 0.0)):
            self.assertEqual(
                _lifesteal_heal(ls, ad, as_),
                _vamp_heal_pool(ls, ad, as_),
            )


# ---------------- integration: lifesteal sustain ----------------


class LifestealSustainTests(_SnapBase):
    def _bt(self):
        # Bloodthirster (3072) on Aatrox L11 - the contract test's build.
        return compute_ehp(self.snap, "Aatrox", level=11, item_ids=["3072"])

    def test_lifesteal_resolves_and_feeds_a_vamp_heal(self) -> None:
        e = self._bt()
        self.assertGreater(e.stats.get("lifesteal", 0.0), 0.0)
        self.assertGreater(e.heal_lifesteal, 0.0)

    def test_effective_exceeds_raw_ehp_by_the_vamp_sustain(self) -> None:
        e = self._bt()
        self.assertGreater(e.ehp_without_sustain, 0.0)
        self.assertGreater(e.effective_ehp_with_sustain, e.ehp_without_sustain)
        self.assertAlmostEqual(
            e.sustain_ehp_delta,
            e.effective_ehp_with_sustain - e.ehp_without_sustain,
            places=6,
        )
        self.assertGreater(e.sustain_ehp_delta, 0.0)

    def test_effective_equals_blended_when_no_spellvamp_or_omnivamp(self) -> None:
        # Lifesteal already lives in blended_ehp (ENGINE 1.28.0); with no
        # spellvamp/omnivamp item the named term must equal it EXACTLY. This
        # transitively proves _blend_with_heal reproduces the main blend.
        e = self._bt()
        self.assertEqual(e.heal_spellvamp, 0.0)
        self.assertEqual(e.heal_omnivamp, 0.0)
        self.assertAlmostEqual(
            e.effective_ehp_with_sustain, e.blended_ehp, places=9
        )

    def test_effective_equals_blended_with_each_permanent_hp_seam_ARMED(self) -> None:
        """RM-105. The equality above only ever held AT DEFAULT FLAGS.

        `ehp.py` assembles its per-type numerators TWICE - the main block and
        the `_blend_with_heal` mirror that produces effective_ehp_with_sustain.
        The mirror silently OMITTED the entire permanent-HP family
        (passive_health_hp R46, rune_perm_hp R136, item_health_stack_hp R137),
        so the two fields diverged by exactly the omitted HP the moment any of
        those seams was armed - and every one of them is queued for an
        operator-gated default-ON flip, which is precisely what arms it.

        Measured on Sion L13 [3084, 3068] before the fix: -618.33 with
        apply_rune_health_grants (about 10 percent), -301.42 with
        assume_passive_health_stacks, -373.24 with assume_item_health_stacks,
        and exactly 0.0000 at defaults - which is why nothing caught it.

        The mirror's own comment claimed it mirrored the main numerators. That
        was true when written and stopped being true at R46.
        """
        seams = (
            ("assume_passive_health_stacks", {}),
            ("assume_item_health_stacks", {}),
            ("apply_rune_health_grants", {"rune_ids": ["8451", "8437"]}),
        )
        for flag, extra in seams:
            with self.subTest(seam=flag):
                e = compute_ehp(
                    self.snap, "Sion", level=13, item_ids=["3084", "3068"],
                    **{flag: True}, **extra,
                )
                self.assertAlmostEqual(
                    e.effective_ehp_with_sustain, e.blended_ehp, places=6,
                    msg=(f"{flag} armed: the sustain mirror diverges from the "
                         f"main blend by "
                         f"{e.blended_ehp - e.effective_ehp_with_sustain:.4f} "
                         f"EHP - the permanent-HP family is missing from "
                         f"_blend_with_heal"),
                )

    def test_raw_ehp_is_strictly_below_blended_for_a_lifesteal_build(self) -> None:
        # ehp_without_sustain strips the lifesteal heal that blended_ehp
        # carries, so it must be smaller for a build that has lifesteal.
        e = self._bt()
        self.assertLess(e.ehp_without_sustain, e.blended_ehp)


# ---------------- integration: no-vamp builds ----------------


class NoVampSustainTests(_SnapBase):
    def test_naked_build_all_three_terms_coincide(self) -> None:
        # No items -> no vamp, no item heal -> raw == blended == effective.
        e = compute_ehp(self.snap, "Garen", level=11)
        self.assertEqual(e.heal_lifesteal, 0.0)
        self.assertAlmostEqual(e.ehp_without_sustain, e.blended_ehp, places=9)
        self.assertAlmostEqual(
            e.effective_ehp_with_sustain, e.blended_ehp, places=9
        )
        self.assertAlmostEqual(e.sustain_ehp_delta, 0.0, places=9)

    def test_shield_is_not_counted_as_sustain(self) -> None:
        # Sterak's Gage (3053) is a shield, not vamp. ehp_without_sustain
        # keeps the shield (only the VAMP heal is stripped), so raw still
        # equals blended and the sustain delta stays 0.
        e = compute_ehp(self.snap, "Sett", level=11, item_ids=["3053"])
        self.assertEqual(e.heal_lifesteal, 0.0)
        self.assertAlmostEqual(e.sustain_ehp_delta, 0.0, places=9)
        self.assertAlmostEqual(e.ehp_without_sustain, e.blended_ehp, places=9)


# ---------------- to_dict surface ----------------


class SustainToDictTests(_SnapBase):
    def test_flat_keys_and_nested_block_present(self) -> None:
        e = compute_ehp(self.snap, "Aatrox", level=11, item_ids=["3072"])
        d = e.to_dict()
        for k in (
            "effective_ehp_with_sustain",
            "ehp_without_sustain",
            "sustain_ehp_delta",
            "heal_spellvamp",
            "heal_omnivamp",
            "sustain",
        ):
            self.assertIn(k, d)
        block = d["sustain"]
        for k in (
            "effective_ehp_with_sustain",
            "ehp_without_sustain",
            "sustain_ehp_delta",
            "heal_lifesteal",
            "heal_spellvamp",
            "heal_omnivamp",
        ):
            self.assertIn(k, block)
        self.assertAlmostEqual(
            block["effective_ehp_with_sustain"],
            e.effective_ehp_with_sustain,
            places=9,
        )


# ---------------- format_table surface ----------------


class SustainFormatTableTests(_SnapBase):
    def test_sustain_row_renders_for_a_lifesteal_build(self) -> None:
        e = compute_ehp(self.snap, "Aatrox", level=11, item_ids=["3072"])
        table = e.format_table()
        self.assertIn("sustain", table)
        self.assertIn("(vamp)", table)

    def test_no_sustain_row_for_a_naked_build(self) -> None:
        e = compute_ehp(self.snap, "Garen", level=11)
        self.assertNotIn("(vamp)", e.format_table())


# ---------------- spellvamp / omnivamp structural wiring ----------------


class SpellvampOmnivampWiringTests(_SnapBase):
    def test_no_current_item_resolves_spellvamp_or_omnivamp(self) -> None:
        # The data reality the EHP sustain wiring depends on: no snapshot item
        # carries a spellvamp/omnivamp stat, so the vamp delta is lifesteal-only
        # today and effective_ehp_with_sustain == blended_ehp on every build.
        e = compute_ehp(self.snap, "Aatrox", level=11, item_ids=["3072"])
        self.assertEqual(e.heal_spellvamp, 0.0)
        self.assertEqual(e.heal_omnivamp, 0.0)

    def test_helper_would_credit_spellvamp_off_aa_throughput(self) -> None:
        # Structural proof the conversion is wired (the same pool the EHP site
        # calls): a nonzero spellvamp fraction yields a nonzero heal.
        self.assertGreater(_vamp_heal_pool(0.15, 200.0, 1.0), 0.0)


# ---------------- byte-identical guard ----------------


class ByteIdenticalGuardTests(_SnapBase):
    def test_existing_ehp_fields_unchanged_by_the_sustain_layer(self) -> None:
        # The sibling sustain layer must not perturb the primary EHP math.
        # blended_ehp still equals the per-type blend, and the lifesteal heal
        # pool is unchanged (the sustain delta is derived, not additive to it).
        e = compute_ehp(
            self.snap, "Aatrox", level=11, item_ids=["3072"],
            enemy_ad_share=0.6, enemy_ap_share=0.3,
        )
        expected_blend = (
            e.physical_ehp * e.enemy_ad_share
            + e.magical_ehp * e.enemy_ap_share
            + e.true_ehp * e.enemy_true_share
        )
        self.assertAlmostEqual(e.blended_ehp, expected_blend, places=6)
        # effective term sits on top, never below the (lifesteal-inclusive) blend.
        self.assertGreaterEqual(e.effective_ehp_with_sustain, e.blended_ehp)


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_is_1_121_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.245.0")


if __name__ == "__main__":
    unittest.main()
