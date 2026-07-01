"""Regression: LcuClient must survive a League restart (lockfile rotation)
WITHOUT an RC restart.

Root cause (reference_runewriter_dies_after_game1, 2026-07-01): the frozen
LcuClient read the lockfile once at connect() and cached port/auth forever.
When League restarts the lockfile rotates (new port + password), so a
long-lived RC kept hammering the dead port -> get_champ_select() returned
None forever -> RuneWriter (shares the one _lcu instance) went silent until
an RC restart.

The fix ports the RC-LCUAgent's proven ensure_lcu_conn() pattern
(tools/lcu_agent.py) into LcuClient:
  - _refresh_conn_if_changed(): mtime-guarded lockfile re-read; swaps creds
    when the lockfile rotated, clears them when it is gone. Called every
    auto-accept tick (1 Hz) so a rotation heals within ~1s.
  - _request(): on a connection-level failure (dead port), re-read the
    lockfile and retry once on the fresh port.
"""
from __future__ import annotations

import urllib.error

import pytest

import lcu.lcu_client as lc
from lcu.lcu_client import LcuClient


def _write_lockfile(path, port, pw):
    # Format: name:pid:port:password:protocol
    path.write_text(f"LeagueClient:12345:{port}:{pw}:https", encoding="utf-8")


def _bump_mtime(path, current):
    # Deterministically advance mtime so the rotation is detected regardless of
    # filesystem timestamp granularity.
    import os

    os.utime(path, (current + 10, current + 10))


@pytest.fixture
def lockfile(tmp_path, monkeypatch):
    lf = tmp_path / "lockfile"
    _write_lockfile(lf, 50001, "oldpw")
    monkeypatch.setattr(lc, "_LOCKFILE_PATHS", [lf])
    return lf


def test_refresh_swaps_port_when_lockfile_rotates(lockfile):
    import base64

    c = LcuClient()
    assert c.connect() is True
    assert c._port == 50001
    old_auth = c._auth

    # League restarts -> lockfile rotates to a new port + password (new mtime).
    _write_lockfile(lockfile, 50002, "newpw")
    _bump_mtime(lockfile, c._lockfile_mtime)

    c._refresh_conn_if_changed()

    assert c._port == 50002
    assert c._auth != old_auth
    assert c._auth == base64.b64encode(b"riot:newpw").decode()


def test_refresh_is_noop_when_lockfile_unchanged(lockfile):
    c = LcuClient()
    c.connect()
    before = (c._port, c._auth, c._lockfile_mtime)

    c._refresh_conn_if_changed()

    assert (c._port, c._auth, c._lockfile_mtime) == before


def test_refresh_clears_creds_when_lockfile_gone(lockfile):
    c = LcuClient()
    c.connect()
    assert c._port == 50001

    lockfile.unlink()  # League fully closed -> lockfile removed
    c._refresh_conn_if_changed()

    assert c._port is None
    assert c._auth is None


def test_request_reconnects_and_retries_on_dead_port(lockfile, monkeypatch):
    # Force the legacy per-call urlopen path so we exercise the retry (not the
    # pooled branch).
    monkeypatch.setenv("RC_LCU_POOL", "0")

    c = LcuClient()
    c.connect()  # port 50001

    # League restarted onto a fresh live port; the old 50001 is dead.
    _write_lockfile(lockfile, 50002, "newpw")
    _bump_mtime(lockfile, c._lockfile_mtime)

    seen = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(req, context=None, timeout=None):
        url = req.full_url
        seen.append(url)
        if ":50001" in url:
            raise urllib.error.URLError("connection refused")
        return _Resp()

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)

    out = c._request("GET", "/lol-champ-select/v1/session")

    assert out == {"ok": True}
    assert any(":50001" in u for u in seen), "should have first tried the dead port"
    assert any(":50002" in u for u in seen), "should have retried on the fresh port"
    assert c._port == 50002


def test_request_no_infinite_retry_when_port_stays_dead(lockfile, monkeypatch):
    # If the lockfile has NOT rotated, a dead port must fail after exactly one
    # retry - never loop.
    monkeypatch.setenv("RC_LCU_POOL", "0")

    c = LcuClient()
    c.connect()

    calls = []

    def always_fail(req, context=None, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(lc.urllib.request, "urlopen", always_fail)

    out = c._request("GET", "/lol-champ-select/v1/session")

    assert out is None
    assert len(calls) <= 2, f"expected at most one retry, got {len(calls)} calls"


def test_auto_accept_tick_refreshes_creds(monkeypatch):
    # The 1 Hz tick must call the lockfile refresher so a rotation is picked up
    # even when no request is in flight.
    monkeypatch.setattr(lc, "_LOCKFILE_PATHS", [])  # keep connect() a no-op

    c = LcuClient()
    c._port = None

    called = []
    monkeypatch.setattr(c, "_refresh_conn_if_changed", lambda: called.append(True))

    c._auto_accept_tick()

    assert called == [True]
