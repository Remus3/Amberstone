"""ENGINE 1.29.0 -> 1.31.0 (2026-05-21) - per-spell CC duration seam.

Closes the item 129 carry-forward (a) at 1.29.0 (the EMPTY seam) +
the item 130 carry-forward (b) at 1.30.0 (REGISTRY SEEDED with 30
starter entries across 24 champions) + item 134 carry-forward (h) at
1.31.0 (registry wave 2, +23 entries / +20 champs = 53 / 44 total).
2nd consumer of the ``effective_cc_duration`` helper shipped 1.25.0
(item 122). The helper itself lives in ``ehp.py`` (free function); this
slice exposes the downstream-consumer surface at the per-spell
AbilityDps layer so a future EHP-vs-CC blended scorer (or fight-sim)
can read per-rank base CC durations + the matching post-tenacity
values without re-resolving the champion.

Contract:

* ``_PER_SPELL_CC_DURATIONS: dict[str, dict[str, tuple[float, ...]]]``
  module-level registry seam in ``ability_dps.py``. EMPTY at 1.29.0,
  SEEDED at 1.30.0 (30/24), EXTENDED 1.31.0 wave 2 (53/44 total;
  full pin split between ``test_per_spell_cc_registry_seed.py`` and
  ``test_per_spell_cc_registry_wave2.py``).
* ``AbilitySpellDps.cc_duration_s`` defaults to ``()`` (per-rank base
  CC tuple from the registry).
* ``AbilitySpellDps.cc_duration_post_tenacity`` defaults to ``()`` (the
  element-wise ``effective_cc_duration(base, tenacity_mult)`` result).

Coverage classes:

* ``CcDurationFieldsSchemaTests`` - dataclass shape, default empty
  tuple, to_dict carries both fields, frozen-dataclass enforcement.
* ``RegistrySeamTests`` - the registry exists as a dict, is non-empty
  at 1.30.0+ (1.31.0 wave 2 = 53 entries), unknown champion returns
  identity (empty tuples).
* ``EffectiveCcDurationConsumerTests`` - registry entries exercised
  via monkey-patch (registry cleared in setUp); tenacity=1.0 identity,
  tenacity=1.20 scales, tenacity=0.0 zeros, missing champion empty,
  partial spell coverage (only some spells populated), SR mode
  identity, multi-rank tuple order preserved, post-tuple length
  matches base.
* ``EmptySeamBehaviorTests`` - with the registry cleared in setUp,
  a live ``compute_ability_dps`` call shows every spell carries ``()``
  on both fields. Production byte-identical to a pre-1.30.0 unseeded
  state, restored in tearDown.
* ``EngineVersionCurrentTests`` - pin ENGINE_VERSION 1.31.0.
"""
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer import ability_dps
from agents.daemon_slayer.ability_dps import (
    AbilitySpellDps,
    _PER_SPELL_CC_DURATIONS,
    _apply_tenacity_to_cc_tuple,
    _per_spell_cc_for,
    compute_ability_dps,
)
from agents.daemon_slayer.data_loader import DataSnapshot


# ---------------- dataclass schema ----------------


