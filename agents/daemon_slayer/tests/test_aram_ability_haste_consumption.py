"""ENGINE 1.23.0 (2026-05-20) - aramAbilityHaste CONSUMPTION + aramTenacity forward.

Sibling of ``test_engine.py::AramAbilityHasteExposureTests`` which proves
that the engine EXPOSES the two keys; this file proves that
``compute_ability_dps`` CONSUMES the aramAbilityHaste delta to shorten
effective ability cooldowns via Riot's canonical haste formula
``eff_cd = base_cd / (1 + total_ah / 100)``.

Coverage:

* ``HasteFormulaTests`` - the pure helper math (positive / negative /
  zero / extreme deltas).
* ``TotalAbilityHasteTests`` - mode-gated composition (SR strips the
  ARAM delta even if present in the scaled stats dict; ARAM folds it).
* ``EffectiveCooldownConsumptionTests`` - end-to-end on live snapshot
  champions with known aramAbilityHaste values (Soraka +10, Azir +20,
  Seraphine -20, Teemo -15, Veigar 0 baseline) - per-spell
  ``cooldown`` is the effective post-haste value, ``base_cooldown``
  is the pre-haste rank value.
* ``ResultTenacityForwardTests`` - the aram_tenacity_mult marker is
  forwarded into the result top-level so a future EHP-side enemy-CC
  consumer can read it without re-resolving the champion (the
  consumption itself is intentionally NOT built in this slice; see
  the TODO at module top of ``ability_dps.py``).
* ``BackwardCompatTests`` - SR mode with no haste sources leaves
  per-spell cooldown identical to the pre-1.23 base behavior.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.ability_dps import (
    _effective_ability_cd,
    _total_ability_haste,
    compute_ability_dps,
)
from agents.daemon_slayer.data_loader import DataSnapshot


# --- haste formula helper ---------------------------------------------------


class HasteFormulaTests(unittest.TestCase):
    """Pin Riot's canonical haste formula identity + edge cases."""

    def test_zero_haste_returns_base(self) -> None:
        self.assertEqual(_effective_ability_cd(6.0, 0.0), 6.0)

    def test_positive_haste_shortens_cd(self) -> None:
        # +10 AH on a 6.0s spell: 6.0 / 1.10 = 5.454545...
        self.assertAlmostEqual(_effective_ability_cd(6.0, 10.0), 6.0 / 1.10)

    def test_haste_20_on_6s_spell(self) -> None:
        # +20 AH on a 6.0s spell: 6.0 / 1.20 = 5.0 exactly.
        self.assertAlmostEqual(_effective_ability_cd(6.0, 20.0), 5.0)

    def test_negative_haste_lengthens_cd(self) -> None:
        # -20 AH on a 6.0s spell: 6.0 / 0.80 = 7.5 exactly.
        self.assertAlmostEqual(_effective_ability_cd(6.0, -20.0), 7.5)

    def test_negative_haste_minus_15(self) -> None:
        # -15 AH on a 6.0s spell: 6.0 / 0.85 = 7.0588...
        self.assertAlmostEqual(_effective_ability_cd(6.0, -15.0), 6.0 / 0.85)

    def test_zero_base_returns_zero(self) -> None:
        # A 0-base CD spell stays at 0 regardless of haste (locked, etc.).
        self.assertEqual(_effective_ability_cd(0.0, 50.0), 0.0)

    def test_extreme_negative_does_not_invert(self) -> None:
        # Cap-protection: haste <= -100 would otherwise divide by zero or
        # invert the formula. The helper clamps the denominator floor to
        # an arbitrarily small positive epsilon so the result is finite +
        # increasing as haste -> -100.
        result = _effective_ability_cd(6.0, -99.0)
        self.assertGreater(result, 6.0 / 0.02)  # 0.01 floor -> >= 600
        # Pass through -100 and below without crashing.
        result_extreme = _effective_ability_cd(6.0, -150.0)
        self.assertGreater(result_extreme, 0.0)


# --- total ability haste composition ----------------------------------------


