"""RM-345 - the LCU pool must not blindly re-send a non-idempotent write.

core/lcu_pool.py retried EVERY pooled request twice (`for attempt in (0, 1)`),
and the fault it catches - http.client.HTTPException / OSError / EOFError - is
raised by `conn.getresponse()` too, i.e. AFTER the request bytes are already on
the wire. The peer may have processed the write and only the response was lost,
so a blind retry double-applies it.

That is live today, not latent: core/lcu_pool.py:43 defaults RC_LCU_POOL to "1",
and lcu/lcu_client.py:186-190 routes EVERY method through the pool, including
POST /lol-matchmaking/v1/ready-check/accept, POST /lol-perks/v1/pages and
POST /lol-champ-select/v1/session/bench/swap/{champ_id}.

These tests pin the new contract:
  - idempotent-by-RFC methods (GET/HEAD/PUT/DELETE/OPTIONS/TRACE) STILL retry
    once on a dropped kept-alive socket - the L6 self-heal is preserved;
  - non-idempotent methods (POST/PATCH, and anything unrecognised) are sent
    exactly ONCE and fail soft to the documented None.

The fake connection is built against the real pool surface, cited line by line:
  core/lcu_pool.py:68  connection_factory: Callable[[str, int], object]
  core/lcu_pool.py:93  conn = self._factory(key[0], key[1])   -> f(host, port)
  core/lcu_pool.py:101 conn.close()                           -> close()
  core/lcu_pool.py:127 conn.request(method, path, body, hdrs) -> 4 positional
  core/lcu_pool.py:128 resp = conn.getresponse()              -> getresponse()
  core/lcu_pool.py:129 data = resp.read()                     -> resp.read()
  core/lcu_pool.py:130 return (resp.status, data)             -> resp.status
  core/lcu_pool.py:135 return None                            -> give-up value
"""
import http.client
import unittest

from core import lcu_pool

_OK_BODY = b'{"ok": true}'


class _FakeResp:
    """Response stand-in - core/lcu_pool.py:129-130 reads .read() and .status."""

    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class _FakeConn:
    """http.client.HTTPSConnection stand-in.

    request() records BEFORE it can fail, mirroring the real client where the
    bytes are already written by the time getresponse() discovers the peer hung
    up. Every conn a single factory builds appends to one shared log, so the
    total number of times the request was put on the wire is len(factory.sent).
    """

    def __init__(self, host, port, sent):
        self.host = host
        self.port = port
        self.sent = sent          # shared across every conn from one factory
        self.requests = []        # this conn's own writes
        self.closed = 0
        self.fail_getresponse = False
        self.status = 200
        self.body = _OK_BODY

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))
        self.sent.append((method, path, body, headers))

    def getresponse(self):
        if self.fail_getresponse:
            self.fail_getresponse = False
            raise http.client.RemoteDisconnected("Remote end closed connection")
        return _FakeResp(self.status, self.body)

    def close(self):
        self.closed += 1


class _Factory:
    """connection_factory per core/lcu_pool.py:68, invoked as f(host, port)."""

    def __init__(self, fail_first=1):
        self.sent = []
        self.conns = []
        self._fail_first = fail_first

    def __call__(self, host, port):
        conn = _FakeConn(host, port, self.sent)
        if len(self.conns) < self._fail_first:
            conn.fail_getresponse = True
        self.conns.append(conn)
        return conn


def _pool(factory):
    return lcu_pool.HttpsConnectionPool(connection_factory=factory)


class NonIdempotentIsSentOnceTests(unittest.TestCase):
    """The RM-345 defect proper: a write must never be replayed."""

    def test_patch_is_sent_exactly_once_when_the_socket_drops(self):
        factory = _Factory(fail_first=1)
        out = _pool(factory).request(
            "127.0.0.1", 2999, "PATCH",
            "/lol-champ-select/v1/session/my-selection", body=b"{}",
        )
        self.assertEqual(len(factory.sent), 1)
        self.assertEqual(len(factory.conns[0].requests), 1)
        self.assertIsNone(out)

    def test_post_ready_check_accept_is_sent_exactly_once(self):
        factory = _Factory(fail_first=1)
        out = _pool(factory).request(
            "127.0.0.1", 2999, "POST",
            "/lol-matchmaking/v1/ready-check/accept",
        )
        self.assertEqual(len(factory.sent), 1)
        self.assertIsNone(out)

    def test_post_bench_swap_is_sent_exactly_once(self):
        factory = _Factory(fail_first=1)
        out = _pool(factory).request(
            "127.0.0.1", 2999, "POST",
            "/lol-champ-select/v1/session/bench/swap/143",
        )
        self.assertEqual(len(factory.sent), 1)
        self.assertIsNone(out)

    def test_no_second_connection_is_built_for_a_write(self):
        factory = _Factory(fail_first=1)
        _pool(factory).request("h", 1, "POST", "/lol-perks/v1/pages", body=b"{}")
        self.assertEqual(len(factory.conns), 1)

    def test_the_poisoned_socket_is_still_dropped(self):
        """Not retrying must NOT leave the broken kept-alive socket in the pool."""
        factory = _Factory(fail_first=1)
        pool = _pool(factory)
        pool.request("h", 1, "POST", "/lol-perks/v1/pages", body=b"{}")
        self.assertEqual(factory.conns[0].closed, 1)
        # the next call gets a fresh connection, not the dead one
        pool.request("h", 1, "GET", "/lol-perks/v1/pages")
        self.assertEqual(len(factory.conns), 2)

    def test_lowercase_write_verb_is_still_not_retried(self):
        factory = _Factory(fail_first=1)
        _pool(factory).request("h", 1, "post", "/x", body=b"{}")
        self.assertEqual(len(factory.sent), 1)

    def test_unknown_verb_is_treated_as_non_idempotent(self):
        factory = _Factory(fail_first=1)
        _pool(factory).request("h", 1, "LOCK", "/x")
        self.assertEqual(len(factory.sent), 1)

    def test_non_string_method_is_treated_as_non_idempotent(self):
        factory = _Factory(fail_first=1)
        _pool(factory).request("h", 1, None, "/x")
        self.assertEqual(len(factory.sent), 1)


