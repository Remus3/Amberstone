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


def test_gemini_returns_empty_string_on_completed_empty(lc):
    # A call that COMPLETES with empty stdout is a genuine empty answer, not the
    # error sentinel -> "" (the successful-empty path is preserved).
    fake = mock.Mock(stdout="")
    with mock.patch.object(lc.subprocess, "run", return_value=fake), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out == ""


def test_auditor_maps_gemini_error_to_clean(lc):
    # An un-auditable cycle (gemini error -> None) must NOT crash the controller's
    # verdict string ops (".strip()", concat) nor read as a false REGRESS.
    with mock.patch.object(lc, "gemini", return_value=None), \
            mock.patch.object(lc, "git", return_value="someoutput"):
        verdict = lc.auditor("aaaaaa", "bbbbbb")
    assert verdict.startswith("VERDICT: CLEAN")
    assert "could not audit" in verdict


def test_gemini_robust_to_empty_cfg(lc):
    # A clean / non-Legion checkout loads CFG = {} (no config.json - see the
    # import-only fallback at the controller top). gemini() must not KeyError on
    # the absent gemini_model / gemini_cmd keys; it falls back to the production
    # defaults. The CI nightly hit exactly this KeyError before the .get() fix.
    with mock.patch.object(lc, "CFG", {}), \
            mock.patch.object(lc.subprocess, "run", return_value=mock.Mock(stdout="ok")), \
            mock.patch.object(lc.time, "sleep", lambda *_a, **_k: None), \
            mock.patch.object(lc, "log", lambda *_a, **_k: None), \
            mock.patch.object(lc, "awrite", lambda *_a, **_k: None):
        out = lc.gemini("body", "inst")
    assert out == "ok"
