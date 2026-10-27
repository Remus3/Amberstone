# launcher_cutover.ps1 - PKG-7: the ONLOGON-to-launcher cutover
# (docs/PACKAGING_PLAN.md section 5). OPERATOR STEP: no session, lane or loop
# runs it with -Apply. Runbook: docs/OPERATIONS.md "Launcher cutover (PKG-7)".
#
# DEFAULT = DRY RUN. With no switch it reads the scheduled tasks, exports each
# task's XML in memory (proves the backup will work), shows what it would write
# and unregister, the RC listeners on 8888 / 8889 / 8860 and the launcher status
# file, and changes NOTHING: no task, no file, no process. Only -Apply changes
# anything, and -WhatIf always wins over -Apply.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\launcher_cutover.ps1
#       dry run of the cutover (also the stage 2 check afterwards)
#   ... -File tools\launcher_cutover.ps1 -Apply                (elevated)
#       1. export every listed task's XML to a NEW gitignored backup folder
#          ops\runtime\launcher_cutover\cutover-<yyyyMMdd-HHmmss>\ (one <task>.xml
#          each, UTF-16 as Task Scheduler writes it, plus manifest.json with the
#          prior state and the sha256 of every file);
#       2. read every file back and check its sha256 - any failure stops the
#          run before the first unregister;
#       3. UNREGISTER each task (never disable: a disabled RC-DaemonSlayer makes
#          RC's DsWatchdog raise instead of starting DS itself, plan S9);
#       4. read back that each one is gone.
#   ... -File tools\launcher_cutover.ps1 -Rollback             (dry run)
#   ... -File tools\launcher_cutover.ps1 -Rollback -Apply      (elevated)
#       re-imports the newest backup (or -BackupDir <folder>): each XML's
#       sha256 must match its manifest entry, a task that is registered again
#       is left alone, a task whose account needs a password is imported by
#       hand (Task Scheduler, Import Task).
#
# Switches: -Apply, -Rollback, -IncludeLiveFlipWatcher (also moves the DS
# live-flip watcher task off ONLOGON; the launcher does not run that watcher),
# -BackupRoot <dir> (default ops\runtime\launcher_cutover), -BackupDir <dir>
# (rollback only), -WhatIf.
#
# The listed tasks are exactly section 5's. Dev and fleet tasks are not the app
# and are never named here; the disabled bare legacy task is the operator's
# separate call. Unregistering a task does not stop a process it already
# started: stage 2 restarts Windows, because a sign-out leaves running both
# the boot-trigger SYSTEM task RC-DaemonSlayer and the S4U tasks RC-LCUAgent,
# RC-LiveClientRelay and RC-Phase3-Supervisor (S4U runs outside the session).
# This script never stops, kills or starts a process and never starts a task.
#
# Exit codes: 0 done (or plan printed), 1 a step failed or a backup was
# refused, 2 refused before any change (not elevated for -Apply, no backup to
# roll back, bad switches).
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Apply,
    [switch]$Rollback,
    [switch]$IncludeLiveFlipWatcher,
    [string]$BackupRoot = '',
    [string]$BackupDir = ''
)

$ErrorActionPreference = 'Stop'

$CoreTasks = @(
    'RC-Supervisor',
    'RC-LCUAgent',
    'RC-LiveClientRelay',
    'RC-HotkeyListener',
    'RC-Phase3-Supervisor',
    'RC-DaemonSlayer',
    'RC-DSKeepalive'
)
$OptionalTasks = @('RC-LiveFlipWatcher')
$RcPorts = @(8888, 8889, 8860)
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Write-Line {
    param([string]$Name, [string]$Message)
    Write-Host ('  {0,-22}: {1}' -f $Name, $Message)
}

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return [bool]$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# The ONE gate for every change. A dry run prints the change and returns; a
# real run refuses without elevation, then runs the block.
function Invoke-Change {
    param([string]$What, [scriptblock]$Do)
    if ($script:DryRun) {
        Write-Host ('  would ' + $What)
        return
    }
    if (-not $script:Elevated) {
        throw ('refused, not elevated: ' + $What)
    }
    Write-Host ('  ' + $What)
    & $Do
}

