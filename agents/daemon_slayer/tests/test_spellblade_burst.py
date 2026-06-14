"""Phase 5.7 (s189, 2026-05-13) - Spellblade-in-burst tests.

Covers the new ``DpsResult.spellblade_per_proc_damage`` /
``DpsResult.spellblade_item_name`` fields and the
``compute_burst_damage`` combo-walker that arms Spellblade on each
ability cast and consumes it on the next AA. Spellblade family in the
engine: Trinity Force (3078), Lich Bane (3100), Essence Reaver (3508),
Iceborn Gauntlet (6662), Dusk and Dawn (2510), Divine Sunderer (6632),
Sheen (3057), Bloodsong (5311) - plus Arena mirrors. ``collect_effects``
dedups via ``unique_passive_key="spellblade"`` so at most one survives.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import compute_burst_damage, reset_combo_cache
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import (
    _spellblade_per_proc_damage,
    compute_dps,
)
from agents.daemon_slayer.effects import CallContext, collect_effects


TRINITY_FORCE = "3078"
LICH_BANE = "3100"
ESSENCE_REAVER = "3508"
ICEBORN_GAUNTLET = "6662"
DIVINE_SUNDERER = "6632"
SHEEN = "3057"
WITS_END = "3091"
BOTRK = "3153"


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_combo_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# --- _spellblade_per_proc_damage helper --------------------------------------


class SpellbladeHelperTests(unittest.TestCase):
    """Direct exercises of the helper without going through compute_dps."""

    def _ctx(self, **overrides) -> CallContext:
        base = {
            "base_ad": 60.0,
            "bonus_ad": 0.0,
            "level": 11,
            "target_armor": 0.0,
            "target_mr": 0.0,
            "ap": 0.0,
            "target_max_hp": 2000.0,
            "caster_max_hp": 2000.0,
            "caster_bonus_hp": 0.0,
            "target_bonus_hp": 0.0,
            "crit_chance": 0.0,
            "caster_max_mp": 0.0,
            "caster_bonus_armor": 0.0,
            "caster_lethality": 0.0,
            "ult_casts_per_sec": 0.0,
        }
        base.update(overrides)
        return CallContext(**base)

    def test_empty_effects_returns_zero(self) -> None:
        dmg, name = _spellblade_per_proc_damage(
            [], 0.0, 0.0, 1.0, self._ctx(),
        )
        self.assertEqual(dmg, 0.0)
        self.assertEqual(name, "")

    def test_non_spellblade_build_returns_zero(self) -> None:
        # Wit's End and BotRK are per-AA on-hit, NOT spellblade.
        effects = collect_effects([WITS_END, BOTRK])
        dmg, name = _spellblade_per_proc_damage(
            effects, 0.0, 30.0, 1.0, self._ctx(),
        )
        self.assertEqual(dmg, 0.0)
        self.assertEqual(name, "")

    def test_trinity_force_returns_physical_proc(self) -> None:
        effects = collect_effects([TRINITY_FORCE])
        # TF: 2.0 x base_ad physical, no armor -> raw 120, factor 1.0 -> 120.
        dmg, name = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        self.assertAlmostEqual(dmg, 120.0, places=1)
        self.assertEqual(name, "Trinity Force")

    def test_trinity_force_armor_mitigation(self) -> None:
        effects = collect_effects([TRINITY_FORCE])
        # With 100 armor: factor 0.5; 120 x 0.5 = 60.
        dmg, _ = _spellblade_per_proc_damage(
            effects, 100.0, 0.0, 1.0, self._ctx(),
        )
        self.assertAlmostEqual(dmg, 60.0, places=1)

    def test_lich_bane_uses_mr_for_magic(self) -> None:
        effects = collect_effects([LICH_BANE])
        # LB: 0.75 x base_ad + 0.40 x ap -> 0.75*60 + 0.40*100 = 45 + 40 = 85
        # MR 100 -> factor 0.5 -> 42.5.
        # (AP coefficient corrected from 50% -> 40% per Meraki bulk 16.10.1.)
        dmg, name = _spellblade_per_proc_damage(
            effects, 0.0, 100.0, 1.0, self._ctx(ap=100.0),
        )
        self.assertAlmostEqual(dmg, 42.5, places=1)
        self.assertEqual(name, "Lich Bane")

    def test_lich_bane_magic_amp_applies(self) -> None:
        effects = collect_effects([LICH_BANE])
        # Without amp: 95 x 1.0 (no MR). With magic_amp=1.20: 95 x 1.20.
        dmg_base, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(ap=100.0),
        )
        dmg_amp, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(ap=100.0), magic_amp=1.20,
        )
        self.assertAlmostEqual(dmg_amp, dmg_base * 1.20, places=2)

    def test_trinity_force_magic_amp_does_not_apply_physical(self) -> None:
        effects = collect_effects([TRINITY_FORCE])
        dmg_base, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        dmg_amp, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(), magic_amp=1.20,
        )
        # Trinity Force is PHYSICAL - magic_amp must not affect it.
        self.assertAlmostEqual(dmg_amp, dmg_base, places=2)

    def test_damage_amp_applies(self) -> None:
        effects = collect_effects([TRINITY_FORCE])
        dmg_base, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        dmg_amp, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(), damage_amp=1.10,
        )
        self.assertAlmostEqual(dmg_amp, dmg_base * 1.10, places=2)

    def test_mode_multiplier_applies(self) -> None:
        effects = collect_effects([TRINITY_FORCE])
        dmg_sr, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        dmg_aram, _ = _spellblade_per_proc_damage(
            effects, 0.0, 0.0, 0.95, self._ctx(),
        )
        self.assertAlmostEqual(dmg_aram, dmg_sr * 0.95, places=2)

    def test_dedup_takes_first_spellblade(self) -> None:
        # collect_effects dedups via unique_passive_key - first item wins.
        # Build [Trinity Force, Lich Bane] keeps TF (physical).
        effects_tf_first = collect_effects([TRINITY_FORCE, LICH_BANE])
        dmg, name = _spellblade_per_proc_damage(
            effects_tf_first, 0.0, 100.0, 1.0, self._ctx(ap=100.0),
        )
        self.assertEqual(name, "Trinity Force")
        # 2.0 x 60 = 120, physical, no armor, no MR effect.
        self.assertAlmostEqual(dmg, 120.0, places=1)

        # Reverse order: Lich Bane wins, magical, MR matters.
        effects_lb_first = collect_effects([LICH_BANE, TRINITY_FORCE])
        dmg2, name2 = _spellblade_per_proc_damage(
            effects_lb_first, 0.0, 0.0, 1.0, self._ctx(ap=100.0),
        )
        self.assertEqual(name2, "Lich Bane")
        # 0.75 x 60 + 0.40 x 100 = 85, no MR.
        # (AP coefficient corrected from 50% -> 40% per Meraki bulk 16.10.1.)
        self.assertAlmostEqual(dmg2, 85.0, places=1)


# --- DpsResult new fields ----------------------------------------------------


class DpsResultSpellbladeFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_naked_build_yields_zero_spellblade(self) -> None:
        r = compute_dps(self.snap, champion_id="Jax", level=11)
        self.assertEqual(r.spellblade_per_proc_damage, 0.0)
        self.assertEqual(r.spellblade_item_name, "")

    def test_per_attack_only_items_still_zero_spellblade(self) -> None:
        # Wit's End + BotRK are per-AA on-hit, not Spellblade.
        r = compute_dps(
            self.snap, champion_id="Vayne", level=11,
            item_ids=[WITS_END, BOTRK], target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
        )
        self.assertEqual(r.spellblade_per_proc_damage, 0.0)
        self.assertEqual(r.spellblade_item_name, "")
        # but per_attack_on_hit_damage non-zero (sanity, s188 behavior).
        self.assertGreater(r.per_attack_on_hit_damage, 0.0)

    def test_trinity_force_surfaces(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Jax", level=11,
            item_ids=[TRINITY_FORCE], target_armor=80.0,
        )
        self.assertGreater(r.spellblade_per_proc_damage, 0.0)
        self.assertEqual(r.spellblade_item_name, "Trinity Force")

    def test_lich_bane_surfaces(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Veigar", level=11,
            item_ids=[LICH_BANE], target_mr=30.0,
        )
        self.assertGreater(r.spellblade_per_proc_damage, 0.0)
        self.assertEqual(r.spellblade_item_name, "Lich Bane")

    def test_to_dict_carries_fields(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Jax", level=11,
            item_ids=[TRINITY_FORCE], target_armor=80.0,
        )
        d = r.to_dict()
        self.assertIn("spellblade_per_proc_damage", d)
        self.assertIn("spellblade_item_name", d)
        self.assertEqual(
            d["spellblade_per_proc_damage"], r.spellblade_per_proc_damage,
        )
        self.assertEqual(d["spellblade_item_name"], r.spellblade_item_name)


# --- Burst combo integration -------------------------------------------------


class BurstSpellbladeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_naked_build_zero_spellblade_in_burst(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        self.assertEqual(r.spellblade_procs, 0)
        self.assertEqual(r.spellblade_damage, 0.0)
        self.assertEqual(r.spellblade_item_name, "")

    def test_trinity_force_arms_and_fires(self) -> None:
        """Ability-then-AA combo with Trinity Force fires Spellblade."""
        naked = compute_burst_damage(
            self.snap, "Akali", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        with_tf = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        self.assertEqual(with_tf.spellblade_procs, 1)
        self.assertGreater(with_tf.spellblade_damage, 0.0)
        self.assertEqual(with_tf.spellblade_item_name, "Trinity Force")
        self.assertGreater(with_tf.total_burst_damage, naked.total_burst_damage)

    def test_two_aa_after_two_spells_fires_twice(self) -> None:
        """Q-AA-W-AA fires Spellblade on both AAs (each arming-then-consume)."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA", "W", "AA"),
        )
        self.assertEqual(r.spellblade_procs, 2)
        # Total Spellblade damage ~= 2x per-proc.
        # We can verify the partition: cumulative ~= sum of per-row Spellblade.
        per_aa_added = sum(
            c.final_damage for c in r.per_cast if c.token == "AA"
        )
        self.assertGreater(per_aa_added, 0.0)

    def test_multi_spell_then_single_aa_fires_once(self) -> None:
        """Q-W-E-AA fires Spellblade once - sequential casts before any AA
        leave it armed, single AA consumes."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "W", "E", "AA"),
        )
        self.assertEqual(r.spellblade_procs, 1)

    def test_aa_before_spell_no_proc(self) -> None:
        """AA before any spell-cast -> no Spellblade. The first AA isn't
        armed; the second AA fires once because Q armed it."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("AA", "Q", "AA"),
        )
        self.assertEqual(r.spellblade_procs, 1)

    def test_no_aa_in_combo_zero_procs(self) -> None:
        """Pure ability combo (no AA tokens) -> Spellblade can't fire."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "W", "E", "R"),
        )
        self.assertEqual(r.spellblade_procs, 0)
        self.assertEqual(r.spellblade_damage, 0.0)
        # but spellblade_item_name still surfaces (build has TF).
        self.assertEqual(r.spellblade_item_name, "Trinity Force")

    def test_only_aa_combo_zero_procs(self) -> None:
        """Pure AA combo (no ability tokens) -> Spellblade never armed."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("AA", "AA", "AA"),
        )
        self.assertEqual(r.spellblade_procs, 0)
        self.assertEqual(r.spellblade_damage, 0.0)

    def test_aa_row_includes_spellblade_in_final_damage(self) -> None:
        """The AA ComboCast row's final_damage reflects Spellblade contribution
        when armed - armed-and-consumed AA row equals
        ``avg_attack_dmg + spellblade_per_proc_damage`` from the same
        build's compute_dps probe."""
        with_sb = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        aa_sb = next(c for c in with_sb.per_cast if c.token == "AA")
        # Both probe + burst use the SAME build (TF), so AA = base AA
        # damage + Spellblade per-proc. Allow tiny float drift.
        from agents.daemon_slayer.dps import compute_dps as _dps
        probe = _dps(
            self.snap, champion_id="Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        expected = probe.avg_attack_dmg + probe.spellblade_per_proc_damage
        self.assertAlmostEqual(aa_sb.final_damage, expected, delta=0.5)
        # Sanity: WITH spellblade > the build's avg_attack_dmg alone.
        self.assertGreater(aa_sb.final_damage, probe.avg_attack_dmg)

    def test_zed_combo_with_trinity_force_meaningful_lift(self) -> None:
        """Zed full combo (Q-W-E-R-Q2-AA) with TF should lift burst
        meaningfully - Zed has 1 AA preceded by 5 ability casts."""
        naked = compute_burst_damage(
            self.snap, "Zed", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        with_tf = compute_burst_damage(
            self.snap, "Zed", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        self.assertEqual(with_tf.spellblade_procs, 1)
        # Total burst should be higher; AA contribution should be higher.
        self.assertGreater(with_tf.total_burst_damage, naked.total_burst_damage)
        self.assertGreater(
            with_tf.auto_attack_damage, naked.auto_attack_damage
        )

    def test_essence_reaver_in_assassin_combo(self) -> None:
        """Essence Reaver (crit-scaling Spellblade) - same arming model."""
        r = compute_burst_damage(
            self.snap, "Talon", level=11,
            item_ids=[ESSENCE_REAVER],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        self.assertEqual(r.spellblade_item_name, "Essence Reaver")
        self.assertGreater(r.spellblade_procs, 0)
        self.assertGreater(r.spellblade_damage, 0.0)

    def test_divine_sunderer_in_burst(self) -> None:
        """Divine Sunderer Spellblade scales with target max HP - assassin
        fighting beefy target should see meaningful lift."""
        r = compute_burst_damage(
            self.snap, "Zed", level=11,
            item_ids=[DIVINE_SUNDERER],
            target_armor=80.0, target_mr=30.0, target_max_hp=3000.0,
        )
        self.assertEqual(r.spellblade_item_name, "Divine Sunderer")
        self.assertGreater(r.spellblade_procs, 0)

    def test_dedup_keeps_one_spellblade(self) -> None:
        """Two Spellblade items in the build -> only first-seen wins (via
        collect_effects). Spellblade fires once, not twice per AA."""
        r = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE, LICH_BANE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        # First-seen wins - TF is the active spellblade, not LB.
        self.assertEqual(r.spellblade_item_name, "Trinity Force")
        self.assertEqual(r.spellblade_procs, 1)

    def test_spellblade_and_wits_end_both_contribute(self) -> None:
        """Both layers contribute independently: Wit's End on EVERY AA, TF on
        ability-then-AA transitions."""
        wits_only = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[WITS_END],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        tf_only = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        both = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[WITS_END, TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        # Both build should beat each single-item variant on AA damage.
        # Comparisons across builds shift base AD/AS/crit + Q damage too,
        # so just assert spellblade and on-hit both registered.
        self.assertEqual(both.spellblade_procs, 1)
        self.assertGreater(both.auto_attack_damage, 0.0)
        # Sanity: the both build's AA damage roughly tracks wits_only + tf
        # Spellblade addition (allow generous slack for stat-block shifts).
        self.assertGreater(
            both.auto_attack_damage,
            max(wits_only.auto_attack_damage, tf_only.auto_attack_damage) - 1.0,
        )

    def test_to_dict_carries_spellblade_fields(self) -> None:
        r = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        d = r.to_dict()
        self.assertIn("spellblade_procs", d)
        self.assertIn("spellblade_damage", d)
        self.assertIn("spellblade_item_name", d)
        self.assertEqual(d["spellblade_item_name"], "Trinity Force")

    def test_zed_default_combo_uses_override(self) -> None:
        """Zed's per-champion combo (Q-W-E-R-Q2-AA from s186 registry)
        has 1 AA - Spellblade fires exactly once."""
        r = compute_burst_damage(
            self.snap, "Zed", level=11,
            item_ids=[TRINITY_FORCE],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        # combo: Q-W-E-R-Q2-AA -> arms via spells, fires on the 1 AA.
        self.assertEqual(r.spellblade_procs, 1)


# --- server route exposes new BurstResult fields -----------------------------


class ServerBurstRouteSpellbladeTests(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8893"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            urlopen(f"{cls.BASE_URL}/health", timeout=2).read()
        except Exception as e:  # pragma: no cover - env-dependent
            raise unittest.SkipTest(f"DS server unavailable: {e}")

    def _post(self, path: str, body: dict) -> dict:
        req = Request(
            f"{self.BASE_URL}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.loads(urlopen(req, timeout=10).read())

    def test_burst_with_trinity_force_surfaces_spellblade(self) -> None:
        r = self._post("/burst", {
            "champion": "Akali", "level": 11, "mode": "SR",
            "items": [TRINITY_FORCE],
            "target_armor": 80.0, "target_mr": 30.0, "target_max_hp": 2000.0,
        })
        self.assertIn("spellblade_procs", r)
        self.assertIn("spellblade_damage", r)
        self.assertIn("spellblade_item_name", r)
        self.assertGreater(r["spellblade_procs"], 0)
        self.assertGreater(r["spellblade_damage"], 0.0)
        self.assertEqual(r["spellblade_item_name"], "Trinity Force")

    def test_burst_naked_zero_spellblade(self) -> None:
        r = self._post("/burst", {
            "champion": "Akali", "level": 11, "mode": "SR",
            "target_armor": 80.0, "target_mr": 30.0, "target_max_hp": 2000.0,
        })
        self.assertEqual(r["spellblade_procs"], 0)
        self.assertEqual(r["spellblade_damage"], 0.0)
        self.assertEqual(r["spellblade_item_name"], "")


if __name__ == "__main__":
    unittest.main()
