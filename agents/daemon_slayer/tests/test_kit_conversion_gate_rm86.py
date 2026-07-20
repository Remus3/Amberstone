"""RM-86 L1 - kit-conversion gate (default-OFF sort-key seam).

Spec: docs/specs/RM-86_scorer_kit_blindness_investigation.md sections 4 / 6 / 8 / 9.

RC-1 is that every scorer ranks candidates by ONE scalar objective into which the
champion enters through BASE STATS ONLY, so an item can raise the score through a
stat the kit cannot convert into output. BotRK raises Naafiri's modelled DPS
through attack speed she has no ratio for; Liandry's raises Orianna's modelled
ability damage through 300 HP an ability-DPS objective cannot read at all.

``kit_conversion_strength`` (default 0.0 = OFF, byte-identical sort) scales a
candidate's SORT score by the fraction of face value at which the champion's kit
actually converts each channel the item sells. Generalises the Slice-B
``ap_ad_coherence`` precedent (``onhit_dps.py:498-509``) from a boolean AP/AD
axis flag to a continuous per-channel vector in [0, 1]. Row fields stay RAW
(transparency); only the in-function sort key is scaled, and only downward.

The conversion vector is a curated champion-keyed registry, NOT a scan of
``damage_blocks``: verified 2026-07-18 that damage_blocks carries no
attack-speed, crit, on-hit or DoT key for ANY champion (all 1709 blocks, 171
champions), and that the loader drops ``effects_descriptions``
(``abilities.py:220-263``). Seeding therefore follows the
``_passive_damage_overrides.py`` prose-seeded precedent.

MEASURED REACHABILITY (main-thread simulation against live 16.14.1 deltas).
L1 only ever LOWERS a score, so it can never push a good item UP past untouched
neighbours. These acceptance anchors are reachable and asserted below:
  * Naafiri BotRK leaves #1 on carry and assassin routes
  * Orianna Liandry's leaves #1 while Blackfire is NOT suppressed with it
  * Poppy top-10 does not degrade (negative control)
These are NOT reachable by any L1 setting and are filed as L2 objective-coverage
work, deliberately NOT asserted here:
  * Olaf Stridebreaker rising from #34 (it and BotRK both carry
    PercentAttackSpeedMod 0.25, so no attack_speed fraction separates them;
    Stridebreaker's real justification is Halting Slash's engage slow and no
    objective contains a term for it)
  * Pantheon Heartsteel leaving #3 (pure HP, which is ON-AXIS for the bruiser
    objective, so exposure is zero on every channel and it floats up as
    neighbours fall)
"""

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import rank_items_by_ability_dps
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.kit_conversion import (
    KitConversion,
    kit_conversion,
    registry_champion_ids,
)
from agents.daemon_slayer.rank import rank_items

BOTRK = "3153"
VOLTAIC = "6699"
LIANDRYS = "6653"
BLACKFIRE = "2503"

# Same target profile the RM-86 invariance table was measured at.
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)


