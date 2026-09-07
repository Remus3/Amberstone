# launch_queue_loop.ps1 - detached launcher for ops/loop/queue_loop.py, the driver
# that re-fires the one-row `queue` lane worker cycle after cycle. Modelled on
# run_lane.ps1, which does the same job one level down (it runs ONE worker; this
# runs the thing that runs many).
#
# $PSScriptRoot in a param default is not a guess - MEASURED 2026-09-05 on this
# box: a probe script with `param([string]$Log = "$PSScriptRoot\reports\x.log")`
# resolved it correctly, because PowerShell sets $PSScriptRoot for a script file
# before it binds parameters. That keeps the default relative to wherever this
# repo is checked out instead of pinning C:\Riot Commander into a param block.
param(
  [int]$Cycles = 12,
  [int]$Settle = 45,
  [string]$Log  = "$PSScriptRoot\reports\queue_loop.log",
  # See the sentinel pre-check below. -Force starts the driver over a stop file
  # that is already present; it does NOT override the driver's own check.
  [switch]$Force
)
$ErrorActionPreference = "Stop"   # unlike run_lane.ps1: nothing here is long-lived
                                  # enough to ride out a fault, and a launcher that
                                  # half-worked must fail loudly at the prompt.

# Ride the Max subscription login, never the API key - the SAME measured failure
# run_lane.ps1 documents. On 2026-08-02 the `gated` lane spawned correctly and
# died 3s later with "Credit balance is too low", because ANTHROPIC_API_KEY is set
# at MACHINE scope on Legion and the CLI prefers it over the claude.ai login.
# Clearing it HERE matters more than clearing it there: this process is the
# ancestor of every worker the driver spawns, and a Windows child inherits the
# parent's environment block, so one clear at the root covers the whole run. It
# is scoped to this process only; the machine-wide variable is left alone.
$env:ANTHROPIC_API_KEY = $null

# pythonw.exe, not python.exe - CLAUDE.md: background daemons use pythonw so no
# console window flashes on the operator's desktop every time this fires. The
# driver runs for hours, so a stray console would also sit in the taskbar for
# the whole night waiting to be closed by accident.
$py     = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$driver = Join-Path $PSScriptRoot "queue_loop.py"
$repo   = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

if (-not (Test-Path $py))     { throw "python not found: $py" }
if (-not (Test-Path $driver)) { throw "driver not found: $driver" }

# STOP SENTINELS, CHECKED BEFORE THE SPAWN. The driver honours these three files
# itself and correctly runs zero cycles when one is present - but this script
# used to print "queue-loop driver started pid=..." over exactly that no-op, and
# `control\STOP` EXISTS on Legion right now (content: "operator halt via LW
# session 2026-07-28"), so every fire today was that no-op. The operator reads
# this banner, not the ledger, so the refusal has to happen HERE.
#
# The same three relative paths as queue_loop.STOP_RELPATHS, in the same order.
$sentinels = @(
  (Join-Path $PSScriptRoot "control\STOP"),
  (Join-Path $PSScriptRoot "control\lanes\QUEUE_STOP"),
  (Join-Path $PSScriptRoot "control\lanes\QUEUE_DRAINED")
)
$present = @($sentinels | Where-Object { Test-Path $_ })
if ($present.Count -gt 0) {
  Write-Warning "queue-loop: stop sentinel present - the driver would run ZERO cycles."
  foreach ($p in $present) { Write-Warning "  present: $p" }
  if (-not $Force) {
    # exit 2 matches queue_loop.EXIT_STOP_SENTINEL, so a wrapper sees one number
    # for one condition whichever half of the pair refused.
    Write-Warning "REFUSING to start. Delete the file above to run, or pass -Force."
    exit 2
  }
  # Said plainly rather than implied: -Force only gets PAST this script. The
  # driver re-checks the same files before cycle 1 and will still run zero
  # cycles and exit 2 while they exist. It is for the case where the file is
  # about to be removed, or where --control-dir points somewhere else.
  Write-Warning "-Force given: starting anyway. NOTE the driver re-checks these files itself."
}

# Start-Process refuses to point stdout and stderr at the SAME file, so stderr
# gets a sibling. Both are truncated on each launch, which is fine because the
# DURABLE record is ops/loop/reports/queue_loop.jsonl - these two are the human
# tail, not the ledger.
$logDir = Split-Path $Log -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$errLog = "$Log.err"

# NO DETACHED_PROCESS equivalent anywhere in this file, and that is deliberate.
# MEASURED 2026-07-31 (recorded in lane_launcher.py): a spawn carrying
# DETACHED_PROCESS issues a real pid and returns rc=0 while doing NOTHING at all,
# because the child cannot initialise a host without a console. Start-Process
# already returns immediately and leaves the child running independently of this
# session, so detachment costs nothing extra; -WindowStyle Hidden is the belt to
# pythonw's braces for any console the child might otherwise be given.
# The driver path MUST be quoted, and this is not defensive style - MEASURED
# 2026-09-05 on the first real fire of this launcher. Start-Process joins an
# -ArgumentList array with spaces and quotes NOTHING, so the repo root's space
# split the path in two and pythonw got `C:\Riot` as its script argument:
#
#   pythonw.exe: can't open file 'C:\Riot': [Errno 2] No such file or directory
#
# The failure is silent in the shape that matters - Start-Process still issued
# a real pid, this script still printed "queue-loop driver started", and the
# whole night would have produced nothing. Same class as the DETACHED_PROCESS
# note below: a success banner over a process that did no work.
$argList = @("`"$driver`"", "--cycles", $Cycles, "--settle", $Settle)
$proc = Start-Process -FilePath $py -ArgumentList $argList `
                      -WorkingDirectory $repo `
                      -WindowStyle Hidden -PassThru `
                      -RedirectStandardOutput $Log -RedirectStandardError $errLog

"queue-loop driver started pid=$($proc.Id) cycles=$Cycles settle=$Settle"
"  log:    $Log"
"  errlog: $errLog"
"  ledger: $(Join-Path $PSScriptRoot 'reports\queue_loop.jsonl')"
"  stop:   create ops\loop\control\lanes\QUEUE_STOP (or control\STOP for everything)"
"  kill:   taskkill /F /T /PID $($proc.Id)    # never Stop-Process"
