# DEV_WORKFLOW.md (updated -- Step 5.1)
# Riot Commander -- Local Developer/Operator Workflow

---

## One-Command Entry Point

All routine developer and operator actions go through:

    python tools/dev_cli.py <subcommand>

Or via the Windows batch wrapper (from any directory):

    tools\dev_cli.cmd <subcommand>

For a quick environment pre-flight check (before anything else):

    python tools/bootstrap_env_check.py
    tools\bootstrap_env_check.cmd

---

## Subcommands

### `status` (read-only diagnostic)

    python tools/dev_cli.py status

Prints:
- Project root path and Python executable/version
- Git availability and last commits
- Whether key scripts/tools exist
- **[Launch Targets]** -- whether start.bat and restart_clean.bat exist (the real launchers)
- Whether key config files exist (feature_flags.json, API-Key-Claude.txt)
- Whether audit/ is writable

**Safe: read-only, no side effects.**

---

### `start`

    python tools/dev_cli.py start

Delegates to **start.bat** -- the project-established launch path.

start.bat:
  1. Reads ANTHROPIC_API_KEY from API-Key-Claude.txt
  2. Validates key (prefix sk-ant-)
  3. Launches: `python-embed\pythonw.exe main.py` (Option B -- embedded runtime)
              OR `pythonw.exe main.py` (Option A fallback -- PATH pythonw)

main.py is the true project entrypoint (sets up DevRuntime, MetricsCache,
overlay, LCU auto-accept).

---

### `start-clean`

    python tools/dev_cli.py start-clean

Delegates to **restart_clean.bat** -- the project-established clean-start path.

restart_clean.bat:
  1. Kills existing pythonw.exe processes
  2. Clears `__pycache__/` and `*.pyc` files
  3. Launches: `python-embed\pythonw.exe main.py` (Option B -- embedded runtime)
              OR `pythonw.exe main.py` (Option A fallback -- PATH pythonw)

dev_cli does NOT manually wipe ops/runtime/ or any supervisor-owned paths.

---

### `preflight`

    python tools/dev_cli.py preflight

Runs `tools/preflight.cmd` (ruff lint + Python syntax check).

---

### `smoke`

    python tools/dev_cli.py smoke

Runs the Phase 2 deterministic smoke test harness. 68 tests. Exit 0 = all pass.

---

### `perf [args]`

    python tools/dev_cli.py perf
    python tools/dev_cli.py perf --fail-section feature_policy

Runs the Phase 2 performance probe. Extra arguments passed through unchanged.

---

### `snapshot`

    python tools/dev_cli.py snapshot

Creates a git checkpoint commit via `tools/snapshot.cmd`.

---

### `rollback-last`

    python tools/dev_cli.py rollback-last           # interactive prompt
    python tools/dev_cli.py rollback-last --yes      # non-interactive

**Destructive.** Runs `git reset --soft HEAD~1`. Changes stay staged.
Requires `--yes` or interactive confirmation. Cancellation returns exit 1.

---

## Return Code Reference

| code | meaning |
|---|---|
| 0 | Success or clean no-op |
| 1 | Failure, error, or cancellation |
| 2 | Unknown subcommand |

---

## Wrapper Script Consistency

All wrapper .cmd files use the same pattern:

    cd /d "%~dp0\.."         <- project root from script location
    where py >nul 2>&1       <- test for Windows Py Launcher
    if %ERRORLEVEL%==0 (     <- py.exe found: use it
        "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\...py
    ) else (
        python tools\...py   <- fallback: python on PATH
    )
    exit /b %ERRORLEVEL%     <- propagate exit code

Scripts:
  `tools\dev_cli.cmd`
  `tools\run_phase2_smoke.cmd`
  `tools\run_phase2_perf.cmd`
  `tools\bootstrap_env_check.cmd`

No hardcoded absolute Python paths. Resolves `py.exe` (Windows Py Launcher)
first, then falls back to `python` on PATH.

---

## What Is Out of Scope

- Full NSIS/MSIX/Inno installer (not yet in scope)
- Supervisor/watchdog management (frozen Phase 0 ops scripts)
- Dependency installation
- Any GameEnvelope, worker, or UI changes

---

## Distribution and Packaging References

For Phase 4 packaging readiness work:

  tools/DISTRIBUTION_LAYOUT.md       -- portable folder layout and runtime paths
  tools/PYTHON_BUNDLING_STRATEGY.md  -- Python bundling options and recommendation
  tools/LAUNCH_STRATEGY.md           -- authoritative launch chain and env assumptions

Packaging readiness is now also reported by:

  python tools/bootstrap_env_check.py  -- includes [Packaging Readiness] section

## Build and Package Commands (Phase 4 / Phase 5)

  Stage portable bundle:
    python tools/build_portable.py
    tools\build_portable.cmd

  Produce redistributable archive:
    python tools/package_portable.py
    python tools/package_portable.py --rebuild-staging
    tools\package_portable.cmd

  Output: dist/RiotCommander-portable-<YYYYMMDD>.zip
  ZIP root: RiotCommander-portable/  (single top-level folder)

  Produce installer staging directory (Phase 5 Step 3):
    python tools/build_installer.py
    tools\build_installer.cmd

  Output: dist/installer_staging/
    setup.bat                        -- guided extract + first-time setup
    RiotCommander-portable-*.zip     -- validated portable archive
    INSTALL_README.md                -- operator install guide
    INSTALL_MANIFEST.json            -- machine-readable metadata

  Run packaged artifact smoke harness (Phase 5 Step 2):
    python tools/run_packaged_smoke.py
    python tools/run_packaged_smoke.py --archive dist/installer_staging/*.zip

## Option B Embedded Runtime (Phase 5 Step 1 / 1.1)

  python-embed/ at project root enables Option B (embeddable Python 3.11.9).
  build_portable.py detects and stages python-embed/ automatically.
  Staged/archived bundles are self-contained -- no PATH Python needed for launch.
  PATH python still required by frozen ops/.ps1 supervisor scripts.

  All staged/package metadata is strategy-sensitive (Phase 5 Step 1.1):
    PREREQUISITES.md: Option B version says embedded runtime included, no Python install needed.
    BUILD_MANIFEST.json: prerequisites/launch_chain/install_chain reflect Option B.
    PACKAGE_MANIFEST.json: first_run_steps/not_included reflect Option B.

  bootstrap_env_check.py sections under Option B:
    [Embedded Python Runtime (Option B)]: primary launch readiness
    [Install / Setup Readiness]: embedded packages verified; no PATH python check
    [Frozen Ops Stack (PATH Python Advisory)]: PATH python advisory for ops/.ps1 only

---

## Relationship to the Frozen Control Plane

Phase 0 frozen files must never be modified:
  `ops/rc_supervisor.py`, `ops/rc_self_monitor.py`, `ops/rc_incident_log.py`,
  `ops/rc_league_watcher.ps1`, `ops/run_self_healing_watchdog.ps1`

`dev_cli` does NOT invoke these files. `start` and `start-clean` delegate
to `start.bat` / `restart_clean.bat` which launch `main.py` independently
of the supervisor watchdog.

---

## Read-Only vs State-Changing Commands

| command | type | what changes |
|---|---|---|
| status | read-only | nothing |
| smoke | read-only | nothing (temp dirs only) |
| perf | read-only | audit/perf_baseline.* |
| preflight | read-only | nothing |
| start | launching | spawns pythonw main.py via start.bat |
| start-clean | launching | kills pythonw, clears __pycache__, relaunches |
| snapshot | state-changing | creates a git commit |
| rollback-last | destructive | removes the last git commit (soft) |
