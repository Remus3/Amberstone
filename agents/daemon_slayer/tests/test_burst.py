"""Phase 5 (s180, 2026-05-13) — Assassin burst-window evaluator tests.

Coverage split into eight groups:

* ``ComboTokenTests`` — token normalization + validation.
* ``ComboSequenceValidationTests`` — sequence-level parsing.
* ``ComputeBurstDamageBasicsTests`` — type / metadata sanity.
* ``BurstScoringTests`` — end-to-end on Zed / Diana / Talon / Akali.
* ``AmpFlowThroughTests`` — Rabadon / Liandry / Abyssal Mask flow through.
* ``ModeMultiplierTests`` — ARAM damage modifier on per-cast.
* ``EdgeCaseTests`` — missing snapshot / unknown champion / locked spells.
* ``BurstRouteTests`` — POST /burst happy path + errors.
"""
from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import (
    DEFAULT_COMBO_SEQUENCE,
    BurstResult,
    ComboCast,
    _normalize_combo_token,
    _validate_combo_sequence,
    compute_burst_damage,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── token normalization ─────────────────────────────────────────────────────


class ComboTokenTests(unittest.TestCase):
    def test_aa_token_uppercase(self) -> None:
        canon, key, is_ability = _normalize_combo_token("AA")
        self.assertEqual(canon, "AA")
        self.assertEqual(key, "")
        self.assertFalse(is_ability)

    def test_aa_token_lowercase(self) -> None:
        canon, key, is_ability = _normalize_combo_token("aa")
        self.assertEqual(canon, "AA")
        self.assertEqual(key, "")
        self.assertFalse(is_ability)

    def test_q_token_basic(self) -> None:
        canon, key, is_ability = _normalize_combo_token("Q")
        self.assertEqual(canon, "Q")
        self.assertEqual(key, "Q")
        self.assertTrue(is_ability)

    def test_q2_repeat_resolves_to_q(self) -> None:
        canon, key, is_ability = _normalize_combo_token("Q2")
        self.assertEqual(canon, "Q2")
        self.assertEqual(key, "Q")
        self.assertTrue(is_ability)

    def test_r_token_basic(self) -> None:
        canon, key, is_ability = _normalize_combo_token("R")
        self.assertEqual(canon, "R")
        self.assertEqual(key, "R")
        self.assertTrue(is_ability)

    def test_w_e_p_tokens(self) -> None:
        for k in ("P", "W", "E"):
            canon, key, is_ability = _normalize_combo_token(k)
            self.assertEqual(canon, k)
            self.assertEqual(key, k)
            self.assertTrue(is_ability)

    def test_unknown_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_combo_token("X")

    def test_empty_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_combo_token("")

    def test_bogus_suffix_raises(self) -> None:
        # "Q9" — 9 isn't a valid repeat suffix (only 2/3/4).
        with self.assertRaises(ValueError):
            _normalize_combo_token("Q9")

    def test_lowercase_q2_works(self) -> None:
        canon, key, _ = _normalize_combo_token("q2")
        self.assertEqual(canon, "Q2")
        self.assertEqual(key, "Q")


class ComboSequenceValidationTests(unittest.TestCase):
    def test_default_sequence(self) -> None:
        norm = _validate_combo_sequence(DEFAULT_COMBO_SEQUENCE)
        self.assertEqual(norm, ("Q", "W", "E", "AA", "R", "AA"))

    def test_custom_sequence_normalizes_case(self) -> None:
        norm = _validate_combo_sequence(["q", "aa", "r"])
        self.assertEqual(norm, ("Q", "AA", "R"))

    def test_empty_sequence_raises(self) -> None:
        with self.assertRaises(ValueError):
            _validate_combo_sequence([])

    def test_invalid_token_in_sequence_raises(self) -> None:
        with self.assertRaises(ValueError):
            _validate_combo_sequence(["Q", "BAD", "AA"])

    def test_repeat_tokens_allowed(self) -> None:
        norm = _validate_combo_sequence(["Q", "AA", "R", "Q2", "AA"])
        self.assertEqual(norm, ("Q", "AA", "R", "Q2", "AA"))


# ─── compute_burst_damage basics ─────────────────────────────────────────────


class ComputeBurstDamageBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_returns_burst_result(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11, mode="SR")
        self.assertIsInstance(r, BurstResult)
        self.assertEqual(r.champion_id, "Zed")
        self.assertEqual(r.level, 11)
        self.assertEqual(r.mode, "SR")

    def test_default_combo_sequence_applied(self) -> None:
        # Phase 5.5 (s186): Zed has an override (Q-W-E-R-Q2-AA via shadow Q
        # double-cast). The engine resolver fires when combo_sequence=None.
        r = compute_burst_damage(self.snap, "Zed", level=11)
        self.assertEqual(r.combo_sequence, ("Q", "W", "E", "R", "Q2", "AA"))
        self.assertEqual(r.combo_sequence_source, "champion")
        # Engine default (Q-W-E-AA-R-AA) still applies for champions without
        # an override entry — verified separately in test_max_priority_overrides.

    def test_per_cast_one_row_per_token(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11)
        self.assertEqual(len(r.per_cast), len(r.combo_sequence))

    def test_total_equals_sum_of_per_cast(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        cast_sum = sum(c.final_damage for c in r.per_cast)
        self.assertAlmostEqual(r.total_burst_damage, cast_sum, places=4)

    def test_split_ability_vs_aa(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        ability_sum = sum(c.final_damage for c in r.per_cast if c.is_ability)
        aa_sum = sum(c.final_damage for c in r.per_cast if not c.is_ability)
        self.assertAlmostEqual(r.ability_damage, ability_sum, places=4)
        self.assertAlmostEqual(r.auto_attack_damage, aa_sum, places=4)

    def test_burst_positive(self) -> None:
        # Naked Zed at lvl 11 should still produce > 0 burst from Q+E+R+AAs.
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        self.assertGreater(r.total_burst_damage, 0.0)

    def test_invalid_block_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_burst_damage(self.snap, "Zed", level=11, block_strategy="bogus")

    def test_invalid_max_priority_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_burst_damage(self.snap, "Zed", level=11,
                                 max_priority=("Q", "Q", "E"))

    def test_invalid_current_hp_pct_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_burst_damage(self.snap, "Zed", level=11,
                                 target_current_hp_pct=1.5)

    def test_invalid_combo_sequence_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_burst_damage(self.snap, "Zed", level=11,
                                 combo_sequence=["Q", "NOTOKEN"])


# ─── per-champion scoring sanity ─────────────────────────────────────────────


class BurstScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_zed_primary_ad(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        self.assertEqual(r.primary_scaling, "AD")

    def test_diana_primary_ap(self) -> None:
        r = compute_burst_damage(self.snap, "Diana", level=11, target_mr=30)
        self.assertEqual(r.primary_scaling, "AP")

    def test_zed_ult_contributes(self) -> None:
        # R at lvl 11 should have rank 1 and produce damage.
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        r_cast = next(c for c in r.per_cast if c.token == "R")
        self.assertEqual(r_cast.rank, 1)
        self.assertGreater(r_cast.raw_damage, 0)

    def test_pre_lvl_6_r_locked(self) -> None:
        # R locked at lvl 5 — that cast should be 0 damage with a "locked" note.
        r = compute_burst_damage(self.snap, "Zed", level=5, target_armor=40)
        r_cast = next(c for c in r.per_cast if c.token == "R")
        self.assertEqual(r_cast.rank, -1)
        self.assertEqual(r_cast.final_damage, 0.0)

    def test_aa_uses_compute_dps_per_hit(self) -> None:
        # AA contribution should be > 0 at lvl 11 (Zed has AD at level). Pin
        # the combo so this test stays decoupled from the per-champion
        # override registry — Zed's registry combo includes one AA.
        r = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
            combo_sequence=("Q", "W", "E", "AA", "R", "AA"),
        )
        aa_count = sum(1 for c in r.per_cast if c.token == "AA")
        self.assertEqual(aa_count, 2)
        per_aa = next(c for c in r.per_cast if c.token == "AA")
        self.assertGreater(per_aa.final_damage, 0)

    def test_higher_target_armor_reduces_zed_burst(self) -> None:
        low = compute_burst_damage(self.snap, "Zed", level=11, target_armor=40)
        high = compute_burst_damage(self.snap, "Zed", level=11, target_armor=200)
        self.assertGreater(low.total_burst_damage, high.total_burst_damage)

    def test_higher_target_mr_reduces_diana_burst(self) -> None:
        low = compute_burst_damage(self.snap, "Diana", level=11, target_mr=30)
        high = compute_burst_damage(self.snap, "Diana", level=11, target_mr=200)
        self.assertGreater(low.total_burst_damage, high.total_burst_damage)

    def test_lethality_helps_zed(self) -> None:
        # Adding Youmuu's Ghostblade (3142, lethality=18) vs same build w/o.
        naked = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_mr=30,
        )
        lethal = compute_burst_damage(
            self.snap, "Zed", level=11, item_ids=["3142"],
            target_armor=80, target_mr=30,
        )
        self.assertGreater(lethal.total_burst_damage, naked.total_burst_damage)
        # And armor-after-pen should be lower with lethality.
        self.assertLess(lethal.target_armor_after_pen, naked.target_armor_after_pen)

    def test_custom_combo_q2_repeat_doubles_q_contribution(self) -> None:
        # Zed Q hits at rank 4 lvl 11. Q+Q2 should double the Q contribution
        # vs Q alone (single block, no per-cast cooldown gating).
        single = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
            combo_sequence=["Q"],
        )
        doubled = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80,
            combo_sequence=["Q", "Q2"],
        )
        self.assertAlmostEqual(
            doubled.total_burst_damage,
            2.0 * single.total_burst_damage,
            places=2,
        )


