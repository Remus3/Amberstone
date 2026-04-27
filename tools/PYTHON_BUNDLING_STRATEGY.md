# PYTHON_BUNDLING_STRATEGY.md
# Riot Commander -- Python Bundling Strategy
# Phase 4 Step 1

---

## Context

Riot Commander's authoritative launch path is:

  start.bat -> python-embed\pythonw.exe main.py  (Option B -- current baseline)
  OR: start.bat -> PATH pythonw.exe main.py  (Option A fallback)

`pythonw.exe` is a Windows-specific executable that runs Python without a
console window. This is a hard GUI requirement for the tkinter overlay.

The Python environment also serves:
  - dev/operator tooling (dev_cli.py, bootstrap_env_check.py, smoke/perf harness)
  - frozen Phase 0 ops stack (rc_supervisor.py, rc_league_watcher.ps1)
  - coaching engines and coach integration

---

## Options Evaluated

### Option A: Prerequisite Python Install (legacy / Option A fallback)

  The user installs Python 3.9+ separately. install.bat checks for python
  on PATH and installs packages via pip.

  Pros:
    - Simplest. No bundling work required.
    - pythonw.exe is guaranteed to exist alongside python.exe.
    - pip install of anthropic SDK is straightforward.
    - dev_cli and all tooling work identically in dev and deployed contexts.
    - Harness, smoke, perf, preflight all run without modification.

  Cons:
    - User must install Python manually before running install.bat.
    - Python version is not pinned; future Python releases could break things.
    - PATH dependency: python.exe and pythonw.exe must be on PATH.

  Current constraint: This is what Phase 3 Step 3 made portable. All
  .cmd wrappers now use `py` (Windows Py Launcher) with fallback to `python`.

### Option B: Bundled/Embeddable Python

  Ship a copy of Python's embeddable distribution (python-X.Y.Z-embed-amd64.zip)
  inside the project folder (e.g., python-embed/).

  Pros:
    - Python version is fully pinned and self-contained.
    - No dependency on user's PATH for python.exe.
    - The project folder is fully self-contained.

  Cons:
    - The embeddable distribution does NOT include pip by default; must
      manually add pip via get-pip.py and install packages.
    - pythonw.exe IS included in the embeddable distribution, satisfying
      the GUI launch requirement.
    - .cmd wrappers and start.bat must be updated to use the embedded path.
    - The embedded Python path would be hardcoded in launcher scripts;
      this reduces portability unless relative paths are used.
    - Frozen Phase 0 .ps1 files (rc_league_watcher.ps1) may assume a
      system Python and would need documentation updates.
    - Adds ~30MB+ to the distribution footprint.
    - dev_cli tooling and harness runners must explicitly reference the
      embedded Python, complicating the development workflow.

  Constraint: Embeddable Python cannot be modified (frozen files concern
  applies here too -- the ops PowerShell scripts call Python by name;
  those cannot be changed).

### Option C: Standalone Executable (PyInstaller / Nuitka)

  Build a single .exe (or single-folder) distribution using PyInstaller
  or Nuitka. The .exe bundles Python and all dependencies.

  Pros:
    - Zero Python prerequisite for end users.
    - Single-file or single-folder distribution is the simplest user experience.
    - Version is fully locked at build time.

  Cons:
    - `pythonw.exe` cannot be replicated by a PyInstaller .exe -- the .exe
      itself IS the process; there is no separate pythonw.exe to call from
      start.bat. The start.bat -> pythonw.exe chain would need to be replaced
      by start.bat -> riot_commander.exe or similar.
    - The frozen ops stack (rc_supervisor.py etc.) imports Python directly;
      these cannot be bundled into a single .exe without modifying frozen files.
    - dev_cli, smoke harness, and perf probe all require unbundled Python;
      a single-exe distribution does not serve the developer/operator workflow.
    - PyInstaller builds are non-trivial to maintain with tkinter + Anthropic SDK.
    - Nuitka is faster but requires a C compiler toolchain.
    - Rebuilds are required on every dependency update.

