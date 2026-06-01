"""Tests for core.live_metrics - the shared live-metrics enable gate and
per-coach MetricStreamer dispatch wired into the 4 live coaches (sr / aram /
arena / brawl).

Covers:
  - enabled() reads env OR config switch, default OFF
  - _config_enabled() re-reads coach_settings.json live, fail-closed
  - stream() no-ops when disabled / when state has no game_id
  - stream() creates a per-match streamer keyed on game_id, reuses it on the
    same id, recreates it on a new id
  - stream() never raises (swallows streamer errors)
  - the 4 coach wire-in call sites exist (grep guard)
  - ASCII hygiene
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import live_metrics

_REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeStreamer:
    """Stand-in for core.metric_streamer.MetricStreamer."""

    created: list = []

    def __init__(self, *, match_id, champion=None, mode=None):
        self.match_id = match_id
        self.champion = champion
        self.mode = mode
        self.calls: list = []
        _FakeStreamer.created.append(self)

    def on_state(self, payload, **kw):
        self.calls.append(payload)
        return 1


class _Holder:
    """Stand-in for a coach instance (stream stashes _streamer on it)."""


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeStreamer.created = []
    yield


# ---------- enabled() / _config_enabled() ----------------------------------

def test_enabled_default_off(monkeypatch, tmp_path):
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", tmp_path / "absent.json")
    assert live_metrics.enabled() is False


def test_enabled_via_env(monkeypatch, tmp_path):
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", True)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", tmp_path / "absent.json")
    assert live_metrics.enabled() is True


def test_enabled_via_config_true(monkeypatch, tmp_path):
    cfg = tmp_path / "coach_settings.json"
    cfg.write_text(json.dumps({"live_metrics_enabled": True}), encoding="utf-8")
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", cfg)
    assert live_metrics.enabled() is True


def test_config_false_or_missing_key_is_off(monkeypatch, tmp_path):
    cfg = tmp_path / "coach_settings.json"
    cfg.write_text(json.dumps({"live_metrics_enabled": False,
                               "disabled_coaches": ["brawl"]}), encoding="utf-8")
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", cfg)
    assert live_metrics.enabled() is False
    cfg.write_text(json.dumps({"model": "x"}), encoding="utf-8")  # key absent
    assert live_metrics.enabled() is False


def test_config_malformed_fails_closed(monkeypatch, tmp_path):
    cfg = tmp_path / "coach_settings.json"
    cfg.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", cfg)
    assert live_metrics.enabled() is False


def test_config_reread_live(monkeypatch, tmp_path):
    cfg = tmp_path / "coach_settings.json"
    cfg.write_text(json.dumps({"live_metrics_enabled": False}), encoding="utf-8")
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", cfg)
    assert live_metrics.enabled() is False
    # flip on disk - enabled() must reflect it without any restart/reimport
    cfg.write_text(json.dumps({"live_metrics_enabled": True}), encoding="utf-8")
    assert live_metrics.enabled() is True


# ---------- stream() -------------------------------------------------------

def _enable(monkeypatch):
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", True)
    monkeypatch.setattr(live_metrics, "_resolve_streamer", lambda: _FakeStreamer)


def test_stream_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", False)
    monkeypatch.setattr(live_metrics, "_COACH_CFG", Path("/no/such/file.json"))
    monkeypatch.setattr(live_metrics, "_resolve_streamer", lambda: _FakeStreamer)
    h = _Holder()
    assert live_metrics.stream(h, {"game_time_s": 60}, {"game_id": "1"}, "sr") == 0
    assert _FakeStreamer.created == []
    assert getattr(h, "_streamer", None) is None


def test_stream_synthesizes_id_without_game_id(monkeypatch):
    """ARAM and other modes never expose game_id (item 211) - the streamer
    must still capture via a synthetic per-match session id."""
    _enable(monkeypatch)
    h = _Holder()
    rows = live_metrics.stream(h, {"game_time_s": 60, "champion": "Sona"}, {}, "aram")
    assert rows == 1
    assert len(_FakeStreamer.created) == 1
    assert _FakeStreamer.created[0].match_id.startswith("sess_aram_Sona_")


def test_synthetic_id_reused_within_match(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"game_time_s": 30, "champion": "Sona"}, {}, "aram")
    live_metrics.stream(h, {"game_time_s": 90, "champion": "Sona"}, {}, "aram")
    live_metrics.stream(h, {"game_time_s": 600, "champion": "Sona"}, {}, "aram")
    assert len(_FakeStreamer.created) == 1  # one match, clock only rises


def test_synthetic_id_new_on_clock_reset(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"game_time_s": 1400, "champion": "Sona"}, {}, "aram")
    first = h._streamer.match_id
    # next game starts near 0 -> clock dropped >30s -> new synthetic match
    live_metrics.stream(h, {"game_time_s": 25, "champion": "Lux"}, {}, "aram")
    assert len(_FakeStreamer.created) == 2
    assert h._streamer.match_id != first


def test_real_game_id_preferred_and_zero_treated_empty(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    # game_id "0" is treated as absent -> synthetic
    live_metrics.stream(h, {"game_time_s": 10, "champion": "Zed"}, {"game_id": "0"}, "sr")
    assert h._streamer.match_id.startswith("sess_sr_Zed_")
    # a real game_id wins and clears the synthetic session
    live_metrics.stream(h, {"champion": "Zed"}, {"game_id": "777"}, "sr")
    assert h._streamer.match_id == "live_777"
    assert getattr(h, "_lm_session", "x") is None


def test_stream_creates_and_feeds(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    cur = {"game_time_s": 60, "level": 6, "champion": "Jinx"}
    rows = live_metrics.stream(h, cur, {"game_id": "ABC"}, "aram")
    assert rows == 1
    assert len(_FakeStreamer.created) == 1
    s = _FakeStreamer.created[0]
    assert s.match_id == "live_ABC"
    assert s.champion == "Jinx"
    assert s.mode == "aram"
    assert s.calls == [cur]


def test_stream_reuses_same_match_recreates_on_new(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    live_metrics.stream(h, {"champion": "Jinx"}, {"game_id": "ABC"}, "sr")
    live_metrics.stream(h, {"champion": "Jinx"}, {"game_id": "ABC"}, "sr")
    assert len(_FakeStreamer.created) == 1  # reused
    live_metrics.stream(h, {"champion": "Lux"}, {"game_id": "XYZ"}, "sr")
    assert len(_FakeStreamer.created) == 2  # new match -> new streamer
    assert h._streamer.match_id == "live_XYZ"


def test_stream_accepts_gameId_camel(monkeypatch):
    _enable(monkeypatch)
    h = _Holder()
    rows = live_metrics.stream(h, {}, {"gameId": "42"}, "arena")
    assert rows == 1
    assert _FakeStreamer.created[0].match_id == "live_42"


def test_stream_swallows_errors(monkeypatch):
    class _Boom:
        def __init__(self, **kw):
            raise RuntimeError("kaboom")
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", True)
    monkeypatch.setattr(live_metrics, "_resolve_streamer", lambda: _Boom)
    h = _Holder()
    # must not raise
    assert live_metrics.stream(h, {"game_time_s": 1}, {"game_id": "1"}, "sr") == 0


def test_stream_noop_when_streamer_unresolvable(monkeypatch):
    monkeypatch.setattr(live_metrics, "_ENV_ENABLED", True)
    monkeypatch.setattr(live_metrics, "_resolve_streamer", lambda: None)
    h = _Holder()
    assert live_metrics.stream(h, {"game_time_s": 1}, {"game_id": "1"}, "sr") == 0


# ---------- wire-in call-site guards ---------------------------------------

@pytest.mark.parametrize("rel,needle", [
    ("coaches/aram_coach.py", 'live_metrics.stream(self, cur, state, self._MODE_NAME)'),
    ("coaches/arena_coach.py", 'live_metrics.stream(self, current, state, self._MODE_NAME)'),
    ("coaches/brawl_coach.py", 'live_metrics.stream(self, current, state, self._MODE_NAME)'),
    ("coach_integration/_coach.py", 'live_metrics.stream('),
])
def test_coach_wire_in_present(rel, needle):
    text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "from core import live_metrics" in text, f"{rel} missing live_metrics import"
    assert needle in text, f"{rel} missing wire-in call {needle!r}"


def test_sr_wire_gated_on_update_ts():
    """SR wires inside the update_ts block so status/pregame writes don't
    record off-cadence rows."""
    text = (_REPO_ROOT / "coach_integration/_coach.py").read_text(encoding="utf-8")
    idx_gate = text.find("if update_ts:")
    idx_stream = text.find("live_metrics.stream(")
    assert idx_gate != -1 and idx_stream != -1
    assert idx_stream > idx_gate, "SR stream call must sit inside the update_ts block"


def test_module_is_ascii():
    raw = (_REPO_ROOT / "core" / "live_metrics.py").read_bytes()
    bad = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not bad, f"core/live_metrics.py non-ASCII at {bad[:3]}"
