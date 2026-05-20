"""Phase 5.8 (s190, 2026-05-13) - Sundered Sky Lightshield Strike in burst.

Covers the new ``DpsResult.lightshield_strike_per_proc_damage`` /
``DpsResult.lightshield_strike_item_name`` fields and the
``compute_burst_damage`` combo-walker extension that arms Sundered Sky's
Lightshield Strike on ability cast, consumes on the next AA, capped at
1 proc per combo (Sundered Sky's 8s real CD vs typical 2-3s burst window).

Independent of Spellblade - a build with both Sundered Sky + Trinity
Force gets BOTH procs on the AA following the first ability cast
(separate state machines).
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
    _lightshield_strike_per_proc_damage,
    compute_dps,
)
from agents.daemon_slayer.effects import CallContext, collect_effects


SUNDERED_SKY = "6610"
TRINITY_FORCE = "3078"
LICH_BANE = "3100"
WITS_END = "3091"


def _snap() -> DataSnapshot:
    reset_default_cache()
    reset_combo_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── _lightshield_strike_per_proc_damage helper ──────────────────────────────


class LightshieldHelperTests(unittest.TestCase):
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
        dmg, name = _lightshield_strike_per_proc_damage(
            [], 0.0, 0.0, 1.0, self._ctx(),
        )
        self.assertEqual(dmg, 0.0)
        self.assertEqual(name, "")

    def test_non_lightshield_build_returns_zero(self) -> None:
        # Trinity Force is Spellblade, not Lightshield Strike.
        effects = collect_effects([TRINITY_FORCE])
        dmg, name = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        self.assertEqual(dmg, 0.0)
        self.assertEqual(name, "")

    def test_sundered_sky_returns_physical_proc(self) -> None:
        effects = collect_effects([SUNDERED_SKY])
        # Iter 16 (2026-05-20) recalibration: 70 + 0.8 * (base_ad +
        # bonus_ad) physical, no armor. base_ad=60, bonus_ad=0 ->
        # 70 + 0.8 * 60 = 70 + 48 = 118.
        dmg, name = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        self.assertAlmostEqual(dmg, 118.0, places=1)
        self.assertEqual(name, "Sundered Sky")

    def test_sundered_sky_armor_mitigation(self) -> None:
        effects = collect_effects([SUNDERED_SKY])
        # With 100 armor: factor 0.5; 118 x 0.5 = 59.
        dmg, _ = _lightshield_strike_per_proc_damage(
            effects, 100.0, 0.0, 1.0, self._ctx(),
        )
        self.assertAlmostEqual(dmg, 59.0, places=1)

    def test_sundered_sky_damage_amp_applies(self) -> None:
        effects = collect_effects([SUNDERED_SKY])
        dmg_base, _ = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        dmg_amp, _ = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(), damage_amp=1.10,
        )
        self.assertAlmostEqual(dmg_amp, dmg_base * 1.10, places=2)

    def test_sundered_sky_mode_multiplier_applies(self) -> None:
        effects = collect_effects([SUNDERED_SKY])
        dmg_sr, _ = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        dmg_aram, _ = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 0.95, self._ctx(),
        )
        self.assertAlmostEqual(dmg_aram, dmg_sr * 0.95, places=2)

    def test_sundered_sky_physical_unaffected_by_magic_amp(self) -> None:
        effects = collect_effects([SUNDERED_SKY])
        dmg_base, _ = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        dmg_amp, _ = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(), magic_amp=1.20,
        )
        # Sundered Sky's Lightshield Strike is PHYSICAL - magic_amp must
        # not affect it.
        self.assertAlmostEqual(dmg_amp, dmg_base, places=2)

    def test_lightshield_independent_of_spellblade(self) -> None:
        """A build with [Trinity Force, Sundered Sky] must surface BOTH
        procs separately - TF via spellblade helper, Sundered Sky via
        lightshield helper. No dedup family overlap."""
        effects = collect_effects([TRINITY_FORCE, SUNDERED_SKY])
        ls_dmg, ls_name = _lightshield_strike_per_proc_damage(
            effects, 0.0, 0.0, 1.0, self._ctx(),
        )
        self.assertGreater(ls_dmg, 0.0)
        self.assertEqual(ls_name, "Sundered Sky")
        # Order reversed - still independent.
        effects2 = collect_effects([SUNDERED_SKY, TRINITY_FORCE])
        ls_dmg2, ls_name2 = _lightshield_strike_per_proc_damage(
            effects2, 0.0, 0.0, 1.0, self._ctx(),
        )
        self.assertGreater(ls_dmg2, 0.0)
        self.assertEqual(ls_name2, "Sundered Sky")


# ─── DpsResult new fields ────────────────────────────────────────────────────


class DpsResultLightshieldFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_naked_build_yields_zero(self) -> None:
        r = compute_dps(self.snap, champion_id="Aatrox", level=11)
        self.assertEqual(r.lightshield_strike_per_proc_damage, 0.0)
        self.assertEqual(r.lightshield_strike_item_name, "")

    def test_spellblade_only_build_yields_zero_lightshield(self) -> None:
        # Trinity Force is Spellblade, not Lightshield Strike.
        r = compute_dps(
            self.snap, champion_id="Aatrox", level=11,
            item_ids=[TRINITY_FORCE], target_armor=80.0,
        )
        self.assertEqual(r.lightshield_strike_per_proc_damage, 0.0)
        self.assertEqual(r.lightshield_strike_item_name, "")
        # Sanity: spellblade is non-zero (s189 behavior unchanged).
        self.assertGreater(r.spellblade_per_proc_damage, 0.0)

    def test_sundered_sky_surfaces(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Aatrox", level=11,
            item_ids=[SUNDERED_SKY], target_armor=80.0,
        )
        self.assertGreater(r.lightshield_strike_per_proc_damage, 0.0)
        self.assertEqual(r.lightshield_strike_item_name, "Sundered Sky")
        # Sanity: spellblade still zero for a non-spellblade build.
        self.assertEqual(r.spellblade_per_proc_damage, 0.0)

    def test_both_items_surface_independently(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Aatrox", level=11,
            item_ids=[TRINITY_FORCE, SUNDERED_SKY], target_armor=80.0,
        )
        self.assertGreater(r.spellblade_per_proc_damage, 0.0)
        self.assertEqual(r.spellblade_item_name, "Trinity Force")
        self.assertGreater(r.lightshield_strike_per_proc_damage, 0.0)
        self.assertEqual(r.lightshield_strike_item_name, "Sundered Sky")

    def test_to_dict_carries_fields(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Aatrox", level=11,
            item_ids=[SUNDERED_SKY], target_armor=80.0,
        )
        d = r.to_dict()
        self.assertIn("lightshield_strike_per_proc_damage", d)
        self.assertIn("lightshield_strike_item_name", d)
        self.assertEqual(
            d["lightshield_strike_per_proc_damage"],
            r.lightshield_strike_per_proc_damage,
        )
        self.assertEqual(
            d["lightshield_strike_item_name"], r.lightshield_strike_item_name,
        )


# ─── Burst combo integration ─────────────────────────────────────────────────


class BurstLightshieldIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_naked_build_zero_lightshield_in_burst(self) -> None:
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        self.assertEqual(r.lightshield_strike_procs, 0)
        self.assertEqual(r.lightshield_strike_damage, 0.0)
        self.assertEqual(r.lightshield_strike_item_name, "")

    def test_sundered_sky_arms_and_fires_once(self) -> None:
        """Q-AA combo with Sundered Sky fires exactly 1 Lightshield Strike."""
        naked = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        with_ss = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        self.assertEqual(with_ss.lightshield_strike_procs, 1)
        self.assertGreater(with_ss.lightshield_strike_damage, 0.0)
        self.assertEqual(with_ss.lightshield_strike_item_name, "Sundered Sky")
        self.assertGreater(with_ss.total_burst_damage, naked.total_burst_damage)

    def test_capped_at_one_proc_per_combo(self) -> None:
        """Q-AA-W-AA combo - Sundered Sky fires ONCE, not twice (8s CD).
        Spellblade in same combo would fire twice, but Lightshield Strike
        is capped."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA", "W", "AA"),
        )
        self.assertEqual(r.lightshield_strike_procs, 1)

    def test_pure_aa_combo_zero_procs(self) -> None:
        """No ability cast → Lightshield Strike never armed."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("AA", "AA", "AA"),
        )
        self.assertEqual(r.lightshield_strike_procs, 0)
        self.assertEqual(r.lightshield_strike_damage, 0.0)
        # but item name still surfaces (build has Sundered Sky).
        self.assertEqual(r.lightshield_strike_item_name, "Sundered Sky")

    def test_no_aa_combo_zero_procs(self) -> None:
        """Pure ability combo with no AAs → can't fire."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "W", "E", "R"),
        )
        self.assertEqual(r.lightshield_strike_procs, 0)

    def test_aa_before_spell_no_proc(self) -> None:
        """AA before any spell-cast → not armed; only the post-spell AA
        fires."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("AA", "Q", "AA"),
        )
        self.assertEqual(r.lightshield_strike_procs, 1)

    def test_aa_row_includes_lightshield_in_final_damage(self) -> None:
        """The AA ComboCast row's final_damage carries the Lightshield
        contribution when armed."""
        with_ss = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        aa_row = next(c for c in with_ss.per_cast if c.token == "AA")
        from agents.daemon_slayer.dps import compute_dps as _dps
        probe = _dps(
            self.snap, champion_id="Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        # AA row final = base AA + Lightshield (no spellblade in this build).
        expected = probe.avg_attack_dmg + probe.lightshield_strike_per_proc_damage
        self.assertAlmostEqual(aa_row.final_damage, expected, delta=0.5)

    def test_sundered_sky_plus_trinity_force_stack_on_same_aa(self) -> None:
        """A build with both items lands both procs on the AA following
        the first ability cast - independent state machines, no dedup."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[TRINITY_FORCE, SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        self.assertEqual(r.spellblade_procs, 1)
        self.assertEqual(r.lightshield_strike_procs, 1)
        self.assertEqual(r.spellblade_item_name, "Trinity Force")
        self.assertEqual(r.lightshield_strike_item_name, "Sundered Sky")
        self.assertGreater(r.spellblade_damage, 0.0)
        self.assertGreater(r.lightshield_strike_damage, 0.0)

    def test_dual_proc_aa_row_carries_both(self) -> None:
        """The dual-item build's AA row carries base + spellblade +
        lightshield damage."""
        with_both = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[TRINITY_FORCE, SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        aa_row = next(c for c in with_both.per_cast if c.token == "AA")
        from agents.daemon_slayer.dps import compute_dps as _dps
        probe = _dps(
            self.snap, champion_id="Aatrox", level=11,
            item_ids=[TRINITY_FORCE, SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        expected = (
            probe.avg_attack_dmg
            + probe.spellblade_per_proc_damage
            + probe.lightshield_strike_per_proc_damage
        )
        self.assertAlmostEqual(aa_row.final_damage, expected, delta=0.5)

    def test_lightshield_after_spellblade_fired_does_not_re_arm(self) -> None:
        """Once Lightshield Strike fires in a combo, subsequent ability
        casts can't re-arm it (8s CD cap)."""
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA", "W", "E", "R", "AA"),
        )
        self.assertEqual(r.lightshield_strike_procs, 1)

    def test_to_dict_carries_lightshield_fields(self) -> None:
        r = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        d = r.to_dict()
        self.assertIn("lightshield_strike_procs", d)
        self.assertIn("lightshield_strike_damage", d)
        self.assertIn("lightshield_strike_item_name", d)
        self.assertEqual(d["lightshield_strike_item_name"], "Sundered Sky")

    def test_lightshield_plus_per_attack_on_hit_stack(self) -> None:
        """Wit's End (per-AA on-hit) + Sundered Sky (Lightshield Strike)
        both contribute independently - different mechanics, no overlap."""
        wits_only = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[WITS_END],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        ss_only = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        both = compute_burst_damage(
            self.snap, "Aatrox", level=11,
            item_ids=[WITS_END, SUNDERED_SKY],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        # Both build's AA carries Wit's End on-hit (every AA) + Lightshield
        # (post-spell AA only).
        self.assertEqual(both.lightshield_strike_procs, 1)
        self.assertGreater(both.auto_attack_damage, 0.0)
        # Both build should beat either single-item AA damage (sanity, allow
        # small slack for stat-block shifts).
        self.assertGreater(
            both.auto_attack_damage,
            max(wits_only.auto_attack_damage, ss_only.auto_attack_damage) - 1.0,
        )


# ─── server route exposes new BurstResult fields ─────────────────────────────


class ServerBurstRouteLightshieldTests(unittest.TestCase):
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

    def test_burst_with_sundered_sky_surfaces_lightshield(self) -> None:
        r = self._post("/burst", {
            "champion": "Aatrox", "level": 11, "mode": "SR",
            "items": [SUNDERED_SKY],
            "target_armor": 80.0, "target_mr": 30.0, "target_max_hp": 2000.0,
        })
        self.assertIn("lightshield_strike_procs", r)
        self.assertIn("lightshield_strike_damage", r)
        self.assertIn("lightshield_strike_item_name", r)
        self.assertGreater(r["lightshield_strike_procs"], 0)
        self.assertGreater(r["lightshield_strike_damage"], 0.0)
        self.assertEqual(r["lightshield_strike_item_name"], "Sundered Sky")

    def test_burst_naked_zero_lightshield(self) -> None:
        r = self._post("/burst", {
            "champion": "Aatrox", "level": 11, "mode": "SR",
            "target_armor": 80.0, "target_mr": 30.0, "target_max_hp": 2000.0,
        })
        self.assertEqual(r["lightshield_strike_procs"], 0)
        self.assertEqual(r["lightshield_strike_damage"], 0.0)
        self.assertEqual(r["lightshield_strike_item_name"], "")

    def test_burst_dual_proc_build_stacks(self) -> None:
        r = self._post("/burst", {
            "champion": "Aatrox", "level": 11, "mode": "SR",
            "items": [TRINITY_FORCE, SUNDERED_SKY],
            "target_armor": 80.0, "target_mr": 30.0, "target_max_hp": 2000.0,
        })
        self.assertGreater(r["spellblade_procs"], 0)
        self.assertGreater(r["lightshield_strike_procs"], 0)
        self.assertEqual(r["spellblade_item_name"], "Trinity Force")
        self.assertEqual(r["lightshield_strike_item_name"], "Sundered Sky")


if __name__ == "__main__":
    unittest.main()
