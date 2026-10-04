"""RM-637 (ADR-016 "Opt-in and default OFF"): the vod_record feature is the
one DEFAULT-OFF entry in core/feature_policy.py. Every other feature keeps
the historical safe default of allow."""
from __future__ import annotations

import json

import pytest

from core import feature_policy as fp


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "feature_flags.json"
    yield p
    fp._reload()


def _load(p, data):
    p.write_text(json.dumps(data), encoding="utf-8")
    fp._reload(p)


def test_vod_record_default_off_when_absent(cfg):
    _load(cfg, {"sr": {"live_coaching": "allow"}})
    assert fp.is_allowed("sr", "vod_record") is False
    assert fp.vod_record_allowed("sr", 420) is False
    # the historical default is untouched for other features
    assert fp.is_allowed("aram", "live_coaching") is True


def test_vod_record_default_off_when_file_missing(tmp_path):
    fp._reload(tmp_path / "nope.json")
    try:
        assert fp.vod_record_allowed("sr", 420) is False
    finally:
        fp._reload()


def test_vod_record_explicit_allow_per_mode(cfg):
    _load(cfg, {"sr": {"vod_record": "allow"}, "aram": {"vod_record": "disabled"}})
    assert fp.vod_record_allowed("sr", 420) is True
    assert fp.vod_record_allowed("SR", 420) is True
    assert fp.vod_record_allowed("aram", 450) is False
    assert fp.vod_record_allowed("arena", 1700) is False


def test_vod_record_unknown_mode_is_off(cfg):
    _load(cfg, {"sr": {"vod_record": "allow"}})
    assert fp.vod_record_allowed("unsupported", 0) is False
    assert fp.vod_record_allowed("jade", 0) is False
    assert fp.vod_record_allowed(None, 420) is False


def test_vod_record_queue_allowlist(cfg):
    _load(cfg, {"_vod_record_queues": [420, 440],
                "sr": {"vod_record": "allow"}})
    assert fp.vod_record_allowed("sr", 420) is True
    assert fp.vod_record_allowed("sr", 400) is False
    assert fp.vod_record_allowed("sr", None) is False


def test_vod_record_malformed_decision_is_rejected(cfg):
    _load(cfg, {"sr": {"vod_record": "yes"}})
    # invalid reload keeps last-known-good (empty) -> still off
    assert fp.vod_record_allowed("sr", 420) is False


def test_policy_state_reports_vod_record_default_disabled(cfg):
    _load(cfg, {})
    dec = fp.get_policy_state()["effective_decisions"]
    assert dec["sr"]["vod_record"] == "disabled"
    assert dec["sr"]["live_coaching"] == "allow"
