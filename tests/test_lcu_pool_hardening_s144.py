"""s144 true-audit (lane 8) - core/lcu_pool.py hardening.

HttpsConnectionPool.request() promises "(status, body_bytes) on success or None
on a fail-soft error". Measured at HEAD before this slice it did not hold:

  H1  junk input raised out of request(): an inf port (OverflowError), a
      CR/LF header value (ValueError), a non-ASCII path or a non-latin-1 str
      body (UnicodeEncodeError); a bool port was read as port 1 and a float
      port was truncated (8.9 -> 8).
  H2  the escaping ValueError for a CR/LF header CARRIED THE HEADER VALUE in
      its message - for the LCU that is the Basic auth token.
  H3  a ValueError / TypeError / OverflowError raised by the connection left
      the half-sent connection in the pool for the next caller.
  H4  a timeout was retried like a dropped socket, doubling the time the
      per-key lock is held on a hung LCU (the caller then adds its own
      urlopen attempts on top).
  H5  a write (POST / PATCH, never retried by RM-345) rode a kept-alive
      socket that had been idle long enough for the peer to close it, so the
      write was lost with no recovery anywhere (SENT_UNCONFIRMED).
  H6  the connection registry was unbounded: every LCU port rotation left the
      old port's socket open in the pool forever.
  H7  close_all() closed a connection another thread was mid-request on.
  H8  MinIntervalGuard accepted a NaN / negative / inf / bool floor, and one
      NaN clock reading disabled the floor for good; the pool accepted a junk
      timeout that only failed at connect time.

All connections are fakes; no socket is opened (validation runs before the
factory, so even the default factory is never reached on junk input).
"""
from __future__ import annotations

import http.client
import logging
import socket
import threading
import time
import unittest

import pytest

from core import lcu_pool
from tests._timing_budget import fleet_test_guard

_OK = b'{"ok": true}'


class _Resp:
    def __init__(self, status=200, body=_OK):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class _Conn:
    """HTTPSConnection stand-in. `request_exc` / `response_exc` are raised on
    the next request() / getresponse() and then cleared."""

    def __init__(self, host, port, log):
        self.host = host
        self.port = port
        self.log = log
        self.requests = []
        self.closed = 0
        self.request_exc = None
        self.response_exc = None
        self.block = None      # threading.Event getresponse waits on
        self.in_flight = None  # threading.Event set when getresponse starts

    def request(self, method, path, body=None, headers=None):
        exc, self.request_exc = self.request_exc, None
        if exc is not None:
            raise exc
        self.requests.append((method, path, body, headers))
        self.log.append((self.port, method, path))

    def getresponse(self):
        if self.in_flight is not None:
            self.in_flight.set()
        if self.block is not None:
            self.block.wait(5.0)
        exc, self.response_exc = self.response_exc, None
        if exc is not None:
            raise exc
        return _Resp()

    def close(self):
        self.closed += 1


class _Factory:
    def __init__(self):
        self.conns = []
        self.sent = []
        self.on_build = None

    def __call__(self, host, port):
        c = _Conn(host, port, self.sent)
        if self.on_build is not None:
            self.on_build(c, len(self.conns))
        self.conns.append(c)
        return c


def _pool(factory=None, **kw):
    return lcu_pool.HttpsConnectionPool(connection_factory=factory or _Factory(), **kw)


class _Boom:
    """A factory that must never be called."""

    def __call__(self, host, port):  # pragma: no cover - failure path
        raise AssertionError("factory reached on junk input")


# ---------------------------------------------------------------- H1 input


@pytest.mark.parametrize("port", [
    True, False, 0, -1, 65536, 70000, 8.9, 5000.0, float("inf"), float("nan"),
    "abc", " 5000", "5000\n", "", "99999", "\u00b2", "5\u0660", None, [5000], b"5000",
])
def test_h1_junk_port_returns_none_without_building_a_connection(port):
    pool = lcu_pool.HttpsConnectionPool(connection_factory=_Boom())
    assert pool.request("127.0.0.1", port, "GET", "/x") is None


@pytest.mark.parametrize("port,expect", [(5000, 5000), ("5000", 5000), (1, 1), (65535, 65535)])
def test_h1_valid_ports_are_accepted(port, expect):
    f = _Factory()
    assert _pool(f).request("127.0.0.1", port, "GET", "/x") == (200, _OK)
    assert f.conns[0].port == expect


