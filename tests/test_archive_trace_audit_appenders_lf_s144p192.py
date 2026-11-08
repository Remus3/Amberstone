"""RM-481 residual (s144, RM-1703): three more jsonl appenders write LF.

Four text-mode ``open(..., "a", encoding="utf-8")`` sites passed no
``newline=``, so on Windows every row carried CRLF:

- core/rofl_archive.py ``record_pull_observation`` (pull_log.jsonl);
- coaches/_base_coach.py ``_trace_coach_tick`` (data/coach_tick_trace.jsonl, whose
  trim rewrites the file as LF);
- tools/ci_watchdog.py ``record_pr_creation`` (pr_creations.jsonl) and
  ``audit_line`` (audit.jsonl).

CI is Linux, where the text layer does not translate, so the behaviour tests
run under a harness that forces CRLF on any text-mode write that passes no
``newline=``; a positive control proves the harness bites. The AST scan is the
OS-independent half and reuses the RM-1701 scanner.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests._crlf_text_layer import install_crlf_text_layer
from tests._repo_walk import REPO_ROOT
from tests.test_shadow_appenders_lf_s144p190 import _append_offenders

_MODULES = (
    "core/rofl_archive.py",
    "coaches/_base_coach.py",
    "tools/ci_watchdog.py",
)


@pytest.mark.parametrize("rel", _MODULES)
def test_no_bare_text_mode_append(rel):
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} missing - the scan would be vacuous"
    found = _append_offenders(path.read_bytes().decode("utf-8"))
    assert found == [], (
        f'{rel}: text-mode append without newline="\n" writes CRLF rows on '
        f"Windows (lines {found})")


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS (the shared
    harness reads a positional ``newline``, the shape ``Path.open`` uses)."""
    return install_crlf_text_layer(monkeypatch)


def _rows(raw: bytes) -> list:
    return [json.loads(r) for r in raw.decode("utf-8").split("\n") if r]


def test_positive_control_path_open_append_produces_crlf(tmp_path,
                                                         crlf_text_layer):
    target = tmp_path / "control.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert crlf_text_layer.forced_for(target), "harness missed Path.open"
    assert target.read_bytes() == b"a\r\nb\r\n", "harness failed to force CRLF"


def test_rofl_pull_observation_appends_lf(tmp_path, crlf_text_layer):
    from core import rofl_archive
    for acct in ("acct-a", "acct-b"):
        rofl_archive.record_pull_observation(tmp_path, acct, ["M1"], now=1.0)
    raw = (tmp_path / "pull_log.jsonl").read_bytes()
    assert b"\r" not in raw
    assert [r["account"] for r in _rows(raw)] == ["acct-a", "acct-b"]


def test_coach_tick_trace_appends_lf(tmp_path, monkeypatch, crlf_text_layer):
    from coaches import _base_coach as bc
    monkeypatch.setattr(bc, "_APP_DIR", tmp_path)
    fake = SimpleNamespace(_MODE_NAME="test")
    for phase in ("on_state", "whole_tick"):
        bc.BaseCoach._trace_coach_tick(fake, phase, 12.5, {"total": 1}, "30:00")
    raw = (tmp_path / "data" / "coach_tick_trace.jsonl").read_bytes()
    assert b"\r" not in raw
    assert [r["phase"] for r in _rows(raw)] == ["on_state", "whole_tick"]


def test_ci_watchdog_pr_log_and_audit_append_lf(tmp_path, crlf_text_layer):
    from tools import ci_watchdog as cw
    pr_log = tmp_path / "pr.jsonl"
    audit = tmp_path / "audit.jsonl"
    for run_id in (1, 2):
        cw.record_pr_creation(1000.0, run_id, "pr", path=pr_log)
        cw.audit_line({"run_id": run_id}, path=audit)
    assert b"\r" not in pr_log.read_bytes()
    assert b"\r" not in audit.read_bytes()
    assert [r["run_id"] for r in _rows(pr_log.read_bytes())] == [1, 2]
    assert [r["run_id"] for r in _rows(audit.read_bytes())] == [1, 2]