class CcDurationFieldsSchemaTests(unittest.TestCase):
    """``AbilitySpellDps`` carries the 2 new tuple fields."""

    def _build(self, **overrides) -> AbilitySpellDps:
        defaults = dict(
            key="Q", form_name="x", form_index=0, rank=1, cooldown=6.0,
            cost=0.0, damage_type=None, resource=None,
            raw_damage_per_cast=0.0, post_mode_damage_per_cast=0.0,
            post_mitigation_damage_per_cast=0.0,
            casts_per_sec=0.0, casts_per_sec_source="missing",
            mana_uptime_factor=1.0, dps=0.0,
        )
        defaults.update(overrides)
        return AbilitySpellDps(**defaults)

    def test_default_cc_duration_s_is_empty_tuple(self) -> None:
        s = self._build()
        self.assertEqual(s.cc_duration_s, ())

    def test_default_cc_duration_post_tenacity_is_empty_tuple(self) -> None:
        s = self._build()
        self.assertEqual(s.cc_duration_post_tenacity, ())

    def test_populated_cc_duration_s_preserves_tuple(self) -> None:
        s = self._build(cc_duration_s=(1.0, 1.25, 1.5))
        self.assertEqual(s.cc_duration_s, (1.0, 1.25, 1.5))

    def test_populated_post_tenacity_preserves_tuple(self) -> None:
        s = self._build(cc_duration_post_tenacity=(1.2, 1.5))
        self.assertEqual(s.cc_duration_post_tenacity, (1.2, 1.5))

    def test_to_dict_carries_both_fields_when_empty(self) -> None:
        s = self._build()
        d = s.to_dict()
        self.assertIn("cc_duration_s", d)
        self.assertIn("cc_duration_post_tenacity", d)
        self.assertEqual(d["cc_duration_s"], [])
        self.assertEqual(d["cc_duration_post_tenacity"], [])

    def test_to_dict_serializes_populated_tuple_as_list(self) -> None:
        s = self._build(
            cc_duration_s=(1.0, 1.25),
            cc_duration_post_tenacity=(1.2, 1.5),
        )
        d = s.to_dict()
        self.assertEqual(d["cc_duration_s"], [1.0, 1.25])
        self.assertEqual(d["cc_duration_post_tenacity"], [1.2, 1.5])

    def test_frozen_dataclass_rejects_mutation(self) -> None:
        s = self._build()
        with self.assertRaises(FrozenInstanceError):
            s.cc_duration_s = (1.0,)
        with self.assertRaises(FrozenInstanceError):
            s.cc_duration_post_tenacity = (1.0,)

    def test_post_and_base_can_differ_in_length(self) -> None:
        # Defense against accidental coupling: the dataclass schema
        # doesn't enforce shape equality (consumer math does).
        s = self._build(
            cc_duration_s=(1.0, 1.5),
            cc_duration_post_tenacity=(1.2, 1.8, 2.4),
        )
        self.assertEqual(len(s.cc_duration_s), 2)
        self.assertEqual(len(s.cc_duration_post_tenacity), 3)


# ---------------- registry seam ----------------


class RegistrySeamTests(unittest.TestCase):
    """The ``_PER_SPELL_CC_DURATIONS`` registry is the displacement seam."""

    def test_registry_is_a_dict(self) -> None:
        self.assertIsInstance(_PER_SPELL_CC_DURATIONS, dict)

    def test_registry_is_non_empty_at_1_30_0(self) -> None:
        # ENGINE 1.30.0 seeded the registry; ``test_registry_seed_size`` in
        # ``test_per_spell_cc_registry_seed.py`` pins the exact counts.
        self.assertGreater(len(_PER_SPELL_CC_DURATIONS), 0)

    def test_unknown_champion_returns_empty_tuple(self) -> None:
        self.assertEqual(_per_spell_cc_for("UnknownChamp_xyz", "Q"), ())

    def test_unknown_spell_for_known_pattern_returns_empty(self) -> None:
        # Even with a monkey-patched champ entry, an unknown key returns ().
        # Use a synthetic champion id that does not collide with the
        # ENGINE 1.30.0 registry seed.
        try:
            _PER_SPELL_CC_DURATIONS["AnnieTest_xyz"] = {"Q": (1.0,)}
            self.assertEqual(_per_spell_cc_for("AnnieTest_xyz", "W"), ())
            self.assertEqual(_per_spell_cc_for("AnnieTest_xyz", "Q"), (1.0,))
        finally:
            _PER_SPELL_CC_DURATIONS.pop("AnnieTest_xyz", None)


# ---------------- consumer math (monkey-patched registry) ----------------


