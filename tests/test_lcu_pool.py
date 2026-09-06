# arch: port-safety pooled-connection + min-interval primitives (RC2 P6.4) | section=test | frozen=no
"""Tests for core/lcu_pool.py - L6 connection reuse + L7 min-interval guard.

Deterministic: a FakeConnection stands in for http.client.HTTPSConnection so
no real sockets are opened. Covers reuse, reconnect-on-drop, fail-soft, the
RC_LCU_POOL gate (DEFAULT-ON since the E7 flip 2026-06-30 - see
test_default_on; explicit RC_LCU_POOL=0 is the only way off), and the shared
min-interval rate floor.
"""
import os
import unittest

from core import lcu_pool


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class _FakeConn:
    """Stands in for http.client.HTTPSConnection. Counts requests; can be
    told to raise on a specific 0-based request index to simulate a peer
    that dropped a kept-alive socket."""
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.requests = []
        self.closed = 0
        self.raise_on = set()
        self.status = 200
        self.body = b'{"ok": true}'
        _FakeConn.instances.append(self)

    def request(self, method, path, body=None, headers=None):
        idx = len(self.requests)
        self.requests.append((method, path, body, headers))
        if idx in self.raise_on:
            raise OSError("simulated dropped socket")

    def getresponse(self):
        return _FakeResp(self.status, self.body)

    def close(self):
        self.closed += 1


def _factory():
    def make(host, port):
        return _FakeConn(host, port)
    return make


class HttpsConnectionPoolTests(unittest.TestCase):
    def setUp(self):
        _FakeConn.instances = []

    def test_reuses_one_connection_per_host_port(self):
        pool = lcu_pool.HttpsConnectionPool(connection_factory=_factory())
        a = pool.request("127.0.0.1", 5000, "GET", "/x")
        b = pool.request("127.0.0.1", 5000, "GET", "/y")
        self.assertEqual(a, (200, b'{"ok": true}'))
        self.assertEqual(b, (200, b'{"ok": true}'))
        self.assertEqual(len(_FakeConn.instances), 1)  # single socket reused
        self.assertEqual(len(_FakeConn.instances[0].requests), 2)

    def test_distinct_ports_get_distinct_connections(self):
        pool = lcu_pool.HttpsConnectionPool(connection_factory=_factory())
        pool.request("127.0.0.1", 5000, "GET", "/x")
        pool.request("127.0.0.1", 6000, "GET", "/x")
        self.assertEqual(len(_FakeConn.instances), 2)

    def test_reconnect_on_dropped_socket(self):
        made = []

        def make(host, port):
            c = _FakeConn(host, port)
            if not made:  # first connection drops on its 2nd request
                c.raise_on = {1}
            made.append(c)
            return c

        pool = lcu_pool.HttpsConnectionPool(connection_factory=make)
        self.assertEqual(pool.request("h", 1, "GET", "/a"), (200, b'{"ok": true}'))
        # 2nd call: first conn raises -> pool closes it, rebuilds, retries OK
        self.assertEqual(pool.request("h", 1, "GET", "/b"), (200, b'{"ok": true}'))
        self.assertEqual(len(_FakeConn.instances), 2)
        self.assertEqual(_FakeConn.instances[0].closed, 1)

    def test_double_failure_is_fail_soft_none(self):
        def make(host, port):
            c = _FakeConn(host, port)
            c.raise_on = {0}  # every fresh conn fails immediately
            return c

        pool = lcu_pool.HttpsConnectionPool(connection_factory=make)
        self.assertIsNone(pool.request("h", 1, "GET", "/a"))
        # both the original and the one reconnect attempt were closed
        self.assertEqual(len(_FakeConn.instances), 2)

    def test_close_all_drops_every_connection(self):
        pool = lcu_pool.HttpsConnectionPool(connection_factory=_factory())
        pool.request("127.0.0.1", 5000, "GET", "/x")
        pool.request("127.0.0.1", 6000, "GET", "/x")
        pool.close_all()
        self.assertTrue(all(c.closed >= 1 for c in _FakeConn.instances))


class PoolEnabledTests(unittest.TestCase):
    def _set(self, val):
        if val is None:
            os.environ.pop("RC_LCU_POOL", None)
        else:
            os.environ["RC_LCU_POOL"] = val
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))

    def test_default_on(self):
        # E7 flip 2026-06-30: pooling is DEFAULT-ON (validated live - one
        # persistent LCU socket held ~3 min, zero SSL EOF). An UNSET env now
        # opts IN; explicit RC_LCU_POOL=0 is the only way to force the legacy
        # per-call path (see test_falsy_values_off).
        self._set(None)
        self.assertTrue(lcu_pool.pool_enabled())

    def test_truthy_values_on(self):
        for v in ("1", "true", "TRUE", "yes", "on"):
            self._set(v)
            self.assertTrue(lcu_pool.pool_enabled(), v)

    def test_falsy_values_off(self):
        for v in ("0", "false", "no", "off", ""):
            self._set(v)
            self.assertFalse(lcu_pool.pool_enabled(), v)


