"""tests/test_postmortem_runner_pipe.py - RC-PostmortemAnalyze wrapper pipe drain.

Regression cover for the redirected-pipe deadlock in
`ops/run_postmortem_with_restart.ps1`.

The wrapper used to call `WaitForExit()` BEFORE `ReadToEnd()`. When the child
writes more than the ~4 KB OS pipe buffer the child blocks on a full pipe while
the parent blocks waiting for the child to exit, so neither side ever proceeds.
The scheduled task's ExecutionTimeLimit (PT15M) then kills the run with
2147946720 (0x800710E0 / Win32 4320) and nothing is logged - the noisiest run is
exactly the one that cannot complete OR record why.

These tests exercise the REAL script's drain helper against a synthetic child
that deliberately overruns both pipe buffers. The real analyzer child is never
executed: it rewrites data/coaching/death_patterns.json and writes
restart_trigger.txt, which bounces the live RC supervisor.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "ops" / "run_postmortem_with_restart.ps1"

# Each stream gets far more than the ~4 KB OS pipe buffer.
PAYLOAD_BYTES = 256 * 1024

# Glyphs banned repo-wide (7-bit ASCII authored content). Doubly load-bearing
# in a no-BOM .ps1: PowerShell 5.1 ANSI-decodes the file, so a UTF-8 em-dash
# inside a double-quoted string becomes a smart quote that terminates the
# string and cascades into a parse failure (2026-05-18 boot-script incident).
# The repo already has a global banned-glyph guard; this is a local
# belt-and-braces on this one file, not a replacement for it.
BANNED_GLYPHS = {
    "\u2014": "EM DASH",
    "\u2013": "EN DASH",
    "\u2018": "LEFT SINGLE QUOTE",
    "\u2019": "RIGHT SINGLE QUOTE",
    "\u201c": "LEFT DOUBLE QUOTE",
    "\u201d": "RIGHT DOUBLE QUOTE",
}


def _powershell() -> str:
    """Absolute path to Windows PowerShell 5.1, or skip the test."""
    fixed = pathlib.Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if fixed.is_file():
        return str(fixed)
    found = shutil.which("powershell")
    if not found:
        pytest.skip("Windows PowerShell 5.1 not available on this host")
    return found


def _kill_tree(pid: int) -> None:
    """Hard-kill a wedged process tree. Never Stop-Process (hangs the MCP pipe)."""
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        check=False,
    )


def _write_chatty_child(tmp_path: pathlib.Path) -> pathlib.Path:
    """A synthetic child that overruns BOTH pipe buffers, then exits 0.

    Raw byte writes (no newline translation, no trailing newline) so the parent
    side sees an exact, assertable length.
    """
    child = tmp_path / "chatty_child.py"
    child.write_text(
        "import sys\n"
        f"sys.stdout.buffer.write(b'A' * {PAYLOAD_BYTES})\n"
        "sys.stdout.buffer.flush()\n"
        f"sys.stderr.buffer.write(b'B' * {PAYLOAD_BYTES})\n"
        "sys.stderr.buffer.flush()\n"
        "sys.exit(0)\n",
        encoding="ascii",
    )
    return child


def _assert_safe_to_dot_source() -> None:
    """Refuse to dot-source the script unless -LibraryOnly is still declared.

    MEASURED THE HARD WAY 2026-09-29: PowerShell SILENTLY IGNORES an unknown
    argument passed to a script that has no param block. Dot-sourcing a version
    of this script without -LibraryOnly therefore does not error - it runs the
    entire main body, which executes the REAL analyzer, rewrites
    data/coaching/death_patterns.json and writes restart_trigger.txt, bouncing
    the live RC supervisor. This guard turns that catastrophe into a clean
    assertion failure.
    """
    text = SCRIPT.read_text(encoding="ascii")
    assert re.search(r"^param\(\[switch\]\$LibraryOnly\)\s*$", text, flags=re.MULTILINE), (
        "run_postmortem_with_restart.ps1 no longer declares param([switch]$LibraryOnly) - "
        "refusing to dot-source it, because PowerShell would ignore the switch and run "
        "the REAL analyzer plus the restart trigger"
    )
    body_start = text.index("if ($LibraryOnly) { return }")
    assert body_start < text.index("Test-Path $Python"), (
        "the -LibraryOnly early return no longer precedes the main body - "
        "dot-sourcing would execute the real run"
    )


def _run_driver(driver: pathlib.Path, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_kv(stdout: str) -> dict:
    out = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


@pytest.mark.timeout(180)
def test_drain_captures_both_oversized_streams_without_deadlock(tmp_path):
    """The REAL script's drain helper survives 256 KB on stdout AND stderr."""
    _assert_safe_to_dot_source()
    child = _write_chatty_child(tmp_path)
    driver = tmp_path / "drive_real_drain.ps1"
    driver.write_text(
        '$ErrorActionPreference = "Stop"\n'
        f'. "{SCRIPT}" -LibraryOnly\n'
        f'$r = Invoke-DrainedProcess -FilePath "{sys.executable}" -Arguments \'"{child}"\'\n'
        'Write-Output ("OUTLEN=" + $r.StdOut.Length)\n'
        'Write-Output ("ERRLEN=" + $r.StdErr.Length)\n'
        'Write-Output ("CODE=" + $r.ExitCode)\n',
        encoding="ascii",
    )

    try:
        # Generous but finite: a regression surfaces as a timeout failure, not
        # as a suite that hangs forever.
        proc = _run_driver(driver, timeout=90)
    except subprocess.TimeoutExpired as exc:
        _kill_tree(exc.args[0] if isinstance(exc.args[0], int) else 0)
        pytest.fail(
            "Invoke-DrainedProcess deadlocked on an oversized child: the drain "
            "must start BOTH stream reads before waiting for exit."
        )

    assert proc.returncode == 0, f"driver failed rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    kv = _parse_kv(proc.stdout)
    assert kv.get("CODE") == "0", f"child exit code not preserved: {kv}"
    assert kv.get("OUTLEN") == str(PAYLOAD_BYTES), f"stdout truncated: {kv}"
    assert kv.get("ERRLEN") == str(PAYLOAD_BYTES), f"stderr truncated: {kv}"


