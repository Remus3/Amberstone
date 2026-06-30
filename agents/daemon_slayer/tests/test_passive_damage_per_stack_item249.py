"""item 249 - per-stack passive damage schema lift tests.

The lift adds ``PerStackTerm`` + ``PassiveDamageEntry.per_stack`` /
``assumed_stacks``; ``to_damage_block`` folds ``field + per_stack.field *
assumed_stacks`` element-wise into the synthetic block. SEEDED: Kai'Sa P /
Darius P / Twitch P (new) + an Orianna P upgrade. All default-OFF
byte-identical (the seam injects only under apply_passive_damage=True).

Verbatim 16.11.1 effects_descriptions back each pinned value; the EXHAUSTED
scan (only 4 of 15 "per stack"+damage no_damage P-forms are per-stack TARGET
damage; the other 11 are stat steroids / stack-gain) is pinned by the
NotSeeded test.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    _select_blocks,
    rank_at_level,
)
from agents.daemon_slayer._passive_damage_overrides import (
    _PASSIVE_DAMAGE_OVERRIDES,
    PassiveDamageEntry,
    PerStackTerm,
    to_damage_block,
)

_PATCH = "16.11.1"
_PER_STACK_SEEDS = ("Kaisa", "Darius", "Twitch", "Orianna")
# no_damage P-forms with "per stack"+"damage" text that are NOT per-stack
# target damage (stat steroids / stack-gain / store mechanics) and are absent
# from the registry. Sona is EXCLUDED here - its per-stack Accelerando is a
# haste steroid, but Sona P IS seeded for its flat Power Chord (item 247), so
# (Sona, P, 0) is legitimately present.
_NOT_SEEDED = (
    "Belveth", "Garen", "Irelia", "Kayle", "Mel",
    "Samira", "Senna", "Volibear", "MonkeyKing", "Smolder",
)


def _full_hp_ctx(*, ap: float = 0.0, bonus_ad: float = 0.0) -> AbilityContext:
    base_ad = 60.0
    return AbilityContext.from_build(
        stats={"ad": base_ad + bonus_ad, "ap": ap, "hp": 1800.0},
        base_stats={"ad": base_ad, "hp": 1800.0},
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=2000.0,
        target_bonus_hp=0.0,
    )


class FoldMathTests(unittest.TestCase):
    """to_damage_block folds field + per_stack.field * assumed_stacks."""

    def test_fold_flat_base_and_ap(self) -> None:
        e = PassiveDamageEntry(
            base=(10.0,),
            ap_pct=5.0,
            per_stack=PerStackTerm(base=2.0, ap_pct=1.0),
            assumed_stacks=3.0,
            damage_type="MAGIC",
            cadence="on_hit",
            note="x",
        )
        b = to_damage_block(e)
        self.assertEqual(b.base, (16.0,))       # 10 + 2*3
        self.assertEqual(b.ap_pct, (8.0,))      # 5 + 1*3

    def test_fold_per_level_tuple_base(self) -> None:
        e = PassiveDamageEntry(
            base=(0.0,),
            per_stack=PerStackTerm(base=(1.0, 2.0)),
            assumed_stacks=4.0,
            damage_type="PHYSICAL",
            cadence="dot",
            note="x",
        )
        b = to_damage_block(e)
        self.assertEqual(b.base, (4.0, 8.0))    # (0+1*4, 0+2*4)

    def test_assumed_stacks_zero_is_inert(self) -> None:
        e = PassiveDamageEntry(
            base=(10.0,),
            per_stack=PerStackTerm(base=99.0, ap_pct=99.0),
            assumed_stacks=0.0,
            damage_type="MAGIC",
            cadence="on_hit",
            note="x",
        )
        b = to_damage_block(e)
        self.assertEqual(b.base, (10.0,))
        self.assertIsNone(b.ap_pct)             # per_stack ap never folded in

    def test_no_per_stack_is_unchanged(self) -> None:
        e = PassiveDamageEntry(
            base=(7.0,), ap_pct=3.0, damage_type="MAGIC",
            cadence="on_hit", note="x",
        )
        b = to_damage_block(e)
        self.assertEqual(b.base, (7.0,))
        self.assertEqual(b.ap_pct, (3.0,))


class RegistryShapeTests(unittest.TestCase):
    def test_four_per_stack_seeds_present_with_per_stack(self) -> None:
        for cid in _PER_STACK_SEEDS:
            e = _PASSIVE_DAMAGE_OVERRIDES[(cid, "P", 0)]
            self.assertIsInstance(e.per_stack, PerStackTerm, cid)
            self.assertGreater(e.assumed_stacks, 0.0, cid)

    def test_each_builds_a_damage_block(self) -> None:
        for cid in _PER_STACK_SEEDS:
            self.assertEqual(
                to_damage_block(_PASSIVE_DAMAGE_OVERRIDES[(cid, "P", 0)]).attribute_kind,
                "damage",
            )

    def test_steroid_forms_not_seeded(self) -> None:
        for cid in _NOT_SEEDED:
            self.assertNotIn((cid, "P", 0), _PASSIVE_DAMAGE_OVERRIDES, cid)


class ByteIdenticalDefaultTests(unittest.TestCase):
    """Flag OFF (default) -> the 3 NEW seeds stay no_damage / no synthetic block."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH)

    def test_new_seeds_stay_no_damage(self) -> None:
        for cid in ("Kaisa", "Darius", "Twitch"):
            form = self.snap.get_abilities(cid)["P"][0]
            self.assertEqual(form.parse_status, "no_damage", cid)
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(dmg, [], cid)


