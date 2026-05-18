"""Phase 5.5 (s186, 2026-05-13) - per-champion combo_sequence override tests.

Tests the ``champion_combo_sequences.json`` registry loader plus its
integration with ``compute_burst_damage`` and ``rank_items_by_burst``.
The override table assigns Zed → Q-W-E-R-Q2-AA (shadow Q double),
Yone → Q-Q2-Q3-AA-E-W-R (chain knockup), Akali → Q-AA-E-R-Q2-AA-R2
(R recast), etc. Verifies the canonical-combo overrides and the
``combo_sequence_source`` provenance field that the burst scorer
threads through its result.
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import (
    DEFAULT_COMBO_SEQUENCE,
    _COMBO_PATH,
    _load_combo_table,
    _resolve_combo_sequence,
    compute_burst_damage,
    get_combo_for,
    rank_items_by_burst,
    reset_combo_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── registry shape ──────────────────────────────────────────────────────────


class RegistryShapeTests(unittest.TestCase):
    """The on-disk JSON must be a valid combo registry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.table = _load_combo_table()

    def test_path_exists(self) -> None:
        self.assertTrue(_COMBO_PATH.exists())

    def test_has_default_and_champions(self) -> None:
        self.assertIn("default", self.table)
        self.assertIn("champions", self.table)

    def test_default_is_engine_default(self) -> None:
        self.assertEqual(
            tuple(self.table["default"]),
            ("Q", "W", "E", "AA", "R", "AA"),
        )

    def test_every_entry_validates(self) -> None:
        # Validator raises on bad tokens; an entry that fails validation
        # would surface here as an exception from get_combo_for.
        for champion_id in self.table["champions"]:
            with self.subTest(champion_id=champion_id):
                combo, source = get_combo_for(champion_id)
                self.assertEqual(source, "champion")
                self.assertGreater(len(combo), 0)

    def test_zed_combo_includes_q2(self) -> None:
        zed = tuple(self.table["champions"]["Zed"])
        self.assertIn("Q2", zed)

    def test_yone_combo_includes_q3(self) -> None:
        yone = tuple(self.table["champions"]["Yone"])
        self.assertIn("Q3", yone)

    def test_akali_combo_includes_r2(self) -> None:
        akali = tuple(self.table["champions"]["Akali"])
        self.assertIn("R2", akali)

    def test_canonical_assassin_ids_used(self) -> None:
        # DDragon canonical ids - no apostrophe, lowercase 'b'.
        champions = self.table["champions"]
        self.assertIn("Khazix", champions)
        self.assertIn("Leblanc", champions)
        self.assertNotIn("Kha'Zix", champions)
        self.assertNotIn("KhaZix", champions)
        self.assertNotIn("LeBlanc", champions)


# ─── loader / cache ──────────────────────────────────────────────────────────


class LoaderCacheTests(unittest.TestCase):
    def test_singleton_returns_same_object(self) -> None:
        reset_combo_cache()
        a = _load_combo_table()
        b = _load_combo_table()
        self.assertIs(a, b)

    def test_reset_clears_cache(self) -> None:
        reset_combo_cache()
        a = _load_combo_table()
        reset_combo_cache()
        b = _load_combo_table()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


# ─── get_combo_for ───────────────────────────────────────────────────────────


class GetComboForTests(unittest.TestCase):
    def test_known_override_returns_champion_source(self) -> None:
        combo, source = get_combo_for("Zed")
        self.assertEqual(combo, ("Q", "W", "E", "R", "Q2", "AA"))
        self.assertEqual(source, "champion")

    def test_unknown_falls_back_to_default(self) -> None:
        combo, source = get_combo_for("Pantheon")
        self.assertEqual(combo, DEFAULT_COMBO_SEQUENCE)
        self.assertEqual(source, "default")

    def test_invented_champion_falls_back(self) -> None:
        combo, source = get_combo_for("NoSuchChampion")
        self.assertEqual(combo, DEFAULT_COMBO_SEQUENCE)
        self.assertEqual(source, "default")

    def test_repeat_tokens_preserved(self) -> None:
        akali, _ = get_combo_for("Akali")
        # Akali's override has Q2 + R2; both must survive validation.
        self.assertIn("Q2", akali)
        self.assertIn("R2", akali)


# ─── _resolve_combo_sequence ─────────────────────────────────────────────────