class MinIntervalGuardTests(unittest.TestCase):
    def test_first_ready_then_blocked_until_interval(self):
        t = [100.0]
        g = lcu_pool.MinIntervalGuard(1.5, clock=lambda: t[0])
        self.assertTrue(g.ready())          # first call always ready
        self.assertFalse(g.ready())         # immediate repeat blocked
        t[0] += 1.4
        self.assertFalse(g.ready())         # still under floor
        t[0] += 0.2
        self.assertTrue(g.ready())          # 1.6s elapsed -> ready

    def test_keys_are_independent(self):
        t = [0.0]
        g = lcu_pool.MinIntervalGuard(1.0, clock=lambda: t[0])
        self.assertTrue(g.ready("a"))
        self.assertTrue(g.ready("b"))       # different key, own floor
        self.assertFalse(g.ready("a"))

    def test_time_until_ready(self):
        t = [0.0]
        g = lcu_pool.MinIntervalGuard(2.0, clock=lambda: t[0])
        g.ready()
        self.assertAlmostEqual(g.time_until_ready(), 2.0, places=3)
        t[0] += 0.5
        self.assertAlmostEqual(g.time_until_ready(), 1.5, places=3)


class SharedPoolTests(unittest.TestCase):
    def test_shared_pool_is_singleton(self):
        self.assertIs(lcu_pool.get_shared_pool(), lcu_pool.get_shared_pool())


class PollerPilotTests(unittest.TestCase):
    """game_reader.poller._lcu_get pilot: explicit RC_LCU_POOL=0 uses urlopen
    byte-for-byte; default / RC_LCU_POOL=1 routes through the shared pool
    (E7 flipped the default ON 2026-06-30)."""

    def _stub(self):
        from game_reader.poller import _PollerMixin
        obj = _PollerMixin.__new__(_PollerMixin)
        obj._lcu_port = "5000"
        obj._lcu_auth = "QUJD"
        obj._ssl = None
        return obj

    def test_pool_off_uses_urlopen(self):
        os.environ["RC_LCU_POOL"] = "0"  # explicit off; default is now ON (E7)
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))
        import game_reader.poller as pmod

        calls = []

        class _R:
            def read(self):
                return b'{"via": "urlopen"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, context=None, timeout=None):
            calls.append(req.full_url)
            return _R()

        orig = pmod.urllib.request.urlopen
        pmod.urllib.request.urlopen = fake_urlopen
        self.addCleanup(lambda: setattr(pmod.urllib.request, "urlopen", orig))
        out = self._stub()._lcu_get("/x")
        self.assertEqual(out, {"via": "urlopen"})
        self.assertEqual(len(calls), 1)

    def test_pool_on_routes_through_pool(self):
        os.environ["RC_LCU_POOL"] = "1"
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))
        seen = {}

        class _P:
            def request(self, host, port, method, path, headers=None, body=None):
                seen.update(host=host, port=port, method=method,
                            path=path, headers=headers)
                return (200, b'{"via": "pool"}')

        orig = lcu_pool.get_shared_pool
        lcu_pool.get_shared_pool = lambda: _P()
        self.addCleanup(lambda: setattr(lcu_pool, "get_shared_pool", orig))
        out = self._stub()._lcu_get("/lol-champ-select/v1/session")
        self.assertEqual(out, {"via": "pool"})
        self.assertEqual(seen["path"], "/lol-champ-select/v1/session")
        self.assertEqual(seen["method"], "GET")
        self.assertIn("Authorization", seen["headers"])


