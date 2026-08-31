"""tests/test_smoothed_rates_101qq_lock.py - lane 8 concurrency regression.

`core.smoothed_rates_101qq._load_once()` used to run the live Tencent fetch
(up to 3 sequential HTTP GETs at a 6s socket timeout each, so ~18s worst
case) INSIDE the process-wide `_CACHE_LOCK` that all 7 public accessors
take. On the threaded dashboard server that convoyed every champ-select
caller of `/api/duo-synergy` and `/api/draft-score` behind one unreachable
CN endpoint - the exact failure the static-seed fallback exists to absorb.

These tests pin the three properties of the fix:

  1. no network I/O runs while `_CACHE_LOCK` is held (probed from a second
     thread - `_CACHE_LOCK` is an RLock, so a same-thread acquire always
     succeeds and would prove nothing),
  2. serve-stale-while-refreshing: once a snapshot exists, an expired TTL
     never blocks a reader,
  3. exactly one refresh runs at a time, however many callers pile up.

Cold start (no snapshot at all) may still block - there is nothing to
serve - and that is asserted as intended behaviour, not a defect.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core import smoothed_rates_101qq as S101  # noqa: E402
from core import synergy_external_source as SES  # noqa: E402

# Bound every wait so a regression fails the assertion rather than hanging
# the suite.
_FETCH_HOLD_S = 5.0        # how long a stubbed fetch parks
_NONBLOCK_BOUND_S = 1.0    # a reader that must not block
_JOIN_S = 15.0


def _live_rows(pairs: list) -> list:
    """Rows in the Tencent `data` schema the indexer consumes."""
    return [
        {
            "championid1": str(c1), "championid2": str(c2),
            "doublewinrate": wr, "iwinrate1": 0.5, "iwinrate2": 0.5,
            "itemp1": pick, "irank": i + 1,
            "lane1": "bottom", "lane2": "support",
        }
        for i, (c1, c2, wr, pick) in enumerate(pairs)
    ]


def _envelope(rows: list) -> dict:
    return {"code": 0, "data": rows, "message": "success"}


def _join_background_refresh(timeout: float = _JOIN_S) -> None:
    """Join the module's in-flight refresh thread if it has one.

    Uses getattr so this file is meaningful against the pre-fix module too
    (which has no refresh thread at all) - it must fail on its timing
    assertions, not on an AttributeError.
    """
    t = getattr(S101, "_REFRESH_THREAD", None)
    if t is not None:
        t.join(timeout)


class LockBase(unittest.TestCase):
    """Saves + restores every module seam these tests reach into."""

    def setUp(self) -> None:
        self._prior_env = os.environ.get("RC_DUO_SYNERGY_LIVE")
        os.environ["RC_DUO_SYNERGY_LIVE"] = "1"
        self._orig_live_rows = S101._live_data_rows
        self._orig_clock = S101._clock
        self._orig_http = SES._http_get_json
        SES._reset_cache_for_tests()
        S101._reset_cache()

    def tearDown(self) -> None:
        # Let any refresh finish before the seams are yanked back.
        _join_background_refresh()
        S101._live_data_rows = self._orig_live_rows
        S101._clock = self._orig_clock
        SES._http_get_json = self._orig_http
        if self._prior_env is None:
            os.environ.pop("RC_DUO_SYNERGY_LIVE", None)
        else:
            os.environ["RC_DUO_SYNERGY_LIVE"] = self._prior_env
        SES._reset_cache_for_tests()
        S101._reset_cache()

    def _prime(self, wr: float = 0.61) -> None:
        """Populate the cache from a cheap synthetic live row (cold start)."""
        S101._live_data_rows = lambda: _live_rows([(22, 147, wr, "4.00%")])
        S101._reset_cache()
        self.assertEqual(S101.source(), "live")

    def _expire_ttl(self) -> None:
        """Jump the module clock past the TTL so the next call sees stale."""
        base = time.monotonic()
        S101._clock = lambda: base + (S101._LIVE_TTL_S * 4.0)


class NoNetworkUnderCacheLockTests(LockBase):
    def test_fetch_does_not_run_while_cache_lock_is_held(self) -> None:
        probe: dict = {"acquired": None}

        def _probe_from_another_thread() -> None:
            def _try() -> None:
                # _CACHE_LOCK is an RLock: a same-thread acquire always
                # succeeds, so the probe MUST run on a different thread.
                got = S101._CACHE_LOCK.acquire(blocking=False)
                probe["acquired"] = got
                if got:
                    S101._CACHE_LOCK.release()

            t = threading.Thread(target=_try, daemon=True)
            t.start()
            t.join(_JOIN_S)

        def _fake_http(url: str, timeout_s: float = 0.0) -> dict:
            _probe_from_another_thread()
            return _envelope(_live_rows([(22, 147, 0.61, "4.00%")]))

        SES._http_get_json = _fake_http
        SES._reset_cache_for_tests()
        S101._reset_cache()

        # Cold start still blocks the caller (nothing to serve), but it must
        # do the network work OUTSIDE the cache lock.
        self.assertEqual(S101.source(), "live")
        self.assertIs(
            probe["acquired"], True,
            "network fetch ran while _CACHE_LOCK was held - every accessor "
            "convoys behind the CN endpoint timeout",
        )

    def test_static_fallback_path_also_reads_outside_the_lock(self) -> None:
        probe: dict = {"acquired": None}

        def _probing_live_rows() -> None:
            def _try() -> None:
                got = S101._CACHE_LOCK.acquire(blocking=False)
                probe["acquired"] = got
                if got:
                    S101._CACHE_LOCK.release()

            t = threading.Thread(target=_try, daemon=True)
            t.start()
            t.join(_JOIN_S)
            return None  # force the static-seed fallback

        S101._live_data_rows = _probing_live_rows
        S101._reset_cache()
        self.assertEqual(S101.source(), "static")
        self.assertIs(probe["acquired"], True,
                      "seed load ran while _CACHE_LOCK was held")


class ServeStaleWhileRefreshingTests(LockBase):
    def test_expired_ttl_does_not_block_readers(self) -> None:
        self._prime(wr=0.61)
        self._expire_ttl()

        entered = threading.Event()
        release = threading.Event()

        def _blocking_rows() -> list:
            entered.set()
            release.wait(_FETCH_HOLD_S)
            return _live_rows([(22, 147, 0.62, "4.00%")])

        S101._live_data_rows = _blocking_rows

        elapsed: dict = {}

        def _reader_a() -> None:
            t0 = time.perf_counter()
            S101.top_duos_for_bot("Ashe", top_n=1)
            elapsed["a"] = time.perf_counter() - t0

        ta = threading.Thread(target=_reader_a, daemon=True)
        ta.start()
        self.assertTrue(entered.wait(_JOIN_S), "the refresh fetch never started")

        # Reader B arrives with the refresh genuinely in flight.
        t0 = time.perf_counter()
        recs = S101.top_duos_for_sup("Seraphine", top_n=1)
        elapsed["b"] = time.perf_counter() - t0

        # Reader A must ALREADY be done while the fetch is still parked -
        # asserted before `release` is set, or a blocked A would be let go
        # by the release and its elapsed time would look fine.
        ta.join(_NONBLOCK_BOUND_S)
        a_alive = ta.is_alive()

        release.set()
        ta.join(_JOIN_S)
        _join_background_refresh()

        self.assertLess(
            elapsed["b"], _NONBLOCK_BOUND_S,
            "a reader blocked on an in-flight refresh instead of being "
            f"served the stale snapshot ({elapsed['b']:.2f}s)",
        )
        self.assertFalse(
            a_alive,
            "the refresh-triggering reader blocked on the fetch instead of "
            "being served the stale snapshot",
        )
        self.assertLess(elapsed.get("a", 99.0), _NONBLOCK_BOUND_S)
        # Stale, but real: shape preserved while refreshing.
        self.assertEqual(len(recs), 1)
        self.assertAlmostEqual(recs[0].doublewinrate, 0.61, places=3)

    def test_refresh_result_replaces_the_stale_snapshot(self) -> None:
        self._prime(wr=0.61)
        self._expire_ttl()
        S101._live_data_rows = lambda: _live_rows([(22, 147, 0.77, "4.00%")])

        # Stale read first, then the refresh lands.
        stale = S101.pair_synergy("Ashe", "Seraphine")
        self.assertIsNotNone(stale)
        self.assertAlmostEqual(stale.doublewinrate, 0.61, places=3)

        _join_background_refresh()
        fresh = S101.pair_synergy("Ashe", "Seraphine")
        self.assertIsNotNone(fresh)
        self.assertAlmostEqual(fresh.doublewinrate, 0.77, places=3)
        self.assertEqual(S101.source(), "live")


class SingleFlightTests(LockBase):
    def test_concurrent_cold_start_triggers_exactly_one_fetch(self) -> None:
        calls: list = []
        started = threading.Event()
        hold = threading.Event()

        def _counted() -> list:
            calls.append(1)
            started.set()
            hold.wait(_FETCH_HOLD_S)
            return _live_rows([(22, 147, 0.61, "4.00%")])

        S101._live_data_rows = _counted
        S101._reset_cache()

        ready = [threading.Event() for _ in range(5)]

        def _reader(idx: int) -> None:
            ready[idx].set()
            S101.top_duos_for_bot("Ashe", top_n=1)

        first = threading.Thread(
            target=lambda: S101.top_duos_for_bot("Ashe", top_n=1), daemon=True)
        first.start()
        self.assertTrue(started.wait(_JOIN_S), "the cold-start fetch never ran")

        rest = [threading.Thread(target=_reader, args=(i,), daemon=True)
                for i in range(5)]
        for t in rest:
            t.start()
        for ev in ready:
            self.assertTrue(ev.wait(_JOIN_S))

        hold.set()
        for t in [first, *rest]:
            t.join(_JOIN_S)
            self.assertFalse(t.is_alive(), "a reader never returned")

        self.assertEqual(
            len(calls), 1,
            f"expected exactly one underlying fetch, got {len(calls)}",
        )

    def test_stale_refresh_is_single_flight(self) -> None:
        self._prime(wr=0.61)
        self._expire_ttl()

        calls: list = []
        entered = threading.Event()
        release = threading.Event()

        def _counted() -> list:
            calls.append(1)
            entered.set()
            release.wait(_FETCH_HOLD_S)
            return _live_rows([(22, 147, 0.62, "4.00%")])

        S101._live_data_rows = _counted

        S101.source()
        self.assertTrue(entered.wait(_JOIN_S), "the refresh fetch never started")
        # Six more stale readers while the first refresh is parked.
        for _ in range(6):
            S101.coverage()
        release.set()
        _join_background_refresh()

        self.assertEqual(
            len(calls), 1,
            f"stale readers each fired their own fetch ({len(calls)} total)",
        )


    def test_reset_during_an_inflight_refresh_is_not_undone(self) -> None:
        self._prime(wr=0.61)
        self._expire_ttl()

        entered = threading.Event()
        release = threading.Event()

        def _parked() -> list:
            entered.set()
            release.wait(_FETCH_HOLD_S)
            return _live_rows([(22, 147, 0.62, "4.00%")])

        S101._live_data_rows = _parked
        S101.source()
        self.assertTrue(entered.wait(_JOIN_S), "the refresh fetch never started")

        # A reset lands while the refresh is still out on the network; the
        # late publish must be dropped, not resurrect the dropped snapshot.
        S101._reset_cache()
        release.set()
        _join_background_refresh()
        self.assertFalse(
            S101._LOADED,
            "an in-flight refresh republished a snapshot after _reset_cache()",
        )


class FailSoftTests(LockBase):
    def test_accessors_swallow_a_raising_fetch(self) -> None:
        def _boom() -> list:
            raise RuntimeError("CN endpoint exploded")

        S101._live_data_rows = _boom
        S101._reset_cache()
        # Falls back to the committed static seed, no exception escapes.
        self.assertEqual(S101.source(), "static")
        self.assertIsInstance(S101.top_duos_for_bot("Ashe"), list)
        self.assertIsInstance(S101.top_duos_for_sup("Seraphine"), list)
        self.assertIsInstance(S101.top_solo_picks("bot"), list)
        self.assertIsInstance(S101.coverage(), dict)

    def test_source_stays_in_the_declared_domain(self) -> None:
        S101._live_data_rows = lambda: _live_rows([(22, 147, 0.61, "4.00%")])
        S101._reset_cache()
        self.assertIn(S101.source(), ("live", "static", "none"))


class AsciiHygieneTests(unittest.TestCase):
    def test_this_file_is_ascii(self) -> None:
        b = Path(__file__).read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])

    def test_module_is_ascii(self) -> None:
        b = (_ROOT / "core" / "smoothed_rates_101qq.py").read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
