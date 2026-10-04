"""RM-193: ops/runtime/incident_summary.json had a writer and ZERO readers,
and its only write swallowed failure with `except Exception: pass`.

Acceptance option (a): wire a reader. GET /api/incidents/summary serves the
file the IncidentLog writer produces, and a failed write leaves a WARNING.
"""

import json
import logging

from dashboard import routes_diag as rd
from ops import rc_incident_log
from ops.rc_incident_log import IncidentLog


class _FakeHandler:
    def __init__(self, path="/api/incidents/summary"):
        self.path = path
        self.sent = None

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


def _serve(monkeypatch, runtime_dir):
    monkeypatch.setattr(rd, "_INCIDENT_RUNTIME_DIR", runtime_dir)
    h = _FakeHandler()
    rd._serve_incident_summary(h)
    status, payload, _ = h.sent
    return status, json.loads(payload.decode("utf-8"))


def test_route_is_registered():
    paths = []
    for matcher, handler in rd.GET_ROUTES:
        if handler is rd._serve_incident_summary:
            paths.append(matcher)
    assert paths, "GET /api/incidents/summary is not registered"
    assert any(m("/api/incidents/summary") for m in paths)


def test_route_serves_what_the_writer_wrote(tmp_path, monkeypatch):
    log = IncidentLog(runtime_dir=tmp_path)
    log.record("ERROR", "app", "relay_stale")
    log.write_summary({"profile": "test"})
    status, body = _serve(monkeypatch, tmp_path)
    assert status == 200
    assert body["available"] is True
    assert body["error_count_24h"] == 1
    assert body["last_24h_count"] == 1
    assert body["monitor_state"] == {"profile": "test"}
    assert body["top_triggers"][0][0] == "app.relay_stale"


def test_route_reports_absent_file_without_error(tmp_path, monkeypatch):
    status, body = _serve(monkeypatch, tmp_path)
    assert status == 200
    assert body == {"available": False}


def test_route_reports_corrupt_file_as_unavailable(tmp_path, monkeypatch):
    (tmp_path / "incident_summary.json").write_bytes(b"{not json")
    status, body = _serve(monkeypatch, tmp_path)
    assert status == 200
    assert body == {"available": False}


def test_failed_summary_write_is_logged(tmp_path, monkeypatch, caplog):
    log = IncidentLog(runtime_dir=tmp_path)

    def boom(path, data):
        raise OSError("disk full")

    monkeypatch.setattr(rc_incident_log, "_atomic_write", boom)
    with caplog.at_level(logging.WARNING, logger="ops.rc_incident_log"):
        log.write_summary()
    assert any("incident summary write failed" in r.getMessage() for r in caplog.records)
