"""True-audit (s144 cycle 176) regression tests for tools/pytest_guard.py.

Findings pinned here, one test per finding (each RED before the fix):

- S144-T-544: a *.py file under any docs/ directory skipped the syntax gate,
  because the docs-tree skip ran before the suffix check. Eight tracked
  scripts live under docs/ (docs/_rescore/*.py, docs/_rsc_score/*.py, ...),
  and a checkout whose absolute path holds a docs/ segment skipped EVERY
  Python edit. A source file is never docs-only.
- S144-T-545: compile() emits SyntaxWarning (invalid escape, return in
  finally) through the warnings machinery. The hook printed it to stderr,
  breaking the silent-by-default contract, and under PYTHONWARNINGS=error it
  turned into a SyntaxError, so a file that runs fine was reported as a
  "SYNTAX CHECK FAILED".
- S144-T-546: a non-dict tool_input (a list or a string) raised
  AttributeError inside _collect_paths; only main()'s catch-all hid it.
- S144-T-547: a *.pyw edit (the pythonw-run source the silent-crash rule is
  about) was never checked, and a path named twice was reported twice.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import pytest_guard

GUARD = REPO_ROOT / "tools" / "pytest_guard.py"
_BAD_SRC = b"def f(:\n    pass\n"
_WARN_SRC = b'x = "\\d"\n'  # invalid escape: SyntaxWarning, still runs


class _StubStdin:
    def __init__(self, raw: str):
        self._raw = raw

    def read(self) -> str:
        return self._raw


def _invoke(payload: dict, monkeypatch) -> int:
    monkeypatch.setattr("sys.stdin", _StubStdin(json.dumps(payload)))
    return pytest_guard.main()


def _context(out: str) -> str:
    lines = out.splitlines()
    assert len(lines) == 1, f"expected ONE stdout line, got {out!r}"
    return json.loads(lines[0])["hookSpecificOutput"]["additionalContext"]


def _run_hook(payload: dict, cwd: Path, extra_env: dict | None = None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("RC_FULL_SUITE", "PYTHONWARNINGS")}
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(GUARD)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=60, env=env, cwd=str(cwd),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


# ---------- S144-T-544: .py under a docs/ directory --------------------------


@pytest.mark.parametrize("rel", ["docs/_rescore/tally.py", "DOCS/Tool.PY"])
def test_python_source_under_docs_is_not_docs_only(rel):
    assert not pytest_guard._is_docs_only(rel)


def test_docs_tree_non_python_still_docs_only():
    # The fix must not widen the gate: docs/ data files still skip.
    assert pytest_guard._is_docs_only("docs/_archive/snapshot.json")
    assert pytest_guard._is_docs_only("docs/adr/007-config.yml")


def test_broken_py_under_docs_dir_is_reported(monkeypatch, capsys, tmp_path):
    bad = tmp_path / "docs" / "_rescore" / "tally.py"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(_BAD_SRC)
    assert _invoke({"tool_input": {"file_path": str(bad)}}, monkeypatch) == 0
    ctx = _context(capsys.readouterr().out)
    assert "tally.py:1" in ctx and "SYNTAX CHECK FAILED" in ctx


# ---------- S144-T-545: SyntaxWarning is neither noise nor a failure ---------


def test_syntax_warning_is_not_a_failure_under_warnings_as_errors(monkeypatch, tmp_path):
    import warnings

    src = tmp_path / "escape.py"
    src.write_bytes(_WARN_SRC)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert pytest_guard._syntax_error(str(src)) is None


def test_syntax_warning_file_is_silent_on_both_streams(tmp_path):
    src = tmp_path / "escape.py"
    src.write_bytes(_WARN_SRC)
    proc = _run_hook({"tool_input": {"file_path": str(src)}}, tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == "", proc.stdout
    assert proc.stderr == "", f"hook leaked a warning to stderr: {proc.stderr!r}"


def test_pythonwarnings_error_env_gives_no_false_positive(tmp_path):
    src = tmp_path / "escape.py"
    src.write_bytes(_WARN_SRC)
    proc = _run_hook({"tool_input": {"file_path": str(src)}}, tmp_path,
                     {"PYTHONWARNINGS": "error"})
    assert proc.returncode == 0
    assert proc.stdout == "", f"false SYNTAX CHECK FAILED: {proc.stdout!r}"


def test_real_syntax_error_still_reported_under_warnings_as_errors(tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_bytes(_BAD_SRC)
    proc = _run_hook({"tool_input": {"file_path": str(bad)}}, tmp_path,
                     {"PYTHONWARNINGS": "error"})
    assert proc.returncode == 0
    assert "broken.py:1" in _context(proc.stdout)


# ---------- S144-T-546: malformed tool_input never raises --------------------


@pytest.mark.parametrize("tool_input", [["a.py"], "a.py", 7, True])
def test_collect_paths_non_dict_tool_input_is_empty(tool_input):
    assert pytest_guard._collect_paths({"tool_input": tool_input}) == []


# ---------- S144-T-547: .pyw is checked; a path is reported once -------------


def test_broken_pyw_is_reported(monkeypatch, capsys, tmp_path):
    bad = tmp_path / "tray.pyw"
    bad.write_bytes(_BAD_SRC)
    assert _invoke({"tool_input": {"file_path": str(bad)}}, monkeypatch) == 0
    assert "tray.pyw:1" in _context(capsys.readouterr().out)


def test_same_path_twice_is_reported_once(monkeypatch, capsys, tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_bytes(_BAD_SRC)
    payload = {"tool_input": {"file_path": str(bad),
                              "edits": [{"file_path": str(bad)}]}}
    assert _invoke(payload, monkeypatch) == 0
    assert _context(capsys.readouterr().out).count("broken.py:1") == 1
