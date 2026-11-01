"""RM-1329 (part) - /api/ds-statcheck and /api/spike-markers bound their response caches.

Defect (measured 2026-10-31 on the lane base):
  * Both modules kept a module-level ``_CACHE`` with a 300 s TTL that was
    checked only on READ, and no size bound. statcheck's key is
    (champion, mode, sorted items, target_armor, target_mr, target_hp,
    target_bonus_hp, level): the champion and mode are caller strings and
    the four target values are caller floats, so one numeric query
    parameter alone mints a fresh key per request. spike_markers' key is
    (champion, level, sorted items, mode, item_count, minor): level and
    item_count are unclamped caller ints and mode has no allow-list. So
    the key space is unbounded: every distinct request stayed resident
    for the process lifetime.

Contract pinned here (the RM-1327 routes_ds_sweep ``_cache_put``
discipline, already applied to routes_ds_combo / routes_ds_knobs /
routes_ds_matchup / routes_ds_profile / routes_ds_relscore /
routes_ds_skill_order):
  * the cache never holds more than ``_CACHE_MAX`` entries and keeps the
    newest, which is still a cache hit;
  * an expired entry is dropped on the next write.

The engine is stubbed (statcheck ``_load_engine``, spike_markers
``_compute``) so these tests pin the cache contract, not stat or marker
numbers (those are tests/test_routes_ds_statcheck.py and
tests/test_routes_spike_markers.py).
"""

from __future__ import annotations

import io
import json
import pathlib
import time
import types
import unittest

from dashboard import routes_ds_statcheck as statcheck
from dashboard import routes_spike_markers as spike


class _SpikeHarness:
    """h._send(status, body, content_type) shape (routes_spike_markers)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.body: bytes = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body

    def parsed(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


class _StatcheckHarness:
    """BaseHTTPRequestHandler shape (routes_ds_statcheck._send)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.wfile = io.BytesIO()

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, name: str, value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    @property
    def body(self) -> bytes:
        return self.wfile.getvalue()

    def parsed(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


class _StatcheckBase(unittest.TestCase):
    mod = statcheck

    def setUp(self) -> None:
        statcheck._reset_caches()
        self._orig = statcheck._load_engine

        def _fake_dps(snap, *, champion_id, **_kw):
            return types.SimpleNamespace(
                champion_name=champion_id, stats={"ad": 60.0},
                weighted_dps=100.0, phase="mid")

        statcheck._load_engine = lambda: (None, _fake_dps)

    def tearDown(self) -> None:
        statcheck._load_engine = self._orig
        statcheck._reset_caches()

    def _now(self) -> float:
        return time.monotonic()

    def _path(self, i: int) -> str:
        # target_armor is a caller float taken into the key as is: every
        # value is a distinct key. target_mr is pinned so the auto
        # enemy-stat curve is never consulted.
        return (f"/api/ds-statcheck?champion=Ahri&target_armor={i}"
                "&target_mr=30")

    def _do(self, path: str) -> _StatcheckHarness:
        h = _StatcheckHarness(path)
        statcheck._serve_ds_statcheck(h)
        return h


class _SpikeBase(unittest.TestCase):
    mod = spike

    def setUp(self) -> None:
        spike._reset_caches()
        self._orig = spike._compute

        def _fake(champion, level, items, mode, item_count, minor):
            return {"ok": True, "champion": champion, "level": level,
                    "item_count_done": 0,
                    "markers": [{"kind": "level", "at": 6}],
                    "next": None, "count": 1}

        spike._compute = _fake

    def tearDown(self) -> None:
        spike._compute = self._orig
        spike._reset_caches()

    def _now(self) -> float:
        return time.time()

    def _path(self, i: int) -> str:
        # level is an unclamped caller int: every value is a distinct key.
        return f"/api/spike-markers?champion=Ahri&level={i}"

    def _do(self, path: str) -> _SpikeHarness:
        h = _SpikeHarness(path)
        spike._serve_spike_markers(h)
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
        # Stamped on the module's own clock, well past the TTL.
        stale_key = ("Stale-sentinel",)
        self.mod._CACHE[stale_key] = (
            self._now() - self.mod._CACHE_TTL_S - 60.0, {"ok": True})
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


class StatcheckCacheBoundTests(_CacheBoundMixin, _StatcheckBase):
    pass


class SpikeMarkersCacheBoundTests(_CacheBoundMixin, _SpikeBase):
    pass


class AsciiTests(unittest.TestCase):
    def test_this_file_is_ascii_lf(self) -> None:
        raw = pathlib.Path(__file__).read_bytes()
        self.assertTrue(all(b < 0x80 for b in raw))
        self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
