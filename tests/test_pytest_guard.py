"""Tests for tools/pytest_guard.py - the PostToolUse py_compile hook.

Pins the gate semantics (tiered-verification default since item 408, 2026-06-13):
- docs-only edit (*.md / *.txt / docs/* paths) -> skip everything, exit 0
- *.py edit -> syntax compile only, NO pytest, exit 0
- non-python code edit (*.js / *.css / etc) -> skip, exit 0
- empty / unknown payload -> skip, exit 0 (cannot identify code)
- OUTPUT (MAIN FIX 1254 #2, fleet UI/UX standard section 5): silent unless
  there is something to say; then ONE stdout line of
  hookSpecificOutput.additionalContext. Plain stdout on exit 0 never reached
  the model, so a syntax error after an edit used to be invisible.
- NO BYTECODE (MAIN FIX 1254 #12): compile(source, path, "exec"), never
  py_compile, which wrote a .pyc into __pycache__/ beside every edited file.
- the hook NEVER runs a test suite. The RC_FULL_SUITE=1 whole-suite branch was
  removed 2026-10-09 (MAIN kit-v13 ORDER section 2, PERF-AUDIT item 10): it ran
  a serial whole-repo suite per edit, outside the machine-wide suite gate, with
  no timeout. A whole suite now runs only through ops/fleet_kit/fleet_suite_gate.py
  (FLEET-COMMON 16c; the TIER TABLE in tools/done.md).

Every process spawn is intercepted at the real `subprocess` module, so a
re-added suite run is caught however the guard reaches it.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests._module_view import this_thread_only
from tools import pytest_guard

GUARD_SRC = REPO_ROOT / "tools" / "pytest_guard.py"


class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def captured_run(monkeypatch):
    """Record every subprocess.run / Popen so a test can assert none happened."""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProc(stdout="1 passed in 0.01s\n")

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("pytest_guard must not spawn a process")

    # tools/pytest_guard.py imports no subprocess (no module-local name to
    # scope through) and the pin is "however the guard reaches it", so the
    # tripwire stays on the shared module - for this test's thread and the
    # threads it starts only; a thread already alive keeps the real one (RM-801).
    monkeypatch.setattr(subprocess, "run", this_thread_only(fake_run, subprocess.run))
    monkeypatch.setattr(subprocess, "Popen", this_thread_only(fake_popen, subprocess.Popen))
    return calls


def _invoke(payload: dict, monkeypatch) -> int:
    monkeypatch.setattr("sys.stdin", _StubStdin(json.dumps(payload)))
    return pytest_guard.main()


def _context(out: str) -> str:
    """The one additionalContext line the hook printed (MAIN FIX 1254 #2)."""
    lines = out.splitlines()
    assert len(lines) == 1, f"expected ONE stdout line, got {out!r}"
    hso = json.loads(lines[0])["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    return hso["additionalContext"]


class _StubStdin:
    def __init__(self, raw: str):
        self._raw = raw

    def read(self) -> str:
        return self._raw


# ---------- is_docs_only ----------------------------------------------------


def test_is_docs_only_md():
    assert pytest_guard._is_docs_only("README.md")
    assert pytest_guard._is_docs_only("docs/ARCHITECTURE.md")
    assert pytest_guard._is_docs_only(r"C:\Example Repo\docs\OPERATIONS.md")


def test_is_docs_only_txt():
    assert pytest_guard._is_docs_only("notes.txt")
    assert pytest_guard._is_docs_only(r"C:\Example Repo\API-Key-Claude.txt")


def test_is_docs_only_docs_tree_non_md():
    # any file under docs/ counts even if extension is not .md
    assert pytest_guard._is_docs_only("docs/_archive/snapshot.json")
    assert pytest_guard._is_docs_only("C:/Example Repo/docs/adr/007-config.yml")


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
    assert capsys.readouterr().out == "", "nothing to report -> silent"


def test_main_docs_only_txt_skips_pytest(captured_run, monkeypatch, capsys):
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "WAKEUP_NOTES.txt"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert capsys.readouterr().out == ""


def test_main_code_py_default_compiles_only(captured_run, monkeypatch, capsys):
    # Tiered default (item 408): a .py edit runs py_compile, NOT the suite.
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "core/engine.py"}}, monkeypatch)
    assert rc == 0
    assert captured_run == [], "default tiered behavior: no pytest subprocess"
    assert capsys.readouterr().out == "", "a clean compile is silent"


def test_rc_full_suite_env_no_longer_runs_a_suite(captured_run, monkeypatch, capsys):
    # The retired opt-in: setting RC_FULL_SUITE=1 must NOT bring back a serial,
    # ungated, untimed whole-repo suite per edit. It compiles like any edit.
    monkeypatch.setenv("RC_FULL_SUITE", "1")
    rc = _invoke({"tool_input": {"file_path": "core/engine.py"}}, monkeypatch)
    assert rc == 0
    assert captured_run == [], "RC_FULL_SUITE=1 must not spawn pytest any more"
    # The one-line pointer tells whoever still sets the variable where suites went.
    assert "fleet_suite_gate" in _context(capsys.readouterr().out)


