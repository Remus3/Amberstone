"""RM-371: two external fetchers that bypass lib/http/client.py still read an
UNBOUNDED body: core/riot_api.py `_http_get` and core/sgp_client.py
`_urllib_transport` (the core/rofl_archive.py third shipped 2026-09-06).

Both now use the read-one-past-the-cap shape (core/augment_external_source.py
/ core/rank_tier_source.py prior art): `read(cap + 1)`, and a body over the
cap is an OSError subclass that each module's existing network-error path
already handles (riot_api -> outcome "error"; sgp -> (0, b"")).
"""
from __future__ import annotations

import urllib.request

import pytest

from core import riot_api, sgp_client


class _Resp:
    def __init__(self, size):
        self.size = size
        self.read_args = []
        self.status = 200
        self.headers = {}

    def read(self, n=-1):
        self.read_args.append(n)
        if n is None or n < 0:
            return b"x" * self.size
        return b"x" * min(n, self.size)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def serve(monkeypatch):
    holder = {}

    def _install(size):
        resp = _Resp(size)
        holder["resp"] = resp
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: resp)
        return resp

    return _install


def test_riot_api_reads_bounded_and_refuses_oversize(serve, monkeypatch):
    monkeypatch.setattr(riot_api, "_MAX_BODY_BYTES", 100)
    resp = serve(1000)
    with pytest.raises(OSError):
        riot_api._http_get("https://na1.api.riotgames.com/x", "k")
    assert resp.read_args == [101]


def test_riot_api_body_under_cap_is_returned(serve, monkeypatch):
    monkeypatch.setattr(riot_api, "_MAX_BODY_BYTES", 100)
    serve(100)
    assert riot_api._http_get("https://na1.api.riotgames.com/x", "k").body == b"x" * 100


def test_sgp_transport_reads_bounded_and_refuses_oversize(serve, monkeypatch):
    monkeypatch.setattr(sgp_client, "_MAX_BODY_BYTES", 100)
    resp = serve(1000)
    assert sgp_client._urllib_transport("https://x.pp.sgp.pvp.net/y", {}) == (0, b"")
    assert resp.read_args == [101]


def test_sgp_body_under_cap_is_returned(serve, monkeypatch):
    monkeypatch.setattr(sgp_client, "_MAX_BODY_BYTES", 100)
    serve(50)
    assert sgp_client._urllib_transport("https://x.pp.sgp.pvp.net/y", {}) == (200, b"x" * 50)
