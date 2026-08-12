# LAUNCH_STRATEGY.md
# Amberstone -- Launch Strategy and Environment Documentation
# Phase 3 Step 3

---

## True Runtime Entrypoint Chain

  Current packaged baseline: Option B (embedded Python runtime)

    start.bat
      |
      +-> reads API-Key-Claude.txt  (validates sk-ant- prefix)
      |
      +-> python-embed\pythonw.exe main.py   (primary: embedded runtime)
            OR
      +-> PATH pythonw.exe main.py           (fallback: Option A / no python-embed/)
            |
            +-> core/log_setup.py         (logging init)
            +-> core/config_validator.py  (config validation)
            +-> core/resource_manager.py  (memory watchdog)
            +-> ops/rc_dev_runtime.py     (heartbeat + hot-reload + file bridge)
            +-> core/metrics_cache.py     (background OPS metrics)
            +-> coach_integration.py      (coaching engine setup)
            +-> overlay.py -> OverlayApp  (tkinter overlay launch)
            +-> lcu/lcu_client.py         (LCU auto-accept, if present)

  Note: app.py is the overlay class definition file (OverlayApp).
  It is imported by overlay.py. It is NOT the entrypoint.

---

## Authoritative vs Legacy/Manual/Emergency Scripts

### Authoritative (use these)

  start.bat                 Primary launch. API key validation + embedded pythonw (Option B) or PATH pythonw (Option A fallback).
  restart_clean.bat         Clean-start. Kills pythonw + clears __pycache__ + relaunches.
  tools/dev_cli.py          Operator CLI. Single command surface for all routine ops.
  tools/dev_cli.cmd         Windows wrapper for dev_cli.py (py launcher + fallback).
  tools/bootstrap_env_check.py  Pre-flight environment diagnostic.

### Informational / Background (do not invoke directly for normal ops)

  ops/run_self_healing_watchdog.ps1  Supervisor watchdog (FROZEN Phase 0).
  ops/rc_league_watcher.ps1          League client watcher (FROZEN Phase 0).
  run_watchdog.bat                   Starts the watchdog (separate from app launch).

### Legacy / Fallback (keep but prefer dev_cli)

  restart.bat               Manual kill + relaunch (legacy; prefer restart_clean.bat).
  kill.bat                  Force-kills pythonw.exe processes.
  start_debug.bat           Debug-mode launch variant.
  install.bat               One-time install/setup only.

### Emergency Only

  tools/rollback_last.cmd   Git rollback. Requires explicit confirmation.
  tools/rollback_last.cmd --yes  Non-interactive rollback. Use with care.

---

## Dev/Operator Command Surface (via dev_cli)

  python tools/dev_cli.py status        Environment diagnostics (read-only)
  python tools/dev_cli.py start         Launch app (via start.bat)
  python tools/dev_cli.py start-clean   Clean start (via restart_clean.bat)
  python tools/dev_cli.py preflight     Lint + syntax check
  python tools/dev_cli.py smoke         Phase 2 smoke harness (68 tests)
  python tools/dev_cli.py perf          Phase 2 performance probe
  python tools/dev_cli.py snapshot      Git checkpoint commit
  python tools/dev_cli.py rollback-last Undo last commit (confirm required)

  Also available:
  python tools/bootstrap_env_check.py   Pre-flight environment check

---

## Environment Assumptions

### Python

  Required: Python 3.9+
  Recommended: Python 3.11+ for best performance

  Resolution order (dev_cli.cmd and smoke/perf wrappers):
    1. py.exe  -- Windows Py Launcher (auto-selects version by .python-version or
                  latest installed; preferred for multi-Python machines)
    2. python  -- standard name on PATH (fallback)

  When invoked as `python tools/dev_cli.py`, sys.executable is used directly.
  This is always the most reliable path.

  No hardcoded absolute Python paths remain in any wrapper script.

### Git

  Optional but required for: snapshot, rollback-last
  Detection: shutil.which("git") -- uses PATH only
  If absent: status shows MISSING; smoke/perf/start/preflight unaffected

