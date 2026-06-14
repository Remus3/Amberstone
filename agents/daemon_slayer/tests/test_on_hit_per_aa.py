"""Phase 5.6 (s188, 2026-05-13) - per-attack on-hit proc damage tests.

Covers the new ``DpsResult.per_attack_on_hit_damage`` field + its
integration with ``compute_burst_damage``. Items that proc on every AA
(Wit's End +magic, BotRK Mist's Edge HP%, Statikk Shiv 4-stack) should
make each AA token in a burst combo deal more than the raw armor-only
``avg_attack_dmg``.
"""
from __future__ import annotations

import unittest
from urllib.request import Request, urlopen
import json

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps


WITS_END = "3091"
BOTRK = "3153"
STATIKK_SHIV = "3087"
TRINITY_FORCE = "3078"


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# --- DpsResult new field -----------------------------------------------------


class DpsResultFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_empty_build_is_zero(self) -> None:
        r = compute_dps(self.snap, champion_id="Caitlyn", level=11)
        self.assertEqual(r.per_attack_on_hit_damage, 0.0)

    def test_wits_end_adds_per_aa_magic_damage(self) -> None:
        no_item = compute_dps(self.snap, champion_id="Akali", level=11, target_mr=30.0)
        with_wits = compute_dps(
            self.snap, champion_id="Akali", level=11,
            item_ids=[WITS_END], target_mr=30.0,
        )
        self.assertEqual(no_item.per_attack_on_hit_damage, 0.0)
        self.assertGreater(with_wits.per_attack_on_hit_damage, 0.0)

    def test_botrk_adds_per_aa_hp_proc(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Vayne", level=11,
            item_ids=[BOTRK], target_armor=80.0, target_max_hp=2000.0,
        )
        self.assertGreater(r.per_attack_on_hit_damage, 0.0)

    def test_to_dict_carries_field(self) -> None:
        r = compute_dps(
            self.snap, champion_id="Akali", level=11,
            item_ids=[WITS_END], target_mr=30.0,
        )
        d = r.to_dict()
        self.assertIn("per_attack_on_hit_damage", d)
        self.assertEqual(d["per_attack_on_hit_damage"], r.per_attack_on_hit_damage)


# --- Burst integration ------------------------------------------------------


class BurstOnHitIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_akali_wits_end_increases_burst(self) -> None:
        """Akali with Wit's End should have higher total burst than naked
        Akali - every AA in the combo procs Wit's End magic damage."""
        naked = compute_burst_damage(
            self.snap, "Akali", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        with_wits = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[WITS_END],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        # The new build's burst must exceed naked by at least the on-hit
        # contribution x AA count.
        self.assertGreater(
            with_wits.total_burst_damage,
            naked.total_burst_damage,
            "Akali with Wit's End must beat naked Akali by the on-hit"
            " procs on her AAs in the combo",
        )

    def test_botrk_increases_zed_burst(self) -> None:
        naked = compute_burst_damage(
            self.snap, "Zed", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        with_botrk = compute_burst_damage(
            self.snap, "Zed", level=11,
            item_ids=[BOTRK],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        # Zed's combo includes 1 AA (Q-W-E-R-Q2-AA from the s186
        # registry); BotRK Mist's Edge is on-hit physical (target current
        # HP %).
        self.assertGreater(with_botrk.total_burst_damage, naked.total_burst_damage)

    def test_per_cast_aa_picks_up_on_hit(self) -> None:
        """The AA ComboCast row's final_damage should reflect base + on-hit."""
        no_item = compute_burst_damage(
            self.snap, "Akali", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        with_wits = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[WITS_END],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        aa_naked = next(c for c in no_item.per_cast if c.token == "AA")
        aa_wits = next(c for c in with_wits.per_cast if c.token == "AA")
        self.assertGreater(aa_wits.final_damage, aa_naked.final_damage)

    def test_naked_build_aa_unchanged(self) -> None:
        """Without any on-hit items, AA damage equals avg_attack_dmg (the
        pre-s188 behavior - backward-compat sanity)."""
        naked = compute_burst_damage(
            self.snap, "Zed", level=11,
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
        )
        # No on-hit procs in a naked build, so AA == avg_attack_dmg.
        from agents.daemon_slayer.dps import compute_dps as _dps
        probe = _dps(
            self.snap, champion_id="Zed", level=11,
            target_armor=80.0, target_mr=30.0,
            target_max_hp=2000.0,
        )
        self.assertEqual(probe.per_attack_on_hit_damage, 0.0)
        aa_row = next(c for c in naked.per_cast if c.token == "AA")
        self.assertAlmostEqual(aa_row.final_damage, probe.avg_attack_dmg, places=2)

    def test_aa_count_2_scales_on_hit(self) -> None:
        """A combo with 2 AAs should pick up 2x the on-hit contribution
        (each AA fires its own on-hit proc)."""
        r1 = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[WITS_END],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA"),
        )
        r2 = compute_burst_damage(
            self.snap, "Akali", level=11,
            item_ids=[WITS_END],
            target_armor=80.0, target_mr=30.0, target_max_hp=2000.0,
            combo_sequence=("Q", "AA", "AA"),
        )
        aa1 = sum(c.final_damage for c in r1.per_cast if c.token == "AA")
        aa2 = sum(c.final_damage for c in r2.per_cast if c.token == "AA")
        # 2 AAs should be ~2x one AA.
        self.assertAlmostEqual(aa2, 2.0 * aa1, places=2)


# --- server route exposes new DpsResult field -------------------------------


class ServerDpsRouteTests(unittest.TestCase):
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

    def test_dps_with_wits_end_surfaces_per_attack_on_hit(self) -> None:
        r = self._post("/dps", {
            "champion": "Akali", "level": 11, "mode": "SR",
            "items": [WITS_END], "target_mr": 30.0,
        })
        self.assertIn("per_attack_on_hit_damage", r)
        self.assertGreater(r["per_attack_on_hit_damage"], 0.0)

    def test_dps_naked_per_attack_on_hit_zero(self) -> None:
        r = self._post("/dps", {
            "champion": "Caitlyn", "level": 11, "mode": "SR",
        })
        self.assertEqual(r["per_attack_on_hit_damage"], 0.0)


if __name__ == "__main__":
    unittest.main()
