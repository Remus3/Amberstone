"""RM-481 residual (s144, RM-1706): the supervisor / loop / scout log appenders write LF.

Text-mode append opens that passed no ``newline=`` wrote CRLF on Windows:

- agents/_supervisor_ephemeral.py (five SPAWN / REFUSED / TIMEOUT / FAIL / OK rows);
- agents/supervisor.py ``_run_deterministic`` (the per-agent DETERMINISTIC row);
- ops/loop/headless_env.py ``_log_refusal`` (headless_route.log);
- ops/loop/loop_controller.py ``log`` (controller.log) and
  ``record_directive_outcome`` (directive_history.jsonl);
- the ``--log-file`` sinks of tools/ladder_role_scout.py,
  tools/replay_roster_pull.py and tools/timeline_ingest.py.

CI is Linux, where the text layer does not translate, so the behaviour tests
run under a harness that forces CRLF on any text-mode write that passes no
``newline=``; a positive control proves the harness bites. The AST scan is the
OS-independent half and reuses the RM-1701 scanner. Excluded by ownership:
ops/rc_supervisor.py and ops/launcher/service_host.py (frozen / main session).
"""
from __future__ import annotations

import importlib

import pytest

from tests._crlf_text_layer import install_crlf_text_layer
from tests._repo_walk import REPO_ROOT
from tests.test_shadow_appenders_lf_s144p190 import _append_offenders

_MODULES = (
    "agents/_supervisor_ephemeral.py",
    "agents/supervisor.py",
    "ops/loop/headless_env.py",
    "ops/loop/loop_controller.py",
    "tools/ladder_role_scout.py",
    "tools/replay_roster_pull.py",
    "tools/timeline_ingest.py",
)


@pytest.mark.parametrize("rel", _MODULES)
def test_no_bare_text_mode_append(rel):
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} missing - the scan would be vacuous"
    found = _append_offenders(path.read_bytes().decode("utf-8"))
    assert found == [], (
        f'{rel}: text-mode append without newline="\\n" writes CRLF rows on '
        f"Windows (lines {found})")


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS (the shared
    harness reads a positional ``newline``, the shape ``Path.open`` uses)."""
    return install_crlf_text_layer(monkeypatch)


def test_positive_control_open_append_produces_crlf(tmp_path, crlf_text_layer):
    target = tmp_path / "control.log"
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert crlf_text_layer.forced_for(target), "harness missed open"
    assert target.read_bytes() == b"a\r\nb\r\n", "harness failed to force CRLF"


def test_headless_env_refusal_log_appends_lf(tmp_path, monkeypatch,
                                             crlf_text_layer):
    he = importlib.import_module("ops.loop.headless_env")
    log = tmp_path / "headless_route.log"
    monkeypatch.setattr(he, "REFUSAL_LOG", log)
    he._log_refusal("caller-a", "reason one")
    he._log_refusal("caller-b", "reason two")
    raw = log.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


def test_loop_controller_log_appends_lf(tmp_path, monkeypatch, crlf_text_layer):
    lc = importlib.import_module("ops.loop.loop_controller")
    monkeypatch.setattr(lc, "CTL", tmp_path)
    lc.log("first")
    lc.log("second")
    raw = (tmp_path / "controller.log").read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


def test_loop_controller_directive_history_appends_lf(tmp_path,
                                                      crlf_text_layer):
    lc = importlib.import_module("ops.loop.loop_controller")
    lc.record_directive_outcome(1, "# t\nbody", "aaaa", "bbbb", {}, "ok",
                                ctl=tmp_path)
    lc.record_directive_outcome(2, "# t\nbody", "bbbb", "cccc", {}, "ok",
                                ctl=tmp_path)
    raw = (tmp_path / "directive_history.jsonl").read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2