### Required Config Files

  File                        Purpose                     Required for
  API-Key-Claude.txt          Anthropic API key           App launch (coaching)
  config/feature_flags.json   Feature policy matrix       Policy gating
  config/coach_settings.json  Model/timeout settings      Coaching
  ops/rc_config.json          Runtime ops stack config    DevRuntime/supervisor

### Required Writable Directories

  audit/                      Proof bundles, perf baselines
  ops/runtime/                Supervisor heartbeat artifacts
  data/                       Coaching output artifacts

### Working Directory

  All scripts resolve project root from their own location (%~dp0 or Path(__file__)).
  Preferred: run from the project root (C:\Riot Commander\) for consistency.
  The dev_cli.py status command reports whether CWD matches project root.

---

## What Is Intentionally NOT Solved Yet

  - Full MSI/MSIX/NSIS/Inno installer build (not yet in scope)
  - Single-exe distribution (Option C -- not recommended; frozen ops stack incompatible)
  - Auto-dependency installation for new machines (beyond install.bat)
  - Python version pinning (.python-version file)
  - Virtual environment (venv) management
  - Multi-machine / CI deployment

  Implemented in Phase 5:
  - Bundled/embeddable Python (Option B): IMPLEMENTED -- python-embed/ in staged/archive/installer
  - Scripted-extract installer staging: IMPLEMENTED -- tools/build_installer.py -> dist/installer_staging/ deployment

---

## Distribution Layout Reference

  See tools/DISTRIBUTION_LAYOUT.md for the complete portable folder layout,
  runtime-generated vs source-controlled file classification, and frozen-file
  packaging constraints.

## Python Bundling Strategy Reference

  See tools/PYTHON_BUNDLING_STRATEGY.md for options analysis and the
  current implemented Option B baseline (embedded Python 3.11 runtime).

## Build Command (Phase 4 Step 3)

  Produces a staged portable bundle at dist/portable_staging/:

    python tools/build_portable.py
    tools\build_portable.cmd

  The staged output includes all source, launchers, config, and operator tooling.
  Excludes: secrets, .git, __pycache__, audit proof bundles, transient logs.
  Includes: PREREQUISITES.md and BUILD_MANIFEST.json.

## Package Command (Phase 4 Step 4)

  Produces a redistributable ZIP archive from the staged bundle:

    python tools/package_portable.py
    python tools/package_portable.py --rebuild-staging
    tools\package_portable.cmd

  Output: dist/Amberstone-portable-<YYYYMMDD>.zip
  ZIP root: Amberstone-portable/  (single top-level folder)
  Includes: BUILD_MANIFEST.json + PACKAGE_MANIFEST.json inside the archive.

## Installer Command (Phase 5 Step 3)

  Produces a guided-setup installer staging directory:

    python tools/build_installer.py
    tools\build_installer.cmd

  Output: dist/installer_staging/
    setup.bat                         -- guided extract + first-run setup
    Amberstone-portable-<date>.zip -- validated portable archive
    INSTALL_README.md                  -- operator install guide
    INSTALL_MANIFEST.json              -- machine-readable installer metadata

  Installer type: scripted-extract (not NSIS/MSIX/Inno yet).
  Input: latest dist/Amberstone-portable-*.zip (validated Option B archive).

  python-embed/ is staged by build_portable.py when present at project root.
  Authoritative launch chain (Option B):
    start.bat -> %~dp0python-embed\pythonw.exe main.py
  Fallback (Option A -- python-embed/ absent):
    start.bat -> PATH pythonw.exe main.py

  BUILD_MANIFEST.json and PACKAGE_MANIFEST.json are strategy-sensitive:
    prerequisites, launch_chain, install_chain reflect Option B when staged with embed dir.
  PREREQUISITES.md is strategy-sensitive: Option B emits embedded-runtime content.

  Frozen .ps1 constraint: ops supervisor scripts call python by PATH name.
  PATH python is still required for the ops/watchdog stack (Phase 0 frozen).
  bootstrap_env_check.py reports this under [Frozen Ops Stack (PATH Python Advisory)].
  Normal app launch does NOT require PATH python under Option B.
