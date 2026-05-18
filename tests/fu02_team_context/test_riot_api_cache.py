"""SQLite cache tests for `core/riot_api_cache.py` - FU02 fan-out backing.

Covers:
  - Immutable cache: store + retrieve + miss returns None.
  - TTL cache: store + retrieve + expiry.
  - Concurrent writes are atomic (INSERT OR REPLACE).
  - cached_get helper: cache-miss invokes fetch_fn, caches result.
  - cached_get does NOT cache None (transient errors retry).
  - Stats counter accuracy.
  - DB path is created on demand (parent dir doesn't pre-exist).
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core.riot_api_cache import RiotApiCache, cached_get   # noqa: E402
from core import riot_api_cache as RIC                     # noqa: E402


class _TempCache(unittest.TestCase):
    """Mixin: each test gets a fresh DB inside a TemporaryDirectory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "riot_api_cache.db"
        self.cache = RiotApiCache(db_path=self.db_path)

    def tearDown(self):
        # On Windows, SQLite WAL/SHM sidecar files can linger briefly
        # after the last connection closes - TemporaryDirectory cleanup
        # then raises PermissionError. Best-effort: ignore_errors.
        try:
            self._tmp.cleanup()
        except (OSError, PermissionError):
            pass


class TestImmutableCache(_TempCache):
    def test_miss_returns_none(self):
        self.assertIsNone(self.cache.get_immutable("missing-key"))

    def test_set_then_get(self):
        payload = {"matchId": "NA1_4567", "gameMode": "CLASSIC"}
        self.assertTrue(self.cache.set_immutable("match:v5:NA1_4567", payload))
        self.assertEqual(
            self.cache.get_immutable("match:v5:NA1_4567"),
            payload,
        )

    def test_replace_overwrites(self):
        self.cache.set_immutable("k", {"v": 1})
        self.cache.set_immutable("k", {"v": 2})
        self.assertEqual(self.cache.get_immutable("k"), {"v": 2})

    def test_round_trip_unicode(self):
        # Riot summoner names can be arbitrary unicode; ensure the
        # JSON encoder isn't breaking on non-ASCII.
        payload = {"name": "Faker곤", "tag": "KR1"}
        self.cache.set_immutable("account:v1:KR:Faker곤#KR1", payload)
        self.assertEqual(
            self.cache.get_immutable("account:v1:KR:Faker곤#KR1"),
            payload,
        )


class TestTtlCache(_TempCache):
    def test_miss_returns_none(self):
        self.assertIsNone(self.cache.get_ttl("k"))

    def test_set_then_get_within_ttl(self):
        self.cache.set_ttl("rank:k", {"tier": "PLATINUM"}, ttl_s=300)
        self.assertEqual(
            self.cache.get_ttl("rank:k"),
            {"tier": "PLATINUM"},
        )

    def test_expired_returns_none(self):
        # ttl_s=0 → expires_at == now → already expired on first read.
        self.cache.set_ttl("ephem", {"v": 1}, ttl_s=0)
        # Tiny sleep so the integer-second clock advances past the boundary.
        time.sleep(1.05)
        self.assertIsNone(self.cache.get_ttl("ephem"))

    def test_purge_expired_drops_rows(self):
        self.cache.set_ttl("a", {"v": 1}, ttl_s=0)
        self.cache.set_ttl("b", {"v": 2}, ttl_s=300)
        time.sleep(1.05)
        purged = self.cache.purge_expired_ttl()
        self.assertGreaterEqual(purged, 1)
        # Live row survives.
        self.assertEqual(self.cache.get_ttl("b"), {"v": 2})


class TestStats(_TempCache):
    def test_initial_stats_are_zero(self):
        st = self.cache.stats()
        self.assertEqual(st["immutable_rows"], 0)
        self.assertEqual(st["ttl_live_rows"], 0)

    def test_stats_count_rows(self):
        self.cache.set_immutable("a", {"v": 1})
        self.cache.set_immutable("b", {"v": 2})
        self.cache.set_ttl("c", {"v": 3}, ttl_s=300)
        st = self.cache.stats()
        self.assertEqual(st["immutable_rows"], 2)
        self.assertEqual(st["ttl_live_rows"], 1)


class TestConcurrency(_TempCache):
    def test_parallel_writes_dont_corrupt(self):
        # 8 threads each writing 50 distinct keys - no corruption,
        # all rows survive. Validates the WAL + INSERT OR REPLACE path.
        def writer(tid: int) -> None:
            for i in range(50):
                self.cache.set_immutable(f"thread{tid}:key{i}", {"i": i, "tid": tid})

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()

        st = self.cache.stats()
        self.assertEqual(st["immutable_rows"], 8 * 50)
        # Spot-check a couple
        self.assertEqual(self.cache.get_immutable("thread3:key17"),
                         {"i": 17, "tid": 3})
        self.assertEqual(self.cache.get_immutable("thread7:key0"),
                         {"i": 0, "tid": 7})


class TestCachedGet(unittest.TestCase):
    """cached_get exercises the module-level singleton; isolate via reset."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "rapc.db"
        # Reset module-level singleton to point at our tempdir DB.
        RIC._reset_for_tests(db_path=self._db_path)

    def tearDown(self):
        # Restore default singleton (caller may not need it but keep
        # other tests isolated).
        RIC._reset_for_tests(db_path=None)
        try:
            self._tmp.cleanup()
        except (OSError, PermissionError):
            pass

    def test_immutable_miss_invokes_fetch(self):
        calls = []
        def fetch():
            calls.append(1)
            return {"v": 42}
        out = cached_get("k", fetch, ttl_s=None)
        self.assertEqual(out, {"v": 42})
        self.assertEqual(len(calls), 1)
        # Second call hits cache, no fetch.
        out2 = cached_get("k", fetch, ttl_s=None)
        self.assertEqual(out2, {"v": 42})
        self.assertEqual(len(calls), 1)

    def test_ttl_miss_invokes_fetch(self):
        calls = []
        def fetch():
            calls.append(1)
            return {"tier": "PLATINUM"}
        out = cached_get("rank:k", fetch, ttl_s=300)
        self.assertEqual(out, {"tier": "PLATINUM"})
        self.assertEqual(len(calls), 1)

    def test_none_result_is_not_cached(self):
        calls = []
        def fetch():
            calls.append(1)
            return None
        out1 = cached_get("k-none", fetch, ttl_s=None)
        out2 = cached_get("k-none", fetch, ttl_s=None)
        self.assertIsNone(out1)
        self.assertIsNone(out2)
        # Both calls hit fetch; the None wasn't poisoned in cache.
        self.assertEqual(len(calls), 2)

    def test_db_parent_dir_created(self):
        # Pointing at a fresh nested dir that doesn't exist yet.
        deeper = Path(self._tmp.name) / "newer" / "deeper" / "rapc.db"
        cache2 = RiotApiCache(db_path=deeper)
        cache2.set_immutable("k", {"v": 1})
        self.assertTrue(deeper.exists())
        self.assertEqual(cache2.get_immutable("k"), {"v": 1})


if __name__ == "__main__":
    unittest.main()
