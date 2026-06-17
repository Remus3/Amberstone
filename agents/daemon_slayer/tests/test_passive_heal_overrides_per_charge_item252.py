"""item 252 - PER-CHARGE effects-text HEAL seam (sibling of item-249 per-stack).

Extends ``_passive_heal_overrides`` with a per-charge fold: ``PassiveHealEntry``
gains ``per_charge`` (a tuple of ``(value, unit)`` linear terms read "per
charge") + ``assumed_charges`` (the operator-tunable steady-state stock).
``to_heal_block`` FOLDS each per_charge term * assumed_charges into
``raw_modifiers`` at BUILD time, so the existing ``_eval_heal_shield_block``
needs ZERO new math. The sole per-charge heal is Taric Q Starlight's Touch
(25 + 15% AP + 1% of max HP per charge; assumed_charges 3.0).

DEFAULT (apply_passive_heal=False / load_default) stays byte-identical: the seam
injects only under the opt-in flag. Taric Q's terms are flat / caster-stat, so
the flag-ON heal resolves NON-zero with no HP assumption (like the item-251
linear caster-stat seeds) - resolve_target_relative does not change it.

Verbatim 16.11.1 effects_descriptions back each pinned value.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    load_default,
)
from agents.daemon_slayer.ability_hps import compute_ability_hps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer._passive_heal_overrides import (
    _PASSIVE_HEAL_OVERRIDES,
    PassiveHealEntry,
    to_heal_block,
)

_PATCH = "16.11.1"
_TARIC_KEY = ("Taric", "Q", 0)


def _snap() -> DataSnapshot:
    return DataSnapshot.load()


def _heal(cid, lvl, ab, *, rtr=False, items=None):
    r = compute_ability_hps(
        _snap(), cid, lvl, item_ids=items, abilities=ab,
        resolve_target_relative=rtr,
    )
    return {s.key: s.heal_per_cast for s in r.spells}, r.total_heal_per_sec


class RegistryShapeTests(unittest.TestCase):
    def test_taric_q_present(self) -> None:
        self.assertIn(_TARIC_KEY, _PASSIVE_HEAL_OVERRIDES)

    def test_taric_q_per_charge_terms(self) -> None:
        e = _PASSIVE_HEAL_OVERRIDES[_TARIC_KEY]
        self.assertEqual(e.linear_terms, ())
        self.assertEqual(
            e.per_charge,
            ((25.0, ""), (15.0, "% ap"), (1.0, "% maximum health")),
        )
        self.assertEqual(e.assumed_charges, 3.0)
        self.assertEqual(e.cadence, "per_cast")
        self.assertEqual(e.attribute, "Starlight's Touch")
        self.assertFalse(e.level_scaled)
        self.assertEqual(e.bilinear_terms, ())

    def test_taric_q_is_only_per_charge_entry(self) -> None:
        # item 252 exhaust: Taric Q is the sole per-charge heal in the registry
        # (Zeri P is a damage charge, not a heal -> not seeded here).
        with_pc = [
            k for k, e in _PASSIVE_HEAL_OVERRIDES.items() if e.per_charge
        ]
        self.assertEqual(with_pc, [_TARIC_KEY])


class SchemaFieldDefaultTests(unittest.TestCase):
    def test_new_fields_default_empty(self) -> None:
        e = PassiveHealEntry(
            linear_terms=((10.0, ""),), cadence="per_cast", note="x",
        )
        self.assertEqual(e.per_charge, ())
        self.assertEqual(e.assumed_charges, 0.0)

    def test_prior_entries_leave_per_charge_default(self) -> None:
        # every NON-Taric entry carries no per_charge term (byte-identical).
        for key, e in _PASSIVE_HEAL_OVERRIDES.items():
            if key == _TARIC_KEY:
                continue
            self.assertEqual(e.per_charge, (), key)
            self.assertEqual(e.assumed_charges, 0.0, key)


class FoldTests(unittest.TestCase):
    def test_taric_block_folds_at_assumed_charges(self) -> None:
        # 3 per-charge terms folded * 3.0: 25->75 flat, 15%->45% AP, 1%->3% maxHP.
        block = to_heal_block(_PASSIVE_HEAL_OVERRIDES[_TARIC_KEY])
        self.assertEqual(block.attribute_kind, "heal")
        self.assertEqual(
            block.raw_modifiers,
            (
                {"values": [75.0], "units": [""]},
                {"values": [45.0], "units": ["% ap"]},
                {"values": [3.0], "units": ["% maximum health"]},
            ),
        )
        self.assertEqual(block.bilinear_terms, ())

    def test_fold_scales_tuple_value_elementwise(self) -> None:
        e = PassiveHealEntry(
            linear_terms=(),
            per_charge=(((1.0, 2.0, 3.0), ""),),
            assumed_charges=2.0,
            cadence="per_cast",
            note="x",
        )
        block = to_heal_block(e)
        self.assertEqual(
            block.raw_modifiers,
            ({"values": [2.0, 4.0, 6.0], "units": [""]},),
        )

    def test_no_per_charge_block_has_only_linear(self) -> None:
        # an entry without per_charge yields raw_modifiers from linear_terms only.
        fiora = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Fiora", "P", 0)])
        self.assertEqual(len(fiora.raw_modifiers), 1)  # the lerp flat base only

    def test_zero_assumed_charges_drops_per_charge(self) -> None:
        e = PassiveHealEntry(
            linear_terms=((5.0, ""),),
            per_charge=((25.0, ""),),
            assumed_charges=0.0,
            cadence="per_cast",
            note="x",
        )
        block = to_heal_block(e)
        # per_charge term contributes nothing at assumed_charges 0.
        self.assertEqual(block.raw_modifiers, ({"values": [5.0], "units": [""]},))


class DefaultByteIdenticalTests(unittest.TestCase):
    def test_default_load_taric_heal_zero(self) -> None:
        ab = load_default()  # apply_passive_heal flag OFF (default)
        _, total = _heal("Taric", 11, ab)
        self.assertEqual(total, 0.0)

    def test_default_taric_q_not_scored(self) -> None:
        ab = load_default()
        per_key, _ = _heal("Taric", 11, ab)
        self.assertEqual(per_key.get("Q", 0.0), 0.0)


class FlagOnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ab_on = AbilitiesSnapshot.load(apply_passive_heal=True)

    def test_taric_q_surfaces_above_flat(self) -> None:
        per_key, total = _heal("Taric", 11, self.ab_on)
        q = per_key.get("Q", 0.0)
        # 75 flat + 0.03*caster_max_hp (>0) + 0.45*AP(0 itemless) -> > 75.
        self.assertGreater(q, 75.0)
        self.assertGreater(total, 0.0)

    def test_taric_q_resolve_target_relative_invariant(self) -> None:
        # caster-stat heal: rtr ON vs OFF give the SAME value (not a lower-bound
        # target-relative seed - it resolves at the default, no HP assumption).
        off, _ = _heal("Taric", 11, self.ab_on, rtr=False)
        on, _ = _heal("Taric", 11, self.ab_on, rtr=True)
        self.assertAlmostEqual(off.get("Q", 0.0), on.get("Q", 0.0), places=6)

    def test_taric_q_ap_scaling(self) -> None:
        # adding AP raises the Q heal via the 45% AP folded term.
        itemless, _ = _heal("Taric", 11, self.ab_on)
        ap_build, _ = _heal("Taric", 11, self.ab_on, items=["6655", "3157"])
        self.assertGreater(ap_build.get("Q", 0.0), itemless.get("Q", 0.0))


class ExistingHealBlockGateTests(unittest.TestCase):
    def test_soraka_unchanged_flag_on(self) -> None:
        # Soraka has real heal blocks; the no-existing-heal-block gate skips
        # injection -> flag ON == OFF for her.
        off = compute_ability_hps(
            _snap(), "Soraka", 11, abilities=load_default(),
        ).total_heal_per_sec
        on = compute_ability_hps(
            _snap(), "Soraka", 11,
            abilities=AbilitiesSnapshot.load(apply_passive_heal=True),
        ).total_heal_per_sec
        self.assertAlmostEqual(off, on, places=4)


class EnginePinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.140.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self) -> None:
        import agents.daemon_slayer._passive_heal_overrides as m

        with open(m.__file__, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                line.encode("ascii")  # raises on any non-ASCII byte

    def test_test_file_ascii(self) -> None:
        with open(__file__, encoding="utf-8") as fh:
            for line in fh:
                line.encode("ascii")


if __name__ == "__main__":
    unittest.main()