class ConversionGateHarness(unittest.TestCase):
    """Ranker helpers. ``rank_items_by_ehp`` takes enemy shares, NOT a target
    profile - it is the one ranker with a different target contract."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _carry(self, champ, **kw):
        res = rank_items(self.snap, champ, 16, mode="SR", top_n=60, **TARGET, **kw)
        return [r.item_id for r in res.ranked]

    def _assassin(self, champ, **kw):
        res = rank_items_by_burst(self.snap, champ, 16, mode="SR", top_n=60, **TARGET, **kw)
        return [r.item_id for r in res.ranked]

    def _mage(self, champ, **kw):
        res = rank_items_by_ability_dps(
            self.snap, champ, 16, mode="SR", top_n=60, **TARGET, **kw
        )
        return [r.item_id for r in res.ranked]

    def _tank(self, champ, **kw):
        res = rank_items_by_ehp(self.snap, champ, 16, mode="SR", top_n=60, **kw)
        return [r.item_id for r in res.ranked]


class DefaultOffByteIdenticalTests(ConversionGateHarness):
    """The non-negotiable contract: OFF must be byte-identical, not merely close.

    Mirrors the real default-off pattern at test_cost_aware_top_f2.py:60-62
    (absent param == explicit default), strengthened to compare FULL ordered
    lists. Deliberately does NOT copy test_onhit_dps.py:90-96, which is named
    ..._byte_identical but only asserts one item is present and would stay green
    if the off-path broke.
    """

    def test_omitted_param_equals_explicit_zero(self):
        for champ, helper in (
            ("Naafiri", self._carry),
            ("Naafiri", self._assassin),
            ("Orianna", self._mage),
            ("Poppy", self._tank),
        ):
            with self.subTest(champion=champ, route=helper.__name__):
                self.assertEqual(helper(champ), helper(champ, kit_conversion_strength=0.0))

    def test_zero_lever_does_not_mutate_any_row_field(self):
        off = rank_items(self.snap, "Naafiri", 16, mode="SR", top_n=60, **TARGET)
        zero = rank_items(
            self.snap, "Naafiri", 16, mode="SR", top_n=60,
            kit_conversion_strength=0.0, **TARGET,
        )
        self.assertEqual(
            [r.to_dict() for r in off.ranked], [r.to_dict() for r in zero.ranked]
        )

    def test_unseeded_champion_is_identity_at_full_strength(self):
        # Ziggs is absent from the registry, so every channel converts at 1.0 and
        # the gate is the identity even at full strength. This is the operational
        # proof that an unseeded default cannot move anyone.
        self.assertNotIn("Ziggs", registry_champion_ids())
        self.assertEqual(
            self._mage("Ziggs"), self._mage("Ziggs", kit_conversion_strength=1.0)
        )


class ReachableAnchorTests(ConversionGateHarness):
    def test_naafiri_botrk_leaves_top1_on_carry_route(self):
        # Every Naafiri damage block scales bonus_ad_pct only - zero AS terms,
        # zero crit terms, no attack-timer reset. BotRK wins today purely on
        # attack speed she cannot convert.
        self.assertEqual(self._carry("Naafiri")[0], BOTRK)
        self.assertNotEqual(self._carry("Naafiri", kit_conversion_strength=1.0)[0], BOTRK)

    def test_naafiri_botrk_leaves_top1_on_assassin_route(self):
        self.assertEqual(self._assassin("Naafiri")[0], BOTRK)
        self.assertNotEqual(
            self._assassin("Naafiri", kit_conversion_strength=1.0)[0], BOTRK
        )

    def test_naafiri_voltaic_climbs_on_assassin_route(self):
        # Voltaic Cyclosword is her 87% real first item and sits at #22 today.
        before = self._assassin("Naafiri").index(VOLTAIC)
        after = self._assassin("Naafiri", kit_conversion_strength=1.0).index(VOLTAIC)
        self.assertLess(after, before)

    def test_orianna_liandrys_leaves_top1_and_blackfire_is_not_suppressed(self):
        # The over-fire guard. BOTH items carry a burn passive, so a DoT-keyed
        # gate would suppress both. Liandry's spends 800g of its 3000g on HP an
        # ability-DPS objective cannot read; Blackfire spends none - its 600 mana
        # is mage-convertible. Only the off-axis-stat channel separates them.
        before = self._mage("Orianna")
        self.assertEqual(before[0], LIANDRYS)
        self.assertEqual(before[1], BLACKFIRE)

        after = self._mage("Orianna", kit_conversion_strength=0.5)
        self.assertNotEqual(after[0], LIANDRYS)
        self.assertEqual(after[0], BLACKFIRE, "Blackfire must NOT be suppressed with Liandry's")

    def test_poppy_tank_top10_does_not_degrade(self):
        # Negative control. Poppy is a REFUTE: her tank top-10 has zero exposure
        # on every channel, so every _conversion_key call must return the raw
        # value and the order must be preserved exactly.
        self.assertEqual(
            self._tank("Poppy")[:10],
            self._tank("Poppy", kit_conversion_strength=1.0)[:10],
        )


class UnreachableControlTests(ConversionGateHarness):
    def test_pyke_is_deliberately_absent_from_the_registry(self):
        # Pyke P: "Pyke's maximum health cannot increase except through growth
        # (per level), instead he gains bonus attack damage equal to 7.143% of
        # bonus health." damage_blocks is empty and parse_status is no_damage.
        # L1 only LOWERS a positive score; Pyke needs HP items RAISED and raw
        # max-HP credit REMOVED. Both have the wrong sign for this gate, and the
        # second is an objective change. Seeding him would be meaningless, so his
        # absence is the assertion.
        self.assertNotIn("Pyke", registry_champion_ids())
        self.assertEqual(
            self._carry("Pyke"), self._carry("Pyke", kit_conversion_strength=1.0)
        )


class GateContractTests(ConversionGateHarness):
    def test_gate_never_improves_a_penalised_item(self):
        # Monotonicity: BotRK's rank for Naafiri must never improve as the lever
        # rises. A gate that only lowers cannot promote what it penalises.
        ranks = [
            self._assassin("Naafiri", kit_conversion_strength=s).index(BOTRK)
            for s in (0.0, 0.25, 0.5, 0.75, 1.0)
        ]
        for weaker, stronger in zip(ranks, ranks[1:]):
            self.assertGreaterEqual(stronger, weaker, f"rank improved: {ranks}")

    def test_registry_invariants(self):
        ids = registry_champion_ids()
        self.assertGreater(len(ids), 0)
        snap_champs = DataSnapshot.load().champions
        for cid in ids:
            with self.subTest(champion=cid):
                entry = kit_conversion(cid)
                self.assertIsInstance(entry, KitConversion)
                self.assertIn(cid, snap_champs, "seeded id must resolve in the snapshot")
                self.assertTrue(entry.note.strip(), "every seed needs prose evidence")
                for channel in ("attack_speed", "crit", "on_hit", "off_axis_stat"):
                    value = getattr(entry, channel)
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)

    def test_unknown_champion_resolves_to_the_identity(self):
        entry = kit_conversion("NotAChampion")
        self.assertEqual(entry.attack_speed, 1.0)
        self.assertEqual(entry.crit, 1.0)
        self.assertEqual(entry.on_hit, 1.0)
        self.assertEqual(entry.off_axis_stat, 1.0)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.231.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_kit_conversion_module_is_ascii(self):
        import agents.daemon_slayer.kit_conversion as mod

        with open(mod.__file__, "rb") as fh:
            raw = fh.read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes in kit_conversion.py: {bad[:5]}")

    def test_this_test_file_is_ascii(self):
        with open(__file__, "rb") as fh:
            raw = fh.read()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII bytes in test file: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
