"""item 250 - effects-text-only HEAL registry (bilinear AP/AD-on-HP) tests.

The lift adds ``_passive_heal_overrides`` (PassiveHealEntry + to_heal_block),
the ``apply_passive_heal`` load flag + ``_apply_passive_heal_overrides`` seam in
abilities.py, and the ``bilinear_ctx`` evaluation path in
``ability_hps._eval_heal_shield_block``. SEEDED: Viego P / Karma W f1 / Kayn R -
effects-text-only bilinear self-heals (no snapshot heal block).

All default-OFF byte-identical: the seam injects only under
apply_passive_heal=True, and every seeded heal scales on a target / caster-
MISSING HP quantity so it resolves to 0 unless the caller also opts into
resolve_target_relative + an HP assumption.

Verbatim 16.11.1 effects_descriptions back each pinned value.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    DamageBlock,
    _apply_passive_heal_overrides,
    load_default,
)
from agents.daemon_slayer.ability_hps import (
    _eval_heal_shield_block,
    compute_ability_hps,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer._passive_heal_overrides import (
    _PASSIVE_HEAL_OVERRIDES,
    PassiveHealEntry,
    to_heal_block,
)
from agents.daemon_slayer._passive_damage_overrides import _per_100

_PATCH = "16.11.1"
_SEEDS = (("Viego", "P", 0), ("Karma", "W", 1), ("Kayn", "R", 0))


def _snap() -> DataSnapshot:
    return DataSnapshot.load()


class RegistryShapeTests(unittest.TestCase):
    def test_three_bilinear_seeds_present(self) -> None:
        # item 251 added the LINEAR seeds; the 3 item-250 bilinear seeds stay.
        self.assertTrue(set(_SEEDS).issubset(_PASSIVE_HEAL_OVERRIDES.keys()))

    def test_entries_are_passive_heal_entries(self) -> None:
        for key in _SEEDS:
            e = _PASSIVE_HEAL_OVERRIDES[key]
            self.assertIsInstance(e, PassiveHealEntry, key)
            self.assertTrue(e.linear_terms, key)
            self.assertTrue(e.bilinear_terms, key)
            self.assertIn(e.cadence, ("per_cast", "per_fight"), key)

    def test_documented_exclusions_absent(self) -> None:
        # Vladimir Q has a snapshot heal block (the no-existing-heal-block gate
        # skips it). Fiora P is NOW seeded by item 251 (flat linear heal).
        self.assertNotIn(("Vladimir", "Q", 0), _PASSIVE_HEAL_OVERRIDES)


class ToHealBlockTests(unittest.TestCase):
    def test_builds_heal_block_with_raw_and_bilinear(self) -> None:
        e = _PASSIVE_HEAL_OVERRIDES[("Viego", "P", 0)]
        b = to_heal_block(e)
        self.assertIsInstance(b, DamageBlock)
        self.assertEqual(b.attribute_kind, "heal")
        self.assertEqual(b.attribute, "Sovereign's Domination")
        # one linear term -> one raw_modifier
        self.assertEqual(len(b.raw_modifiers), 1)
        self.assertEqual(b.raw_modifiers[0]["values"], [2.0])
        self.assertEqual(
            b.raw_modifiers[0]["units"], ["% of target's maximum health"],
        )
        # bilinear terms (bonus AD + AP + the item-253 bonus AS), all *
        # target_max_hp. Was 2 pre-item-253; the AS-aware seam added the 3rd.
        self.assertEqual(len(b.bilinear_terms), 3)
        for (_factor, a, b_attr) in b.bilinear_terms:
            self.assertEqual(b_attr, "target_max_hp")
            self.assertIn(a, ("bonus_ad", "ap", "bonus_as"))

    def test_per_100_factors_match_helper(self) -> None:
        e = _PASSIVE_HEAL_OVERRIDES[("Viego", "P", 0)]
        self.assertIn(_per_100(2.5, "bonus_ad", "target_max_hp"), e.bilinear_terms)
        self.assertIn(_per_100(2.0, "ap", "target_max_hp"), e.bilinear_terms)

    def test_per_rank_linear_value_round_trips(self) -> None:
        e = PassiveHealEntry(
            linear_terms=(((1.0, 2.0, 3.0), "% missing health"),),
            cadence="per_cast",
            note="x",
        )
        b = to_heal_block(e)
        self.assertEqual(b.raw_modifiers[0]["values"], [1.0, 2.0, 3.0])


class EvalBilinearTests(unittest.TestCase):
    """_eval_heal_shield_block sums linear (raw_modifiers) + bilinear products."""

    def _ctx(self) -> SimpleNamespace:
        return SimpleNamespace()  # _HEAL_UNIT_TO_CTX units absent -> ctx unused

    def test_viego_exact(self) -> None:
        # 2% of 2500 + 2.5%/100 bonus AD (80) * 2500 + 2%/100 AP (200) * 2500
        # = 50 + 50 + 100 = 200
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Viego", "P", 0)])
        extra = {"% of target's maximum health": 2500.0}
        bil = {"bonus_ad": 80.0, "ap": 200.0, "target_max_hp": 2500.0}
        amt, unres = _eval_heal_shield_block(b, 0, self._ctx(), extra, bil)
        self.assertAlmostEqual(amt, 200.0, places=6)
        self.assertFalse(unres)

    def test_kayn_exact(self) -> None:
        # 11.25% of 2500 + 7.5%/100 bonus AD (80) * 2500 = 281.25 + 150 = 431.25
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Kayn", "R", 0)])
        extra = {"% of target's maximum health": 2500.0}
        bil = {"bonus_ad": 80.0, "target_max_hp": 2500.0}
        amt, unres = _eval_heal_shield_block(b, 0, self._ctx(), extra, bil)
        self.assertAlmostEqual(amt, 431.25, places=6)
        self.assertFalse(unres)

    def test_karma_exact_missing_hp(self) -> None:
        # 17% of missing (900) + 1%/100 AP (200) * 900 = 153 + 18 = 171
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Karma", "W", 1)])
        extra = {"% missing health": 900.0}
        bil = {"ap": 200.0, "caster_missing_hp": 900.0}
        amt, unres = _eval_heal_shield_block(b, 0, self._ctx(), extra, bil)
        self.assertAlmostEqual(amt, 171.0, places=6)
        self.assertFalse(unres)

    def test_no_extra_units_is_lower_bound_unresolved(self) -> None:
        # without extra_units the linear %-of-HP unit is unresolved; the
        # bilinear term with a 0 HP factor contributes 0 -> total 0, unresolved
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Viego", "P", 0)])
        bil = {"bonus_ad": 80.0, "ap": 200.0, "target_max_hp": 0.0}
        amt, unres = _eval_heal_shield_block(b, 0, self._ctx(), None, bil)
        self.assertEqual(amt, 0.0)
        self.assertTrue(unres)

    def test_bilinear_ctx_none_is_noop(self) -> None:
        # a None bilinear_ctx leaves the bilinear terms unevaluated (the v1/v2
        # call shape) - only the linear term resolves
        b = to_heal_block(_PASSIVE_HEAL_OVERRIDES[("Viego", "P", 0)])
        extra = {"% of target's maximum health": 2500.0}
        amt, unres = _eval_heal_shield_block(b, 0, self._ctx(), extra, None)
        self.assertAlmostEqual(amt, 50.0, places=6)  # flat 2% only
        self.assertFalse(unres)


class LoadSeamGateTests(unittest.TestCase):
    def _form(self, blocks):
        return SimpleNamespace(
            form_index=0,
            damage_blocks=tuple(blocks),
        )

    def test_injects_when_no_heal_block(self) -> None:
        # use the real load() seam path via _apply_passive_heal_overrides
        from agents.daemon_slayer.abilities import AbilityForm

        f = AbilityForm(
            key="P", name="Sovereign's Domination", form_index=0, icon=None,
            cooldown=None, cost=None, damage_type=None, targeting=None,
            affects=None, resource=None, is_aoe=False, damage_blocks=(),
            raw_effects_count=0, raw_leveling_count=0, parse_status="no_damage",
            parse_notes=(),
        )
        out = _apply_passive_heal_overrides("Viego", "P", f)
        heal_blocks = [b for b in out.damage_blocks if b.attribute_kind == "heal"]
        self.assertEqual(len(heal_blocks), 1)
        self.assertEqual(heal_blocks[0].attribute, "Sovereign's Domination")

    def test_skips_when_existing_heal_block(self) -> None:
        from agents.daemon_slayer.abilities import AbilityForm

        existing = DamageBlock(attribute="Base Heal", attribute_kind="heal")
        f = AbilityForm(
            key="P", name="Sovereign's Domination", form_index=0, icon=None,
            cooldown=None, cost=None, damage_type=None, targeting=None,
            affects=None, resource=None, is_aoe=False,
            damage_blocks=(existing,),
            raw_effects_count=0, raw_leveling_count=0, parse_status="no_damage",
            parse_notes=(),
        )
        out = _apply_passive_heal_overrides("Viego", "P", f)
        self.assertEqual(out, f)  # unchanged - no double-count

    def test_skips_unregistered(self) -> None:
        from agents.daemon_slayer.abilities import AbilityForm

        f = AbilityForm(
            key="Q", name="Whatever", form_index=0, icon=None, cooldown=None,
            cost=None, damage_type=None, targeting=None, affects=None,
            resource=None, is_aoe=False, damage_blocks=(),
            raw_effects_count=0, raw_leveling_count=0, parse_status="ok",
            parse_notes=(),
        )
        self.assertEqual(_apply_passive_heal_overrides("Caitlyn", "Q", f), f)


class DefaultByteIdenticalTests(unittest.TestCase):
    """Flag OFF and flag-ON/resolve-OFF are byte-identical to the v2 default."""

    def test_flag_off_vs_flag_on_resolve_off(self) -> None:
        snap = _snap()
        ab_off = load_default()
        ab_on = AbilitiesSnapshot.load(apply_passive_heal=True)
        for cid in ("Viego", "Karma", "Kayn", "Caitlyn", "Soraka"):
            r0 = compute_ability_hps(snap, cid, 13, abilities=ab_off)
            r1 = compute_ability_hps(snap, cid, 13, abilities=ab_on)
            self.assertEqual(
                r0.total_ability_hps, r1.total_ability_hps,
                f"{cid}: flag-on resolve-off must match flag-off",
            )

    def test_resolve_off_seeds_contribute_zero(self) -> None:
        # even with the flag on, resolve_target_relative=False keeps the seeded
        # target/missing-HP heals at 0 (the lower-bound contract)
        snap = _snap()
        ab_on = AbilitiesSnapshot.load(apply_passive_heal=True)
        r = compute_ability_hps(snap, "Viego", 13, abilities=ab_on)
        self.assertEqual(r.total_ability_hps, 0.0)


class InjectionEndToEndTests(unittest.TestCase):
    """With the flag + resolve on + an HP assumption, the seeded heals surface."""

    def setUp(self) -> None:
        self.snap = _snap()
        self.ab_on = AbilitiesSnapshot.load(apply_passive_heal=True)

    def test_viego_p_per_cast_flat_plus_as_itemless(self) -> None:
        # itemless L13: AP=0, bonus_ad=0 -> heal = flat 2% of 2500 (=50) + the
        # item-253 AS term (5% per 100% bonus AS, here per-level growth only).
        from agents.daemon_slayer.engine import build_champion

        rc = build_champion(self.snap, "Viego", 13, item_ids=[], mode="SR")
        base_as = float(self.snap.champion("Viego")["stats"]["attackspeed"])
        bonus_as_pct = (float(rc.stats["as"]) - base_as) / base_as * 100.0
        expected = 0.02 * 2500.0 + 0.0005 * bonus_as_pct * 2500.0
        r = compute_ability_hps(
            self.snap, "Viego", 13, abilities=self.ab_on,
            resolve_target_relative=True, target_max_hp=2500.0,
        )
        p = [s for s in r.spells if s.key == "P"]
        self.assertTrue(p)
        self.assertGreater(p[0].heal_per_cast, 50.0)  # AS term adds to the flat 50
        self.assertAlmostEqual(p[0].heal_per_cast, expected, places=3)

    def test_kayn_r_per_cast_flat_only_itemless(self) -> None:
        r = compute_ability_hps(
            self.snap, "Kayn", 13, abilities=self.ab_on,
            resolve_target_relative=True, target_max_hp=2500.0,
        )
        rr = [s for s in r.spells if s.key == "R"]
        self.assertTrue(rr)
        # 11.25% of 2500 = 281.25 (itemless bonus AD term ~0)
        self.assertAlmostEqual(rr[0].heal_per_cast, 281.25, places=2)

    def test_karma_w_form1_missing_hp_resolves(self) -> None:
        r = compute_ability_hps(
            self.snap, "Karma", 13, abilities=self.ab_on,
            resolve_target_relative=True, target_max_hp=2500.0,
            caster_missing_hp_pct=0.5, form_index_overrides={"W": 1},
        )
        w = [s for s in r.spells if s.key == "W"]
        self.assertTrue(w)
        self.assertEqual(w[0].form_index, 1)
        # 17% of (caster_max_hp * 0.5); positive lower bound + a per-sec rate
        self.assertGreater(w[0].heal_per_cast, 100.0)
        self.assertGreater(w[0].heal_per_sec, 0.0)

    def test_viego_ap_increases_per_cast(self) -> None:
        # adding AP raises the 2%/100 AP bilinear term -> larger heal_per_cast
        base = compute_ability_hps(
            self.snap, "Viego", 13, abilities=self.ab_on,
            resolve_target_relative=True, target_max_hp=2500.0,
        )
        ap = compute_ability_hps(
            self.snap, "Viego", 13, item_ids=["3089"], abilities=self.ab_on,
            resolve_target_relative=True, target_max_hp=2500.0,
        )
        bp = [s for s in base.spells if s.key == "P"][0].heal_per_cast
        ap_p = [s for s in ap.spells if s.key == "P"][0].heal_per_cast
        self.assertGreater(ap_p, bp)


class EnginePinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.233.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer._passive_heal_overrides as M

        src = open(M.__file__, encoding="utf-8").read()
        bad = [(i, c) for i, c in enumerate(src) if ord(c) > 127]
        self.assertEqual(bad, [], f"non-ASCII at {bad[:5]}")

    def test_test_file_is_ascii(self) -> None:
        src = open(__file__, encoding="utf-8").read()
        bad = [(i, c) for i, c in enumerate(src) if ord(c) > 127]
        self.assertEqual(bad, [], f"non-ASCII at {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
