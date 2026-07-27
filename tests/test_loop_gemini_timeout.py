# arch: N3 regression - gemini timeout must not falsely terminate the loop | section=tests | frozen=no
"""N3 (docs/LOOP_IMPROVEMENTS_2026-06-27.md): a gemini TIMEOUT / CLI error must be
distinguishable from a genuine empty answer.

Before the fix `gemini()` returned `""` both on all-3-retries-exhausted (the
2026-06-22 300s-timeout class) AND on a successful empty answer, so `main()` read
the timeout `""` as the NO_WORK token and called `stop()` - a flaky CLI falsely
ended a multi-cycle run. The fix returns a distinct `None` sentinel ONLY when no
attempt completed, so the director path re-enters the cycle, and the auditor maps
the sentinel to a safe CLEAN so its verdict string ops never hit `None`.

Loaded by file path (the .json-suffix guard makes import-under-pytest use the real
config), mirroring tests/test_loop_director_continuity.py.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest import mock

import pytest

_CTRL = Path(__file__).resolve().parent.parent / "ops" / "loop" / "loop_controller.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("loop_controller_uut_n3", _CTRL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gemini_returns_none_when_all_retries_error(lc):
    # Every attempt raises (the 300s timeout class) -> the distinct None sentinel,
    # NOT "" (which main() would treat as NO_WORK and terminate the run on).
    with mock.patch.object(
        lc.subprocess, "run",
        side_effect=subprocess.TimeoutExpired("powershell", 300),
    ), mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out is None


def test_gemini_returns_none_on_completed_empty(lc):
    # 2026-07-01 17:57 false-stop: a completed call with EMPTY stdout is never a
    # usable answer (the director prompt mandates a directive or the literal
    # NO_WORK token; the auditor a VERDICT line) - it is a swallowed CLI/API
    # error (quota, overload) whose stderr the old 2>$null discarded. It must
    # map to the SAME None error sentinel as a timeout, so main() advances the
    # cycle instead of misreading "" as NO_WORK and killing a run with OPEN
    # queue rows.
    fake = mock.Mock(stdout="")
    with mock.patch.object(lc.subprocess, "run", return_value=fake), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out is None


def test_gemini_logs_stderr_head_on_empty(lc, tmp_path):
    # When stdout comes back empty the captured stderr head must reach the
    # controller log so the operator can see WHY (429 quota, model overload)
    # instead of a bare "NO_WORK / empty" stop.
    (tmp_path / "_gemini_err.txt").write_text(
        "Error: 429 RESOURCE_EXHAUSTED quota exceeded", encoding="utf-8")
    lines = []
    fake = mock.Mock(stdout="")
    with mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc.subprocess, "run", return_value=fake), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda m: lines.append(m)), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out is None
    assert any("RESOURCE_EXHAUSTED" in ln for ln in lines)


def test_gemini_falls_back_to_flash_on_primary_exhaustion(lc, tmp_path):
    # 2026-07-02 9h outage: gemini-3-pro-preview 503-overloaded for hours; the
    # 3-try loop exhausted every cycle and the run burned 92 cycles doing
    # nothing. After the primary-model tries exhaust, gemini() must retry on
    # the configured fallback model so the loop keeps moving.
    (tmp_path / "_gemini_err.txt").write_text("503 UNAVAILABLE", encoding="utf-8")
    cmds = []

    def fake_run(args, **_k):
        cmds.append(args[-1])
        # empty for the 3 primary tries; the fallback try answers
        return mock.Mock(stdout="" if len(cmds) <= 3 else "flash-directive")

    cfg = {"gemini_model": "gemini-3-pro-preview",
           "gemini_fallback_model": "gemini-2.5-flash"}
    with mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc, "CFG", cfg), \
            mock.patch.object(lc.subprocess, "run", side_effect=fake_run), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out == "flash-directive"
    assert all("gemini-3-pro-preview" in c for c in cmds[:3])
    assert "gemini-2.5-flash" in cmds[3]


def test_gemini_stderr_utf16_decoded_and_error_line_surfaced(lc, tmp_path):
    # PS 5.1 `2>file` writes UTF-16 LE; the old utf-8 read mojibake'd the
    # stderr head and the node/terminal warnings masked the real 503 for 9h.
    # The log line must carry the decoded ERROR line, not the warning head.
    body = ("node.exe : Warning: Windows 10 detected. blah\n"
            "Warning: 256-color support not detected.\n"
            "Attempt 1 failed with status 503. UNAVAILABLE high demand\n")
    (tmp_path / "_gemini_err.txt").write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))
    lines = []
    with mock.patch.object(lc, "CTL", tmp_path), \
            mock.patch.object(lc.subprocess, "run", return_value=mock.Mock(stdout="")), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda m: lines.append(m)), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out is None
    assert any("503" in ln and "UNAVAILABLE" in ln for ln in lines)
    # no NUL interleave / replacement chars = the utf-16 stream was decoded
    assert not any("\x00" in ln or "\ufffd" in ln for ln in lines)


def test_auditor_maps_gemini_error_to_clean(lc):
    # An un-auditable cycle (gemini error -> None) must NOT crash the controller's
    # verdict string ops (".strip()", concat) nor read as a false REGRESS.
    with mock.patch.object(lc, "gemini", return_value=None), \
            mock.patch.object(lc, "git", return_value="someoutput"):
        verdict = lc.auditor("aaaaaa", "bbbbbb")
    assert verdict.startswith("VERDICT: CLEAN")
    assert "could not audit" in verdict


def test_gemini_robust_to_empty_cfg(lc):
    # CFG = {} is patched in deliberately - as of 2026-07-27 it is no longer
    # what a clean checkout produces. The controller used to default its config
    # to an absolute Legion path, so every other host silently took the
    # not-found branch; that default is now module-relative and a fresh clone
    # reads the same tracked config Legion does. The empty case survives as a
    # contract, not as a description of CI: a controller vendored without its
    # config still lands here, so gemini() must not KeyError on an absent
    # gemini_model / gemini_cmd and must fall back to the production defaults.
    # The CI nightly hit exactly this KeyError before the .get() fix.
    with mock.patch.object(lc, "CFG", {}), \
            mock.patch.object(lc.subprocess, "run", return_value=mock.Mock(stdout="ok")), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out == "ok"
