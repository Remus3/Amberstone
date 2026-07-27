# PowerShell 7 on this machine - what was done, and how to switch a project to it

Machine: DESKTOP-LCA3EBI (hostname verified live 2026-07-26; Tailscale is NOT installed on this box)
Installed: 2026-07-26
Applies to: every project on this box, not just Riot Commander

> This file is the CANONICAL copy and is version controlled. A Desktop copy
> exists for handing to other projects; an earlier Desktop-only version of this
> document was lost, which is why the canonical copy now lives in the repo.

---

## 1. What is installed now

| | |
|---|---|
| Version | PowerShell 7.6.4 (edition Core) |
| Executable | `C:\Program Files\PowerShell\7\pwsh.exe` |
| Installer shape | **MSI, machine scope** (deliberately NOT the MSIX/Store package - see section 2) |
| Machine PATH | `C:\Program Files\PowerShell\7\` was added |
| Default output encoding | **UTF-8** (5.1 uses the system ANSI codepage) |
| PSRemoting | **NOT enabled** (installed with `ENABLE_PSREMOTING=0`) |
| Servicing | Microsoft Update enabled (`USE_MU=1 ENABLE_MU=1`) |
| Explorer context menu | not added |

**Windows PowerShell 5.1 is untouched and stays forever.** `powershell.exe` is
still 5.1.19041.6456. PS7 is a SIDE-BY-SIDE install under a different executable
name (`pwsh.exe`). Nothing switched to PS7 automatically - every call site is an
explicit, per-project decision.

    powershell.exe  ->  Windows PowerShell 5.1   (Desktop edition, ANSI default)
    pwsh.exe        ->  PowerShell 7.6.4         (Core edition, UTF-8 default)

---

## 2. Why the MSI, and the trap to avoid repeating

`winget install --id Microsoft.PowerShell` installs the **MSIX/Store** package,
because the winget manifest for 7.6.4.0 offers ONLY the msixbundle. Verified with
`winget show --id Microsoft.PowerShell --source winget`:

    Installer Type: msix
    Installer Url:  .../releases/download/v7.6.4/PowerShell-7.6.4.msixbundle

**The MSIX shape is unsuitable for automation on this box:**

1. The real executable lands at
   `C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.4.0_x64__8wekyb3d8bbwe\pwsh.exe`
   - the path carries the VERSION, so it changes on every update and anything
   pinned to it breaks silently.
2. The stable-looking launcher `%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe` is
   a **per-user app-execution alias**. It does not reliably resolve for scheduled
   tasks, services, or anything running as another user or as SYSTEM.

This machine runs 22 `RC-*` scheduled tasks, so both were disqualifying.

`--installer-type msi` does NOT work - winget answers `No applicable installer
found`, because the MSI is genuinely absent from the manifest. Take it from the
SAME Microsoft release the manifest resolves to:

    https://github.com/PowerShell/PowerShell/releases/download/v7.6.4/PowerShell-7.6.4-win-x64.msi

110.2 MB. **Verify the signature before running it:**

```
Get-AuthenticodeSignature <path-to-msi> | Select-Object Status, SignerCertificate
```

Must report `Status: Valid` and signer
`CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US`.

Exact install command used (exit code 0):

```
msiexec.exe /i "PowerShell-7.6.4-win-x64.msi" /qn /norestart /l*v ps7_msi.log ADD_PATH=1 ENABLE_PSREMOTING=0 REGISTER_MANIFEST=1 ADD_EXPLORER_CONTEXT_MENU_OPENPOWERSHELL=0 USE_MU=1 ENABLE_MU=1
```

**winget wrinkle:** immediately after uninstalling the MSIX, winget kept reporting
`Found an existing package already installed` while `winget list` reported
nothing. Its tracking lags. Confirm from the filesystem and Appx, never winget:

```
Get-AppxPackage -Name "Microsoft.PowerShell*"
Test-Path 'C:\Users\Administrator\AppData\Local\Microsoft\WindowsApps\pwsh.exe'
Test-Path 'C:\Program Files\PowerShell\7\pwsh.exe'
```

---

## 3. What PS7 actually fixes

Measured under 7.6.4 on this machine, not assumed:

| Feature | 5.1 | 7.6.4 |
|---|---|---|
| `&&` / `\|\|` chain operators | parser error | works |
| Ternary `? :` | not available | works |
| Null-coalescing `??` / `?.` | not available | works |
| `ConvertFrom-Json -AsHashtable` | not available | works (`OrderedHashtable`) |
| Default output encoding | system ANSI codepage | UTF-8 |
| Native exe stderr redirection | wraps lines in `NativeCommandError`, sets `$?` false on exit 0 | behaves sanely |

---

## 4. HOW TO SWITCH A PROJECT TO PS7

Change one class of call site at a time and verify before moving on.

### 4a. Scheduled tasks

```
Get-ScheduledTask | Where-Object { $_.TaskName -like 'RC-*' } | ForEach-Object { "$($_.TaskName) -> $(($_.Actions | Select-Object -First 1).Execute)" }
```

Only tasks whose `Execute` is `powershell.exe` are candidates:

```
$t = Get-ScheduledTask -TaskName '<NAME>'
$new = New-ScheduledTaskAction -Execute 'C:\Program Files\PowerShell\7\pwsh.exe' -Argument $t.Actions[0].Arguments
Set-ScheduledTask -TaskName '<NAME>' -Action $new
```

Cautions: use the FULL path (a task's PATH is not an interactive PATH); add
`-NoProfile` (PS7 has its own profile location); there is no `pwshw.exe`, so keep
whatever window-hiding mechanism the task already uses; a hidden parent does NOT
hide a CHILD process it spawns. After each change force a run and confirm both
`Last Result` is 0 AND the real side effect happened - a launcher that declines to
do its work also exits 0.

### 4b. `.ps1` invoked from other languages

```
Select-String -Path <project>\**\*.py,<project>\**\*.bat,<project>\**\*.ps1 -Pattern 'powershell(\.exe)?' -List
```

Replace the executable string with the full pwsh path. Expect stdout as **UTF-8** -
if the caller decodes with a hardcoded ANSI codepage, fix the decode at the same
time or you trade one mojibake bug for another.

### 4c. Claude Code's PowerShell tool - binds its binary AT SESSION START

There is no setting that selects the binary; `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`
only turns the tool on or off. But the tool is **not pinned to 5.1** - it resolves
`pwsh.exe` if one is available when the session starts, else `powershell.exe`.

Measured 2026-07-26, two sessions, same box, same settings:

| Session | Started | `$PSVersionTable` | Host exe |
|---|---|---|---|
| A | BEFORE the install | 5.1.19041.6456 / Desktop | `...\WindowsPowerShell\v1.0\powershell.exe` |
| B | AFTER the install | 7.6.4 / Core | `C:\Program Files\PowerShell\7\pwsh.exe` |

Consequences: installing PS7 upgrades agent sessions for free, but only sessions
started AFTER it. **Never assume which you are on - probe**
`$PSVersionTable.PSVersion` and
`[System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName`. A
long-lived session and a fresh one can genuinely disagree and both be right.

---

## 5. WHAT MUST NOT CHANGE - the no-em-dash rule stays

Measured under 7.6.4: a no-BOM UTF-8 `.ps1` containing an em-dash parses with
**0 errors**, so the 5.1 `ParseFile` ANSI-decode failure does not occur there.

**Do NOT relax the rule.** Three reasons:

1. **The 5.1 failure mode is LIVE, not legacy** - and this is the strongest,
   because it does not depend on anyone's migration schedule. Authored `.ps1`
   files are invoked by shims that name `powershell.exe` EXPLICITLY. On Riot
   Commander, verified 2026-07-26:

       ops/rc_watcher_launch.vbs:2      oShell.Run "powershell.exe ... rc_league_watcher.ps1"
       ops/install_startup.bat:24       generates a .vbs that does the same
       ops/launch_new_system.bat:36     powershell.exe ... run_self_healing_watchdog.ps1
       ops/start_ops.bat:15             powershell.exe ... run_self_healing_watchdog.ps1
       bootstrap_riot_commander_dev.cmd:3   powershell ... bootstrap_riot_commander_dev.ps1

   Grep your own project for `powershell.exe` in `*.vbs` / `*.bat` / `*.cmd`
   before assuming otherwise - a shim is easy to forget because it is neither a
   scheduled task nor a `.ps1`.
2. It is also a standing operator style rule, independent of any parser.
3. It is mechanically enforced (`tools/precommit_gate.py`, now in BOTH the Claude
   PreToolUse hook and the tracked git hooks).

PS7 removes one FAILURE MODE, not the rule.

---

## 6. Verify

```
& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoProfile -Command '$PSVersionTable'
powershell.exe -NoProfile -Command '$PSVersionTable.PSVersion'
```

Expect `7.6.4 / Core` and `5.1.19041.6456`. **If the second stops working,
something went wrong** - PS7 must never replace it. A shell opened before the
install will not have the new PATH entry; open a new one or use the full path.

---

## 7. Rollback

```
Get-Package -Name "PowerShell 7*" | Uninstall-Package
```

As of 2026-07-26 nothing depends on PS7 - no scheduled task, script or project
has been pointed at it - so removing it is a no-op. That changes the moment
section 4 is acted on, so record migrated call sites below.

## 8. Migration log - append as call sites move

| Date | Project | Call site moved | Verified how |
|---|---|---|---|
| 2026-07-26 | (none yet) | PS7 installed only; zero call sites switched | n/a |
