"""2026-06-19 (item 515) - missing-HP heal-AMPLIFICATION seam (ENGINE 1.146.0).

``compute_ability_hps`` gains ``assume_missing_hp_heal_amp`` (default False ->
byte-identical). When ON, a (champion, spell) in ``_MISSING_HP_HEAL_AMP`` has its
``heal_per_cast`` multiplied by ``1 + max_bonus * caster_missing_hp_pct`` - the
heal-AMP MULTIPLIER class the item-253 ``_passive_heal_overrides`` header
explicitly EXCLUDED from the heal-MAGNITUDE registry (a comeback multiplier on
the heal already computed, not a heal amount scaling on a stat).

Ground truth (``data/daemon_slayer/16.12.1/champion_abilities.json``,
effects_descriptions, probed 2026-06-19):
  Master Yi W Meditate    "healing himself ... increased by 0% : 100% (based on
                           missing health)"                              -> 1.0
  Lissandra R Frozen Tomb  "The healing is increased by 0% : 100% (based on
                           missing health at the time of cast)"          -> 1.0
  Sylas    W Kingslayer    "Sylas is also healed, increased by 0% : 100% (based
                           on his missing health)"                       -> 1.0
  Briar    P Crimson Curse "increases healing from all sources by 0% : 40%
                           (based on missing health)"                    -> 0.40
Nidalee E (Primal Surge) was probed and carries NO missing-HP amp text, so it is
NOT seeded (the directive example was loose; we never fabricate).
"""
from __future__ import annotations

import unittest
from pathlib import Path

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.abilities import AbilitiesSnapshot, AbilityForm
from agents.daemon_slayer.ability_hps import (
    _MISSING_HP_HEAL_AMP,
    _missing_hp_heal_amp_factor,
    compute_ability_hps,
)
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


def _spell(result, key):
    return next((s for s in result.spells if s.key == key), None)


def _stub_masteryi_w_heal(flat: float = 100.0) -> AbilitiesSnapshot:
    """MasterYi (a registered champ) with one flat-heal Meditate (W) block."""
    w_form = AbilityForm.from_dict({
        "key": "W", "name": "Meditate", "form_index": 0,
        "icon": None, "cooldown": [8.0], "cost": None, "damage_type": None,
        "targeting": None, "affects": None, "resource": "NONE",
        "is_aoe": False,
        "damage_blocks": [{
            "attribute": "Heal", "attribute_kind": "heal",
            "raw_modifiers": [{"values": [flat], "units": [""]}],
        }],
        "raw_effects_count": 0, "raw_leveling_count": 0,
        "parse_status": "ok", "parse_notes": [],
    })
    return AbilitiesSnapshot(
        patch="stub", fetched_at="", source="", coverage={},
        champions={"MasterYi": {
            "P": (), "Q": (), "W": (w_form,), "E": (), "R": (),
        }},
    )


class RegistryGroundTruthTests(unittest.TestCase):
    def test_registry_seeds_exactly_the_verified_champs(self):
        seeded = {
            (c, k) for c, sp in _MISSING_HP_HEAL_AMP.items() for k in sp
        }
        self.assertEqual(
            seeded,
            {("MasterYi", "W"), ("Lissandra", "R"), ("Sylas", "W"),
             ("Briar", "P")},
        )

    def test_registry_max_bonus_values(self):
        self.assertEqual(_MISSING_HP_HEAL_AMP["MasterYi"]["W"], 1.0)
        self.assertEqual(_MISSING_HP_HEAL_AMP["Lissandra"]["R"], 1.0)
        self.assertEqual(_MISSING_HP_HEAL_AMP["Sylas"]["W"], 1.0)
        self.assertAlmostEqual(_MISSING_HP_HEAL_AMP["Briar"]["P"], 0.40)

    def test_nidalee_not_seeded(self):
        # Directive example was loose: Primal Surge has no missing-HP amp text.
        self.assertNotIn("Nidalee", _MISSING_HP_HEAL_AMP)


