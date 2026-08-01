"""Phase 4d (s185, 2026-05-13) - per-champion max_priority override tests.

Tests the ``champion_max_priority.json`` registry loader plus its
integration with ``compute_ability_dps`` / ``rank_items_by_ability_dps``
and ``compute_burst_damage`` / ``rank_items_by_burst``. The override
table assigns Cassiopeia -> E-Q-W, Kayle -> E-Q-W, TwistedFate -> W-Q-E,
etc.; verifying both the canonical-priority overrides and the
``max_priority_source`` provenance field that every scorer threads
through their result.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    DEFAULT_MAX_PRIORITY,
    _MAX_PRIORITY_PATH,
    _load_max_priority_table,
    _resolve_max_priority,
    compute_ability_dps,
    get_max_priority_for,
    rank_at_level,
    rank_items_by_ability_dps,
    reset_max_priority_cache,
)
from agents.daemon_slayer.burst import (
    compute_burst_damage,
    rank_items_by_burst,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# --- registry shape ----------------------------------------------------------


class RegistryShapeTests(unittest.TestCase):
    """The on-disk JSON must be a valid permutation registry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.table = _load_max_priority_table()

    def test_path_exists(self) -> None:
        self.assertTrue(_MAX_PRIORITY_PATH.exists())

    def test_has_default_and_champions(self) -> None:
        self.assertIn("default", self.table)
        self.assertIn("champions", self.table)

    def test_default_is_q_w_e(self) -> None:
        self.assertEqual(tuple(self.table["default"]), ("Q", "W", "E"))

    def test_every_entry_is_valid_permutation(self) -> None:
        for champion_id, value in self.table["champions"].items():
            with self.subTest(champion_id=champion_id):
                self.assertEqual(len(value), 3, f"{champion_id}: expected 3 keys")
                self.assertEqual(
                    set(value), {"Q", "W", "E"},
                    f"{champion_id}: not a permutation of (Q, W, E)",
                )

    def test_known_canonical_overrides(self) -> None:
        """Lock down the specific overrides operators will see."""
        overrides = self.table["champions"]
        self.assertEqual(tuple(overrides["Cassiopeia"]), ("E", "Q", "W"))
        self.assertEqual(tuple(overrides["Kayle"]), ("E", "Q", "W"))
        self.assertEqual(tuple(overrides["TwistedFate"]), ("W", "Q", "E"))
        self.assertEqual(tuple(overrides["Heimerdinger"]), ("W", "Q", "E"))
        self.assertEqual(tuple(overrides["Kassadin"]), ("E", "Q", "W"))


# --- loader / cache ----------------------------------------------------------


class LoaderCacheTests(unittest.TestCase):
    def test_singleton_returns_same_object(self) -> None:
        reset_max_priority_cache()
        a = _load_max_priority_table()
        b = _load_max_priority_table()
        self.assertIs(a, b)

    def test_reset_clears_cache(self) -> None:
        reset_max_priority_cache()
        a = _load_max_priority_table()
        reset_max_priority_cache()
        b = _load_max_priority_table()
        # New parse - equal contents but distinct object identity.
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_default_constant_matches_registry(self) -> None:
        table = _load_max_priority_table()
        self.assertEqual(DEFAULT_MAX_PRIORITY, tuple(table["default"]))


# --- get_max_priority_for ----------------------------------------------------


class GetMaxPriorityForTests(unittest.TestCase):
    def test_known_override_returns_champion_source(self) -> None:
        priority, source = get_max_priority_for("Cassiopeia")
        self.assertEqual(priority, ("E", "Q", "W"))
        self.assertEqual(source, "champion")

    def test_unknown_falls_back_to_default(self) -> None:
        priority, source = get_max_priority_for("Veigar")
        self.assertEqual(priority, ("Q", "W", "E"))
        self.assertEqual(source, "default")

    def test_invented_champion_falls_back(self) -> None:
        priority, source = get_max_priority_for("NoSuchChampion")
        self.assertEqual(priority, ("Q", "W", "E"))
        self.assertEqual(source, "default")

    def test_uppercase_normalized(self) -> None:
        # Registry stores upper-case keys; resolver should return upper-case.
        priority, _ = get_max_priority_for("Kayle")
        self.assertTrue(all(k.isupper() for k in priority))


