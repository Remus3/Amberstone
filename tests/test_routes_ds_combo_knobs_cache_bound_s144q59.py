"""RM-1329 (part) - /api/ds-combo and /api/ds-knobs bound their response caches.

Defect (measured 2026-10-31 on the lane base):
  * Both modules kept a module-level ``_CACHE`` with a 300 s TTL that was
    checked only on READ, and no size bound. The keys carry free-form
    floats (target_armor / target_mr / target_max_hp / target_bonus_hp /
    fight_length), the champion string and the item / seq / rune lists, so
    the key space is unbounded: every distinct request stayed resident for
    the process lifetime.

Contract pinned here (the RM-1327 routes_ds_sweep ``_cache_put``
discipline):
  * the cache never holds more than ``_CACHE_MAX`` entries and keeps the
    newest, which is still a cache hit;
  * an expired entry is dropped on the next write.

The engine is stubbed (``mod._compute``) so these tests pin the cache
contract, not combo / rank numbers (those are tests/test_routes_ds_combo.py
and tests/test_routes_ds_knobs.py).
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_combo as combo
from dashboard import routes_ds_knobs as knobs


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


class _ComboBase(unittest.TestCase):
    mod = combo

    def setUp(self) -> None:
        combo._reset_caches()
        self._orig = combo._compute

        def _fake(champion, level, items, seq, target_armor, target_mr,
                  target_max_hp, target_bonus_hp, mode, runes):
            return {"ok": True, "champion": champion, "mode": mode,
                    "hits": [], "count": 0}

        combo._compute = _fake

    def tearDown(self) -> None:
        combo._compute = self._orig
        combo._reset_caches()

    def _path(self, i: int) -> str:
        # target_armor is a free float: every value is a distinct key.
        return f"/api/ds-combo?champion=Champ&seq=Q,W&target_armor={i}"

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        combo._serve_ds_combo(h)
        return h


class _KnobsBase(unittest.TestCase):
    mod = knobs

    def setUp(self) -> None:
        knobs._reset_caches()
        self._orig = knobs._compute

        def _fake(champion, mode, items, level, armor_override, mr_override,
                  budget, fight_length=None):
            return {"ok": True, "champion": champion, "mode": mode,
                    "rows": [], "count": 0}

        knobs._compute = _fake

    def tearDown(self) -> None:
        knobs._compute = self._orig
        knobs._reset_caches()

    def _path(self, i: int) -> str:
        return f"/api/ds-knobs?champion=Champ&target_armor={i}"

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        knobs._serve_ds_knobs(h)
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
        before = len(self.mod._CACHE)
        h = self._do(self._path(0))
        self.assertIs(h.parsed()["cached"], False)
        self.assertLessEqual(len(self.mod._CACHE), cap)
        self.assertLessEqual(before, cap)

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


class ComboCacheBoundTests(_CacheBoundMixin, _ComboBase):
    pass


class KnobsCacheBoundTests(_CacheBoundMixin, _KnobsBase):
    pass


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 0x80 for b in raw))
        self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