@pytest.mark.parametrize("host", [None, "", "a b", "h\r\n", "h\x00", 5, b"h", "x" * 300, "h\u00e9"])
def test_h1_junk_host_returns_none(host):
    pool = lcu_pool.HttpsConnectionPool(connection_factory=_Boom())
    assert pool.request(host, 5000, "GET", "/x") is None


@pytest.mark.parametrize("method", [None, "", "GE T", "GET\r\n", " GET ", b"GET", "G" * 40, "G\u00c9T"])
def test_h1_junk_method_returns_none(method):
    pool = lcu_pool.HttpsConnectionPool(connection_factory=_Boom())
    assert pool.request("127.0.0.1", 5000, method, "/x") is None


@pytest.mark.parametrize("path", [
    None, "", "x", "/a b", "/a\r\nX: y", "/\u00e9", "/" + "a" * 9000, b"/x", "/a\x00",
])
def test_h1_junk_path_returns_none(path):
    pool = lcu_pool.HttpsConnectionPool(connection_factory=_Boom())
    assert pool.request("127.0.0.1", 5000, "GET", path) is None


@pytest.mark.parametrize("headers", [
    ["Authorization"], {"A": 1}, {"A": "v\r\nInjected: 1"}, {"A\r": "v"}, {"": "v"},
    {1: "v"}, {"A": "\u00e9"}, {"A": b"v"}, {"A B": "v"},
])
def test_h1_junk_headers_return_none(headers):
    pool = lcu_pool.HttpsConnectionPool(connection_factory=_Boom())
    assert pool.request("127.0.0.1", 5000, "GET", "/x", headers=headers) is None


@pytest.mark.parametrize("body", ["{}", "\u20ac", 123, "oversized"], ids=["str", "euro", "int", "oversized"])
def test_h1_junk_body_returns_none(body):
    if body == "oversized":
        body = b"x" * (8 * 1024 * 1024 + 1)
    pool = lcu_pool.HttpsConnectionPool(connection_factory=_Boom())
    assert pool.request("127.0.0.1", 5000, "POST", "/x", body=body) is None


def test_h1_legit_shapes_still_pass_through_unchanged():
    f = _Factory()
    hdrs = {"Authorization": "Basic cmlvdDpwdw==", "Content-Type": "application/json"}
    out = _pool(f).request(
        "127.0.0.1", "54321", "POST", "/lol-perks/v1/pages?x=1&y=%20",
        headers=hdrs, body=bytearray(b'{"a": 1}'),
    )
    assert out == (200, _OK)
    assert f.sent == [(54321, "POST", "/lol-perks/v1/pages?x=1&y=%20")]
    assert f.conns[0].requests[0][3] == hdrs


def test_h1_default_factory_never_raises_on_an_out_of_range_float_port():
    # HEAD: int(float("inf")) raised OverflowError out of request().
    assert lcu_pool.HttpsConnectionPool().request("127.0.0.1", float("inf"), "GET", "/x") is None


def test_h1_default_factory_never_raises_on_a_non_ascii_path():
    # HEAD: http.client raised UnicodeEncodeError out of request().
    assert lcu_pool.HttpsConnectionPool().request("127.0.0.1", 5000, "GET", "/\u00e9") is None


# ------------------------------------------------- H2 secret never escapes


def test_h2_crlf_auth_header_never_raises_or_reaches_a_log(caplog):
    secret = "Basic c2VjcmV0LXRva2Vu\r\nX-Evil: 1"
    caplog.set_level(logging.DEBUG, logger="rc.lcu_pool")
    # The DEFAULT factory: at HEAD http.client raised ValueError whose message
    # contained the header value.
    out = lcu_pool.HttpsConnectionPool().request(
        "127.0.0.1", 5000, "GET", "/x", headers={"Authorization": secret})
    assert out is None
    assert "c2VjcmV0LXRva2Vu" not in caplog.text


# ---------------------------------------- H3 unexpected connection faults


