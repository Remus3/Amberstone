# arch: tests for GET /api/loop-monitor (per-tool-call timeline) | section=tests | frozen=no
"""Behavior tests for dashboard.routes_loop_monitor.

The route is the per-tool-call TIMELINE complement to GET /api/loop-status
(which surfaces cycle/budget/state). It parses the active session transcript
JSONL - the same files ops/loop/loop_controller.meter() bills - pairing each
``tool_use`` block (assistant) with its later ``tool_result`` (user) by
``id``/``tool_use_id`` and reporting the wall-clock duration of each call.

It answers the operator question "why is this step taking 30 minutes?" -> the
``summary`` aggregates repeated calls so a 14-run pytest battery shows as one
``Bash:pytest x14 = 26m`` row, and ``inflight`` surfaces a call still running
(no result yet) as the live "stuck on X" signal.

Read-only, fail-soft, no engine math. All IO is injected via session_path /
monkeypatched _active_session_path so these tests touch only a tmp dir.
"""
from __future__ import annotations

import json

from dashboard import routes_loop_monitor as mod


# --------------------------------------------------------------------------- fixture builders
def _line(ts: str, blocks: list, tur=None) -> str:
    ev = {"timestamp": ts, "type": "x", "message": {"content": blocks}}
    if tur is not None:
        ev["toolUseResult"] = tur
    return json.dumps(ev)


def _use(tid: str, name: str, inp: dict) -> dict:
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _result(tid: str, is_error: bool = False) -> dict:
    return {"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
            "content": "ok"}


def _write(tmp_path, lines: list[str]):
    p = tmp_path / "sess.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# fixed ISO instants (ms + Z, matching the real transcript schema)
T00 = "2026-06-20T10:00:00.000Z"
T00_5 = "2026-06-20T10:00:00.500Z"
T05 = "2026-06-20T10:00:05.000Z"
T06 = "2026-06-20T10:00:06.000Z"
T10 = "2026-06-20T10:00:10.000Z"
T16 = "2026-06-20T10:00:16.000Z"
T20 = "2026-06-20T10:00:20.000Z"
T25 = "2026-06-20T10:00:25.000Z"


