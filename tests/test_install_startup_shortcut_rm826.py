"""RM-826 (b): ops/install_startup.bat builds its PowerShell without in-quote carets.

WHY THIS FILE EXISTS. The installer created its Startup shortcut with

    "%SystemRoot%\\...\\powershell.exe" -Command ^
      "$ws = New-Object -ComObject WScript.Shell; ^
       $s = $ws.CreateShortcut('%STARTUP%\\RiotCommanderWatcher.lnk'); ^
       ...
       $s.Save()"

The first caret sits outside any quote, so it joins the next line. Every
later caret sits INSIDE the double-quoted -Command string, where cmd reads a
caret as a literal. So the command ended at the end of the "$ws = ..." line,
PowerShell got an unterminated string, and each later line ran as a cmd
command of its own ("'$s' is not recognized"). No shortcut was ever made,
and the script then printed its "[FAIL] Could not create startup shortcut"
branch. The same block also pasted %STARTUP% and %SCRIPT_DIR% into
PowerShell source, inside single-quoted literals, so a path holding an
apostrophe would have broken the command even on one line.

The fix is one physical line, and the paths reach PowerShell as environment
variables ($env:SCRIPT_DIR, $env:STARTUP), never as source text.

Pinned here:
  (a) static: no tracked .bat / .cmd has a line that ends in ^ while cmd is
      inside a double quote (the sibling sweep: the scan reads every tracked
      batch file, not only this one); the scan sees the old block;
  (b) static: the shortcut command in install_startup.bat pastes no %VAR%
      into the PowerShell source;
  (c) behaviour (Windows): the shortcut command runs under cmd.exe with
      SCRIPT_DIR and STARTUP pointed into tmp_path (folder names with a
      space, an apostrophe and an ampersand), and the .lnk it writes is read
      back: target wscript.exe, arguments '/nologo "<dir>rc_watcher_launch.vbs"',
      working folder, window style 7. A positive control runs the OLD block
      in the same harness and finds no .lnk, so the harness can see the
      defect. Only the shortcut command runs: not the del lines, not the
      .vbs writer, not the pause; APPDATA and USERPROFILE also point into
      tmp_path, so nothing reaches the real Startup folder.
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
BAT = "ops/install_startup.bat"
_PS_HEAD = '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"'
_LNK = "RiotCommanderWatcher.lnk"

# The block as it stood before RM-826 (b), for the positive control.
_OLD_BLOCK = [
    _PS_HEAD + " -Command ^",
    '  "$ws = New-Object -ComObject WScript.Shell; ^',
    "   $s = $ws.CreateShortcut('%STARTUP%\\RiotCommanderWatcher.lnk'); ^",
    "   $s.TargetPath = 'wscript.exe'; ^",
    "   $s.Arguments = '/nologo \\\"%SCRIPT_DIR%rc_watcher_launch.vbs\\\"'; ^",
    "   $s.WorkingDirectory = '%SCRIPT_DIR%'; ^",
    "   $s.Description = 'Riot Commander League Watcher'; ^",
    "   $s.WindowStyle = 7; ^",
    '   $s.Save()"',
]


def in_quote_carets(lines: list[str]) -> list[tuple[int, str]]:
    """(line, text) for each line that ends in ^ while cmd is inside a double
    quote. There the caret is a literal: the command ends with the line, and
    the next line runs as a command of its own. A continuation outside quotes
    always resumes outside quotes, so each physical line starts outside."""
    hits = []
    for n, raw in enumerate(lines, 1):
        s = raw.rstrip()
        if not s.endswith("^") or _is_comment(s.strip()):
            continue
        quoted = False
        i = 0
        body = s[:-1]
        while i < len(body):
            if body[i] == '"':
                quoted = not quoted
            elif body[i] == "^" and not quoted:
                i += 1  # an escaped character, never a quote toggle
            i += 1
        if quoted:
            hits.append((n, s))
    return hits


def _lines() -> list[str]:
    return (REPO / BAT).read_text(encoding="ascii").splitlines()


def _shortcut_cut(lines: list[str]) -> list[str]:
    """The PowerShell shortcut command: its first line plus every line a
    trailing caret joins to it (what cmd would read, carets taken at face
    value, so the old block yields all of its lines)."""
    begin = next(i for i, ln in enumerate(lines) if ln.strip().startswith(_PS_HEAD))
    end = begin
    while lines[end].rstrip().endswith("^") and end + 1 < len(lines):
        end += 1
    return [ln.strip() for ln in lines[begin:end + 1]]


def test_the_scan_sees_the_old_block():
    # Line 2 opens the quote and ends the command; line 3 then starts a new
    # command outside quotes, so its own trailing caret is a real one.
    assert [n for n, _ in in_quote_carets(_OLD_BLOCK)] == [2]
    # Carets outside quotes (and an escaped quote outside quotes) are fine.
    assert in_quote_carets(['echo a ^', 'echo "b" ^', 'echo ^" c ^', 'echo "d"']) == []


def test_no_tracked_batch_file_ends_a_line_with_a_caret_inside_quotes():
    files = _repo_walk.repo_files(REPO, ("*.bat", "*.cmd"))
    rels = {_repo_walk.relative_posix(p, REPO): p for p in files}
    assert BAT in rels, f"{BAT} not reached - the scan proves nothing: {sorted(rels)}"
    hits = {rel: in_quote_carets(p.read_text(encoding="latin-1").splitlines())
            for rel, p in rels.items()}
    assert {rel: h for rel, h in hits.items() if h} == {}


def test_the_shortcut_command_pastes_no_cmd_variable_into_powershell():
    cut = _shortcut_cut(_lines())
    assert len(cut) == 1, f"{BAT}: the shortcut command spans lines: {cut}"
    line = cut[0]
    assert line.startswith(_PS_HEAD + " "), line
    script = line[len(_PS_HEAD):]
    assert re.findall(r"%[^%\s]+%", script) == [], (
        f"{BAT}: a cmd variable is pasted into the PowerShell source: {line}")
    for name in ("$env:SCRIPT_DIR", "$env:STARTUP", _LNK, "$s.Save()"):
        assert name in script, (name, line)
    assert "^" not in script, line


win_only = pytest.mark.skipif(sys.platform != "win32", reason="runs cmd.exe and PowerShell")
_POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows"),
                   "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def _folders(tmp_path: Path) -> tuple[Path, Path]:
    script_dir = tmp_path / "R&D it's" / "ops"
    startup = tmp_path / "Start Menu's" / "Startup"
    script_dir.mkdir(parents=True)
    startup.mkdir(parents=True)
    return script_dir, startup


def _env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["APPDATA"] = str(tmp_path / "appdata")
    env["USERPROFILE"] = str(tmp_path / "profile")
    return env


def _run(tmp_path: Path, body: list[str], script_dir: Path, startup: Path):
    refused = [ln for ln in body
               if re.search(r"%APPDATA%|%USERPROFILE%|^\s*(?:del|start|pause|wscript)\b",
                            ln, re.IGNORECASE)]
    assert not refused, f"the cut would touch something real: {refused}"
    bat = tmp_path / "harness" / "install_startup_harness.bat"
    bat.parent.mkdir(exist_ok=True)
    head = ["@echo off", "setlocal",
            f'set "SCRIPT_DIR={script_dir}\\"', f'set "STARTUP={startup}"']
    bat.write_bytes(("\r\n".join(head + body) + "\r\n").encode("ascii"))
    return subprocess.run(["cmd.exe", "/d", "/c", str(bat)], cwd=bat.parent,
                          env=_env(tmp_path), capture_output=True, timeout=120,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _read_back(tmp_path: Path, lnk: Path) -> list[str]:
    env = _env(tmp_path)
    env["RC_TEST_LNK"] = str(lnk)
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:RC_TEST_LNK); "
          "$s.TargetPath; $s.Arguments; $s.WorkingDirectory; [string]$s.WindowStyle")
    proc = subprocess.run([str(_POWERSHELL), "-NoProfile", "-Command", ps],
                          env=env, capture_output=True, text=True, timeout=120,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.splitlines()


@win_only
def test_the_old_block_makes_no_shortcut(tmp_path):
    # Positive control: the harness sees the defect this row removed.
    script_dir, startup = _folders(tmp_path)
    proc = _run(tmp_path, _shortcut_cut(_OLD_BLOCK), script_dir, startup)
    assert not (startup / _LNK).exists(), proc.stdout + proc.stderr
    assert b"not recognized" in proc.stderr, proc.stdout + proc.stderr


@win_only
def test_the_shortcut_is_created_and_reads_back(tmp_path):
    script_dir, startup = _folders(tmp_path)
    proc = _run(tmp_path, _shortcut_cut(_lines()), script_dir, startup)
    lnk = startup / _LNK
    assert lnk.is_file(), proc.stdout + proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
    target, args, workdir, style = _read_back(tmp_path, lnk)
    assert target.lower().endswith("wscript.exe"), target
    assert args == f'/nologo "{script_dir}\\rc_watcher_launch.vbs"', args
    assert workdir.rstrip("\\") == str(script_dir), workdir
    assert style == "7", style
    assert sorted(p.name for p in startup.iterdir()) == [_LNK]
