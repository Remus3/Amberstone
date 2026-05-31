"""2026-05-30 (item 226 NEXT) - ability_hps v2 tests.

Pins the two v2 additive paths on top of the v1 active-slot heal/shield
scorer, and proves both are BYTE-IDENTICAL to v1 when they do not apply.
The v1 suite (``test_ability_hps_2026_05_30.py``) stays green unchanged.

v2 adds:
* PASSIVE-P slot inclusion (``include_passive=True``, default ON). The
  extractor emits NO P-slot heal/shield blocks at 16.11.1, so the path is a
  no-op for the live roster - proven via a hand-built abilities snapshot
  that DOES carry a P heal block (the path scores it) plus a real-data
  data-availability-ceiling assertion (Aatrox/Dr.Mundo passive heals are NOT
  in the snapshot, so they contribute 0 - we do NOT fabricate them).
* TARGET-RELATIVE + CASTER-MISSING-HP unit resolution
  (``resolve_target_relative=True``, default OFF). v1 flags these units
  unresolved (lower bound 0); v2 resolves them against documented
  representative stats. Ground truth probed from the live 16.11.1 snapshot:
  - Taric W shield = "% of target's maximum health" [7,8,9,10,11]; rank 2 = 9
  - Volibear W heal = flat [20,35,50,65,80] + "% of his missing health"
    [8,11,14,17,20]; rank 2 = 50 flat + 14% caster-missing-HP
"""
from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.abilities import AbilitiesSnapshot, AbilityForm
from agents.daemon_slayer.ability_dps import AbilityContext
from agents.daemon_slayer.ability_hps import (
    _eval_heal_shield_block,
    _resolve_extra_units,
    compute_ability_hps,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import build_champion

_SNAP = DataSnapshot.load()


def _caster_max_hp(champ_id: str, level: int = 11) -> float:
    """Resolve the itemless SR caster max HP the heal scorer sees."""
    r = build_champion(_SNAP, champ_id, level, item_ids=None, mode="SR")
    ctx = AbilityContext.from_build(
        stats=r.stats, base_stats=r.base_stats,
        target_armor=0.0, target_mr=0.0, target_max_hp=0.0, target_bonus_hp=0.0,
    )
    return float(ctx.caster_max_hp)


def _spell(result, key):
    return next((s for s in result.spells if s.key == key), None)


class TargetRelativeShieldTests(unittest.TestCase):
    """Taric W shield = % of target's maximum health (a target-relative unit)."""

    def test_default_off_drops_unresolved_target_shield(self):
        # v1 default: the target-relative unit is unresolved -> shield 0 ->
        # the W spell is dropped entirely (no other heal/shield term).
        off = compute_ability_hps(_SNAP, "Taric", 11, mode="SR")
        self.assertIsNone(_spell(off, "W"))
        self.assertEqual(off.total_shield_per_sec, 0.0)

    def test_v2_on_computes_lower_bound_shield(self):
        # v2: 9% (rank 2) of a representative 2000-HP target = 180.0.
        on = compute_ability_hps(
            _SNAP, "Taric", 11, mode="SR",
            resolve_target_relative=True, target_max_hp=2000.0,
        )
        w = _spell(on, "W")
        self.assertIsNotNone(w)
        self.assertEqual(w.rank, 2)
        self.assertAlmostEqual(w.shield_per_cast, 0.09 * 2000.0, places=4)  # 180.0
        self.assertGreater(on.total_shield_per_sec, 0.0)

    def test_v2_on_with_zero_target_hp_stays_zero(self):
        # Resolving ON but with target_max_hp=0 (the default) still gives 0 -
        # so flipping the flag without a representative HP changes nothing.
        on = compute_ability_hps(
            _SNAP, "Taric", 11, mode="SR", resolve_target_relative=True,
        )
        self.assertIsNone(_spell(on, "W"))
        self.assertEqual(on.total_shield_per_sec, 0.0)


class CasterMissingHpHealTests(unittest.TestCase):
    """Volibear W heal = flat + % of his missing health (caster-missing-HP)."""

    def test_default_off_scores_flat_only_and_flags_lower_bound(self):
        off = compute_ability_hps(_SNAP, "Volibear", 11, mode="SR")
        w = _spell(off, "W")
        self.assertIsNotNone(w)
        self.assertAlmostEqual(w.heal_per_cast, 50.0, places=4)  # flat r2 only
        self.assertTrue(w.notes)  # missing-HP unit unresolved -> lower-bound note

    def test_v2_on_adds_caster_missing_hp_term(self):
        cmax = _caster_max_hp("Volibear", 11)
        on = compute_ability_hps(
            _SNAP, "Volibear", 11, mode="SR",
            resolve_target_relative=True, caster_missing_hp_pct=0.5,
        )
        w = _spell(on, "W")
        self.assertIsNotNone(w)
        self.assertEqual(w.rank, 2)
        # 50 flat + 14% (rank 2) of (caster_max_hp * 0.5 missing).
        expected = 50.0 + 0.14 * (cmax * 0.5)
        self.assertAlmostEqual(w.heal_per_cast, expected, places=3)

    def test_v2_delta_isolates_missing_hp_term(self):
        off = compute_ability_hps(_SNAP, "Volibear", 11, mode="SR")
        on = compute_ability_hps(
            _SNAP, "Volibear", 11, mode="SR",
            resolve_target_relative=True, caster_missing_hp_pct=0.5,
        )
        wo = _spell(off, "W")
        wn = _spell(on, "W")
        delta = wn.heal_per_cast - wo.heal_per_cast
        self.assertAlmostEqual(delta, 0.14 * (_caster_max_hp("Volibear", 11) * 0.5), places=3)


class PassiveSlotTests(unittest.TestCase):
    """P-slot inclusion: scores a passive heal block when one exists; honest
    no-op when (as at 16.11.1) the snapshot carries none."""

    @staticmethod
    def _stub_with_passive_heal():
        # Garen exists in the build engine; give it a synthetic P heal block.
        p_form = AbilityForm.from_dict({
            "key": "P", "name": "Stub Passive Heal", "form_index": 0,
            "icon": None, "cooldown": [8.0], "cost": None, "damage_type": None,
            "targeting": None, "affects": None, "resource": "NONE",
            "is_aoe": False,
            "damage_blocks": [{
                "attribute": "Heal", "attribute_kind": "heal",
                "raw_modifiers": [{"values": [40], "units": [""]}],
            }],
            "raw_effects_count": 0, "raw_leveling_count": 0,
            "parse_status": "ok", "parse_notes": [],
        })
        return AbilitiesSnapshot(
            patch="stub", fetched_at="", source="", coverage={},
            champions={"Garen": {
                "P": (p_form,), "Q": (), "W": (), "E": (), "R": (),
            }},
        )

    def test_passive_heal_block_is_scored(self):
        stub = self._stub_with_passive_heal()
        r = compute_ability_hps(
            _SNAP, "Garen", 11, mode="SR", abilities=stub, include_passive=True,
        )
        p = _spell(r, "P")
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.heal_per_cast, 40.0, places=4)
        # 8s cooldown -> 0.125 casts/s -> 5.0 heal/s.
        self.assertAlmostEqual(p.casts_per_sec, 0.125, places=4)
        self.assertAlmostEqual(p.heal_per_sec, 5.0, places=3)
        self.assertGreater(r.total_heal_per_sec, 0.0)

    def test_include_passive_false_drops_p(self):
        stub = self._stub_with_passive_heal()
        r = compute_ability_hps(
            _SNAP, "Garen", 11, mode="SR", abilities=stub, include_passive=False,
        )
        self.assertEqual(r.spells, ())
        self.assertEqual(r.total_ability_hps, 0.0)

    def test_real_roster_has_no_passive_heal_blocks(self):
        # Data-availability ceiling: Aatrox/Dr.Mundo passive heals live in
        # stripped effects text, not in parsed P-slot heal/shield blocks.
        for c in ("Aatrox", "DrMundo", "Vladimir", "Warwick"):
            r = compute_ability_hps(_SNAP, c, 11, mode="SR")
            self.assertEqual(
                [s for s in r.spells if s.key == "P"], [],
                f"{c} should surface no P-slot heal/shield (none in snapshot)",
            )


