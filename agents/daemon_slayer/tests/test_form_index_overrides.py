"""Phase 4e (s187, 2026-05-13) - per-(champion, key) form_index override tests.

Tests the ``champion_form_index.json`` registry loader plus its integration
with ``compute_ability_dps`` / ``rank_items_by_ability_dps`` and
``compute_burst_damage`` / ``rank_items_by_burst``. The override table
maps Nidalee Q/W/E → 1 (cougar), Elise Q → 1 (Venomous Bite), Jayce Q → 1
(cannon Shock Blast), Hwei Q/W/E → first damage-bearing form, LeeSin
Q → 1 (Resonating Strike).
"""
from __future__ import annotations

import json
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    _FORM_INDEX_PATH,
    _load_form_index_table,
    _resolve_form_index_overrides,
    compute_ability_dps,
    get_form_index_for,
    rank_items_by_ability_dps,
    reset_form_index_cache,
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


# ─── registry shape ──────────────────────────────────────────────────────────


class RegistryShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = _load_form_index_table()

    def test_path_exists(self) -> None:
        self.assertTrue(_FORM_INDEX_PATH.exists())

    def test_has_default_and_champions(self) -> None:
        self.assertIn("default", self.table)
        self.assertIn("champions", self.table)

    def test_default_is_empty_dict(self) -> None:
        self.assertEqual(self.table["default"], {})

    def test_known_champion_overrides(self) -> None:
        champions = self.table["champions"]
        # Phase 4e (s187) - initial seed of 5 multi-form champions
        self.assertEqual(champions["Nidalee"], {"Q": 1, "W": 1, "E": 1})
        self.assertEqual(champions["Elise"], {"Q": 1})
        self.assertEqual(champions["Jayce"], {"Q": 1})
        self.assertEqual(champions["Hwei"], {"Q": 1, "W": 3, "E": 1})
        self.assertEqual(champions["LeeSin"], {"Q": 1})
        # Phase 5.9.17 (s204) - Riven form_index seed (closes the s203
        # carry-forward 'Riven form_index registry seed needed').
        self.assertEqual(champions["Riven"], {"R": 1})
        # Phase 5.9.18 (s205) - Qiyana / AurelionSol / Renekton form_index
        # seeds (closes the s204 carry-forward 'Qiyana Q form_index seed
        # expansion still pending'). Third instance of form_index +
        # block_index NET-damage composition after s203 LeeSin Q + s204
        # Riven R + s204 Nidalee Q.
        self.assertEqual(champions["Qiyana"], {"Q": 1})
        self.assertEqual(champions["AurelionSol"], {"R": 1})
        self.assertEqual(champions["Renekton"], {"E": 1})

    def test_every_value_is_int(self) -> None:
        for champion_id, entries in self.table["champions"].items():
            for key, value in entries.items():
                with self.subTest(champion_id=champion_id, key=key):
                    self.assertIsInstance(value, int)
                    self.assertGreaterEqual(value, 0)


# ─── loader / cache ──────────────────────────────────────────────────────────


class LoaderCacheTests(unittest.TestCase):
    def test_singleton_returns_same_object(self) -> None:
        reset_form_index_cache()
        a = _load_form_index_table()
        b = _load_form_index_table()
        self.assertIs(a, b)

    def test_reset_clears_cache(self) -> None:
        reset_form_index_cache()
        a = _load_form_index_table()
        reset_form_index_cache()
        b = _load_form_index_table()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)


# ─── get_form_index_for ──────────────────────────────────────────────────────