# --------------------------------------------------------------------------- pairing + durations
def test_pairs_use_to_result_by_id(tmp_path):
    sp = _write(tmp_path, [
        _line(T00, [_use("u1", "Read", {"file_path": "a.py"})]),
        _line(T00_5, [_result("u1")]),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    assert out["ok"] is True and out["tool_count"] == 1
    call = out["recent"][0]
    assert call["name"] == "Read" and call["sig"] == "Read"
    assert call["duration_s"] == 0.5 and call["inflight"] is False
    assert call["target"] == "a.py"


def test_pytest_battery_aggregates_in_summary(tmp_path):
    sp = _write(tmp_path, [
        _line(T00, [_use("p1", "Bash", {"command": "python -m pytest tests/x.py"})]),
        _line(T05, [_result("p1")]),                       # 5s
        _line(T10, [_use("p2", "Bash", {"command": "python -m pytest tests/y.py"})]),
        _line(T16, [_result("p2")]),                       # 6s
        _line(T20, [_use("p3", "Bash", {"command": "python -m pytest tests/z.py"})]),
        _line(T25, [_result("p3")]),                       # 5s
    ])
    out = mod.build_loop_timeline(session_path=sp)
    row = next(r for r in out["summary"] if r["sig"] == "Bash:pytest")
    assert row["count"] == 3
    assert row["total_s"] == 16.0 and row["max_s"] == 6.0


def test_inflight_call_has_no_result(tmp_path):
    sp = _write(tmp_path, [
        _line(T00, [_use("u9", "Agent", {"description": "big parallel sweep"})]),
    ])
    now = mod._parse_ts(T00) + 120.0
    out = mod.build_loop_timeline(session_path=sp, now_ts=now)
    assert len(out["inflight"]) == 1
    inf = out["inflight"][0]
    assert inf["name"] == "Agent" and abs(inf["elapsed_s"] - 120.0) < 0.01
    assert out["recent"][0]["inflight"] is True


def test_error_result_counted(tmp_path):
    sp = _write(tmp_path, [
        _line(T00, [_use("e1", "Bash", {"command": "pytest"})]),
        _line(T05, [_result("e1", is_error=True)]),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    row = next(r for r in out["summary"] if r["sig"] == "Bash:pytest")
    assert row["errors"] == 1
    assert out["recent"][0]["is_error"] is True


def test_parallel_tool_uses_in_one_turn(tmp_path):
    # two tool_use blocks in the SAME assistant message (same ts), each its
    # own result -> both paired independently.
    sp = _write(tmp_path, [
        _line(T00, [_use("a", "Grep", {"pattern": "foo"}),
                    _use("b", "Glob", {"pattern": "*.py"})]),
        _line(T05, [_result("a")]),
        _line(T06, [_result("b")]),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    assert out["tool_count"] == 2
    sigs = {r["sig"] for r in out["summary"]}
    assert {"Grep", "Glob"} <= sigs


def test_recent_is_newest_first(tmp_path):
    sp = _write(tmp_path, [
        _line(T00, [_use("u1", "Read", {"file_path": "first.py"})]),
        _line(T00_5, [_result("u1")]),
        _line(T10, [_use("u2", "Edit", {"file_path": "second.py"})]),
        _line(T16, [_result("u2")]),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    assert out["recent"][0]["target"] == "second.py"
    assert out["recent"][1]["target"] == "first.py"


def test_missing_session_is_fail_soft(tmp_path):
    out = mod.build_loop_timeline(session_path=tmp_path / "nope.jsonl")
    assert out["ok"] is True and out["tool_count"] == 0
    assert out["recent"] == [] and out["summary"] == [] and out["inflight"] == []
    assert out["session"] == "nope.jsonl"


def test_garbage_lines_skipped(tmp_path):
    sp = _write(tmp_path, [
        "not json at all",
        json.dumps({"timestamp": T00, "type": "attachment"}),  # no message
        _line(T00, [_use("u1", "Read", {"file_path": "a.py"})]),
        _line(T05, [_result("u1")]),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    assert out["tool_count"] == 1


# --------------------------------------------------------------------------- route surface
def test_route_is_get_only():
    assert mod.POST_ROUTES == []
    assert len(mod.GET_ROUTES) == 2          # JSON api + the HTML page
    matchers = [m for m, _ in mod.GET_ROUTES]
    assert any(m("/api/loop-monitor") for m in matchers)   # data
    assert any(m("/loop-monitor") for m in matchers)        # page
    api = mod.GET_ROUTES[0][0]
    assert api("/api/loop-monitor") is True
    assert api("/api/loop-status") is False


def test_serve_sends_json(tmp_path, monkeypatch):
    sp = _write(tmp_path, [
        _line(T00, [_use("u1", "Read", {"file_path": "a.py"})]),
        _line(T05, [_result("u1")]),
    ])
    monkeypatch.setattr(mod, "_active_session_path", lambda: sp)

    class FakeHandler:
        def __init__(self):
            self.sent = None

        def _send(self, status, body, ctype):
            self.sent = (status, body, ctype)

    h = FakeHandler()
    mod._serve_loop_monitor(h)
    assert h.sent is not None
    status, raw, ctype = h.sent
    assert status == 200 and ctype == "application/json"
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is True and payload["tool_count"] == 1


# --------------------------------------------------------------------------- exec-time vs stalls
def test_embedded_exec_preferred_over_wall_gap(tmp_path):
    # WebFetch carries a true durationMs; a 10-min wall gap must NOT win over it.
    sp = _write(tmp_path, [
        _line(T00, [_use("w1", "WebFetch", {"url": "http://x"})]),
        _line("2026-06-20T10:10:00.000Z", [_result("w1")],
              tur={"durationMs": 6317, "url": "http://x"}),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    row = next(r for r in out["summary"] if r["sig"] == "WebFetch")
    assert row["total_s"] == 6.32          # 6317ms, not the 600s wall gap
    assert out["recent"][0]["approx"] is False
    assert out["stalls"] == []


def test_fast_tool_long_gap_is_stall_not_tool_time(tmp_path):
    # an Edit cannot really take 10 min - a straddling model/API/hook stall is
    # billed to `stalls`, contributing 0 to the Edit summary total.
    sp = _write(tmp_path, [
        _line(T00, [_use("e1", "Edit", {"file_path": "a.py"})]),
        _line("2026-06-20T10:10:00.000Z", [_result("e1")]),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    assert len(out["stalls"]) == 1 and out["stalls"][0]["after_sig"] == "Edit"
    assert abs(out["stalls"][0]["gap_s"] - 600.0) < 0.5
    row = next(r for r in out["summary"] if r["sig"] == "Edit")
    assert row["count"] == 1 and row["total_s"] == 0.0
    assert out["recent"][0]["suspect"] is True


def test_shell_stall_at_retry_quantum_is_billed_away(tmp_path):
    # a PowerShell call landing on the ~10-min API-retry boundary is a stall, not
    # a 10-min command -> reclassified to `stalls` so it can't headline the table.
    sp = _write(tmp_path, [
        _line(T00, [_use("p1", "PowerShell", {"command": "pytest -q"})]),
        _line("2026-06-20T10:10:00.200Z", [_result("p1")]),   # 600.2s ~ quantum
    ])
    out = mod.build_loop_timeline(session_path=sp)
    assert len(out["stalls"]) == 1
    assert out["stalls"][0]["after_sig"] == "PowerShell:pytest"
    row = next(r for r in out["summary"] if r["sig"] == "PowerShell:pytest")
    assert row["count"] == 1 and row["total_s"] == 0.0


def test_long_shell_run_counts_as_real_time(tmp_path):
    # a genuine 26-min pytest battery (Bash is a LONG tool) is real work, not a
    # stall - this is the "why is the step slow" answer the panel exists for.
    sp = _write(tmp_path, [
        _line(T00, [_use("b1", "Bash", {"command": "python -m pytest -x"})]),
        _line("2026-06-20T10:26:00.000Z", [_result("b1")]),
    ])
    out = mod.build_loop_timeline(session_path=sp)
    assert out["stalls"] == []
    row = next(r for r in out["summary"] if r["sig"] == "Bash:pytest")
    assert row["count"] == 1 and abs(row["total_s"] - 1560.0) < 1.0
