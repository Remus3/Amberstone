"""RM-1329 (last part) - /api/cc-pairing and /api/peel-priority bound their response caches.

Defect (measured 2026-10-31 on the lane base):
  * Both modules kept a module-level ``_CACHE`` with a 300 s TTL that was
    checked only on READ, and no size bound. routes_cc_pairing keys on
    (sorted ally tuple, top_n); routes_peel_priority keys on (sorted ally
    tuple, mode). The ally entries are caller strings that
    ``_parse_champ_list`` does not filter (unknown ids pass through on
    purpose, fail-soft), so one query parameter alone mints a fresh key
    per request. The key space is unbounded: every distinct request
    stayed resident for the process lifetime.

Contract pinned here (the RM-1327 routes_ds_sweep ``_cache_put``
discipline, already applied to the other ten RM-1329 modules):
  * the cache never holds more than ``_CACHE_MAX`` entries and keeps the
    newest, which is still a cache hit;
  * an expired entry is dropped on the next write.

The engine is stubbed (each module's ``_compute``) so these tests pin the
cache contract, not card or verdict content (those are
tests/test_routes_cc_pairing.py and tests/test_routes_peel_priority.py).
"""

from __future__ import annotations

import json
import pathlib
import time
import unittest

from dashboard import routes_cc_pairing as pairing
from dashboard import routes_peel_priority as peel


class _Harness:
    """h._send(status, body, content_type) shape (both modules)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.body: bytes = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body

    def parsed(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


def _fake_compute(*_args):
    return {"ok": True, "cards": [], "count": 0}


class _Base(unittest.TestCase):
    mod = None
    route = ""
    handler_name = ""
    extra_query = ""

    def setUp(self) -> None:
        self.mod._reset_caches()
        self._orig = self.mod._compute
        self.mod._compute = _fake_compute

    def tearDown(self) -> None:
        self.mod._compute = self._orig
        self.mod._reset_caches()

    def _path(self, i: int) -> str:
        # An ally entry is a caller string, not filtered by
        # _parse_champ_list: every value is a distinct key.
        return f"{self.route}?ally=Synthetic{i}{self.extra_query}"

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        getattr(self.mod, self.handler_name)(h)
        return h


class _CacheBoundMixin:
    def test_cache_max_is_a_positive_int(self) -> None:
        cap = getattr(self.mod, "_CACHE_MAX", None)
        self.assertIsInstance(cap, int)
        self.assertGreater(cap, 0)

    def test_cache_never_exceeds_max_and_keeps_newest(self) -> None:
        cap = getattr(self.mod, "_CACHE_MAX", 256)
        total = cap + 40
        for i in range(total):
            h = self._do(self._path(i))
            self.assertEqual(h.status, 200, h.body)
            self.assertIs(h.parsed()["ok"], True, h.body)
            self.assertLessEqual(len(self.mod._CACHE), cap)
        # The oldest request was evicted, the newest is still a hit.
        h = self._do(self._path(total - 1))
        self.assertIs(h.parsed()["cached"], True)
        h = self._do(self._path(0))
        self.assertIs(h.parsed()["cached"], False)
        self.assertLessEqual(len(self.mod._CACHE), cap)

    def test_expired_entries_dropped_on_write(self) -> None:
        # Stamped on the module's own clock (time.time), well past the TTL.
        stale_key = ("Stale-sentinel",)
        self.mod._CACHE[stale_key] = (
            time.time() - self.mod._CACHE_TTL_S - 60.0, {"ok": True})
        h = self._do(self._path(1))
        self.assertEqual(h.status, 200, h.body)
        self.assertNotIn(stale_key, self.mod._CACHE)
        self.assertEqual(len(self.mod._CACHE), 1)

    def test_fresh_entry_survives_a_write(self) -> None:
        # Positive control: the bound must not evict a live entry below cap.
        self._do(self._path(1))
        self._do(self._path(2))
        self.assertEqual(len(self.mod._CACHE), 2)
        self.assertIs(self._do(self._path(1)).parsed()["cached"], True)

    def test_compute_failure_is_not_cached(self) -> None:
        # Positive control: a 503 compute failure writes no entry.
        def _boom(*_args):
            raise RuntimeError("synthetic")

        self.mod._compute = _boom
        h = self._do(self._path(1))
        self.assertEqual(h.status, 503, h.body)
        self.assertEqual(len(self.mod._CACHE), 0)


class CcPairingCacheBoundTests(_CacheBoundMixin, _Base):
    mod = pairing
    route = "/api/cc-pairing"
    handler_name = "_serve_cc_pairing"
    extra_query = "&top_n=6"


class PeelPriorityCacheBoundTests(_CacheBoundMixin, _Base):
    mod = peel
    route = "/api/peel-priority"
    handler_name = "_serve_peel_priority"
    extra_query = "&mode=SR"


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 0x80 for b in raw))
        self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
