"""RM-826 (f): scripts/restart.bat runs no interpreter by bare name after its cd.

WHY THIS FILE EXISTS. After `cd /d "%RC_ROOT%"` restart.bat ran

    if exist "apply_patches.py" (
        echo [Amberstone] Applying patches...
        python apply_patches.py
    )

cmd looks a bare command name up in the CURRENT folder before PATH, and the
current folder is the repo root by then, so a python.bat / python.cmd there
ran instead of Python (the RM-810 N1 shape, one folder over). It also ignored
python-embed, which the key check above it prefers. No apply_patches.py exists
in the tree, scripts/restart_clean.bat deletes one on sight, and the
2026-10-09 repo review (B27-01, filed as RM-721) found the branch dead, so it
is removed rather than given an absolute interpreter: a script dropped into
the repo root no longer runs on every restart either.

Pinned here:
  (a) static: no code line of restart.bat names apply_patches, and no command
      on it is a bare python / py (with or without .exe). The scan reads
      the RM-810 command tokens: a line start, after & | ( or a for's `do`.
      Not seen (verifier): a command right after an `if` condition with no
      "(", the program of `call` / `cmd /c` / `start`, a `for /f ('...')`
      clause, and a "( ... )" after a bare word "in" (erased with the for
      sets). (b) still runs whatever sits in its cut, so there they are
      caught by behaviour;
  (b) behaviour (Windows): the lines between the key check's end and the
      relaunch run under cmd.exe in a folder holding planted python.bat /
      python.cmd / py.bat and an apply_patches.py, and no plant runs. A
      positive control shows the same plant DOES run for a bare
      `python apply_patches.py` from that folder, so the absence is not a
      harness that cannot see it.
Not in scope (filed as RM-935): the bare `pythonw.exe` relaunch line and
the other launchers' bare-interpreter fallbacks.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_launcher_key_read_rm810 import _CMD_TOKEN, _EC_END, _PLANT, _is_comment

REPO = Path(__file__).resolve().parent.parent
RESTART = "scripts/restart.bat"
_BARE_PY = {"python", "python.exe", "py", "py.exe"}
# A cut holding any of these would launch or kill something real.
_REFUSE = re.compile(r"^(?:(?:start|pythonw|taskkill|wmic)\b|\"%SystemRoot%)|main\.py",
                     re.IGNORECASE)


def _lines() -> list[str]:
    return (REPO / RESTART).read_text(encoding="ascii").splitlines()


def bare_python_runs(lines: list[str]) -> list[tuple[int, str]]:
    hits = []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or _is_comment(s):
            continue
        # A for's set "in (python.exe)" names a file to search for, not a command.
        s = re.sub(r"(?<![\w%])in\s*\([^)]*\)", "in ()", s, flags=re.IGNORECASE)
        for m in _CMD_TOKEN.finditer(s):
            if m.group(1).strip('"').lower() in _BARE_PY:
                hits.append((n, s))
    return hits


def test_the_scan_sees_the_old_patch_step():
    old = ['if exist "apply_patches.py" (', "    python apply_patches.py", ")",
           'if exist x.py (py.exe x.py)', "echo python is not run here",
           'for %%I in (python.exe) do set "P=%%~$PATH:I"']
    assert [n for n, _ in bare_python_runs(old)] == [2, 4]


def test_restart_runs_no_bare_python_and_no_patch_script():
    lines = _lines()
    code = [ln for ln in lines if ln.strip() and not _is_comment(ln.strip())]
    assert not [ln for ln in code if "apply_patches" in ln.lower()], RESTART
    assert bare_python_runs(lines) == [], RESTART
    # Anchor: the relaunch is still there, so the file was not emptied.
    assert any(ln.strip().lower().startswith("start ") for ln in code), RESTART


def _tail_cut() -> list[str]:
    """restart.bat from the line after the key check's last clear up to the
    relaunch: the lines that run in the repo root before the app starts."""
    lines = _lines()
    stripped = [ln.strip() for ln in lines]
    begin = stripped.index(_EC_END) + 1
    end = next(i for i in range(begin, len(lines)) if stripped[i].lower().startswith("start "))
    cut = lines[begin:end]
    refused = [ln.strip() for ln in cut if _REFUSE.search(ln.strip())]
    assert not refused, f"the {RESTART} cut would launch something: {refused}"
    return cut


def _plant(root: Path) -> None:
    for name in ("python.bat", "python.cmd", "py.bat", "py.cmd"):
        (root / name).write_bytes(_PLANT)
    (root / "apply_patches.py").write_bytes(b"raise SystemExit(0)\n")


def _run(root: Path, body: list[str]) -> subprocess.CompletedProcess:
    bat = root / "harness" / "restart_tail_harness.bat"
    bat.parent.mkdir(exist_ok=True)
    head = ["@echo off", "setlocal", f'cd /d "{root}"']
    bat.write_bytes(("\r\n".join(head + body) + "\r\n").encode("ascii"))
    # NoDefaultCurrentDirectoryInExePath (set in agent shells) stops cmd from
    # searching the current folder; a user's console does not have it.
    env = {k: v for k, v in os.environ.items()
           if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}
    return subprocess.run(["cmd.exe", "/d", "/c", str(bat)], cwd=bat.parent, env=env,
                          capture_output=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs cmd.exe")


@win_only
def test_a_bare_python_runs_a_plant_in_the_repo_root(tmp_path):
    # Positive control: the harness sees the shape this row removed.
    _plant(tmp_path)
    proc = _run(tmp_path, ["python apply_patches.py"])
    assert (tmp_path / "planted.txt").is_file(), proc.stdout + proc.stderr


@win_only
def test_restart_runs_no_plant_before_the_relaunch(tmp_path):
    _plant(tmp_path)
    proc = _run(tmp_path, _tail_cut())
    assert not (tmp_path / "planted.txt").exists(), (
        f"{RESTART} ran a planted python from the repo root: {proc.stdout!r}")
    assert proc.returncode == 0, proc.stdout + proc.stderr
