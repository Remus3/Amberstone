"""RM-2107 (S144-G-45 recurrence): health.json's `alive` is a stale claim.

The writer (ops/rc_dev_runtime.py, FROZEN) sets alive=true on every tick and
cannot clear it when the box reboots under it, so before the s163 launch the
file read alive=true for pid 16164, dead since the 2026-11-10 reboot. The
session-start reader tools/rc_facts.py printed that as `alive=True` and raised
no "RC not alive" line. The reader now owes the check the writer cannot make:
alive only when the file says so AND the pid runs AND the heartbeat is fresh.
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from tools import rc_facts

NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)


def _iso(delta_s: float) -> str:
    return (NOW - timedelta(seconds=delta_s)).isoformat()


def _verdict(health, *, running=True):
    return rc_facts.rc_health_alive(health, now=NOW.timestamp(),
                                    pid_alive=lambda pid: running)


def test_fresh_live_claim_is_alive():
    alive, why = _verdict({"pid": 4242, "alive": True, "updated_at": _iso(2)})
    assert alive is True
    assert why == ""


def test_dead_pid_is_not_alive_whatever_the_file_says():
    alive, why = _verdict({"pid": 16164, "alive": True, "updated_at": _iso(2)},
                          running=False)
    assert alive is False
    assert "16164" in why and "not running" in why


def test_stale_heartbeat_is_not_alive_even_if_the_pid_was_reused():
    # After a reboot the old pid can belong to an unrelated process, so the
    # pid probe alone would pass; a days-old heartbeat still refutes the claim.
    alive, why = _verdict({"pid": 16164, "alive": True,
                           "updated_at": _iso(4 * 86400)})
    assert alive is False
    assert "stale" in why


def test_file_saying_not_alive_stays_not_alive():
    alive, why = _verdict({"pid": 4242, "alive": False, "updated_at": _iso(1)})
    assert alive is False
    assert why == ""


def test_alive_claim_without_a_pid_is_not_alive():
    alive, why = _verdict({"alive": True, "updated_at": _iso(1)})
    assert alive is False
    assert "pid" in why


def test_unparseable_timestamp_falls_back_to_the_pid_probe():
    assert _verdict({"pid": 4242, "alive": True, "updated_at": "garbage"})[0] is True
    assert _verdict({"pid": 4242, "alive": True})[0] is True


def test_default_pid_probe_sees_this_process_and_not_an_impossible_pid():
    assert rc_facts._pid_alive(os.getpid()) is True
    assert rc_facts._pid_alive(0) is False


def test_main_reports_a_dead_pid_as_not_alive(tmp_path, monkeypatch):
    health = tmp_path / "health.json"
    health.write_text(json.dumps({"pid": 16164, "alive": True,
                                  "last_reload_ok": True,
                                  "updated_at": datetime.now(timezone.utc).isoformat()}),
                      encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_APP", tmp_path)
    monkeypatch.setattr(rc_facts, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: False)
    monkeypatch.setattr(rc_facts, "_health_all", dict)
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", list)
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    from tools import slot_bucket_audit, upstream_drift_check
    monkeypatch.setattr(slot_bucket_audit, "anomaly_lines", lambda *a, **k: [])
    monkeypatch.setattr(upstream_drift_check, "unacked_alert_lines", lambda *a, **k: [])
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    assert rc_facts.main(session=None) == 0
    text = buf.getvalue()
    assert "pid=16164 alive=False" in text
    assert "alive=True" not in text
    assert "RC not alive (pid=16164" in text
    # The checklist block above carries U+2610 by design; the RC lines are ASCII.
    for line in text.splitlines():
        if "16164" in line:
            assert line.isascii(), line