class TotalAbilityHasteTests(unittest.TestCase):
    """Mode-gated read of the engine-exposed aram_ability_haste delta."""

    def test_aram_mode_folds_aram_ah(self) -> None:
        scaled = {"aram_ability_haste": 10.0}
        self.assertEqual(_total_ability_haste(scaled, mode="ARAM"), 10.0)

    def test_aram_mode_folds_negative_aram_ah(self) -> None:
        scaled = {"aram_ability_haste": -20.0}
        self.assertEqual(_total_ability_haste(scaled, mode="ARAM"), -20.0)

    def test_sr_mode_strips_aram_ah_even_if_present(self) -> None:
        # The exposure module already strips it in SR, but the consumer
        # MUST also defensively gate on mode in case a caller mutates the
        # dict between resolve + consume.
        scaled = {"aram_ability_haste": 10.0}
        self.assertEqual(_total_ability_haste(scaled, mode="SR"), 0.0)

    def test_missing_key_defaults_to_zero(self) -> None:
        self.assertEqual(_total_ability_haste({}, mode="ARAM"), 0.0)
        self.assertEqual(_total_ability_haste({}, mode="SR"), 0.0)

    def test_arena_mode_strips_aram_ah(self) -> None:
        # Only "ARAM" folds the delta; ARENA / CHERRY / other modes don't.
        scaled = {"aram_ability_haste": 10.0}
        self.assertEqual(_total_ability_haste(scaled, mode="ARENA"), 0.0)
        self.assertEqual(_total_ability_haste(scaled, mode="CHERRY"), 0.0)


# --- end-to-end CD consumption ----------------------------------------------


class EffectiveCooldownConsumptionTests(unittest.TestCase):
    """``compute_ability_dps`` shrinks per-spell cooldown via the haste
    formula when the engine exposes a non-zero aram_ability_haste."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _spell(self, champion: str, key: str, level: int, mode: str):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=[], mode=mode,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_soraka_q_aram_cd_shortened(self) -> None:
        # Soraka aramAbilityHaste = +10. Q cd table is [8, 7, 6, 5, 4];
        # at level 5 rank is 2 -> base cd = 6.0. Expected effective:
        # 6.0 / 1.10 = 5.4545...
        s = self._spell("Soraka", "Q", level=5, mode="ARAM")
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.base_cooldown, 6.0, places=4)
        self.assertAlmostEqual(s.cooldown, 6.0 / 1.10, places=4)
        self.assertAlmostEqual(s.total_ability_haste, 10.0, places=4)

    def test_soraka_q_sr_cd_unchanged(self) -> None:
        # SR mode strips the ARAM delta -> identity preserved.
        s = self._spell("Soraka", "Q", level=5, mode="SR")
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.base_cooldown, 6.0, places=4)
        self.assertAlmostEqual(s.cooldown, 6.0, places=4)
        self.assertAlmostEqual(s.total_ability_haste, 0.0, places=4)

    def test_azir_e_aram_cd_shortened(self) -> None:
        # Azir aramAbilityHaste = +20. E base cd at lvl11 (some rank) = 22.0.
        # Expected effective: 22.0 / 1.20 = 18.3333...
        s = self._spell("Azir", "E", level=11, mode="ARAM")
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.base_cooldown, 22.0, places=4)
        self.assertAlmostEqual(s.cooldown, 22.0 / 1.20, places=4)
        self.assertAlmostEqual(s.total_ability_haste, 20.0, places=4)

    def test_seraphine_q_aram_cd_lengthened(self) -> None:
        # Seraphine aramAbilityHaste = -20. Q base cd @ lvl1 = 12.0
        # (depending on rank). Expected effective: base / 0.80 (longer).
        s = self._spell("Seraphine", "Q", level=1, mode="ARAM")
        self.assertIsNotNone(s)
        # eff_cd > base_cd when haste < 0.
        self.assertGreater(s.cooldown, s.base_cooldown)
        # Formula match.
        self.assertAlmostEqual(s.cooldown, s.base_cooldown / 0.80, places=4)
        self.assertAlmostEqual(s.total_ability_haste, -20.0, places=4)

    def test_teemo_q_aram_cd_lengthened(self) -> None:
        # Teemo aramAbilityHaste = -15.
        s = self._spell("Teemo", "Q", level=1, mode="ARAM")
        self.assertIsNotNone(s)
        self.assertGreater(s.cooldown, s.base_cooldown)
        self.assertAlmostEqual(s.cooldown, s.base_cooldown / 0.85, places=4)
        self.assertAlmostEqual(s.total_ability_haste, -15.0, places=4)

    def test_veigar_aram_zero_haste_identity(self) -> None:
        # Veigar carries aramAbilityHaste = 0 (default). Q base @ lvl 11
        # rank 4 = 4.0 (5 ranks descending). Effective unchanged.
        s = self._spell("Veigar", "Q", level=11, mode="ARAM")
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.cooldown, s.base_cooldown, places=4)
        self.assertAlmostEqual(s.total_ability_haste, 0.0, places=4)


# --- result-level forwarding for tenacity -----------------------------------


class ResultTenacityForwardTests(unittest.TestCase):
    """``AbilityDpsResult.aram_tenacity_mult`` is forwarded for future
    enemy-CC consumers. This slice does NOT build the CC model; it just
    plumbs the value through so the data lane is visible end-to-end."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_katarina_aram_tenacity_1_2(self) -> None:
        # Katarina aramTenacity = 1.20 in 16.10.1.
        out = compute_ability_dps(
            self.snap, "Katarina", level=11, item_ids=[], mode="ARAM",
        )
        self.assertAlmostEqual(out.aram_tenacity_mult, 1.20, places=4)

    def test_soraka_aram_tenacity_default_1_0(self) -> None:
        # Soraka has no aramTenacity entry -> default 1.0.
        out = compute_ability_dps(
            self.snap, "Soraka", level=11, item_ids=[], mode="ARAM",
        )
        self.assertAlmostEqual(out.aram_tenacity_mult, 1.0, places=4)

    def test_sr_mode_tenacity_is_1_0(self) -> None:
        # SR mode strips the ARAM-side mod -> default 1.0.
        out = compute_ability_dps(
            self.snap, "Katarina", level=11, item_ids=[], mode="SR",
        )
        self.assertAlmostEqual(out.aram_tenacity_mult, 1.0, places=4)

    def test_aram_ability_haste_forwarded_on_result(self) -> None:
        # The result top-level surfaces the haste delta the per-spell
        # CDs were shortened with.
        out = compute_ability_dps(
            self.snap, "Azir", level=11, item_ids=[], mode="ARAM",
        )
        self.assertAlmostEqual(out.aram_ability_haste, 20.0, places=4)

    def test_to_dict_carries_new_fields(self) -> None:
        # Round-trip through to_dict for downstream JSON consumers.
        out = compute_ability_dps(
            self.snap, "Soraka", level=6, item_ids=[], mode="ARAM",
        )
        d = out.to_dict()
        self.assertIn("aram_ability_haste", d)
        self.assertIn("aram_tenacity_mult", d)
        self.assertAlmostEqual(d["aram_ability_haste"], 10.0, places=4)
        self.assertAlmostEqual(d["aram_tenacity_mult"], 1.0, places=4)
        # Per-spell new fields too.
        q = next((s for s in d["per_spell"] if s["key"] == "Q"), None)
        self.assertIsNotNone(q)
        self.assertIn("base_cooldown", q)
        self.assertIn("total_ability_haste", q)


