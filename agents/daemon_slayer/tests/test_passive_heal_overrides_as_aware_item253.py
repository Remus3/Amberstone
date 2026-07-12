"""item 253 - AS-aware effects-text HEAL seam (the LAST named clean headless lift).

The bilinear HEAL registry (items 250-252) could not express a heal scaling on
bonus ATTACK SPEED (the heal block carried no AS stat). This slice feeds a
``bonus_as`` entry into ``ability_hps``'s ``bilinear_ctx`` = bonus attack speed
in PERCENTAGE POINTS (total AS minus the champion's INNATE base AS over the
innate base - the "% per 100% bonus AS" convention, crediting both the per-level
AND item AS bonus). Viego P's deliberately-omitted "+5% per 100% bonus attack
speed of the target's maximum health" sub-term is the sole consumer, now a plain
``_per_100(5.0, "bonus_as", "target_max_hp")`` bilinear product (zero new eval
math).

DEFAULT (apply_passive_heal=False / load_default) stays byte-identical. With the
flag ON the Viego term still gates on its ``target_max_hp`` half, so a build with
no AS bonus AND the default ``resolve_target_relative=False`` are both
byte-identical (the bilinear product is 0). The AS term only surfaces under
``resolve_target_relative=True`` + a ``target_max_hp``.

EXHAUSTED: the all-171-champ scan for a heal OR shield magnitude scaling on the
caster's own bonus attack speed found Viego P and nothing else.

Verbatim 16.11.1 effects_descriptions back the pinned value.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer._passive_damage_overrides import _per_100
from agents.daemon_slayer._passive_heal_overrides import (
    _PASSIVE_HEAL_OVERRIDES,
    to_heal_block,
)
from agents.daemon_slayer.abilities import AbilitiesSnapshot, load_default
from agents.daemon_slayer.ability_hps import compute_ability_hps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import build_champion

_PATCH = "16.11.1"
_VIEGO_KEY = ("Viego", "P", 0)
_AS_TERM = (0.0005, "bonus_as", "target_max_hp")  # _per_100(5.0, ...)


def _snap() -> DataSnapshot:
    return DataSnapshot.load()


def _viego_p_heal(level, *, ab, rtr=False, tmax=0.0, items=None) -> float:
    r = compute_ability_hps(
        _snap(), "Viego", level, item_ids=items, mode="SR", abilities=ab,
        resolve_target_relative=rtr, target_max_hp=tmax,
    )
    p = [s for s in r.spells if s.key == "P"]
    return p[0].heal_per_cast if p else 0.0


def _bonus_as_pct(level, items=None) -> float:
    snap = _snap()
    r = build_champion(snap, "Viego", level, item_ids=items, mode="SR")
    base = float(snap.champion("Viego")["stats"]["attackspeed"])
    return (float(r.stats["as"]) - base) / base * 100.0


class RegistryShapeTests(unittest.TestCase):
    def test_viego_p_present(self) -> None:
        self.assertIn(_VIEGO_KEY, _PASSIVE_HEAL_OVERRIDES)

    def test_viego_p_has_four_terms(self) -> None:
        e = _PASSIVE_HEAL_OVERRIDES[_VIEGO_KEY]
        # 1 linear (flat 2% target max HP) + 3 bilinear (bonus AD / AP / AS).
        self.assertEqual(e.linear_terms, ((2.0, "% of target's maximum health"),))
        self.assertEqual(len(e.bilinear_terms), 3)

    def test_viego_p_as_term_exact(self) -> None:
        e = _PASSIVE_HEAL_OVERRIDES[_VIEGO_KEY]
        # the AS term is _per_100(5.0, "bonus_as", "target_max_hp").
        self.assertEqual(_per_100(5.0, "bonus_as", "target_max_hp"), _AS_TERM)
        self.assertIn(_AS_TERM, e.bilinear_terms)

    def test_viego_p_other_two_bilinear_unchanged(self) -> None:
        e = _PASSIVE_HEAL_OVERRIDES[_VIEGO_KEY]
        self.assertIn(_per_100(2.5, "bonus_ad", "target_max_hp"), e.bilinear_terms)
        self.assertIn(_per_100(2.0, "ap", "target_max_hp"), e.bilinear_terms)

    def test_viego_is_only_bonus_as_consumer(self) -> None:
        # item 253 exhaust: Viego P is the sole heal entry with a bonus_as term.
        with_as = [
            k
            for k, e in _PASSIVE_HEAL_OVERRIDES.items()
            if any(b[1] == "bonus_as" or b[2] == "bonus_as" for b in e.bilinear_terms)
        ]
        self.assertEqual(with_as, [_VIEGO_KEY])


class BlockBuildTests(unittest.TestCase):
    def test_block_carries_three_bilinear_terms(self) -> None:
        block = to_heal_block(_PASSIVE_HEAL_OVERRIDES[_VIEGO_KEY])
        self.assertEqual(block.attribute_kind, "heal")
        self.assertEqual(len(block.bilinear_terms), 3)
        self.assertIn(_AS_TERM, block.bilinear_terms)


class DefaultByteIdenticalTests(unittest.TestCase):
    def test_flag_off_viego_heal_zero(self) -> None:
        # apply_passive_heal OFF: no synthetic block injected, even with resolve.
        ab = load_default()
        self.assertEqual(_viego_p_heal(11, ab=ab, rtr=True, tmax=2500.0), 0.0)

    def test_flag_on_resolve_off_zero(self) -> None:
        # flag ON but resolve OFF: every Viego term gates on target_max_hp (0).
        ab = AbilitiesSnapshot.load(apply_passive_heal=True)
        self.assertEqual(_viego_p_heal(11, ab=ab, rtr=False, tmax=2500.0), 0.0)


class AsTermResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ab_on = AbilitiesSnapshot.load(apply_passive_heal=True)

    def test_itemless_heal_is_flat_plus_as_term(self) -> None:
        # L11 itemless: AP=0, bonus AD=0, so heal = flat 2% + AS term only.
        tmax = 2500.0
        heal = _viego_p_heal(11, ab=self.ab_on, rtr=True, tmax=tmax)
        bas = _bonus_as_pct(11)
        expected = 0.02 * tmax + 0.0005 * bas * tmax
        self.assertAlmostEqual(heal, expected, places=4)

    def test_as_term_uses_percentage_points(self) -> None:
        # at 100% bonus AS the AS term must equal 5% of target max HP. Solve for
        # the AS-only contribution = total - flat 2%.
        tmax = 2000.0
        heal = _viego_p_heal(11, ab=self.ab_on, rtr=True, tmax=tmax)
        bas = _bonus_as_pct(11)  # percentage points
        as_contrib = heal - 0.02 * tmax
        # as_contrib / (bas/100) == 5% of tmax (the per-100%-bonus-AS rate).
        per_100pct = as_contrib / (bas / 100.0)
        self.assertAlmostEqual(per_100pct, 0.05 * tmax, places=4)

    def test_more_attack_speed_raises_heal(self) -> None:
        # Berserker's Greaves (3006) + Guinsoo's (3091) add bonus AS -> larger AS
        # term -> larger heal.
        tmax = 2500.0
        itemless = _viego_p_heal(11, ab=self.ab_on, rtr=True, tmax=tmax)
        as_build = _viego_p_heal(
            11, ab=self.ab_on, rtr=True, tmax=tmax, items=["3006", "3091"],
        )
        self.assertGreater(as_build, itemless)
        self.assertGreater(_bonus_as_pct(11, ["3006", "3091"]), _bonus_as_pct(11))

    def test_per_level_growth_credited(self) -> None:
        # innate-base denominator: per-level AS growth IS bonus AS, so an itemless
        # Viego at a higher level has more bonus_as -> a larger AS term.
        tmax = 2500.0
        l3 = _viego_p_heal(3, ab=self.ab_on, rtr=True, tmax=tmax)
        l18 = _viego_p_heal(18, ab=self.ab_on, rtr=True, tmax=tmax)
        self.assertGreater(_bonus_as_pct(18), _bonus_as_pct(3))
        # both share the same flat 2% base; the AS term grows with level.
        self.assertGreater(l18, l3)


class ExistingHealBlockGateTests(unittest.TestCase):
    def test_soraka_unchanged_flag_on(self) -> None:
        # the bonus_as bilinear_ctx key is a no-op for snapshot heal blocks
        # (they carry no bilinear_terms); Soraka has real heal blocks so the
        # gate skips injection -> flag ON == OFF.
        off = compute_ability_hps(
            _snap(), "Soraka", 11, abilities=load_default(),
        ).total_heal_per_sec
        on = compute_ability_hps(
            _snap(), "Soraka", 11,
            abilities=AbilitiesSnapshot.load(apply_passive_heal=True),
        ).total_heal_per_sec
        self.assertAlmostEqual(off, on, places=6)


class EnginePinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.204.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_ascii(self) -> None:
        import agents.daemon_slayer._passive_heal_overrides as m

        src = open(m.__file__, encoding="utf-8").read()
        self.assertTrue(src.isascii())

    def test_self_ascii(self) -> None:
        src = open(__file__, encoding="utf-8").read()
        self.assertTrue(src.isascii())


if __name__ == "__main__":
    unittest.main()
