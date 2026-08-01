# arch: controller-level robustness of the single adjudicate() call | section=tests | frozen=no
"""loop_controller.adjudicate(): the failure shapes the LOOP depends on.

Companion to tests/test_loop_adjudicator.py, which guards the backend itself.
This file guards the CONTROLLER's behaviour when that backend fails, because
the loop's response to a failed brain call is what decides whether a run
degrades or terminates.

Renamed from test_loop_gemini_timeout.py on 2026-08-01. The tests that went
away with the rename were the retired vendor's 3+2 model retry ladder and its
fallback-model escalation; what remains is vendor-independent and is exactly
the part that still runs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_LC = Path(__file__).resolve().parent.parent / "ops" / "loop" / "loop_controller.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("loop_controller_uut_robust", _LC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg():
    return {"claude_adjudicator": {"cmd": "claude.cmd", "model": "opus"}}


def test_a_raised_error_is_the_none_sentinel_not_empty_string(lc, tmp_path):
    """None and "" are NOT interchangeable here.

    main() treats an empty director answer as NO_WORK and terminates the run.
    A CLI timeout is not the loop having nothing to do, so the failure path
    must be distinguishable from a legitimate empty answer.
    """
    with mock.patch.object(lc, "CFG", _cfg()), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", {"active": "", "usd": {}}), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc.subprocess, "run", side_effect=OSError("boom")):
        out = lc.adjudicate("body", "inst")
    assert out is None and out != ""


def test_a_completed_but_empty_call_is_also_none(lc, tmp_path):
    with mock.patch.object(lc, "CFG", _cfg()), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", {"active": "", "usd": {}}), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc.subprocess, "run", return_value=mock.Mock(stdout="  \n")):
        assert lc.adjudicate("body", "inst") is None


def test_stderr_is_logged_when_the_call_comes_back_empty(lc, tmp_path):
    """A silent empty answer is the hardest failure to diagnose after the fact,
    so the decoded stderr must reach the controller log."""
    (tmp_path / "_claude_err.txt").write_text(
        "Error: something specific went wrong\n", encoding="utf-8")
    lines = []
    with mock.patch.object(lc, "CFG", _cfg()), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", {"active": "", "usd": {}}), \
            mock.patch.object(lc, "log", lines.append), \
            mock.patch.object(lc.subprocess, "run", return_value=mock.Mock(stdout="")):
        assert lc.adjudicate("body", "inst") is None
    assert any("something specific" in ln for ln in lines)


def test_auditor_maps_a_failed_call_to_clean_not_regress(lc):
    """An un-auditable cycle must not crash the controller's verdict string ops
    and must not read as a false REGRESS - the loop would then chase a
    regression that never happened."""
    with mock.patch.object(lc, "adjudicate", return_value=None), \
            mock.patch.object(lc, "git", return_value="someoutput"):
        verdict = lc.auditor("aaaaaa", "bbbbbb")
    assert verdict.startswith("VERDICT: CLEAN")
    assert "could not audit" in verdict


def test_adjudicate_is_robust_to_an_empty_cfg(lc, tmp_path):
    """A controller vendored WITHOUT its config still lands here.

    CFG = {} is patched deliberately; since 2026-07-27 it is not what a clean
    checkout produces (the config path is module-relative), but the contract
    survives: adjudicate() must not KeyError on absent config keys and must
    fall back to the production defaults. The CI nightly hit exactly this
    KeyError before the .get() fix.
    """
    with mock.patch.object(lc, "CFG", {}), \
            mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "_ADJ_STATE", {"active": "", "usd": {}}), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc.subprocess, "run", return_value=mock.Mock(stdout="ok")):
        assert lc.adjudicate("body", "inst") == "ok"


def test_cap_stdin_keeps_head_and_tail_and_cuts_the_middle(lc):
    """The prompt-size rail. The HEAD carries the prompt template and the TAIL
    carries the directive suffix and final rules, so a naive truncation would
    silently drop the operator's instructions."""
    body = "H" * 100 + "M" * 200_000 + "T" * 100
    out = lc.cap_stdin(body)
    assert len(out) <= lc.ADJ_STDIN_CAP
    assert out.startswith("H" * 100)
    assert out.endswith("T" * 100)
    assert "STDIN CAP" in out


def test_cap_stdin_passes_a_short_body_through_untouched(lc):
    assert lc.cap_stdin("short") == "short"
