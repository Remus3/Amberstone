"""tests/test_p2w1_core_d.py - deep-audit cycle 7 P2 W1 slice D regression pins.

Pins the audit fixes for the core/ post-game + stats slice:

  1. death_patterns_loader.top_patterns fail-soft on a malformed `count`
     (documented contract: malformed entry values degrade, never raise).
  2. synergy_external_source._cache prunes expired entries on insert
     (date-keyed entries previously accumulated forever in a long-running
     process - one new unreachable key per day).
  3. damage_mix._key_to_id_map validates the cached snapshot identity via
     weakref (an id()-reuse after GC could previously serve a STALE
     key->id map for a different snapshot) and prunes dead entries.
  4. damage_mix._cache_put prunes expired mix entries on insert (expired
     keys were previously only evicted when the SAME key was read again,
     so dead keys accumulated across games / item changes).
  5. aftergame_summary.write_to_client_coaching_data logs the swallowed
     exception (fail-soft return False preserved).
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
import weakref

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.death_patterns_loader import top_patterns  # noqa: E402
from core import synergy_external_source as S  # noqa: E402
from core import damage_mix as dm  # noqa: E402
from core import aftergame_summary as ag  # noqa: E402


def _write(tmp: pathlib.Path, data: dict) -> pathlib.Path:
    p = tmp / "death_patterns.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class DeathPatternsCountFailSoftTests(unittest.TestCase):
    """A malformed `count` (string garbage / null) must degrade to 0,
    matching the rate/confidence fail-soft semantics - never raise."""

    def _patterns_for_count(self, count_value) -> list[dict]:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="dpl_cnt_"))
        try:
            p = _write(tmp, {
                "schema_version": 2,
                "top3": ["solo_pickoff"],
                "patterns": {"solo_pickoff": {
                    "label": "Solo pickoffs", "description": "x",
                    "count": count_value, "rate": 0.5, "confidence": 0.9,
                }},
            })
            return top_patterns(p)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_string_garbage_count_degrades_to_zero(self):
        out = self._patterns_for_count("not-a-number")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["count"], 0)
        self.assertEqual(out[0]["rate"], 0.5)

    def test_null_count_degrades_to_zero(self):
        out = self._patterns_for_count(None)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["count"], 0)

    def test_numeric_count_still_passes_through(self):
        out = self._patterns_for_count(7)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["count"], 7)


class SynergyCachePruneTests(unittest.TestCase):
    """Expired date-keyed cache entries are pruned at insert time so the
    in-memory cache stays bounded in a long-running process."""

    def setUp(self) -> None:
        S._reset_cache_for_tests()
        self._t = [1000.0]
        S._clock = lambda: self._t[0]
        from datetime import datetime, timezone
        self._day = [2]
        S._utcnow = lambda: datetime(2026, 6, self._day[0], tzinfo=timezone.utc)
        self._orig_http = S._http_get_json
        S._http_get_json = lambda url, timeout_s=S._TIMEOUT_S: {
            "code": 0,
            "data": [{
                "championid1": "498", "championid2": "497",
                "doublewinrate": 0.56, "iwinrate1": 0.5, "iwinrate2": 0.5,
                "itemp1": "4.42%", "irank": 1,
                "lane1": "bottom", "lane2": "support",
            }],
        }

    def tearDown(self) -> None:
        import time as _time
        from datetime import datetime, timezone
        S._clock = _time.monotonic
        S._utcnow = lambda: datetime.now(timezone.utc)
        S._http_get_json = self._orig_http
        S._reset_cache_for_tests()

    def test_expired_entries_pruned_on_insert(self):
        self.assertIsNotNone(S.fetch_rows("bottom", "support"))
        self.assertEqual(len(S._cache), 1)
        # Next day + past TTL: the old date-keyed entry is unreachable
        # AND expired - the refetch insert must prune it.
        self._day[0] += 1
        self._t[0] += S._TTL_S + 1.0
        self.assertIsNotNone(S.fetch_rows("bottom", "support"))
        self.assertEqual(len(S._cache), 1,
                         "stale date-keyed entry must be pruned on insert")

    def test_fresh_entries_survive_prune(self):
        self.assertIsNotNone(S.fetch_rows("bottom", "support"))
        # A second lane-pair within TTL: both entries stay.
        self._t[0] += 60.0
        self.assertIsNotNone(S.fetch_rows("top", "jungle"))
        self.assertEqual(len(S._cache), 2)


class _FakeSnap:
    """Minimal weakref-able stand-in carrying the two attributes
    _key_to_id_map touches (champions + patch for error strings).
    A plain class (not SimpleNamespace, which has no __weakref__ slot)
    to mirror the real DataSnapshot dataclass."""

    def __init__(self, champions: dict) -> None:
        self.patch = "test-patch"
        self.champions = champions


def _fake_snapshot(champions: dict) -> _FakeSnap:
    return _FakeSnap(champions)


class DamageMixKeyMapCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        with dm._KEY_CACHE_LOCK:
            dm._KEY_TO_ID_CACHE.clear()

    def tearDown(self) -> None:
        with dm._KEY_CACHE_LOCK:
            dm._KEY_TO_ID_CACHE.clear()

    def test_same_snapshot_returns_cached_mapping(self):
        snap = _fake_snapshot({"Garen": {"key": "86"}})
        m1 = dm._key_to_id_map(snap)
        m2 = dm._key_to_id_map(snap)
        self.assertIs(m1, m2)
        self.assertEqual(m1, {86: "Garen"})

    def test_id_reuse_does_not_serve_stale_map(self):
        """If a cache slot's id() key now belongs to a DIFFERENT snapshot
        object (id reuse after GC), the map must be rebuilt - never served
        stale."""
        snap = _fake_snapshot({"Garen": {"key": "86"}})
        other = _fake_snapshot({"Lux": {"key": "99"}})
        # Poison the slot for id(snap) with a mapping built from `other`.
        with dm._KEY_CACHE_LOCK:
            dm._KEY_TO_ID_CACHE[id(snap)] = (weakref.ref(other), {99: "Lux"})
        m = dm._key_to_id_map(snap)
        self.assertEqual(m, {86: "Garen"},
                         "stale id-reuse mapping must be rebuilt")

    def test_dead_snapshot_entries_pruned_on_insert(self):
        snap1 = _fake_snapshot({"Garen": {"key": "86"}})
        dm._key_to_id_map(snap1)
        self.assertEqual(len(dm._KEY_TO_ID_CACHE), 1)
        del snap1  # drop the only strong ref
        import gc
        gc.collect()
        snap2 = _fake_snapshot({"Lux": {"key": "99"}})
        dm._key_to_id_map(snap2)
        with dm._KEY_CACHE_LOCK:
            live = len(dm._KEY_TO_ID_CACHE)
        self.assertEqual(live, 1, "dead snapshot entries must be pruned")


class DamageMixTtlCachePruneTests(unittest.TestCase):
    def setUp(self) -> None:
        dm.clear_cache()

    def tearDown(self) -> None:
        dm.clear_cache()

    def test_expired_mix_entries_pruned_on_insert(self):
        sentinel = object()
        with dm._MIX_LOCK:
            dm._MIX_CACHE[("old", "", 1, "SR")] = dm._CacheEntry(
                expires_at=0.0, mix=sentinel)  # long expired
        dm._cache_put(("new", "", 1, "SR"), sentinel)
        with dm._MIX_LOCK:
            keys = set(dm._MIX_CACHE)
        self.assertEqual(keys, {("new", "", 1, "SR")},
                         "expired entries must be pruned on insert")

    def test_fresh_entries_survive_insert(self):
        sentinel = object()
        dm._cache_put(("a", "", 1, "SR"), sentinel)
        dm._cache_put(("b", "", 1, "SR"), sentinel)
        with dm._MIX_LOCK:
            self.assertEqual(len(dm._MIX_CACHE), 2)


class AftergameWriteLogsSwallowedErrorTests(unittest.TestCase):
    def test_failure_returns_false_and_logs(self):
        # Target inside a nonexistent directory -> tmp write raises.
        bad_target = pathlib.Path(tempfile.gettempdir()) / "rc_p2w1_missing_dir" / "x" / "coaching_data.json"
        with self.assertLogs("rc.aftergame_summary", level="WARNING"):
            ok = ag.write_to_client_coaching_data({"action": "x"}, target=bad_target)
        self.assertFalse(ok)

    def test_success_still_returns_true(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="ag_ok_"))
        try:
            target = tmp / "coaching_data.json"
            ok = ag.write_to_client_coaching_data({"action": "x"}, target=target)
            self.assertTrue(ok)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["action"], "x")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii(self) -> None:
        b = pathlib.Path(__file__).read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