# ─── amp flow-through ────────────────────────────────────────────────────────


class AmpFlowThroughTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_rabadons_lifts_diana_burst(self) -> None:
        # Rabadon's Deathcap (3089) — 30% AP amp + 130 raw AP.
        naked = compute_burst_damage(
            self.snap, "Diana", level=11, target_mr=30,
        )
        rab = compute_burst_damage(
            self.snap, "Diana", level=11, item_ids=["3089"], target_mr=30,
        )
        self.assertGreater(rab.total_burst_damage, naked.total_burst_damage)
        # And the ap_amp note should be present.
        self.assertTrue(any("AP amplified" in n for n in rab.notes))

    def test_liandrys_damage_amp_applies(self) -> None:
        # Liandry's Torment (6653) — damage_amp_pct=0.06 + 80 AP.
        naked = compute_burst_damage(
            self.snap, "Diana", level=11, target_mr=30, target_max_hp=2000,
        )
        liandry = compute_burst_damage(
            self.snap, "Diana", level=11, item_ids=["6653"],
            target_mr=30, target_max_hp=2000,
        )
        self.assertGreater(liandry.total_burst_damage, naked.total_burst_damage)

    def test_abyssal_mask_magic_amp_only_on_magic(self) -> None:
        # Abyssal Mask (8020) — magic_amp_pct=0.12. Zed (PHYSICAL) shouldn't
        # benefit; Diana (MAGIC) should. Test the directional asymmetry.
        zed_naked = compute_burst_damage(
            self.snap, "Zed", level=11, target_armor=80, target_mr=30,
        )
        zed_abyssal = compute_burst_damage(
            self.snap, "Zed", level=11, item_ids=["8020"],
            target_armor=80, target_mr=30,
        )
        # Zed: abyssal contributes only stats (HP/MR), the magic_amp doesn't
        # apply to PHYSICAL casts. Some lift from HP scaling on R is possible
        # but should be small relative to a 12% magic amp on Diana.
        diana_naked = compute_burst_damage(
            self.snap, "Diana", level=11, target_armor=80, target_mr=30,
        )
        diana_abyssal = compute_burst_damage(
            self.snap, "Diana", level=11, item_ids=["8020"],
            target_armor=80, target_mr=30,
        )
        zed_lift_pct = (zed_abyssal.total_burst_damage - zed_naked.total_burst_damage) / max(1.0, zed_naked.total_burst_damage)
        diana_lift_pct = (diana_abyssal.total_burst_damage - diana_naked.total_burst_damage) / max(1.0, diana_naked.total_burst_damage)
        # Diana gets the magic amp ×1.12 multiplicatively + 50 MR for survival.
        # Zed gets stats only — much smaller lift.
        self.assertGreater(diana_lift_pct, zed_lift_pct)