# --- backward-compat: SR-mode cooldowns unchanged ---------------------------


class BackwardCompatTests(unittest.TestCase):
    """SR-mode + no item AH source -> per-spell cooldown identical to
    pre-1.23 base value (the existing test_cooldown_inheritance.py suite
    must continue to pass; this re-asserts the contract here)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_riven_r_sr_base_cooldown_preserved(self) -> None:
        # Riven R form 0 cd=[120, 90, 60]; at lvl 11 rank 2 -> 90.0.
        out = compute_ability_dps(
            self.snap, "Riven", level=11, item_ids=[], mode="SR",
        )
        r = next((s for s in out.per_spell if s.key == "R"), None)
        self.assertIsNotNone(r)
        self.assertEqual(r.cooldown, 90.0)
        self.assertEqual(r.base_cooldown, 90.0)
        self.assertEqual(r.total_ability_haste, 0.0)

    def test_veigar_w_sr_base_cooldown_preserved(self) -> None:
        out = compute_ability_dps(
            self.snap, "Veigar", level=11, item_ids=[], mode="SR",
        )
        w = next((s for s in out.per_spell if s.key == "W"), None)
        self.assertIsNotNone(w)
        # base_cooldown match cooldown at SR.
        self.assertEqual(w.cooldown, w.base_cooldown)

    def test_qiyana_q_sr_flat_7s_preserved(self) -> None:
        # Qiyana Q form 1 inherits cd=[7,7,7,7,7]; flat 7s at any rank.
        out = compute_ability_dps(
            self.snap, "Qiyana", level=11, item_ids=[], mode="SR",
        )
        q = next((s for s in out.per_spell if s.key == "Q"), None)
        self.assertIsNotNone(q)
        self.assertEqual(q.cooldown, 7.0)
        self.assertEqual(q.base_cooldown, 7.0)


if __name__ == "__main__":
    unittest.main()