class IdempotentRetryIsPreservedTests(unittest.TestCase):
    """The L6 self-heal must survive the fix - do not over-narrow."""

    def test_get_still_retries_once_and_succeeds(self):
        factory = _Factory(fail_first=1)
        out = _pool(factory).request("127.0.0.1", 2999, "GET", "/liveclientdata/allgamedata")
        self.assertEqual(len(factory.sent), 2)
        self.assertEqual(len(factory.conns), 2)
        self.assertEqual(out, (200, _OK_BODY))

    def test_every_rfc_idempotent_method_retries(self):
        for method in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"):
            with self.subTest(method=method):
                factory = _Factory(fail_first=1)
                out = _pool(factory).request("h", 1, method, "/x")
                self.assertEqual(len(factory.sent), 2)
                self.assertEqual(out, (200, _OK_BODY))

    def test_lowercase_get_still_retries(self):
        factory = _Factory(fail_first=1)
        out = _pool(factory).request("h", 1, "get", "/x")
        self.assertEqual(len(factory.sent), 2)
        self.assertEqual(out, (200, _OK_BODY))

    def test_idempotent_double_failure_is_fail_soft_none(self):
        factory = _Factory(fail_first=99)  # every fresh conn drops too
        out = _pool(factory).request("h", 1, "GET", "/x")
        self.assertEqual(len(factory.sent), 2)
        self.assertIsNone(out)


class HappyPathUnaffectedTests(unittest.TestCase):
    """A write with no fault must behave exactly as before the fix."""

    def test_post_with_no_fault_returns_the_response(self):
        factory = _Factory(fail_first=0)
        out = _pool(factory).request("h", 1, "POST", "/lol-perks/v1/pages", body=b"{}")
        self.assertEqual(out, (200, _OK_BODY))
        self.assertEqual(len(factory.sent), 1)

    def test_writes_still_reuse_the_kept_alive_socket(self):
        factory = _Factory(fail_first=0)
        pool = _pool(factory)
        pool.request("h", 1, "POST", "/a", body=b"{}")
        pool.request("h", 1, "POST", "/b", body=b"{}")
        self.assertEqual(len(factory.conns), 1)
        self.assertEqual(len(factory.conns[0].requests), 2)

    def test_body_and_headers_reach_the_connection_unchanged(self):
        factory = _Factory(fail_first=0)
        _pool(factory).request(
            "h", 1, "POST", "/x", headers={"Authorization": "Basic z"}, body=b'{"a": 1}',
        )
        method, path, body, headers = factory.sent[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/x")
        self.assertEqual(body, b'{"a": 1}')
        self.assertEqual(headers, {"Authorization": "Basic z"})


class IdempotentMethodRegistryTests(unittest.TestCase):
    """The module must expose the set it gates on, so callers can reason about it."""

    def test_registry_is_exactly_the_rfc_idempotent_verbs(self):
        self.assertEqual(
            set(lcu_pool.IDEMPOTENT_METHODS),
            {"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"},
        )

    def test_registry_is_an_immutable_frozenset(self):
        self.assertIsInstance(lcu_pool.IDEMPOTENT_METHODS, frozenset)

    def test_writes_are_absent_from_the_registry(self):
        self.assertNotIn("POST", lcu_pool.IDEMPOTENT_METHODS)
        self.assertNotIn("PATCH", lcu_pool.IDEMPOTENT_METHODS)

    def test_is_idempotent_predicate(self):
        self.assertTrue(lcu_pool.is_idempotent("GET"))
        self.assertTrue(lcu_pool.is_idempotent(" delete "))
        self.assertFalse(lcu_pool.is_idempotent("POST"))
        self.assertFalse(lcu_pool.is_idempotent("PATCH"))
        self.assertFalse(lcu_pool.is_idempotent(None))
        self.assertFalse(lcu_pool.is_idempotent(b"GET"))


if __name__ == "__main__":
    unittest.main()