function Write-AtomicFile {
    param([string]$Path, [byte[]]$Bytes)
    $tmp = $Path + '.tmp'
    [IO.File]::WriteAllBytes($tmp, $Bytes)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Get-Sha256Hex {
    param([byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash($Bytes) } finally { $sha.Dispose() }
    return ([BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant()
}

# Task XML as Task Scheduler writes it: UTF-16 LE with a byte-order mark.
function ConvertTo-TaskXmlBytes {
    param([string]$Text)
    $enc = [Text.Encoding]::Unicode
    return [byte[]]($enc.GetPreamble() + $enc.GetBytes($Text))
}

# Bytes -> text; throws unless the bytes hold a task definition.
function ConvertFrom-TaskXmlBytes {
    param([byte[]]$Bytes)
    $stream = New-Object IO.MemoryStream(, $Bytes)
    $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::Unicode, $true)
    try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
    $doc = New-Object Xml.XmlDocument
    $doc.LoadXml($text)
    if ($doc.DocumentElement.LocalName -ne 'Task') { throw 'not a task definition' }
    return $text
}

function Get-XmlLogonType {
    param([string]$Text)
    $doc = New-Object Xml.XmlDocument
    $doc.LoadXml($Text)
    $node = $doc.SelectSingleNode("//*[local-name()='Principal']/*[local-name()='LogonType']")
    if ($null -eq $node) { return '' }
    return $node.InnerText.Trim()
}

function Write-Listeners {
    $rows = @(Get-NetTCPConnection -State Listen -LocalPort $RcPorts -ErrorAction SilentlyContinue)
    if ($rows.Count -eq 0) {
        Write-Host '  listeners on 8888 / 8889 / 8860: none'
        return
    }
    foreach ($row in ($rows | Sort-Object LocalPort, OwningProcess -Unique)) {
        Write-Host ('  listener :' + $row.LocalPort + ' pid ' + $row.OwningProcess)
    }
}

function Write-LauncherStatus {
    $path = Join-Path $RepoRoot 'ops\runtime\launcher_status.json'
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host '  launcher_status.json: absent - stage 0 (the app once in attach mode) comes first'
        return
    }
    try {
        $status = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
        Write-Host ('  launcher_status.json: mode ' + $status.mode + ', state ' + $status.state +
            ', profile ' + $status.profile + ', updated ' + $status.updated)
    } catch {
        Write-Host '  launcher_status.json: unreadable'
    }
}

# After a real write: every file must read back with the sha256 recorded.
function Test-BackupReadBack {
    param([string]$Dir, $Entries)
    $bad = 0
    foreach ($entry in $Entries) {
        $ok = $false
        try {
            $bytes = [IO.File]::ReadAllBytes((Join-Path $Dir $entry.file))
            if ((Get-Sha256Hex -Bytes $bytes) -eq $entry.sha256) {
                [void](ConvertFrom-TaskXmlBytes -Bytes $bytes)
                $ok = $true
            }
        } catch {
            $ok = $false
        }
        if ($ok) {
            Write-Line $entry.name 'backup read back, sha256 ok'
        } else {
            Write-Line $entry.name 'backup read back FAILED'
            $bad++
        }
    }
    try {
        $manifest = Get-Content -Raw -LiteralPath (Join-Path $Dir 'manifest.json') | ConvertFrom-Json
        if (@($manifest.tasks).Count -ne @($Entries).Count) { $bad++ }
    } catch {
        Write-Host '  manifest.json read back FAILED'
        $bad++
    }
    return ($bad -eq 0)
}

function Invoke-Cutover {
    $names = @($CoreTasks)
    if ($IncludeLiveFlipWatcher) { $names += $OptionalTasks }
    Write-Host ''
    Write-Host 'Preflight:'
    Write-LauncherStatus
    Write-Listeners
    Write-Host ''
    Write-Host 'Tasks (unregister, never disable):'
    $found = @()
    $bad = 0
    foreach ($n in $names) {
        $hits = @(Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue)
        if ($hits.Count -eq 0) {
            Write-Line $n 'not registered - nothing to do'
            continue
        }
        if ($hits.Count -gt 1) {
            Write-Line $n ('registered in ' + $hits.Count + ' folders - refused, ambiguous')
            $bad++
            continue
        }
        $t = $hits[0]
        try {
            $xml = Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop
            $bytes = ConvertTo-TaskXmlBytes -Text ([string]$xml)
            [void](ConvertFrom-TaskXmlBytes -Bytes $bytes)
        } catch {
            Write-Line $n ('export FAILED: ' + $_.Exception.Message)
            $bad++
            continue
        }
        Write-Line $n ('state ' + $t.State + ', logon ' + $t.Principal.LogonType + ', run level ' +
            $t.Principal.RunLevel + ', XML ' + $bytes.Length + ' bytes')
        $entry = [ordered]@{
            name       = [string]$t.TaskName
            path       = [string]$t.TaskPath
            state      = [string]$t.State
            logon_type = [string]$t.Principal.LogonType
            run_level  = [string]$t.Principal.RunLevel
            file       = ($n + '.xml')
            sha256     = (Get-Sha256Hex -Bytes $bytes)
            bytes      = $bytes.Length
        }
        $found += [pscustomobject]@{ Task = $t; Bytes = $bytes; Entry = $entry }
    }
    if ($bad -gt 0) {
        Write-Host ''
        Write-Host ('refused: ' + $bad + ' task(s) could not be backed up - nothing was changed.')
        return 1
    }
    if ($found.Count -eq 0) {
        Write-Host ''
        Write-Host 'nothing to unregister: none of the listed tasks is registered.'
        return 0
    }

    $dir = Join-Path $script:BackupRootPath ('cutover-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if (Test-Path -LiteralPath $dir) {
        Write-Host ('refused: the backup folder already exists: ' + $dir)
        return 2
    }
    Write-Host ''
    Write-Host ('Backup: ' + $dir)
    $null = Invoke-Change -What 'create the backup folder' -Do { [void][IO.Directory]::CreateDirectory($dir) }
    foreach ($f in $found) {
        $null = Invoke-Change -What ('write ' + $f.Entry.file) -Do { Write-AtomicFile -Path (Join-Path $dir $f.Entry.file) -Bytes $f.Bytes }
    }
    $manifest = [ordered]@{
        schema  = 1
        tool    = 'tools/launcher_cutover.ps1'
        created = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        tasks   = @($found | ForEach-Object { $_.Entry })
    }
    $manifestBytes = (New-Object Text.UTF8Encoding($false)).GetBytes((ConvertTo-Json -InputObject $manifest -Depth 4))
    $null = Invoke-Change -What 'write manifest.json' -Do { Write-AtomicFile -Path (Join-Path $dir 'manifest.json') -Bytes $manifestBytes }
    if ($script:DryRun) {
        Write-Host '  (the read-back of the written backup runs with -Apply, before any unregister)'
    } elseif (-not (Test-BackupReadBack -Dir $dir -Entries $manifest.tasks)) {
        Write-Host 'refused: the backup did not read back - NOTHING was unregistered.'
        return 1
    }

    Write-Host ''
    Write-Host 'Unregister:'
    foreach ($f in $found) {
        $t = $f.Task
        try {
            $null = Invoke-Change -What ('unregister ' + $t.TaskName) -Do { Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false -ErrorAction Stop }
        } catch {
            Write-Line $t.TaskName ('unregister FAILED: ' + $_.Exception.Message)
            $bad++
        }
    }
    if (-not $script:DryRun) {
        Write-Host ''
        Write-Host 'Read back:'
        foreach ($f in $found) {
            $left = @(Get-ScheduledTask -TaskName $f.Task.TaskName -TaskPath $f.Task.TaskPath -ErrorAction SilentlyContinue)
            if ($left.Count -gt 0) {
                Write-Line $f.Task.TaskName 'STILL registered'
                $bad++
            } else {
                Write-Line $f.Task.TaskName 'gone'
            }
        }
        Write-Host ''
        Write-Host 'Next (stage 2): restart Windows - an unregistered task does not stop what it'
        Write-Host 'started. Then run this script with no switch: no listed task, no listener on'
        Write-Host '8888 / 8889 / 8860. Then launch the app (this checkout: --profile dev).'
        Write-Host ('Rollback: tools\launcher_cutover.ps1 -Rollback -Apply   (backup ' + $dir + ')')
    }
    if ($bad -gt 0) { return 1 }
    return 0
}

function Invoke-Rollback {
    $dir = $BackupDir
    if (-not $dir -and (Test-Path -LiteralPath $script:BackupRootPath)) {
        $candidates = @(Get-ChildItem -LiteralPath $script:BackupRootPath -Directory |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'manifest.json') } |
            Sort-Object Name -Descending)
        if ($candidates.Count -gt 0) { $dir = $candidates[0].FullName }
    }
    if (-not $dir -or -not (Test-Path -LiteralPath (Join-Path $dir 'manifest.json'))) {
        Write-Host ''
        Write-Host ('refused: no backup with a manifest.json under ' + $script:BackupRootPath)
        return 2
    }
    Write-Host ''
    Write-Host ('Backup: ' + $dir)
    try {
        $manifest = Get-Content -Raw -LiteralPath (Join-Path $dir 'manifest.json') | ConvertFrom-Json
    } catch {
        Write-Host 'refused: manifest.json is unreadable - nothing re-registered.'
        return 1
    }
    if ($manifest.schema -ne 1 -or $null -eq $manifest.tasks) {
        Write-Host 'refused: manifest.json is not a schema-1 cutover manifest - nothing re-registered.'
        return 1
    }
    $known = @($CoreTasks) + @($OptionalTasks)
    $integrity = 0
    $manual = 0
    $todo = @()
    Write-Host 'Tasks:'
    foreach ($e in @($manifest.tasks)) {
        $name = [string]$e.name
        if ($known -notcontains $name -or [string]$e.file -ne ($name + '.xml')) {
            Write-Line $name 'not a cutover task entry - refused'
            $integrity++
            continue
        }
        try {
            $bytes = [IO.File]::ReadAllBytes((Join-Path $dir $e.file))
        } catch {
            Write-Line $name ('backup file missing: ' + $e.file)
            $integrity++
            continue
        }
        if ((Get-Sha256Hex -Bytes $bytes) -ne [string]$e.sha256) {
            Write-Line $name 'sha256 mismatch - refused, the backup changed after the cutover'
            $integrity++
            continue
        }
        try {
            $text = ConvertFrom-TaskXmlBytes -Bytes $bytes
            $logon = Get-XmlLogonType -Text $text
        } catch {
            Write-Line $name 'not a task definition - refused'
            $integrity++
            continue
        }
        if ($logon -eq 'Password' -or $logon -eq 'InteractiveTokenOrPassword') {
            Write-Line $name ('needs its account password - import ' + $e.file + ' by hand (Task Scheduler, Import Task)')
            $manual++
            continue
        }
        $taskPath = [string]$e.path
        if (-not $taskPath) { $taskPath = '\' }
        $existing = @(Get-ScheduledTask -TaskName $name -TaskPath $taskPath -ErrorAction SilentlyContinue)
        if ($existing.Count -gt 0) {
            Write-Line $name 'already registered - left alone'
            continue
        }
        Write-Line $name ('backup ok (sha256), prior state ' + $e.state + ', logon ' + $e.logon_type)
        $todo += [pscustomobject]@{ Name = $name; TaskPath = $taskPath; Xml = $text; File = [string]$e.file }
    }
    if ($integrity -gt 0) {
        Write-Host ''
        Write-Host ('refused: ' + $integrity + ' backup entry(ies) failed the integrity check - nothing re-registered.')
        return 1
    }
    $bad = $manual
    Write-Host ''
    Write-Host 'Re-register:'
    if ($todo.Count -eq 0) { Write-Host '  nothing to re-register' }
    foreach ($r in $todo) {
        try {
            $null = Invoke-Change -What ('re-register ' + $r.Name + ' from ' + $r.File) -Do { Register-ScheduledTask -Xml $r.Xml -TaskName $r.Name -TaskPath $r.TaskPath -ErrorAction Stop | Out-Null }
        } catch {
            Write-Line $r.Name ('re-register FAILED: ' + $_.Exception.Message)
            $bad++
        }
    }
    if (-not $script:DryRun) {
        Write-Host ''
        Write-Host 'Read back:'
        foreach ($r in $todo) {
            $back = @(Get-ScheduledTask -TaskName $r.Name -TaskPath $r.TaskPath -ErrorAction SilentlyContinue)
            if ($back.Count -eq 0) {
                Write-Line $r.Name 'NOT registered'
                $bad++
            } else {
                Write-Line $r.Name ('registered, state ' + $back[0].State)
            }
        }
    }
    if ($bad -gt 0) { return 1 }
    return 0
}

# ---- main
$script:DryRun = (-not $Apply) -or [bool]$WhatIfPreference
$script:Elevated = Test-Elevated
if ($BackupRoot) {
    $script:BackupRootPath = $BackupRoot
} else {
    $script:BackupRootPath = Join-Path $RepoRoot 'ops\runtime\launcher_cutover'
}
$mode = 'cutover'
if ($Rollback) { $mode = 'rollback' }

Write-Host ('=== launcher_cutover: ' + $mode + ' (PACKAGING_PLAN section 5) ===')
if ($script:DryRun) {
    Write-Host 'DRY RUN (the default): nothing is changed. A real run is elevated, with -Apply.'
} else {
    Write-Host 'APPLY: scheduled tasks WILL change.'
}
Write-Host ('elevated: ' + $script:Elevated)

if ($BackupDir -and -not $Rollback) {
    Write-Host 'refused: -BackupDir goes with -Rollback.'
    exit 2
}
if (-not $script:DryRun -and -not $script:Elevated) {
    Write-Host 'refused: -Apply needs an elevated PowerShell (Run as administrator). Nothing changed.'
    exit 2
}
if ($Rollback) {
    $rc = @(Invoke-Rollback)[-1]
} else {
    $rc = @(Invoke-Cutover)[-1]
}
exit ([int]$rc)
