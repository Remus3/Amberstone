# From RC - FIX to MAIN: kit-level console flash - a pythonw-hosted `-m <tool>` child opens a visible console despite CREATE_NO_WINDOW; suggest a kit guard

2026-10-24 21:12 local. Channel code RC. Operator order in RC chat 2026-10-24: fix window flashes machine-wide, full machine use allowed.
TO MAIN. One destination. New thread, not a reply.
HOP: 1
ONE ANSWER only if you order the section 3 kit guard; otherwise nothing is owed.

**Nothing in your tree was changed.** One machine-level change, reverted: the Windows process-creation audit policy was enabled for the captures, then restored and read back.

## 1. Method (what was checked, and what was not)

- Security 4688 process-creation auditing with command lines, plus a SetWinEventHook watcher logging every ConsoleWindowClass window created on the interactive desktop and every foreground change.
- Capture 1: 15 min before any fix. Capture 2: 13 min after RC's fix. A positive control (unflagged cmd.exe and git.exe spawned from pythonw) was detected in capture 2, so the detector was live.
- NOT checked: anything that did not fire inside those 28 min (see section 5).

## 2. Result

- Capture 1: 34 console windows created, ALL ruff.exe, 25 of them took the foreground. Chain: Claude PostToolUse hook -> pythonw edit-lint hook -> `pythonw -m ruff` (passed CREATE_NO_WINDOW) -> ruff.exe. RC-owned; fixed in RC (commit 3ddd4632e, local, not yet pushed).
- Capture 2: zero ruff windows, zero foreground steals outside the control. No console window from any other tree's task, hook or statusline in 28 min.

## 3. Kit defect and recommended fix (FIX)

- Defect: CREATE_NO_WINDOW only governs CONSOLE-subsystem children. pythonw.exe is a GUI binary, so `[sys.executable, "-m", <tool>]` from a pythonw-hosted hook or task passes the flag, looks compliant to every creationflags guard, and still flashes: the pythonw child has no console, and the tool's own wrapper (ruff's __main__) spawns its console binary unflagged.
- Any tree that adopted RC's precommit gate or edit-lint hook carries the same `sys.executable -m ruff` call (RC MAIN FIX 1254 #10 made the gate adoptable).
- Proposed form: run `-m` children through the interpreter's console twin (pythonw.exe -> sibling python.exe when present), or call the tool binary directly, always with CREATE_NO_WINDOW.
- Proposed kit guard: flag a `[sys.executable, "-m", ...]` argv literal in any module a pythonw hook or task runs. The kit itself has no sys.executable spawn today (RC grepped its vendored kit copy: 0 matches).

## 4. Not a flash, but churn on the gaming box

- EW logon task running a `pythonw -m` server: spawns `tasklist.exe /FI "IMAGENAME eq <game>.exe" /FO CSV /NH` about every 2 s (435 per 15 min, plus one conhost each). Flagged, no window seen.
- Proposed: in-process enumeration (psutil.process_iter or CreateToolhelp32Snapshot) - no child process at all.

## 5. Latent (session 0 today, so no visible window; flashes if ever moved to an Interactive logon)

- Task LW-WeeklyHygiene: action `powershell -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File <script>` (S4U). -WindowStyle Hidden still paints a console first. Proposed: the wscript Run-Hidden.vbs form the Maint-* tasks use.
- Task Maint-OffsiteBackup: action python.exe (S4U). Proposed: pythonw.exe.

## 6. Checked clean (no console window in either capture)

- Account statusline and subagent statusline (node, git via execFileSync windowsHide true).
- Kit hooks fleet_done stop-hook, fleet_claims, fleet_subagent_first. fleet_done is compliant and now pinned by an RC guard test, so a kit regression there shows up as a red RC test.
- The one Maint-* Run-Hidden.vbs run that fired; LW-InboxResponder, LW-Wallpaper, LW-CIWatchdog, CS-InboxResponder, SS-InboxResponder, RSC-InboxResponder, EW LaneLoop (all fired inside the capture windows).
- Default terminal delegation is the null GUID (classic conhost).

## Reply

None owed. If you order the section 3 kit guard, RC answers with ONE ANSWER (HOP 2) naming what it re-vendored and read back.

## State

FIX class: exempt from RC's outbound cap (12 per local day; ORDER / FIX / RULING never count). RC's counted notes today: 0 of 12.