class LcuClientPoolPilotTests(unittest.TestCase):
    """lcu.lcu_client.LcuClient._request pilot (E7, operator frozen-grant
    2026-06-30): explicit RC_LCU_POOL=0 uses urlopen byte-for-byte; default /
    RC_LCU_POOL=1 routes the every-tick auto-accept path through the shared
    pool (E7 flipped the default ON 2026-06-30). Because
    _request returns {} for an empty body and None on error (and callers
    like _maybe_apply_runes treat any dict as a valid session), the pooled
    path preserves that contract: a non-2xx pooled response returns None
    (mirrors urlopen HTTPError -> None) and a fail-soft pool None falls
    through to the per-call urlopen read."""

    def _stub(self):
        from lcu.lcu_client import LcuClient
        obj = LcuClient.__new__(LcuClient)
        obj._port = 5000
        obj._auth = "QUJD"
        obj._ssl = None
        return obj

    def test_pool_off_uses_urlopen(self):
        os.environ["RC_LCU_POOL"] = "0"  # explicit off; default is now ON (E7)
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))
        import lcu.lcu_client as cmod

        calls = []

        class _R:
            def read(self):
                return b'{"via": "urlopen"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, context=None, timeout=None):
            calls.append(req.full_url)
            return _R()

        orig = cmod.urllib.request.urlopen
        cmod.urllib.request.urlopen = fake_urlopen
        self.addCleanup(lambda: setattr(cmod.urllib.request, "urlopen", orig))
        out = self._stub()._request("GET", "/x")
        self.assertEqual(out, {"via": "urlopen"})
        self.assertEqual(len(calls), 1)

    def test_pool_on_routes_through_pool(self):
        os.environ["RC_LCU_POOL"] = "1"
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))
        seen = {}

        class _P:
            def request(self, host, port, method, path, headers=None, body=None):
                seen.update(host=host, port=port, method=method,
                            path=path, headers=headers, body=body)
                return (200, b'{"via": "pool"}')

        orig = lcu_pool.get_shared_pool
        lcu_pool.get_shared_pool = lambda: _P()
        self.addCleanup(lambda: setattr(lcu_pool, "get_shared_pool", orig))
        out = self._stub()._request("GET", "/lol-champ-select/v1/session")
        self.assertEqual(out, {"via": "pool"})
        self.assertEqual(seen["path"], "/lol-champ-select/v1/session")
        self.assertEqual(seen["method"], "GET")
        self.assertIn("Authorization", seen["headers"])

    def test_pool_on_post_passes_json_body(self):
        os.environ["RC_LCU_POOL"] = "1"
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))
        seen = {}

        class _P:
            def request(self, host, port, method, path, headers=None, body=None):
                seen.update(method=method, body=body)
                return (200, b"")  # empty body -> {} per the contract

        orig = lcu_pool.get_shared_pool
        lcu_pool.get_shared_pool = lambda: _P()
        self.addCleanup(lambda: setattr(lcu_pool, "get_shared_pool", orig))
        out = self._stub()._request("POST", "/x", {"code": "abc"})
        self.assertEqual(out, {})  # empty body decodes to {}
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["body"], b'{"code": "abc"}')

    def test_pool_non_2xx_returns_none(self):
        os.environ["RC_LCU_POOL"] = "1"
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))

        class _P:
            def request(self, *a, **k):
                return (404, b'{"errorCode": "RPC_ERROR"}')

        orig = lcu_pool.get_shared_pool
        lcu_pool.get_shared_pool = lambda: _P()
        self.addCleanup(lambda: setattr(lcu_pool, "get_shared_pool", orig))
        # A 404 error body must NOT leak as a dict to _maybe_apply_runes.
        out = self._stub()._request("GET", "/lol-champ-select/v1/session")
        self.assertIsNone(out)

    def test_pool_fail_soft_none_falls_through_to_urlopen(self):
        os.environ["RC_LCU_POOL"] = "1"
        self.addCleanup(lambda: os.environ.pop("RC_LCU_POOL", None))
        import lcu.lcu_client as cmod

        class _P:
            def request(self, *a, **k):
                return None  # connection-level fail-soft

        class _R:
            def read(self):
                return b'{"via": "urlopen_fallback"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, context=None, timeout=None):
            return _R()

        orig_pool = lcu_pool.get_shared_pool
        lcu_pool.get_shared_pool = lambda: _P()
        self.addCleanup(lambda: setattr(lcu_pool, "get_shared_pool", orig_pool))
        orig_uo = cmod.urllib.request.urlopen
        cmod.urllib.request.urlopen = fake_urlopen
        self.addCleanup(lambda: setattr(cmod.urllib.request, "urlopen", orig_uo))
        out = self._stub()._request("GET", "/x")
        self.assertEqual(out, {"via": "urlopen_fallback"})


class RelaySelfReadFloorTests(unittest.TestCase):
    """L8 regression: the :2999 direct self-read throttle must never drop
    below the 1.5s hard floor documented in the port-safety audit."""

    def test_relay_self_read_floor_at_least_1_5s(self):
        from vision_server import _relay
        self.assertGreaterEqual(_relay._SELF_READ_MIN_INTERVAL_S, 1.5)


if __name__ == "__main__":
    unittest.main()
