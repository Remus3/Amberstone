"""MAIN FIX 2026-10-25 1935 section 1 (RM-906): CodeQL alerts 65 and 66.

65 py/redos: ``_OBJ_FACTORY_RE`` let the param group be ``(name,?)+``, so one
long identifier split many ways and a non-matching tail backtracked
exponentially. The comma is now required between names: linear.

66 py/bind-socket-all-network-interfaces: ``core.port_handoff.can_bind`` (and
``await_port``, and the ds-matchdb serve path behind ``--host``) refuse a
non-loopback host, so ``''`` / ``0.0.0.0`` never reaches a bind.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import daemon_slayer_extract as dse  # noqa: E402

from core import port_handoff  # noqa: E402


def test_obj_factory_re_still_matches_real_headers():
    for hdr in ("12,(e,a,t)=>{a.exports=", "7,(a,i,e)=>{i.exports=",
                "3,($x)=>{$x.exports=", "99,(a_1,$b)=>{$b.exports="):
        assert dse._OBJ_FACTORY_RE.search(hdr), hdr


def test_obj_factory_re_rejects_bad_param_lists():
    for hdr in ("12,()=>{a.exports=", "12,(a,)=>{a.exports=", "12,(,a)=>{a.exports="):
        assert dse._OBJ_FACTORY_RE.search(hdr) is None, hdr


@pytest.mark.parametrize("filler", ["$", "a", "a1"])
def test_obj_factory_re_is_linear_on_hostile_input(filler):
    hostile = "0,(" + filler * 5000 + "!"
    t0 = time.perf_counter()
    assert dse._OBJ_FACTORY_RE.search(hostile) is None
    assert time.perf_counter() - t0 < 2.0


@pytest.mark.parametrize("host", ["127.0.0.1", "127.5.6.7", "::1", "localhost"])
def test_require_loopback_accepts_loopback(host):
    assert port_handoff.require_loopback(host) == host


@pytest.mark.parametrize("host", ["", "0.0.0.0", "::", "192.0.2.10", "100.64.0.5",
                                  "rc-host", "example.com"])
def test_require_loopback_refuses_everything_else(host):
    with pytest.raises(ValueError):
        port_handoff.require_loopback(host)


@pytest.mark.parametrize("host", ["", "0.0.0.0"])
def test_can_bind_and_await_port_refuse_all_interfaces(host):
    with pytest.raises(ValueError):
        port_handoff.can_bind(host, 0)
    with pytest.raises(ValueError):
        port_handoff.await_port(host, 1, holder_live=lambda: False,
                                bind_ok=lambda h, p: True)


def test_matchdb_serve_forever_refuses_all_interfaces(monkeypatch):
    import ds_matchdb_mcp_server as srv

    def _boom(*a, **k):
        raise AssertionError("bind reached")
    monkeypatch.setattr(srv, "_MatchDBHTTPServer", _boom)
    monkeypatch.setattr(srv, "_await_port", _boom)
    assert srv.serve_forever("0.0.0.0", 1) == 1
    assert srv.serve_forever("", 1) == 1
