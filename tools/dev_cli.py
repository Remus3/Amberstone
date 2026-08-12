"""
tools/dev_cli.py
Amberstone - local developer/operator CLI.

Usage (from project root):
    python tools/dev_cli.py <subcommand> [options]

Or via wrapper:
    tools\\dev_cli.cmd <subcommand> [options]

Subcommands:
    status          Print environment diagnostics (read-only)
    start           Launch via start.bat (the supported project entrypoint)
    start-clean     Launch via restart_clean.bat (clears __pycache__, kills old proc)
    preflight       Run lint + syntax checks
    smoke           Run Phase 2 smoke test harness
    perf            Run Phase 2 performance probe
    snapshot        Create a git checkpoint commit
    rollback-last   Roll back the last git checkpoint (requires --yes or prompt)

Exit codes:
    0   Success (or clean no-op for snapshot/rollback when nothing to do)
    1   Failure or explicit cancellation for destructive commands
    2   Unknown subcommand or missing argument

Design rules:
  - Allowlisted subcommands only -- no arbitrary shell passthrough.
  - Each subcommand delegates to the established scripts/tools.
  - start delegates to start.bat (API key loading + pythonw main.py).
  - start-clean delegates to restart_clean.bat (kills pythonw, clears cache, relaunches).
  - Missing required tools produce a clear error, not silent fallback.
  - Destructive commands (rollback-last) require --yes flag or interactive prompt.
  - No live Riot API, no Anthropic API, no Tk, no internet required for
    status/smoke/perf. start/start-clean launch the app but do not block.
"""
import subprocess
import sys
import os
import shutil
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent


def _find_python() -> str:
    """
    Resolve the Python executable to use for spawning sub-processes.

    Priority:
      1. sys.executable  -- the interpreter running dev_cli.py right now
                            (always correct when invoked via `python dev_cli.py`)
      2. 'py'            -- Windows Py Launcher, auto-selects the right version
      3. 'python'        -- standard name on PATH

    This avoids hardcoding an absolute path while remaining explicit about
    which Python is being used.  The result is printed by `status` so the
    operator can verify it.
    """
    exe = sys.executable
    if exe and Path(exe).exists():
        return exe
    if shutil.which("py"):
        return "py"
    if shutil.which("python"):
        return "python"
    return "python"  # last resort -- will fail clearly at runtime


_PYTHON = _find_python()

# -- Helpers ----------------------------------------------------------------

