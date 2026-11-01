"""RM-1329 (part) - /api/ds-matchup and /api/ds-profile bound their response caches.

Defect (measured 2026-10-31 on the lane base):
  * Both modules kept a module-level ``_CACHE`` with a 300 s TTL that was
    checked only on READ, and no size bound. The keys carry the caller's
    champion string(s) (a non-numeric token is taken verbatim by
    ``_resolve_champion``) and the caller's ``mode`` string, and a
    no_matchup / no_profile answer is cached too, so the key space is
    unbounded: every distinct request stayed resident for the process
    lifetime.

Contract pinned here (the RM-1327 routes_ds_sweep ``_cache_put``
discipline, already applied to routes_ds_combo / routes_ds_knobs):
  * the cache never holds more than ``_CACHE_MAX`` entries and keeps the
    newest, which is still a cache hit;
  * an expired entry is dropped on the next write.

The engine is stubbed (``mod._compute``) so these tests pin the cache
contract, not matchup / profile numbers (those are
tests/test_routes_ds_matchup.py and tests/test_routes_ds_profile.py).
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_matchup as matchup
from dashboard import routes_ds_profile as profile


class _Harness:
    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.body: bytes = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body

    def parsed(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


class _MatchupBase(unittest.TestCase):
    mod = matchup

    def setUp(self) -> None:
        matchup._reset_caches()
        self._orig = matchup._compute

        def _fake(champ_a, champ_b, level_a, level_b, mode):
            return {"ok": True, "champ_a": champ_a, "champ_b": champ_b,
                    "mode": mode}

        matchup._compute = _fake

    def tearDown(self) -> None:
        matchup._compute = self._orig
        matchup._reset_caches()

    def _path(self, i: int) -> str:
        # A non-numeric champion token is taken verbatim: every value is a
        # distinct key.
        return f"/api/ds-matchup?champ_a=Champ{i}&champ_b=Other"

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        matchup._serve_ds_matchup(h)
        return h


class _ProfileBase(unittest.TestCase):
    mod = profile

    def setUp(self) -> None:
        profile._reset_caches()
        self._orig = profile._compute

        def _fake(champion, mode):
            return {"ok": True, "champion": champion, "mode": mode,
                    "axes": []}

        profile._compute = _fake

    def tearDown(self) -> None:
        profile._compute = self._orig
        profile._reset_caches()

    def _path(self, i: int) -> str:
        return f"/api/ds-profile?champion=Champ{i}"

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        profile._serve_ds_profile(h)
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
            self.assertLessEqual(len(self.mod._CACHE), cap)
        # The oldest request was evicted, the newest is still a hit.
        h = self._do(self._path(total - 1))
        self.assertIs(h.parsed()["cached"], True)
        h = self._do(self._path(0))
        self.assertIs(h.parsed()["cached"], False)
        self.assertLessEqual(len(self.mod._CACHE), cap)

    def test_expired_entries_dropped_on_write(self) -> None:
        stale_key = ("Stale-sentinel",)
        self.mod._CACHE[stale_key] = (0.0, {"ok": True})
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


class MatchupCacheBoundTests(_CacheBoundMixin, _MatchupBase):
    pass


class ProfileCacheBoundTests(_CacheBoundMixin, _ProfileBase):
    pass


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 0x80 for b in raw))
        self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
