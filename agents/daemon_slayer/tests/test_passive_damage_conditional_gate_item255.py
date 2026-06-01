"""GAP-2 CONDITIONAL-GATE passive damage schema lift (item 255).

The conditional-gate lift adds the class items 248/249 STAGED (Brand P ring
explosion + Ekko W sub-30% passive) plus 3 siblings the exhaustion scan
surfaced (Jhin P 4th shot, K'Sante P mark consume, Sejuani P frozen
detonation). Two new ``PassiveDamageEntry`` knobs:

  * ``target_missing_hp_pct`` - % of the target's MISSING health (the sibling
    of ``target_max_hp_pct``). It rides the EXISTING evaluator
    (``target_missing_hp_pct -> target_missing_hp`` is already in
    ``_SCALING_TARGETS``) so there is ZERO new evaluator math. It resolves to
    0 at the default full-HP ctx = byte-identical lower-bound (like the
    missing-HP HEAL seeds), surfacing only under a sub-threshold
    ``target_current_hp_pct``.
  * ``conditional_probability`` (default 1.0 = no-op for the 23 prior
    entries) - ``to_damage_block`` MULTIPLIES every coefficient (base + each
    scaling field + each bilinear factor) by it, so the injected block is the
    amortized expected magnitude. The documented operator-tunable firing
    midpoint for a gate NOT expressible via the target-HP ctx.

Pinned here (hand-computed against verbatim 16.11.1, NOT a circular
re-derive):
  * schema defaults on PassiveDamageEntry + PerStackTerm.
  * to_damage_block scales by conditional_probability; 1.0 is identity.
  * the 5 SEEDED entries evaluate to the hand-computed value at known
    (level, AP, max HP, current HP).
  * missing-HP seeds (Ekko / Jhin) are 0 at the default full-HP ctx.
  * default load (flag OFF) is BYTE-IDENTICAL: the 5 forms inject nothing.
  * the 23 prior entries keep conditional_probability == 1.0 (byte-identical).

Does NOT pin ENGINE_VERSION (owned by orchestrator).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_damage_overrides import (
    _PASSIVE_DAMAGE_OVERRIDES,
    PassiveDamageEntry,
    PerStackTerm,
    to_damage_block,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.ability_dps import (
    AbilityContext,
    _evaluate_block,
    rank_at_level,
)

_PATCH = "16.11.1"

# The 5 conditional-gate seeds added by item 255.
_SEEDS = (
    ("Brand", "P", 0),
    ("Ekko", "W", 0),
    ("Jhin", "P", 0),
    ("KSante", "P", 0),
    ("Sejuani", "P", 0),
)


def _ctx(*, ap: float = 0.0, current_hp_pct: float = 1.0,
         target_max_hp: float = 2500.0) -> AbilityContext:
    return AbilityContext.from_build(
        stats={"ad": 60.0, "ap": ap, "hp": 1800.0},
        base_stats={"ad": 60.0, "hp": 1800.0},
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=target_max_hp,
        target_bonus_hp=0.0,
        target_current_hp_pct=current_hp_pct,
    )


def _eval(cid: str, key: str, *, level: int = 11, **ctx_kw) -> float:
    entry = _PASSIVE_DAMAGE_OVERRIDES[(cid, key, 0)]
    block = to_damage_block(entry)
    rank = rank_at_level("P", level)  # passive: rank == level - 1
    return _evaluate_block(block, rank, _ctx(**ctx_kw))


class SchemaDefaultsTests(unittest.TestCase):
    def test_entry_new_fields_default(self) -> None:
        e = PassiveDamageEntry(base=(0.0,), damage_type="MAGIC", cadence="on_hit", note="x")
        self.assertEqual(e.conditional_probability, 1.0)
        self.assertEqual(e.target_missing_hp_pct, 0.0)

    def test_perstack_has_target_missing_hp_pct(self) -> None:
        ps = PerStackTerm()
        self.assertEqual(ps.target_missing_hp_pct, 0.0)


class ConditionalProbabilityFoldTests(unittest.TestCase):
    def test_default_one_is_identity(self) -> None:
        e = PassiveDamageEntry(
            base=(100.0,), ap_pct=50.0,
            bilinear_terms=((0.0002, "ap", "target_max_hp"),),
            damage_type="MAGIC", cadence="on_hit", note="x",
        )
        b = to_damage_block(e)
        self.assertEqual(b.value_at("base", 0), 100.0)
        self.assertEqual(b.value_at("ap_pct", 0), 50.0)
        self.assertEqual(b.bilinear_terms, ((0.0002, "ap", "target_max_hp"),))

    def test_half_scales_every_coefficient(self) -> None:
        e = PassiveDamageEntry(
            base=(100.0,), ap_pct=50.0, target_max_hp_pct=10.0,
            bilinear_terms=((0.0002, "ap", "target_max_hp"),),
            damage_type="MAGIC", cadence="on_hit", note="x",
            conditional_probability=0.5,
        )
        b = to_damage_block(e)
        self.assertEqual(b.value_at("base", 0), 50.0)
        self.assertEqual(b.value_at("ap_pct", 0), 25.0)
        self.assertEqual(b.value_at("target_max_hp_pct", 0), 5.0)
        self.assertEqual(b.bilinear_terms[0][0], 0.0001)

    def test_missing_hp_pct_flows_into_block(self) -> None:
        e = PassiveDamageEntry(
            base=(0.0,), target_missing_hp_pct=3.0,
            damage_type="MAGIC", cadence="on_hit", note="x",
        )
        b = to_damage_block(e)
        self.assertEqual(b.value_at("target_missing_hp_pct", 0), 3.0)


class SeededMagnitudeTests(unittest.TestCase):
    def test_brand_p_max_hp_no_ap_full(self) -> None:
        # 0.5 * lerp(8,12)@L11 * 2500 = 0.5 * (8 + 4*10/17)% * 2500 = 129.41
        self.assertAlmostEqual(_eval("Brand", "P"), 129.412, places=2)

    def test_brand_p_with_ap(self) -> None:
        # + bilinear 0.0002 * 656 * 2500 * 0.5 = 164.0 -> 293.41
        self.assertAlmostEqual(_eval("Brand", "P", ap=656.0), 293.412, places=2)

    def test_ekko_w_zero_at_full_hp(self) -> None:
        self.assertEqual(_eval("Ekko", "W", ap=656.0), 0.0)

    def test_ekko_w_resolves_low_hp(self) -> None:
        # missing = 1875; (0.03 + 0.0003*656) * 1875 = 425.25
        self.assertAlmostEqual(_eval("Ekko", "W", ap=656.0, current_hp_pct=0.25),
                               425.25, places=2)

    def test_jhin_p_zero_at_full_hp(self) -> None:
        self.assertEqual(_eval("Jhin", "P"), 0.0)

    def test_jhin_p_exact_quarter_gate(self) -> None:
        # 0.25 * 20%(L11 step) * 1875 missing = 93.75 EXACT (no AP term)
        self.assertAlmostEqual(_eval("Jhin", "P", current_hp_pct=0.25), 93.75, places=4)

    def test_ksante_p_flat_plus_max_hp(self) -> None:
        # 12 + lerp(1,2)@L11 * 2500 = 12 + (1 + 10/17)% * 2500 = 51.71
        self.assertAlmostEqual(_eval("KSante", "P"), 51.706, places=2)

    def test_sejuani_p_gated_max_hp(self) -> None:
        # 0.5 * 10% * 2500 = 125.0 EXACT
        self.assertAlmostEqual(_eval("Sejuani", "P"), 125.0, places=4)


class ByteIdenticalDefaultTests(unittest.TestCase):
    """Flag OFF: the 5 conditional forms inject NOTHING (default-OFF)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.off = AbilitiesSnapshot.load(patch=_PATCH)
        cls.on = AbilitiesSnapshot.load(patch=_PATCH, apply_passive_damage=True)

    def _form(self, snap, cid, key):
        ab = snap.get_ability(cid, key)
        return ab if ab is None else (ab[0] if isinstance(ab, list) else ab)

    def test_off_no_injection_on_seeds(self) -> None:
        for cid, key, _fi in _SEEDS:
            f = self._form(self.off, cid, key)
            self.assertIsNotNone(f, f"{cid} {key} form missing")
            dmg = [b for b in f.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(dmg, [], f"{cid} {key} injected a block with flag OFF")

    def test_on_injects_each_seed(self) -> None:
        for cid, key, _fi in _SEEDS:
            f = self._form(self.on, cid, key)
            dmg = [b for b in f.damage_blocks if b.attribute_kind == "damage"]
            self.assertEqual(len(dmg), 1, f"{cid} {key} expected 1 injected block ON")


class PriorEntriesByteIdenticalTests(unittest.TestCase):
    def test_prior_entries_keep_probability_one(self) -> None:
        for keytuple, entry in _PASSIVE_DAMAGE_OVERRIDES.items():
            if keytuple in _SEEDS:
                continue
            self.assertEqual(
                entry.conditional_probability, 1.0,
                f"{keytuple} prior entry must keep conditional_probability 1.0",
            )

    def test_only_missing_hp_seeds_use_missing_field(self) -> None:
        users = {
            k for k, e in _PASSIVE_DAMAGE_OVERRIDES.items()
            if (e.target_missing_hp_pct if not isinstance(e.target_missing_hp_pct, (tuple, list))
                else any(e.target_missing_hp_pct))
        }
        self.assertEqual(users, {("Ekko", "W", 0), ("Jhin", "P", 0)})


class RegistryGrowthTests(unittest.TestCase):
    def test_all_five_seeds_present(self) -> None:
        for k in _SEEDS:
            self.assertIn(k, _PASSIVE_DAMAGE_OVERRIDES)

    def test_kaisa_fifth_stack_not_seeded_separately(self) -> None:
        # Kai'Sa P stays the unconditional Caustic Wounds per-stack entry;
        # the 5th-stack missing-HP consume is a documented reject (mixed entry).
        e = _PASSIVE_DAMAGE_OVERRIDES[("Kaisa", "P", 0)]
        self.assertEqual(e.conditional_probability, 1.0)
        miss = e.target_missing_hp_pct
        self.assertEqual(miss if not isinstance(miss, (tuple, list)) else max(miss), 0.0)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self) -> None:
        import agents.daemon_slayer._passive_damage_overrides as m
        from pathlib import Path
        for p in (Path(m.__file__), Path(__file__)):
            data = p.read_bytes()
            self.assertEqual([b for b in data if b > 0x7F], [], f"non-ASCII in {p.name}")


if __name__ == "__main__":
    unittest.main()