# --- _resolve_max_priority ---------------------------------------------------


class ResolveMaxPriorityTests(unittest.TestCase):
    def test_none_with_known_returns_champion(self) -> None:
        priority, source = _resolve_max_priority("Cassiopeia", None)
        self.assertEqual(priority, ("E", "Q", "W"))
        self.assertEqual(source, "champion")

    def test_none_with_unknown_returns_default(self) -> None:
        priority, source = _resolve_max_priority("Veigar", None)
        self.assertEqual(priority, ("Q", "W", "E"))
        self.assertEqual(source, "default")

    def test_explicit_returns_override(self) -> None:
        priority, source = _resolve_max_priority("Cassiopeia", ("W", "Q", "E"))
        self.assertEqual(priority, ("W", "Q", "E"))
        self.assertEqual(source, "override")

    def test_explicit_uppercases(self) -> None:
        priority, _ = _resolve_max_priority("Veigar", ("q", "w", "e"))
        self.assertEqual(priority, ("Q", "W", "E"))

    def test_explicit_validates_permutation(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_max_priority("Veigar", ("Q", "Q", "E"))

    def test_explicit_validates_length(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_max_priority("Veigar", ("Q", "W"))


# --- rank_at_level reflects priority -----------------------------------------


class RankAtLevelOverrideTests(unittest.TestCase):
    """The actual rank math should shift when priority changes - that's
    the whole point of this feature."""

    def test_default_q_first_at_lvl9(self) -> None:
        self.assertEqual(rank_at_level("Q", 9, max_priority=("Q", "W", "E")), 4)
        self.assertEqual(rank_at_level("W", 9, max_priority=("Q", "W", "E")), 1)
        self.assertEqual(rank_at_level("E", 9, max_priority=("Q", "W", "E")), 0)

    def test_cassi_e_first_at_lvl9(self) -> None:
        # When E is maxed first, by lvl 9 E should be rank 4, not Q.
        priority = ("E", "Q", "W")
        self.assertEqual(rank_at_level("E", 9, max_priority=priority), 4)
        self.assertEqual(rank_at_level("Q", 9, max_priority=priority), 1)
        self.assertEqual(rank_at_level("W", 9, max_priority=priority), 0)


# --- integration: compute_ability_dps ---------------------------------------


class ComputeAbilityDpsOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_default_champion_source(self) -> None:
        r = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.max_priority, ("Q", "W", "E"))
        self.assertEqual(r.max_priority_source, "default")

    def test_overridden_champion_source(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.max_priority, ("E", "Q", "W"))
        self.assertEqual(r.max_priority_source, "champion")

    def test_explicit_override_wins(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
            max_priority=("W", "Q", "E"),
        )
        self.assertEqual(r.max_priority, ("W", "Q", "E"))
        self.assertEqual(r.max_priority_source, "override")

    def test_override_changes_dps(self) -> None:
        """Cassiopeia's total DPS should differ when E-Q-W (override) vs
        Q-W-E (forced default) because E is her spam spell - at lvl 9
        E sits at rank 4 vs rank 0."""
        with_override = compute_ability_dps(
            self.snap, "Cassiopeia", level=9, mode="SR", target_mr=30.0,
        )
        without_override = compute_ability_dps(
            self.snap, "Cassiopeia", level=9, mode="SR", target_mr=30.0,
            max_priority=("Q", "W", "E"),
        )
        # Override picks E first -> E rank 4 -> Twin Fang contributes more.
        self.assertGreater(
            with_override.total_ability_dps,
            without_override.total_ability_dps,
            "Cassiopeia E-Q-W should beat Q-W-E at lvl 9 (Twin Fang at rank 4 vs rank 0)",
        )


# --- integration: compute_burst_damage --------------------------------------


class ComputeBurstOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_default_champion_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11, mode="SR", target_armor=80.0, target_max_hp=2000.0,
        )
        self.assertEqual(r.max_priority, ("Q", "W", "E"))
        self.assertEqual(r.max_priority_source, "default")

    def test_overridden_champion_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR", target_mr=30.0, target_max_hp=2000.0,
        )
        # Akali -> E-Q-W (Shuriken Flip primary)
        self.assertEqual(r.max_priority, ("E", "Q", "W"))
        self.assertEqual(r.max_priority_source, "champion")

    def test_explicit_override_wins(self) -> None:
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR", target_mr=30.0, target_max_hp=2000.0,
            max_priority=("Q", "W", "E"),
        )
        self.assertEqual(r.max_priority, ("Q", "W", "E"))
        self.assertEqual(r.max_priority_source, "override")


