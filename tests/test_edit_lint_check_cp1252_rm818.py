"""RM-818 (a): the edit hook's ruff arm decoded ruff's stdout through the
LOCALE encoding.

`tools/edit_lint_check.py` ran ruff with `text=True` and no encoding. Ruff
writes its JSON as UTF-8 whatever the console code page (measured: a path or a
message holding U+0101 reaches the pipe as C4 81, and cp1252 has no 0x81), so
under a cp1252 locale (Windows without UTF-8 mode) the reader thread raised
UnicodeDecodeError: the ruff findings were dropped and a traceback went to
stderr. On POSIX the same decode runs in the caller, so the whole hook line
was lost. The arm now decodes UTF-8 explicitly.

The child cases run the hook as Claude Code does, with UTF-8 mode OFF. Windows
gets its ANSI code page; POSIX gets the C locale with coercion off (ASCII),
which faults the same way. A child that still decodes UTF-8 cannot show the
bug, so that case skips rather than passes vacuously. A POSIX C-locale child
cannot stat a non-ASCII path at all, so the path case is Windows-only; the
message case runs everywhere.

Source stays ASCII: every non-ASCII probe is built with chr().
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests._module_view import bind_subprocess  # noqa: E402
from tools import edit_lint_check  # noqa: E402

HOOK = REPO_ROOT / "tools" / "edit_lint_check.py"
_A_MACRON = chr(0x0101)  # UTF-8 C4 81; 0x81 is undefined in cp1252
requires_ruff = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None, reason="ruff is not importable by this interpreter"
)


def _legacy_env() -> dict:
    drop = ("CLAUDE_FILE_PATHS", "PYTHONUTF8", "PYTHONIOENCODING", "LC_ALL", "LC_CTYPE", "LANG")
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["PYTHONUTF8"] = "0"
    if os.name != "nt":
        env.update(LC_ALL="C", LANG="C", PYTHONCOERCECLOCALE="0")
    return env


def _child_encoding(cwd: Path) -> str:
    probe = subprocess.run(
        [sys.executable, "-c", "import locale; print(locale.getencoding())"],
        capture_output=True, timeout=30, env=_legacy_env(), cwd=str(cwd))
    return probe.stdout.decode("ascii", errors="replace").strip()


def _payload(target: Path, content: str, cwd: Path) -> bytes:
    return json.dumps({
        "cwd": str(cwd), "hook_event_name": "PostToolUse", "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": content},
    }).encode("utf-8")


def _run_legacy(target: Path, content: str, cwd: Path):
    encoding = _child_encoding(cwd)
    if encoding.replace("-", "").lower() in ("utf8", ""):
        pytest.skip(f"this host's legacy child still decodes {encoding or 'nothing'}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input=_payload(target, content, cwd),
        capture_output=True, timeout=60, env=_legacy_env(), cwd=str(cwd))
    return encoding, proc


def _context(proc) -> str:
    assert proc.returncode == 0
    lines = proc.stdout.decode("ascii").splitlines()
    assert len(lines) == 1, (proc.stdout, proc.stderr[-1500:])
    return json.loads(lines[0])["hookSpecificOutput"]["additionalContext"]


@requires_ruff
def test_a_non_ascii_ruff_message_survives_a_legacy_locale(tmp_path):
    encoding, proc = _run_legacy(tmp_path / "m.py", "import " + _A_MACRON + "\n", tmp_path)
    stderr = proc.stderr.decode("ascii", errors="replace")
    assert "UnicodeDecodeError" not in stderr and "Traceback" not in stderr, (encoding, stderr[-1500:])
    ctx = _context(proc)
    assert "m.py:1 F401" in ctx, (encoding, ctx)


@requires_ruff
@pytest.mark.skipif(os.name != "nt", reason="a POSIX C-locale child cannot stat a non-ASCII path")
def test_a_non_ascii_path_survives_a_cp1252_console(tmp_path):
    target = tmp_path / ("d" + _A_MACRON) / "p.py"
    encoding, proc = _run_legacy(target, "import os\n", tmp_path)
    stderr = proc.stderr.decode("ascii", errors="replace")
    assert "UnicodeDecodeError" not in stderr and "Traceback" not in stderr, (encoding, stderr[-1500:])
    ctx = _context(proc)
    assert "p.py:1 F401" in ctx, (encoding, ctx)


def test_the_ruff_arm_decodes_utf8_explicitly(tmp_path, monkeypatch):
    """The host-independent half: the call names its encoding, so neither the
    locale nor UTF-8 mode decides how ruff's JSON is read."""
    calls = []

    class _Proc:
        stdout, stderr, returncode = "[]", "", 0

    def fake_run(argv, **kwargs):
        calls.append(kwargs)
        return _Proc()

    bind_subprocess(monkeypatch, edit_lint_check, run=fake_run)
    edit_lint_check._ruff_findings([tmp_path / "x.py"])
    assert calls and calls[0].get("encoding") == "utf-8", calls
    assert calls[0].get("errors") == "replace", calls