class InjectOnTests(unittest.TestCase):
    """Flag ON -> each seed gains 1 synthetic block; pin verbatim L11 values."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = AbilitiesSnapshot.load(_PATCH, apply_passive_damage=True)

    def _val(self, cid: str, ctx: AbilityContext, level: int = 11) -> float:
        form = self.snap.get_abilities(cid)["P"][0]
        return _select_blocks(form.damage_blocks, rank_at_level("P", level), ctx, "first")

    def test_each_seed_gains_one_block(self) -> None:
        for cid in _PER_STACK_SEEDS:
            form = self.snap.get_abilities(cid)["P"][0]
            dmg = [b for b in form.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(len(dmg), 1, cid)

    def test_kaisa_value(self) -> None:
        # base lerp(6,36)[10]=23.647059 (assumed 2: 4+1*2 .. 24+6*2) + 18% AP (12+3*2).
        # AP 200 -> 23.647059 + 36 = 59.647059
        self.assertAlmostEqual(self._val("Kaisa", _full_hp_ctx(ap=200.0)), 59.647, places=3)

    def test_darius_value(self) -> None:
        # base lerp(39,90)[10]=69.0 (assumed 3: 13*3 .. 30*3) + 90% bonus AD (30*3).
        # bonus_ad 100 -> 69 + 90 = 159.0
        self.assertAlmostEqual(self._val("Darius", _full_hp_ctx(bonus_ad=100.0)), 159.0, places=3)

    def test_twitch_value(self) -> None:
        # base step(18,36,54,72,90)[rank10]=72 (assumed 3: 6*3..30*3) + 54% AP (18*3).
        # AP 200 -> 72 + 108 = 180.0
        self.assertAlmostEqual(self._val("Twitch", _full_hp_ctx(ap=200.0)), 180.0, places=3)

    def test_orianna_upgrade_value(self) -> None:
        # UPGRADED: base lerp(12,60)[10]=40.235294 (10:50 + 2:10*1) + 18% AP (15+3*1).
        # AP 200 -> 40.235294 + 36 = 76.235294 (was 73.647 base-only pre-item-249)
        self.assertAlmostEqual(self._val("Orianna", _full_hp_ctx(ap=200.0)), 76.235, places=3)

    def test_damage_types(self) -> None:
        for cid, dt in (("Kaisa", "MAGIC"), ("Darius", "PHYSICAL"), ("Twitch", "TRUE")):
            self.assertEqual(_PASSIVE_DAMAGE_OVERRIDES[(cid, "P", 0)].damage_type, dt, cid)


class EnginePinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.155.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer._passive_damage_overrides as M
        src = open(M.__file__, encoding="utf-8").read()
        bad = [(i, c) for i, c in enumerate(src) if ord(c) > 127]
        self.assertEqual(bad, [], f"non-ASCII at {bad[:5]}")

    def test_test_file_is_ascii(self) -> None:
        src = open(__file__, encoding="utf-8").read()
        bad = [(i, c) for i, c in enumerate(src) if ord(c) > 127]
        self.assertEqual(bad, [], f"non-ASCII at {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
