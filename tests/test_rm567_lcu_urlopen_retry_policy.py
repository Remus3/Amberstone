"""RM-567 / Y-44 (external reference N) - the LCU urlopen layer must not
re-send on ANY failure.

Before: lcu/lcu_client.py `_request` caught (URLError, OSError, TimeoutError)
in one clause. HTTPError is a URLError subclass, so every 400/403/404/409/500
landed there too, and the only retry guard was "a port is still set" - so a
rejected POST was transmitted twice and a 404 GET was read twice. A timeout or
reset AFTER the bytes were sent re-sent a write the server may have applied.

Policy pinned here (legacy per-call urlopen path, RC_LCU_POOL=0):
  - HTTPError is handled before URLError.
  - 401/403: one retry ONLY when a lockfile re-read shows port or auth changed
    (`_refresh_conn_if_changed` now returns that flag).
  - every other non-2xx returns None at once (one urlopen).
  - pure connect-refused: one retry for any method (never transmitted).
  - timeout / reset (may be after send): one retry only for
    core.lcu_pool.is_idempotent methods.
"""
from __future__ import annotations

import os
import urllib.error

import pytest

import lcu.lcu_client as lc
from lcu.lcu_client import LcuClient


def _write_lockfile(path, port, pw):
    path.write_text(f"LeagueClient:12345:{port}:{pw}:https", encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RC_LCU_POOL", "0")
    lf = tmp_path / "lockfile"
    _write_lockfile(lf, 50001, "oldpw")
    monkeypatch.setattr(lc, "_LOCKFILE_PATHS", [lf])
    c = LcuClient()
    assert c.connect() is True
    c._test_lockfile = lf
    return c


def _rotate(c, port=50002, pw="newpw"):
    lf = c._test_lockfile
    _write_lockfile(lf, port, pw)
    os.utime(lf, (c._lockfile_mtime + 10, c._lockfile_mtime + 10))


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"ok": true}'


def _install(monkeypatch, behaviour):
    """behaviour(req, n) -> raise or return. Returns the list of calls."""
    calls = []

    def fake_urlopen(req, context=None, timeout=None):
        calls.append((req.get_method(), req.full_url))
        return behaviour(req, len(calls))

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    return calls


def _http_error(code):
    def _b(req, n):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
    return _b


# --- HTTPError: answered by the server, never blindly re-sent ---------------

def test_http_400_on_post_is_exactly_one_urlopen(client, monkeypatch):
    calls = _install(monkeypatch, _http_error(400))
    assert client._request("POST", "/lol-perks/v1/pages", {"a": 1}) is None
    assert len(calls) == 1, calls
    assert client.last_request_error() == "http 400"


def test_http_404_on_get_is_one_call(client, monkeypatch):
    calls = _install(monkeypatch, _http_error(404))
    assert client._request("GET", "/lol-champ-select/v1/session") is None
    assert len(calls) == 1, calls
    assert client.last_request_error() == "http 404"


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT", "DELETE"])
@pytest.mark.parametrize("code", [400, 404, 409, 422, 500, 503])
def test_other_non_2xx_returns_at_once(client, monkeypatch, method, code):
    calls = _install(monkeypatch, _http_error(code))
    assert client._request(method, "/x", {"a": 1}) is None
    assert len(calls) == 1, calls
    assert client.last_request_error() == f"http {code}"


@pytest.mark.parametrize("code", [401, 403])
def test_auth_reject_with_rotated_lockfile_retries_once_on_new_port(
        client, monkeypatch, code):
    _rotate(client)

    def _b(req, n):
        if ":50001" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return _Resp()

    calls = _install(monkeypatch, _b)
    out = client._request("POST", "/lol-matchmaking/v1/ready-check/accept")
    assert out == {"ok": True}
    assert len(calls) == 2, calls
    assert ":50001" in calls[0][1] and ":50002" in calls[1][1]
    assert client._port == 50002


