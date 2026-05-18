"""
tests/test_augment_external_source.py — CLAUDE #88 Task 2 + 3.

Covers the external Mayhem win-rate prior fetch/parse/cache/degrade and
the cherry-augments.json metadata cache + OCR-name→id reconciliation.
HTTP is monkey-patched (`_http_get` / `_http_get_json` are encapsulated
for exactly this — riot_api pattern); the cache dir is redirected to a
temp tree so no real network or repo writes happen.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import augment_external_source as X


def _blitz_payload():
    return {
        "meta": {"count": 2, "generated_at": "2026-05-18T02:21:07Z"},
        "data": [
            {
                "augment_id": "1088",
                "patch": "16.10",
                "stats": {
                    "win_rate": 0.50,
                    "num_games": 1000,
                    "num_win_games": 500,
                    "pick_rate": 0.01,
                    "tier": 3,
                    "augment_stage_stats": [
                        {"augment_stage": "1", "win_rate": 0.40},
                        {"augment_stage": "3", "win_rate": 0.55},
                    ],
                },
            },
            {
                "augment_id": "1406",
                "patch": "16.10",
                "stats": {"win_rate": 0.62, "num_games": 800, "tier": 1},
            },
            # malformed rows must be dropped, not crash:
            {"augment_id": None, "stats": {"win_rate": 0.9}},
            {"augment_id": "9", "stats": {"win_rate": "bad"}},
        ],
    }


def _cherry_payload():
    return [
        {"id": 1103, "nameTRA": "Bread And Butter", "simpleNameTRA": "",
         "rarity": "kGold", "augmentSmallIconPath": "/x/bnb.png"},
        {"id": 1011, "nameTRA": "Can't Touch This", "rarity": "kPrismatic",
         "augmentSmallIconPath": "/x/ctt.png"},
        {"id": 0, "nameTRA": "bogus-no-int-skip"},   # int id 0 still stored
        {"nameTRA": "no id at all"},                  # dropped
    ]


class _TmpCacheMixin(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._root = Path(self._td.name)
        (self._root / "tp").mkdir(parents=True)
        self._p_ds = mock.patch.object(X, "_DS_DATA_DIR", self._root)
        self._p_patch = mock.patch.object(X, "_current_patch", lambda: "tp")
        self._p_ds.start()
        self._p_patch.start()
        X.reset_cache()

    def tearDown(self):
        self._p_patch.stop()
        self._p_ds.stop()
        X.reset_cache()
        self._td.cleanup()


class NormalizeTests(unittest.TestCase):
    def test_parses_and_drops_malformed(self):
        snap = X._normalize("mayhem", "16.10.1", _blitz_payload())
        self.assertEqual(snap["count"], 2)               # 2 malformed dropped
        self.assertEqual(snap["source_patch"], "16.10")
        self.assertEqual(snap["augments"]["1088"]["win_rate"], 0.50)
        self.assertEqual(snap["augments"]["1088"]["num_games"], 1000)
        self.assertEqual(snap["augments"]["1088"]["stage_win_rate"]["3"], 0.55)

    def test_empty_payload_raises(self):
        with self.assertRaises(X.AugmentSourceError):
            X._normalize("mayhem", "p", {"data": []})
        with self.assertRaises(X.AugmentSourceError):
            X._normalize("mayhem", "p", {"data": "notalist"})


class PriorTableTests(unittest.TestCase):
    def setUp(self):
        self.t = X._table_from_snapshot(
            "mayhem", X._normalize("mayhem", "16.10.1", _blitz_payload())
        )

    def test_lookup_int_and_str(self):
        self.assertAlmostEqual(self.t.win_rate(1088), 0.50)
        self.assertAlmostEqual(self.t.win_rate("1088"), 0.50)
        self.assertEqual(self.t.num_games(1088), 1000)

    def test_unknown_is_none_zero(self):
        self.assertIsNone(self.t.win_rate(999999))
        self.assertEqual(self.t.num_games(999999), 0)
        self.assertIsNone(self.t.win_rate(None))

    def test_stage_win_rate(self):
        self.assertAlmostEqual(self.t.stage_win_rate(1088, 3), 0.55)
        self.assertIsNone(self.t.stage_win_rate(1088, 2))   # absent stage
        self.assertIsNone(self.t.stage_win_rate(1406, 1))   # no stage stats


class RefreshAndDegradeTests(_TmpCacheMixin):
    def test_refresh_writes_snapshot_and_reads_back(self):
        with mock.patch.object(X, "_http_get_json", lambda u, t: _blitz_payload()):
            t = X.refresh_cache("mayhem", force=True)
        self.assertTrue(t.has_data)
        self.assertEqual(t.count, 2)
        self.assertTrue((self._root / "tp" / "mayhem_augment_stats.json").exists())
        # second call with file present + not force → no network (boom proves it)
        with mock.patch.object(X, "_http_get_json", mock.Mock(side_effect=AssertionError)):
            t2 = X.refresh_cache("mayhem", force=False)
        self.assertEqual(t2.count, 2)

    def test_outage_degrades_no_raise_force_raises(self):
        with mock.patch.object(X, "_http_get_json", lambda u, t: _blitz_payload()):
            X.refresh_cache("mayhem", force=True)            # seed cache

        def boom(u, t):
            raise X.AugmentSourceError("outage")

        with mock.patch.object(X, "_http_get_json", boom):
            degraded = X.refresh_cache("mayhem", force=False)  # no raise
            self.assertEqual(degraded.count, 2)
            with self.assertRaises(X.AugmentSourceError):
                X.refresh_cache("mayhem", force=True)

    def test_get_priors_never_raises_unknown_mode(self):
        empty = X.get_priors("nonsense")
        self.assertFalse(empty.has_data)
        self.assertEqual(empty.count, 0)


class MetaTests(_TmpCacheMixin):
    def _seed_arena_augments(self):
        (self._root / "tp" / "arena_augments.json").write_text(
            json.dumps({"augments": [
                {"id": 1103, "apiName": "BreadAndButter", "name": "Bread And Butter"},
                {"id": 1011, "apiName": "CantTouchThis", "name": "Can't Touch This"},
            ]}), encoding="utf-8",
        )

    def test_build_meta_resolves_name_rarity_icon(self):
        self._seed_arena_augments()
        with mock.patch.object(X, "_http_get", lambda u, t: _cherry_payload()):
            m = X.refresh_meta_cache(force=True)
        self.assertEqual(m.name(1103), "Bread And Butter")
        self.assertEqual(m.rarity(1103), "kGold")
        self.assertEqual(m.icon_path(1103), "/x/bnb.png")
        self.assertTrue((self._root / "tp" / "cherry_augments.json").exists())

    def test_resolve_id_normalizes_and_uses_arena_alias(self):
        self._seed_arena_augments()
        with mock.patch.object(X, "_http_get", lambda u, t: _cherry_payload()):
            m = X.refresh_meta_cache(force=True)
        # cherry display-name forms
        self.assertEqual(m.resolve_id("Bread And Butter"), 1103)
        self.assertEqual(m.resolve_id("bread-and-butter"), 1103)
        self.assertEqual(m.resolve_id("BREAD AND BUTTER!"), 1103)
        self.assertEqual(m.resolve_id("Can't Touch This"), 1011)
        # apiName form only present via the arena_augments.json alias merge
        self.assertEqual(m.resolve_id("BreadAndButter"), 1103)
        self.assertIsNone(m.resolve_id("totally unknown augment"))
        self.assertIsNone(m.resolve_id(""))

    def test_meta_outage_degrades_no_raise(self):
        with mock.patch.object(X, "_http_get", lambda u, t: _cherry_payload()):
            X.refresh_meta_cache(force=True)

        def boom(u, t):
            raise X.AugmentSourceError("down")

        with mock.patch.object(X, "_http_get", boom):
            d = X.refresh_meta_cache(force=False)
            self.assertTrue(d.has_data)                      # degraded to cache
            with self.assertRaises(X.AugmentSourceError):
                X.refresh_meta_cache(force=True)

    def test_get_augment_meta_never_raises(self):
        with mock.patch.object(X, "_http_get",
                               mock.Mock(side_effect=X.AugmentSourceError("x"))):
            m = X.get_augment_meta()      # no cache, outage → empty, no raise
        self.assertFalse(m.has_data)


if __name__ == "__main__":
    unittest.main()
