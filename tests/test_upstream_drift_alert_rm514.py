"""RM-514: the upstream drift checker consumed the 2026-09-12 drift SILENTLY.

The scheduled task runs under pythonw.exe with no log handler, so the drift
WARNING went nowhere and the sentinel advance consumed the drift. A drift must
now leave a durable, unacknowledged alert that rc_facts surfaces, written
BEFORE the sentinel advances.
"""
from __future__ import annotations

import json

import pytest

from tools import upstream_drift_check as M


@pytest.fixture()
def iso(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "SENTINEL_PATH", tmp_path / "upstream_drift.json")
    for name in ("probe_meraki_content_patch", "probe_cdragon_content_version",
                 "probe_qq_synergy_shape", "probe_cdragon_queue_catalog"):
        monkeypatch.setattr(M, name, lambda: None)
    return tmp_path


def _run(version):
    return M.main(["--patch", version])


def test_drift_leaves_a_durable_unacknowledged_alert(iso):
    assert _run("16.18.1") == 0          # baseline seeding, not drift
    assert M.load_alerts() == []
    assert _run("16.19.1") == 0          # drift
    alerts = M.load_alerts()
    assert len(alerts) == 1 and alerts[0]["acknowledged"] is False
    assert alerts[0]["changed"] == [{"name": "ddragon_version",
                                     "previous": "16.18.1", "current": "16.19.1"}]
    lines = M.unacked_alert_lines()
    assert len(lines) == 1 and "16.18.1 -> 16.19.1" in lines[0]
    assert (iso / M.ALERTS_NAME).exists(), "alerts live beside the sentinel"


def test_ack_clears_the_anomaly(iso):
    _run("16.18.1")
    _run("16.19.1")
    assert M.main(["--ack"]) == 0
    assert M.unacked_alert_lines() == []
    assert M.load_alerts()[0]["acknowledged"] is True


def test_no_drift_no_alert(iso):
    _run("16.18.1")
    _run("16.18.1")
    assert M.load_alerts() == []


def test_alert_write_failure_does_not_advance_the_sentinel(iso, monkeypatch):
    """If the alert cannot be recorded, the drift must NOT be consumed."""
    _run("16.18.1")

    def boom(fields, path=None):
        raise OSError("disk full")

    monkeypatch.setattr(M, "record_alert", boom)
    assert _run("16.19.1") == 2
    sentinel = json.loads((iso / "upstream_drift.json").read_text(encoding="utf-8"))
    assert sentinel["ddragon_version"] == "16.18.1"


def test_check_only_records_nothing(iso):
    _run("16.18.1")
    assert M.main(["--check-only", "--patch", "16.19.1"]) == 1
    assert M.load_alerts() == []
