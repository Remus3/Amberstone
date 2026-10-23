"""RM-783: tools/precommit_gate.py read a stdin fault as "no commit in flight".

`_read_stdin` returned "" on OSError / ValueError, so a Claude PreToolUse call
whose payload could not be read was allowed with no word, and a payload the
console code page could not decode (UnicodeDecodeError is a ValueError) was
one such fault: under cp1252 a UTF-8 commit message holding U+0101 (bytes
C4 81; 0x81 is undefined in cp1252) passed the gate silently.

Fixed shape (the C1b-3 S4 ruling, unchanged): stdin is read as BYTES and
decoded UTF-8, so the code page never decides what the payload says and an
undecodable byte is a U+FFFD glyph, not a fault. A stream that cannot be read
at all is a fault BEFORE the channel is known, so safe_main() exits 1 with ONE
stderr line naming it (a git hook refuses; Claude PreToolUse does not block on
1). The git channels are unchanged: --message-file and --scan-files never
read stdin, and the pre-commit hook's piped "git commit" still gates.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "precommit_gate.py"
sys.path.insert(0, str(ROOT / "tools"))

import precommit_gate as G  # noqa: E402

_A_MACRON = chr(0x0101)
_BOM = b"\xef\xbb\xbf"


class _FaultyStdin:
    """A pipe whose read faults (text layer and byte layer alike)."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def isatty(self) -> bool:
        return False

    def read(self, *a):
        raise self._exc

    @property
    def buffer(self):
        return self


def _claude_commit(message: str = "x") -> str:
    # ensure_ascii=False: Claude Code's payload carries raw UTF-8, not \\u escapes.
    return json.dumps({"tool_name": "Bash",
                       "tool_input": {"command": f'git commit -m "{message}"'}},
                      ensure_ascii=False)


def _no_git(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(G, "_staged_added", lambda root: {})
    monkeypatch.setattr(G, "_staged_new_paths", lambda root: [])
    monkeypatch.setattr(G, "_root_from_command", lambda c: str(tmp_path))


@pytest.mark.parametrize("exc", [OSError("pipe gone"), ValueError("I/O on closed file")],
                         ids=["OSError", "ValueError"])
def test_a_stdin_fault_is_named_never_read_as_no_commit(exc, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", _FaultyStdin(exc))
    rc = G.safe_main(["precommit_gate.py"])
    cap = capsys.readouterr()
    assert rc == 1, "a stdin fault read as 'no commit in flight' (silent pass)"
    lines = [ln for ln in cap.err.splitlines() if ln.strip()]
    assert len(lines) == 1, cap.err
    assert "stdin" in lines[0] and type(exc).__name__ in lines[0], lines[0]
    assert str(exc) not in lines[0], "type name only, never the text"
    assert cap.out == ""


def test_no_stdin_handle_is_a_fault_too(monkeypatch, capsys):
    # pythonw.exe started with no stdin handle: both real channels pipe one.
    monkeypatch.setattr("sys.stdin", None)
    assert G.safe_main(["precommit_gate.py"]) == 1
    err = capsys.readouterr().err
    assert "stdin" in err and len(err.strip().splitlines()) == 1, err


def test_a_tty_is_still_a_manual_run_with_no_commit(monkeypatch, capsys):
    class _Tty(_FaultyStdin):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", _Tty(OSError("never read")))
    assert G.safe_main(["precommit_gate.py"]) == 0
    assert capsys.readouterr() == ("", "")


def test_main_propagates_the_fault_for_tests(monkeypatch):
    monkeypatch.setattr("sys.stdin", _FaultyStdin(OSError("x")))
    with pytest.raises(G.StdinFault):
        G.main(["precommit_gate.py"])


def test_stdin_is_read_as_bytes_and_decoded_utf8(monkeypatch, tmp_path, capsys):
    """A cp1252 text layer would raise on byte 0x81; the byte layer cannot."""
    raw = _BOM + _claude_commit("a" + _A_MACRON + "b").encode("utf-8")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252"))
    _no_git(monkeypatch, tmp_path)
    rc = G.safe_main(["precommit_gate.py"])
    err = capsys.readouterr().err
    assert rc == 2, err
    assert "commit message" in err and "banned glyph" in err


def test_an_undecodable_byte_is_a_glyph_not_a_fault(monkeypatch, tmp_path, capsys):
    raw = _claude_commit("caf").encode("ascii").replace(b"caf", b"caf\xff", 1)
    assert b"\xff" in raw
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    _no_git(monkeypatch, tmp_path)
    assert G.safe_main(["precommit_gate.py"]) == 2
    assert "banned glyph" in capsys.readouterr().err


def test_the_git_pre_commit_pipe_still_gates(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"git commit\n")))
    _no_git(monkeypatch, tmp_path)
    monkeypatch.setattr(G, "_staged_added", lambda root: {
        "n.md": {"ranges": [(1, 1)], "lines": [(1, "a " + chr(0x2014) + " b")]}})
    assert G.safe_main(["precommit_gate.py"]) == 2
    assert "n.md:1" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--message-file", "--scan-files"])
def test_git_modes_never_read_stdin(flag, monkeypatch, tmp_path, capsys):
    f = tmp_path / "msg.txt"
    f.write_text("clean ascii\n", encoding="ascii")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _FaultyStdin(OSError("must not be read")))
    arg = str(f) if flag == "--message-file" else "msg.txt"
    assert G.safe_main(["precommit_gate.py", flag, arg]) == 0
    assert capsys.readouterr().err == ""


def test_the_script_under_a_cp1252_console_still_blocks(tmp_path):
    """End to end, as Claude Code runs it: a child process, the payload's UTF-8
    bytes on stdin, the console code page cp1252 (strict)."""
    # No GIT_* (a suite run inside a git hook must not aim the child at the
    # real index); tmp_path is not a repo, so nothing is staged.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PYTHONIOENCODING"] = "cp1252"
    env["PYTHONUTF8"] = "0"
    payload = _claude_commit("a" + _A_MACRON + "b").encode("utf-8")
    proc = subprocess.run([sys.executable, str(GATE)], input=payload, cwd=tmp_path,
                          env=env, capture_output=True, timeout=60)
    err = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 2, (proc.returncode, err)
    assert "banned glyph" in err
