"""A-12 / RM-46: the per-champion CRIT CONVERSION seam (Ashe Frost Shot).

GROUND TRUTH (``data/daemon_slayer/16.14.1/champion_abilities.json``, Ashe P
"Frost Shot", verbatim):

    "Innate: Ashe's basic attacks deal bonus physical damage equal to
     (75% + 40%) critical strike chance. Critical strikes do not deal any
     additional damage."
    notes: "Runaan's Hurricane's will not deal additional damage on critical
     strikes."

The engine models every champion's auto attack as ``ad * (1 + crit *
crit_bonus)`` with ``crit_bonus = DEFAULT_CRIT_BONUS (0.75) +
total_crit_damage_bonus(items)`` (``dps.py``). For Ashe both halves are wrong:

  1. her conversion factor is 0.75 + 0.40 = 1.15, not 0.75, so at c=1.00 the
     engine returns 1.75x AD where the correct value is 2.15x - a 22.9 pct
     UNDER-valuation of her crit (2.15 / 1.75 = 1.2286);
  2. "Critical strikes do not deal any additional damage" means an item
     crit-damage bonus (Infinity Edge +0.30) is INERT on her, so the
     conversion factor REPLACES the item sum rather than adding to it.

Consequence, and the point of the row: modelling Frost Shot RAISES Ashe's crit
items across the board (1.15 > 0.75); what it CORRECTLY does is demote Infinity
Edge RELATIVE to pure crit-chance items, because IE's crit-damage half stops
paying her.

Third term: the Runaan's Hurricane crit deny. The Hurricane bolts must never be
credited the conversion. This module pins that as a live invariant.

DEFAULT-OFF: ``compute_dps(apply_crit_conversion=False)`` (the default) is
byte-identical for EVERY champion including Ashe - pinned below against goldens
captured from the pre-seam engine at HEAD c9296b34.

OFFLINE ONLY: no live :8860, no network.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import rank as rank_mod
from agents.daemon_slayer._crit_conversion_overrides import (
    _ASHE_FROST_SHOT_FACTOR,
    _CRIT_CONVERSION,
    CritConversionEntry,
    crit_conversion_entry,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import DEFAULT_CRIT_BONUS, compute_dps

ASHE = "Ashe"
APHELIOS = "Aphelios"          # negative control: no registry entry
INFINITY_EDGE = "3031"
PHANTOM_DANCER = "3046"
RUNAANS = "3085"
RUNAANS_ARENA = "223085"
ESSENCE_REAVER = "3508"        # its proc DOES read CallContext.crit_chance
BERSERKERS = "3006"

# PART 7 gate params (docs/OPEN_ITEMS_REVIEW_2026-07-25.md:473-482). This build
# reproduces the filed gate line byte-for-byte on the shipped engine:
# Ashe BotRK #1 / Runaan's #2 / IE #8 vs Aphelios Yun Tal #1 / IE #2 / BotRK #13.
GATE_BUILD = [BERSERKERS]
GATE_TARGET = dict(
    target_armor=110.0,
    target_mr=52.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)
GATE_LEVEL = 16

# Goldens captured in-process from the pre-seam engine (HEAD c9296b34) at the
# gate params. These pin the DEFAULT-OFF byte-identity contract - they must not
# move when the seam is omitted.
GOLDEN_WEIGHTED_DPS = {
    (ASHE, (BERSERKERS,)): 46.23721226731604,
    (ASHE, (BERSERKERS, INFINITY_EDGE)): 101.42297828433249,
    (ASHE, (BERSERKERS, PHANTOM_DANCER)): 69.76064417326164,
    (ASHE, (BERSERKERS, RUNAANS)): 123.37587370353087,
    (APHELIOS, (BERSERKERS,)): 91.88821206250002,
    (APHELIOS, (BERSERKERS, INFINITY_EDGE)): 214.55251616640632,
    (APHELIOS, (BERSERKERS, PHANTOM_DANCER)): 154.43751616015624,
    (APHELIOS, (BERSERKERS, RUNAANS)): 137.00664526171875,
}

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _dps(champion: str, build, **kwargs):
    return compute_dps(
        _snap(),
        champion_id=champion,
        level=GATE_LEVEL,
        item_ids=list(build),
        mode="SR",
        **GATE_TARGET,
        **kwargs,
    )


def _implied_crit_bonus(result) -> float:
    """Recover crit_bonus from the per-hit display fields.

    ``raw_attack_dps = ad * as * (1 + crit * crit_bonus) * aa_empower_amp`` and
    ``aa_empower_amp`` is 1.0 with apply_ability_amps off, so the factor is
    exact for any build with non-zero crit.
    """
    ad = result.stats["ad"]
    as_ = result.stats["as"]
    crit = min(result.stats["crit"], 1.0)
    assert crit > 0.0, "caller must use a crit build"
    return ((result.raw_attack_dps / (ad * as_)) - 1.0) / crit


def _ranked_ids(champion: str, top_n: int = 200, convert: bool = False):
    """Item-id ordering from rank_items at the gate params.

    This originally patched the module-level ``compute_dps`` name rank.py
    imported, because ``rank_items`` had no crit-conversion parameter (rank.py
    was owned by another slice) - the same technique PART 7 used to SIMULATE the
    reorder before any code existed. ``apply_crit_conversion`` is now plumbed
    through ``rank_items`` and POST /rank for real, so the measurement runs on
    the shipped code path instead. NOTE the patch technique would now SILENTLY
    NO-OP: rank_items passes the flag explicitly, and a call-time keyword
    overrides a ``functools.partial`` keyword.
    """
    res = rank_mod.rank_items(
        _snap(),
        champion_id=champion,
        level=GATE_LEVEL,
        current_item_ids=list(GATE_BUILD),
        mode="SR",
        top_n=top_n,
        apply_crit_conversion=convert,
        **GATE_TARGET,
    )
    return [r.item_id for r in res.ranked]


class TestCritConversionRegistry(unittest.TestCase):
    def test_ashe_entry_matches_ddragon(self):
        entry = crit_conversion_entry(ASHE)
        self.assertIsNotNone(entry)
        self.assertIsInstance(entry, CritConversionEntry)
        # 75% + 40% per the verbatim DDragon innate line.
        self.assertAlmostEqual(entry.crit_bonus, 1.15, places=12)
        self.assertAlmostEqual(_ASHE_FROST_SHOT_FACTOR, 1.15, places=12)
        # "Critical strikes do not deal any additional damage" -> IE is inert.
        self.assertTrue(entry.replaces_item_crit_damage)
        # "Runaan's Hurricane's will not deal additional damage on critical
        # strikes" - SR id plus the Arena mirror.
        self.assertIn(RUNAANS, entry.crit_denied_item_ids)
        self.assertIn(RUNAANS_ARENA, entry.crit_denied_item_ids)

    def test_registry_is_ashe_only(self):
        self.assertEqual(set(_CRIT_CONVERSION), {ASHE})
        self.assertIsNone(crit_conversion_entry(APHELIOS))
        self.assertIsNone(crit_conversion_entry("Jhin"))

    def test_conversion_exceeds_engine_default(self):
        # The row's headline direction: the engine UNDER-values her crit.
        self.assertGreater(_ASHE_FROST_SHOT_FACTOR, DEFAULT_CRIT_BONUS)
        self.assertAlmostEqual(
            (1.0 + _ASHE_FROST_SHOT_FACTOR) / (1.0 + DEFAULT_CRIT_BONUS),
            1.2285714285714286,
            places=12,
        )


class TestDefaultOffByteIdentity(unittest.TestCase):
    def test_omitted_flag_matches_pre_seam_goldens(self):
        for (champ, build), golden in GOLDEN_WEIGHTED_DPS.items():
            with self.subTest(champion=champ, build=build):
                self.assertEqual(_dps(champ, build).weighted_dps, golden)

    def test_explicit_false_matches_omitted(self):
        for champ, build in GOLDEN_WEIGHTED_DPS:
            with self.subTest(champion=champ, build=build):
                self.assertEqual(
                    _dps(champ, build, apply_crit_conversion=False).to_dict(),
                    _dps(champ, build).to_dict(),
                )

    def test_aphelios_negative_control_is_byte_identical_flag_on(self):
        # Aphelios carries no registry entry: flag ON must change NOTHING.
        for build in ((BERSERKERS,), (BERSERKERS, INFINITY_EDGE),
                      (BERSERKERS, PHANTOM_DANCER), (BERSERKERS, RUNAANS)):
            with self.subTest(build=build):
                self.assertEqual(
                    _dps(APHELIOS, build, apply_crit_conversion=True).to_dict(),
                    _dps(APHELIOS, build).to_dict(),
                )

    def test_unregistered_roster_sample_is_byte_identical_flag_on(self):
        for champ in ("Jhin", "Sivir", "Caitlyn", "Garen", "Ahri"):
            with self.subTest(champion=champ):
                self.assertEqual(
                    _dps(champ, (BERSERKERS, INFINITY_EDGE),
                         apply_crit_conversion=True).to_dict(),
                    _dps(champ, (BERSERKERS, INFINITY_EDGE)).to_dict(),
                )

    def test_zero_crit_ashe_build_is_identity(self):
        # No crit in the build -> the conversion term is multiplied by 0.
        off = _dps(ASHE, (BERSERKERS,))
        on = _dps(ASHE, (BERSERKERS,), apply_crit_conversion=True)
        self.assertEqual(off.stats["crit"], 0.0)
        self.assertEqual(on.weighted_dps, off.weighted_dps)
        self.assertEqual(on.avg_attack_dmg, off.avg_attack_dmg)

    def test_ranked_order_unchanged_when_flag_off(self):
        self.assertEqual(_ranked_ids(ASHE), _ranked_ids(ASHE, convert=False))


class TestConversionBehaviour(unittest.TestCase):
    def test_crit_bonus_becomes_frost_factor(self):
        on = _dps(ASHE, (BERSERKERS, PHANTOM_DANCER), apply_crit_conversion=True)
        self.assertAlmostEqual(_implied_crit_bonus(on), 1.15, places=9)

    def test_item_crit_damage_is_inert_under_conversion(self):
        # IE (+0.30 crit damage) and PD (+0.00) must resolve the SAME factor.
        ie = _dps(ASHE, (BERSERKERS, INFINITY_EDGE), apply_crit_conversion=True)
        pd = _dps(ASHE, (BERSERKERS, PHANTOM_DANCER), apply_crit_conversion=True)
        self.assertAlmostEqual(
            _implied_crit_bonus(ie), _implied_crit_bonus(pd), places=9
        )
        # ... and OFF they must differ (IE 1.05 vs PD 0.75), or the assertion
        # above proves nothing.
        ie_off = _dps(ASHE, (BERSERKERS, INFINITY_EDGE))
        pd_off = _dps(ASHE, (BERSERKERS, PHANTOM_DANCER))
        self.assertAlmostEqual(_implied_crit_bonus(ie_off), 1.05, places=9)
        self.assertAlmostEqual(_implied_crit_bonus(pd_off), 0.75, places=9)

    def test_conversion_raises_ashe_crit_dps(self):
        off = _dps(ASHE, (BERSERKERS, PHANTOM_DANCER))
        on = _dps(ASHE, (BERSERKERS, PHANTOM_DANCER), apply_crit_conversion=True)
        self.assertGreater(on.weighted_dps, off.weighted_dps)
        # AA-only term: (1 + 0.25*1.15) / (1 + 0.25*0.75).
        self.assertAlmostEqual(
            on.avg_attack_dmg / off.avg_attack_dmg,
            1.2875 / 1.1875,
            places=9,
        )

    def test_conversion_emits_a_note(self):
        on = _dps(ASHE, (BERSERKERS, PHANTOM_DANCER), apply_crit_conversion=True)
        self.assertTrue(
            any("crit conversion" in n.lower() for n in on.notes),
            on.notes,
        )
        off = _dps(ASHE, (BERSERKERS, PHANTOM_DANCER))
        self.assertFalse(any("crit conversion" in n.lower() for n in off.notes))


class TestRunaansCritDeny(unittest.TestCase):
    def test_hurricane_bolts_get_no_conversion_credit(self):
        # per_attack_on_hit_damage carries the Wind's Fury bolts. The Frost
        # conversion is an AA-only term, so the bolt damage must be invariant.
        off = _dps(ASHE, (BERSERKERS, RUNAANS))
        on = _dps(ASHE, (BERSERKERS, RUNAANS), apply_crit_conversion=True)
        self.assertGreater(off.per_attack_on_hit_damage, 0.0)
        self.assertEqual(on.per_attack_on_hit_damage,
                         off.per_attack_on_hit_damage)

    def test_deny_set_zeroes_a_crit_scaling_proc(self):
        # Mechanism proof. Essence Reaver's proc reads CallContext.crit_chance
        # (_effects_data.py:750, ``1.25*base_ad + 50*crit_chance``). Denying it
        # for Ashe must strip exactly that crit-scaled half. Runaan's own proc
        # carries no crit term, so the shipped 3085 entry is a REGRESSION GUARD
        # rather than a numeric demotion - this test proves the guard is live.
        # ER's proc is TIME-based (spellblade family), so it lands in
        # weighted_dps via _periodic_proc_dps, not in per_attack_on_hit_damage.
        base = crit_conversion_entry(ASHE)
        patched = CritConversionEntry(
            champion_id=ASHE,
            crit_bonus=base.crit_bonus,
            replaces_item_crit_damage=base.replaces_item_crit_damage,
            crit_denied_item_ids=frozenset({ESSENCE_REAVER}),
            note="test-only",
        )
        build = (BERSERKERS, PHANTOM_DANCER, ESSENCE_REAVER)
        undenied = _dps(ASHE, build, apply_crit_conversion=True)
        _CRIT_CONVERSION[ASHE] = patched
        try:
            denied = _dps(ASHE, build, apply_crit_conversion=True)
        finally:
            _CRIT_CONVERSION[ASHE] = base
        self.assertLess(denied.weighted_dps, undenied.weighted_dps)
        # ... and the deny is surgical: the AA term is untouched.
        self.assertEqual(denied.avg_attack_dmg, undenied.avg_attack_dmg)


class TestGateOrdering(unittest.TestCase):
    def test_infinity_edge_demotes_relative_to_phantom_dancer(self):
        before = _ranked_ids(ASHE)
        after = _ranked_ids(ASHE, convert=True)
        ie_before, ie_after = before.index(INFINITY_EDGE), after.index(INFINITY_EDGE)
        pd_before, pd_after = before.index(PHANTOM_DANCER), after.index(PHANTOM_DANCER)
        # The pure crit-chance item must close the gap on IE, IE must slip, and
        # PD must gain. Measured at the gate params: IE #8 -> #10, PD #36 -> #30
        # (PART 7's pre-code simulation filed #8 -> #9 and #35 -> #29).
        self.assertGreater(pd_before - ie_before, pd_after - ie_after)
        self.assertLess(pd_after, pd_before)
        self.assertGreater(ie_after, ie_before)
        self.assertEqual((ie_before + 1, ie_after + 1), (8, 10))
        self.assertEqual((pd_before + 1, pd_after + 1), (36, 30))

    def test_aphelios_ordering_is_byte_identical(self):
        self.assertEqual(_ranked_ids(APHELIOS), _ranked_ids(APHELIOS, convert=True))


if __name__ == "__main__":
    unittest.main()