class V1RegressionTests(unittest.TestCase):
    """A champion already covered by v1 returns the SAME per-cast values.

    Expected values are the v1 pins from ``test_ability_hps_2026_05_30.py``.
    """

    def test_soraka_w_unchanged(self):
        r = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR")
        self.assertAlmostEqual(_spell(r, "W").heal_per_cast, 130.0, places=1)

    def test_janna_e_unchanged(self):
        r = compute_ability_hps(_SNAP, "Janna", 11, mode="SR")
        self.assertAlmostEqual(_spell(r, "E").shield_per_cast, 80.0, places=1)

    def test_sona_w_unchanged(self):
        r = compute_ability_hps(_SNAP, "Sona", 11, mode="SR")
        w = _spell(r, "W")
        self.assertAlmostEqual(w.heal_per_cast, 60.0, places=1)
        self.assertAlmostEqual(w.shield_per_cast, 65.0, places=1)

    def test_defaults_byte_identical_to_explicit_v1_path(self):
        # v2 defaults (include_passive=True + resolve_target_relative=False)
        # must produce the same totals as the exact v1 Q/W/E/R-only walk.
        for c in ("Soraka", "Janna", "Sona", "Volibear", "Yorick", "Caitlyn"):
            default = compute_ability_hps(_SNAP, c, 11, mode="SR")
            v1eq = compute_ability_hps(
                _SNAP, c, 11, mode="SR",
                include_passive=False, resolve_target_relative=False,
            )
            self.assertAlmostEqual(
                default.total_ability_hps, v1eq.total_ability_hps, places=9,
                msg=f"{c} default vs v1-equivalent totals diverged",
            )


