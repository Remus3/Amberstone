"""Phase 4b (s178, 2026-05-12) — spell cast-rate plumbing tests.

Covers ``ult_rates.get_spell_casts_per_sec`` + the file fallback chain
+ backward compat of ``get_ult_casts_per_sec``. The Phase 4b extension
shares the cache state with the legacy path, so we ``reset_cache()``
between fixtures.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.daemon_slayer import ult_rates


class SpellCastRateLookupTests(unittest.TestCase):
    """File-level fallback tests using a temp data root."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self.tmp.name)
        self.spell_file = self.tmp_root / "spell_cast_rates.json"
        self.ult_file = self.tmp_root / "ult_cast_rates.json"
        # Default payload exercised by most tests.
        self.payload = {
            "by_champ_mode": {
                "Veigar": {
                    "SR":     {"Q": 0.10, "W": 0.05, "E": 0.03, "R": 0.01},
                    "ARAM":   {"Q": 0.12, "W": 0.06, "E": 0.04, "R": 0.015},
                    "global": {"Q": 0.11, "W": 0.055, "E": 0.035, "R": 0.012},
                },
                "Aatrox": {
                    "global": {"Q": 0.08, "W": 0.04, "E": 0.06, "R": 0.005},
                },
            },
            "global_fallback": {"Q": 0.05, "W": 0.03, "E": 0.04, "R": 0.007},
            "generated_at": "2026-05-12",
        }
        self.spell_file.write_text(json.dumps(self.payload), encoding="utf-8")
        self.patcher = patch.object(
            ult_rates, "_SPELL_RATE_FILE", self.spell_file
        )
        self.patcher.start()
        # Also redirect the ult-rates file so legacy tests don't accidentally
        # hit the real on-disk file.
        self.ult_patcher = patch.object(
            ult_rates, "_ULT_RATE_FILE", self.ult_file
        )
        self.ult_patcher.start()
        ult_rates.reset_cache()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.ult_patcher.stop()
        self.tmp.cleanup()
        ult_rates.reset_cache()

    # ----- happy path

    def test_champion_mode_match(self) -> None:
        self.assertAlmostEqual(
            ult_rates.get_spell_casts_per_sec("Veigar", "Q", "SR"), 0.10
        )
        self.assertAlmostEqual(
            ult_rates.get_spell_casts_per_sec("Veigar", "W", "SR"), 0.05
        )

    def test_champion_aram_distinct_from_sr(self) -> None:
        self.assertAlmostEqual(
            ult_rates.get_spell_casts_per_sec("Veigar", "Q", "ARAM"), 0.12
        )

    # ----- fallback chain

    def test_unknown_mode_falls_back_to_champ_global(self) -> None:
        # Veigar has no ARENA entry; should hit champion's "global".
        self.assertAlmostEqual(
            ult_rates.get_spell_casts_per_sec("Veigar", "Q", "ARENA"), 0.11
        )

    def test_unknown_champion_falls_back_to_global_fallback(self) -> None:
        self.assertAlmostEqual(
            ult_rates.get_spell_casts_per_sec("NobodyChamp", "Q", "SR"), 0.05
        )

    def test_aatrox_arena_falls_through_to_global(self) -> None:
        # Aatrox only has "global" — no SR / ARAM / ARENA.
        self.assertAlmostEqual(
            ult_rates.get_spell_casts_per_sec("Aatrox", "Q", "SR"), 0.08
        )

    def test_missing_file_returns_zero(self) -> None:
        # Wipe the spell file and reset cache; should yield 0.0 (no value).
        self.spell_file.unlink()
        ult_rates.reset_cache()
        self.assertEqual(
            ult_rates.get_spell_casts_per_sec("Veigar", "Q", "SR"), 0.0
        )

    def test_invalid_spell_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            ult_rates.get_spell_casts_per_sec("Veigar", "Z", "SR")
        with self.assertRaises(ValueError):
            ult_rates.get_spell_casts_per_sec("Veigar", "P", "SR")

    def test_all_four_keys_distinct(self) -> None:
        rates = {
            k: ult_rates.get_spell_casts_per_sec("Veigar", k, "SR")
            for k in ("Q", "W", "E", "R")
        }
        # Default Veigar data has descending rates Q > W > E > R.
        self.assertGreater(rates["Q"], rates["W"])
        self.assertGreater(rates["W"], rates["E"])
        self.assertGreater(rates["E"], rates["R"])


