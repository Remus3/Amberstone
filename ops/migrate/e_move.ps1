<#
.SYNOPSIS
  Move RC from C: to E: - copy, then leave DIRECTORY JUNCTIONS at the old C: paths.

.DESCRIPTION
  Phases, in order (each idempotent; -DryRun only lists and writes nothing but its log):
    Stop             disable + end the RC-* tasks that reference Src/WtSrc, kill RC processes
    Preseed          robocopy Src->Dst and WtSrc->WtDst, recreate links that point inside
    RepointInternal  git hooksPath, worktree link files, untracked configs, Claude memory (Dst only)
    Cutover          detached waiter: wait for -WaitPid, delta copy, rename C: aside,
                     junction C: -> E:, repoint tasks / shortcuts / .claude.json, restart, verify
    Status           print the state file summary
  Read ops/migrate/README.md before running anything that is not -DryRun.

  Windows PowerShell 5.1 compatible. ASCII only. Processes are ended with taskkill /F /PID.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Stop', 'Preseed', 'RepointInternal', 'Cutover', 'Status')]
    [string]$Phase,
    [switch]$DryRun,
    # The four roots carry no machine default: a re-run names them explicitly.
    [Parameter(Mandatory = $true)][string]$Src,
    [Parameter(Mandatory = $true)][string]$Dst,
    [Parameter(Mandatory = $true)][string]$WtSrc,
    [Parameter(Mandatory = $true)][string]$WtDst,
    [int]$WaitPid = 0,
    [int]$ExcludeTreeOfPid = -1,
    [switch]$Detach,
    [switch]$NoWait,
    [switch]$AllowExistingDst,
    [string]$Python = '',
    [string]$UserHome = ''
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Constants and parameter normalisation
# ---------------------------------------------------------------------------

function Get-NormPath([string]$Path) {
    return ([System.IO.Path]::GetFullPath($Path)).TrimEnd('\')
}

$Src = Get-NormPath $Src
$Dst = Get-NormPath $Dst
$WtSrc = Get-NormPath $WtSrc
$WtDst = Get-NormPath $WtDst
if (-not $UserHome) { $UserHome = $env:USERPROFILE }
if (-not $Python) {
    $base = $env:LOCALAPPDATA
    if (-not $base) { $base = Join-Path $UserHome 'AppData\Local' }
    $Python = Join-Path $base 'Programs\Python\Python314\python.exe'
}
if ($ExcludeTreeOfPid -lt 0) {
    $ExcludeTreeOfPid = 0
    if ($env:CLAUDE_PID) { $ExcludeTreeOfPid = [int]$env:CLAUDE_PID }
}

$script:Sys32 = Join-Path $env:SystemRoot 'System32'
$script:SafeCwd = $env:SystemRoot
$script:StateRel = 'ops\runtime\e_move_state.json'
# This tool's own files are written on both sides and must never be copied over each
# other (robocopy holds its log open; the state is saved from memory after each copy).
$script:OwnFilesXf = @('/XF', 'e_move.log', 'e_move_robocopy.log', 'e_move_state.json')
$script:BackupRel = 'ops\runtime\e_move_backup'
$script:LogFile = $null
$script:RoboLog = $null
$script:StateLoadedFrom = '(new)'
$script:KilledPids = @{}
$script:SrcAside = $null
$script:WtAside = $null
# Which C: directories THIS run (or the crashed run it resumes) renamed / junctioned.
$script:Renamed = @{ src = $false; wt = $false }
$script:Junctioned = @{ src = $false; wt = $false }
# A live Claude session whose tree is NOT protected (the exited -WaitPid session).
$script:UnprotectPid = 0
# Never stopped, never killed: the headless proxy every other tree depends on.
$script:ProtectedTasks = @('RC-TeamClaudeProxy')
$script:ProtectCmdPattern = '(?i)teamclaude'
# Never killed: any copy of this tool (another phase, or the detached waiter).
$script:SelfCmdPattern = '(?i)e_move\.ps1'
$script:WaiterCmdPattern = '(?i)e_move\.ps1.*-Phase\s+Cutover'
# Live Claude sessions (claude.exe, or node running the Claude Code CLI) keep their trees.
$script:ClaudeCmdPattern = '(?i)@anthropic-ai[\\/]+claude-code|claude-code[\\/]+cli\.m?js'
$script:CwdReaderReady = $null
# Reads another process's current directory from its PEB (x64 and WOW64 targets).
# Fail-soft: any failure (access, exited, layout) returns null for that process.
$script:CwdReaderSource = @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace EMove {
public static class ProcCwd {
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr OpenProcess(int access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, IntPtr size, out IntPtr read);
    [DllImport("ntdll.dll")]
    static extern int NtQueryInformationProcess(IntPtr h, int cls, ref Pbi info, int len, out int retLen);
    [DllImport("ntdll.dll")]
    static extern int NtQueryInformationProcess(IntPtr h, int cls, ref IntPtr info, int len, out int retLen);

    [StructLayout(LayoutKind.Sequential)]
    struct Pbi {
        public IntPtr ExitStatus; public IntPtr PebBaseAddress; public IntPtr AffinityMask;
        public IntPtr BasePriority; public IntPtr UniqueProcessId; public IntPtr InheritedFromUniqueProcessId;
    }

    static byte[] Read(IntPtr h, long addr, int n) {
        if (addr == 0 || n <= 0) return null;
        byte[] b = new byte[n];
        IntPtr got;
        if (!ReadProcessMemory(h, new IntPtr(addr), b, new IntPtr(n), out got)) return null;
        if (got.ToInt64() != n) return null;
        return b;
    }

    static string ReadStr(IntPtr h, long addr, int len) {
        if (len <= 0 || len > 0x8000) return null;
        byte[] s = Read(h, addr, len);
        return s == null ? null : Encoding.Unicode.GetString(s);
    }

    public static string Get(int pid) {
        if (IntPtr.Size != 8) return null;
        IntPtr h = OpenProcess(0x0410, false, pid);
        if (h == IntPtr.Zero) return null;
        try {
            int rl;
            IntPtr peb32 = IntPtr.Zero;
            if (NtQueryInformationProcess(h, 26, ref peb32, IntPtr.Size, out rl) == 0 && peb32 != IntPtr.Zero) {
                byte[] p = Read(h, peb32.ToInt64() + 0x10, 4);
                if (p == null) return null;
                byte[] us = Read(h, (long)BitConverter.ToUInt32(p, 0) + 0x24, 8);
                if (us == null) return null;
                return ReadStr(h, (long)BitConverter.ToUInt32(us, 4), BitConverter.ToUInt16(us, 0));
            }
            Pbi pbi = new Pbi();
            if (NtQueryInformationProcess(h, 0, ref pbi, Marshal.SizeOf(typeof(Pbi)), out rl) != 0) return null;
            byte[] q = Read(h, pbi.PebBaseAddress.ToInt64() + 0x20, 8);
            if (q == null) return null;
            byte[] u = Read(h, BitConverter.ToInt64(q, 0) + 0x38, 16);
            if (u == null) return null;
            return ReadStr(h, BitConverter.ToInt64(u, 8), BitConverter.ToUInt16(u, 0));
        } catch {
            return null;
        } finally {
            CloseHandle(h);
        }
    }
}
}
'@
# Never killed even when they descend from an RC process (a live game, the shell).
$script:ProtectNames = @(
    'league of legends.exe', 'leagueclient.exe', 'leagueclientux.exe', 'leagueclientuxrender.exe',
    'riotclientservices.exe', 'riotclientux.exe', 'riotclientuxrender.exe', 'riotclientcrashhandler.exe',
    'vgc.exe', 'vgtray.exe', 'obs64.exe', 'obs32.exe', 'obs.exe',
    'explorer.exe', 'dwm.exe', 'csrss.exe', 'winlogon.exe', 'svchost.exe', 'services.exe',
    'lsass.exe', 'wininit.exe', 'smss.exe', 'taskhostw.exe', 'wmiprvse.exe'
)
# Never OPENED either (no OpenProcess / ReadProcessMemory for the cwd probe): anti-cheat
# (Vanguard), the Riot / League clients, OBS and core OS processes. Matched by NAME,
# before any handle is requested.
$script:NoProbePattern = '(?i)^(riotclient.*|leagueclient.*|league of legends\.exe|vg[a-z]*\.exe|obs(32|64)?\.exe|obs-.*\.exe|' +
    'system|registry|secure system|memory compression|system idle process|idle|' +
    'csrss\.exe|lsass\.exe|lsaiso\.exe|smss\.exe|wininit\.exe|services\.exe|winlogon\.exe|dwm\.exe)$'

$script:Git = 'git.exe'
$gitCmd = Get-Command git.exe -ErrorAction SilentlyContinue
if ($gitCmd) { $script:Git = $gitCmd.Source }
elseif (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'Git\cmd\git.exe')) {
    $script:Git = Join-Path $env:ProgramFiles 'Git\cmd\git.exe'
}

# ---------------------------------------------------------------------------
# Logging, text, state
# ---------------------------------------------------------------------------

function ConvertTo-AsciiText([string]$Text) {
    if ($null -eq $Text) { return '' }
    $sb = New-Object System.Text.StringBuilder ($Text.Length + 16)
    foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        if ($code -lt 128) { [void]$sb.Append($ch) } else { [void]$sb.Append(('\u{0:x4}' -f $code)) }
    }
    return $sb.ToString()
}

function Limit-Text([string]$Text, [int]$Max) {
    if ($null -eq $Text) { return '' }
    if ($Text.Length -le $Max) { return $Text }
    return $Text.Substring(0, $Max)
}

function Initialize-Log {
    # A dry run logs beside Src so it never writes into the destination tree.
    $first = Join-Path $Dst 'logs'
    $second = Join-Path $Src 'logs'
    if ($DryRun) { $first = Join-Path $Src 'logs'; $second = Join-Path $Dst 'logs' }
    $dir = $first
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { $dir = $second }
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        if ($DryRun) { $dir = $env:TEMP } else { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    }
    $script:LogFile = Join-Path $dir 'e_move.log'
    $script:RoboLog = Join-Path $dir 'e_move_robocopy.log'
}

function Write-Log([string]$Message) {
    $tag = $Phase
    if ($DryRun) { $tag = $Phase + ' dry-run' }
    $msg = $Message -replace "(`r`n|`n|`r)", ' | '
    $line = ConvertTo-AsciiText ('{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $tag, $msg)
    Write-Host $line
    if ($script:LogFile) {
        try { [System.IO.File]::AppendAllText($script:LogFile, $line + "`n", [System.Text.Encoding]::ASCII) }
        catch { Write-Host ('log write failed: ' + $_.Exception.Message) }
    }
}

function New-List { return , (New-Object System.Collections.ArrayList) }

function ConvertTo-PlainData($Obj) {
    if ($null -eq $Obj) { return $null }
    if ($Obj -is [System.Management.Automation.PSCustomObject]) {
        $h = [ordered]@{}
        foreach ($prop in $Obj.PSObject.Properties) { $h[$prop.Name] = ConvertTo-PlainData $prop.Value }
        return $h
    }
    if ($Obj -is [System.Collections.IDictionary]) {
        $h = [ordered]@{}
        foreach ($k in @($Obj.Keys)) { $h[[string]$k] = ConvertTo-PlainData $Obj[$k] }
        return $h
    }
    if (($Obj -is [System.Collections.IEnumerable]) -and -not ($Obj -is [string])) {
        $list = New-Object System.Collections.ArrayList
        foreach ($x in $Obj) { [void]$list.Add((ConvertTo-PlainData $x)) }
        return , $list
    }
    return $Obj
}

function Read-State {
    foreach ($root in @($Dst, $Src)) {
        $p = Join-Path $root $script:StateRel
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            try {
                $obj = (Get-Content -LiteralPath $p -Raw) | ConvertFrom-Json
                $script:StateLoadedFrom = $p
                return (ConvertTo-PlainData $obj)
            } catch { Write-Log ('state at ' + $p + ' unreadable: ' + $_.Exception.Message) }
        }
    }
    return [ordered]@{
        version = 1; src = $Src; dst = $Dst; wt_src = $WtSrc; wt_dst = $WtDst
        status = 'new'; created = (Get-Date).ToString('s')
    }
}

function Get-StateTargets {
    $t = New-Object System.Collections.ArrayList
    if ($Phase -eq 'Cutover') {
        [void]$t.Add((Join-Path $Dst $script:StateRel))
        $srcItem = Get-Item -LiteralPath $Src -Force -ErrorAction SilentlyContinue
        if ($srcItem -and -not $srcItem.LinkType) { [void]$t.Add((Join-Path $Src $script:StateRel)) }
        if ($script:SrcAside -and (Test-Path -LiteralPath $script:SrcAside -PathType Container)) {
            [void]$t.Add((Join-Path $script:SrcAside $script:StateRel))
        }
    } elseif (Test-Path -LiteralPath $Dst -PathType Container) {
        [void]$t.Add((Join-Path $Dst $script:StateRel))
    } else {
        [void]$t.Add((Join-Path $Src $script:StateRel))
    }
    return , $t
}

