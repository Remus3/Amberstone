"""Tests for core.draft_score - the five-layer deterministic draft score.

Two surfaces:
  * fuse_layers(...)          - the pure fusion math (DB-free). Bulk of the
                               correctness proof: clamp, weighting, trust,
                               confidence tiers, monotonicity.
  * compute_draft_score(...)  - assembles the 5 layers from owned primitives
                               (draft_elo_db corpus + injectable resolvers)
                               and calls fuse_layers. Tested for never-raises,
                               structure, resolver wiring, DB integration.

No data-fragile absolute-WR assertions - we assert on computed invariants
(bounds, ordering, contribution flags) not on specific corpus numbers.
"""
from __future__ import annotations

import sqlite3
import unittest

from core import draft_score
from core.draft_score import BAND_HI, BAND_LO, WEIGHTS, compute_draft_score, fuse_layers


def _layer(name, sub_score, n, weight=None):
    return {
        "name": name,
        "weight": WEIGHTS[name] if weight is None else weight,
        "sub_score": sub_score,
        "n": n,
    }


def _all_layers(sub_score, n):
    return [_layer(name, sub_score, n) for name in WEIGHTS]


class FuseLayersMathTest(unittest.TestCase):
    def test_all_neutral_scores_50(self):
        out = fuse_layers(_all_layers(0.5, 100))
        self.assertEqual(out["score"], 50.0)

    def test_no_contributing_layers_is_neutral_low(self):
        # every layer thin (n=0) or None -> nothing contributes.
        out = fuse_layers(_all_layers(None, 0))
        self.assertEqual(out["score"], 50.0)
        self.assertEqual(out["confidence"], "LOW")
        self.assertEqual(out["contributing"], 0)

    def test_score_always_within_band(self):
        for s in (0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0):
            out = fuse_layers(_all_layers(s, 500))
            self.assertGreaterEqual(out["score"], BAND_LO)
            self.assertLessEqual(out["score"], BAND_HI)

    def test_positive_edge_pushes_above_50(self):
        out = fuse_layers(_all_layers(0.6, 500))
        self.assertGreater(out["score"], 50.0)

    def test_negative_edge_pushes_below_50(self):
        out = fuse_layers(_all_layers(0.4, 500))
        self.assertLess(out["score"], 50.0)

    def test_extreme_positive_clamps_to_band_hi(self):
        out = fuse_layers(_all_layers(1.0, 5000))
        self.assertEqual(out["score"], BAND_HI)

    def test_extreme_negative_clamps_to_band_lo(self):
        out = fuse_layers(_all_layers(0.0, 5000))
        self.assertEqual(out["score"], BAND_LO)

    def test_monotonic_raising_a_layer_never_lowers_score(self):
        base = fuse_layers(_all_layers(0.5, 500))["score"]
        for name in WEIGHTS:
            layers = _all_layers(0.5, 500)
            for ly in layers:
                if ly["name"] == name:
                    ly["sub_score"] = 0.7
            self.assertGreaterEqual(fuse_layers(layers)["score"], base)

    def test_thin_layer_barely_moves_score(self):
        thin = fuse_layers([_layer("matchup", 1.0, 1)] +
                           [_layer(n, 0.5, 500) for n in WEIGHTS if n != "matchup"])
        thick = fuse_layers([_layer("matchup", 1.0, 5000)] +
                            [_layer(n, 0.5, 500) for n in WEIGHTS if n != "matchup"])
        # A high-evidence positive matchup layer moves the score more than a
        # one-game one.
        self.assertGreater(thick["score"] - 50.0, thin["score"] - 50.0)

    def test_confidence_high_on_dense_sample(self):
        out = fuse_layers(_all_layers(0.55, 5000))
        self.assertEqual(out["confidence"], "HIGH")

    def test_confidence_low_on_thin_sample(self):
        out = fuse_layers([_layer("base_wr", 0.55, 1)] +
                          [_layer(n, None, 0) for n in WEIGHTS if n != "base_wr"])
        self.assertEqual(out["confidence"], "LOW")

    def test_layer_contribution_flags(self):
        layers = [_layer("matchup", 0.6, 100),
                  _layer("synergy", None, 0),
                  _layer("damage_balance", 0.7, 5),
                  _layer("scaling", 0.5, 0),
                  _layer("base_wr", 0.52, 200)]
        out = fuse_layers(layers)
        flags = {ly["name"]: ly["contributed"] for ly in out["layers"]}
        self.assertTrue(flags["matchup"])
        self.assertFalse(flags["synergy"])
        self.assertTrue(flags["damage_balance"])
        self.assertFalse(flags["scaling"])  # n=0 -> not contributed
        self.assertTrue(flags["base_wr"])

    def test_band_reported(self):
        out = fuse_layers(_all_layers(0.5, 100))
        self.assertEqual(out["band"], [BAND_LO, BAND_HI])


