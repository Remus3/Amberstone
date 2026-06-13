"""Tests for tools/pytest_guard.py - the PostToolUse pytest gate.

Pins the gate semantics (tiered-verification default since item 408, 2026-06-13):
- docs-only edit (*.md / *.txt / docs/* paths) -> skip everything, exit 0
- *.py edit (default) -> py_compile only, NO pytest, exit 0
- non-python code edit (*.js / *.css / etc, default) -> skip, exit 0
- RC_FULL_SUITE=1 -> restore the old auto `pytest -x --ff -q` on any code edit
- empty / unknown payload -> skip, exit 0 (cannot identify code)

Subprocess invocation is monkeypatched so the tests do not actually re-run
the suite from inside the suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import pytest_guard


class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def captured_run(monkeypatch):
    """Capture subprocess.run calls so we can assert pytest was/was not invoked."""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProc(stdout="1 passed in 0.01s\n")

    monkeypatch.setattr(pytest_guard.subprocess, "run", fake_run)
    return calls


def _invoke(payload: dict, monkeypatch) -> int:
    monkeypatch.setattr("sys.stdin", _StubStdin(json.dumps(payload)))
    return pytest_guard.main()


class _StubStdin:
    def __init__(self, raw: str):
        self._raw = raw

    def read(self) -> str:
        return self._raw


# ---------- is_docs_only ----------------------------------------------------


def test_is_docs_only_md():
    assert pytest_guard._is_docs_only("README.md")
    assert pytest_guard._is_docs_only("docs/ARCHITECTURE.md")
    assert pytest_guard._is_docs_only(r"C:\Riot Commander\docs\OPERATIONS.md")


def test_is_docs_only_txt():
    assert pytest_guard._is_docs_only("notes.txt")
    assert pytest_guard._is_docs_only(r"C:\Riot Commander\API-Key-Claude.txt")


def test_is_docs_only_docs_tree_non_md():
    # any file under docs/ counts even if extension is not .md
    assert pytest_guard._is_docs_only("docs/_archive/snapshot.json")
    assert pytest_guard._is_docs_only("C:/Riot Commander/docs/adr/007-config.yml")


def test_is_docs_only_rejects_code():
    assert not pytest_guard._is_docs_only("tools/pytest_guard.py")
    assert not pytest_guard._is_docs_only("web/js/main.js")
    assert not pytest_guard._is_docs_only("web/css/panels/grid.css")
    assert not pytest_guard._is_docs_only("core/engine.py")


def test_is_docs_only_case_insensitive():
    assert pytest_guard._is_docs_only("README.MD")
    assert pytest_guard._is_docs_only("DOCS/Foo.md")


# ---------- _collect_paths --------------------------------------------------


def test_collect_paths_single_file_path():
    payload = {"tool_input": {"file_path": "core/engine.py"}}
    assert pytest_guard._collect_paths(payload) == ["core/engine.py"]


def test_collect_paths_notebook_path():
    payload = {"tool_input": {"notebook_path": "notebooks/analysis.ipynb"}}
    assert pytest_guard._collect_paths(payload) == ["notebooks/analysis.ipynb"]


def test_collect_paths_multi_edit_edits_array():
    payload = {
        "tool_input": {
            "file_path": "core/engine.py",
            "edits": [
                {"file_path": "tools/extra.py"},
                {"file_path": "docs/notes.md"},
            ],
        }
    }
    assert pytest_guard._collect_paths(payload) == [
        "core/engine.py",
        "tools/extra.py",
        "docs/notes.md",
    ]


def test_collect_paths_empty_payload():
    assert pytest_guard._collect_paths({}) == []


def test_collect_paths_handles_malformed_edits():
    payload = {"tool_input": {"edits": [None, {"not_file_path": "x"}, 42]}}
    assert pytest_guard._collect_paths(payload) == []


# ---------- end-to-end main() ----------------------------------------------


def test_main_docs_only_md_skips_pytest(captured_run, monkeypatch, capsys):
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "docs/ARCHITECTURE.md"}}, monkeypatch)
    assert rc == 0
    assert captured_run == [], "pytest should NOT run for docs-only edit"
    assert "skipped" in capsys.readouterr().out


def test_main_docs_only_txt_skips_pytest(captured_run, monkeypatch, capsys):
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "WAKEUP_NOTES.txt"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert "skipped" in capsys.readouterr().out


def test_main_code_py_default_compiles_only(captured_run, monkeypatch, capsys):
    # Tiered default (item 408): a .py edit runs py_compile, NOT the suite.
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "core/engine.py"}}, monkeypatch)
    assert rc == 0
    assert captured_run == [], "default tiered behavior: no pytest subprocess"
    assert "py_compile OK" in capsys.readouterr().out


def test_main_full_suite_opt_in_runs_pytest(captured_run, monkeypatch):
    # RC_FULL_SUITE=1 restores the old auto `pytest -x --ff -q` on a code edit.
    monkeypatch.setenv("RC_FULL_SUITE", "1")
    rc = _invoke({"tool_input": {"file_path": "core/engine.py"}}, monkeypatch)
    assert rc == 0
    assert len(captured_run) == 1, "RC_FULL_SUITE=1 runs the suite exactly once"
    args, _kwargs = captured_run[0]
    cmd = args[0]
    assert "pytest" in cmd
    assert "-x" in cmd
    assert "--ff" in cmd


def test_main_code_js_default_skips(captured_run, monkeypatch, capsys):
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "web/js/main.js"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert "non-python code edit" in capsys.readouterr().out


def test_main_code_css_default_skips(captured_run, monkeypatch, capsys):
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "web/css/panels/grid.css"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert "non-python code edit" in capsys.readouterr().out


def test_main_mixed_paths_default_compiles_py(captured_run, monkeypatch, capsys):
    # one docs + one code -> default tiered behavior compiles the .py, no suite
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    payload = {
        "tool_input": {
            "file_path": "docs/ARCHITECTURE.md",
            "edits": [{"file_path": "core/engine.py"}],
        }
    }
    rc = _invoke(payload, monkeypatch)
    assert rc == 0
    assert captured_run == [], "default tiered behavior: no pytest subprocess"
    assert "py_compile OK" in capsys.readouterr().out


def test_main_empty_payload_skips_pytest(captured_run, monkeypatch, capsys):
    rc = _invoke({}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    out = capsys.readouterr().out
    assert "skipped" in out


def test_main_unknown_shape_skips_pytest(captured_run, monkeypatch, capsys):
    # PostToolUse fired for a non-Edit tool somehow -> no paths -> skip.
    rc = _invoke({"tool_input": {"command": "ls -la"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert "skipped" in capsys.readouterr().out


def test_main_invalid_json_stdin_skips(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        pytest_guard.subprocess,
        "run",
        lambda *a, **k: calls.append((a, k)) or _FakeProc(),
    )
    monkeypatch.setattr("sys.stdin", _StubStdin("not json {{{"))
    rc = pytest_guard.main()
    assert rc == 0
    assert calls == [], "invalid JSON should treat payload as empty -> skip"


def test_main_pytest_output_tail_emitted(monkeypatch, capsys):
    # The output tail only exists on the RC_FULL_SUITE=1 path.
    monkeypatch.setenv("RC_FULL_SUITE", "1")
    long_output = "\n".join(f"line {i}" for i in range(50))
    monkeypatch.setattr(
        pytest_guard.subprocess,
        "run",
        lambda *a, **k: _FakeProc(stdout=long_output),
    )
    monkeypatch.setattr(
        "sys.stdin", _StubStdin(json.dumps({"tool_input": {"file_path": "x.py"}}))
    )
    rc = pytest_guard.main()
    assert rc == 0
    out = capsys.readouterr().out
    # Last 20 lines should be present, earliest should not.
    assert "line 49" in out
    assert "line 30" in out
    assert "line 5" not in out


def test_main_pytest_failure_still_exits_zero(monkeypatch):
    # Informational gate: even a red suite must exit 0 (not block the tool).
    monkeypatch.setenv("RC_FULL_SUITE", "1")
    monkeypatch.setattr(
        pytest_guard.subprocess,
        "run",
        lambda *a, **k: _FakeProc(stdout="1 failed", returncode=1),
    )
    monkeypatch.setattr(
        "sys.stdin", _StubStdin(json.dumps({"tool_input": {"file_path": "x.py"}}))
    )
    assert pytest_guard.main() == 0


# ---------- live subprocess (real Python, no monkeypatch) ------------------


def test_cli_docs_only_real_subprocess(tmp_path):
    """End-to-end: invoke the script as a subprocess, feed JSON on stdin."""
    payload = json.dumps({"tool_input": {"file_path": "docs/foo.md"}})
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "pytest_guard.py")],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "skipped" in proc.stdout