function Save-State {
    if ($DryRun) { return }
    $script:State['updated'] = (Get-Date).ToString('s')
    $json = ConvertTo-Json -InputObject $script:State -Depth 24
    $json = (ConvertTo-AsciiText $json) -replace "`r`n", "`n"
    foreach ($p in (Get-StateTargets)) {
        try {
            $dir = Split-Path -Parent $p
            if (-not (Test-Path -LiteralPath $dir -PathType Container)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            $tmp = '{0}.{1}.tmp' -f $p, $PID
            [System.IO.File]::WriteAllText($tmp, $json + "`n", (New-Object System.Text.ASCIIEncoding))
            if (Test-Path -LiteralPath $p -PathType Leaf) { [System.IO.File]::Replace($tmp, $p, [NullString]::Value) }
            else { [System.IO.File]::Move($tmp, $p) }
        } catch { Write-Log ('state write failed at ' + $p + ': ' + $_.Exception.Message) }
    }
}

function Set-Status([string]$Status) {
    $script:State['status'] = $Status
    Write-Log ('status -> ' + $Status)
}

# ---------------------------------------------------------------------------
# Child processes (no console window, never a cwd inside Src)
# ---------------------------------------------------------------------------

function Format-Arg([string]$Arg) {
    if ($null -eq $Arg -or $Arg -eq '') { return '""' }
    if ($Arg -notmatch '[\s"]') { return $Arg }
    $s = [regex]::Replace($Arg, '(\\*)"', { param($m) ($m.Groups[1].Value * 2) + '\"' })
    $s = [regex]::Replace($s, '(\\+)$', { param($m) $m.Groups[1].Value * 2 })
    return '"' + $s + '"'
}

function Invoke-Exe {
    param([string]$File, [string[]]$ArgList = @(), [string]$RawArgs = '', [switch]$NoCapture)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $File
    if ($RawArgs) { $psi.Arguments = $RawArgs }
    else { $psi.Arguments = ((@($ArgList) | ForEach-Object { Format-Arg ([string]$_) }) -join ' ') }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $script:SafeCwd
    if (-not $NoCapture) {
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    }
    $p = [System.Diagnostics.Process]::Start($psi)
    $out = ''
    $err = ''
    if (-not $NoCapture) {
        $errTask = $p.StandardError.ReadToEndAsync()
        $out = $p.StandardOutput.ReadToEnd()
        $p.WaitForExit()
        $err = $errTask.Result
    } else {
        $p.WaitForExit()
    }
    return [pscustomobject]@{ Code = $p.ExitCode; Out = $out; Err = $err; Cmd = ($File + ' ' + $psi.Arguments) }
}

function Get-MapArgs { return @('--map', $Src, $Dst, '--map', $WtSrc, $WtDst) }

function Invoke-Helper([string[]]$HelperArgs) {
    $helper = Join-Path $PSScriptRoot 'e_move_helpers.py'
    $r = Invoke-Exe -File $Python -ArgList (@('-B', $helper) + $HelperArgs)
    if ($r.Err -and $r.Err.Trim()) { Write-Log ('helper stderr: ' + (Limit-Text $r.Err.Trim() 600)) }
    if ($r.Code -ne 0) { throw ('helper exit ' + $r.Code + ': ' + (Limit-Text $r.Cmd 300)) }
    return (ConvertTo-PlainData ($r.Out | ConvertFrom-Json))
}

function Invoke-Robocopy([string]$From, [string]$To, [string[]]$Opts) {
    $argStr = (Format-Arg $From) + ' ' + (Format-Arg $To) + ' ' + ($Opts -join ' ') + ' /LOG+:"' + $script:RoboLog + '"'
    if ($DryRun) {
        Write-Log ('would run: robocopy ' + $argStr)
        return [pscustomobject]@{ Code = -1; Ok = $true; Args = $argStr }
    }
    Write-Log ('robocopy ' + $argStr)
    $r = Invoke-Exe -File (Join-Path $script:Sys32 'Robocopy.exe') -RawArgs $argStr -NoCapture
    $ok = ($r.Code -ge 0 -and $r.Code -lt 8)
    Write-Log ('robocopy exit {0} ok={1}' -f $r.Code, $ok)
    return [pscustomobject]@{ Code = $r.Code; Ok = $ok; Args = $argStr }
}

function New-Link([string]$Kind, [string]$Link, [string]$Target) {
    $flag = ''
    if ($Kind -eq 'junction') { $flag = '/J ' } elseif ($Kind -eq 'symlink_dir') { $flag = '/D ' }
    $raw = '/c mklink ' + $flag + (Format-Arg $Link) + ' ' + (Format-Arg $Target)
    return (Invoke-Exe -File (Join-Path $script:Sys32 'cmd.exe') -RawArgs $raw)
}

# ---------------------------------------------------------------------------
# Path literals: every spelling of Src / WtSrc (C:\X, C:/X, C:\\X, /c/X)
# ---------------------------------------------------------------------------

function Split-DrivePath([string]$Path) {
    if ($Path -notmatch '^([A-Za-z]):[\\/]+(.+)$') { throw ('not a drive-absolute path: ' + $Path) }
    $drive = $Matches[1]
    $parts = @($Matches[2] -split '[\\/]+' | Where-Object { $_ -ne '' })
    if ($parts.Count -eq 0) { throw ('refusing a bare drive root: ' + $Path) }
    return @{ Drive = $drive; Parts = $parts }
}

function New-PathMapping([string]$From, [string]$To) {
    $f = Split-DrivePath $From
    $t = Split-DrivePath $To
    $d = '(?<d>' + [regex]::Escape($f.Drive) + ')'
    $esc = @($f.Parts | ForEach-Object { [regex]::Escape($_) })
    $left = '(?<![A-Za-z0-9_])'
    $pattern = '(?:' +
        '(?<json>' + $left + $d + ':\\\\' + ($esc -join '\\\\') + ')' +
        '|(?<bs>' + $left + $d + ':\\' + ($esc -join '\\') + ')' +
        '|(?<fwd>' + $left + $d + ':/' + ($esc -join '/') + ')' +
        '|(?<msys>/' + $d + '/' + ($esc -join '/') + ')' +
        ')(?![A-Za-z0-9_.\-])'
    $opts = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    $rx = New-Object System.Text.RegularExpressions.Regex($pattern, $opts)
    return [pscustomobject]@{ From = $From; To = $To; Rx = $rx; ToDrive = $t.Drive; ToParts = $t.Parts; Depth = $f.Parts.Count }
}

$script:Mappings = @(
    @((New-PathMapping $Src $Dst), (New-PathMapping $WtSrc $WtDst)) | Sort-Object -Property Depth -Descending
)

function Test-RefsSrc([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return $false }
    foreach ($m in $script:Mappings) { if ($m.Rx.IsMatch($Text)) { return $true } }
    return $false
}

function Convert-PathText([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    $out = $Text
    foreach ($m in $script:Mappings) {
        $toDrive = $m.ToDrive
        $toParts = $m.ToParts
        $ev = {
            param($match)
            $dv = $match.Groups['d'].Value
            if ($dv -ceq $dv.ToLowerInvariant()) { $drv = $toDrive.ToLowerInvariant() } else { $drv = $toDrive.ToUpperInvariant() }
            if ($match.Groups['json'].Success) { return $drv + ':\\' + ($toParts -join '\\') }
            if ($match.Groups['bs'].Success) { return $drv + ':\' + ($toParts -join '\') }
            if ($match.Groups['fwd'].Success) { return $drv + ':/' + ($toParts -join '/') }
            return '/' + $drv + '/' + ($toParts -join '/')
        }.GetNewClosure()
        $out = $m.Rx.Replace($out, [System.Text.RegularExpressions.MatchEvaluator]$ev)
    }
    return $out
}

function Test-UnderPath([string]$Path, [string]$Root) {
    if (-not $Path -or -not $Root) { return $false }
    $p = $Path.TrimEnd('\').ToLowerInvariant()
    $r = $Root.TrimEnd('\').ToLowerInvariant()
    return (($p -eq $r) -or $p.StartsWith($r + '\'))
}

function Assert-Distinct {
    foreach ($a in @($Src, $WtSrc)) {
        foreach ($b in @($Dst, $WtDst)) {
            if ((Test-UnderPath $a $b) -or (Test-UnderPath $b $a)) { throw ('source and destination overlap: ' + $a + ' / ' + $b) }
        }
    }
}

# ---------------------------------------------------------------------------
# Processes and tasks
# ---------------------------------------------------------------------------

function Get-AncestorIds($ById, [int]$StartId) {
    $out = New-Object System.Collections.ArrayList
    $cur = $ById[$StartId]
    $guard = 0
    while ($cur -and $guard -lt 64) {
        $guard++
        $ppid = [int]$cur.ParentProcessId
        if ($ppid -le 4 -or $out.Contains($ppid) -or $ppid -eq [int]$cur.ProcessId) { break }
        $par = $ById[$ppid]
        if (-not $par) { break }
        # A parent created after its child is a recycled pid, not the parent.
        if ($par.CreationDate -and $cur.CreationDate -and ($par.CreationDate -gt $cur.CreationDate)) { break }
        [void]$out.Add($ppid)
        $cur = $par
    }
    return , $out
}

function Get-DescendantIds($ById, $Children, [int]$Root, $RootCreated) {
    $out = New-Object System.Collections.ArrayList
    if ($Root -le 4) { return , $out }
    $seen = @{}
    $seen[$Root] = $true
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($Root)
    while ($queue.Count -gt 0) {
        $cur = [int]$queue.Dequeue()
        if (-not $Children.ContainsKey($cur)) { continue }
        $parentCreated = $null
        if ($ById.ContainsKey($cur)) {
            $parentCreated = $ById[$cur].CreationDate
            # A dead root whose pid now belongs to a newer process: not our tree.
            if (($cur -eq $Root) -and $RootCreated -and $parentCreated -and ($parentCreated -ne $RootCreated)) { continue }
        } elseif ($cur -eq $Root) { $parentCreated = $RootCreated }
        if ($null -eq $parentCreated) { continue }
        foreach ($c in $Children[$cur]) {
            $cid = [int]$c.ProcessId
            if ($cid -le 4 -or $seen.ContainsKey($cid)) { continue }
            if ($c.CreationDate -and ($c.CreationDate -lt $parentCreated)) { continue }
            $seen[$cid] = $true
            [void]$out.Add($cid)
            $queue.Enqueue($cid)
        }
    }
    return , $out
}

function Initialize-CwdReader {
    if ($null -ne $script:CwdReaderReady) { return $script:CwdReaderReady }
    $script:CwdReaderReady = $false
    if ([IntPtr]::Size -ne 8) { Write-Log 'cwd reader: 32-bit PowerShell - process cwd matching disabled'; return $false }
    try {
        if (-not ('EMove.ProcCwd' -as [type])) { Add-Type -TypeDefinition $script:CwdReaderSource -Language CSharp }
        try { [System.Diagnostics.Process]::EnterDebugMode() } catch { Write-Log ('cwd reader: SeDebugPrivilege not enabled (' + $_.Exception.Message + ')') }
        $script:CwdReaderReady = $true
    } catch { Write-Log ('cwd reader unavailable - cwd matching disabled: ' + $_.Exception.Message) }
    return $script:CwdReaderReady
}

function Get-ProcessCwd([int]$ProcId) {
    if (-not $script:CwdReaderReady) { return $null }
    try { $c = [EMove.ProcCwd]::Get($ProcId) } catch { return $null }
    if (-not $c) { return $null }
    $c = $c.TrimEnd('\')
    if ($c.StartsWith('\\?\')) { $c = $c.Substring(4) }
    return $c
}

function Test-ProtectedProcess($Proc) {
    # The never-kill set, decided from Win32_Process fields only (no handle opened).
    $n = ([string]$Proc.Name).ToLowerInvariant()
    if ($script:ProtectNames -contains $n) { return $true }
    if ($n -match $script:NoProbePattern) { return $true }
    $cl = [string]$Proc.CommandLine
    return (($cl -match $script:ProtectCmdPattern) -or ($cl -match $script:SelfCmdPattern))
}

function Test-IsClaudeProcess($Proc) {
    $n = ([string]$Proc.Name).ToLowerInvariant()
    if ($n -eq 'claude.exe') { return $true }
    return (($n -eq 'node.exe') -and ([string]$Proc.CommandLine -match $script:ClaudeCmdPattern))
}

function Add-Excluded($Excluded, $ById, $Children, [int]$Root, [string]$Why) {
    if (-not $Excluded.ContainsKey($Root)) { $Excluded[$Root] = $Why }
    foreach ($x in (Get-DescendantIds $ById $Children $Root $null)) {
        if (-not $Excluded.ContainsKey([int]$x)) { $Excluded[[int]$x] = $Why }
    }
}

function Get-KillPlan {
    param([int]$ExcludeTree = 0, [int[]]$RootPids = @(), [hashtable]$RootCreated = @{})
    $procs = @(Get-CimInstance -ClassName Win32_Process)
    $byId = @{}
    $children = @{}
    foreach ($p in $procs) {
        $id = [int]$p.ProcessId
        $byId[$id] = $p
        $pp = [int]$p.ParentProcessId
        if (-not $children.ContainsKey($pp)) { $children[$pp] = New-Object System.Collections.ArrayList }
        [void]$children[$pp].Add($p)
    }
    $excluded = @{}
    # Own tree: this process, its ancestors and its own children (git / python helpers).
    Add-Excluded $excluded $byId $children ([int]$PID) 'self'
    foreach ($a in (Get-AncestorIds $byId ([int]$PID))) { $excluded[[int]$a] = 'self-ancestor' }
    if ($ExcludeTree -gt 0) {
        Add-Excluded $excluded $byId $children $ExcludeTree 'exclude-tree'
        foreach ($a in (Get-AncestorIds $byId $ExcludeTree)) { $excluded[[int]$a] = 'exclude-tree-ancestor' }
    }
    # Any copy of this tool (another phase, the detached waiter) and its children.
    foreach ($p in $procs) {
        if ([string]$p.CommandLine -match $script:SelfCmdPattern) { Add-Excluded $excluded $byId $children ([int]$p.ProcessId) 'e_move' }
    }
    $reason = @{}
    $order = New-Object System.Collections.ArrayList
    $roots = New-Object System.Collections.ArrayList
    foreach ($rp in $RootPids) {
        $rp = [int]$rp
        if ($rp -le 4) { continue }
        [void]$roots.Add($rp)
        if ($byId.ContainsKey($rp) -and -not $reason.ContainsKey($rp)) {
            $why = 'task-engine'
            if ($RootCreated.ContainsKey($rp)) {
                $why = 'root-still-alive'
                # Recycled pid of a dead root: a stranger, never a target.
                if ($RootCreated[$rp] -and $byId[$rp].CreationDate -and ($byId[$rp].CreationDate -ne $RootCreated[$rp])) { $why = $null }
            }
            if ($why) { $reason[$rp] = $why; [void]$order.Add($rp) }
        }
    }
    foreach ($p in $procs) {
        $id = [int]$p.ProcessId
        if ((Test-RefsSrc ([string]$p.CommandLine)) -or (Test-RefsSrc ([string]$p.ExecutablePath))) {
            if (-not $reason.ContainsKey($id)) { $reason[$id] = 'references-src'; [void]$order.Add($id) }
            [void]$roots.Add($id)
        }
    }
    $rcDesc = @{}
    foreach ($r in $roots) {
        $rc = $null
        if ($RootCreated.ContainsKey($r)) { $rc = $RootCreated[$r] }
        foreach ($x in (Get-DescendantIds $byId $children ([int]$r) $rc)) {
            $rcDesc[[int]$x] = $true
            if (-not $reason.ContainsKey([int]$x)) { $reason[[int]$x] = ('descendant-of-' + $r); [void]$order.Add([int]$x) }
        }
    }
    # Live Claude sessions keep their whole tree, except -WaitPid's and a session that
    # an RC process started itself (a headless lane is RC work and stops with RC).
    $claudeProtected = 0
    foreach ($p in $procs) {
        if (-not (Test-IsClaudeProcess $p)) { continue }
        $id = [int]$p.ProcessId
        if ($id -eq $script:UnprotectPid -or $rcDesc.ContainsKey($id)) { continue }
        Add-Excluded $excluded $byId $children $id ('claude-session-' + $id)
        $claudeProtected++
    }
    # Processes whose CURRENT DIRECTORY is inside Src/WtSrc hold a handle that blocks the
    # rename even though nothing on their command line names it (tail.exe, grep.exe ...).
    $cwdHits = 0
    $cwdRead = 0
    if (Initialize-CwdReader) {
        foreach ($p in $procs) {
            $id = [int]$p.ProcessId
            if ($id -le 4 -or $reason.ContainsKey($id) -or $excluded.ContainsKey($id)) { continue }
            # Skip protected processes BEFORE any handle is opened (anti-cheat, OS core).
            if (Test-ProtectedProcess $p) { continue }
            $c = Get-ProcessCwd $id
            if (-not $c) { continue }
            $cwdRead++
            if ((Test-UnderPath $c $Src) -or (Test-UnderPath $c $WtSrc)) {
                $reason[$id] = 'cwd-in-src: ' + (Limit-Text $c 120)
                [void]$order.Add($id)
                $cwdHits++
            }
        }
    }
    $kill = New-Object System.Collections.ArrayList
    $skipped = New-Object System.Collections.ArrayList
    foreach ($id in $order) {
        $p = $byId[[int]$id]
        if (-not $p) { continue }
        $cmd = [string]$p.CommandLine
        if (-not $cmd) { $cmd = [string]$p.ExecutablePath }
        $row = [ordered]@{ pid = [int]$id; name = [string]$p.Name; reason = $reason[[int]$id]; cmd = (Limit-Text $cmd 200) }
        $name = ([string]$p.Name).ToLowerInvariant()
        if ($excluded.ContainsKey([int]$id)) { $row['skip'] = $excluded[[int]$id]; [void]$skipped.Add($row); continue }
        if (($script:ProtectNames -contains $name) -or ($name -match $script:NoProbePattern)) { $row['skip'] = 'protected-name'; [void]$skipped.Add($row); continue }
        if ($cmd -match $script:ProtectCmdPattern) { $row['skip'] = 'protected-cmd'; [void]$skipped.Add($row); continue }
        if ($cmd -match $script:SelfCmdPattern) { $row['skip'] = 'protected-e_move'; [void]$skipped.Add($row); continue }
        [void]$kill.Add([pscustomobject]@{ Row = $row; Created = $p.CreationDate })
    }
    return [pscustomobject]@{
        Kill = $kill; Skipped = $skipped; Excluded = $excluded.Count; Scanned = $procs.Count
        CwdRead = $cwdRead; CwdHits = $cwdHits; ClaudeProtected = $claudeProtected
    }
}

function Invoke-KillPlan($Plan) {
    $rows = New-Object System.Collections.ArrayList
    foreach ($k in $Plan.Kill) {
        $row = $k.Row
        $procId = [int]$row['pid']
        if ($DryRun) {
            $row['result'] = 'would-kill'
            Write-Log ('would kill pid {0} {1} ({2}): {3}' -f $procId, $row['name'], $row['reason'], $row['cmd'])
            [void]$rows.Add($row)
            continue
        }
        $cur = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId=' + $procId) -ErrorAction SilentlyContinue
        if (-not $cur) { $row['result'] = 'gone'; [void]$rows.Add($row); continue }
        if ($k.Created -and $cur.CreationDate -and ($cur.CreationDate -ne $k.Created)) {
            $row['result'] = 'pid-reused-skipped'; [void]$rows.Add($row); continue
        }
        $r = Invoke-Exe -File (Join-Path $script:Sys32 'taskkill.exe') -ArgList @('/F', '/PID', [string]$procId)
        if ($r.Code -eq 0) {
            $row['result'] = 'killed'
            $script:KilledPids[$procId] = $k.Created
        } else {
            $row['result'] = 'kill-failed: ' + (Limit-Text (($r.Out + ' ' + $r.Err).Trim()) 160)
        }
        Write-Log ('kill pid {0} {1} ({2}) -> {3}' -f $procId, $row['name'], $row['reason'], $row['result'])
        [void]$rows.Add($row)
    }
    foreach ($s in $Plan.Skipped) {
        if ($s['skip'] -like 'protected*') { Write-Log ('protected, not killed: pid {0} {1}' -f $s['pid'], $s['name']) }
    }
    return , $rows
}

function Invoke-KillPass([string]$Label) {
    $roots = New-Object System.Collections.ArrayList
    foreach ($k in $script:KilledPids.Keys) { [void]$roots.Add([int]$k) }
    $plan = Get-KillPlan -ExcludeTree 0 -RootPids ([int[]]$roots.ToArray([int])) -RootCreated $script:KilledPids
    if ($plan.Kill.Count -gt 0) { Write-Log ('{0}: {1} process(es) still reference Src' -f $Label, $plan.Kill.Count) }
    return , (Invoke-KillPlan $plan)
}

function Get-RunningTaskPids {
    $map = @{}
    try {
        $svc = New-Object -ComObject Schedule.Service
        $svc.Connect()
        foreach ($r in @($svc.GetRunningTasks(1))) { $map[[string]$r.Path] = [int]$r.EnginePID }
    } catch { Write-Log ('running-task query failed: ' + $_.Exception.Message) }
    return $map
}

function Get-RcTasks {
    $out = New-Object System.Collections.ArrayList
    $all = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like 'RC-*' })
    foreach ($t in $all) {
        if ($script:ProtectedTasks -contains $t.TaskName) { continue }
        $hit = $false
        foreach ($a in @($t.Actions)) {
            foreach ($v in @([string]$a.Execute, [string]$a.Arguments, [string]$a.WorkingDirectory)) {
                if (Test-RefsSrc $v) { $hit = $true }
            }
        }
        if ($hit) { [void]$out.Add($t) }
    }
    return , $out
}

function Get-HealthInfo([string]$Root) {
    $p = Join-Path $Root 'ops\runtime\health.json'
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { return $null }
    try { return ((Get-Content -LiteralPath $p -Raw) | ConvertFrom-Json) } catch { return $null }
}

# ---------------------------------------------------------------------------
# Phase 1: Stop
# ---------------------------------------------------------------------------

function Invoke-StopPass([int]$ExcludeTree, [string]$Label) {
    $running = Get-RunningTaskPids
    $tasks = Get-RcTasks
    if (-not $script:State.Contains('stop')) {
        $hp = 0
        $h = Get-HealthInfo $Src
        if ($h -and $h.pid) { $hp = [int]$h.pid }
        $script:State['stop'] = [ordered]@{
            first_at = (Get-Date).ToString('s'); health_pid_before = $hp
            tasks = (New-List); runs = (New-List)
        }
    }
    $stop = $script:State['stop']
    $known = @{}
    foreach ($r in $stop['tasks']) { $known[[string]$r['path'] + [string]$r['name']] = $true }
    $enginePids = New-Object System.Collections.ArrayList
    $newRecords = 0
    foreach ($t in $tasks) {
        $full = $t.TaskPath + $t.TaskName
        $ep = 0
        if ($running.ContainsKey($full)) { $ep = [int]$running[$full]; [void]$enginePids.Add($ep) }
        if (-not $known.ContainsKey($full)) {
            $acts = New-Object System.Collections.ArrayList
            foreach ($a in @($t.Actions)) {
                [void]$acts.Add([ordered]@{ execute = [string]$a.Execute; arguments = [string]$a.Arguments; workdir = [string]$a.WorkingDirectory })
            }
            [void]$stop['tasks'].Add([ordered]@{
                name = $t.TaskName; path = $t.TaskPath; enabled = [bool]$t.Settings.Enabled
                state = [string]$t.State; running = (($ep -gt 0) -or ([string]$t.State -eq 'Running'))
                engine_pid = $ep; actions = $acts
            })
            $known[$full] = $true
            $newRecords++
        }
        Write-Log ('task {0} state={1} enabled={2} engine_pid={3}' -f $full, $t.State, $t.Settings.Enabled, $ep)
    }
    Write-Log ('{0}: tasks matched {1} (new records {2}, recorded total {3})' -f $Label, $tasks.Count, $newRecords, $stop['tasks'].Count)

    # Plan BEFORE ending tasks: a task's engine process is the only link to children
    # that do not name Src themselves (pythonw main.py, -m agents.supervisor). Dead
    # roots (killed earlier, or the exited -WaitPid session) catch their orphans.
    foreach ($k in $script:KilledPids.Keys) { [void]$enginePids.Add([int]$k) }
    $plan = Get-KillPlan -ExcludeTree $ExcludeTree -RootPids ([int[]]$enginePids.ToArray([int])) -RootCreated $script:KilledPids
    Write-Log ('{0}: processes scanned {1}, to kill {2}, excluded {3}, skipped {4}, cwd read {5} (in Src {6}), claude sessions protected {7}' -f $Label, $plan.Scanned, $plan.Kill.Count, $plan.Excluded, $plan.Skipped.Count, $plan.CwdRead, $plan.CwdHits, $plan.ClaudeProtected)

    # Non-RC tasks that still name Src (e.g. the old disabled \RiotCommander task) are
    # listed for the operator and never touched; the junction keeps them working.
    $others = New-Object System.Collections.ArrayList
    foreach ($t in @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -notlike 'RC-*' })) {
        $hit = $false
        foreach ($a in @($t.Actions)) {
            foreach ($v in @([string]$a.Execute, [string]$a.Arguments, [string]$a.WorkingDirectory)) { if (Test-RefsSrc $v) { $hit = $true } }
        }
        if ($hit) {
            [void]$others.Add([ordered]@{ task = $t.TaskPath + $t.TaskName; state = [string]$t.State; action = 'not-repointed (not an RC-* task)' })
            Write-Log ('non-RC task names Src - left untouched, not repointed: {0}{1} ({2})' -f $t.TaskPath, $t.TaskName, $t.State)
        }
    }
    $stop['other_tasks_not_repointed'] = $others

    $disableFailures = New-Object System.Collections.ArrayList
    foreach ($t in $tasks) {
        $full = $t.TaskPath + $t.TaskName
        $isRunning = $running.ContainsKey($full) -or ([string]$t.State -eq 'Running')
        if ($DryRun) {
            $verb = 'already disabled:'
            if ($t.Settings.Enabled) { $verb = 'would disable' }
            Write-Log ('{0} {1}{2}' -f $verb, $full, $(if ($isRunning) { ' and schtasks /End it' } else { '' }))
            continue
        }
        if ($t.Settings.Enabled) {
            try { Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop | Out-Null }
            catch { Write-Log ('disable failed {0}: {1}' -f $full, $_.Exception.Message) }
            # Settings.Enabled is the truth: State stays 'Running' for a running instance
            # of a task that is already disabled.
            $chk = Get-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue
            if ($chk -and -not [bool]$chk.Settings.Enabled) { Write-Log ('disabled ' + $full) }
            else {
                $st = 'missing'
                if ($chk) { $st = 'Settings.Enabled=' + [bool]$chk.Settings.Enabled + ' State=' + [string]$chk.State }
                [void]$disableFailures.Add([ordered]@{ task = $full; state_after = $st })
                Write-Log ('DISABLE DID NOT TAKE: {0} reads {1}' -f $full, $st)
            }
        }
        if ($isRunning) {
            $r = Invoke-Exe -File (Join-Path $script:Sys32 'schtasks.exe') -ArgList @('/End', '/TN', $full)
            Write-Log ('schtasks /End {0} -> {1} {2}' -f $full, $r.Code, (($r.Out + ' ' + $r.Err).Trim()))
        }
    }

    $killed = Invoke-KillPlan $plan
    if (-not $DryRun) {
        for ($i = 0; $i -lt 3; $i++) {
            Start-Sleep -Seconds 2
            $more = Invoke-KillPass ($Label + ' follow-up')
            if ($more.Count -eq 0) { break }
            foreach ($m in $more) { [void]$killed.Add($m) }
        }
    }
    $protected = New-Object System.Collections.ArrayList
    foreach ($s in $plan.Skipped) { if ($s['skip'] -like 'protected*') { [void]$protected.Add($s) } }
    $run = [ordered]@{
        at = (Get-Date).ToString('s'); label = $Label; exclude_tree = $ExcludeTree; dry_run = [bool]$DryRun
        tasks_matched = $tasks.Count; processes = $killed; protected = $protected; excluded = $plan.Excluded
        disable_failures = $disableFailures; cwd_read = $plan.CwdRead; cwd_hits = $plan.CwdHits
        claude_sessions_protected = $plan.ClaudeProtected
    }
    if (-not $DryRun) {
        [void]$stop['runs'].Add($run)
        while ($stop['runs'].Count -gt 20) { $stop['runs'].RemoveAt(0) }
        if ($script:State['status'] -eq 'new') { Set-Status 'stopped' }
        Save-State
    }
    Write-Log ('{0}: {1} process row(s): {2}' -f $Label, $killed.Count, ((@($killed) | ForEach-Object { '' + $_['pid'] + ':' + $_['name'] }) -join ', '))
    return $run
}

function Invoke-StopPhase {
    [void](Invoke-StopPass -ExcludeTree $ExcludeTreeOfPid -Label 'stop')
}

# ---------------------------------------------------------------------------
# Phase 2: Preseed
# ---------------------------------------------------------------------------

function Invoke-PreseedPhase {
    Assert-Distinct
    $srcItem = Get-Item -LiteralPath $Src -Force -ErrorAction SilentlyContinue
    if (-not $srcItem) { throw ('Src not found: ' + $Src) }
    if ($srcItem.LinkType) { Write-Log 'Src is already a link (cut over) - nothing to preseed'; return }
    # robocopy /E never deletes, so a destination this tool did not create keeps files
    # Src no longer has (stale modules, deleted tests). Refuse unless told otherwise.
    $foreign = @()
    if (-not ($script:State.Contains('preseed'))) {
        foreach ($d in @($Dst, $WtDst)) { if (Test-Path -LiteralPath $d) { $foreign += $d } }
    }
    if ($foreign.Count -gt 0) {
        $msg = 'destination already exists and was not created by this tool: ' + ($foreign -join '; ') + ' - move it aside first, or pass -AllowExistingDst to copy over it (extras are never purged)'
        if ($AllowExistingDst) { Write-Log ('WARNING ' + $msg) }
        elseif ($DryRun) { Write-Log ('WOULD REFUSE: ' + $msg) }
        else { throw $msg }
    }
    $roots = @($Src)
    if (Test-Path -LiteralPath $WtSrc -PathType Container) { $roots += $WtSrc }
    $hargs = @('scan-reparse') + (Get-MapArgs)
    foreach ($r in $roots) { $hargs += @('--root', $r) }
    $scan = Invoke-Helper $hargs
    $st = $scan['stats']
    Write-Log ('scan: dirs {0} files {1} bytes {2} reparse {3} errors {4}' -f $st['dirs'], $st['files'], $st['bytes'], $scan['reparse'].Count, $scan['error_count'])
    $pre = [ordered]@{
        started_at = (Get-Date).ToString('s'); stats = $st; reparse = $scan['reparse']
        robocopy = (New-List); relinked = (New-List); external_links = (New-List); ok = $false
    }
    foreach ($rp in $scan['reparse']) {
        if ($rp['dst_link']) { Write-Log ('link inside: {0} -> {1} ({2}) will become {3} -> {4}' -f $rp['path'], $rp['target'], $rp['kind'], $rp['dst_link'], $rp['dst_target']) }
        else { Write-Log ('link outside or unknown, reported only: {0} -> {1} ({2})' -f $rp['path'], $rp['target'], $rp['kind']); [void]$pre['external_links'].Add($rp) }
    }
    $opts = @('/E', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1', '/MT:16', '/NP', '/NFL', '/NDL', '/XJ') + $script:OwnFilesXf
    $ok = $true
    $pairs = New-Object System.Collections.ArrayList
    [void]$pairs.Add(@{ From = $Src; To = $Dst })
    if (Test-Path -LiteralPath $WtSrc -PathType Container) { [void]$pairs.Add(@{ From = $WtSrc; To = $WtDst }) }
    foreach ($pr in $pairs) {
        $rc = Invoke-Robocopy $pr.From $pr.To $opts
        [void]$pre['robocopy'].Add([ordered]@{ src = $pr.From; dst = $pr.To; exit = $rc.Code; ok = $rc.Ok })
        if (-not $rc.Ok) { $ok = $false }
    }
    if (-not $DryRun) { Initialize-Log }
    foreach ($rp in $scan['reparse']) {
        if (-not $rp['dst_link']) { continue }
        $row = [ordered]@{ link = $rp['dst_link']; target = $rp['dst_target']; kind = $rp['kind'] }
        if ($DryRun) { $row['action'] = 'would-create'; [void]$pre['relinked'].Add($row); continue }
        $existing = Get-Item -LiteralPath $rp['dst_link'] -Force -ErrorAction SilentlyContinue
        if ($existing) {
            if ($existing.LinkType) { $row['action'] = 'exists' } else { $row['action'] = 'blocked-by-real-item'; $ok = $false }
        } else {
            $parent = Split-Path -Parent $rp['dst_link']
            if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            $r = New-Link $rp['kind'] $rp['dst_link'] $rp['dst_target']
            $row['action'] = 'created'
            $row['code'] = $r.Code
            if ($r.Code -ne 0) { $row['action'] = 'failed: ' + (Limit-Text (($r.Out + ' ' + $r.Err).Trim()) 160); $ok = $false }
        }
        Write-Log ('relink {0} -> {1}: {2}' -f $row['link'], $row['target'], $row['action'])
        [void]$pre['relinked'].Add($row)
    }
    $pre['finished_at'] = (Get-Date).ToString('s')
    $pre['ok'] = ($ok -and -not $DryRun)
    if (-not $DryRun) {
        $script:State['preseed'] = $pre
        # A re-copy can overwrite Dst-side rewrites with Src originals, so any earlier
        # RepointInternal result no longer holds; Cutover refuses until it is re-run.
        if ($script:State.Contains('repoint')) {
            $script:State['repoint']['ok'] = $false
            $script:State['repoint']['invalidated_by'] = 'preseed rerun ' + (Get-Date).ToString('s')
        }
        if ($ok) { Set-Status 'preseeded' } else { Set-Status 'preseed_failed' }
        Save-State
    }
    if ($DryRun) { Write-Log 'preseed dry run: nothing copied, nothing recorded' } else { Write-Log ('preseed ok={0}' -f $ok) }
}

# ---------------------------------------------------------------------------
# Phase 3: RepointInternal (Dst only)
# ---------------------------------------------------------------------------

function Get-WorktreeDirs {
    $paths = New-Object System.Collections.ArrayList
    foreach ($base in @((Join-Path $Dst '.claude\worktrees'), $WtDst)) {
        if (-not (Test-Path -LiteralPath $base -PathType Container)) { continue }
        foreach ($d in @(Get-ChildItem -LiteralPath $base -Directory -Force -ErrorAction SilentlyContinue)) {
            if (Test-Path -LiteralPath (Join-Path $d.FullName '.git') -PathType Leaf) { [void]$paths.Add($d.FullName) }
        }
    }
    return , $paths
}

function Invoke-SafeDirectory {
    $paths = New-Object System.Collections.ArrayList
    [void]$paths.Add($Dst)
    foreach ($p in (Get-WorktreeDirs)) { [void]$paths.Add($p) }
    $cfg = Invoke-Exe -File $script:Git -ArgList @('config', '--global', '--get-all', 'safe.directory')
    $existing = @(($cfg.Out -split "`n") | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
    $entries = New-Object System.Collections.ArrayList
    foreach ($p in $paths) {
        $r = Invoke-Exe -File $script:Git -ArgList @('-C', $p, 'rev-parse', '--git-dir')
        if ($r.Err -notmatch 'dubious ownership') { continue }
        $fwd = $p -replace '\\', '/'
        $row = [ordered]@{ path = $fwd; action = '' }
        if (($existing -contains $fwd.ToLowerInvariant()) -or ($existing -contains '*')) { $row['action'] = 'already' }
        elseif ($DryRun) { $row['action'] = 'would-add' }
        else {
            $a = Invoke-Exe -File $script:Git -ArgList @('config', '--global', '--add', 'safe.directory', $fwd)
            if ($a.Code -eq 0) { $row['action'] = 'added' } else { $row['action'] = 'add-failed: ' + $a.Err.Trim() }
        }
        Write-Log ('safe.directory {0}: {1}' -f $fwd, $row['action'])
        [void]$entries.Add($row)
    }
    Write-Log ('safe.directory: checked {0}, dubious {1}' -f $paths.Count, $entries.Count)
    return [ordered]@{ checked = $paths.Count; dubious = $entries.Count; entries = $entries }
}

function Invoke-HooksPath {
    $r = Invoke-Exe -File $script:Git -ArgList @('-C', $Dst, 'config', '--local', '--get', 'core.hooksPath')
    $cur = $r.Out.Trim()
    $res = [ordered]@{ before = $cur; after = $cur; action = 'unset'; refs_src = $false }
    if (-not $cur) { Write-Log 'core.hooksPath: not set locally'; return $res }
    $res['refs_src'] = (Test-RefsSrc $cur)
    $new = Convert-PathText $cur
    $res['after'] = $new
    if ($new -ceq $cur) { $res['action'] = 'no-change' }
    elseif ($DryRun) { $res['action'] = 'would-set' }
    else {
        [void](Invoke-Exe -File $script:Git -ArgList @('-C', $Dst, 'config', '--local', 'core.hooksPath', $new))
        $v = (Invoke-Exe -File $script:Git -ArgList @('-C', $Dst, 'config', '--local', '--get', 'core.hooksPath')).Out.Trim()
        if ($v -ceq $new) { $res['action'] = 'set' } else { $res['action'] = 'set-failed (reads ' + $v + ')' }
    }
    Write-Log ('core.hooksPath: {0} -> {1} [{2}] refs_src={3}' -f $cur, $new, $res['action'], $res['refs_src'])
    return $res
}

function Invoke-WorktreeRepair($Links) {
    $res = [ordered]@{ action = ''; detail = '' }
    $extLive = @($Links['external_worktrees'] | Where-Object { $_['exists'] })
    if ($extLive.Count -gt 0) {
        # repair walks EVERY registered worktree and rewrites its .git pointer back to
        # this repo - from Dst that would steal a live C: worktree before cutover.
        $res['action'] = 'skipped'
        $res['detail'] = 'registered worktrees outside Dst/WtDst exist on disk: ' + ((@($extLive) | ForEach-Object { $_['worktree'] }) -join '; ')
        Write-Log ('worktree repair skipped: ' + $res['detail'])
        return $res
    }
    $paths = @($Links['internal_worktrees'] | Where-Object { $_['exists'] } | ForEach-Object { [string]$_['worktree'] })
    if ($DryRun) {
        $res['action'] = 'would-run'
        $res['detail'] = 'git -C Dst worktree repair with {0} path(s)' -f $paths.Count
        Write-Log $res['detail']
        return $res
    }
    $r = Invoke-Exe -File $script:Git -ArgList (@('-C', $Dst, 'worktree', 'repair') + $paths)
    $res['action'] = 'ran'
    $res['code'] = $r.Code
    $res['detail'] = Limit-Text (($r.Out + ' ' + $r.Err).Trim()) 600
    Write-Log ('worktree repair exit {0}: {1}' -f $r.Code, $res['detail'])
    return $res
}

function Test-WorktreeList {
    $r = Invoke-Exe -File $script:Git -ArgList @('-C', $Dst, 'worktree', 'list', '--porcelain')
    $missing = New-Object System.Collections.ArrayList
    $count = 0
    foreach ($line in ($r.Out -split "`n")) {
        $l = $line.Trim()
        if (-not $l.StartsWith('worktree ')) { continue }
        $count++
        $p = $l.Substring(9)
        if (-not (Test-Path -LiteralPath ($p -replace '/', '\') -PathType Container)) { [void]$missing.Add($p) }
    }
    Write-Log ('worktree list: {0} path(s), {1} missing{2}' -f $count, $missing.Count, $(if ($missing.Count) { ': ' + ($missing -join '; ') } else { '' }))
    return [ordered]@{ code = $r.Code; count = $count; missing = $missing }
}

function Get-ClaudeProjectKey([string]$Path) { return ($Path -replace '[^A-Za-z0-9]', '-') }

function Copy-ClaudeMemory {
    $res = New-Object System.Collections.ArrayList
    $srcKey = Get-ClaudeProjectKey $Src
    $dstKey = Get-ClaudeProjectKey $Dst
    foreach ($cfg in @('.claude-acct2', '.claude')) {
        $base = Join-Path (Join-Path $UserHome $cfg) 'projects'
        $from = Join-Path (Join-Path $base $srcKey) 'memory'
        $to = Join-Path (Join-Path $base $dstKey) 'memory'
        $row = [ordered]@{ config = $cfg; from = $from; to = $to; action = '' }
        if (-not (Test-Path -LiteralPath $from -PathType Container)) { $row['action'] = 'absent' }
        else {
            $row['files'] = @(Get-ChildItem -LiteralPath $from -Recurse -File -Force -ErrorAction SilentlyContinue).Count
            if ($srcKey -eq $dstKey) { $row['action'] = 'same-dir' }
            elseif ($DryRun) { $row['action'] = 'would-copy' }
            else {
                $rc = Invoke-Robocopy $from $to @('/E', '/XO', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1', '/NP', '/NFL', '/NDL')
                $row['exit'] = $rc.Code
                if ($rc.Ok) { $row['action'] = 'copied' } else { $row['action'] = 'copy-failed' }
            }
        }
        Write-Log ('claude memory {0}: {1} files={2} -> {3}' -f $cfg, $row['action'], $row['files'], $to)
        [void]$res.Add($row)
    }
    return , $res
}

function Invoke-RepointInternal([switch]$FromCutover) {
    if (-not $DryRun) {
        Assert-Distinct
        if (-not (Test-Path -LiteralPath (Join-Path $Dst '.git') -PathType Container)) { throw ('Dst has no .git directory - run Preseed first: ' + $Dst) }
    }
    $rep = [ordered]@{ started_at = (Get-Date).ToString('s'); ok = $false }
    $backupRoot = Join-Path $Dst $script:BackupRel
    $problems = New-Object System.Collections.ArrayList

    # (e) first: git refuses every later step in a dubious-ownership repo.
    $rep['safe_directory'] = Invoke-SafeDirectory

    # (a) core.hooksPath
    $rep['hooks_path'] = Invoke-HooksPath
    if ($rep['hooks_path']['action'] -like 'set-failed*') { [void]$problems.Add('hooksPath') }

    # (b) worktree link files, then repair + existence check
    $hargs = @('repoint-gitdirs') + (Get-MapArgs) + @('--repo', $Dst, '--wt-root', $WtDst, '--backup-root', $backupRoot)
    if ($DryRun) { $hargs += '--dry-run' }
    $links = Invoke-Helper $hargs
    foreach ($f in $links['rewritten']) { Write-Log ('gitlink {0}: {1} literal(s)' -f $f['path'], $f['count']) }
    foreach ($e in $links['external_worktrees']) { Write-Log ('worktree registered outside Dst/WtDst (left as-is): {0} exists={1}' -f $e['worktree'], $e['exists']) }
    foreach ($d in $links['dangling_pointers']) { Write-Log ('dangling .git pointer: {0} -> {1}' -f $d['pointer'], $d['gitdir']) }
    Write-Log ('gitlinks: files {0}, rewritten {1}, internal worktrees {2}, external {3}, dangling {4}, errors {5}' -f $links['files'], $links['rewritten'].Count, $links['internal_worktrees'].Count, $links['external_worktrees'].Count, $links['dangling_pointers'].Count, $links['errors'].Count)
    if ($links['errors'].Count -gt 0) { [void]$problems.Add('gitlinks') }
    $rep['gitlinks'] = [ordered]@{
        files = $links['files']; rewritten = $links['rewritten'].Count; internal = $links['internal_worktrees'].Count
        external = $links['external_worktrees']; dangling = $links['dangling_pointers']; errors = $links['errors']
    }
    $rep['repair'] = Invoke-WorktreeRepair $links
    $rep['worktree_check'] = Test-WorktreeList

    # (c) untracked / ignored config files
    $hargs = @('repoint-configs') + (Get-MapArgs) + @('--repo', $Dst, '--backup-root', $backupRoot)
    if ($DryRun) { $hargs += '--dry-run' }
    $cfg = Invoke-Helper $hargs
    foreach ($m in $cfg['matched']) { Write-Log ('config {0}: {1} literal(s) [{2}]' -f $m['path'], $m['count'], $m['kind']) }
    foreach ($e in $cfg['errors']) { Write-Log ('config error {0}: {1}' -f $e['path'], $e['error']) }
    Write-Log ('configs: untracked listed {0}, candidates {1}, matched {2}, errors {3}' -f $cfg['listed'], $cfg['candidates'], $cfg['matched'].Count, $cfg['errors'].Count)
    if ($cfg['errors'].Count -gt 0) { [void]$problems.Add('configs') }
    $rep['configs'] = [ordered]@{ listed = $cfg['listed']; candidates = $cfg['candidates']; matched = $cfg['matched']; errors = $cfg['errors'] }

    # (d) Claude Code project memory
    $rep['memory'] = Copy-ClaudeMemory
    foreach ($m in $rep['memory']) { if ($m['action'] -eq 'copy-failed') { [void]$problems.Add('memory') } }

    $rep['problems'] = $problems
    $rep['ok'] = (($problems.Count -eq 0) -and -not $DryRun)
    $rep['finished_at'] = (Get-Date).ToString('s')
    if ($DryRun) { Write-Log ('repoint dry run: nothing written; problems={0}' -f ($problems -join ',')) }
    else { Write-Log ('repoint ok={0} problems={1}' -f $rep['ok'], ($problems -join ',')) }
    if (-not $DryRun) {
        if ($FromCutover) { $script:State['cutover']['repoint'] = $rep }
        else {
            $script:State['repoint'] = $rep
            if ($rep['ok']) { Set-Status 'repointed' } else { Set-Status 'repoint_failed' }
        }
        Save-State
    }
    return $rep
}

# ---------------------------------------------------------------------------
# Phase 4: Cutover
# ---------------------------------------------------------------------------

function Get-DirState([string]$Path, [string]$Expect) {
    $it = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $it) { return 'missing' }
    if (-not $it.LinkType) { return 'real' }
    $target = (@($it.Target) -join ';').TrimEnd('\')
    if ($target.StartsWith('\\?\')) { $target = $target.Substring(4) }
    if ($it.LinkType -eq 'Junction' -and ($target.ToLowerInvariant() -eq $Expect.ToLowerInvariant())) { return 'junction-ok' }
    return 'link-other'
}

function Get-AsidePath([string]$Path) {
    $base = '{0}.pre-E-move-{1}' -f $Path, (Get-Date -Format 'yyyyMMdd')
    if (-not (Test-Path -LiteralPath $base)) { return $base }
    return ('{0}-{1}' -f $base, (Get-Date -Format 'HHmmss'))
}

function Rename-DirWithRetry([string]$Path, [string]$NewPath, [int]$Minutes) {
    $deadline = (Get-Date).AddMinutes($Minutes)
    $attempt = 0
    while ($true) {
        $attempt++
        try {
            Rename-Item -LiteralPath $Path -NewName (Split-Path -Leaf $NewPath) -ErrorAction Stop
            Write-Log ('renamed {0} -> {1} (attempt {2})' -f $Path, $NewPath, $attempt)
            return $true
        } catch { Write-Log ('rename {0} attempt {1} failed: {2}' -f $Path, $attempt, $_.Exception.Message) }
        if ((Get-Date) -ge $deadline) { return $false }
        # A failing kill pass must never abort the retry loop (or a rollback that uses it).
        try { [void](Invoke-KillPass 'rename-retry') } catch { Write-Log ('kill pass during rename retry failed: ' + $_.Exception.Message) }
        Start-Sleep -Seconds 15
    }
}

function Remove-JunctionOnly([string]$Path) {
    $it = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($it -and $it.LinkType -eq 'Junction') {
        # rmdir without /s on a junction removes the link, never the target's content.
        $r = Invoke-Exe -File (Join-Path $script:Sys32 'cmd.exe') -RawArgs ('/c rmdir ' + (Format-Arg $Path))
        Write-Log ('removed junction {0} (exit {1})' -f $Path, $r.Code)
        return ($r.Code -eq 0)
    }
    return $false
}

function New-VerifiedJunction([string]$Link, [string]$Target, [string]$Probe) {
    $r = New-Link 'junction' $Link $Target
    $it = Get-Item -LiteralPath $Link -Force -ErrorAction SilentlyContinue
    $ok = $false
    if ($it -and $it.LinkType -eq 'Junction') {
        if ($Probe) { $ok = Test-Path -LiteralPath (Join-Path $Link $Probe) } else { $ok = $true }
    }
    Write-Log ('junction {0} -> {1}: exit {2} ok={3} probe={4}' -f $Link, $Target, $r.Code, $ok, $Probe)
    return [ordered]@{ link = $Link; target = $Target; code = $r.Code; ok = $ok; probe = $Probe; out = (Limit-Text (($r.Out + ' ' + $r.Err).Trim()) 200) }
}

function Get-TaskRecords {
    if ($script:State.Contains('stop') -and $script:State['stop']['tasks'].Count -gt 0) { return , $script:State['stop']['tasks'] }
    $list = New-Object System.Collections.ArrayList
    foreach ($t in (Get-RcTasks)) {
        [void]$list.Add([ordered]@{ name = $t.TaskName; path = $t.TaskPath; enabled = [bool]$t.Settings.Enabled; state = [string]$t.State; running = ([string]$t.State -eq 'Running') })
    }
    return , $list
}

function Restart-RecordedTasks {
    $res = New-Object System.Collections.ArrayList
    foreach ($rec in (Get-TaskRecords)) {
        $name = [string]$rec['name']
        $path = [string]$rec['path']
        $full = $path + $name
        $row = [ordered]@{ task = $full; enabled = $false; started = $false }
        if ($DryRun) {
            Write-Log ('would re-enable={0} run={1}: {2}' -f $rec['enabled'], $rec['running'], $full)
            [void]$res.Add($row)
            continue
        }
        if ($rec['enabled']) {
            try { Enable-ScheduledTask -TaskName $name -TaskPath $path -ErrorAction Stop | Out-Null; $row['enabled'] = $true }
            catch { $row['enable_error'] = $_.Exception.Message }
        }
        if ($rec['running']) {
            $r = Invoke-Exe -File (Join-Path $script:Sys32 'schtasks.exe') -ArgList @('/Run', '/TN', $full)
            $row['started'] = ($r.Code -eq 0)
            if ($r.Code -ne 0) { $row['run_error'] = Limit-Text (($r.Out + ' ' + $r.Err).Trim()) 160 }
        }
        Write-Log ('restart {0}: enabled={1} started={2}' -f $full, $row['enabled'], $row['started'])
        [void]$res.Add($row)
    }
    return , $res
}

function Update-RecordedTasks {
    $res = New-Object System.Collections.ArrayList
    $bdir = Join-Path $Dst ($script:BackupRel + '\tasks')
    if (-not $DryRun -and -not (Test-Path -LiteralPath $bdir)) { New-Item -ItemType Directory -Path $bdir -Force | Out-Null }
    foreach ($rec in (Get-TaskRecords)) {
        $name = [string]$rec['name']
        $path = [string]$rec['path']
        $full = $path + $name
        $row = [ordered]@{ task = $full; ok = $false; fields_changed = 0 }
        try {
            $t = Get-ScheduledTask -TaskName $name -TaskPath $path -ErrorAction Stop
            $bfile = Join-Path $bdir (($full.Trim('\') -replace '[\\/:*?"<>|]', '_') + '.xml')
            $row['backup'] = $bfile
            if (-not $DryRun -and -not (Test-Path -LiteralPath $bfile)) {
                $xml = Export-ScheduledTask -TaskName $name -TaskPath $path
                [System.IO.File]::WriteAllText($bfile, $xml, [System.Text.Encoding]::Unicode)
            }
            $acts = @($t.Actions)
            $changed = 0
            foreach ($a in $acts) {
                foreach ($prop in @('Execute', 'Arguments', 'WorkingDirectory')) {
                    $v = [string]$a.$prop
                    if (-not $v) { continue }
                    $nv = Convert-PathText $v
                    if ($nv -cne $v) {
                        $changed++
                        if ($DryRun) { Write-Log ('would set {0}.{1}: {2}' -f $full, $prop, $nv) } else { $a.$prop = $nv }
                    }
                }
            }
            $row['fields_changed'] = $changed
            if ($DryRun) { $row['ok'] = $true }
            else {
                if ($changed -gt 0) { Set-ScheduledTask -TaskName $name -TaskPath $path -Action $acts -ErrorAction Stop | Out-Null }
                $t2 = Get-ScheduledTask -TaskName $name -TaskPath $path -ErrorAction Stop
                $left = 0
                foreach ($a in @($t2.Actions)) {
                    foreach ($v in @([string]$a.Execute, [string]$a.Arguments, [string]$a.WorkingDirectory)) { if (Test-RefsSrc $v) { $left++ } }
                }
                $row['ok'] = ($left -eq 0)
                $row['src_refs_left'] = $left
            }
        } catch { $row['error'] = $_.Exception.Message }
        Write-Log ('task repoint {0}: changed {1} ok={2} {3}' -f $full, $row['fields_changed'], $row['ok'], $row['error'])
        [void]$res.Add($row)
    }
    return , $res
}

function Update-Shortcuts {
    $res = New-Object System.Collections.ArrayList
    $public = $env:PUBLIC
    if (-not $public) { $public = Join-Path (Split-Path -Parent $UserHome) 'Public' }
    $candidates = @(
        (Join-Path $UserHome 'Desktop'),
        [System.Environment]::GetFolderPath('Desktop'),
        (Join-Path $public 'Desktop'),
        (Join-Path $UserHome 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'),
        (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs')
    )
    $roots = New-Object System.Collections.ArrayList
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        if (-not (Test-Path -LiteralPath $c -PathType Container)) { continue }
        $n = (Get-NormPath $c).ToLowerInvariant()
        if (-not ($roots | Where-Object { $_.ToLowerInvariant() -eq $n })) { [void]$roots.Add((Get-NormPath $c)) }
    }
    $shell = New-Object -ComObject WScript.Shell
    $bdir = Join-Path $Dst ($script:BackupRel + '\shortcuts')
    foreach ($root in $roots) {
        foreach ($f in @(Get-ChildItem -LiteralPath $root -Filter '*.lnk' -Recurse -File -Force -ErrorAction SilentlyContinue)) {
            $sc = $null
            try { $sc = $shell.CreateShortcut($f.FullName) } catch { continue }
            $hit = (Test-RefsSrc $sc.TargetPath) -or (Test-RefsSrc $sc.Arguments) -or (Test-RefsSrc $sc.WorkingDirectory)
            if (-not $hit) { continue }
            $row = [ordered]@{ lnk = $f.FullName; target_before = $sc.TargetPath; target_after = (Convert-PathText $sc.TargetPath); ok = $false }
            if ($DryRun) {
                $row['ok'] = $true
                Write-Log ('would repoint shortcut {0}: {1} -> {2}' -f $f.FullName, $row['target_before'], $row['target_after'])
                [void]$res.Add($row)
                continue
            }
            try {
                if (-not (Test-Path -LiteralPath $bdir)) { New-Item -ItemType Directory -Path $bdir -Force | Out-Null }
                $b = Join-Path $bdir ($f.FullName -replace '[:\\/]', '_')
                if (-not (Test-Path -LiteralPath $b)) { Copy-Item -LiteralPath $f.FullName -Destination $b -Force }
                $row['backup'] = $b
                foreach ($prop in @('TargetPath', 'Arguments', 'WorkingDirectory', 'IconLocation')) {
                    $v = [string]$sc.$prop
                    if (-not $v) { continue }
                    $nv = Convert-PathText $v
                    if ($nv -cne $v) { $sc.$prop = $nv }
                }
                $sc.Save()
                $sc2 = $shell.CreateShortcut($f.FullName)
                $row['ok'] = -not ((Test-RefsSrc $sc2.TargetPath) -or (Test-RefsSrc $sc2.Arguments) -or (Test-RefsSrc $sc2.WorkingDirectory))
                $row['target_after'] = $sc2.TargetPath
            } catch { $row['error'] = $_.Exception.Message }
            Write-Log ('shortcut {0}: {1} -> {2} ok={3}' -f $f.FullName, $row['target_before'], $row['target_after'], $row['ok'])
            [void]$res.Add($row)
        }
    }
    return , $res
}

function Update-ClaudeJson {
    $hargs = @('clone-project-keys') + (Get-MapArgs) + @('--backup-dir', (Join-Path $Dst ($script:BackupRel + '\claude_json')))
    foreach ($f in @((Join-Path $UserHome '.claude-acct2\.claude.json'), (Join-Path $UserHome '.claude.json'))) { $hargs += @('--file', $f) }
    if ($DryRun) { $hargs += '--dry-run' }
    $r = Invoke-Helper $hargs
    foreach ($f in $r['files']) {
        $acts = @($f['actions'] | ForEach-Object { '{0} -> {1} [{2}]' -f $_['from'], $_['to'], $_['action'] })
        Write-Log ('claude.json {0}: written={1} {2} {3}' -f $f['file'], $f['written'], ($acts -join '; '), $f['error'])
    }
    return $r
}

function Test-RcHealth([int]$Seconds) {
    $before = 0
    if ($script:State.Contains('stop')) { $before = [int]$script:State['stop']['health_pid_before'] }
    $hp = Join-Path $Dst 'ops\runtime\health.json'
    $deadline = (Get-Date).AddSeconds($Seconds)
    $res = [ordered]@{ ok = $false; pid_before = $before; pid = 0; alive = $false; ports = @() }
    while ($true) {
        $h = $null
        try { $h = (Get-Content -LiteralPath $hp -Raw -ErrorAction Stop) | ConvertFrom-Json } catch { $h = $null }
        if ($h) { $res['pid'] = [int]$h.pid; $res['alive'] = ($h.alive -eq $true) }
        $ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { @(8888, 8889, 8860) -contains [int]$_.LocalPort } | ForEach-Object { [int]$_.LocalPort } | Sort-Object -Unique)
        $res['ports'] = $ports
        $live = $false
        if ($res['pid'] -gt 0) { $live = $null -ne (Get-Process -Id $res['pid'] -ErrorAction SilentlyContinue) }
        $pidOk = ($res['pid'] -gt 0) -and ($res['pid'] -ne $before) -and $res['alive'] -and $live
        if ($pidOk -and $ports.Count -eq 3) { $res['ok'] = $true; break }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Seconds 5
    }
    $res['checked_at'] = (Get-Date).ToString('s')
    Write-Log ('verify: ok={0} pid={1} (before {2}) alive={3} ports={4}' -f $res['ok'], $res['pid'], $before, $res['alive'], ($res['ports'] -join ','))
    return $res
}

function Wait-ForPid([int]$WaitFor) {
    if ($WaitFor -le 0) { Write-Log 'no -WaitPid given - not waiting'; return }
    $p = Get-Process -Id $WaitFor -ErrorAction SilentlyContinue
    if (-not $p) { Write-Log ('wait pid {0} is not running' -f $WaitFor); return }
    $start = $null
    try { $start = $p.StartTime } catch { $start = $null }
    if ($DryRun) { Write-Log ('wait pid {0} ({1}) is alive; a real run polls every 10 s with no timeout' -f $WaitFor, $p.ProcessName); return }
    Write-Log ('waiting for pid {0} ({1}) to exit' -f $WaitFor, $p.ProcessName)
    $n = 0
    while ($true) {
        Start-Sleep -Seconds 10
        $n++
        $p = Get-Process -Id $WaitFor -ErrorAction SilentlyContinue
        if (-not $p) { break }
        if ($start) {
            $s2 = $null
            try { $s2 = $p.StartTime } catch { $s2 = $null }
            if ($s2 -and ($s2 -ne $start)) { break }
        }
        if (($n % 60) -eq 0) { Write-Log ('still waiting for pid ' + $WaitFor) }
    }
    Write-Log ('pid {0} exited' -f $WaitFor)
    Start-Sleep -Seconds 5
}

function Invoke-Rollback([string]$Reason) {
    Write-Log ('ROLLBACK: ' + $Reason)
    $rb = [ordered]@{ at = (Get-Date).ToString('s'); reason = $Reason; steps = (New-List); anomalies = (New-List) }
    # WtSrc first: it was moved last, so it is undone first.
    $pairs = @(
        @{ Key = 'wt'; Orig = $WtSrc; Target = $WtDst; Aside = $script:WtAside },
        @{ Key = 'src'; Orig = $Src; Target = $Dst; Aside = $script:SrcAside }
    )
    foreach ($pair in $pairs) {
        $k = $pair.Key
        $o = $pair.Orig
        $a = $pair.Aside
        # Directories are only touched when THIS run (or the crashed run it resumes) moved them.
        if ($DryRun -or -not ($script:Renamed[$k] -or $script:Junctioned[$k])) { continue }
        $st = Get-DirState $o $pair.Target
        if ($st -eq 'junction-ok') {
            if (Remove-JunctionOnly $o) { [void]$rb['steps'].Add('removed junction ' + $o) }
            else { [void]$rb['anomalies'].Add('could not remove the junction at ' + $o); continue }
        } elseif ($st -eq 'link-other') {
            [void]$rb['anomalies'].Add($o + ' is a link to somewhere other than ' + $pair.Target); continue
        }
        if (-not $script:Renamed[$k]) { continue }
        $asideThere = $a -and (Test-Path -LiteralPath $a -PathType Container)
        $st = Get-DirState $o $pair.Target
        if ($st -eq 'real' -and $asideThere) {
            # Something recreated the C: path after the rename: two trees, nobody may guess.
            [void]$rb['anomalies'].Add(('{0} is a REAL directory again while the renamed original {1} still exists - two trees, merge by hand' -f $o, $a))
        } elseif ($st -eq 'missing') {
            if (-not $asideThere) { [void]$rb['anomalies'].Add(('{0} is missing and the renamed original {1} is gone' -f $o, $a)) }
            else {
                $ok = Rename-DirWithRetry $a $o 5
                $after = Get-DirState $o $pair.Target
                [void]$rb['steps'].Add(('rename back {0} -> {1}: {2} (now {3})' -f $a, $o, $ok, $after))
                if (-not $ok -or $after -ne 'real' -or (Test-Path -LiteralPath $a)) {
                    [void]$rb['anomalies'].Add(('could not restore {0} from {1} (state {2})' -f $o, $a, $after))
                }
            }
        }
        # The C: path must never end up missing: if the original could not come back,
        # put the junction to E: back so every C: literal still resolves.
        if ((Get-DirState $o $pair.Target) -eq 'missing' -and (Test-Path -LiteralPath $pair.Target -PathType Container)) {
            $probe = $null
            if ($k -eq 'src') { $probe = 'CLAUDE.md' }
            $j = New-VerifiedJunction $o $pair.Target $probe
            [void]$rb['steps'].Add(('re-created junction {0} -> {1}: ok={2}' -f $o, $pair.Target, $j['ok']))
            [void]$rb['anomalies'].Add(('{0} could not be restored, so the junction to {1} was re-created (ok={2}); the original is at {3}' -f $o, $pair.Target, $j['ok'], $a))
        }
    }
    $srcState = Get-DirState $Src $Dst
    $rb['src_state'] = $srcState
    if ($rb['anomalies'].Count -eq 0 -and $srcState -eq 'real') {
        $rb['tasks'] = Restart-RecordedTasks
        Set-Status 'rolled_back'
    } else {
        # Never start anything while the trees are ambiguous: that would split the data.
        [void]$rb['steps'].Add('NOTHING restarted: tasks stay disabled until the operator resolves the anomalies')
        foreach ($an in $rb['anomalies']) { Write-Log ('ANOMALY: ' + $an) }
        Set-Status 'needs_operator'
    }
    $script:State['cutover']['result'] = $script:State['status']
    $script:State['cutover']['reason'] = $Reason
    $script:State['cutover']['rollback'] = $rb
    Save-State
}

function Get-LiveWaiters {
    # Other copies of this tool running Cutover (never this process or its ancestors).
    $mine = @{}
    $mine[[int]$PID] = $true
    $all = @(Get-CimInstance -ClassName Win32_Process)
    $byId = @{}
    foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
    foreach ($a in (Get-AncestorIds $byId ([int]$PID))) { $mine[[int]$a] = $true }
    $out = New-Object System.Collections.ArrayList
    foreach ($p in $all) {
        $cl = [string]$p.CommandLine
        if ($mine.ContainsKey([int]$p.ProcessId)) { continue }
        if (($cl -match $script:WaiterCmdPattern) -and ($cl -notmatch '(?i)-Detach')) { [void]$out.Add([int]$p.ProcessId) }
    }
    return , $out
}

function Sync-MigrateScripts {
    # The waiter runs the E: copy, so it must be byte-identical to the reviewed C: copy.
    $from = Join-Path $Src 'ops\migrate'
    $to = Join-Path $Dst 'ops\migrate'
    $res = [ordered]@{ files = 0; mismatched = (New-List); copied = $false }
    if ((Get-DirState $Src $Dst) -eq 'junction-ok') { Write-Log 'script sync: Src is already the junction - same files'; return $res }
    $files = @(Get-ChildItem -LiteralPath $from -File -Force -ErrorAction Stop)
    $res['files'] = $files.Count
    if (-not $DryRun) {
        if (-not (Test-Path -LiteralPath $to -PathType Container)) { New-Item -ItemType Directory -Path $to -Force | Out-Null }
        foreach ($f in $files) { Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $to $f.Name) -Force }
        $res['copied'] = $true
    }
    foreach ($f in $files) {
        $h1 = (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash
        $t = Join-Path $to $f.Name
        $h2 = ''
        if (Test-Path -LiteralPath $t -PathType Leaf) { $h2 = (Get-FileHash -Algorithm SHA256 -LiteralPath $t).Hash }
        if ($h1 -ne $h2) { [void]$res['mismatched'].Add($f.Name) }
    }
    Write-Log ('script sync {0} -> {1}: {2} file(s), sha256 mismatches {3} {4}' -f $from, $to, $files.Count, $res['mismatched'].Count, ($res['mismatched'] -join ','))
    return $res
}

function Start-DetachedCutover {
    $refuse = New-Object System.Collections.ArrayList
    # 1. a waiter must not already be running (recorded pid, or any live copy).
    $live = Get-LiveWaiters
    if ($live.Count -gt 0) { [void]$refuse.Add('a Cutover waiter is already running: pid ' + ($live -join ',')) }
    if ($script:State.Contains('cutover')) {
        foreach ($k in @('detached', 'waiter')) {
            if ($script:State['cutover'].Contains($k)) {
                $wp = [int]$script:State['cutover'][$k]['pid']
                if ($wp -le 4) { continue }
                $p = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId=' + $wp) -ErrorAction SilentlyContinue
                if ($p -and ([string]$p.CommandLine -match $script:SelfCmdPattern)) { [void]$refuse.Add(('recorded {0} pid {1} is alive' -f $k, $wp)) }
            }
        }
    }
    # 2. the session to wait for must be named and alive.
    if (-not $NoWait) {
        if ($WaitPid -le 0) { [void]$refuse.Add('no -WaitPid given (pass -NoWait to cut over without waiting)') }
        elseif (-not (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue)) { [void]$refuse.Add(('-WaitPid {0} is not running (pass -NoWait to cut over without waiting)' -f $WaitPid)) }
    }
    # 3. the E: copy of this tool must be the reviewed C: copy, byte for byte.
    $sync = Sync-MigrateScripts
    if ($sync['files'] -eq 0) { [void]$refuse.Add('no files found in ' + (Join-Path $Src 'ops\migrate')) }
    if ($sync['mismatched'].Count -gt 0) {
        $m = 'E: copy of ops\migrate differs from C: (sha256): ' + ($sync['mismatched'] -join ',')
        if ($DryRun) { Write-Log ('dry run: a real run copies first, then refuses only if still different - ' + $m) } else { [void]$refuse.Add($m) }
    }
    $self = Join-Path $Dst 'ops\migrate\e_move.ps1'
    if (-not $DryRun -and -not (Test-Path -LiteralPath $self -PathType Leaf)) { [void]$refuse.Add('Dst copy of the script not found: ' + $self) }
    $ps = Join-Path $script:Sys32 'WindowsPowerShell\v1.0\powershell.exe'
    $cmd = (Format-Arg $ps) + ' -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ' + (Format-Arg $self) +
        ' -Phase Cutover -WaitPid ' + $WaitPid + ' -Src ' + (Format-Arg $Src) + ' -Dst ' + (Format-Arg $Dst) +
        ' -WtSrc ' + (Format-Arg $WtSrc) + ' -WtDst ' + (Format-Arg $WtDst) + ' -Python ' + (Format-Arg $Python) +
        ' -UserHome ' + (Format-Arg $UserHome)
    if ($NoWait) { $cmd += ' -NoWait' }
    $cwd = (Split-Path -Qualifier $Dst) + '\'
    if ($refuse.Count -gt 0) {
        foreach ($r in $refuse) { Write-Log ('DETACH REFUSED: ' + $r) }
        if (-not $DryRun) { throw ('detach refused: ' + ($refuse -join '; ')) }
    }
    if ($DryRun) { Write-Log ('would launch detached (WMI, cwd ' + $cwd + '): ' + $cmd); return }
    # Saved BEFORE the launch: the waiter owns the state file from its first second on and
    # records its own pid under cutover.waiter, so this process never writes it again.
    if (-not $script:State.Contains('cutover')) { $script:State['cutover'] = [ordered]@{} }
    $script:State['cutover']['detached'] = [ordered]@{
        at = (Get-Date).ToString('s'); pid = 0; launched_by = $PID
        wait_pid = $WaitPid; no_wait = [bool]$NoWait; script_sync = $sync
    }
    Save-State
    $startupClass = Get-CimClass -ClassName Win32_ProcessStartup
    $startup = New-CimInstance -CimClass $startupClass -Property @{ ShowWindow = [uint16]0 } -ClientOnly
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; CurrentDirectory = $cwd; ProcessStartupInformation = $startup }
    Write-Log ('detached cutover launched: returnvalue={0} pid={1}' -f $r.ReturnValue, $r.ProcessId)
    Start-Sleep -Seconds 3
    $alive = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId=' + [int]$r.ProcessId) -ErrorAction SilentlyContinue
    if ($r.ReturnValue -ne 0 -or -not $alive) { throw ('detached waiter is not running (returnvalue ' + $r.ReturnValue + ') - see ' + $script:LogFile) }
    Write-Log ('waiter pid {0} is running: {1}' -f $r.ProcessId, (Limit-Text ([string]$alive.CommandLine) 160))
}

function Copy-MissingWorktreePointers {
    $n = 0
    $pairs = @(
        @{ From = (Join-Path $Src '.claude\worktrees'); To = (Join-Path $Dst '.claude\worktrees') },
        @{ From = $WtSrc; To = $WtDst }
    )
    foreach ($pr in $pairs) {
        if (-not (Test-Path -LiteralPath $pr.From -PathType Container)) { continue }
        foreach ($d in @(Get-ChildItem -LiteralPath $pr.From -Directory -Force -ErrorAction SilentlyContinue)) {
            $sp = Join-Path $d.FullName '.git'
            $dd = Join-Path $pr.To $d.Name
            $dp = Join-Path $dd '.git'
            if ((Test-Path -LiteralPath $sp -PathType Leaf) -and (Test-Path -LiteralPath $dd -PathType Container) -and -not (Test-Path -LiteralPath $dp)) {
                if (-not $DryRun) { Copy-Item -LiteralPath $sp -Destination $dp }
                $n++
                Write-Log ('worktree pointer copied (new since preseed): ' + $dp)
            }
        }
    }
    return $n
}

function Invoke-DeltaCopies([string]$SrcState, [string]$WtState) {
    # No /XO: the C: version of every file wins (newer AND older), because RepointInternal is
    # re-applied right after. Dst-only files (e_move_backup, state, logs) are excluded by
    # name so nothing of this tool's is clobbered; robocopy without /PURGE never deletes.
    $base = @('/E', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1', '/MT:16', '/NP', '/NFL', '/NDL', '/XJ')
    $attempts = New-Object System.Collections.ArrayList
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $copies = New-Object System.Collections.ArrayList
        if ($SrcState -eq 'real') {
            $rc = Invoke-Robocopy $Src $Dst ($base + @('/XD', (Format-Arg (Join-Path $Src '.git')), 'e_move_backup') + $script:OwnFilesXf + @('.git'))
            [void]$copies.Add([ordered]@{ what = 'src'; exit = $rc.Code; ok = $rc.Ok })
            # .git is MIRRORED: commits / branches / prunes made in Src after Preseed must land.
            $rc = Invoke-Robocopy (Join-Path $Src '.git') (Join-Path $Dst '.git') @('/MIR', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1', '/MT:16', '/NP', '/NFL', '/NDL', '/XJ')
            [void]$copies.Add([ordered]@{ what = 'git-mirror'; exit = $rc.Code; ok = $rc.Ok })
        }
        if ($WtState -eq 'real') {
            $rc = Invoke-Robocopy $WtSrc $WtDst ($base + @('/XD', 'e_move_backup') + $script:OwnFilesXf + @('.git'))
            [void]$copies.Add([ordered]@{ what = 'wt'; exit = $rc.Code; ok = $rc.Ok })
        }
        [void]$attempts.Add([ordered]@{ attempt = $attempt; copies = $copies })
        $bad = @($copies | Where-Object { -not $_['ok'] })
        if ($bad.Count -eq 0) { return [ordered]@{ ok = $true; attempts = $attempts } }
        Write-Log ('delta attempt {0} failed: {1}' -f $attempt, ((@($bad) | ForEach-Object { $_['what'] + ' exit ' + $_['exit'] }) -join ', '))
        if ($attempt -lt 3) {
            [void](Invoke-KillPass 'delta-retry')
            Start-Sleep -Seconds 30
        }
    }
    return [ordered]@{ ok = $false; attempts = $attempts }
}

function Invoke-CatchUp([string]$Aside, [string]$To) {
    # Never throws: the junction is already in place, so a failed catch-up is recorded,
    # not rolled back. Lists every file it copied (full paths, /FP, no size / class).
    $res = [ordered]@{ from = $Aside; to = $To; exit = $null; ok = $false; copied = 0; files = (New-List) }
    try {
        if (-not $Aside -or -not (Test-Path -LiteralPath $Aside -PathType Container)) { $res['skipped'] = 'no aside directory'; return $res }
        $argStr = (Format-Arg $Aside) + ' ' + (Format-Arg $To) +
            ' /E /XO /XX /XJ /COPY:DAT /DCOPY:DAT /R:1 /W:1 /NP /NJH /NJS /NDL /NC /NS /FP' +
            ' /XD ' + (Format-Arg (Join-Path $Aside '.git')) + ' e_move_backup' +
            ' /XF .git e_move.log e_move_robocopy.log e_move_state.json'
        if ($DryRun) { Write-Log ('would run catch-up: robocopy ' + $argStr); $res['ok'] = $true; return $res }
        Write-Log ('catch-up: robocopy ' + $argStr)
        $r = Invoke-Exe -File (Join-Path $script:Sys32 'Robocopy.exe') -RawArgs $argStr
        $res['exit'] = $r.Code
        $res['ok'] = ($r.Code -ge 0 -and $r.Code -lt 8)
        foreach ($line in ($r.Out -split "`r?`n")) {
            $l = $line.Trim()
            if (-not $l -or -not $l.StartsWith($Aside, [System.StringComparison]::OrdinalIgnoreCase)) { continue }
            $res['copied']++
            if ($res['files'].Count -lt 500) { [void]$res['files'].Add($l.Substring($Aside.Length).TrimStart('\')) }
        }
        if (-not $res['ok']) { $res['output_tail'] = Limit-Text (($r.Out + ' ' + $r.Err).Trim()) 600 }
        Write-Log ('catch-up {0} -> {1}: exit {2}, {3} file(s) copied' -f $Aside, $To, $r.Code, $res['copied'])
        foreach ($f in @($res['files'] | Select-Object -First 30)) { Write-Log ('  caught up: ' + $f) }
    } catch {
        $res['error'] = $_.Exception.Message
        Write-Log ('catch-up failed (recorded, not rolled back): ' + $_.Exception.Message)
    }
    return $res
}

function Get-Strays([string]$SrcState, [string]$WtState) {
    # Files on E: that C: does not have (e.g. deleted on C: after the pre-seed). Report only.
    $hargs = @('strays', '--limit', '300')
    $pairs = 0
    if ($SrcState -eq 'real') { $hargs += @('--pair', $Src, $Dst); $pairs++ }
    if ($WtState -eq 'real') { $hargs += @('--pair', $WtSrc, $WtDst); $pairs++ }
    if ($pairs -eq 0) { return $null }
    $r = Invoke-Helper $hargs
    foreach ($p in $r['pairs']) {
        Write-Log ('strays {0}: {1} entr(ies) holding {2} file(s) exist only on the destination - reported, never deleted' -f $p['dst'], $p['count'], $p['files'])
        foreach ($s in @($p['sample'] | Select-Object -First 20)) { Write-Log ('  stray {0} {1}' -f $s['kind'], $s['rel']) }
    }
    return $r
}

function Invoke-CutoverPhase {
    if ($Detach) { Start-DetachedCutover; return }
    $driveRoot = (Split-Path -Qualifier $Dst) + '\'
    $script:SafeCwd = $driveRoot
    if (-not $DryRun) {
        Set-Location -LiteralPath $driveRoot
        [System.Environment]::CurrentDirectory = $driveRoot
    }
    if (-not $script:State.Contains('cutover')) { $script:State['cutover'] = [ordered]@{} }
    $cut = $script:State['cutover']
    if ($cut.Contains('src_aside')) { $script:SrcAside = [string]$cut['src_aside'] }
    if ($cut.Contains('wt_aside')) { $script:WtAside = [string]$cut['wt_aside'] }
    $self = Get-NormPath $PSCommandPath
    $script:UnprotectPid = $WaitPid

    # Refusals: wrong invocation. Nothing is touched, nothing restarted, state not written
    # (another waiter may own it).
    $refuse = New-Object System.Collections.ArrayList
    if ($WaitPid -le 0 -and -not $NoWait) { [void]$refuse.Add('no -WaitPid given (pass -NoWait to cut over without waiting)') }
    $others = Get-LiveWaiters
    if ($others.Count -gt 0) { [void]$refuse.Add('another Cutover waiter is running: pid ' + ($others -join ',')) }
    if (-not (Test-UnderPath $self $Dst)) { [void]$refuse.Add('script is not running from the Dst copy (' + $self + ')') }
    if (-not $DryRun -and (Test-UnderPath ((Get-Location).Path) $Src)) { [void]$refuse.Add('cwd is inside Src') }
    # Preconditions: the move is not ready. RC is put back to running from C:.
    $problems = New-Object System.Collections.ArrayList
    if (-not (Test-Path -LiteralPath (Join-Path $Dst 'CLAUDE.md') -PathType Leaf)) { [void]$problems.Add('Dst has no CLAUDE.md') }
    if (-not ($script:State.Contains('preseed') -and $script:State['preseed']['ok'])) { [void]$problems.Add('Preseed not recorded ok') }
    if (-not ($script:State.Contains('repoint') -and $script:State['repoint']['ok'])) { [void]$problems.Add('RepointInternal not recorded ok') }
    try { Assert-Distinct } catch { [void]$problems.Add($_.Exception.Message) }
    $srcState = Get-DirState $Src $Dst
    $wtState = Get-DirState $WtSrc $WtDst
    Write-Log ('src {0} is {1}; wtsrc {2} is {3}; aside {4} | {5}' -f $Src, $srcState, $WtSrc, $wtState, $script:SrcAside, $script:WtAside)

    if ($DryRun) {
        foreach ($p in $refuse) { Write-Log ('would REFUSE (no changes, nothing restarted): ' + $p) }
        foreach ($p in $problems) { Write-Log ('precondition (would refuse + restart RC from C:): ' + $p) }
        Wait-ForPid $WaitPid
        $d = Invoke-DeltaCopies $srcState $wtState
        $st = Get-Strays $srcState $wtState
        Write-Log ('would rename {0} -> {1} then at once mklink /J {0} {2}' -f $Src, (Get-AsidePath $Src), $Dst)
        if ($wtState -eq 'real') { Write-Log ('would then rename {0} -> {1} then at once mklink /J {0} {2}' -f $WtSrc, (Get-AsidePath $WtSrc), $WtDst) }
        Write-Log 'after each junction: catch-up robocopy <aside> -> <Dst> /E /XO /XX (no .git, no tool state/log/backup), copied files recorded'
        $t = Update-RecordedTasks
        $s = Update-Shortcuts
        $c = Update-ClaudeJson
        $r = Restart-RecordedTasks
        $clones = 0
        foreach ($f in $c['files']) { foreach ($a in $f['actions']) { if ($a['action'] -eq 'cloned') { $clones++ } } }
        Write-Log ('cutover plan: tasks {0}, shortcuts {1}, claude.json clones {2}, restarts {3}, refusals {4}, preconditions failing {5}' -f $t.Count, $s.Count, $clones, $r.Count, $refuse.Count, $problems.Count)
        return
    }
    if ($refuse.Count -gt 0) {
        foreach ($p in $refuse) { Write-Log ('REFUSED (no changes made): ' + $p) }
        throw ('cutover refused: ' + ($refuse -join '; '))
    }

    $cut['started_at'] = (Get-Date).ToString('s')
    $cut['waiter'] = [ordered]@{ pid = $PID; started_at = (Get-Date).ToString('s'); wait_pid = $WaitPid; no_wait = [bool]$NoWait; script = $self }
    if ($problems.Count -gt 0) {
        $why = 'precondition: ' + ($problems -join '; ')
        if ($srcState -eq 'real') {
            # Nothing renamed yet: put RC back exactly as it was (tasks only).
            Invoke-Rollback $why
        } else {
            # C: is already a junction or mid-move: never undo it on a precondition.
            $cut['refused'] = $why
            Write-Log ('REFUSED (no changes made): ' + $why)
            if ($srcState -eq 'missing') { Set-Status 'needs_operator' }
            Save-State
        }
        return
    }
    # Once the session exits, its orphaned children (MCP servers, shells with a cwd in
    # Src) are found as descendants of this dead root by the Stop pass below.
    $waitCreated = $null
    if ($WaitPid -gt 0) {
        $wp = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId=' + $WaitPid) -ErrorAction SilentlyContinue
        if ($wp) { $waitCreated = $wp.CreationDate }
    }
    Set-Status 'cutover_waiting'
    Save-State
    if ($NoWait) { Write-Log '-NoWait: not waiting for any session' } else { Wait-ForPid $WaitPid }
    if ($waitCreated) { $script:KilledPids[[int]$WaitPid] = $waitCreated }
    # The wait can last hours: decide from what the C: paths are NOW, not before the wait.
    $srcState = Get-DirState $Src $Dst
    $wtState = Get-DirState $WtSrc $WtDst
    Write-Log ('after wait: src {0} is {1}; wtsrc {2} is {3}' -f $Src, $srcState, $WtSrc, $wtState)
    # Resuming after a crash between a rename and its junction: that rename was ours.
    if ($srcState -eq 'missing') { $script:Renamed['src'] = $true }
    if ($wtState -eq 'missing' -and $script:WtAside -and (Test-Path -LiteralPath $script:WtAside -PathType Container)) { $script:Renamed['wt'] = $true }
    Set-Status 'cutover_running'
    Save-State

    try {
        if ($srcState -eq 'link-other' -or $wtState -eq 'link-other') { throw 'Src or WtSrc is a link to somewhere other than Dst/WtDst' }
        if ($srcState -eq 'missing' -and -not ($script:SrcAside -and (Test-Path -LiteralPath $script:SrcAside -PathType Container))) {
            throw 'Src is missing and no recorded aside directory exists'
        }
        $cut['stop'] = Invoke-StopPass -ExcludeTree 0 -Label 'cutover-stop'
        $delta = Invoke-DeltaCopies $srcState $wtState
        $cut['delta'] = $delta
        if (-not $delta['ok']) { throw 'delta copy still failing after 3 attempts' }
        if ($srcState -eq 'real' -or $wtState -eq 'real') {
            # After the delta AND the .git mirror: report strays, then re-apply every E: rewrite.
            $cut['strays'] = Get-Strays $srcState $wtState
            $cut['pointers_copied'] = Copy-MissingWorktreePointers
            $rep = Invoke-RepointInternal -FromCutover
            if (-not $rep['ok']) { throw ('repoint after delta failed: ' + ($rep['problems'] -join ',')) }
        }
        Save-State
    } catch {
        Invoke-Rollback ('before rename: ' + $_.Exception.Message)
        return
    }

    # Src: rename aside and IMMEDIATELY junction it; only then WtSrc, the same way.
    # Any failure undoes whatever this run did (Invoke-Rollback) and restarts RC from C:.
    try {
        $junctions = New-Object System.Collections.ArrayList
        $cut['junctions'] = $junctions
        if ($srcState -eq 'real') {
            $script:SrcAside = Get-AsidePath $Src
            $cut['src_aside'] = $script:SrcAside
            Save-State
            if (-not (Rename-DirWithRetry $Src $script:SrcAside 20)) { Invoke-Rollback ('could not rename ' + $Src + ' within 20 minutes'); return }
            $script:Renamed['src'] = $true
        }
        $now = Get-DirState $Src $Dst
        if ($now -ne 'junction-ok') {
            if ($now -ne 'missing') { Invoke-Rollback (('{0} reappeared as {1} before its junction was made' -f $Src, $now)); return }
            $script:Junctioned['src'] = $true
            $j = New-VerifiedJunction $Src $Dst 'CLAUDE.md'
            [void]$junctions.Add($j)
            if (-not $j['ok']) { Invoke-Rollback ('junction failed: ' + $Src); return }
        }
        # Files that landed in C: after the delta (rename-retry window: sibling notes into
        # moon_sync_inbox ...) now sit in the aside directory: copy them over (/XO).
        $catchups = New-Object System.Collections.ArrayList
        $cut['catchup'] = $catchups
        if ($script:Renamed['src']) { [void]$catchups.Add((Invoke-CatchUp $script:SrcAside $Dst)) }
        Save-State
        if ($wtState -eq 'real') {
            $script:WtAside = Get-AsidePath $WtSrc
            $cut['wt_aside'] = $script:WtAside
            Save-State
            if (-not (Rename-DirWithRetry $WtSrc $script:WtAside 20)) { Invoke-Rollback ('could not rename ' + $WtSrc + ' within 20 minutes'); return }
            $script:Renamed['wt'] = $true
        }
        $now = Get-DirState $WtSrc $WtDst
        if ($now -eq 'missing' -and (Test-Path -LiteralPath $WtDst -PathType Container)) {
            $probe = $null
            $first = @(Get-ChildItem -LiteralPath $WtDst -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
            if ($first.Count -gt 0) { $probe = $first[0].Name }
            $script:Junctioned['wt'] = $true
            $j = New-VerifiedJunction $WtSrc $WtDst $probe
            [void]$junctions.Add($j)
            if (-not $j['ok']) { Invoke-Rollback ('junction failed: ' + $WtSrc); return }
        } elseif ($now -ne 'junction-ok' -and $script:Renamed['wt']) {
            Invoke-Rollback (('{0} reappeared as {1} before its junction was made' -f $WtSrc, $now)); return
        }
        if ($script:Renamed['wt']) { [void]$catchups.Add((Invoke-CatchUp $script:WtAside $WtDst)) }
    } catch {
        Invoke-Rollback ('rename/junction step threw: ' + $_.Exception.Message)
        return
    }
    Set-Status 'junctioned'
    Save-State

    # Externals point at the canonical E: paths from here on. The junction is in place,
    # so a failed step here is recorded and skipped - RC must still be restarted.
    try { $cut['tasks_repointed'] = Update-RecordedTasks } catch { $cut['tasks_repointed_error'] = $_.Exception.Message; Write-Log ('task repoint step failed: ' + $_.Exception.Message) }
    Save-State
    try { $cut['shortcuts'] = Update-Shortcuts } catch { $cut['shortcuts_error'] = $_.Exception.Message; Write-Log ('shortcut step failed: ' + $_.Exception.Message) }
    try { $cut['claude_json'] = Update-ClaudeJson } catch { $cut['claude_json'] = [ordered]@{ error = $_.Exception.Message }; Write-Log ('claude.json step failed: ' + $_.Exception.Message) }
    try { $cut['memory'] = Copy-ClaudeMemory } catch { Write-Log ('memory copy failed: ' + $_.Exception.Message) }
    Save-State
    try { $cut['tasks_restarted'] = Restart-RecordedTasks } catch { $cut['tasks_restarted_error'] = $_.Exception.Message; Write-Log ('restart step failed: ' + $_.Exception.Message) }
    Save-State
    $cut['verify'] = Test-RcHealth 120
    $cut['finished_at'] = (Get-Date).ToString('s')
    if ($cut['verify']['ok']) { Set-Status 'cut_over' } else { Set-Status 'cut_over_verify_failed' }
    $cut['result'] = $script:State['status']
    Save-State
}

# ---------------------------------------------------------------------------
# Phase 5: Status
# ---------------------------------------------------------------------------

function Get-Verdict($s) {
    # One phone-readable line: cut_over / rolled_back / needs_operator / cutover_waiting /
    # cutover_running (or the pre-cutover status), plus waiter liveness and the reason.
    $st = [string]$s['status']
    $v = $st
    if ($st -eq 'junctioned') { $v = 'cutover_running' }
    if ($st -eq 'cut_over_verify_failed') { $v = 'cut_over (health verify FAILED)' }
    $extra = ''
    $cut = $null
    if ($s.Contains('cutover')) { $cut = $s['cutover'] }
    if ($cut -and (@('cutover_waiting', 'cutover_running', 'junctioned') -contains $st) -and $cut.Contains('waiter')) {
        $wp = [int]$cut['waiter']['pid']
        $p = $null
        if ($wp -gt 4) { $p = Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId=' + $wp) -ErrorAction SilentlyContinue }
        if ($p -and ([string]$p.CommandLine -match $script:SelfCmdPattern)) { $extra += ('; waiter pid {0} alive' -f $wp) }
        else { $extra += ('; waiter pid {0} NOT RUNNING - see logs\e_move.log' -f $wp) }
    }
    if ($cut -and $cut.Contains('reason') -and $cut['reason']) { $extra += '; reason: ' + (Limit-Text ([string]$cut['reason']) 160) }
    return ('VERDICT ' + $v + $extra)
}

function Show-Status {
    $s = $script:State
    $lines = New-Object System.Collections.ArrayList
    try { [void]$lines.Add((Get-Verdict $s)) } catch { [void]$lines.Add('VERDICT ' + $s['status'] + ' (verdict detail failed: ' + $_.Exception.Message + ')') }
    [void]$lines.Add(('state {0} (updated {1}) status={2}' -f $script:StateLoadedFrom, $s['updated'], $s['status']))
    try { Add-StatusLines $s $lines } catch { [void]$lines.Add('status summary incomplete: ' + $_.Exception.Message) }
    foreach ($l in ($lines | Select-Object -First 15)) { Write-Host (ConvertTo-AsciiText $l) }
}

function Add-StatusLines($s, $lines) {
    if ($s.Contains('stop')) {
        $st = $s['stop']
        $en = @($st['tasks'] | Where-Object { $_['enabled'] }).Count
        $ru = @($st['tasks'] | Where-Object { $_['running'] }).Count
        $last = $null
        if ($st['runs'].Count -gt 0) { $last = $st['runs'][$st['runs'].Count - 1] }
        $lk = 0
        if ($last) { $lk = @($last['processes'] | Where-Object { $_['result'] -eq 'killed' }).Count }
        [void]$lines.Add(('stop: first {0}; tasks recorded {1} (enabled {2}, running {3}); runs {4}; last run killed {5}; health pid before {6}' -f $st['first_at'], $st['tasks'].Count, $en, $ru, $st['runs'].Count, $lk, $st['health_pid_before']))
    }
    if ($s.Contains('preseed')) {
        $p = $s['preseed']
        $exits = (@($p['robocopy']) | ForEach-Object { $_['exit'] }) -join ','
        [void]$lines.Add(('preseed: ok={0} robocopy exits {1}; files {2} bytes {3}; links relinked {4}, external {5}' -f $p['ok'], $exits, $p['stats']['files'], $p['stats']['bytes'], $p['relinked'].Count, $p['external_links'].Count))
    }
    if ($s.Contains('repoint')) {
        $r = $s['repoint']
        [void]$lines.Add(('repoint: ok={0} hooksPath [{1}] {2}; gitlinks rewritten {3}; repair {4}; configs rewritten {5}; safe.directory dubious {6}' -f $r['ok'], $r['hooks_path']['action'], $r['hooks_path']['after'], $r['gitlinks']['rewritten'], $r['repair']['action'], $r['configs']['matched'].Count, $r['safe_directory']['dubious']))
    }
    if ($s.Contains('cutover')) {
        $c = $s['cutover']
        [void]$lines.Add(('cutover: result={0} reason={1} started {2} finished {3}' -f $c['result'], $c['reason'], $c['started_at'], $c['finished_at']))
        [void]$lines.Add(('cutover: aside {0} | {1}; junctions ok {2}' -f $c['src_aside'], $c['wt_aside'], ((@($c['junctions']) | ForEach-Object { $_['ok'] }) -join ',')))
        $tr = @($c['tasks_repointed'] | Where-Object { $_['ok'] }).Count
        $sh = @($c['shortcuts'] | Where-Object { $_['ok'] }).Count
        $rs = @($c['tasks_restarted'] | Where-Object { $_['started'] }).Count
        [void]$lines.Add(('cutover: tasks repointed {0}/{1}; shortcuts {2}/{3}; tasks started {4}' -f $tr, @($c['tasks_repointed']).Count, $sh, @($c['shortcuts']).Count, $rs))
        if ($c.Contains('catchup')) {
            [void]$lines.Add(('cutover: catch-up from aside: ' + ((@($c['catchup']) | ForEach-Object { '{0} file(s) ok={1}' -f $_['copied'], $_['ok'] }) -join '; ')))
        }
        if ($c.Contains('verify')) {
            $v = $c['verify']
            [void]$lines.Add(('verify: ok={0} pid {1} (before {2}) alive={3} ports {4}' -f $v['ok'], $v['pid'], $v['pid_before'], $v['alive'], (@($v['ports']) -join ',')))
        }
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

try {
    Initialize-Log
    if ($Phase -ne 'Status') {
        Write-Log ('start pid={0} src={1} dst={2} wtsrc={3} wtdst={4} exclude_tree={5} wait_pid={6}' -f $PID, $Src, $Dst, $WtSrc, $WtDst, $ExcludeTreeOfPid, $WaitPid)
    }
    $script:State = Read-State
    switch ($Phase) {
        'Stop' { Invoke-StopPhase }
        'Preseed' { Invoke-PreseedPhase }
        'RepointInternal' { [void](Invoke-RepointInternal) }
        'Cutover' { Invoke-CutoverPhase }
        'Status' { Show-Status }
    }
    exit 0
} catch {
    Write-Log ('FATAL: ' + $_.Exception.Message + ' @ ' + $_.InvocationInfo.ScriptLineNumber)
    exit 1
}