# ─── mode multiplier ─────────────────────────────────────────────────────────


class ModeMultiplierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_sr_mode_multiplier_exactly_1(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11, mode="SR",
                                 target_armor=80)
        self.assertEqual(r.mode_multiplier, 1.0)

    def test_aram_mode_multiplier_lifts_zed(self) -> None:
        # Zed has aramDamageDealt > 1.0 per current ARAM rebalance —
        # the engine surfaces the modifier verbatim from the snapshot.
        r = compute_burst_damage(self.snap, "Zed", level=11, mode="ARAM",
                                 target_armor=80)
        self.assertGreater(r.mode_multiplier, 1.0)

    def test_aram_mode_multiplier_nerfs_veigar(self) -> None:
        # Veigar has aramDamageDealt < 1.0 — sanity-check the nerf side.
        r = compute_burst_damage(self.snap, "Veigar", level=11, mode="ARAM",
                                 target_mr=30)
        self.assertLess(r.mode_multiplier, 1.0)

    def test_aram_ratio_matches_mode_multiplier(self) -> None:
        # Ability damage in ARAM divided by SR should equal mode_multiplier
        # (per-cast damage scales linearly via mode_mult before mitigation).
        sr = compute_burst_damage(self.snap, "Zed", level=11, mode="SR",
                                  target_armor=80, target_mr=30)
        aram = compute_burst_damage(self.snap, "Zed", level=11, mode="ARAM",
                                    target_armor=80, target_mr=30)
        self.assertGreater(sr.ability_damage, 0.0)
        ratio = aram.ability_damage / sr.ability_damage
        self.assertAlmostEqual(ratio, aram.mode_multiplier, places=3)