@pytest.mark.parametrize("exc_type", [ValueError, TypeError, OverflowError, UnicodeEncodeError])
def test_h3_unexpected_request_fault_is_fail_soft_and_drops_the_connection(exc_type, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.lcu_pool")
    f = _Factory()
    pool = _pool(f)
    assert pool.request("h", 1, "GET", "/a") == (200, _OK)
    if exc_type is UnicodeEncodeError:
        exc = UnicodeEncodeError("ascii", "tok-SECRET", 0, 1, "tok-SECRET")
    else:
        exc = exc_type("tok-SECRET in message")
    f.conns[0].request_exc = exc
    assert pool.request("h", 1, "GET", "/b") is None
    assert f.conns[0].closed == 1
    assert "tok-SECRET" not in caplog.text
    # the next call builds a fresh connection instead of reusing the broken one
    assert pool.request("h", 1, "GET", "/c") == (200, _OK)
    assert len(f.conns) == 2


def test_h3_unexpected_fault_after_send_is_sent_unconfirmed_for_a_write():
    f = _Factory()
    f.on_build = lambda c, i: setattr(c, "response_exc", ValueError("bad"))
    out = _pool(f).request("h", 1, "POST", "/x", body=b"{}", distinguish_sent=True)
    assert out is lcu_pool.SENT_UNCONFIRMED
    assert len(f.sent) == 1


def test_h3_unexpected_fault_is_not_retried():
    f = _Factory()
    f.on_build = lambda c, i: setattr(c, "request_exc", TypeError("x"))
    assert _pool(f).request("h", 1, "GET", "/x") is None
    assert len(f.conns) == 1


# ------------------------------------------------------ H4 timeouts


@pytest.mark.parametrize("exc", [TimeoutError("timed out"), socket.timeout("timed out")])
def test_h4_a_timeout_is_not_retried(exc):
    f = _Factory()
    f.on_build = lambda c, i: setattr(c, "response_exc", exc) if i == 0 else None
    assert _pool(f).request("h", 1, "GET", "/x") is None
    assert len(f.conns) == 1
    assert len(f.sent) == 1
    assert f.conns[0].closed == 1


def test_h4_a_dropped_socket_is_still_retried():
    f = _Factory()
    f.on_build = lambda c, i: setattr(c, "response_exc", ConnectionResetError("rst")) if i == 0 else None
    assert _pool(f).request("h", 1, "GET", "/x") == (200, _OK)
    assert len(f.conns) == 2


# ------------------------------------------- H5 write on an idle socket


class _Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def test_h5_a_write_after_an_idle_gap_goes_on_a_fresh_connection():
    f = _Factory()
    clk = _Clock()
    pool = _pool(f, clock=clk)
    assert pool.request("h", 1, "GET", "/warm") == (200, _OK)
    # the peer closed the idle kept-alive socket; the next exchange on it dies
    f.conns[0].response_exc = http.client.RemoteDisconnected("peer closed")
    clk.t += lcu_pool._WRITE_MAX_IDLE_S + 5.0
    out = pool.request("h", 1, "POST", "/lol-matchmaking/v1/ready-check/accept",
                       distinguish_sent=True)
    assert out == (200, _OK)
    assert len(f.conns) == 2
    assert f.conns[0].closed == 1
    assert len(f.conns[0].requests) == 1  # the write never touched the stale socket
    assert len(f.sent) == 2


def test_h5_a_write_right_after_use_still_reuses_the_socket():
    f = _Factory()
    clk = _Clock()
    pool = _pool(f, clock=clk)
    pool.request("h", 1, "GET", "/warm")
    clk.t += lcu_pool._WRITE_MAX_IDLE_S / 2
    assert pool.request("h", 1, "POST", "/x", body=b"{}") == (200, _OK)
    assert len(f.conns) == 1


def test_h5_a_read_after_an_idle_gap_still_reuses_the_socket():
    f = _Factory()
    clk = _Clock()
    pool = _pool(f, clock=clk)
    pool.request("h", 1, "GET", "/a")
    clk.t += 1000.0
    assert pool.request("h", 1, "GET", "/b") == (200, _OK)
    assert len(f.conns) == 1


def test_h5_a_non_finite_clock_reading_makes_a_write_take_a_fresh_connection():
    f = _Factory()
    clk = _Clock()
    pool = _pool(f, clock=clk)
    pool.request("h", 1, "GET", "/a")
    clk.t = float("nan")
    assert pool.request("h", 1, "POST", "/x") == (200, _OK)
    assert len(f.conns) == 2


# --------------------------------------------- H6 bounded registry


def test_h6_rotated_ports_do_not_accumulate_open_sockets():
    f = _Factory()
    pool = _pool(f)
    for port in range(1000, 1040):
        assert pool.request("h", port, "GET", "/x") == (200, _OK)
    open_conns = [c for c in f.conns if c.closed == 0]
    assert len(open_conns) <= lcu_pool._MAX_CONNS
    assert f.conns[-1].closed == 0  # the newest key is kept
    assert len(pool._conns) <= lcu_pool._MAX_CONNS


def test_h6_least_recently_used_key_is_evicted_first():
    f = _Factory()
    clk = _Clock()
    pool = _pool(f, clock=clk)
    for port in range(1, lcu_pool._MAX_CONNS + 1):
        clk.t += 1.0
        pool.request("h", port, "GET", "/x")
    clk.t += 1.0
    pool.request("h", 1, "GET", "/again")  # port 1 is now the most recent
    clk.t += 1.0
    pool.request("h", 999, "GET", "/x")    # forces one eviction
    by_port = {c.port: c for c in f.conns}
    assert by_port[1].closed == 0
    assert by_port[2].closed == 1


def test_h6_a_busy_key_is_never_evicted():
    f = _Factory()
    pool = _pool(f)
    pool.request("h", 1, "GET", "/x")
    busy = pool._key_lock(("h", 1))
    with busy:
        for port in range(2, lcu_pool._MAX_CONNS + 5):
            pool.request("h", port, "GET", "/x")
        assert f.conns[0].closed == 0


# --------------------------------------------- H7 close_all vs in-flight


def test_h7_close_all_waits_for_an_in_flight_request():
    f = _Factory()
    pool = _pool(f)
    pool.request("h", 1, "GET", "/warm")
    conn = f.conns[0]
    conn.block = threading.Event()
    conn.in_flight = threading.Event()
    result = {}
    t1 = threading.Thread(target=lambda: result.update(r=pool.request("h", 1, "GET", "/slow")),
                          name="lcu-pool-test-req", daemon=True)
    t1.start()
    assert conn.in_flight.wait(fleet_test_guard.budget(5.0))
    t2 = threading.Thread(target=pool.close_all, name="lcu-pool-test-close", daemon=True)
    t2.start()
    time.sleep(0.2)
    assert conn.closed == 0  # not closed under the in-flight request
    conn.block.set()
    t1.join(5.0)
    t2.join(5.0)
    assert result["r"] == (200, _OK)
    assert conn.closed == 1


# ------------------------------------------------ H8 guard + timeout


@pytest.mark.parametrize("bad", [float("nan"), -1.0, float("inf"), True, "2", None, 10 ** 400])
def test_h8_min_interval_guard_refuses_a_junk_floor(bad):
    with pytest.raises((ValueError, TypeError)):
        lcu_pool.MinIntervalGuard(bad)


def test_h8_zero_floor_is_allowed_and_always_ready():
    g = lcu_pool.MinIntervalGuard(0, clock=lambda: 1.0)
    assert g.ready() and g.ready()


def test_h8_one_nan_clock_reading_does_not_disable_the_floor():
    clk = _Clock(0.0)
    g = lcu_pool.MinIntervalGuard(2.0, clock=clk)
    assert g.ready()
    clk.t = float("nan")
    assert g.ready() is False            # fail closed: skip the read
    assert g.time_until_ready() == 2.0
    clk.t = 0.5
    assert g.ready() is False            # the floor still holds afterwards
    clk.t = 2.5
    assert g.ready() is True


@pytest.mark.parametrize("bad", [float("nan"), 0, -1.0, float("inf"), True, "3", None])
def test_h8_pool_refuses_a_junk_timeout(bad):
    with pytest.raises((ValueError, TypeError)):
        lcu_pool.HttpsConnectionPool(timeout=bad)


def test_h8_default_factory_gets_the_validated_timeout():
    pool = lcu_pool.HttpsConnectionPool(timeout=2)
    conn = pool._default_factory("127.0.0.1", 5000)
    assert conn.timeout == 2.0
    conn.close()


if __name__ == "__main__":
    unittest.main()
