# arch: tests for GET /api/loop-status (headless-loop status surface) | section=tests | frozen=no
"""Characterization + behavior tests for dashboard.routes_loop_status.

The route is a thin, read-only aggregator over the headless-loop control
files (ops/loop/control/*) + the last git commit. It must be fail-soft per
source (a missing/corrupt file never raises), derive a 3-way state
(stopped/running/idle), and prefer the live claude.done sentinel over the
controller.log fallback for the last-cycle summary.

All file IO is redirected at module-level Path constants so these tests touch
only a tmp dir; the single git call is monkeypatched.
"""
from __future__ import annotations

import json

import pytest

from dashboard import routes_loop_status as mod


class FakeHandler:
    """Minimal StubHandler stand-in capturing the _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/loop-status") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture
def loopdir(tmp_path, monkeypatch):
    """Point the route's control-dir / config / log at a tmp sandbox."""
    ctl = tmp_path / "control"
    ctl.mkdir()
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "CONTROLLER_LOG", ctl / "controller.log")
    # Deterministic git seam so last_commit never shells out in tests.
    monkeypatch.setattr(mod, "_last_commit", lambda: {
        "sha": "deadbeef", "subject": "test commit", "iso": "2026-06-07T00:00:00-05:00",
    })
    return ctl, cfg


def _serve(handler):
    mod._serve_loop_status(handler)
    assert handler.sent is not None
    status, body, ctype = handler.sent
    return status, json.loads(body.decode("utf-8")), ctype


# --------------------------------------------------------------------------- state
def test_stopped_when_stop_file_present(loopdir):
    ctl, cfg = loopdir
    (ctl / "STOP").write_text("max_cycles 10 reached", encoding="utf-8")
    (ctl / "cycle.txt").write_text("10", encoding="utf-8")
    (ctl / "ahk_mode.txt").write_text("live\n", encoding="utf-8")
    cfg.write_text(json.dumps({"max_cycles": 24}), encoding="utf-8")

    status, body, ctype = _serve(FakeHandler())
    assert status == 200
    assert ctype == "application/json"
    assert body["ok"] is True
    assert body["state"] == "stopped"
    assert body["stop_reason"] == "max_cycles 10 reached"
    assert body["cycle"] == 10
    assert body["max_cycles"] == 24
    assert body["mode"] == "live"


def test_running_when_cycle_present_and_no_stop(loopdir):
    ctl, _ = loopdir
    (ctl / "cycle.txt").write_text("3", encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    assert body["state"] == "running"
    assert body["cycle"] == 3
    assert body["stop_reason"] is None


def test_idle_when_nothing_present(loopdir):
    _, body, _ = _serve(FakeHandler())
    assert body["ok"] is True
    assert body["state"] == "idle"
    assert body["cycle"] is None
    assert body["last_done"] is None
    assert body["budget"] is None


# --------------------------------------------------------------------------- budget
def test_budget_parsed(loopdir):
    ctl, _ = loopdir
    (ctl / "budget.json").write_text(json.dumps({
        "gemini_usd": 0.0, "gemini_ceiling": 999.0,
        "claude_usd_info": 26.1447, "cycle": 10,
    }), encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    assert body["budget"]["claude_usd_info"] == 26.1447
    assert body["budget"]["gemini_ceiling"] == 999.0
    assert body["budget"]["cycle"] == 10


def test_malformed_budget_is_failsoft(loopdir):
    ctl, _ = loopdir
    (ctl / "budget.json").write_text("{not json", encoding="utf-8")
    status, body, _ = _serve(FakeHandler())
    assert status == 200
    assert body["ok"] is True
    assert body["budget"] is None


# --------------------------------------------------------------------------- last_done
def test_last_done_prefers_sentinel(loopdir):
    ctl, _ = loopdir
    (ctl / "claude.done").write_text(json.dumps({
        "cycle": 10, "sha": "38158e1d0011223344", "tests_pass": 7024,
        "regressions": False, "ts": 1717000000.0,
    }), encoding="utf-8")
    # A log line that should be IGNORED because the sentinel wins.
    (ctl / "controller.log").write_text(
        "2026-06-07T10:38:03 cycle 9: claude.done sha=aaaaaaaa tests=1 regress=True\n",
        encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    ld = body["last_done"]
    assert ld["source"] == "sentinel"
    assert ld["cycle"] == 10
    assert ld["sha"] == "38158e1d"  # truncated to 8
    assert ld["tests_pass"] == 7024
    assert ld["regressions"] is False


def test_last_done_falls_back_to_log(loopdir):
    ctl, _ = loopdir
    (ctl / "controller.log").write_text(
        "2026-06-07T09:00:00 cycle 8: claude.done sha=11111111 tests=10 regress=False\n"
        "2026-06-07T10:38:03 cycle 10: claude.done sha=38158e1d tests=7024 regress=False\n"
        "2026-06-07T10:38:03 STOP written: max_cycles 10 reached\n",
        encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    ld = body["last_done"]
    assert ld["source"] == "log"
    assert ld["cycle"] == 10
    assert ld["sha"] == "38158e1d"
    assert ld["tests_pass"] == "7024"  # log values stay strings
    assert ld["regressions"] is False


# --------------------------------------------------------------------------- last_commit + log tail
def test_last_commit_passthrough(loopdir):
    _, body, _ = _serve(FakeHandler())
    assert body["last_commit"] == {
        "sha": "deadbeef", "subject": "test commit",
        "iso": "2026-06-07T00:00:00-05:00",
    }


def test_log_tail_is_last_lines(loopdir):
    ctl, _ = loopdir
    lines = [f"line {i}" for i in range(40)]
    (ctl / "controller.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    tail = body["log_tail"]
    assert tail[-1] == "line 39"
    assert len(tail) <= mod.LOG_TAIL_LINES


def test_last_commit_failsoft_when_git_raises(loopdir, monkeypatch):
    def _boom():
        raise RuntimeError("git missing")
    monkeypatch.setattr(mod, "_last_commit", _boom)
    status, body, _ = _serve(FakeHandler())
    assert status == 200
    assert body["ok"] is True
    assert body["last_commit"] is None


# --------------------------------------------------------------------------- registration
def test_route_registered():
    from dashboard._dispatch import equals  # noqa: F401
    paths = [m for m, _ in mod.GET_ROUTES]
    assert any(matcher("/api/loop-status") for matcher in paths)
    assert mod.POST_ROUTES == []