class ResolveComboSequenceTests(unittest.TestCase):
    def test_none_with_known_returns_champion(self) -> None:
        combo, source = _resolve_combo_sequence("Zed", None)
        self.assertEqual(combo, ("Q", "W", "E", "R", "Q2", "AA"))
        self.assertEqual(source, "champion")

    def test_none_with_unknown_returns_default(self) -> None:
        combo, source = _resolve_combo_sequence("Pantheon", None)
        self.assertEqual(combo, DEFAULT_COMBO_SEQUENCE)
        self.assertEqual(source, "default")

    def test_explicit_returns_override(self) -> None:
        combo, source = _resolve_combo_sequence("Zed", ("Q", "AA", "R"))
        self.assertEqual(combo, ("Q", "AA", "R"))
        self.assertEqual(source, "override")

    def test_explicit_validates_tokens(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_combo_sequence("Zed", ("Q", "BAD"))

    def test_explicit_validates_empty(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_combo_sequence("Zed", [])


# ─── integration: compute_burst_damage ──────────────────────────────────────


class ComputeBurstOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_default_champion_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Pantheon", level=11, target_armor=80,
        )
        self.assertEqual(r.combo_sequence, DEFAULT_COMBO_SEQUENCE)
        self.assertEqual(r.combo_sequence_source, "default")

    def test_overridden_champion_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
        )
        self.assertEqual(r.combo_sequence, ("Q", "W", "E", "R", "Q2", "AA"))
        self.assertEqual(r.combo_sequence_source, "champion")

    def test_explicit_override_wins(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
            combo_sequence=("Q", "AA", "R"),
        )
        self.assertEqual(r.combo_sequence, ("Q", "AA", "R"))
        self.assertEqual(r.combo_sequence_source, "override")

    def test_zed_shadow_q_increases_burst(self) -> None:
        """Zed's registry combo includes Q2 (shadow Q). With override, burst
        should exceed the engine-default 6-token combo because Q fires twice
        at the same rank instead of once."""
        with_q2 = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_max_hp=2000,
        )
        without_q2 = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_max_hp=2000,
            combo_sequence=("Q", "W", "E", "AA", "R", "AA"),
        )
        self.assertGreater(
            with_q2.total_burst_damage,
            without_q2.total_burst_damage,
            "Zed Q-W-E-R-Q2-AA must beat Q-W-E-AA-R-AA (Q fires twice vs once)",
        )

    def test_yone_q3_chain(self) -> None:
        """Yone's combo fires Q1+Q2+Q3 - three Q casts at the same rank."""
        r = compute_burst_damage(
            self.snap, "Yone", level=11, target_armor=80,
        )
        q_casts = [c for c in r.per_cast if c.token in ("Q", "Q2", "Q3")]
        self.assertEqual(len(q_casts), 3)


# ─── integration: rank_items_by_burst ───────────────────────────────────────


class RankByBurstOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_zed_ranker_carries_override(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.combo_sequence, ("Q", "W", "E", "R", "Q2", "AA"))
        self.assertEqual(r.combo_sequence_source, "champion")

    def test_pantheon_ranker_uses_default(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Pantheon", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.combo_sequence, DEFAULT_COMBO_SEQUENCE)
        self.assertEqual(r.combo_sequence_source, "default")

    def test_explicit_override_wins_in_ranker(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
            combo_sequence=("Q", "AA", "R"),
        )
        self.assertEqual(r.combo_sequence, ("Q", "AA", "R"))
        self.assertEqual(r.combo_sequence_source, "override")

    def test_zed_baseline_higher_with_override(self) -> None:
        with_override = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        forced_default = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
            combo_sequence=("Q", "W", "E", "AA", "R", "AA"),
        )
        self.assertGreater(
            with_override.baseline_burst,
            forced_default.baseline_burst,
        )


# ─── to_dict serialization ───────────────────────────────────────────────────


class ToDictSerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_compute_burst_to_dict_carries_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
        )
        d = r.to_dict()
        self.assertEqual(d["combo_sequence"], ["Q", "W", "E", "R", "Q2", "AA"])
        self.assertEqual(d["combo_sequence_source"], "champion")

    def test_rank_assassin_to_dict_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Akali", level=11, mode="SR",
            target_mr=30.0, target_max_hp=2000.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["combo_sequence_source"], "champion")
        self.assertIn("R2", d["combo_sequence"])


# ─── server route surfaces source ────────────────────────────────────────────


class ServerRouteSourceTests(unittest.TestCase):
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

    def test_burst_default_source(self) -> None:
        r = self._post("/burst", {
            "champion": "Pantheon", "level": 11, "mode": "SR", "target_armor": 80,
        })
        self.assertEqual(r["combo_sequence"], ["Q", "W", "E", "AA", "R", "AA"])
        self.assertEqual(r["combo_sequence_source"], "default")

    def test_burst_champion_source(self) -> None:
        r = self._post("/burst", {
            "champion": "Zed", "level": 11, "mode": "SR", "target_armor": 80,
        })
        self.assertEqual(r["combo_sequence"], ["Q", "W", "E", "R", "Q2", "AA"])
        self.assertEqual(r["combo_sequence_source"], "champion")

    def test_burst_explicit_override(self) -> None:
        r = self._post("/burst", {
            "champion": "Zed", "level": 11, "mode": "SR", "target_armor": 80,
            "combo_sequence": "Q-AA-R",
        })
        self.assertEqual(r["combo_sequence"], ["Q", "AA", "R"])
        self.assertEqual(r["combo_sequence_source"], "override")

    def test_rank_assassin_champion_source(self) -> None:
        r = self._post("/rank-assassin", {
            "champion": "Akali", "level": 11, "mode": "SR",
            "target_mr": 30.0, "target_max_hp": 2000.0, "top": 3,
        })
        self.assertEqual(r["combo_sequence_source"], "champion")
        self.assertIn("R2", r["combo_sequence"])


if __name__ == "__main__":
    unittest.main()