# ─── edge cases ─────────────────────────────────────────────────────────────


class EdgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_unknown_champion_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            compute_burst_damage(self.snap, "NotARealChampion", level=11)

    def test_aa_only_combo_returns_only_aa(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11,
                                 target_armor=80,
                                 combo_sequence=["AA", "AA", "AA"])
        self.assertEqual(r.ability_damage, 0.0)
        self.assertGreater(r.auto_attack_damage, 0.0)
        self.assertEqual(len(r.per_cast), 3)
        for c in r.per_cast:
            self.assertFalse(c.is_ability)

    def test_w_with_no_damage_blocks_yields_zero(self) -> None:
        # Zed.W = "Living Shadow" has no damage_blocks of kind "damage"
        # (it's a clone-repositioning ability). Should register 0 damage.
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        w_cast = next(c for c in r.per_cast if c.token == "W")
        self.assertEqual(w_cast.raw_damage, 0.0)
        self.assertEqual(w_cast.final_damage, 0.0)

    def test_to_dict_round_trip(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Zed")
        self.assertEqual(d["level"], 11)
        self.assertIn("total_burst_damage", d)
        self.assertIn("ability_damage", d)
        self.assertIn("auto_attack_damage", d)
        self.assertIn("per_cast", d)
        self.assertEqual(len(d["per_cast"]), 6)
        # Per-cast row shape:
        for k in ("token", "is_ability", "ability_key", "rank",
                  "raw_damage", "final_damage"):
            self.assertIn(k, d["per_cast"][0])

    def test_format_table_includes_assassin_tag(self) -> None:
        r = compute_burst_damage(self.snap, "Zed", level=11, target_armor=80)
        out = r.format_table()
        self.assertIn("[ASSASSIN]", out)
        self.assertIn("Zed", out)
        self.assertIn("total_burst_damage", out)


# ─── server route ────────────────────────────────────────────────────────────


class BurstRouteTests(unittest.TestCase):
    """Spin the engine server on a free port; hit /burst; tear down."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.server import start_server, _CACHE
        reset_default_cache()
        ult_rates.reset_cache()
        cls.snap = _snap()
        _CACHE.set(cls.snap)
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=cls.snap)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        raw = json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=raw, method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            try:
                code = getattr(e, "code", None)
                body_resp = json.loads(e.read().decode("utf-8"))  # type: ignore[attr-defined]
                return code, body_resp
            except Exception:
                raise

    def test_post_burst_returns_200(self) -> None:
        status, body = self._post("/burst", {
            "champion": "Zed", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Zed")
        self.assertIn("total_burst_damage", body)
        self.assertIn("ability_damage", body)
        self.assertIn("auto_attack_damage", body)
        self.assertGreater(body["total_burst_damage"], 0.0)

    def test_burst_custom_combo_dash_separated(self) -> None:
        status, body = self._post("/burst", {
            "champion": "Talon", "level": 11, "mode": "SR",
            "combo_sequence": "W-Q-AA-R-AA-AA",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["combo_sequence"],
                         ["W", "Q", "AA", "R", "AA", "AA"])

    def test_burst_custom_combo_list(self) -> None:
        status, body = self._post("/burst", {
            "champion": "Akali", "level": 11, "mode": "SR",
            "combo_sequence": ["E", "Q", "AA", "R", "Q2", "AA"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["combo_sequence"],
                         ["E", "Q", "AA", "R", "Q2", "AA"])

    def test_burst_404_on_unknown_champion(self) -> None:
        status, _ = self._post("/burst", {
            "champion": "NobodyChampion", "level": 11,
        })
        self.assertEqual(status, 404)

    def test_burst_422_on_invalid_max_priority(self) -> None:
        status, _ = self._post("/burst", {
            "champion": "Zed", "level": 11,
            "max_priority": "QQE",
        })
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()