def _run(args, *, cwd=None, capture=False):
    """Run a subprocess. Returns CompletedProcess. Never raises on nonzero."""
    try:
        return subprocess.run(
            args,
            cwd=cwd or str(_PROJECT_ROOT),
            capture_output=capture,
            text=True,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: command not found: {exc}")
        return subprocess.CompletedProcess(args, returncode=127)


def _require_tool(script_rel: str) -> Path:
    """Return Path to a project-relative tool/script; exit with message if missing."""
    p = _PROJECT_ROOT / script_rel
    if not p.exists():
        print(f"ERROR: required script not found: {p}")
        sys.exit(1)
    return p


def _ok(msg): print(f"  OK      {msg}")
def _warn(msg): print(f"  WARN    {msg}")
def _miss(msg): print(f"  MISSING {msg}")
def _info(msg): print(f"          {msg}")

# -- Subcommands ------------------------------------------------------------

def cmd_status() -> int:
    """Print environment diagnostics. Read-only, no side effects."""
    print("=" * 60)
    print("Amberstone -- Environment Status")
    print("=" * 60)

    # Project root
    print("\n[Project]")
    _ok(f"project root: {_PROJECT_ROOT}")
    _ok(f"python:       {_PYTHON}")
    _info(f"python version: {sys.version.split()[0]}")
    cwd = Path.cwd()
    if cwd == _PROJECT_ROOT:
        _ok(f"cwd: {cwd}  (matches project root)")
    else:
        _warn(f"cwd: {cwd}  (differs from project root -- use project root as cwd for scripts)")

    # Git
    print("\n[Git]")
    git = shutil.which("git")
    if git:
        _ok(f"git: {git}")
        r = _run(["git", "log", "--oneline", "-3"], capture=True)
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                _info(f"  {line}")
        else:
            _warn("git log failed (not a git repo?)")
    else:
        _miss("git not found in PATH")

    # Key scripts
    print("\n[Tools/Scripts]")
    scripts = [
        "tools/run_phase2_smoke.py",
        "tools/run_phase2_perf.py",
        "tools/dev_cli.py",
        "tools/preflight.cmd",
        "tools/snapshot.cmd",
        "tools/rollback_last.cmd",
        "main.py",
    ]
    for s in scripts:
        p = _PROJECT_ROOT / s
        if p.exists():
            _ok(s)
        else:
            _miss(s)

    # Launch targets (the actual paths used by start / start-clean)
    print("\n[Launch Targets]")
    launch_targets = [
        ("start",       "start.bat",         "start.bat -> pythonw main.py"),
        ("start-clean", "restart_clean.bat",  "restart_clean.bat -> kills pythonw, clears cache, relaunches"),
    ]
    for cmd_name, rel_path, description in launch_targets:
        p = _PROJECT_ROOT / rel_path
        if p.exists():
            _ok(f"{cmd_name}: {rel_path}  ({description})")
        else:
            _miss(f"{cmd_name}: {rel_path}  -- MISSING")

    # GUI launcher Python (pythonw.exe) - separate from tooling Python
    # start.bat and restart_clean.bat call pythonw.exe directly.
    # This is NOT the same as the tooling Python (_PYTHON above).
    print("\n[Launch Python / GUI Launcher]")
    _info(f"Tooling Python (dev_cli wrappers): {_PYTHON}")
    pythonw = shutil.which("pythonw") or shutil.which("pythonw.exe")
    if pythonw:
        _ok(f"pythonw.exe (GUI launcher): {pythonw}")
    else:
        _miss("pythonw.exe NOT found in PATH -- start.bat and restart_clean.bat will fail")

    # Key config files
    print("\n[Config Files]")
    configs = [
        "config/feature_flags.json",
        "config/FEATURE_POLICY.md",
        "API-Key-Claude.txt",
    ]
    for c in configs:
        p = _PROJECT_ROOT / c
        if p.exists():
            _ok(c)
        else:
            _miss(c)

    # Audit/proof dirs writability
    print("\n[Audit Directories]")
    audit_dir = _PROJECT_ROOT / "audit"
    if audit_dir.exists():
        try:
            test_f = audit_dir / ".write_test"
            test_f.write_text("x")
            test_f.unlink()
            _ok(f"audit/ is writable ({audit_dir})")
        except Exception as exc:  # noqa: BLE001
            _warn(f"audit/ not writable: {exc}")
    else:
        _miss(f"audit/ directory does not exist: {audit_dir}")

    # Runtime artifacts dir
    rt_dir = _PROJECT_ROOT / "ops" / "runtime"
    if rt_dir.exists():
        _ok("ops/runtime/ exists")
    else:
        _miss("ops/runtime/ does not exist (first run?)")

    print()
    return 0


def cmd_start() -> int:
    """Launch via start.bat -- the supported project entrypoint.
    start.bat loads the API key from API-Key-Claude.txt, then launches
    pythonw.exe main.py. Non-blocking: the CLI returns immediately.
    """
    start_bat = _require_tool("start.bat")
    print(f"Launching: {start_bat}")
    # Use Popen on the bat file so the CLI returns immediately.
    subprocess.Popen(
        ["cmd", "/c", str(start_bat)],
        cwd=str(_PROJECT_ROOT),
        shell=False,
    )
    print("App launched via start.bat. (Use 'status' to check runtime state.)")
    return 0


def cmd_start_clean() -> int:
    """Launch via restart_clean.bat -- the supported clean-start path.
    restart_clean.bat kills existing pythonw processes, clears __pycache__,
    then relaunches pythonw.exe main.py. Delegates entirely to the
    established script; dev_cli does not manually wipe any directories.
    """
    clean_bat = _require_tool("restart_clean.bat")
    print(f"Running clean start: {clean_bat}")
    r = _run(["cmd", "/c", str(clean_bat)])
    return r.returncode


def cmd_preflight() -> int:
    """Run preflight checks (lint + syntax). Delegates to tools/preflight.cmd."""
    pf = _require_tool("tools/preflight.cmd")
    print(f"Running preflight: {pf}")
    r = _run([str(pf)])
    return r.returncode


def cmd_smoke() -> int:
    """Run the Phase 2 smoke test harness."""
    _require_tool("tools/run_phase2_smoke.py")
    print("Running smoke harness: python tools/run_phase2_smoke.py")
    r = _run([_PYTHON, "tools/run_phase2_smoke.py"])
    return r.returncode


def cmd_perf(extra_args: list[str]) -> int:
    """Run the Phase 2 performance probe. Passes extra args through."""
    _require_tool("tools/run_phase2_perf.py")
    cmd_args = [_PYTHON, "tools/run_phase2_perf.py"] + list(extra_args)
    print(f"Running perf probe: {' '.join(cmd_args)}")
    r = _run(cmd_args)
    return r.returncode


def cmd_snapshot() -> int:
    """Create a git checkpoint commit. Delegates to tools/snapshot.cmd."""
    snap = _require_tool("tools/snapshot.cmd")
    print(f"Running snapshot: {snap}")
    r = _run([str(snap)])
    return r.returncode


def cmd_rollback_last(argv: list[str]) -> int:
    """
    Roll back the last git checkpoint commit.
    Requires --yes flag for non-interactive use, otherwise prompts.
    Uses git reset --soft HEAD~1 so changes stay staged (not discarded).
    """
    if not shutil.which("git"):
        print("ERROR: git not found in PATH")
        return 1

    # Show last 3 commits for context
    r = _run(["git", "log", "--oneline", "-3"], capture=True)
    if r.returncode != 0:
        print("ERROR: git log failed. Is this a git repository?")
        return 1

    print("Last 3 commits:")
    for line in r.stdout.strip().splitlines():
        print(f"  {line}")
    print()

    # Require explicit confirmation
    if "--yes" in argv:
        confirmed = True
    else:
        try:
            ans = input("Roll back most recent commit? Changes stay staged. (y/N): ").strip()
            confirmed = ans.lower() == "y"
        except (EOFError, KeyboardInterrupt):
            confirmed = False

    if not confirmed:
        print("Rollback cancelled.")
        return 1  # explicit exit 1 so caller knows action was not taken

    r2 = _run(["git", "reset", "--soft", "HEAD~1"])
    if r2.returncode != 0:
        print("ERROR: git reset --soft HEAD~1 failed.")
        return 1

    print("Done. Changes are staged. Use 'git status' to review.")
    return 0


# -- Dispatch ---------------------------------------------------------------

_HELP = """\
Usage: python tools/dev_cli.py <subcommand> [options]

Subcommands:
  status           Print environment diagnostics (read-only)
  start            Launch via start.bat (API key load + pythonw main.py)
  start-clean      Launch via restart_clean.bat (kill old, clear cache, relaunch)
  preflight        Run lint + syntax checks (tools/preflight.cmd)
  smoke            Run Phase 2 smoke test harness
  perf [args]      Run Phase 2 performance probe (passes extra args through)
  snapshot         Create a git checkpoint commit
  rollback-last    Roll back the last git commit (--yes to skip prompt)

Examples:
  python tools/dev_cli.py status
  python tools/dev_cli.py smoke
  python tools/dev_cli.py perf --fail-section feature_policy
  python tools/dev_cli.py rollback-last --yes
"""


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(_HELP)
        return 0

    sub = sys.argv[1]
    rest = sys.argv[2:]

    if sub == "status":
        return cmd_status()
    elif sub == "start":
        return cmd_start()
    elif sub == "start-clean":
        return cmd_start_clean()
    elif sub == "preflight":
        return cmd_preflight()
    elif sub == "smoke":
        return cmd_smoke()
    elif sub == "perf":
        return cmd_perf(rest)
    elif sub == "snapshot":
        return cmd_snapshot()
    elif sub == "rollback-last":
        return cmd_rollback_last(rest)
    else:
        print(f"ERROR: unknown subcommand '{sub}'")
        print("Run 'python tools/dev_cli.py --help' for usage.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