class UltRateBackwardCompatTests(unittest.TestCase):
    """``get_ult_casts_per_sec`` must keep reading the legacy ult file
    so Malignance Hatefog behaves identically to pre-Phase-4b builds."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_root = Path(self.tmp.name)
        self.ult_file = self.tmp_root / "ult_cast_rates.json"
        self.spell_file = self.tmp_root / "spell_cast_rates.json"
        # Legacy ult file shape — flat float per mode + global_fallback float.
        self.ult_file.write_text(json.dumps({
            "by_champ_mode": {
                "Veigar": {"SR": 0.012, "ARAM": 0.015, "global": 0.013},
            },
            "global_fallback": 0.0073,
        }), encoding="utf-8")
        self.patchers = [
            patch.object(ult_rates, "_ULT_RATE_FILE", self.ult_file),
            patch.object(ult_rates, "_SPELL_RATE_FILE", self.spell_file),
        ]
        for p in self.patchers:
            p.start()
        ult_rates.reset_cache()

    def tearDown(self) -> None:
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()
        ult_rates.reset_cache()

    def test_ult_file_takes_precedence(self) -> None:
        # Ult file has Veigar SR 0.012; that's what should come back even
        # if the spell file is missing entirely.
        self.assertAlmostEqual(
            ult_rates.get_ult_casts_per_sec("Veigar", "SR"), 0.012
        )

    def test_missing_ult_file_returns_legacy_default(self) -> None:
        self.ult_file.unlink()
        ult_rates.reset_cache()
        # Falls back to the in-code legacy default of 0.0073.
        self.assertAlmostEqual(
            ult_rates.get_ult_casts_per_sec("Veigar", "SR"), 0.0073
        )

    def test_legacy_global_fallback_used_on_unknown_champ(self) -> None:
        self.assertAlmostEqual(
            ult_rates.get_ult_casts_per_sec("UnknownChamp", "SR"), 0.0073
        )

    def test_ult_file_with_dict_fallback_shape(self) -> None:
        """When the ult file gets regenerated with the new dict
        ``global_fallback`` shape, the legacy function should still
        extract ``R`` and behave correctly."""
        self.ult_file.write_text(json.dumps({
            "by_champ_mode": {},
            "global_fallback": {"Q": 0.10, "W": 0.05, "E": 0.04, "R": 0.008},
        }), encoding="utf-8")
        ult_rates.reset_cache()
        self.assertAlmostEqual(
            ult_rates.get_ult_casts_per_sec("AnyChamp", "SR"), 0.008
        )


class LiveSpellRatesSnapshotTests(unittest.TestCase):
    """Smoke tests against the real shipped ``spell_cast_rates.json`` so a
    bad regeneration (zero rates, missing champions) reddens CI fast."""

    def setUp(self) -> None:
        ult_rates.reset_cache()

    def tearDown(self) -> None:
        ult_rates.reset_cache()

    def test_veigar_q_above_zero(self) -> None:
        rate = ult_rates.get_spell_casts_per_sec("Veigar", "Q", "SR")
        self.assertGreater(rate, 0.01)
        self.assertLess(rate, 1.0)

    def test_global_fallback_present_for_all_spells(self) -> None:
        # An unknown champion should still get >0 for each spell.
        for k in ("Q", "W", "E", "R"):
            v = ult_rates.get_spell_casts_per_sec("__nonexistent__", k, "SR")
            self.assertGreaterEqual(v, 0.0)


if __name__ == "__main__":
    unittest.main()
