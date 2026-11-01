"""RM-1329 (part) - /api/ds-relscore and /api/ds-skill-order bound their response caches.

Defect (measured 2026-10-31 on the lane base):
  * Both modules kept a module-level ``_CACHE`` with a 300 s TTL that was
    checked only on READ, and no size bound. relscore's key is
    (champion, mode, sorted items, level): the champion is the caller's
    string verbatim, mode has no allow-list and the item list is free
    text. skill_order's key is (champion, mode): ``_resolve_champion``
    takes a non-numeric token verbatim, and a no_skill_order answer is
    cached too. So the key space is unbounded: every distinct request
    stayed resident for the process lifetime.

Contract pinned here (the RM-1327 routes_ds_sweep ``_cache_put``
discipline, already applied to routes_ds_combo / routes_ds_knobs /
routes_ds_matchup / routes_ds_profile):
  * the cache never holds more than ``_CACHE_MAX`` entries and keeps the
    newest, which is still a cache hit;
  * an expired entry is dropped on the next write.

The engine is stubbed (``mod._compute``) so these tests pin the cache
contract, not relscore / skill-order numbers (those are
tests/test_routes_ds_relscore.py and tests/test_routes_ds_skill_order.py).
"""

from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_relscore as relscore
from dashboard import routes_ds_skill_order as skill_order


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


class _RelscoreBase(unittest.TestCase):
    mod = relscore

    def setUp(self) -> None:
        relscore._reset_caches()
        self._orig = relscore._compute

        def _fake(champion, mode, items, level):
            return {"ok": True, "champion": champion, "rows": [],
                    "count": 0}

        relscore._compute = _fake

    def tearDown(self) -> None:
        relscore._compute = self._orig
        relscore._reset_caches()

    def _path(self, i: int) -> str:
        # The champion string is taken verbatim: every value is a distinct
        # key. No items, so the non-inventory filter has nothing to drop.
        return f"/api/ds-relscore?champion=Champ{i}"

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        relscore._serve_ds_relscore(h)
        return h


class _SkillOrderBase(unittest.TestCase):
    mod = skill_order

    def setUp(self) -> None:
        skill_order._reset_caches()
        self._orig = skill_order._compute

        def _fake(champion, mode):
            return {"ok": True, "champion": champion, "mode": mode,
                    "skill_order": []}

        skill_order._compute = _fake

    def tearDown(self) -> None:
        skill_order._compute = self._orig
        skill_order._reset_caches()

    def _path(self, i: int) -> str:
        # A non-numeric champion token is taken verbatim by
        # _resolve_champion: every value is a distinct key.
        return f"/api/ds-skill-order?champion=Champ{i}"

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        skill_order._serve_ds_skill_order(h)
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


class RelscoreCacheBoundTests(_CacheBoundMixin, _RelscoreBase):
    pass


class SkillOrderCacheBoundTests(_CacheBoundMixin, _SkillOrderBase):
    pass


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 0x80 for b in raw))
        self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
