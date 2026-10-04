"""RM-293(a): `_lookup_summoner_by_id` cached only SUCCESS, so an id LCU
keeps declining to resolve was re-fetched on every capture tick (1 Hz in the
LCU agent). A miss is now remembered under its own SHORT ttl, so a transient
blip cannot suppress lookups for the 600 s success ttl.

RM-293(c): the zero-caller `tools/lcu_agent.py` re-export with an unenforced
`sid: int` annotation is deleted (the shared helper coerces intrinsically).
"""
from __future__ import annotations

import pytest

from lcu import snapshot_shape as ss


@pytest.fixture(autouse=True)
def _clean():
    ss._reset_summoner_lookup_cache_for_tests()
    yield
    ss._reset_summoner_lookup_cache_for_tests()


class _Recorder:
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload

    def __call__(self, method, path):
        self.calls.append(path)
        return self.payload, ("404" if self.payload is None else None)


def test_two_consecutive_misses_reach_the_transport_once():
    req = _Recorder(payload=None)
    assert ss._lookup_summoner_by_id(req, 42) is None
    assert ss._lookup_summoner_by_id(req, 42) is None
    assert len(req.calls) == 1


def test_miss_ttl_is_short_and_expires(monkeypatch):
    req = _Recorder(payload=None)
    t = [1000.0]
    monkeypatch.setattr(ss.time, "time", lambda: t[0])
    ss._lookup_summoner_by_id(req, 42)
    assert ss._SUMMONER_MISS_TTL_S < ss._SUMMONER_LOOKUP_TTL_S
    t[0] += ss._SUMMONER_MISS_TTL_S + 0.1
    ss._lookup_summoner_by_id(req, 42)
    assert len(req.calls) == 2


def test_success_after_a_miss_is_cached_normally(monkeypatch):
    req = _Recorder(payload=None)
    t = [1000.0]
    monkeypatch.setattr(ss.time, "time", lambda: t[0])
    ss._lookup_summoner_by_id(req, 42)
    t[0] += ss._SUMMONER_MISS_TTL_S + 0.1
    req.payload = {"gameName": "x"}
    assert ss._lookup_summoner_by_id(req, 42) == {"gameName": "x"}
    t[0] += ss._SUMMONER_MISS_TTL_S + 0.1
    assert ss._lookup_summoner_by_id(req, 42) == {"gameName": "x"}
    assert len(req.calls) == 2


def test_lcu_agent_reexport_is_gone():
    import tools.lcu_agent as agent
    assert not hasattr(agent, "_lookup_summoner_by_id")