class EffectiveCcDurationConsumerTests(unittest.TestCase):
    """``_apply_tenacity_to_cc_tuple`` is the consumer wrapper around
    ``ehp.effective_cc_duration``. Tested on its own + via end-to-end
    ``compute_ability_dps`` with a monkey-patched registry entry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def setUp(self) -> None:
        # Clean snapshot per test - no leakage between cases.
        self._registry_backup = dict(_PER_SPELL_CC_DURATIONS)
        _PER_SPELL_CC_DURATIONS.clear()

    def tearDown(self) -> None:
        _PER_SPELL_CC_DURATIONS.clear()
        _PER_SPELL_CC_DURATIONS.update(self._registry_backup)

    def _spell(self, champion: str, key: str, level: int, mode: str):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=[], mode=mode,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_tenacity_1_0_returns_identity_values(self) -> None:
        # Annie carries aramTenacity = 1.0 (default - no entry).
        base = (1.0, 1.25, 1.5, 1.75, 2.0)
        result = _apply_tenacity_to_cc_tuple(base, 1.0)
        self.assertEqual(result, base)

    def test_tenacity_1_20_scales_each_element(self) -> None:
        base = (1.0, 1.5, 2.0)
        result = _apply_tenacity_to_cc_tuple(base, 1.20)
        for i, val in enumerate(result):
            self.assertAlmostEqual(val, base[i] * 1.20, places=6)

    def test_tenacity_zero_zeros_out_each_element(self) -> None:
        base = (1.0, 2.0, 3.0)
        result = _apply_tenacity_to_cc_tuple(base, 0.0)
        for val in result:
            self.assertEqual(val, 0.0)

    def test_empty_base_returns_empty_post(self) -> None:
        # Mirrors the empty-registry behavior.
        self.assertEqual(_apply_tenacity_to_cc_tuple((), 1.20), ())

    def test_multi_rank_tuple_order_preserved(self) -> None:
        base = (1.0, 1.5, 2.0, 2.5, 3.0)
        result = _apply_tenacity_to_cc_tuple(base, 1.20)
        # Order check: result[i] corresponds to base[i].
        for i in range(len(base)):
            self.assertAlmostEqual(result[i], base[i] * 1.20, places=6)

    def test_post_tuple_length_matches_base_tuple_length(self) -> None:
        base = (1.0, 2.0)
        self.assertEqual(
            len(_apply_tenacity_to_cc_tuple(base, 1.0)), len(base)
        )
        base3 = (1.0, 1.5, 2.0)
        self.assertEqual(
            len(_apply_tenacity_to_cc_tuple(base3, 0.85)), len(base3)
        )

    def test_compute_ability_dps_uses_registry_for_known_champ(self) -> None:
        # Inject Annie W = (1.0, 1.25, 1.5, 1.75, 2.0); Annie carries
        # tenacity 1.0 (no aramTenacity entry) so post == base.
        _PER_SPELL_CC_DURATIONS["Annie"] = {
            "W": (1.0, 1.25, 1.5, 1.75, 2.0),
        }
        w = self._spell("Annie", "W", level=11, mode="ARAM")
        self.assertIsNotNone(w)
        self.assertEqual(w.cc_duration_s, (1.0, 1.25, 1.5, 1.75, 2.0))
        # Annie ARAM tenacity_mult = 1.0 -> identity.
        self.assertEqual(
            w.cc_duration_post_tenacity, (1.0, 1.25, 1.5, 1.75, 2.0)
        )

    def test_compute_ability_dps_applies_tenacity_for_aram_modified_champ(
        self,
    ) -> None:
        # Katarina aramTenacity = 1.20 (item 122 / item 126).
        _PER_SPELL_CC_DURATIONS["Katarina"] = {
            "W": (1.0, 1.5, 2.0, 2.5, 3.0),
        }
        w = self._spell("Katarina", "W", level=11, mode="ARAM")
        self.assertIsNotNone(w)
        self.assertEqual(w.cc_duration_s, (1.0, 1.5, 2.0, 2.5, 3.0))
        # tenacity 1.20 -> each element x 1.20.
        for i, val in enumerate(w.cc_duration_post_tenacity):
            self.assertAlmostEqual(val, (1.0 + 0.5 * i) * 1.20, places=6)

    def test_sr_mode_strips_tenacity_keeps_identity(self) -> None:
        # SR mode -> aram_tenacity_mult defaults to 1.0; post == base.
        _PER_SPELL_CC_DURATIONS["Katarina"] = {
            "W": (1.0, 1.5, 2.0, 2.5, 3.0),
        }
        w = self._spell("Katarina", "W", level=11, mode="SR")
        self.assertIsNotNone(w)
        self.assertEqual(w.cc_duration_s, (1.0, 1.5, 2.0, 2.5, 3.0))
        self.assertEqual(
            w.cc_duration_post_tenacity, (1.0, 1.5, 2.0, 2.5, 3.0),
        )

    def test_partial_spell_coverage_leaves_others_empty(self) -> None:
        # Only W populated; Q/E/R stay empty tuples.
        _PER_SPELL_CC_DURATIONS["Annie"] = {
            "W": (1.0, 1.25, 1.5),
        }
        out = compute_ability_dps(
            self.snap, "Annie", level=11, item_ids=[], mode="ARAM",
        )
        spells = {s.key: s for s in out.per_spell}
        self.assertEqual(spells["Q"].cc_duration_s, ())
        self.assertEqual(spells["Q"].cc_duration_post_tenacity, ())
        self.assertEqual(spells["W"].cc_duration_s, (1.0, 1.25, 1.5))
        self.assertEqual(spells["E"].cc_duration_s, ())
        self.assertEqual(spells["R"].cc_duration_s, ())


# ---------------- empty-seam production behavior ----------------


class EmptySeamBehaviorTests(unittest.TestCase):
    """Pins the empty-registry contract from ENGINE 1.29.0 (when the seam
    shipped empty). Each test setUp clears the registry, runs the case,
    and tearDown restores the live 1.30.0 seed - the empty-registry
    contract remains exercised even though the live registry is now
    populated. Production behavior with the registry populated is pinned
    by ``test_per_spell_cc_registry_seed.py``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def setUp(self) -> None:
        # Force the registry to the empty state for this test class
        # even if a previous test leaked entries (and over the live
        # ENGINE 1.30.0 seed).
        self._registry_backup = dict(_PER_SPELL_CC_DURATIONS)
        _PER_SPELL_CC_DURATIONS.clear()

    def tearDown(self) -> None:
        _PER_SPELL_CC_DURATIONS.clear()
        _PER_SPELL_CC_DURATIONS.update(self._registry_backup)

    def test_annie_all_spells_have_empty_cc_tuples_in_sr(self) -> None:
        out = compute_ability_dps(
            self.snap, "Annie", level=11, item_ids=[], mode="SR",
        )
        for s in out.per_spell:
            self.assertEqual(s.cc_duration_s, ())
            self.assertEqual(s.cc_duration_post_tenacity, ())

    def test_annie_all_spells_have_empty_cc_tuples_in_aram(self) -> None:
        out = compute_ability_dps(
            self.snap, "Annie", level=11, item_ids=[], mode="ARAM",
        )
        for s in out.per_spell:
            self.assertEqual(s.cc_duration_s, ())
            self.assertEqual(s.cc_duration_post_tenacity, ())

    def test_katarina_aram_empty_seam_no_lift(self) -> None:
        # Even a champ with aramTenacity > 1.0 sees identity-empty
        # because the registry has no Katarina entry to scale.
        out = compute_ability_dps(
            self.snap, "Katarina", level=11, item_ids=[], mode="ARAM",
        )
        for s in out.per_spell:
            self.assertEqual(s.cc_duration_s, ())
            self.assertEqual(s.cc_duration_post_tenacity, ())


