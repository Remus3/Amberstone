# DISTRIBUTION_LAYOUT.md
# Riot Commander -- Portable Single-Folder Distribution Layout
# Phase 4 Step 1

---

## Overview

Riot Commander is designed as a single-folder portable installation.
The project root contains all source, config, launchers, and tooling.
All runtime-generated artifacts are written within the project root.
No files are written outside the project root during normal operation.

---

## Required Folder Structure

  <project-root>/               <- portable root; can be any path
  |
  +-- main.py                   SOURCE   true application entrypoint
  +-- app.py                    SOURCE   OverlayApp class (imported by overlay.py)
  +-- overlay.py                SOURCE   tkinter overlay bootstrap
  +-- game_reader.py            SOURCE   Riot Live Client Data reader
  +-- coach_integration.py      SOURCE   SR coaching engine
  +-- start.bat                 LAUNCHER primary launch (API key + embedded pythonw (Option B) or PATH pythonw (fallback))
  +-- restart_clean.bat         LAUNCHER clean-start (kill + cache clear + relaunch)
  +-- install.bat               SETUP    one-time setup (packages, dirs, API key)
  +-- API-Key-Claude.txt        SECRET   Anthropic API key (not source-controlled)
  +-- requirements.txt          SOURCE   pip dependency list
  |
  +-- config/                   CONFIG   all configuration files
  |   +-- feature_flags.json    RUNTIME  feature policy matrix (hot-reload)
  |   +-- coach_settings.json   CONFIG   model/timeout settings
  |   +-- FEATURE_POLICY.md     DOCS     policy matrix documentation
  |   +-- CONFIG_AUTHORITY.md   DOCS     config domain ownership
  |   +-- runtime.json          RUNTIME  written by install.bat (install-time only)
  |   +-- settings.json         CONFIG   LCU/UI legacy settings
  |
  +-- core/                     SOURCE   authority model, workers, policy
  +-- coaches/                  SOURCE   per-mode coaching engines
  +-- tft/                      SOURCE   TFT state reader and coach engine
  +-- ui/                       SOURCE   tkinter overlay panels (read-only/derived)
  +-- lcu/                      SOURCE   LCU auto-accept client
  +-- tests/                    SOURCE   harness suites (not deployed)
  +-- tools/                    TOOLING  dev CLI, diagnostics, harness runners
  |
  +-- ops/                      OPS      supervisor stack
  |   +-- rc_supervisor.py      FROZEN   Phase 0 -- DO NOT MODIFY
  |   +-- rc_self_monitor.py    FROZEN   Phase 0 -- DO NOT MODIFY
  |   +-- rc_incident_log.py    FROZEN   Phase 0 -- DO NOT MODIFY
  |   +-- rc_league_watcher.ps1 FROZEN   Phase 0 -- DO NOT MODIFY
  |   +-- run_self_healing_watchdog.ps1  FROZEN  Phase 0 -- DO NOT MODIFY
  |   +-- runtime/              RUNTIME  supervisor heartbeat artifacts (writable)
  |   +-- rc_config.json        CONFIG   runtime ops stack config
  |   +-- rc_dev_runtime.py     SOURCE   DevRuntime / hot-reload bridge
  |
  +-- data/                     RUNTIME  coaching output artifacts (writable)
  +-- logs/                     RUNTIME  application logs (writable)
  +-- audit/                    TOOLING  proof bundles, perf baselines (writable)

---

## Source-Controlled vs Runtime-Generated

### Source-controlled (must be present in distribution)

  All .py files under: core/, coaches/, tft/, ui/, lcu/, tests/, tools/
  All frozen ops files: ops/rc_supervisor.py etc.
  All config files: config/*.json, config/*.md
  All launchers: start.bat, restart_clean.bat, install.bat
  requirements.txt, main.py, app.py, overlay.py

### Runtime-generated (created at runtime, not in distribution source)

  data/*.json                   coaching output artifacts
  ops/runtime/*.json            supervisor heartbeat / coaching timestamp artifacts
  logs/                         application log files
  audit/perf_baseline.*         perf probe baselines
  config/runtime.json           written by install.bat (install-time only)
  __pycache__/                  Python bytecode cache (safe to delete; recreated)

### User-supplied (not source-controlled)

  API-Key-Claude.txt            Anthropic API key

---

## Paths That Must Be Root-Relative

All launcher scripts (.bat) resolve paths via `%~dp0` (directory of the
script itself). This means the project root can be any path on any drive.

  start.bat:         %~dp0API-Key-Claude.txt, %~dp0main.py
  restart_clean.bat: %~dp0__pycache__, %~dp0*.pyc, %~dp0main.py
  install.bat:       all paths use %~dp0 -- fully portable

All Python tools (tools/dev_cli.py, tools/bootstrap_env_check.py) resolve
project root via Path(__file__).parent.parent -- portable to any location.

---

## Writable Directories Required at Runtime

  data/            coaching JSON artifacts; created by coaches at first run
  ops/runtime/     supervisor heartbeat and coaching_ts files; created at startup
  logs/            log files; created at startup
  audit/           proof bundles and perf baselines; created by tooling

  All four are created by install.bat (data/, logs/, config/) or by the
  runtime on first use. A fresh install without install.bat should create
  missing directories via mkdir in the ops stack.

---

## Frozen-File Packaging Constraints

  The following five Phase 0 files MUST NOT be modified in any future phase:
    ops/rc_supervisor.py
    ops/rc_self_monitor.py
    ops/rc_incident_log.py
    ops/rc_league_watcher.ps1
    ops/run_self_healing_watchdog.ps1

  Known packaging constraint: ops/run_self_healing_watchdog.ps1 and
  ops/rc_league_watcher.ps1 may contain hardcoded absolute paths (they are
  frozen and cannot be verified or modified). When building a portable
  distribution, these files must be audited by a human before deployment
  to a different machine or path, and any hardcoded paths updated manually
  in the distribution copy only (NOT in the source-controlled originals).

  ops/runtime/ is ACTIVELY EXCLUDED from staged bundles by build_portable.py.
  The build script skips any source file whose relative path begins ops/runtime/.
  This is a code-level enforcement, not a reliance on the source tree being clean.

---

## What Is NOT Yet Solved (Phase 4 Remaining)

  - Single-exe packaging (PyInstaller/Nuitka): not yet implemented
  Phase 5 Step 3 implemented: scripted-extract installer staging (tools/build_installer.py)
  Output: dist/installer_staging/  (setup.bat + archive + INSTALL_README.md + INSTALL_MANIFEST.json)
  Full NSIS/MSIX/Inno installer: not yet in scope
  - Auto-update mechanism: not in scope
  - Multi-machine deployment automation: not in scope

## Current Packaging Baseline

  Option B (embedded Python runtime) is the current implemented baseline.
  build_portable.py stages python-embed/ when present; package_portable.py
  archives it. launch path: start.bat -> python-embed\pythonw.exe main.py.
  Archive: dist/RiotCommander-portable-<YYYYMMDD>.zip  (~28 MB, single root folder)

## Historical Progression (superseded steps)

  Phase 4 Step 3: Option A portable staging bundle (tools/build_portable.py)
    -- superseded by Option B when python-embed/ is present
  Phase 4 Step 4: Redistributable archive (tools/package_portable.py)
    -- still in use; now packages the Option B bundle
  Phase 5 Step 1: Option B embeddable Python implemented
    (Python 3.11.9 + pip + anthropic + Pillow in python-embed/)
  Phase 5 Step 1.1-1.3: metadata, docs, and comments fully updated for Option B
