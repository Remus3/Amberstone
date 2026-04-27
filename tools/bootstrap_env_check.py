"""
tools/bootstrap_env_check.py
Riot Commander -- Environment/bootstrap diagnostic.
Phase 3 Step 3 / Phase 4 Step 1 / Phase 5 Step 1 update.

Usage (from any directory):
    python tools/bootstrap_env_check.py

Or via wrapper:
    tools\\bootstrap_env_check.cmd

Reports:
  - Resolved project root
  - Python executable and version
  - Git availability
  - Expected launcher scripts (start.bat, restart_clean.bat)
  - Required config files (API-Key-Claude.txt, feature_flags.json)
  - Embedded Python Runtime (Option B): python-embed/python.exe + pythonw.exe
  - GUI launcher: embedded pythonw.exe (Option B) or PATH pythonw.exe (Option A fallback)
  - Install / Setup Readiness: embedded packages (Option B) or PATH python+pip (Option A)
  - Frozen Ops Stack advisory: PATH python needed by frozen ops/.ps1 scripts
  - Packaging readiness (root-relative launchers, frozen files, runtime layout)
  - Whether runtime/audit/temp directories are writable
  - Whether CWD is the project root

Exit codes:
  0  All required items present and writable (warnings alone do not fail)
  1  One or more MISSING or ERROR items (non-writable dirs, absent files)
"""
import sys
import os
import shutil
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

_PASS  = "  PASS  "
_WARN  = "  WARN  "
_MISS  = "  MISS  "
_ERROR = "  ERROR "
_INFO  = "  INFO  "

_issues: list = []

# ── Staged-bundle detection ───────────────────────────────────────────────────
# When running from inside a staged distribution bundle (dist/portable_staging/
# or equivalent), dev-only tooling that was intentionally not deployed should
# not cause readiness failures.  We detect a staged bundle by the presence of
# BUILD_MANIFEST.json at the project root.

def _is_staged_bundle() -> bool:
    """Return True if we are running from inside a staged portable bundle."""
    return (_PROJECT_ROOT / "BUILD_MANIFEST.json").exists()


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_PASS}{label}{suffix}")


def _warn(label: str, detail: str = "") -> None:
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_WARN}{label}{suffix}")
    _issues.append(("WARN", label))


def _miss(label: str, detail: str = "") -> None:
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_MISS}{label}{suffix}")
    _issues.append(("MISS", label))


def _err(label: str, detail: str = "") -> None:
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_ERROR}{label}{suffix}")
    _issues.append(("ERROR", label))


def _omitted(label: str, detail: str = "") -> None:
    """Report an intentionally omitted item (staged bundle only). Never fails readiness."""
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_INFO}{label}{suffix}")


def _info(label: str, detail: str = "") -> None:
    """Print an informational line. Never fails readiness."""
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_INFO}{label}{suffix}")


def _check_writable(path: Path, label: str) -> None:
    if not path.exists():
        _miss(label, f"directory does not exist: {path}")
        return
    try:
        tmp = path / ".bootstrap_write_test"
        tmp.write_text("x", encoding="utf-8")
        tmp.unlink()
        _ok(label, f"writable ({path})")
    except Exception as exc:
        _err(label, f"not writable: {exc}")


