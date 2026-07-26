"""item 260 - effects-text-only SHIELD registry (GAP 2).

New ``_passive_shield_overrides.py`` (sibling of the heal/damage registries):
a synthetic ``attribute_kind="shield"`` block for the self-shields whose magnitude
lives only in stripped ``effects_descriptions`` (no shield block parsed). The
consumer (``ability_hps._eval_heal_shield_block`` / ``compute_ability_hps``)
already scores shield blocks, so the only additions are the registry, the
``_apply_passive_shield_overrides`` load seam (``apply_passive_shield=True``,
default OFF), and the additive ``% maximum mana`` -> ``caster_max_mp`` unit.

DEFAULT (apply_passive_shield=False / load_default) stays byte-identical: the seam
injects only under the opt-in flag. Every seeded shield is a CASTER stat (max HP /
max mana / bonus HP / AP / flat-per-level) so the flag-ON shield resolves NON-zero
with no HP assumption; none is target-relative.

Verbatim 16.11.1 effects_descriptions back each pinned value.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer._passive_damage_overrides import _lerp_per_level
from agents.daemon_slayer._passive_shield_overrides import (
    _PASSIVE_SHIELD_OVERRIDES,
    PassiveShieldEntry,
    to_shield_block,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot, load_default
from agents.daemon_slayer.ability_hps import _HEAL_UNIT_TO_CTX, compute_ability_hps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import build_champion

_PATCH = "16.11.1"

# Every seeded (champion_id, key, form_index).
_KEYS = {
    "Malphite": ("Malphite", "P", 0),
    "Camille": ("Camille", "P", 0),
    "Vi": ("Vi", "P", 0),
    "Rakan": ("Rakan", "P", 0),
    "Shen": ("Shen", "P", 0),
    "Yasuo": ("Yasuo", "P", 0),
    "Blitzcrank": ("Blitzcrank", "P", 0),
    "Skarner": ("Skarner", "W", 0),
    "Volibear": ("Volibear", "E", 0),
    "Viktor": ("Viktor", "Q", 0),
}


def _snap() -> DataSnapshot:
    return DataSnapshot.load()


def _shield(cid, lvl, ab, key, *, items=None):
    r = compute_ability_hps(_snap(), cid, lvl, item_ids=items, abilities=ab)
    by_key = {s.key: s.shield_per_cast for s in r.spells}
    return by_key.get(key, 0.0), r.total_shield_per_sec


def _max_hp(cid, lvl, items=None):
    r = build_champion(_snap(), cid, lvl, item_ids=items, mode="SR")
    return float((r.stats or {}).get("hp", 0.0))


def _max_mp(cid, lvl, items=None):
    r = build_champion(_snap(), cid, lvl, item_ids=items, mode="SR")
    return float((r.stats or {}).get("mp", 0.0))


class RegistryShapeTests(unittest.TestCase):
    def test_all_ten_present(self) -> None:
        for k in _KEYS.values():
            self.assertIn(k, _PASSIVE_SHIELD_OVERRIDES, k)

    def test_registry_size_is_ten(self) -> None:
        self.assertEqual(len(_PASSIVE_SHIELD_OVERRIDES), 10)

    def test_pct_max_hp_terms(self) -> None:
        cases = {
            "Malphite": 10.0,
            "Camille": 20.0,
            "Vi": 12.0,
            "Skarner": 8.0,
        }
        for cid, pct in cases.items():
            e = _PASSIVE_SHIELD_OVERRIDES[_KEYS[cid]]
            self.assertEqual(e.linear_terms, ((pct, "% maximum health"),), cid)
            self.assertFalse(e.level_scaled, cid)

    def test_volibear_hp_plus_ap(self) -> None:
        e = _PASSIVE_SHIELD_OVERRIDES[_KEYS["Volibear"]]
        self.assertEqual(
            e.linear_terms, ((14.0, "% maximum health"), (75.0, "% ap")),
        )

    def test_rakan_lerp_plus_ap(self) -> None:
        e = _PASSIVE_SHIELD_OVERRIDES[_KEYS["Rakan"]]
        self.assertEqual(e.linear_terms[0][0], _lerp_per_level(30.0, 225.0))
        self.assertEqual(e.linear_terms[0][1], "")
        self.assertEqual(e.linear_terms[1], (95.0, "% ap"))

    def test_shen_lerp_plus_bonus_hp(self) -> None:
        e = _PASSIVE_SHIELD_OVERRIDES[_KEYS["Shen"]]
        self.assertEqual(e.linear_terms[0][0], _lerp_per_level(47.0, 120.0))
        self.assertEqual(e.linear_terms[1], (13.0, "% bonus health"))

    def test_yasuo_flow_lerp(self) -> None:
        e = _PASSIVE_SHIELD_OVERRIDES[_KEYS["Yasuo"]]
        self.assertEqual(e.linear_terms, ((_lerp_per_level(125.0, 600.0), ""),))

    def test_blitz_mana_term(self) -> None:
        e = _PASSIVE_SHIELD_OVERRIDES[_KEYS["Blitzcrank"]]
        self.assertEqual(e.linear_terms, ((35.0, "% maximum mana"),))

    def test_viktor_level_scaled(self) -> None:
        e = _PASSIVE_SHIELD_OVERRIDES[_KEYS["Viktor"]]
        self.assertTrue(e.level_scaled)
        self.assertEqual(e.linear_terms[0][0], _lerp_per_level(40.0, 115.0))
        self.assertEqual(e.linear_terms[1], (18.0, "% ap"))


class SchemaFieldDefaultTests(unittest.TestCase):
    def test_defaults(self) -> None:
        e = PassiveShieldEntry(
            linear_terms=((5.0, ""),), cadence="per_cast", note="x",
        )
        self.assertEqual(e.attribute, "Passive Shield")
        self.assertEqual(e.bilinear_terms, ())
        self.assertFalse(e.level_scaled)


class ToShieldBlockTests(unittest.TestCase):
    def test_attribute_kind_is_shield(self) -> None:
        block = to_shield_block(_PASSIVE_SHIELD_OVERRIDES[_KEYS["Malphite"]])
        self.assertEqual(block.attribute_kind, "shield")
        self.assertEqual(block.attribute, "Granite Shield")
        self.assertEqual(
            block.raw_modifiers,
            ({"values": [10.0], "units": ["% maximum health"]},),
        )

    def test_level_scaled_propagates(self) -> None:
        block = to_shield_block(_PASSIVE_SHIELD_OVERRIDES[_KEYS["Viktor"]])
        self.assertTrue(block.level_scaled)
        # 18-element per-level values list for the flat term.
        self.assertEqual(len(block.raw_modifiers[0]["values"]), 18)

    def test_mana_unit_registered(self) -> None:
        # the additive unit must map to the existing ctx attr.
        self.assertEqual(_HEAL_UNIT_TO_CTX.get("% maximum mana"), "caster_max_mp")


class DefaultByteIdenticalTests(unittest.TestCase):
    """apply_passive_shield OFF (load_default): every seeded champ shields 0."""

    def test_default_all_zero(self) -> None:
        ab = load_default()
        for cid, (_c, key, _f) in _KEYS.items():
            sp, _ = _shield(cid, 11, ab, key)
            self.assertEqual(sp, 0.0, cid)


class FlagOnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ab = AbilitiesSnapshot.load(apply_passive_shield=True)

    def test_malphite_pct_max_hp(self) -> None:
        sp, _ = _shield("Malphite", 11, self.ab, "P")
        self.assertAlmostEqual(sp, 0.10 * _max_hp("Malphite", 11), places=4)

    def test_camille_pct_max_hp(self) -> None:
        sp, _ = _shield("Camille", 11, self.ab, "P")
        self.assertAlmostEqual(sp, 0.20 * _max_hp("Camille", 11), places=4)

    def test_vi_pct_max_hp(self) -> None:
        sp, _ = _shield("Vi", 11, self.ab, "P")
        self.assertAlmostEqual(sp, 0.12 * _max_hp("Vi", 11), places=4)

    def test_skarner_pct_max_hp(self) -> None:
        sp, sps = _shield("Skarner", 11, self.ab, "W")
        self.assertAlmostEqual(sp, 0.08 * _max_hp("Skarner", 11), places=4)
        # spell slot has a cooldown -> shield_per_sec computed (> 0).
        self.assertGreater(sps, 0.0)

    def test_blitzcrank_pct_max_mana(self) -> None:
        sp, _ = _shield("Blitzcrank", 11, self.ab, "P")
        self.assertAlmostEqual(sp, 0.35 * _max_mp("Blitzcrank", 11), places=4)
        self.assertGreater(sp, 0.0)

    def test_rakan_lerp_itemless(self) -> None:
        # P-slot, rank == level-1; itemless AP=0 -> lerp value only.
        sp, _ = _shield("Rakan", 11, self.ab, "P")
        self.assertAlmostEqual(sp, _lerp_per_level(30.0, 225.0)[10], places=4)

    def test_yasuo_lerp_itemless(self) -> None:
        sp, _ = _shield("Yasuo", 11, self.ab, "P")
        self.assertAlmostEqual(sp, _lerp_per_level(125.0, 600.0)[10], places=4)

    def test_viktor_level_scaled_itemless(self) -> None:
        # SPELL-slot level-scaled: L11 reads level-1=10, L18 reads 17 (115).
        l11, _ = _shield("Viktor", 11, self.ab, "Q")
        l18, _ = _shield("Viktor", 18, self.ab, "Q")
        self.assertAlmostEqual(l11, _lerp_per_level(40.0, 115.0)[10], places=4)
        self.assertAlmostEqual(l18, 115.0, places=4)
        self.assertGreater(l18, l11)

    def test_volibear_hp_plus_ap_scales(self) -> None:
        itemless, _ = _shield("Volibear", 11, self.ab, "E")
        self.assertAlmostEqual(itemless, 0.14 * _max_hp("Volibear", 11), places=3)
        # +AP raises the shield via the 75% AP term.
        ap_build, _ = _shield("Volibear", 11, self.ab, "E", items=["6655", "3157"])
        self.assertGreater(ap_build, itemless)

    def test_shen_bonus_hp_scales(self) -> None:
        itemless, _ = _shield("Shen", 11, self.ab, "P")
        # bonus-HP item raises the shield via the 13% bonus health term.
        hp_build, _ = _shield("Shen", 11, self.ab, "P", items=["3084"])
        self.assertGreater(hp_build, itemless)


class ExistingShieldBlockGateTests(unittest.TestCase):
    def test_snapshot_shielder_unchanged(self) -> None:
        # Janna E (Eye of the Storm) carries a real snapshot shield block; the
        # no-existing-shield-block gate skips injection -> flag ON == OFF.
        off = compute_ability_hps(
            _snap(), "Janna", 11, abilities=load_default(),
        ).total_shield_per_sec
        on = compute_ability_hps(
            _snap(), "Janna", 11,
            abilities=AbilitiesSnapshot.load(apply_passive_shield=True),
        ).total_shield_per_sec
        self.assertAlmostEqual(off, on, places=4)
        self.assertGreater(off, 0.0)


class DamageUnaffectedTests(unittest.TestCase):
    def test_viktor_q_damage_blocks_byte_identical(self) -> None:
        # adding a shield block must not touch the form's DAMAGE blocks (so the
        # damage scorer is unaffected even with apply_passive_shield on).
        off = load_default()
        on = AbilitiesSnapshot.load(apply_passive_shield=True)

        def _dmg(snap):
            form = snap.get_abilities("Viktor")["Q"][0]
            return [
                (b.attribute, b.attribute_kind, b.raw_modifiers)
                for b in form.damage_blocks
                if b.attribute_kind == "damage"
            ]

        self.assertEqual(_dmg(off), _dmg(on))
        self.assertGreater(len(_dmg(off)), 0)


class ExhaustTests(unittest.TestCase):
    def test_excluded_not_seeded(self) -> None:
        # spell shields / damage-stored barriers / re-grants are NOT seeded.
        for k in [
            ("Nocturne", "W", 0),   # spell shield
            ("Sivir", "E", 0),      # spell shield
            ("Sett", "W", 0),       # Grit-stored barrier
            ("Mordekaiser", "W", 0),  # stored-damage barrier
            ("TahmKench", "E", 0),  # grey health
            ("Galio", "R", 0),      # re-grants Galio W shield
        ]:
            self.assertNotIn(k, _PASSIVE_SHIELD_OVERRIDES, k)

    def test_no_p_slot_double_count_with_existing(self) -> None:
        # every seeded form has NO snapshot shield block (the gate's precondition).
        ab = AbilitiesSnapshot.load(apply_passive_shield=True)
        for cid, (c, key, fi) in _KEYS.items():
            forms = ab.get_abilities(c).get(key) or ()
            form = forms[fi]
            shields = [b for b in form.damage_blocks if b.attribute_kind == "shield"]
            # exactly ONE shield block (the injected synthetic) per seeded form.
            self.assertEqual(len(shields), 1, cid)


class EnginePinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.252.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self) -> None:
        import agents.daemon_slayer._passive_shield_overrides as m

        with open(m.__file__, encoding="utf-8") as fh:
            for line in fh:
                line.encode("ascii")

    def test_test_file_ascii(self) -> None:
        with open(__file__, encoding="utf-8") as fh:
            for line in fh:
                line.encode("ascii")


if __name__ == "__main__":
    unittest.main()