class ComputeDraftScoreTest(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        build_fixture_db_in_memory(conn)
        return conn

    def test_never_raises_absent_db(self):
        # conn=None + a bogus path via env is exercised elsewhere; here pass a
        # conn that yields no rows to prove the empty path is well-formed.
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER)")
        conn.execute("CREATE TABLE participants (id INTEGER PRIMARY KEY, "
                     "match_id TEXT, champion_id INTEGER, win INTEGER, team_id INTEGER)")
        out = compute_draft_score([1, 2, 3, 4, 5], conn=conn)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["score"], BAND_LO)
        self.assertLessEqual(out["score"], BAND_HI)
        self.assertEqual(len(out["layers"]), 5)

    def test_never_raises_on_garbage_conn(self):
        out = compute_draft_score([1, 2, 3, 4, 5], conn="not a conn")
        self.assertTrue(out["ok"])
        self.assertEqual(out["score"], 50.0)

    def test_structure_keys(self):
        conn = self._conn()
        out = compute_draft_score([64, 22, 1, 2, 3], enemy_ids=[22, 64, 4, 5, 6], conn=conn)
        for k in ("ok", "score", "confidence", "band", "layers", "ally", "enemy"):
            self.assertIn(k, out)
        names = {ly["name"] for ly in out["layers"]}
        self.assertEqual(names, set(WEIGHTS))

    def test_score_bounded_with_real_fixture(self):
        conn = self._conn()
        out = compute_draft_score([64, 22, 1, 2, 3], enemy_ids=[7, 8, 9, 10, 11], conn=conn)
        self.assertGreaterEqual(out["score"], BAND_LO)
        self.assertLessEqual(out["score"], BAND_HI)

    def test_enemy_optional(self):
        conn = self._conn()
        out = compute_draft_score([64, 22, 1, 2, 3], conn=conn)
        self.assertTrue(out["ok"])
        # matchup layer cannot contribute without an enemy comp.
        mu = next(ly for ly in out["layers"] if ly["name"] == "matchup")
        self.assertFalse(mu["contributed"])

    def test_damage_balance_resolver_wiring(self):
        conn = self._conn()
        mono = compute_draft_score(
            [64, 22, 1, 2, 3], conn=conn,
            damage_class_resolver=lambda cid: "physical")
        balanced = compute_draft_score(
            [64, 22, 1, 2, 3], conn=conn,
            damage_class_resolver=lambda cid: "physical" if cid % 2 else "magical")
        db_mono = next(ly for ly in mono["layers"] if ly["name"] == "damage_balance")
        db_bal = next(ly for ly in balanced["layers"] if ly["name"] == "damage_balance")
        self.assertTrue(db_mono["contributed"])
        self.assertTrue(db_bal["contributed"])
        # a balanced comp scores the damage layer higher than a mono one.
        self.assertGreater(db_bal["sub_score"], db_mono["sub_score"])
        self.assertLess(db_mono["sub_score"], 0.5)

    def test_scaling_inert_by_default(self):
        conn = self._conn()
        out = compute_draft_score([64, 22, 1, 2, 3], conn=conn)
        sc = next(ly for ly in out["layers"] if ly["name"] == "scaling")
        self.assertFalse(sc["contributed"])

    def test_scaling_resolver_wiring(self):
        conn = self._conn()
        out = compute_draft_score(
            [64, 22, 1, 2, 3], conn=conn,
            scaling_resolver=lambda cid: 0.5)
        sc = next(ly for ly in out["layers"] if ly["name"] == "scaling")
        self.assertTrue(sc["contributed"])

    def test_duo_synergy_lookup_wiring(self):
        conn = self._conn()
        out = compute_draft_score(
            [64, 22, 1, 2, 3], conn=conn,
            champ_name_resolver=lambda cid: f"C{cid}",
            duo_synergy_lookup=lambda a, b: 0.9)
        self.assertTrue(out["ok"])

    def test_wrong_ally_length_returns_error_not_raise(self):
        out = compute_draft_score([1, 2], conn=self._conn())
        self.assertFalse(out["ok"])
        self.assertIn("error", out)


def build_fixture_db_in_memory(conn: sqlite3.Connection) -> None:
    """Reuse the draft-elo seed schema in an in-memory connection."""
    conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER)")
    conn.execute("CREATE TABLE participants (id INTEGER PRIMARY KEY, "
                 "match_id TEXT, champion_id INTEGER, win INTEGER, team_id INTEGER)")
    seed = (
        ("m1", 420, ((64, 100, 1), (22, 100, 1))),
        ("m2", 420, ((64, 100, 0), (22, 200, 1))),
        ("m3", 400, ((64, 200, 1),)),
    )
    pid = 1
    for match_id, queue_id, parts in seed:
        conn.execute("INSERT INTO matches (match_id, queue_id) VALUES (?, ?)",
                     (match_id, queue_id))
        for champ, team, win in parts:
            conn.execute("INSERT INTO participants (id, match_id, champion_id, "
                         "win, team_id) VALUES (?, ?, ?, ?, ?)",
                         (pid, match_id, champ, win, team))
            pid += 1
    conn.commit()


if __name__ == "__main__":
    unittest.main()