class FailSoftTests(unittest.TestCase):
    def test_champion_absent_from_abilities_snapshot_returns_empty(self):
        # Realistic "unknown to abilities" case: champ resolves in the build
        # engine but is absent from the abilities snapshot -> empty/zero, no
        # raise (the v1 _empty_result path, preserved).
        empty_abil = AbilitiesSnapshot(
            patch="stub", fetched_at="", source="", coverage={},
            champions={"Garen": {"P": (), "Q": (), "W": (), "E": (), "R": ()}},
        )
        r = compute_ability_hps(_SNAP, "Soraka", 11, mode="SR", abilities=empty_abil)
        self.assertEqual(r.total_ability_hps, 0.0)
        self.assertEqual(r.spells, ())
        self.assertTrue(any("no abilities snapshot entry" in n for n in r.notes))


class ResolveExtraUnitsTests(unittest.TestCase):
    """The opt-in resolver builds the right unit -> value map."""

    def test_resolver_maps_target_and_caster_units(self):
        class _Ctx:
            caster_max_hp = 2000.0
        m = _resolve_extra_units(
            _Ctx(), target_max_hp=1000.0,
            target_missing_hp_pct=0.4, caster_missing_hp_pct=0.5,
        )
        self.assertEqual(m["% of target's maximum health"], 1000.0)
        self.assertAlmostEqual(m["% of target's missing health"], 400.0, places=4)
        self.assertAlmostEqual(m["% missing health"], 1000.0, places=4)  # 2000*0.5
        self.assertAlmostEqual(m["% of his missing health"], 1000.0, places=4)

    def test_extra_units_none_keeps_v1_unresolved(self):
        # Calling _eval_heal_shield_block WITHOUT extra_units (the v1 call
        # shape) leaves a target-relative unit unresolved - byte-identical v1.
        from agents.daemon_slayer.abilities import DamageBlock
        b = DamageBlock(
            attribute="Shield Strength", attribute_kind="shield",
            raw_modifiers=({"values": [7, 8, 9, 10, 11],
                            "units": ["% of target's maximum health"] * 5},),
        )

        class _Ctx:
            ap = 0.0
            caster_max_hp = 2000.0
        amt, unres = _eval_heal_shield_block(b, 2, _Ctx())
        self.assertEqual(amt, 0.0)
        self.assertTrue(unres)
        # With the resolved map threaded, the same block resolves (no flag).
        m = _resolve_extra_units(
            _Ctx(), target_max_hp=2000.0,
            target_missing_hp_pct=0.0, caster_missing_hp_pct=0.0,
        )
        amt2, unres2 = _eval_heal_shield_block(b, 2, _Ctx(), m)
        self.assertAlmostEqual(amt2, 0.09 * 2000.0, places=4)  # 180.0
        self.assertFalse(unres2)


class AsciiHygieneTests(unittest.TestCase):
    def test_v2_files_are_ascii(self):
        for rel in ("ability_hps.py", "tests/test_ability_hps_v2.py"):
            p = Path(__file__).resolve().parents[1] / rel
            data = p.read_bytes()
            non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
            self.assertEqual(
                non_ascii, [], f"{rel} has non-ASCII bytes: {non_ascii[:5]}",
            )


if __name__ == "__main__":
    unittest.main()
