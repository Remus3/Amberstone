# ops/migrate - move RC from C: to E:

Moves `C:\Riot Commander` and `C:\rc-worktrees` to `E:\Riot Commander` and
`E:\rc-worktrees`, then leaves DIRECTORY JUNCTIONS at the old C: paths so every
C: literal nobody repointed (tracked HARDCODED paths, frozen files, sibling trees
writing into `moon_sync_inbox/`) keeps working. External launchers (RC-* tasks,
shortcuts, Claude Code project keys) are repointed to the canonical E: paths.

Files: `e_move.ps1` (driver, Windows PowerShell 5.1), `e_move_helpers.py` (byte-exact
rewrites, `.claude.json` edits, stray report; tests in `tests/test_e_move_helpers.py`).
State: `ops\runtime\e_move_state.json` (Dst once it exists; Cutover writes both trees).
Log: `logs\e_move.log` (+ `logs\e_move_robocopy.log`). Backups of everything edited:
`E:\Riot Commander\ops\runtime\e_move_backup\`.

## Launch lines

Run each with `-DryRun` first (a dry run only lists; it writes nothing but its log,
beside Src). Replace 12345 with the PID of the Claude session that will exit last.

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\migrate\e_move.ps1" -Phase Stop -ExcludeTreeOfPid 12345
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\migrate\e_move.ps1" -Phase Preseed -AllowExistingDst
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\migrate\e_move.ps1" -Phase RepointInternal
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\migrate\e_move.ps1" -Phase Status
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\migrate\e_move.ps1" -Phase Cutover -Detach -WaitPid 12345

## Phases

1. **Stop** disables and ends every RC-* task whose action names Src/WtSrc
   (RC-TeamClaudeProxy is never touched; non-RC tasks such as `\RiotCommander` are only
   listed) and re-reads each task to confirm the disable took. It then
   `taskkill /F /PID`s every process that names Src/WtSrc, every task engine process,
   their descendants, and every process whose CURRENT DIRECTORY is inside Src/WtSrc.
   Never killed: this tool (any `e_move.ps1` process) and its children, the
   `-ExcludeTreeOfPid` tree and its ancestors, every live Claude session tree that an RC
   process did not start, League/Riot/Vanguard/OBS/shell processes, teamclaude.
2. **Preseed** robocopies everything (/E, never purges). It refuses a destination it did
   not create unless `-AllowExistingDst`. Re-running it invalidates RepointInternal.
3. **RepointInternal** never touches C:: hooksPath, worktree link files, untracked config
   files, Claude memory, safe.directory. It skips `git worktree repair` when a
   registered worktree lives outside Dst/WtDst.
4. **Cutover -Detach** refuses if a waiter is already running, if `-WaitPid` is missing
   or not running (unless `-NoWait`), or if the E: copy of `ops\migrate` does not match
   the C: copy by SHA-256 after copying it. It then launches the waiter through WMI
   (cwd `E:\`, hidden). The waiter waits for `-WaitPid` with no timeout, then:
   - stops again;
   - delta-copies without /XO (C: wins every file), retried up to 3 times;
   - mirrors `.git` and reports files that exist only on E: (strays: report only);
   - re-applies RepointInternal;
   - renames C:\Riot Commander aside and junctions it at once, then does the same for
     C:\rc-worktrees;
   - after each junction, copies anything that landed in the renamed directory during
     the window (e.g. sibling notes in `moon_sync_inbox`) to E: (/XO) and records it;
   - repoints the tasks, shortcuts and `.claude.json`, restarts the tasks, and checks
     `health.json` plus listeners on 8888 / 8889 / 8860 for 120 s.

## What the operator does

1. Close every shell, editor and Explorer window inside `C:\Riot Commander` or
   `C:\rc-worktrees`, then exit the Claude session whose PID was given to -WaitPid.
2. Do NOT start any Claude session - in C: OR E: - and do not let the Console pane
   auto-restart a session into `C:\Riot Commander`, until Status shows a final verdict.
   Check from any plain PowerShell window (the first line is the verdict):

       powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\Riot Commander\ops\migrate\e_move.ps1" -Phase Status

   `VERDICT cutover_waiting` / `cutover_running`: wait. `VERDICT cut_over`: done.
   `VERDICT rolled_back`: RC runs from C: as before. `VERDICT needs_operator`: read the
   reason; nothing was restarted.
3. After `cut_over`, start the next session in `E:\Riot Commander`. Relaunch the Lane
   Widget / Amberstone shell from their Desktop shortcuts (Stop ended them).

### Resume when C:\Riot Commander is missing

If the waiter died between the rename and the junction (`C:\Riot Commander` absent,
`C:\Riot Commander.pre-E-move-<date>` present, verdict `cutover_running` with the waiter
NOT RUNNING), finish it in the foreground from E: (cwd outside C:):

    cd /d E:\
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\Riot Commander\ops\migrate\e_move.ps1" -Phase Cutover -NoWait

It reads the recorded aside directory, makes the junction, catches up and continues;
if it cannot, it puts the original back (or re-creates the junction so the C: path is
never missing) and reports `needs_operator`.

## Rollback

Automatic, during Cutover: any failure before or during the rename/junction steps
removes the junctions this run made and renames the `*.pre-E-move-<yyyyMMdd>`
directories back. Tasks still point at C:; the recorded tasks are re-enabled and
re-run, and the status is `rolled_back`. If a C: path came back as a REAL directory
while its renamed original still exists (two trees), or the original cannot be renamed
back (the junction to E: is then re-created so the C: path never goes missing),
NOTHING is restarted; the status is `needs_operator` with the reason, in both trees.

Manual, after a SUCCESSFUL cutover (work done on E: since then is NOT in the C: copy;
copy anything you need out of E: first):

    $ps1 = 'E:\Riot Commander\ops\migrate\e_move.ps1'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ps1 -Phase Stop -ExcludeTreeOfPid 12345
    cmd /c rmdir "C:\Riot Commander"
    cmd /c rmdir "C:\rc-worktrees"
    Rename-Item -LiteralPath 'C:\Riot Commander.pre-E-move-20261008' -NewName 'Riot Commander'
    Rename-Item -LiteralPath 'C:\rc-worktrees.pre-E-move-20261008' -NewName 'rc-worktrees'
    Get-ChildItem 'E:\Riot Commander\ops\runtime\e_move_backup\tasks\*.xml' | ForEach-Object {
        $n = $_.BaseName
        Register-ScheduledTask -TaskName $n -Xml (Get-Content -Raw -LiteralPath $_.FullName) -Force
    }

`rmdir` without /s removes only the junction; never use `Remove-Item -Recurse` on a
junction. The XML backups hold the C: actions but were exported after Stop, so the
tasks come back DISABLED: run `Enable-ScheduledTask -TaskName <name>` for each task with
`enabled: true` under `stop.tasks` in the state file, then `schtasks /Run /TN \<name>`
for each with `running: true` (RC-Supervisor, RC-DaemonSlayer, ...).
Restore shortcuts by copying `e_move_backup\shortcuts\*` back over their originals
(each backup name is the original full path with `\` and `:` replaced by `_`). The
`E:/...` keys added to `.claude.json` are harmless and can stay.
