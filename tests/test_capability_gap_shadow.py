# tests/test_capability_gap_shadow.py
"""Tests for the default-OFF capability-gap shadow-log wired into routes_state.

Wire slice (item 632): the L4 Phase-D capability-gap synthesizer
(core.ds_capability_gap.build_capability_gap) is surfaced on the live
/api/state path as a logs-only shadow telemetry, gated behind RC_CAPGAP_SHADOW
(default OFF per RC flip discipline). It adds NO served field and never raises.

Fixtures reuse the live-grounded sustain comp: Lux (0 self-sustain) versus
Vladimir / Fiddlesticks / Warwick (all >= SUSTAIN_HIGH_SCORE, none artillery),
so the verdict's top gap is the sustain axis.
"""
from __future__ import annotations

import logging

from dashboard import routes_state


class _Snap:
    """Stand-in for core.liveclient_cache.Snapshot (only .data + .age_s read)."""

    def __init__(self, data, age_s=1.0):
        self.data = data
        self.age_s = age_s


_LIVE_LUX_VS_SUSTAIN = {
    "activePlayer": {"summonerName": "Me#NA1"},
    "allPlayers": [
        {"summonerName": "Me#NA1", "championName": "Lux", "team": "ORDER"},
        {"summonerName": "E1", "championName": "Vladimir", "team": "CHAOS"},
        {"summonerName": "E2", "championName": "Fiddlesticks", "team": "CHAOS"},
        {"summonerName": "E3", "championName": "Warwick", "team": "CHAOS"},
    ],
}


# --- pure resolution + eval --------------------------------------------------

def test_resolve_my_champion_from_snapshot():
    assert routes_state._resolve_my_champion(_LIVE_LUX_VS_SUSTAIN) == "Lux"


def test_resolve_my_champion_empty_when_no_active_player():
    assert routes_state._resolve_my_champion({}) == ""
    assert routes_state._resolve_my_champion(None) == ""


def test_shadow_eval_finds_sustain_gap():
    res = routes_state._capgap_shadow_eval(_LIVE_LUX_VS_SUSTAIN)
    assert res is not None
    assert res["applies"] is True
    assert res["top_gap"] == "sustain"
    assert res["my_champion"] == "Lux"


def test_shadow_eval_none_without_active_player():
    assert routes_state._capgap_shadow_eval({"allPlayers": []}) is None


def test_shadow_eval_never_raises_on_garbage():
    assert routes_state._capgap_shadow_eval(None) is None
    assert routes_state._capgap_shadow_eval({"activePlayer": 7}) is None


# --- flag gate + throttle ----------------------------------------------------

def test_shadow_log_off_by_default_short_circuits(monkeypatch):
    """Flag unset -> returns None WITHOUT touching the liveclient cache (the
    cache getter is patched to explode; if it were called the test would error).
    """
    monkeypatch.delenv("RC_CAPGAP_SHADOW", raising=False)

    def _boom():
        raise AssertionError("liveclient_cache.get must not run when flag is OFF")

    monkeypatch.setattr("core.liveclient_cache.get", _boom)
    assert routes_state._capgap_shadow_log() is None


def test_shadow_log_on_emits_and_logs(monkeypatch, caplog):
    monkeypatch.setenv("RC_CAPGAP_SHADOW", "1")
    monkeypatch.setattr(routes_state, "_capgap_last_log", 0.0)
    monkeypatch.setattr(
        "core.liveclient_cache.get",
        lambda: _Snap(_LIVE_LUX_VS_SUSTAIN),
    )
    with caplog.at_level(logging.INFO, logger="rc.web_dashboard"):
        res = routes_state._capgap_shadow_log()
    assert res is not None
    assert res["top_gap"] == "sustain"
    assert any("capgap-shadow" in r.message for r in caplog.records)


def test_shadow_log_throttled(monkeypatch):
    monkeypatch.setenv("RC_CAPGAP_SHADOW", "1")
    # Last log "just happened" -> throttled, returns None without a cache read.
    monkeypatch.setattr(routes_state, "_capgap_last_log", routes_state.time.time())

    def _boom():
        raise AssertionError("throttled call must not read the cache")

    monkeypatch.setattr("core.liveclient_cache.get", _boom)
    assert routes_state._capgap_shadow_log() is None


def test_shadow_log_stale_snapshot_returns_none(monkeypatch):
    monkeypatch.setenv("RC_CAPGAP_SHADOW", "1")
    monkeypatch.setattr(routes_state, "_capgap_last_log", 0.0)
    monkeypatch.setattr(
        "core.liveclient_cache.get",
        lambda: _Snap(_LIVE_LUX_VS_SUSTAIN, age_s=99.0),
    )
    assert routes_state._capgap_shadow_log() is None