# ---------------- helpers exposed ----------------


class HelpersExposedTests(unittest.TestCase):
    """The 3 module-level seam symbols are importable + the registry
    is monkey-patchable by tests via dict mutation."""

    def test_per_spell_cc_for_is_callable(self) -> None:
        # Free function callable; safe for None champion / spell.
        self.assertEqual(_per_spell_cc_for("", ""), ())
        self.assertEqual(_per_spell_cc_for("Annie", ""), ())

    def test_apply_tenacity_handles_zero_tenacity(self) -> None:
        # 0.0 tenacity multiplier zeros each element; doesn't raise.
        result = _apply_tenacity_to_cc_tuple((1.0, 1.5), 0.0)
        self.assertEqual(len(result), 2)
        for v in result:
            self.assertEqual(v, 0.0)

    def test_apply_tenacity_handles_negative_floored(self) -> None:
        # The underlying ehp.effective_cc_duration floors tenacity at 0;
        # the wrapper should propagate that floor cleanly.
        result = _apply_tenacity_to_cc_tuple((1.0, 2.0), -0.5)
        for v in result:
            self.assertEqual(v, 0.0)

    def test_registry_mutation_is_test_friendly(self) -> None:
        # Demonstrate the monkey-patch idiom used by consumer tests.
        try:
            _PER_SPELL_CC_DURATIONS["Foo"] = {"Q": (1.0,)}
            self.assertEqual(_per_spell_cc_for("Foo", "Q"), (1.0,))
        finally:
            _PER_SPELL_CC_DURATIONS.pop("Foo", None)
        # State restored after pop.
        self.assertEqual(_per_spell_cc_for("Foo", "Q"), ())


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_at_1_31_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.166.0")


if __name__ == "__main__":
    unittest.main()