---

## Current Implemented Strategy and Rationale

**Option B (embeddable Python) is the current implemented packaging baseline.**
**Option A (prerequisite Python) is the legacy / Option A fallback when python-embed/ is absent.**

### Rationale

Riot Commander's primary deployment context is a single Windows machine
used by the developer/operator. The complexity cost of Option C (full .exe
build) is not justified given:

  1. The frozen ops stack calls Python by name -- changing this would
     require modifying frozen Phase 0 files, which is permanently prohibited.
  2. The developer workflow (dev_cli, harness, smoke, perf) requires
     a full Python environment to remain usable.
  3. pythonw.exe is available in both the system install (Option A) and
     the embeddable distribution (Option B), satisfying the GUI requirement.

Option B (embeddable Python) provides:
  - A pinned, self-contained Python version alongside the project
  - pythonw.exe for GUI launch
  - pip-installable anthropic SDK (once get-pip.py is applied)
  - No user prerequisite beyond unzipping the project folder

### Option B Implementation -- Completed Steps (Phase 5 Step 1)

  All eight required steps were completed in Phase 5 Step 1. For reference:

  1. Python version pinned: 3.11.9 (CPython embeddable amd64)
  2. python-embed/ added to project root (not source-controlled; built at staging time)
  3. start.bat and restart_clean.bat updated to use %~dp0python-embed\pythonw.exe
     with fallback to PATH pythonw.exe (Option A compatibility)
  4. .cmd wrappers retain py/python fallback; dev workflow unchanged
  5. pip bootstrapped via get-pip.py; anthropic + Pillow installed in embed Lib/site-packages/
  6. Embedded Python path documented as packaging constraint in DISTRIBUTION_LAYOUT.md
  7. Frozen .ps1 files verified: call python by bare PATH name (not absolute path).
     Cannot be fixed; documented as advisory WARN in bootstrap_env_check.py.
  8. bootstrap_env_check.py updated with [Embedded Python Runtime (Option B)] section.

### Frozen Constraints / Invariants

  - Frozen Phase 0 files (even if they call `python` by name)
  - GameEnvelope authority in app.py
  - Worker ownership contracts
  - Feature policy gating logic

---

## Historical Progression and Current Baseline

  Historical steps (superseded):
    Phase 4 Step 1: Option A was the target (prerequisite Python on PATH)
    Phase 4 Step 3: Option A portable staging bundle built (tools/build_portable.py)

  Current implemented baseline:
    Phase 5 Step 1:   Option B embeddable Python implemented
                      (python-embed/ + pip + packages + updated launchers)
    Phase 5 Step 1.1: staged/package metadata and diagnostics Option B truthful
    Phase 5 Step 1.2: all operator docs updated to reflect Option B as current baseline
    Phase 5 Step 1.3: remaining stale comments corrected
    Phase 5 Step 3:   scripted-extract installer staging (tools/build_installer.py)

  Current packaged baseline: Option B -- Python 3.11.9 embedded, packages pre-installed
  Option A: legacy/fallback when python-embed/ is absent
  Option C (standalone .exe): not recommended; frozen ops stack incompatible

## Option B Implementation Details (Phase 5 Step 1)

  Python version pinned: 3.11.9 (CPython embeddable amd64)
  Location: python-embed/ at project root (not source-controlled; built at staging time)
  Packages installed: anthropic 0.94.1, Pillow 12.2.0, and all deps
  launch path: start.bat -> %~dp0python-embed\pythonw.exe main.py
  Fallback: PATH pythonw.exe (Option A compatibility when python-embed/ absent)

  Frozen .ps1 constraint: ops/rc_league_watcher.ps1 and
  ops/run_self_healing_watchdog.ps1 call python by bare name (PATH).
  Cannot be fixed (Phase 0 frozen). The ops supervisor stack still requires
  PATH python. Diagnostics report this as advisory WARN in Option B mode.