def main() -> int:
    print("=" * 64)
    print("Riot Commander -- Bootstrap Environment Check")
    print("=" * 64)

    # ── Project root ──────────────────────────────────────────────────────
    print("\n[Project Root]")
    _ok("project root", str(_PROJECT_ROOT))
    cwd = Path.cwd()
    if cwd.resolve() == _PROJECT_ROOT.resolve():
        _ok("cwd matches project root", str(cwd))
    else:
        _warn("cwd differs from project root",
              f"cwd={cwd}  project_root={_PROJECT_ROOT}")

    # ── Python ────────────────────────────────────────────────────────────
    print("\n[Python]")
    py = sys.executable
    if py and Path(py).exists():
        _ok("python executable", py)
    else:
        _err("python executable not found", str(py))
    _ok("python version", sys.version.split()[0])

    # Warn if running Python < 3.9
    vi = sys.version_info
    if vi < (3, 9):
        _err("python version too old",
             f"{vi.major}.{vi.minor} < 3.9 (minimum required)")
    else:
        _ok("python version >= 3.9")

    # ── Git ───────────────────────────────────────────────────────────────
    print("\n[Git]")
    git = shutil.which("git")
    if git:
        _ok("git available", git)
    else:
        _warn("git not found in PATH",
              "snapshot and rollback-last commands will not work")

    # ── Launcher scripts ──────────────────────────────────────────────────
    print("\n[Launcher Scripts]")
    launchers = [
        ("start.bat",        "primary launcher (API key + pythonw main.py)"),
        ("restart_clean.bat","clean-start launcher (kill + cache clear + launch)"),
        ("main.py",          "true application entrypoint"),
    ]
    for name, desc in launchers:
        p = _PROJECT_ROOT / name
        if p.exists():
            _ok(name, desc)
        else:
            _miss(name, desc)

    # ── Dev tools ─────────────────────────────────────────────────────────
    print("\n[Dev Tools]")
    # In a staged bundle, dev-only harness tools are intentionally omitted.
    # Their absence must NOT count as a launch/install readiness failure.
    staged = _is_staged_bundle()
    if staged:
        print("          (staged bundle mode: dev-only tools are intentionally omitted)")
    tools = [
        ("tools/dev_cli.py",              "operator CLI",           False),
        ("tools/run_phase2_smoke.py",     "smoke harness",          True),
        ("tools/run_phase2_perf.py",      "perf probe",             True),
        ("tools/preflight.cmd",           "lint + syntax check",    True),
        ("tools/snapshot.cmd",            "git checkpoint",         True),
        ("tools/rollback_last.cmd",       "git rollback",           True),
        ("tools/bootstrap_env_check.py",  "this diagnostic script", False),
    ]
    # dev_only=True  -> absence is INFO in staged mode, MISS in dev-root mode
    # dev_only=False -> absence is always MISS (required for operator use)
    for name, desc, dev_only in tools:
        p = _PROJECT_ROOT / name
        if p.exists():
            _ok(name, desc)
        elif staged and dev_only:
            _omitted(f"{name}  [dev-only, not staged]", desc)
        else:
            _miss(name, desc)

    # ── Required config files ─────────────────────────────────────────────
    print("\n[Config Files]")
    configs = [
        ("API-Key-Claude.txt",          "Anthropic API key (required for coaching)"),
        ("config/feature_flags.json",   "runtime feature policy matrix"),
        ("config/FEATURE_POLICY.md",    "feature policy documentation"),
        ("config/coach_settings.json",  "AI coaching model/timeout settings"),
        ("ops/rc_config.json",          "runtime ops stack config"),
    ]
    for name, desc in configs:
        p = _PROJECT_ROOT / name
        if p.exists():
            _ok(name, desc)
        else:
            label = "REQUIRED" if "API-Key" in name else "config"
            _miss(f"{name}  [{label}]", desc)

    # ── Embedded Python runtime (Option B) ──────────────────────────────────
    print("\n[Embedded Python Runtime (Option B)]")
    embed_py  = _PROJECT_ROOT / "python-embed" / "python.exe"
    embed_pyw = _PROJECT_ROOT / "python-embed" / "pythonw.exe"
    embed_present = embed_py.exists() and embed_pyw.exists()
    if embed_present:
        _ok("python-embed/python.exe present",  str(embed_py))
        _ok("python-embed/pythonw.exe present", str(embed_pyw))
        try:
            import subprocess as _sp_emb
            r_emb = _sp_emb.run(
                [str(embed_py), "-c", "import anthropic, PIL"],
                capture_output=True, text=True, timeout=10,
            )
            if r_emb.returncode == 0:
                _ok("embedded runtime: anthropic + Pillow importable")
            else:
                _warn("embedded runtime: packages not importable",
                      "run install.bat to install packages into embedded runtime")
        except Exception as exc:
            _warn("embedded runtime package check failed", str(exc))
    else:
        _info("python-embed/ not found -- Option A (PATH Python) in use")

    # ── pythonw.exe availability (required for GUI launch) ──────────────────
    print("\n[GUI Launcher (pythonw.exe)]")
    if embed_present:
        # Option B: use embedded pythonw.exe for launch
        _ok("embedded pythonw.exe available (Option B)", str(embed_pyw))
        _info("start.bat will use python-embed/pythonw.exe (Option B path)")
    else:
        # Option A: require PATH-based pythonw.exe
        pythonw = shutil.which("pythonw") or shutil.which("pythonw.exe")
        if pythonw:
            _ok("pythonw.exe available (Option A -- PATH)", pythonw)
        else:
            _err("pythonw.exe NOT found in PATH and no embedded runtime",
                 "start.bat will fail to launch the app")

    # Validate API key prefix if file exists
    api_file = _PROJECT_ROOT / "API-Key-Claude.txt"
    if api_file.exists():
        try:
            key = api_file.read_text(encoding="utf-8").strip()
            if key.startswith("sk-ant-"):
                _ok("API key format valid  (sk-ant-... prefix present)")
            else:
                _err("API key format invalid",
                     "does not start with sk-ant-; app will fail to start")
        except Exception as exc:
            _err("API key file unreadable", str(exc))

    # ── Install / setup readiness ─────────────────────────────────────────────
    print("\n[Install / Setup Readiness]")
    if embed_present:
        _ok("embedded runtime present -- packages pre-installed",
            "install.bat only needs to verify packages and set up API key")
    else:
        python_on_path = shutil.which("python")
        if python_on_path:
            _ok("python on PATH  (Option A -- required for install.bat)", python_on_path)
            try:
                import subprocess as _sp
                r = _sp.run(
                    [python_on_path, "-m", "pip", "--version"],
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0:
                    pip_ver = r.stdout.strip().split()[1] if r.stdout.strip() else "unknown"
                    _ok("python -m pip usable", f"pip {pip_ver}")
                else:
                    _warn("python -m pip not usable",
                          "install.bat pip install step may fail")
            except Exception as exc:
                _warn("python -m pip check failed", str(exc))
        else:
            _err("python NOT found on PATH",
                 "Option A: install.bat calls python directly; will fail without it")

    # ── Frozen ops stack -- PATH python advisory ──────────────────────────────
    # ops/rc_league_watcher.ps1 and ops/run_self_healing_watchdog.ps1 call
    # python by bare name (PATH). These are Phase 0 FROZEN -- cannot be changed.
    # Under Option B this is advisory only; normal launch does not need PATH python.
    print("\n[Frozen Ops Stack (PATH Python Advisory)]")
    python_on_path = shutil.which("python")
    if python_on_path:
        if embed_present:
            _ok("python on PATH  (advisory -- frozen ops/.ps1 need this)", python_on_path)
        else:
            _ok("python on PATH", python_on_path)
    else:
        if embed_present:
            _warn("python NOT on PATH",
                  "advisory: frozen ops/.ps1 scripts call python by name; ops supervisor may fail")
        else:
            _err("python NOT found on PATH",
                 "required: install.bat and frozen ops/.ps1 scripts depend on PATH python")

    # ── Packaging readiness ────────────────────────────────────────────────
    print("\n[Packaging Readiness]")
    # Launchers that must be root-relative for portable distribution
    portable_launchers = [
        ("start.bat",         "uses %~dp0 -- root-relative"),
        ("restart_clean.bat", "uses %~dp0 -- root-relative"),
        ("install.bat",       "uses %~dp0 -- root-relative"),
    ]
    for name, note in portable_launchers:
        p = _PROJECT_ROOT / name
        if p.exists():
            _ok(f"{name} present", note)
        else:
            _miss(f"{name} missing", "required for portable distribution")

    # Frozen files that cannot be changed: document as packaging constraints
    frozen_constraints = [
        "ops/rc_supervisor.py",
        "ops/rc_self_monitor.py",
        "ops/rc_incident_log.py",
        "ops/rc_league_watcher.ps1",
        "ops/run_self_healing_watchdog.ps1",
    ]
    frozen_present = all((_PROJECT_ROOT / f).exists() for f in frozen_constraints)
    if frozen_present:
        _ok("frozen Phase 0 files present",
            "packaging constraint: these files must NOT be modified")
    else:
        _warn("one or more frozen Phase 0 files missing",
              "unexpected -- check project integrity")

    # Runtime layout: essential writable dirs must exist or be creatable
    runtime_layout = [
        ("data",        "coaching artifacts (runtime-generated)"),
        ("ops/runtime", "supervisor heartbeat artifacts (runtime-generated)"),
        ("logs",        "application logs (runtime-generated)"),
        ("audit",       "proof bundles and perf baselines"),
    ]
    for rel, note in runtime_layout:
        p = _PROJECT_ROOT / rel
        if p.exists():
            _ok(f"{rel}/ exists", note)
        else:
            _warn(f"{rel}/ missing", f"{note} -- will be created at first run")

    # ── Writable directories ──────────────────────────────────────────────
    print("\n[Writable Directories]")
    writable_dirs = [
        (_PROJECT_ROOT / "audit",       "audit/ (proof bundles, baseline outputs)"),
        (_PROJECT_ROOT / "ops" / "runtime", "ops/runtime/ (supervisor artifacts)"),
        (_PROJECT_ROOT / "data",        "data/ (coaching artifacts)"),
    ]
    for path, label in writable_dirs:
        _check_writable(path, label)

    # Temp dir sanity check
    try:
        with tempfile.TemporaryDirectory() as td:
            _ok("system temp dir", td)
    except Exception as exc:
        _err("system temp dir not usable", str(exc))

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    if not _issues:
        print("Bootstrap check: ALL PASS")
        return 0

    errors   = [l for (k, l) in _issues if k in ("ERROR", "MISS")]
    warnings = [l for (k, l) in _issues if k == "WARN"]

    if warnings and not errors:
        print(f"Bootstrap check: {len(warnings)} WARNING(s) -- app may still run")
        for w in warnings:
            print(f"  WARN: {w}")
        return 0  # warnings alone do not fail exit code

    print(f"Bootstrap check: {len(errors)} ISSUE(s) found")
    for e in errors:
        print(f"  ISSUE: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