class FactorRampTests(unittest.TestCase):
    def test_full_hp_is_identity(self):
        self.assertEqual(_missing_hp_heal_amp_factor("Sylas", "W", 0.0), 1.0)
        self.assertEqual(_missing_hp_heal_amp_factor("Briar", "P", 0.0), 1.0)

    def test_zero_hp_is_max_bonus(self):
        self.assertEqual(_missing_hp_heal_amp_factor("Sylas", "W", 1.0), 2.0)
        self.assertEqual(_missing_hp_heal_amp_factor("MasterYi", "W", 1.0), 2.0)
        self.assertEqual(_missing_hp_heal_amp_factor("Lissandra", "R", 1.0), 2.0)
        self.assertAlmostEqual(
            _missing_hp_heal_amp_factor("Briar", "P", 1.0), 1.40,
        )

    def test_linear_midpoint(self):
        self.assertEqual(_missing_hp_heal_amp_factor("Sylas", "W", 0.5), 1.5)
        self.assertAlmostEqual(
            _missing_hp_heal_amp_factor("Briar", "P", 0.5), 1.20,
        )

    def test_clamps_out_of_range_missing_pct(self):
        self.assertEqual(_missing_hp_heal_amp_factor("Sylas", "W", 1.7), 2.0)
        self.assertEqual(_missing_hp_heal_amp_factor("Sylas", "W", -0.3), 1.0)

    def test_unregistered_champ_or_spell_is_identity(self):
        self.assertEqual(_missing_hp_heal_amp_factor("Soraka", "R", 1.0), 1.0)
        self.assertEqual(  # right champ, wrong spell key
            _missing_hp_heal_amp_factor("Sylas", "Q", 1.0), 1.0,
        )
        self.assertEqual(
            _missing_hp_heal_amp_factor("MasterYi", "R", 1.0), 1.0,
        )


class SeamApplicationTests(unittest.TestCase):
    def test_seam_off_is_byte_identical(self):
        stub = _stub_masteryi_w_heal()
        off = compute_ability_hps(
            _SNAP, "MasterYi", 11, mode="SR", abilities=stub,
            caster_missing_hp_pct=1.0,
        )
        w = _spell(off, "W")
        self.assertIsNotNone(w)
        self.assertAlmostEqual(w.heal_per_cast, 100.0, places=6)

    def test_seam_on_doubles_at_zero_hp(self):
        stub = _stub_masteryi_w_heal()
        off = compute_ability_hps(
            _SNAP, "MasterYi", 11, mode="SR", abilities=stub,
            caster_missing_hp_pct=1.0,
        )
        on = compute_ability_hps(
            _SNAP, "MasterYi", 11, mode="SR", abilities=stub,
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=1.0,
        )
        wo, wn = _spell(off, "W"), _spell(on, "W")
        self.assertAlmostEqual(wn.heal_per_cast, 200.0, places=6)
        self.assertAlmostEqual(wn.heal_per_cast, 2.0 * wo.heal_per_cast, places=6)
        # cadence is unchanged -> heal_per_sec also doubles.
        self.assertAlmostEqual(wn.heal_per_sec, 2.0 * wo.heal_per_sec, places=6)
        self.assertAlmostEqual(
            on.total_heal_per_sec, 2.0 * off.total_heal_per_sec, places=6,
        )

    def test_seam_on_at_full_hp_is_identity(self):
        stub = _stub_masteryi_w_heal()
        on = compute_ability_hps(
            _SNAP, "MasterYi", 11, mode="SR", abilities=stub,
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=0.0,
        )
        self.assertAlmostEqual(_spell(on, "W").heal_per_cast, 100.0, places=6)

    def test_seam_on_emits_note(self):
        stub = _stub_masteryi_w_heal()
        on = compute_ability_hps(
            _SNAP, "MasterYi", 11, mode="SR", abilities=stub,
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=1.0,
        )
        self.assertTrue(
            any("missing-HP heal amp" in n for n in _spell(on, "W").notes),
        )

    def test_unregistered_champ_unaffected_by_seam(self):
        # Real Soraka (heal champ, NOT registered) is byte-identical on vs off.
        off = compute_ability_hps(
            _SNAP, "Soraka", 11, mode="SR", caster_missing_hp_pct=1.0,
        )
        on = compute_ability_hps(
            _SNAP, "Soraka", 11, mode="SR",
            assume_missing_hp_heal_amp=True, caster_missing_hp_pct=1.0,
        )
        self.assertAlmostEqual(
            off.total_ability_hps, on.total_ability_hps, places=9,
        )


class EngineVersionPinTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.212.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.212.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_files_are_ascii(self):
        for rel in (
            "ability_hps.py",
            "tests/test_missing_hp_heal_amp_item515.py",
        ):
            p = Path(__file__).resolve().parents[1] / rel
            data = p.read_bytes()
            non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
            self.assertEqual(non_ascii, [], f"{rel} has non-ASCII: {non_ascii[:5]}")


if __name__ == "__main__":
    unittest.main()
