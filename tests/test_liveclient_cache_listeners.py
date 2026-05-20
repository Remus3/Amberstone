"""Tests for the snapshot listener API on ``core.liveclient_cache``.

The listener API was added to support the UX wave 1 ward-heat producer
wire (`core/ward_producer.tick_from_snapshot`). These tests cover the
add/remove/clear contract + exception isolation.
"""
from __future__ import annotations

import unittest

from core import liveclient_cache
from core.liveclient_cache import Snapshot


class ListenerApiTests(unittest.TestCase):
    def setUp(self):
        liveclient_cache.clear_listeners()

    def tearDown(self):
        liveclient_cache.clear_listeners()

    def test_add_listener_registers(self):
        calls = []
        liveclient_cache.add_listener(lambda s: calls.append(s))
        snap = Snapshot(data={"x": 1}, ts=1.0, fetched_at=1.0)
        liveclient_cache._fire_listeners(snap)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0], snap)

    def test_add_listener_idempotent_by_identity(self):
        fn = lambda s: None
        liveclient_cache.add_listener(fn)
        liveclient_cache.add_listener(fn)
        liveclient_cache.add_listener(fn)
        self.assertEqual(len(liveclient_cache._listeners), 1)

    def test_remove_listener(self):
        fn = lambda s: None
        liveclient_cache.add_listener(fn)
        liveclient_cache.remove_listener(fn)
        self.assertEqual(len(liveclient_cache._listeners), 0)

    def test_remove_unregistered_noop(self):
        liveclient_cache.remove_listener(lambda s: None)
        self.assertEqual(len(liveclient_cache._listeners), 0)

    def test_clear_listeners(self):
        liveclient_cache.add_listener(lambda s: None)
        liveclient_cache.add_listener(lambda s: None)
        liveclient_cache.clear_listeners()
        self.assertEqual(len(liveclient_cache._listeners), 0)

    def test_fire_listeners_isolates_exceptions(self):
        calls = []
        def boomer(snap):
            raise RuntimeError("boom")
        def good(snap):
            calls.append(snap)
        liveclient_cache.add_listener(boomer)
        liveclient_cache.add_listener(good)
        snap = Snapshot(data={}, ts=1.0, fetched_at=1.0)
        # Should not raise; the good listener still fires.
        liveclient_cache._fire_listeners(snap)
        self.assertEqual(len(calls), 1)

    def test_fire_listeners_passes_snapshot(self):
        seen = []
        liveclient_cache.add_listener(lambda s: seen.append(s.data))
        snap = Snapshot(data={"k": "v"}, ts=2.0, fetched_at=2.0)
        liveclient_cache._fire_listeners(snap)
        self.assertEqual(seen, [{"k": "v"}])


if __name__ == "__main__":
    unittest.main()