@pytest.mark.timeout(180)
def test_old_wait_then_read_pattern_deadlocks(tmp_path):
    """Positive control: the OLD ordering really does wedge on the same child.

    Run against a throwaway copy of the old pattern in tmp_path - NEVER against
    the real script file. Without this control, the test above could pass for
    reasons unrelated to the drain ordering.
    """
    child = _write_chatty_child(tmp_path)
    driver = tmp_path / "drive_old_pattern.ps1"
    driver.write_text(
        '$ErrorActionPreference = "Stop"\n'
        "$startInfo = New-Object System.Diagnostics.ProcessStartInfo\n"
        f'$startInfo.FileName = "{sys.executable}"\n'
        f"$startInfo.Arguments = '\"{child}\"'\n"
        "$startInfo.RedirectStandardOutput = $true\n"
        "$startInfo.RedirectStandardError = $true\n"
        "$startInfo.UseShellExecute = $false\n"
        "$startInfo.CreateNoWindow = $true\n"
        "$proc = [System.Diagnostics.Process]::Start($startInfo)\n"
        "$proc.WaitForExit()\n"
        "$out = $proc.StandardOutput.ReadToEnd()\n"
        "$err = $proc.StandardError.ReadToEnd()\n"
        'Write-Output ("OUTLEN=" + $out.Length)\n'
        'Write-Output ("ERRLEN=" + $err.Length)\n',
        encoding="ascii",
    )

    wedged = False
    proc = subprocess.Popen(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        proc.communicate(timeout=25)
    except subprocess.TimeoutExpired:
        wedged = True
    finally:
        if proc.poll() is None:
            _kill_tree(proc.pid)
            proc.kill()
            proc.wait(timeout=30)

    assert wedged, (
        "the old WaitForExit-then-ReadToEnd ordering completed, so this control "
        "no longer demonstrates the deadlock it is meant to pin"
    )


def _instrument_script(
    tmp_path: pathlib.Path,
    python_exe: str,
    analyzer: str,
    trigger: pathlib.Path,
    log_dir: pathlib.Path,
) -> pathlib.Path:
    """A copy of the REAL script with its four constants redirected into tmp.

    Everything below the constants - the drain, the log format, the success
    gate, the exit-code passthrough - is the production code path verbatim.
    Redirecting the constants is what keeps the real analyzer from running and
    the real restart_trigger.txt from bouncing the live RC supervisor.
    """
    text = SCRIPT.read_text(encoding="ascii")
    swaps = {
        r"^\$Python\s+= .*$": f'$Python  = "{python_exe}"',
        r"^\$Script\s+= .*$": f'$Script  = "{analyzer}"',
        r"^\$Trigger\s+= .*$": f'$Trigger = "{trigger}"',
        r"^\$LogDir\s+= .*$": f'$LogDir  = "{log_dir}"',
    }
    for pattern, replacement in swaps.items():
        text, count = re.subn(pattern, lambda _m, r=replacement: r, text, count=1, flags=re.MULTILINE)
        assert count == 1, f"constant line {pattern!r} no longer matches the script"

    instrumented = tmp_path / "instrumented_runner.ps1"
    instrumented.write_text(text, encoding="ascii")
    return instrumented


def _write_fake_analyzer(tmp_path: pathlib.Path, exit_code: int) -> pathlib.Path:
    """Stand-in for scripts/postmortem_analyze.py - chatty, then a chosen exit."""
    analyzer = tmp_path / f"fake_analyzer_{exit_code}.py"
    analyzer.write_text(
        "import sys\n"
        f"sys.stdout.buffer.write(b'A' * {PAYLOAD_BYTES})\n"
        "sys.stdout.buffer.flush()\n"
        f"sys.stderr.buffer.write(b'B' * {PAYLOAD_BYTES})\n"
        "sys.stderr.buffer.flush()\n"
        f"sys.exit({exit_code})\n",
        encoding="ascii",
    )
    return analyzer


def _sole_log(log_dir: pathlib.Path) -> str:
    logs = sorted(log_dir.glob("postmortem_analyze.*.log"))
    assert len(logs) == 1, f"expected exactly one dated log, got {logs}"
    return logs[0].read_text(encoding="latin-1")


@pytest.mark.timeout(180)
@pytest.mark.parametrize("exit_code", [0, 2, 3])
def test_end_to_end_run_logs_and_gates_the_trigger(tmp_path, exit_code):
    """Whole-script run on a chatty child: no deadlock, log format intact.

    Covers the GOOD behaviour that must not regress - the exit-code line is
    written UNCONDITIONALLY, so a nonzero analyzer exit is still recorded, and
    the restart trigger fires ONLY on exit 0.
    """
    log_dir = tmp_path / "logs"
    trigger = tmp_path / "restart_trigger.txt"
    analyzer = _write_fake_analyzer(tmp_path, exit_code)
    runner = _instrument_script(tmp_path, sys.executable, str(analyzer), trigger, log_dir)

    try:
        proc = _run_driver(runner, timeout=90)
    except subprocess.TimeoutExpired as exc:
        _kill_tree(exc.args[0] if isinstance(exc.args[0], int) else 0)
        pytest.fail("the wrapper deadlocked end to end on a chatty analyzer child")

    assert proc.returncode == exit_code, (
        f"exit-code semantics changed: expected {exit_code}, got {proc.returncode}\n{proc.stderr}"
    )

    body = _sole_log(log_dir)
    assert re.search(rf"^=== \S+ exit={exit_code} ===$", body, flags=re.MULTILINE), (
        f"exit-code marker line missing or reformatted for exit={exit_code}"
    )
    assert "A" * PAYLOAD_BYTES in body, "stdout was truncated on the way to the log"
    assert "B" * PAYLOAD_BYTES in body, "stderr was truncated on the way to the log"

    if exit_code == 0:
        assert trigger.is_file(), "restart trigger not written on a clean analyzer run"
        assert trigger.read_text(encoding="ascii").strip() == "postmortem-analyze refresh"
        assert "restart_trigger.txt written" in body
    else:
        assert not trigger.exists(), f"restart trigger fired on a failed run (exit={exit_code})"
        assert "restart_trigger.txt written" not in body


@pytest.mark.timeout(120)
def test_missing_interpreter_fails_loudly_not_silently(tmp_path):
    """A missing interpreter used to produce a totally silent scheduled-task run."""
    log_dir = tmp_path / "logs"
    trigger = tmp_path / "restart_trigger.txt"
    analyzer = _write_fake_analyzer(tmp_path, 0)
    missing = tmp_path / "no_such_python.exe"
    runner = _instrument_script(tmp_path, str(missing), str(analyzer), trigger, log_dir)

    proc = _run_driver(runner, timeout=60)

    assert proc.returncode != 0, "a missing interpreter must not report success"
    assert log_dir.is_dir(), "log directory was not created before the early bail"
    body = _sole_log(log_dir)
    assert re.search(r"^=== \S+ exit=1 ===$", body, flags=re.MULTILINE), (
        "early failure did not record an exit-code marker line"
    )
    assert "FATAL:" in body and "no_such_python.exe" in body, (
        f"early failure did not name the missing interpreter:\n{body}"
    )
    assert not trigger.exists(), "restart trigger fired despite an early failure"


@pytest.mark.timeout(120)
def test_script_parses_cleanly_under_powershell_51():
    """A .ps1 that does not parse is a silent Sunday-morning failure."""
    ps = _powershell()
    command = (
        "$errs = $null; $toks = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', "
        "[ref]$toks, [ref]$errs); "
        "if ($errs -and $errs.Count -gt 0) { "
        "foreach ($e in $errs) { Write-Output ('PARSE_ERROR: ' + $e.Message) } } "
        "else { Write-Output 'PARSE_OK' }"
    )
    proc = subprocess.run(
        [ps, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, f"parser probe failed: {proc.stdout}\n{proc.stderr}"
    assert "PARSE_OK" in proc.stdout, f"script does not parse:\n{proc.stdout}\n{proc.stderr}"


def test_dot_source_guard_holds():
    """Pin the guard itself - it is the only thing between a test run and a live bounce."""
    _assert_safe_to_dot_source()


def test_script_has_no_banned_glyphs():
    raw = SCRIPT.read_bytes()
    text = raw.decode("utf-8")
    hits = sorted({name for glyph, name in BANNED_GLYPHS.items() if glyph in text})
    assert not hits, f"{SCRIPT.name} carries banned glyph(s): {hits}"
    assert raw.decode("ascii", errors="strict"), "script must be 7-bit ASCII"


def test_drain_is_concurrent_not_serialized():
    """Guard the fix itself: no synchronous ReadToEnd() may survive."""
    text = SCRIPT.read_text(encoding="ascii")
    assert not re.search(r"\.ReadToEnd\(\)", text), (
        "synchronous ReadToEnd() found - serializing stdout then stderr just "
        "moves the deadlock to the other pipe"
    )
    assert ".ReadToEndAsync()" in text, "expected an asynchronous drain of both streams"


def test_log_format_and_restart_trigger_are_preserved():
    """The GOOD behaviour already in the script must not regress."""
    text = SCRIPT.read_text(encoding="ascii")

    marker = '"=== $ts exit=$code ==="'
    assert marker in text, "unconditional exit-code log line is missing"

    gate = "if ($code -eq 0)"
    assert gate in text, "restart-trigger success gate is missing"
    assert text.index(marker) < text.index(gate), (
        "the exit-code log line must be written UNCONDITIONALLY, before the "
        "success gate, so a nonzero exit is still recorded"
    )

    assert 'Set-Content -Path $Trigger -Value "postmortem-analyze refresh" -Encoding ASCII' in text
    assert '"restart_trigger.txt written"' in text
    assert re.search(r"^exit \$code\s*$", text, flags=re.MULTILINE), "exit-code semantics changed"


def test_early_failure_path_logs_before_it_bails():
    """A missing interpreter must not fail silently under ErrorActionPreference Stop."""
    text = SCRIPT.read_text(encoding="ascii")
    py_check = text.index("if (-not (Test-Path $Python))")
    log_built = text.index('$Log   = Join-Path $LogDir')
    assert log_built < py_check, (
        "the log path must be built BEFORE the interpreter/script existence "
        "checks, otherwise an early failure is completely silent"
    )
    assert "FATAL:" in text, "early-failure path does not write a diagnosable log line"
