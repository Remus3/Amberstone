"""
tests/test_augment_recommender.py — CLAUDE #88 Task 4 + 5.

Recommender math (Laplace / n/(n+K) shrinkage / greedy synergy), the §4
external blend at its three regimes (w=0 / mid / w→1), own-history scan
from a synthetic match_history.db (win derivation, tracked-puuid resolve,
KIWI/CHERRY mode filter), and the arena_coach integration helper. No
network: external prior + meta are stubbed.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import augment_external_source as X
from core import augment_recommender as R

_TP = "tracked-puuid-abc"


def _detail(augs, won, *, mode="KIWI", qid=2400, puuid=_TP):
    stats = {"win": bool(won)}
    for i, a in enumerate(augs, 1):
        stats[f"playerAugment{i}"] = a
    return {
        "tracked_puuid": puuid,
        "lcu_match_detail": {
            "gameMode": mode,
            "queueId": qid,
            "participantIdentities": [
                {"participantId": 1, "player": {"puuid": puuid}},
                {"participantId": 2, "player": {"puuid": "someone-else"}},
            ],
            "participants": [
                {"participantId": 1, "stats": stats},
                {"participantId": 2, "stats": {"win": not won,
                                               "playerAugment1": 7777}},
            ],
        },
    }


def _make_db(rows):
    """rows: list of (augments, won, mode, qid). Returns a temp db Path."""
    td = tempfile.TemporaryDirectory()
    p = Path(td.name) / "match_history.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE matches (id INTEGER PRIMARY KEY, raw_data TEXT)")
    for augs, won, mode, qid in rows:
        conn.execute(
            "INSERT INTO matches (raw_data) VALUES (?)",
            (json.dumps(_detail(augs, won, mode=mode, qid=qid)),),
        )
    conn.commit()
    conn.close()
    return td, p


def _priors(d):
    """d: {id_str: win_rate} -> AugmentPriorTable."""
    return X.AugmentPriorTable(
        mode="mayhem",
        augments={k: {"win_rate": v, "num_games": 9999, "stage_win_rate": {}}
                  for k, v in d.items()},
    )


def _meta(name_index):
    return X.AugmentMetaTable(
        augments={str(v): {"name": k, "rarity": "kGold", "icon": ""}
                  for k, v in name_index.items()},
        _name_index={X._norm_name(k): v for k, v in name_index.items()},
    )


class OwnHistoryScanTests(unittest.TestCase):
    def tearDown(self):
        R.reset_cache()

    def test_counts_pairs_win_and_mode_filter(self):
        td, p = _make_db([
            ([10, 20], True,  "KIWI",   2400),
            ([10],     False, "KIWI",   2400),
            ([99],     True,  "CHERRY", 1700),   # excluded from mayhem scan
        ])
        try:
            h = R.load_own_history("mayhem", db_path=p)
            self.assertEqual(h.n_matches, 2)
            self.assertEqual(h.games[10], 2)
            self.assertEqual(h.wins[10], 1)
            self.assertEqual(h.games[20], 1)
            self.assertEqual(h.pair_games[(10, 20)], 1)
            self.assertEqual(h.pair_wins[(10, 20)], 1)
            self.assertNotIn(99, h.games)              # CHERRY filtered out
            self.assertEqual(h.total_games, 2)
            self.assertEqual(h.total_wins, 1)
        finally:
            td.cleanup()

    def test_missing_db_is_empty_no_raise(self):
        h = R.load_own_history("mayhem", db_path=Path("/no/such/file.db"))
        self.assertEqual(h.n_matches, 0)
        self.assertEqual(h.games, {})

    def test_cache_refreshes_on_db_change(self):
        td, p = _make_db([([1], True, "KIWI", 2400)])
        try:
            h1 = R.load_own_history("mayhem", db_path=p)
            self.assertEqual(h1.n_matches, 1)
            conn = sqlite3.connect(str(p))
            conn.execute("INSERT INTO matches (raw_data) VALUES (?)",
                         (json.dumps(_detail([2], False)),))
            conn.commit()
            conn.close()
            h2 = R.load_own_history("mayhem", db_path=p)
            self.assertEqual(h2.n_matches, 2)        # (mtime,size) changed
        finally:
            td.cleanup()


class SmoothingMathTests(unittest.TestCase):
    def test_laplace_own_wr(self):
        h = R.OwnHistory(mode="mayhem", games={5: 4}, wins={5: 1})
        # (1 + 1) / (4 + 2*1) = 2/6
        self.assertAlmostEqual(R._own_wr(h, 5, 1.0), 2 / 6)
        # unseen → (0+1)/(0+2) = 0.5 neutral
        self.assertAlmostEqual(R._own_wr(h, 999, 1.0), 0.5)

    def test_pair_wr(self):
        h = R.OwnHistory(mode="mayhem", pair_games={(3, 8): 2},
                         pair_wins={(3, 8): 2})
        wr, m = R._pair_wr(h, 8, 3, 1.0)             # order-independent
        self.assertAlmostEqual(wr, 3 / 4)            # (2+1)/(2+2)
        self.assertEqual(m, 2)


class BlendRegimeTests(unittest.TestCase):
    """§4 blend at w=0, mid, w→1."""

    def tearDown(self):
        R.reset_cache()

    def _run(self, rows, offered, picked=(), priors=None, stage=None):
        td, p = _make_db(rows)
        self.addCleanup(td.cleanup)
        with mock.patch.object(R._ext, "get_priors",
                               lambda mode: priors or _priors({})), \
             mock.patch.object(R._ext, "get_augment_meta",
                               lambda: _meta({"A": offered[0]})):
            return R.recommend(offered, picked, mode="mayhem",
                               stage=stage, db_path=p)

    def test_w_zero_is_pure_external(self):
        # n_own=0 → w=0 → score == ext_wr, confidence 0
        res = self._run([], [1088], priors=_priors({"1088": 0.70}))
        s = res.top
        self.assertEqual(s.n_own, 0)
        self.assertAlmostEqual(s.blend_w, 0.0)
        self.assertAlmostEqual(s.ext_wr, 0.70)
        self.assertAlmostEqual(s.score, 0.70)
        self.assertTrue(res.used_external)

    def test_w_mid_blends(self):
        # games[1088]=5 all wins → own_wr=(5+1)/(5+2)=6/7; ext=0.5;
        # w=5/(5+5)=0.5 → base = 0.5*6/7 + 0.5*0.5
        rows = [([1088], True, "KIWI", 2400)] * 5
        res = self._run(rows, [1088], priors=_priors({"1088": 0.50}))
        s = res.top
        self.assertEqual(s.n_own, 5)
        self.assertAlmostEqual(s.blend_w, 0.5)
        self.assertAlmostEqual(s.own_wr, 6 / 7)
        self.assertAlmostEqual(s.score, 0.5 * (6 / 7) + 0.5 * 0.5)

    def test_w_to_one_own_dominates(self):
        rows = [([1088], True, "KIWI", 2400)] * 50
        res = self._run(rows, [1088], priors=_priors({"1088": 0.10}))
        s = res.top
        self.assertGreater(s.blend_w, 0.9)            # 50/55
        # heavily own (≈ (50+1)/(50+2)=0.98), barely pulled by ext 0.10
        self.assertGreater(s.score, 0.88)

    def test_unknown_only_neutral_conf_zero(self):
        res = self._run([], [424242], priors=_priors({}))
        s = res.top
        self.assertAlmostEqual(s.score, 0.5)
        self.assertAlmostEqual(s.confidence, 0.0)
        self.assertIsNone(s.ext_wr)
        self.assertFalse(res.used_external)

    def test_stage_prior_sharpens(self):
        pt = X.AugmentPriorTable(mode="mayhem", augments={
            "1088": {"win_rate": 0.50, "num_games": 9, "stage_win_rate": {"3": 0.80}}
        })
        res = self._run([], [1088], priors=pt, stage=3)
        self.assertAlmostEqual(res.top.ext_wr, 0.80)   # stage 3 used over 0.50
        self.assertAlmostEqual(res.top.score, 0.80)


class SynergyTests(unittest.TestCase):
    def tearDown(self):
        R.reset_cache()

    def test_greedy_synergy_shrunk_and_signed(self):
        # A(=100) in 4 games: 2 with P(=200) both won, 2 solo both lost.
        #   games[A]=4 wins[A]=2 → own_wr(A)=(2+1)/(4+2)=0.5
        #   pair(A,P): m=2 wins=2 → pair_wr=(2+1)/(2+2)=0.75
        #   shrink = 2/(2+5)=0.285714 ; contrib = shrink*(0.75-0.5)
        rows = [
            ([100, 200], True,  "KIWI", 2400),
            ([100, 200], True,  "KIWI", 2400),
            ([100],      False, "KIWI", 2400),
            ([100],      False, "KIWI", 2400),
        ]
        td, p = _make_db(rows)
        self.addCleanup(td.cleanup)
        with mock.patch.object(R._ext, "get_priors", lambda m: _priors({})), \
             mock.patch.object(R._ext, "get_augment_meta",
                               lambda: _meta({"A": 100})):
            res = R.recommend([100], [200], mode="mayhem", db_path=p)
        s = res.top
        self.assertAlmostEqual(s.base, 0.5)            # no ext → own-only
        expected_syn = (2 / 7) * (0.75 - 0.5)
        self.assertAlmostEqual(s.synergy, expected_syn)
        self.assertAlmostEqual(s.score, 0.5 + expected_syn)

    def test_no_picked_no_synergy(self):
        td, p = _make_db([([100], True, "KIWI", 2400)])
        self.addCleanup(td.cleanup)
        with mock.patch.object(R._ext, "get_priors", lambda m: _priors({})), \
             mock.patch.object(R._ext, "get_augment_meta",
                               lambda: _meta({"A": 100})):
            res = R.recommend([100], [], mode="mayhem", db_path=p)
        self.assertAlmostEqual(res.top.synergy, 0.0)


class RecommendContractTests(unittest.TestCase):
    def tearDown(self):
        R.reset_cache()

    def test_empty_offered_returns_empty(self):
        res = R.recommend([], [], mode="mayhem")
        self.assertEqual(res.ranked, [])
        self.assertIsNone(res.top)

    def test_stable_tiebreak_on_input_order(self):
        # all unknown → all score 0.5 → order preserved
        with mock.patch.object(R._ext, "get_priors", lambda m: _priors({})), \
             mock.patch.object(R._ext, "get_augment_meta", lambda: _meta({})):
            res = R.recommend([5, 9, 2], [], mode="mayhem",
                              db_path=Path("/no/db"))
        self.assertEqual([s.augment_id for s in res.ranked], [5, 9, 2])

    def test_bad_input_does_not_raise(self):
        res = R.recommend([None, "x", 0], [], mode="mayhem",
                          db_path=Path("/no/db"))
        self.assertEqual(res.ranked, [])

    def test_higher_score_ranked_first(self):
        with mock.patch.object(R._ext, "get_priors",
                               lambda m: _priors({"1": 0.40, "2": 0.90})), \
             mock.patch.object(R._ext, "get_augment_meta",
                               lambda: _meta({"Lo": 1, "Hi": 2})):
            res = R.recommend([1, 2], [], mode="mayhem", db_path=Path("/no/db"))
        self.assertEqual(res.top.augment_id, 2)
        self.assertEqual(res.ranked[0].name, "Hi")


class ArenaCoachIntegrationTests(unittest.TestCase):
    """coaches.arena_coach._augment_recommendation + helpers."""

    def setUp(self):
        from coaches import arena_coach
        self.AC = arena_coach

    def test_mode_discriminator(self):
        self.assertEqual(self.AC._reco_mode_for("KIWI"), "mayhem")
        self.assertEqual(self.AC._reco_mode_for("CHERRY"), "arena")
        self.assertEqual(self.AC._reco_mode_for("ARENA"), "arena")
        self.assertEqual(self.AC._reco_mode_for(None), "mayhem")

    def test_stage_parse(self):
        self.assertEqual(self.AC._parse_stage("~3"), 3)
        self.assertEqual(self.AC._parse_stage("~7"), None)
        self.assertEqual(self.AC._parse_stage(0), None)
        self.assertEqual(self.AC._parse_stage(None), None)

    def test_helper_emits_compact_fields(self):
        fake_meta = _meta({"Chili": 1406, "Bread": 1103})
        canned = R.RecommendationResult(
            mode="mayhem", used_external=True, n_matches=13, stage=2,
            ranked=[R.AugmentScore(
                augment_id=1406, name="Chili", rarity="kGold", score=0.59,
                base=0.61, own_wr=0.75, ext_wr=0.55, blend_w=0.286,
                n_own=2, synergy=-0.01)],
        )
        with mock.patch.object(X, "get_augment_meta", lambda **k: fake_meta), \
             mock.patch.object(R, "recommend", lambda *a, **k: canned):
            out = self.AC._augment_recommendation(
                {"game_mode": "KIWI", "round": "~2"}, ["Chili"], ["Bread"])
        self.assertEqual(out["aug_reco_top"], "Chili")
        self.assertAlmostEqual(out["aug_reco_conf"], 0.286)
        self.assertEqual(out["aug_reco_mode"], "mayhem")
        self.assertEqual(out["aug_reco_stage"], 2)
        self.assertEqual(out["aug_reco"][0]["id"], 1406)

    def test_helper_returns_empty_on_unresolved(self):
        with mock.patch.object(X, "get_augment_meta", lambda **k: _meta({})):
            out = self.AC._augment_recommendation(
                {"game_mode": "KIWI"}, ["nonexistent augment"], [])
        self.assertEqual(out, {})

    def test_helper_never_raises(self):
        with mock.patch.object(X, "get_augment_meta",
                               mock.Mock(side_effect=RuntimeError("boom"))):
            out = self.AC._augment_recommendation({"game_mode": "KIWI"},
                                                  ["x"], [])
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
