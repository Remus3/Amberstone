"""Unit tests for the live duo-synergy fetch primitive (item 277).

core.synergy_external_source.fetch_rows - the Tencent getRankDouble live
fetch that powers the item-199 duo-synergy lane. The HTTP seam
(_http_get_json) is monkey-patched so these run offline + deterministic.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core import synergy_external_source as S  # noqa: E402


def _envelope(pairs):
    """Build a getRankDouble-shaped envelope from (c1, c2, wr, pick) tuples."""
    return {
        "code": 0,
        "message": "success",
        "data": [
            {
                "championid1": str(c1), "championid2": str(c2),
                "doublewinrate": wr, "iwinrate1": 0.5, "iwinrate2": 0.5,
                "itemp1": pick, "irank": i + 1,
                "lane1": "bottom", "lane2": "support",
            }
            for i, (c1, c2, wr, pick) in enumerate(pairs)
        ],
    }


class FetchRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        S._reset_cache_for_tests()
        self._calls: list[str] = []
        # deterministic clock + date
        self._t = [1000.0]
        S._clock = lambda: self._t[0]
        from datetime import datetime, timezone
        S._utcnow = lambda: datetime(2026, 6, 2, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        import time as _time
        from datetime import datetime, timezone
        S._clock = _time.monotonic
        S._utcnow = lambda: datetime.now(timezone.utc)
        S._reset_cache_for_tests()

    def _patch(self, fn) -> None:
        def wrapped(url, timeout_s=S._TIMEOUT_S):
            self._calls.append(url)
            return fn(url)
        S._http_get_json = wrapped

    def test_success_returns_rows(self) -> None:
        self._patch(lambda url: _envelope([(498, 497, 0.56, "4.42%")]))
        rows = S.fetch_rows("bottom", "support")
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["championid1"], "498")

    def test_invalid_lane_returns_none_without_fetch(self) -> None:
        self._patch(lambda url: _envelope([(1, 2, 0.5, "1%")]))
        self.assertIsNone(S.fetch_rows("bottom", "FOO"))
        self.assertEqual(self._calls, [], "must not hit the network for a bad lane")

    def test_http_failure_is_fail_soft(self) -> None:
        def boom(url):
            raise S.SynergyError("boom")
        self._patch(boom)
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        # tried each candidate date before giving up
        self.assertEqual(len(self._calls), S._DATE_LOOKBACK_DAYS)

    def test_date_fallback_on_empty(self) -> None:
        # first date -> code 0 but empty data; second date -> rows
        def by_date(url):
            return (_envelope([(498, 497, 0.56, "4.42%")])
                    if "20260531" in url else {"code": 0, "data": []})
        self._patch(by_date)
        rows = S.fetch_rows("bottom", "support")
        self.assertIsNotNone(rows)
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(len(self._calls), 2)

    def test_bad_code_is_fail_soft(self) -> None:
        self._patch(lambda url: {"code": 603, "message": "params can't be null", "data": []})
        self.assertIsNone(S.fetch_rows("bottom", "support"))

    def test_cache_hit_skips_refetch(self) -> None:
        self._patch(lambda url: _envelope([(498, 497, 0.56, "4.42%")]))
        S.fetch_rows("bottom", "support")
        n = len(self._calls)
        self._t[0] += 60.0  # within TTL
        S.fetch_rows("bottom", "support")
        self.assertEqual(len(self._calls), n, "second call within TTL must hit cache")

    def test_cache_expires_after_ttl(self) -> None:
        self._patch(lambda url: _envelope([(498, 497, 0.56, "4.42%")]))
        S.fetch_rows("bottom", "support")
        n = len(self._calls)
        self._t[0] += S._TTL_S + 1.0
        S.fetch_rows("bottom", "support")
        self.assertGreater(len(self._calls), n, "expired cache must refetch")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        b = (_ROOT / "core" / "synergy_external_source.py").read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])

    def test_this_file_is_ascii(self) -> None:
        b = Path(__file__).read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
