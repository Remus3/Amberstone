"""Tests for the GAP 1 ability self-damage-amp override registry (item 239).

Covers:
- _amp_multiplier math: always_on (1+addend) + conditional (1+prob*addend).
- compute_ability_dps default == apply_ability_amps=False == no-entry path
  (byte-identical).
- Illaoi Q always_on amp applies end-to-end (synthetic Q damage block, since
  the live Illaoi Q form carries only a modifier block / no queryable damage).
- Mordekaiser Q isolation amp is probability-gated end-to-end (live form).
- Caitlyn W base="aa" entry is INERT in ability_dps even with the flag on.

Does NOT pin ENGINE_VERSION (orchestrator owns the bump).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._ability_amp_overrides import (
    _DEFAULT_AMP_PROBABILITY,
    AmpEntry,
    _ability_amp_for,
    _amp_multiplier,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot, AbilityForm
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


def _q_spell(result):
    for s in result.per_spell:
        if s.key == "Q":
            return s
    return None


def _w_spell(result):
    for s in result.per_spell:
        if s.key == "W":
            return s
    return None


def _illaoi_q_stub() -> AbilitiesSnapshot:
    """Illaoi with a synthetic Q carrying a real flat 100 damage block.

    The live Illaoi Q form holds only a 'Damage Increase' modifier block (no
    queryable ``attribute_kind=="damage"`` block), so the always_on multiplier
    has nothing to scale on the real form. This stub gives Q a flat 100 base
    so the always_on amp surfaces end-to-end at 0 armor.
    """
    q = AbilityForm.from_dict({
        "key": "Q", "name": "Stub Q", "form_index": 0, "icon": None,
        "cooldown": [6, 6, 6, 6, 6], "cost": None, "damage_type": "PHYSICAL",
        "targeting": None, "affects": None, "resource": "NONE", "is_aoe": False,
        "damage_blocks": [{
            "attribute": "Physical Damage", "attribute_kind": "damage",
            "base": [100, 100, 100, 100, 100],
        }],
        "raw_effects_count": 0, "raw_leveling_count": 0,
        "parse_status": "ok", "parse_notes": [],
    })
    return AbilitiesSnapshot(
        patch="stub", fetched_at="", source="", coverage={},
        champions={"Illaoi": {"P": (), "Q": (q,), "W": (), "E": (), "R": ()}},
    )


class AmpMultiplierMathTests(unittest.TestCase):
    def test_always_on_is_one_plus_addend(self):
        e = AmpEntry(amp_per_rank=(0.10, 0.15, 0.20, 0.25, 0.30),
                     base="ability", always_on=True)
        for rk, expect in enumerate((1.10, 1.15, 1.20, 1.25, 1.30)):
            self.assertAlmostEqual(
                _amp_multiplier(e, rk, _DEFAULT_AMP_PROBABILITY), expect)

    def test_conditional_is_one_plus_prob_times_addend(self):
        # isolation midpoint 0.5.
        e = AmpEntry(amp_per_rank=(0.30, 0.35, 0.40, 0.45, 0.50),
                     base="ability", condition="isolation")
        prob = _DEFAULT_AMP_PROBABILITY["isolation"]
        self.assertAlmostEqual(prob, 0.5)
        for rk in range(5):
            self.assertAlmostEqual(
                _amp_multiplier(e, rk, _DEFAULT_AMP_PROBABILITY),
                1.0 + prob * e.amp_per_rank[rk])

    def test_rank_clamped_to_tuple_bounds(self):
        e = AmpEntry(amp_per_rank=(0.10, 0.20), base="ability", always_on=True)
        self.assertAlmostEqual(_amp_multiplier(e, 7, _DEFAULT_AMP_PROBABILITY), 1.20)
        self.assertAlmostEqual(_amp_multiplier(e, -3, _DEFAULT_AMP_PROBABILITY), 1.10)

    def test_unknown_condition_is_inert(self):
        e = AmpEntry(amp_per_rank=(0.50,), base="ability", condition="nope")
        self.assertEqual(_amp_multiplier(e, 0, _DEFAULT_AMP_PROBABILITY), 1.0)

    def test_empty_amp_per_rank_is_unity(self):
        e = AmpEntry(amp_per_rank=(), base="ability", always_on=True)
        self.assertEqual(_amp_multiplier(e, 0, _DEFAULT_AMP_PROBABILITY), 1.0)


class RegistryShapeTests(unittest.TestCase):
    def test_illaoi_q_is_always_on_ability(self):
        e = _ability_amp_for("Illaoi", "Q", 0)
        self.assertIsNotNone(e)
        self.assertEqual(e.base, "ability")
        self.assertTrue(e.always_on)
        self.assertEqual(e.amp_per_rank, (0.10, 0.15, 0.20, 0.25, 0.30))

    def test_mordekaiser_q_is_isolation_ability(self):
        e = _ability_amp_for("Mordekaiser", "Q", 0)
        self.assertIsNotNone(e)
        self.assertEqual(e.base, "ability")
        self.assertFalse(e.always_on)
        self.assertEqual(e.condition, "isolation")

    def test_caitlyn_w_is_aa_base(self):
        e = _ability_amp_for("Caitlyn", "W", 0)
        self.assertIsNotNone(e)
        self.assertEqual(e.base, "aa")

    def test_unmapped_returns_none(self):
        self.assertIsNone(_ability_amp_for("Ahri", "Q", 0))


class ByteIdenticalDefaultTests(unittest.TestCase):
    def test_default_equals_false_equals_no_entry_path(self):
        # Illaoi: default-omitted == explicit False == an unmapped champ path.
        stub = _illaoi_q_stub()
        r_default = compute_ability_dps(
            _SNAP, "Illaoi", 9, item_ids=[], mode="SR", abilities_snapshot=stub)
        r_false = compute_ability_dps(
            _SNAP, "Illaoi", 9, item_ids=[], mode="SR", abilities_snapshot=stub,
            apply_ability_amps=False)
        self.assertEqual(r_default.total_ability_dps, r_false.total_ability_dps)
        # And the flag-on amp DOES change it (sanity: the fixture is live).
        r_on = compute_ability_dps(
            _SNAP, "Illaoi", 9, item_ids=[], mode="SR", abilities_snapshot=stub,
            apply_ability_amps=True)
        self.assertGreater(r_on.total_ability_dps, r_false.total_ability_dps)

    def test_unmapped_champion_byte_identical(self):
        # Ahri has no amp entry on any key -> flag on/off identical.
        off = compute_ability_dps(_SNAP, "Ahri", 9, item_ids=[], mode="SR",
                                  apply_ability_amps=False)
        on = compute_ability_dps(_SNAP, "Ahri", 9, item_ids=[], mode="SR",
                                 apply_ability_amps=True)
        self.assertEqual(off.total_ability_dps, on.total_ability_dps)


class AlwaysOnEngineTests(unittest.TestCase):
    """Illaoi Q always_on amp surfaces end-to-end via the synthetic stub."""

    def _q_post_mit(self, level, amps):
        stub = _illaoi_q_stub()
        r = compute_ability_dps(_SNAP, "Illaoi", level, item_ids=[], mode="SR",
                                abilities_snapshot=stub, apply_ability_amps=amps)
        return _q_spell(r).post_mitigation_damage_per_cast

    def test_exact_multiplier_at_each_rank(self):
        # 0 armor -> post_mit == base(100) * amp_factor. Q maxed first.
        # L3 rank1 -> 1.15, L5 rank2 -> 1.20, L9 rank4 -> 1.30.
        for level, expect in ((3, 115.0), (5, 120.0), (9, 130.0)):
            self.assertAlmostEqual(self._q_post_mit(level, False), 100.0)
            self.assertAlmostEqual(self._q_post_mit(level, True), expect)


class ConditionalEngineTests(unittest.TestCase):
    """Mordekaiser Q isolation amp is probability-gated end-to-end (live form)."""

    def _q_dps(self, amps):
        r = compute_ability_dps(_SNAP, "Mordekaiser", 9, item_ids=[], mode="SR",
                                apply_ability_amps=amps)
        return _q_spell(r).dps

    def test_isolation_amp_is_prob_gated(self):
        off = self._q_dps(False)
        on = self._q_dps(True)
        self.assertGreater(off, 0.0)
        # Mord Q rank at L9 (Q maxed first) -> rank4 -> addend 0.50 -> factor
        # 1 + 0.5*0.50 = 1.25.
        self.assertAlmostEqual(on / off, 1.25, places=4)


class AaBaseInertTests(unittest.TestCase):
    """A base='aa' entry never fires in ability_dps even with the flag on."""

    def _w_value(self, amps):
        r = compute_ability_dps(_SNAP, "Caitlyn", 9, item_ids=[], mode="SR",
                                apply_ability_amps=amps)
        w = _w_spell(r)
        return (w.dps, w.post_mitigation_damage_per_cast)

    def test_caitlyn_w_inert_with_flag_on(self):
        off = self._w_value(False)
        on = self._w_value(True)
        self.assertEqual(off, on)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_are_ascii(self):
        import agents.daemon_slayer._ability_amp_overrides as mod
        for path in (mod.__file__, __file__):
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertTrue(raw.decode("ascii"),
                            f"non-ASCII byte in {path}")


if __name__ == "__main__":
    unittest.main()
