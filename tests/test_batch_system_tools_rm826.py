"""RM-826 (a): every tracked batch file runs Windows system tools by path.

WHY THIS FILE EXISTS. RM-810 (68ab95b8f) moved scripts/restart.bat's wmic /
taskkill / timeout to their System32 paths, because cmd looks a bare command
name up in the CURRENT folder before PATH, so a taskkill.bat or timeout.cmd
planted there runs instead (third RM-810 verifier). Its guard
(tests/test_launcher_key_read_rm810.py) covered only the three key-reading
launchers, so the same shape stayed in scripts/kill.bat:4-5 and
scripts/restart_clean.bat:17-18 (the two RM-826 names), and the sibling sweep
for this row found it in five more tracked batch files at 4486a09bb:
ops/autostart_on_login.bat:10, 15-16 and its `start ... cmd /C` target (:19),
ops/launch_new_system.bat:18-20, 47 and its `start ... powershell.exe` target
(:37), ops/start_ops.bat:16, ops/install_startup.bat:27,
scripts/bootstrap_dev.cmd:3, tools/preflight.cmd:16 (`where`) and
tools/snapshot.cmd:11 (powershell inside a `for /f ('...')` clause; found by
the first verifier, which the RM-810 command-token scan cannot see).
RM-721 (d) (session 144) later archived the dormant autostart_on_login.bat /
launch_new_system.bat pair to docs/_archive/2026-10/, outside this scan, so
the reach anchor in _batch_files names ops/start_ops.bat instead.

The RM-810 tool map also named powershell as %SystemRoot%\\System32\\
powershell.exe, a path that does not exist (Windows PowerShell lives under
WindowsPowerShell\\v1.0); no launcher ran powershell, so nothing caught it.
That map is the one source both guards read, so it is fixed there and its
entries are checked against disk here.

Pinned here:
  (a) static: in every tracked .bat / .cmd, a system tool from the RM-810 map
      that is run as a command - at a command start, as the program of a
      `start`, inside a `for /f` clause, after `call`, after an `if`
      condition with no "(" or after `else` - is named by its quoted absolute
      path from that map. Still not seen: a tool name built from a variable,
      and a command after a caret continuation;
  (b) every mapped path exists on this machine (Windows only; wmic is exempt
      - it is an optional feature on current Windows builds, so its absence
      is not a mapping error);
  (c) behaviour: the taskkill / timeout / where lines of every tracked batch
      file run under cmd.exe from a folder holding planted .bat / .cmd files
      of those names, and none of the plants runs. Lines are made harmless
      first: taskkill aims at an image no process has, `where` looks for a
      name nothing has, and a cut holding a start / python / main.py line is
      refused.
Not in scope, recorded as RM-826 residuals: a bare python / pythonw (the (f)
shape) and tool names written into generated text (install_startup.bat's .vbs
and PowerShell string, the (b) shape).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _repo_walk
from tests.test_launcher_key_read_rm810 import _CMD_TOKEN, _PLANT, _SYSTEM_TOOLS, _is_comment

REPO = Path(__file__).resolve().parent.parent

_PROG = r'("[^"]*"|[^\s&|()\'`]+)'
# Commands the RM-810 _CMD_TOKEN does not see (verifier round 1):
#   - the program a `start` runs, after /switches and an optional quoted title
#     in either order;
#   - the command of a `for /f ('...')` / ('`...`') clause, which cmd runs in
#     a child cmd /c (tools/snapshot.cmd:11 ran powershell there);
#   - the command after `call`, after an `if` condition with no "(", and
#     after `else`. A lookahead, so a nested `if ... if ...` is read twice.
_EXTRA_TOKENS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r'(?:^|[&|(]|\bdo\s)\s*@?start\s+(?:/\S+\s+)*(?:"[^"]*"\s+)?(?:/\S+\s+)*' + _PROG,
    r'\(\s*[\'`]\s*@?' + _PROG,
    r'\bcall\s+' + _PROG,
    r'(?=\bif\s+(?:/i\s+)?(?:not\s+)?(?:(?:exist|defined)\s+(?:"[^"]*"|\S+)'
    r'|(?:errorlevel|cmdextversion)\s+\S+'
    r'|(?:"[^"]*"|\S+?)\s*(?:==|\s(?:equ|neq|lss|leq|gtr|geq)\s)\s*(?:"[^"]*"|\S+))'
    r'\s+@?' + _PROG + ')',
    r'\belse\s+@?' + _PROG,
))

_ROW_NAMES = ("scripts/kill.bat", "scripts/restart_clean.bat")


def _tool_name(token: str) -> str:
    name = re.split(r"[\\/]", token.strip('"'))[-1].lower()
    return name.removesuffix(".exe")


def _batch_files() -> dict[str, list[str]]:
    files = _repo_walk.repo_files(REPO, ("*.bat", "*.cmd"))
    out = {_repo_walk.relative_posix(p, REPO): p.read_text(encoding="latin-1").splitlines()
           for p in files}
    assert set(_ROW_NAMES) | {"scripts/restart.bat", "ops/start_ops.bat"} <= set(out), (
        f"batch files not reached - the scan proves nothing: {sorted(out)}")
    return out


def bare_tool_runs(lines: list[str]) -> list[tuple[int, str, str]]:
    """(line, tool, token) for each system tool run by anything but its
    quoted absolute path from the RM-810 map."""
    hits = []
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or _is_comment(s):
            continue
        for rx in (_CMD_TOKEN, *_EXTRA_TOKENS):
            for m in rx.finditer(s):
                token = m.group(1)
                if token[:1] in "'`":
                    continue  # a for /f clause: read by its own pattern above
                name = _tool_name(token)
                if name in _SYSTEM_TOOLS and token != f'"{_SYSTEM_TOOLS[name]}"':
                    hits.append((n, name, token))
    return hits


def test_the_scan_catches_every_spelling_it_claims():
    shapes = [
        "taskkill /F /IM x.exe",
        "@timeout /t 2",
        "echo a & where ruff",
        "if exist x (taskkill /F /IM x.exe)",
        "for %%I in (a) do wmic process list",
        'start "" /B powershell.exe -File x.ps1',
        'start "" /B cmd /C "x.bat"',
        "start taskkill.exe /IM x.exe",
        'start /B "" timeout /t 2',
        '"%SystemRoot%\\System32\\powershell.exe" -Command x',
        "for /f %%T in ('powershell -Command Get-Date') do set T=%%T",
        "for /f \"usebackq\" %%T in (`where git`) do set G=%%T",
        "call taskkill /IM x.exe",
        "if exist x taskkill /IM y.exe",
        "if not defined X timeout /t 2",
        "if errorlevel 1 timeout /t 2",
        'if "%A%"=="" if exist x taskkill /IM y.exe',
        "if /i %A% equ b where ruff",
        ") else taskkill /IM y.exe",
    ]
    for line in shapes:
        assert bare_tool_runs([line]), line
    good = [
        '"%SystemRoot%\\System32\\taskkill.exe" /F /IM x.exe',
        'start "" /B "%SystemRoot%\\System32\\cmd.exe" /C "x.bat"',
        ":: taskkill /F /IM x.exe",
        "REM timeout /t 2",
        "echo run taskkill later",
        'start "" pythonw.exe main.py',
        "for /f %%T in ('\"%SystemRoot%\\System32\\where.exe\" git') do set G=%%T",
        "if exist x (",
        "if errorlevel 1 (",
        ") else (",
        "call :label",
        'if "%A%"=="" set A=1',
    ]
    assert [bare_tool_runs([line]) for line in good] == [[]] * len(good)


def test_no_tracked_batch_file_runs_a_system_tool_by_bare_name():
    offenders = [f"{rel}:{n} runs {name} as {token}"
                 for rel, lines in sorted(_batch_files().items())
                 for n, name, token in bare_tool_runs(lines)]
    assert not offenders, (
        "cmd looks a bare command name up in the current folder before PATH, so "
        "a planted .bat / .cmd of that name runs instead - name the tool by its "
        "System32 path (the RM-810 map): " + "; ".join(offenders))


def test_the_row_files_really_run_system_tools():
    # Anchor: an empty scan of the two RM-826 files would pass the test above
    # for the wrong reason.
    files = _batch_files()
    for rel in _ROW_NAMES:
        used = {_tool_name(m.group(1)) for ln in files[rel] for m in _CMD_TOKEN.finditer(ln.strip())}
        assert {"taskkill"} <= used & set(_SYSTEM_TOOLS), (rel, used)


win_only = pytest.mark.skipif(sys.platform != "win32", reason="checks Windows paths / cmd.exe")


@win_only
def test_every_mapped_system_tool_path_exists():
    root = os.environ.get("SystemRoot", r"C:\Windows")
    missing = [f"{name}: {path}" for name, path in sorted(_SYSTEM_TOOLS.items())
               if name != "wmic"
               and not Path(path.replace("%SystemRoot%", root)).is_file()]
    assert not missing, f"the RM-810 tool map names paths that do not exist: {missing}"


_HARNESS_TOOLS = ("taskkill", "timeout", "where")
_REFUSE = re.compile(r"\bstart\b|python|main\.py|wmic|powershell|\bcmd\b", re.IGNORECASE)


def _harmless_tool_lines() -> list[str]:
    out = []
    for rel, lines in sorted(_batch_files().items()):
        for raw in lines:
            s = raw.strip()
            if not s or _is_comment(s):
                continue
            m = _CMD_TOKEN.match(s)
            if not m or _tool_name(m.group(1)) not in _HARNESS_TOOLS:
                continue
            safe = re.sub(r"/IM\s+\S+", "/IM rc826-no-such-image.exe", s, flags=re.IGNORECASE)
            safe = re.sub(r"(where(?:\.exe)?\"?)\s+\S+", r"\1 rc826-no-such-name", safe,
                          flags=re.IGNORECASE)
            safe = safe.split("&&")[0].strip()
            assert not _REFUSE.search(safe), f"{rel}: refusing to run {safe!r}"
            if "taskkill" in safe.lower():
                # Only an /IM aimed at the dead image may run: a /PID or an
                # /FI-only line would reach real processes (verifier round 1).
                assert "/im rc826-no-such-image.exe" in safe.lower(), f"{rel}: {safe!r}"
                assert "/pid" not in safe.lower(), f"{rel}: refusing to run {safe!r}"
            out.append(safe)
    return out


@win_only
def test_no_batch_system_tool_resolves_from_the_current_folder(tmp_path):
    caller = tmp_path / "caller"
    caller.mkdir()
    for tool in _HARNESS_TOOLS:
        for ext in (".bat", ".cmd"):
            (caller / f"{tool}{ext}").write_bytes(_PLANT)
    body = _harmless_tool_lines()
    # Anchor: the kill.bat / restart_clean.bat lines must be in the cut.
    # kill.bat, restart.bat and restart_clean.bat run one taskkill each; the
    # other three lines left with the RM-721 (d) archived ops/ pair.
    assert sum("taskkill" in ln.lower() for ln in body) >= 3, body
    assert sum("timeout" in ln.lower() for ln in body) >= 3, body
    bat = tmp_path / "tools_harness.bat"
    bat.write_bytes(("\r\n".join(["@echo off", "setlocal"] + body + ["echo TOOLS=DONE"])
                     + "\r\n").encode("ascii"))
    env = {k: v for k, v in os.environ.items()
           if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}
    proc = subprocess.run(["cmd.exe", "/d", "/c", str(bat)], cwd=str(caller), env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("ascii", "replace")
    assert "TOOLS=DONE" in out, out
    assert not list(tmp_path.rglob("planted.txt")), f"a planted system tool ran: {out!r}"