# --- integration: rankers carry source --------------------------------------


class RankerSourcePropagationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_rank_mage_default_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.max_priority, ("Q", "W", "E"))
        self.assertEqual(r.max_priority_source, "default")

    def test_rank_mage_champion_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.max_priority, ("E", "Q", "W"))
        self.assertEqual(r.max_priority_source, "champion")

    def test_rank_mage_override_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0, top_n=3,
            max_priority=("W", "Q", "E"),
        )
        self.assertEqual(r.max_priority, ("W", "Q", "E"))
        self.assertEqual(r.max_priority_source, "override")

    def test_rank_assassin_champion_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Akali", level=11, mode="SR",
            target_mr=30.0, target_max_hp=2000.0, top_n=3,
        )
        self.assertEqual(r.max_priority, ("E", "Q", "W"))
        self.assertEqual(r.max_priority_source, "champion")


# --- to_dict round-trip ------------------------------------------------------


class ToDictSerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_compute_ability_dps_to_dict_carries_source(self) -> None:
        r = compute_ability_dps(
            self.snap, "Cassiopeia", level=11, mode="SR", target_mr=30.0,
        )
        d = r.to_dict()
        self.assertEqual(d["max_priority"], ["E", "Q", "W"])
        self.assertEqual(d["max_priority_source"], "champion")

    def test_rank_mage_to_dict_carries_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Kayle", level=11, mode="SR", target_mr=30.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["max_priority"], ["E", "Q", "W"])
        self.assertEqual(d["max_priority_source"], "champion")

    def test_compute_burst_to_dict_carries_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Akali", level=11, mode="SR",
            target_mr=30.0, target_max_hp=2000.0,
        )
        d = r.to_dict()
        self.assertEqual(d["max_priority"], ["E", "Q", "W"])
        self.assertEqual(d["max_priority_source"], "champion")

    def test_rank_assassin_to_dict_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Akali", level=11, mode="SR",
            target_mr=30.0, target_max_hp=2000.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["max_priority"], ["E", "Q", "W"])
        self.assertEqual(d["max_priority_source"], "champion")


# --- server route surfaces source --------------------------------------------


class ServerRouteSourceTests(unittest.TestCase):
    """Hits the live :8860 server. Skips if unavailable so the test
    suite remains hermetic when the DS daemon isn't running."""

    BASE_URL = "http://127.0.0.1:8860"

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

    def test_ability_dps_default_source(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Veigar", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["max_priority"], ["Q", "W", "E"])
        self.assertEqual(r["max_priority_source"], "default")

    def test_ability_dps_champion_source(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["max_priority"], ["E", "Q", "W"])
        self.assertEqual(r["max_priority_source"], "champion")

    def test_ability_dps_explicit_override(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Cassiopeia", "level": 11, "mode": "SR", "target_mr": 30.0,
            "max_priority": "QWE",
        })
        self.assertEqual(r["max_priority"], ["Q", "W", "E"])
        self.assertEqual(r["max_priority_source"], "override")

    def test_rank_mage_champion_source(self) -> None:
        r = self._post("/rank-mage", {
            "champion": "Kayle", "level": 11, "mode": "SR",
            "target_mr": 30.0, "top": 3,
        })
        self.assertEqual(r["max_priority"], ["E", "Q", "W"])
        self.assertEqual(r["max_priority_source"], "champion")


if __name__ == "__main__":
    unittest.main()