def test_guard_source_spawns_no_process_and_reads_no_suite_switch():
    # Structural pin: the hook holds no spawn site at all, so a whole suite can
    # only run through the kit's suite gate. Catches every import form.
    tree = ast.parse(GUARD_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != "subprocess" for a in node.names), "imports subprocess"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "subprocess", "imports from subprocess"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "os":
                assert node.func.attr not in {"system", "popen", "startfile"}, (
                    f"os.{node.func.attr} at line {node.lineno}")
                assert not node.func.attr.startswith(("spawn", "exec")), (
                    f"os.{node.func.attr} at line {node.lineno}")
    assert "_full_suite" not in GUARD_SRC.read_text(encoding="utf-8")


def test_compile_failure_reports_and_still_exits_zero(captured_run, monkeypatch,
                                                       capsys, tmp_path):
    # Informational hook: a syntax error is reported, never blocks the tool.
    bad = tmp_path / "broken.py"
    bad.write_bytes(b"def f(:\n    pass\n")
    rc = _invoke({"tool_input": {"file_path": str(bad)}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    ctx = _context(capsys.readouterr().out)
    assert "broken.py:1" in ctx and "syntax" in ctx.lower()


def test_compile_leaves_no_pycache(captured_run, monkeypatch, capsys, tmp_path):
    # MAIN FIX 1254 #12: py_compile wrote a .pyc beside every edited file.
    monkeypatch.setattr(sys, "pycache_prefix", None)
    good = tmp_path / "clean_mod.py"
    good.write_text("x = 1\n", encoding="utf-8")
    bad = tmp_path / "bad_mod.py"
    bad.write_text("def f(:\n", encoding="utf-8")
    for target in (good, bad):
        assert _invoke({"tool_input": {"file_path": str(target)}}, monkeypatch) == 0
    capsys.readouterr()
    assert not (tmp_path / "__pycache__").exists(), "the hook wrote bytecode"
    assert not list(tmp_path.rglob("*.pyc"))


_DEEP = {  # short ids: a 200k-char param id overflows PYTEST_CURRENT_TEST
    "MemoryError": "x = " + "-" * 200000 + "1\n",
    "RecursionError": "x = " + "1+" * 200000 + "1\n",
}


@pytest.mark.parametrize("kind", sorted(_DEEP))
def test_too_deep_to_compile_is_reported_not_swallowed(kind, captured_run,
                                                        monkeypatch, capsys, tmp_path):
    # compile() raises MemoryError / RecursionError on a source nested too
    # deep; py_compile used to report it, so the hook must too (not go silent).
    source = _DEEP[kind]
    deep = tmp_path / "deep.py"
    deep.write_text(source, encoding="utf-8")
    assert _invoke({"tool_input": {"file_path": str(deep)}}, monkeypatch) == 0
    ctx = _context(capsys.readouterr().out)
    assert "deep.py" in ctx and kind in ctx


def test_guard_source_never_uses_py_compile():
    tree = ast.parse(GUARD_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != "py_compile" for a in node.names), "imports py_compile"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "py_compile", "imports from py_compile"


def test_compile_accepts_a_bom_prefixed_file(captured_run, monkeypatch, capsys, tmp_path):
    bom = tmp_path / "bom_mod.py"
    bom.write_bytes(b"\xef\xbb\xbfx = 1\n")
    assert _invoke({"tool_input": {"file_path": str(bom)}}, monkeypatch) == 0
    assert capsys.readouterr().out == ""


def test_main_code_js_default_skips(captured_run, monkeypatch, capsys):
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "web/js/main.js"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert capsys.readouterr().out == ""


def test_main_code_css_default_skips(captured_run, monkeypatch, capsys):
    monkeypatch.delenv("RC_FULL_SUITE", raising=False)
    rc = _invoke({"tool_input": {"file_path": "web/css/panels/grid.css"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert capsys.readouterr().out == ""


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
    assert capsys.readouterr().out == ""


def test_main_empty_payload_skips_pytest(captured_run, monkeypatch, capsys):
    rc = _invoke({}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert capsys.readouterr().out == ""


def test_main_unknown_shape_skips_pytest(captured_run, monkeypatch, capsys):
    # PostToolUse fired for a non-Edit tool somehow -> no paths -> skip.
    rc = _invoke({"tool_input": {"command": "ls -la"}}, monkeypatch)
    assert rc == 0
    assert captured_run == []
    assert capsys.readouterr().out == ""


def test_main_invalid_json_stdin_skips(captured_run, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _StubStdin("not json {{{"))
    rc = pytest_guard.main()
    assert rc == 0
    assert captured_run == [], "invalid JSON should treat payload as empty -> skip"
    assert capsys.readouterr().out == ""


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
    assert proc.stdout == "", "docs-only edit -> silent"
