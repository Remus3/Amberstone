"""RM-826 (d) sibling sweep: a batch `set /p` never keeps an inherited value.

WHY THIS FILE EXISTS. RM-826 (d) found the launchers' deferred PATH copy
(`call set "RC_KEY_SP=..."`) failing at a PATH of about 8180 to 8191
characters and leaving RC_KEY_SP as the caller's console had it, so the next
line searched a folder the caller named (fixed by a clear on the line before;
pinned in tests/test_launcher_key_read_rm810.py). The same root - a set that
can leave a variable unchanged, read without clearing it first - is in every
`set /p`: on an empty answer or an empty first line, `set /p NAME=` leaves
NAME as it was. At 4486a09bb two tracked files had it:
  - install.bat step 3 `set /p API_KEY=<"%API_FILE%"`: with an empty key file
    and an API_KEY variable in the console, step 3 passed that value as the
    key and step 4 wrote it into API-Key-Claude.txt (pinned behaviourally in
    tests/test_api_key_single_lookup_env_apikey.py);
  - tools/rollback_last.cmd `set /p CONFIRM=...`: with CONFIRM=y in the
    console, pressing Enter (the prompt's default is N) ran
    `git reset --soft HEAD~1`.
install.bat's `set /p BOM=` was already cleared two lines before.

Pinned here:
  (a) static: every `set /p NAME=` in a tracked .bat / .cmd has an
      unconditional `set NAME=` / `set "NAME="` within the five code lines
      before it. Not seen: a name built from a variable, and a clear that is
      jumped over by a goto;
  (b) behaviour: tools/rollback_last.cmd runs under cmd.exe in a throwaway
      git repo built with plumbing (no hook runs) and an inherited CONFIRM=y;
      an empty answer leaves HEAD where it was. A "y" answer moves it, so the
      harness can see a rollback.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _repo_walk
from tests.test_launcher_key_read_rm810 import _is_comment

REPO = Path(__file__).resolve().parent.parent

_SET_P = re.compile(r'\bset\s+/p\s+"?([A-Za-z_]\w*)=', re.IGNORECASE)
_WINDOW = 5


def _clears(line: str, name: str) -> bool:
    return re.fullmatch(rf'set\s+"?{re.escape(name)}="?', line, re.IGNORECASE) is not None


def uncleared_reads(lines: list[str]) -> list[tuple[int, str]]:
    """(line number, line) of every `set /p NAME=` with no clear of NAME in
    the _WINDOW code lines before it."""
    code: list[tuple[int, str]] = []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if s and not _is_comment(s):
            code.append((n, s))
    out = []
    for i, (n, s) in enumerate(code):
        m = _SET_P.search(s)
        if m and not any(_clears(prev, m.group(1)) for _, prev in code[max(0, i - _WINDOW):i]):
            out.append((n, s))
    return out


def test_the_scan_catches_an_uncleared_read_and_passes_a_cleared_one():
    assert uncleared_reads(['set /p API_KEY=<"%API_FILE%"']) == [
        (1, 'set /p API_KEY=<"%API_FILE%"')]
    assert uncleared_reads(['set /p CONFIRM="Go? (y/N): "'])
    assert uncleared_reads(['if exist x set /p BOM=<x'])
    # A clear of another name, or a conditional clear, is not a clear.
    assert uncleared_reads(['set "OTHER="', 'set /p NAME=<f'])
    assert uncleared_reads(['if 1==1 set "NAME="', 'set /p NAME=<f'])
    # Too far back.
    assert uncleared_reads(['set NAME='] + ['echo x'] * _WINDOW + ['set /p NAME=<f'])
    assert uncleared_reads(['set "API_KEY="', 'set /p API_KEY=<"%API_FILE%"']) == []
    assert uncleared_reads(['set BOM=', 'echo x', 'if exist x set /p BOM=<x']) == []
    assert uncleared_reads([':: set /p NAME=<f']) == []


def test_no_tracked_batch_file_keeps_an_inherited_set_p_value():
    files = _repo_walk.repo_files(REPO, ("*.bat", "*.cmd"))
    rels = {_repo_walk.relative_posix(p, REPO) for p in files}
    assert {"install.bat", "tools/rollback_last.cmd"} <= rels, "the walk lost the row files"
    seen = 0
    offenders = []
    for path in files:
        lines = path.read_text(encoding="latin-1").splitlines()
        seen += sum(1 for ln in lines if _SET_P.search(ln.strip()) and not _is_comment(ln.strip()))
        offenders += [f"{_repo_walk.relative_posix(path, REPO)}:{n}: {s}"
                      for n, s in uncleared_reads(lines)]
    assert seen >= 3, f"the scan sees {seen} set /p reads; expected install.bat x2 + rollback"
    assert not offenders, (
        "`set /p NAME=` leaves NAME as it was on an empty answer or an empty first "
        'line; clear it first with set "NAME=": ' + "; ".join(offenders))


win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs a .cmd under cmd.exe")
_IDENT = {"GIT_AUTHOR_NAME": "rc826", "GIT_AUTHOR_EMAIL": "rc826@example.invalid",
          "GIT_COMMITTER_NAME": "rc826", "GIT_COMMITTER_EMAIL": "rc826@example.invalid"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "CONFIRM")}
    env.update(_IDENT)
    env.update(extra or {})
    return env


def _git(root: Path, *args: str, stdin: bytes = b"") -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), env=_env(), input=stdin,
                          capture_output=True, timeout=60, check=True,
                          creationflags=_NO_WINDOW)
    return proc.stdout.decode("ascii").strip()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A two-commit repo built with plumbing only, so no hook runs; the
    rollback script copied to its tools folder."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    tree = _git(root, "mktree")
    first = _git(root, "commit-tree", tree, "-m", "first")
    second = _git(root, "commit-tree", tree, "-p", first, "-m", "second")
    _git(root, "update-ref", "refs/heads/rc826", second)
    _git(root, "symbolic-ref", "HEAD", "refs/heads/rc826")
    (root / "tools").mkdir()
    (root / "tools" / "rollback_last.cmd").write_bytes(
        (REPO / "tools" / "rollback_last.cmd").read_bytes())
    return root, first, second


def _rollback(root: Path, answer: bytes, inherit: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", str(root / "tools" / "rollback_last.cmd")],
        cwd=str(root), env=_env(inherit), input=answer, capture_output=True,
        timeout=60, check=False, creationflags=_NO_WINDOW)
    return proc.stdout.decode("ascii", "replace")


@win_only
def test_the_rollback_harness_sees_a_confirmed_rollback(tmp_path):
    root, first, _ = _repo(tmp_path)
    out = _rollback(root, b"y\r\n")
    assert _git(root, "rev-parse", "HEAD") == first, out


@win_only
@pytest.mark.parametrize("answer", [b"\r\n", b""], ids=["enter", "eof"])
def test_an_inherited_confirm_never_rolls_back(tmp_path, answer):
    root, _, second = _repo(tmp_path)
    out = _rollback(root, answer, inherit={"CONFIRM": "y"})
    assert _git(root, "rev-parse", "HEAD") == second, f"an inherited CONFIRM rolled back: {out!r}"
    assert "Cancelled" in out, out