@pytest.mark.parametrize("code", [401, 403])
def test_auth_reject_without_rotation_is_not_retried(client, monkeypatch, code):
    calls = _install(monkeypatch, _http_error(code))
    assert client._request("POST", "/lol-perks/v1/pages", {"a": 1}) is None
    assert len(calls) == 1, calls
    assert client.last_request_error() == f"http {code}"


def test_auth_reject_retry_is_bounded_to_one(client, monkeypatch):
    # Rotated, but the new port also 401s: exactly one retry, never a loop.
    _rotate(client)
    calls = _install(monkeypatch, _http_error(401))
    assert client._request("GET", "/x") is None
    assert len(calls) == 2, calls
    assert client.last_request_error() == "http 401"


# --- transport failures ----------------------------------------------------

def _raise(exc_factory):
    def _b(req, n):
        raise exc_factory()
    return _b


_REFUSED = [
    lambda: urllib.error.URLError(ConnectionRefusedError(10061, "refused")),
    lambda: ConnectionRefusedError(10061, "refused"),
]


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH"])
@pytest.mark.parametrize("mk", _REFUSED)
def test_connect_refused_gets_one_retry_for_any_method(
        client, monkeypatch, method, mk):
    calls = _install(monkeypatch, _raise(mk))
    assert client._request(method, "/x", {"a": 1}) is None
    assert len(calls) == 2, calls


def test_connect_refused_then_rotation_succeeds_on_new_port(client, monkeypatch):
    _rotate(client)

    def _b(req, n):
        if ":50001" in req.full_url:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        return _Resp()

    calls = _install(monkeypatch, _b)
    assert client._request("POST", "/lol-perks/v1/pages", {"a": 1}) == {"ok": True}
    assert [":50002" in u for _, u in calls] == [False, True]


_AFTER_SEND = [
    lambda: urllib.error.URLError(TimeoutError("timed out")),
    lambda: TimeoutError("timed out"),
    lambda: ConnectionResetError(10054, "reset"),
    lambda: urllib.error.URLError(ConnectionResetError(10054, "reset")),
]


@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.parametrize("mk", _AFTER_SEND)
def test_timeout_or_reset_on_write_is_not_retried(client, monkeypatch, method, mk):
    calls = _install(monkeypatch, _raise(mk))
    assert client._request(method, "/lol-perks/v1/pages", {"a": 1}) is None
    assert len(calls) == 1, calls
    assert client.last_request_error().startswith("transport ")


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
@pytest.mark.parametrize("mk", _AFTER_SEND)
def test_timeout_or_reset_on_idempotent_gets_one_retry(
        client, monkeypatch, method, mk):
    calls = _install(monkeypatch, _raise(mk))
    assert client._request(method, "/x") is None
    assert len(calls) == 2, calls


# --- the refresh helper reports whether anything rotated --------------------

def test_refresh_returns_true_only_on_a_real_rotation(client):
    assert client._refresh_conn_if_changed() is False  # unchanged, fast path
    _rotate(client)
    assert client._refresh_conn_if_changed() is True
    assert client._refresh_conn_if_changed() is False  # settled again


def test_refresh_returns_false_when_mtime_moves_but_creds_do_not(client):
    _rotate(client, port=50001, pw="oldpw")
    assert client._refresh_conn_if_changed() is False


def test_refresh_returns_false_when_not_connected(monkeypatch):
    monkeypatch.setattr(lc, "_LOCKFILE_PATHS", [])
    assert LcuClient()._refresh_conn_if_changed() is False


def test_the_cases_above_really_ran(client, monkeypatch):
    # Positive control against an empty or vacuous harness: the stub must see
    # the request we made, on the port the lockfile named.
    calls = _install(monkeypatch, lambda req, n: _Resp())
    assert client._request("GET", "/probe") == {"ok": True}
    assert calls == [("GET", f"https://{lc.GAME_HOST}:50001/probe")]
