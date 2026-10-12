"""RC-PostmortemAnalyze must launch through the hidden wscript wrapper.

WHY THIS EXISTS (MAIN FIX note 2026-10-11 2226). The live task action read back
on 2026-10-12 was `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
...run_postmortem_with_restart.ps1` with no -WindowStyle Hidden, while
ops/install_RC_PostmortemAnalyze.ps1 carried the flag: the live registration
had drifted from the installer. And -WindowStyle Hidden is not enough anyway:
Windows PowerShell 5.1 is a console program, so conhost paints the window
first and the host hides it only after it has initialised (MAIN measured an
8+ s visible window for its own console task; closing it kills the script with
0xC000013A). The task is S4U today, so the window lands on a non-interactive
desktop - this pins the fix so a principal change cannot bring the flash back.

THE FIX PINNED HERE. The task executes `wscript.exe //B //NoLogo
ops\\run_postmortem_hidden.vbs`; the .vbs calls WScript.Shell Run(cmd, 0, True)
- window style 0 creates the console hidden from the start, True waits - and
returns the child's exit code through WScript.Quit, so LastTaskResult still
carries the analyzer's 0 / 2 / 3. //B keeps a script error from raising a
modal dialog that would hold the task until its ExecutionTimeLimit.

The installer also exports the existing task XML to the gitignored
ops/runtime/task_backups/ BEFORE it unregisters anything, and reads the action
back after registering. The behavioural arm runs a COPY of the .vbs next to a
stub .ps1 in tmp_path; the real postmortem wrapper is never executed (it
rewrites data/coaching/death_patterns.json and bounces the live supervisor).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VBS = ROOT / "ops" / "run_postmortem_hidden.vbs"
PS1 = ROOT / "ops" / "install_RC_PostmortemAnalyze.ps1"
TARGET_PS1 = "run_postmortem_with_restart.ps1"


def _read(path: Path) -> str:
    assert path.is_file(), f"{path} is missing"
    return path.read_bytes().decode("ascii")


def _live_lines(text: str, comment: str) -> list[str]:
    """Lines that are not comments (`#` for ps1, `'` for VBScript)."""
    return [ln for ln in text.split("\n")
            if ln.strip() and not ln.lstrip().startswith(comment)]


def _single(pattern: str, lines: list[str], label: str) -> re.Match:
    """Exactly one live-line match - zero is a vacuous pass, two a contradiction."""
    hits = [m for ln in lines for m in [re.search(pattern, ln)] if m]
    assert len(hits) == 1, f"{label}: expected 1 live match for {pattern!r}, found {len(hits)}"
    return hits[0]


# ---------------------------------------------------------------------------
# Encoding: ASCII only, LF only, and git keeps the .vbs LF on checkout.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [VBS, PS1], ids=lambda p: p.name)
def test_file_is_ascii_and_lf_only(path: Path) -> None:
    raw = path.read_bytes()
    assert raw, f"{path.name} is empty"
    raw.decode("ascii")  # raises on any non-ASCII byte
    assert b"\r" not in raw, f"{path.name} carries CR bytes; LF only"
    assert raw.endswith(b"\n"), f"{path.name} does not end in a newline"


def test_vbs_is_pinned_eol_lf_in_gitattributes() -> None:
    # .vbs is not in the `*.<ext> text eol=lf` list, so without a path pin a
    # core.autocrlf=true checkout writes this file CRLF.
    proc = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", "ops/run_postmortem_hidden.vbs"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert "text: set" in proc.stdout and "eol: lf" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# The wrapper.
# ---------------------------------------------------------------------------


def test_vbs_runs_hidden_and_waits() -> None:
    lines = _live_lines(_read(VBS), "'")
    _single(r'CreateObject\("WScript\.Shell"\)', lines, "WScript.Shell")
    m = _single(r"(\w+)\s*=\s*\w+\.Run\(\s*\w+\s*,\s*(\w+)\s*,\s*(\w+)\s*\)", lines, "Run call")
    assert m.group(2) == "0", f"window style is {m.group(2)}, must be 0 (hidden)"
    assert m.group(3) == "True", f"wait flag is {m.group(3)}, must be True"
    # The Run result is what WScript.Quit returns, so LastTaskResult is the child's.
    _single(rf"^\s*WScript\.Quit\s+{re.escape(m.group(1))}\s*$", lines, "Quit with Run code")


def test_vbs_derives_paths_from_its_own_location() -> None:
    text = _read(VBS)
    lines = _live_lines(text, "'")
    _single(r"GetParentFolderName\(WScript\.ScriptFullName\)", lines, "own folder")
    assert any(TARGET_PS1 in ln for ln in lines), f"{VBS.name} does not name {TARGET_PS1}"
    assert not re.search(r"[A-Za-z]:\\", text), f"{VBS.name} carries an absolute machine path"
    _single(r"^\s*Option Explicit\s*$", lines, "Option Explicit")


def test_vbs_command_line_keeps_the_task_flags() -> None:
    lines = _live_lines(_read(VBS), "'")
    cmd = _single(r'"powershell\.exe [^"]*', lines, "powershell command").group(0)
    for flag in ("-NoProfile", "-ExecutionPolicy Bypass", "-File"):
        assert flag in cmd, f"inner command lost {flag}: {cmd}"


# ---------------------------------------------------------------------------
# The installer.
# ---------------------------------------------------------------------------


def test_installer_registers_wscript_and_the_wrapper() -> None:
    lines = _live_lines(_read(PS1), "#")
    _single(r'^\$Wscript\s*=\s*"wscript\.exe"\s*$', lines, "wscript exe")
    _single(r'^\$Launcher\s*=\s*Join-Path \$PSScriptRoot "run_postmortem_hidden\.vbs"\s*$',
            lines, "launcher path")
    args = _single(r'^\$Arguments\s*=\s*"(.*)"\s*$', lines, "arguments").group(1)
    assert "//B" in args and "//NoLogo" in args and "$Launcher" in args, args
    _single(r"-Execute\s+\$Wscript\b", lines, "-Execute $Wscript")
    executes = [ln for ln in lines if "-Execute" in ln]
    assert executes and not any("powershell" in ln.lower() or "$PsExe" in ln for ln in executes), (
        f"the task must not execute powershell.exe directly: {executes}")


def test_installer_backs_up_before_unregistering() -> None:
    text = _read(PS1)
    lines = _live_lines(text, "#")
    live = "\n".join(lines)
    _single(r"Export-ScheduledTask\s+-TaskName\s+\$TaskName", lines, "export")
    _single(r'^\$BackupDir\s*=\s*Join-Path \$Root "ops\\runtime\\task_backups"\s*$',
            lines, "backup dir under ops/runtime")
    _single(r'Get-Date -Format "yyyyMMdd-HHmmss"', lines, "timestamped backup")
    export_at = live.index("Export-ScheduledTask")
    unregister_at = live.index("Unregister-ScheduledTask")
    register_at = live.index("Register-ScheduledTask `")
    assert export_at < unregister_at < register_at, "backup must precede unregister"


def test_installer_reads_the_action_back_after_registering() -> None:
    live = "\n".join(_live_lines(_read(PS1), "#"))
    register_at = live.index("Register-ScheduledTask `")
    after = live[register_at:]
    assert "Show-TaskAction" in after, "no read-back after Register-ScheduledTask"
    body = live[live.index("function Show-TaskAction"):]
    assert ".Actions" in body and ".Execute" in body and ".Arguments" in body


def test_installer_keeps_trigger_principal_and_settings() -> None:
    lines = _live_lines(_read(PS1), "#")
    _single(r"New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4:15AM", lines, "trigger")
    _single(r"-LogonType S4U", lines, "S4U")
    _single(r"-RunLevel Highest", lines, "RunLevel")
    _single(r"-ExecutionTimeLimit \(New-TimeSpan -Minutes 15\)", lines, "ETL")
    _single(r'\$settings\.MultipleInstances\s*=\s*"IgnoreNew"', lines, "IgnoreNew")
    _single(r"-StartWhenAvailable", lines, "StartWhenAvailable")


def test_installer_parses_under_windows_powershell_51() -> None:
    ps = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if not ps.is_file():
        pytest.skip("Windows PowerShell 5.1 not available on this host")
    command = (
        "$e = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{PS1}', [ref]$null, [ref]$e); "
        "Write-Output ('ERRORS=' + $e.Count)"
    )
    proc = subprocess.run([str(ps), "-NoProfile", "-Command", command],
                          capture_output=True, text=True, timeout=90)
    assert "ERRORS=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"


# ---------------------------------------------------------------------------
# Behaviour: a COPY of the wrapper next to a stub, never the real postmortem.
# ---------------------------------------------------------------------------


def _wscript() -> str:
    if sys.platform != "win32":
        pytest.skip("wscript.exe is Windows-only")
    found = shutil.which("wscript.exe")
    if not found:
        pytest.skip("wscript.exe not on PATH")
    return found


@pytest.mark.timeout(120)
def test_wrapper_waits_and_propagates_the_exit_code(tmp_path: Path) -> None:
    wscript = _wscript()
    shutil.copyfile(VBS, tmp_path / VBS.name)
    marker = tmp_path / "ran.txt"
    (tmp_path / TARGET_PS1).write_text(
        f"Set-Content -Path '{marker}' -Value 'ran' -Encoding ASCII\nexit 7\n",
        encoding="ascii", newline="\n")
    proc = subprocess.run([wscript, "//B", "//NoLogo", str(tmp_path / VBS.name)],
                          capture_output=True, timeout=90)
    assert proc.returncode == 7, f"exit code not propagated: {proc.returncode}"
    assert marker.read_text(encoding="ascii").strip() == "ran", "wrapper did not wait"


@pytest.mark.timeout(120)
def test_wrapper_fails_closed_when_the_target_is_missing(tmp_path: Path) -> None:
    wscript = _wscript()
    shutil.copyfile(VBS, tmp_path / VBS.name)
    proc = subprocess.run([wscript, "//B", "//NoLogo", str(tmp_path / VBS.name)],
                          capture_output=True, timeout=90)
    assert proc.returncode == 90, f"missing target must exit 90, got {proc.returncode}"