class GetFormIndexForTests(unittest.TestCase):
    def test_known_override_returns_champion_source(self) -> None:
        mapping, source = get_form_index_for("Nidalee")
        self.assertEqual(mapping, {"Q": 1, "W": 1, "E": 1})
        self.assertEqual(source, "champion")

    def test_unknown_falls_back_to_default(self) -> None:
        mapping, source = get_form_index_for("Veigar")
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_invented_champion_falls_back(self) -> None:
        mapping, source = get_form_index_for("NoSuchChampion")
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_keys_uppercased(self) -> None:
        mapping, _ = get_form_index_for("Hwei")
        # All resolved keys must be uppercase.
        for k in mapping:
            self.assertEqual(k, k.upper())


# ─── _resolve_form_index_overrides ───────────────────────────────────────────


class ResolveFormIndexTests(unittest.TestCase):
    def test_none_with_known_returns_champion(self) -> None:
        mapping, source = _resolve_form_index_overrides("Nidalee", None)
        self.assertEqual(mapping, {"Q": 1, "W": 1, "E": 1})
        self.assertEqual(source, "champion")

    def test_none_with_unknown_returns_default(self) -> None:
        mapping, source = _resolve_form_index_overrides("Veigar", None)
        self.assertEqual(mapping, {})
        self.assertEqual(source, "default")

    def test_explicit_returns_override(self) -> None:
        mapping, source = _resolve_form_index_overrides("Veigar", {"Q": 2})
        self.assertEqual(mapping, {"Q": 2})
        self.assertEqual(source, "override")

    def test_explicit_merges_with_registry(self) -> None:
        # Operator overrides Nidalee Q but not W/E - registry fills the gaps.
        mapping, source = _resolve_form_index_overrides("Nidalee", {"Q": 0})
        self.assertEqual(mapping, {"Q": 0, "W": 1, "E": 1})
        self.assertEqual(source, "override")

    def test_explicit_uppercases_keys(self) -> None:
        mapping, _ = _resolve_form_index_overrides("Veigar", {"q": 1})
        self.assertEqual(mapping, {"Q": 1})


# ─── integration: compute_ability_dps ───────────────────────────────────────


class ComputeAbilityDpsFormIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_champion_uses_default(self) -> None:
        r = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.form_index_source, "default")
        self.assertEqual(r.form_index_resolved, {})

    def test_mapped_champion_uses_registry(self) -> None:
        r = compute_ability_dps(
            self.snap, "Hwei", level=11, mode="SR", target_mr=30.0,
        )
        self.assertEqual(r.form_index_source, "champion")
        self.assertEqual(r.form_index_resolved, {"Q": 1, "W": 3, "E": 1})

    def test_explicit_override_wins(self) -> None:
        r = compute_ability_dps(
            self.snap, "Nidalee", level=11, mode="SR", target_mr=30.0,
            form_index_overrides={"Q": 0},
        )
        # Operator's Q=0 wins; W/E come from registry (Nidalee → both 1).
        self.assertEqual(r.form_index_source, "override")
        self.assertEqual(r.form_index_resolved, {"Q": 0, "W": 1, "E": 1})

    def test_hwei_dps_with_registry_exceeds_zero(self) -> None:
        """Hwei form 0 for each key has zero damage blocks - without the
        registry override the ability DPS would collapse to 0. Registry
        flips to first damaging form."""
        r = compute_ability_dps(
            self.snap, "Hwei", level=11, mode="SR", target_mr=30.0,
        )
        self.assertGreater(r.total_ability_dps, 0.0)

    def test_hwei_forced_form_0_collapses_dps(self) -> None:
        """If operator forces form 0 for each Hwei key, total drops to 0
        because every key's form 0 is a stance-setup with no damage blocks."""
        r = compute_ability_dps(
            self.snap, "Hwei", level=11, mode="SR", target_mr=30.0,
            form_index_overrides={"Q": 0, "W": 0, "E": 0},
        )
        # Only R remains; Q/W/E all evaluate to 0 damage with form 0.
        non_r_dps = sum(s.dps for s in r.per_spell if s.key != "R")
        self.assertEqual(non_r_dps, 0.0)


# ─── integration: compute_burst_damage ──────────────────────────────────────


class ComputeBurstFormIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unmapped_champion_uses_default(self) -> None:
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
        )
        self.assertEqual(r.form_index_source, "default")

    def test_mapped_champion_uses_registry(self) -> None:
        r = compute_burst_damage(
            self.snap, "Nidalee", level=11, target_armor=80,
        )
        self.assertEqual(r.form_index_source, "champion")
        self.assertEqual(r.form_index_resolved, {"Q": 1, "W": 1, "E": 1})

    def test_explicit_override_wins(self) -> None:
        r = compute_burst_damage(
            self.snap, "Nidalee", level=11, target_armor=80,
            form_index_overrides={"R": 0},
        )
        # Operator added R=0; registry Q/W/E pass through.
        self.assertEqual(r.form_index_source, "override")
        self.assertEqual(r.form_index_resolved, {"Q": 1, "W": 1, "E": 1, "R": 0})


# ─── ranker propagation ─────────────────────────────────────────────────────


class RankerFormIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_rank_mage_carries_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Hwei", level=11, mode="SR",
            target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.form_index_source, "champion")
        self.assertEqual(r.form_index_resolved, {"Q": 1, "W": 3, "E": 1})

    def test_rank_assassin_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Nidalee", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.form_index_source, "champion")
        self.assertEqual(r.form_index_resolved, {"Q": 1, "W": 1, "E": 1})

    def test_rank_unmapped_champion_default(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR",
            target_mr=30.0, top_n=3,
        )
        self.assertEqual(r.form_index_source, "default")
        self.assertEqual(r.form_index_resolved, {})


# ─── to_dict serialization ───────────────────────────────────────────────────


class ToDictSerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_compute_ability_dps_carries_source(self) -> None:
        r = compute_ability_dps(
            self.snap, "Hwei", level=11, mode="SR", target_mr=30.0,
        )
        d = r.to_dict()
        self.assertEqual(d["form_index_source"], "champion")
        self.assertEqual(d["form_index_resolved"], {"Q": 1, "W": 3, "E": 1})

    def test_compute_burst_carries_source(self) -> None:
        r = compute_burst_damage(
            self.snap, "Nidalee", level=11, target_armor=80,
        )
        d = r.to_dict()
        self.assertEqual(d["form_index_source"], "champion")
        self.assertEqual(d["form_index_resolved"], {"Q": 1, "W": 1, "E": 1})

    def test_rank_mage_carries_source(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Nidalee", level=11, mode="SR",
            target_mr=30.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["form_index_source"], "champion")
        self.assertEqual(d["form_index_resolved"], {"Q": 1, "W": 1, "E": 1})

    def test_rank_assassin_carries_source(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Nidalee", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=2,
        )
        d = r.to_dict()
        self.assertEqual(d["form_index_source"], "champion")


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

    def test_ability_dps_champion_source(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Hwei", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["form_index_source"], "champion")
        self.assertEqual(r["form_index_resolved"], {"Q": 1, "W": 3, "E": 1})

    def test_ability_dps_default_source(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Veigar", "level": 11, "mode": "SR", "target_mr": 30.0,
        })
        self.assertEqual(r["form_index_source"], "default")
        self.assertEqual(r["form_index_resolved"], {})

    def test_ability_dps_explicit_override(self) -> None:
        r = self._post("/ability-dps", {
            "champion": "Nidalee", "level": 11, "mode": "SR", "target_mr": 30.0,
            "form_index": {"Q": 0},
        })
        self.assertEqual(r["form_index_source"], "override")
        self.assertEqual(r["form_index_resolved"], {"Q": 0, "W": 1, "E": 1})

    def test_rank_assassin_champion_source(self) -> None:
        r = self._post("/rank-assassin", {
            "champion": "Nidalee", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30.0, "top": 3,
        })
        self.assertEqual(r["form_index_source"], "champion")


if __name__ == "__main__":
    unittest.main()
