"""RM-1327 - /api/ds-sweep refuses an unsupported mode and bounds its cache.

Defect (measured 2026-10-31 on the lane base):
  * ``mode`` was upper-cased and accepted verbatim. The DS engine treats an
    unknown mode as SR (``compute_dps_sweep(..., mode="ZZQ")`` returned the
    exact SR points for Caitlyn), so the route answered 200 with SR numbers
    under the caller's made-up label and echoed that label in the body.
  * ``_CACHE`` had no size bound and TTL was checked only on read, so every
    distinct (champion, mode, item_ids, ...) key stayed resident for the
    process lifetime.

Contract pinned here:
  * a mode outside SR / ARAM / ARENA / BRAWL is a 400 with a fixed text and
    the supported list (the /api/spike-curve shape), never the caller's
    value, and the engine is not called;
  * a supported mode in any case reaches the engine upper-cased;
  * the cache never holds more than ``_CACHE_MAX`` entries, keeps the newest,
    and drops expired entries on write.

The engine is stubbed (``rt._compute``) so these tests pin the route
contract, not DPS numbers (those are tests/test_routes_ds_sweep.py).
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_sweep as rt


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


class _StubbedBase(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()
        self.calls: list[tuple] = []
        self._orig_compute = rt._compute

        def _fake(champion, axis, item_ids, mode, level, max_v, step):
            self.calls.append((champion, axis, mode))
            return {"ok": True, "champion": champion, "axis": axis,
                    "mode": mode, "level": level, "item_ids": [],
                    "points": [{"x": 0.0, "dps": 1.0, "phase": "mid"}],
                    "count": 1}

        rt._compute = _fake

    def tearDown(self) -> None:
        rt._compute = self._orig_compute
        rt._reset_caches()

    def _do(self, path: str) -> _Harness:
        h = _Harness(path)
        rt._serve_ds_sweep(h)
        return h


class ModeValidationTests(_StubbedBase):
    def test_unknown_mode_is_400_with_fixed_text(self) -> None:
        h = self._do("/api/ds-sweep?champion=Caitlyn&axis=armor&mode=zzqmode")
        self.assertEqual(h.status, 400)
        body = h.parsed()
        self.assertEqual(body["error"], "unsupported mode")
        self.assertIs(body["ok"], False)
        self.assertEqual(body["supported"], ["SR", "ARAM", "ARENA", "BRAWL"])
        self.assertNotIn(b"ZZQMODE", h.body.upper())
        self.assertEqual(self.calls, [], "engine must not run on a bad mode")

    def test_unknown_mode_is_not_cached(self) -> None:
        self._do("/api/ds-sweep?champion=Caitlyn&axis=armor&mode=URF")
        self.assertEqual(len(rt._CACHE), 0)

    def test_supported_modes_reach_engine_uppercased(self) -> None:
        for raw in ("sr", "Aram", "ARENA", "brawl"):
            h = self._do(f"/api/ds-sweep?champion=Caitlyn&axis=armor&mode={raw}")
            self.assertEqual(h.status, 200, raw)
            self.assertEqual(h.parsed()["mode"], raw.upper())
        self.assertEqual([c[2] for c in self.calls],
                         ["SR", "ARAM", "ARENA", "BRAWL"])

    def test_blank_and_absent_mode_default_to_sr(self) -> None:
        for path in ("/api/ds-sweep?champion=Caitlyn",
                     "/api/ds-sweep?champion=Caitlyn&mode="):
            h = self._do(path)
            self.assertEqual(h.status, 200, path)
            self.assertEqual(h.parsed()["mode"], "SR")


class CacheBoundTests(_StubbedBase):
    def test_cache_never_exceeds_max_and_keeps_newest(self) -> None:
        total = rt._CACHE_MAX + 40
        for i in range(total):
            h = self._do(f"/api/ds-sweep?champion=Champ{i}&axis=armor")
            self.assertEqual(h.status, 200)
            self.assertLessEqual(len(rt._CACHE), rt._CACHE_MAX)
        champs = {k[0] for k in rt._CACHE}
        self.assertIn(f"Champ{total - 1}", champs)
        self.assertNotIn("Champ0", champs)
        # The newest entry is still a cache hit.
        h = self._do(f"/api/ds-sweep?champion=Champ{total - 1}&axis=armor")
        self.assertIs(h.parsed()["cached"], True)

    def test_expired_entries_dropped_on_write(self) -> None:
        stale_key = ("Stale", "target_armor", (), "SR", 11, 300, 25)
        rt._CACHE[stale_key] = (0.0, {"ok": True})
        self._do("/api/ds-sweep?champion=Fresh&axis=armor")
        self.assertNotIn(stale_key, rt._CACHE)
        self.assertEqual(len(rt._CACHE), 1)


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 0x80 for b in raw))
        self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
