"""Unit tests for the live rank-tier aggregate fetch primitive (overlay item 8).

core.rank_tier_source.fetch_rows - the optional live half of the in-game
rank-tier stats panel. There is no real endpoint in this phase, so the module
must return None cleanly when unconfigured. The HTTP seam (_http_get_json) is
monkey-patched so these run offline + deterministic, proving the live-path
plumbing and the fail-soft contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core import rank_tier_source as RTS  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_cache():
    RTS._reset_cache_for_tests()
    yield
    RTS._reset_cache_for_tests()


def _metric_rows():
    return [
        {"role": "all", "bracket": "early", "metric": "cs", "avg": 150.0},
        {"role": "all", "bracket": "early", "metric": "kda", "avg": 2.5},
        {"role": "all", "bracket": "early", "metric": "kp", "avg": 52.0},
    ]


def _payload(rows):
    return {"schema": 1, "tier": "iron", "mode": "SR", "data": rows}


def _write_config(tmp_path, monkeypatch, cfg):
    p = tmp_path / "rank_tier_source.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(RTS, "_CONFIG_PATH", p)
    return p


def _spy_seam(monkeypatch):
    """Patch _http_get_json to record calls; returns the call list. The stub
    returns a valid payload so a reached seam still yields rows."""
    calls: list[str] = []

    def _fake(url, timeout_s=RTS._TIMEOUT_S):
        calls.append(url)
        return _payload(_metric_rows())

    monkeypatch.setattr(RTS, "_http_get_json", _fake)
    return calls


def test_unconfigured_returns_none_without_fetch(monkeypatch, tmp_path):
    # No config file on disk -> unconfigured -> None, and the seam is never hit.
    monkeypatch.setattr(RTS, "_CONFIG_PATH", tmp_path / "does_not_exist.json")
    calls = _spy_seam(monkeypatch)
    assert RTS.fetch_rows("iron", "SR") is None
    assert calls == []


def test_disabled_config_returns_none_without_fetch(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch,
                  {"endpoint": "https://agg.example/x", "tier_param": "tier", "enabled": False})
    calls = _spy_seam(monkeypatch)
    assert RTS.fetch_rows("iron", "SR") is None
    assert calls == []


def test_empty_endpoint_returns_none_without_fetch(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch,
                  {"endpoint": "", "tier_param": "tier", "enabled": True})
    calls = _spy_seam(monkeypatch)
    assert RTS.fetch_rows("iron", "SR") is None
    assert calls == []


def test_invalid_tier_or_mode_returns_none_without_fetch(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch,
                  {"endpoint": "https://agg.example/x", "tier_param": "tier", "enabled": True})
    calls = _spy_seam(monkeypatch)
    assert RTS.fetch_rows("wood", "SR") is None
    assert RTS.fetch_rows("iron", "ARENA") is None
    assert calls == []


def test_configured_live_path_returns_rows(monkeypatch, tmp_path):
    # Configured + enabled: the seam is consulted and its rows come back,
    # proving the live-path plumbing (tier threaded into the URL).
    _write_config(tmp_path, monkeypatch,
                  {"endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True})
    seen = {}

    def _fake(url, timeout_s=RTS._TIMEOUT_S):
        seen["url"] = url
        return _payload(_metric_rows())

    monkeypatch.setattr(RTS, "_http_get_json", _fake)
    rows = RTS.fetch_rows("iron", "SR")
    assert isinstance(rows, list)
    assert len(rows) == 3
    assert "tier=iron" in seen["url"]
    assert "mode=SR" in seen["url"]


def test_http_failure_is_fail_soft(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch,
                  {"endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True})

    def _boom(url, timeout_s=RTS._TIMEOUT_S):
        raise RTS.RankTierSourceError("boom")

    monkeypatch.setattr(RTS, "_http_get_json", _boom)
    assert RTS.fetch_rows("iron", "SR") is None


def test_empty_payload_is_fail_soft(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch,
                  {"endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True})
    monkeypatch.setattr(RTS, "_http_get_json",
                        lambda url, timeout_s=RTS._TIMEOUT_S: {"data": []})
    assert RTS.fetch_rows("iron", "SR") is None


def test_cache_hit_skips_refetch(monkeypatch, tmp_path):
    _write_config(tmp_path, monkeypatch,
                  {"endpoint": "https://agg.example/agg", "tier_param": "tier", "enabled": True})
    calls = _spy_seam(monkeypatch)
    t = [1000.0]
    monkeypatch.setattr(RTS, "_clock", lambda: t[0])
    RTS.fetch_rows("iron", "SR")
    n = len(calls)
    t[0] += 60.0  # within TTL
    RTS.fetch_rows("iron", "SR")
    assert len(calls) == n


def test_module_is_ascii():
    b = (_ROOT / "core" / "rank_tier_source.py").read_bytes()
    assert [(i, x) for i, x in enumerate(b) if x > 0x7F] == []


def test_this_file_is_ascii():
    b = Path(__file__).read_bytes()
    assert [(i, x) for i, x in enumerate(b) if x > 0x7F] == []
