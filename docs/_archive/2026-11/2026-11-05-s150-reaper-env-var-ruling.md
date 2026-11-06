# s150 ruling - CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP

Date: 2026-11-05. Adjudicator: distinct read-only adjudicator agent (RC tree).
Order: operator in chat, 2026-11-05: "OPTIONAL - BEST ADJUDICATED".
Method: read-only. No edit, no settings change, no restart; the gated whole
suite launched 17:13:55 local was left running and untouched.

Archive note: the run that suite became is docs/LEDGER.md entry 2052; the void run of F4 is entry 2050; the operator's answer and this ruling are recorded in entry 2054. Scrubbed for the tracked copy: two machine-local paths reworded (the binary path in F1, the user settings path in F8), and this note added. Nothing else differs from the ruling as written.

## DECISION

DO NOT SET IT NOW, AT ANY SCOPE (no account/user settings, no project
.claude/settings.json env, no registry or setx, no launch env for the current
session). Set it ONLY under the conditions in "Re-open" below: per launch, for
one dedicated landing-suite Claude Code window, after RC has its own measured
physical-memory stop in place and the reaper has fired again while that stop
said the box was safe.

Do the cause-side work first (Alternatives 5 and 6).

## FACTS (source for each)

F1. The variable exists and does what its name says.
- Docs: code.claude.com/docs/en/env-vars, row quoted verbatim: "Set to `1` to
  stop Claude Code from terminating background shell commands under memory
  pressure. By default, on macOS and Linux, Claude Code terminates background
  shells when the operating system reports critical memory pressure and the
  session has been idle for 30 minutes with no turn or subagent running.
  Windows has no memory-pressure signal, so this variable has no effect
  there. Requires Claude Code v2.1.193 or later".
- Installed package: @anthropic-ai/claude-code 2.1.318 (package.json), npm
  global install, binary `bin/claude.exe` inside the npm global package folder
  (342408352 bytes, installed 2026-11-04 19:51). This session runs it: the
  claude.exe process started 2026-11-04 19:51:38 from that path. The string
  occurs 5 times: in the env registry (`CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP:()=>tI`,
  `tI=N.bool()`, a boolean parse), in the kill note, and in the gate itself:
  `if(!ye()&&!i.CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP){ ... process.on("memoryPressure",qe) ... }`.
  With the variable truthy, the memory-pressure listener is never installed
  for that shell.
- Changelog (anthropics/claude-code CHANGELOG.md, newest 2.1.318): no entry
  names the variable or the reaper in the part read (2.1.318 down to
  2.1.304). Not found there, so the docs row and the binary are the sources.

F2. What the reaper does (binary 2.1.318, function around the
"task_local_shell_pressure_reap" event).
- It is installed when a Bash/PowerShell command is moved to the background
  (not for Monitor tasks; the `!ye()` guard is most likely "not a headless run",
  which would mean `-p` lane runs are never reaped; not proven, minified names
  repeat).
- On a runtime "memoryPressure" event it kills the shell (status killed, stop
  cause memory_pressure, the note "do not start it again on your own") only if
  ALL hold: the level is "critical"; no terminal input for 30 min
  (`$Xn=1800000`); no turn running; no delegated agent running; the shell did
  not start within 30 min after an earlier reap with no input since
  (`FDs=1800000`); and host memory is "scarce". Scarce on Linux/WSL means
  MemAvailable under 10 percent and under 4 GiB; on every other OS the code
  returns `scarce:true` with the detail "kernel verdict taken as is".
- It does not touch foreground commands, Monitor tasks, or the separate
  background time limit ("deadline" stop), which the variable does not
  disable.

F3. The docs are wrong for this build on Windows. Measured: 7 memory-pressure
kills on this Windows box, read from the session transcripts (task
notifications "was stopped because the system is running low on memory"):
- 2026-10-20T04:06:56Z, another session: "Run gated Tier-2 dual suite with
  progress file" and its wait command.
- 2026-11-05T07:13:32Z, this session: two "wait for the gated suite" commands.
- 2026-11-05T17:10:05Z (11:10:05 local), this session: the ruled gated whole
  suite on 401dac973 (94 percent), its stop-condition sampler, and a
  verifier's read command.
So the gate is platform independent and the variable WOULD switch it off on
Windows, but the Windows trigger is undocumented: the code takes the runtime's
verdict as is, and the binary links both CreateMemoryResourceNotification and
GlobalMemoryStatusEx, so which signal and which threshold cannot be read from
it.

F4. The margins at the 11:10:05 kill (docs/LEDGER.md entry 2050, RC's own
sampler, one read per 10 s): last read 11:09:58 free commit 14110 MB, physical
4136 MB, suite tree 21912 MB; floors 13709 MB commit and 3850 MB physical at
11:09:38; RAM 31.6 GB, commit limit 48.4 GB. The kill came 7 s after the last
read, so the state at the kill itself is unmeasured. Inference: the Windows
verdict fired at about 12 percent physical free, well before commit ran out.
That is a measurement of when it fired. It is not proof that it was
over-cautious, because the next 7 s were not read.

F5. RC's other guard does not watch physical memory.
`ops/fleet_kit/fleet_suite_gate.py` admits on free COMMIT (CommitLimit -
CommitTotal, GetPerformanceInfo; docstring items 9, 15, 18). It reads
PhysicalAvailable only into a stats dump; no admission or stop uses it (grep).
The ruled run needed 35314 MB free commit at margin 2048 (RC-NEXT-SESSION.txt)
on a 31.6 GB RAM box, so the suite is admitted into states that must page. On
this stack the Claude Code reaper is the only guard tied to physical memory.

F6. What happens with it off when memory really runs out on this box.
Windows has no OOM killer (OS design, not measured here). When physical memory
runs out, working sets are trimmed and pages go to the pagefile (about 16.8 GB
of commit above RAM here): desktop stalls and game hitching. When commit runs
out, whatever process allocates next fails. Measured on this box 2026-09-03
(memory reference_parallel_slices_full_suite_oom.md): 721 MB free, `git status`
malloc failure, pytest INTERNALERROR MemoryError, and two agents died with a
message that read like an API error. The process that fails can be League, the
RC service host, OBS, or Claude Code itself.
Memory feedback_gamepc_league_fullscreen_lockup.md does NOT apply. Its own
scope fence says it records a window-management lockup on the retired Game-PC
and is not a memory or capture record.

F7. This is the game PC. League, Vanguard, RC, vision, dashboard and OBS share
the box (CLAUDE.md Topology, ADR-011). The reaper fires only when the session
is idle 30 min with no turn and no agent, which is what the session looks like
while the operator plays. So the reaper is the guard that stops a background
suite launched from Claude from paging the game mid-match.

F8. Where it can be set.
- Launch environment of the Claude Code process: the vendor's own note says
  "starting Claude Code with CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1 in
  its environment; setting it from a shell command has no effect". The suite's
  own environment cannot carry it, because the reaper runs inside Claude Code.
- settings.json "env": the docs say Claude Code copies those values into its
  own environment; project env values wait for workspace trust. The code reads
  the variable each time a shell is backgrounded. Settings hot-reload is
  documented, but nothing documents whether a reloaded env reaches this check,
  so "takes effect without a restart" is UNVERIFIED. Only a fresh launch is
  verified.
- User scope (the account's own Claude Code settings file) is an account settings file: operator
  only (CLAUDE.md, FLEET item 15).
- Project scope (gitignored `.claude/settings.json`, which already has an env
  block): the variable is not a display key and not in `tree_forbidden` of
  `ops/fleet_kit/cli_display.json`, so FLEET item 15 does not bar it. It would
  still apply to every interactive session started in this tree for as long as
  it stays, and it is absent from the tracked template
  `ops/claude_settings.example.json`.
- Current state: unset in User and Machine registry env and in this session's
  process env (read 2026-11-05).

F9. A restart now ends the running work. The gated suite's python (gate
started 17:13:55 local) is a descendant of this session's claude.exe through a
bash chain (process table read). Restarting that process ends the suite, every
background agent and shell, and the session-only cron job. `claude --continue`
brings back the conversation but not running tasks (general CLI behavior, not
measured here).

## ALTERNATIVES

1. User/account scope: REFUSED. It is the operator's file. It covers every
   session in every tree on the game PC, indefinitely, and it needs a restart
   (F9).
2. Project `.claude/settings.json` env: REFUSED. It covers every interactive
   session in this tree with no end date, its effect without a restart is
   unverified (F8), and it drifts from the template.
3. Only for the suite's launch: NOT POSSIBLE through the suite's env (F8). The
   narrowest real scope is one dedicated Claude Code window started with it,
   which is the conditional path below.
4. Agent-held window (the reaper skips while a turn or a delegated agent
   runs, F2). Exposure is the same as the variable, but limited to the run.
   NOT ruled here: LEDGER 2051 refused it and the detached `run_suite.py` as
   paths chosen to dodge the reaper. This ruling does not reverse that. It
   falls under the same conditions as the variable.
5. Cause side, in-tree, ADOPTED: give RC's landing-run stop-condition sampler
   a physical-memory STOP (proposal: PhysicalAvailable under 2048 MB on two
   reads in a row; that is half the measured 3850 MB floor and above the
   721 MB failure state of 2026-09-03) and a STOP when a League or Vanguard
   game process appears. Launch the landing suite only on a quiet box (no
   game, lanes paused, browsers closed), which raises the physical headroom
   the reaper reacts to. Fewer workers stay out: `-n 8` is MAIN's order, and
   LEDGER 2051 measured no admission gain.
6. Kit side, ADOPTED as a report: tell MAIN that fleet_suite_gate admits on
   commit only and never on physical memory (F5). The kit is MAIN's (FLEET
   item 11); RC does not edit it. It goes in the next note to MAIN under the
   outbound cap.
7. Do nothing: ACCEPTABLE as the default. A kill costs one re-run when the
   operator asks for it. It never costs the game, the RC stack or the box.

## WHY

- The rule "do not disable a protection on a guess" binds. The only
  measurement (F4) misses the 7 s before the kill, and the Windows threshold
  is undocumented (F3). Those facts cannot show the reaper fired early.
- It is the only guard in the stack tied to physical memory (F5), on the box
  that runs League (F7). Without it, a real exhaustion fails processes at
  random, including the game (F6).
- The docs say the variable does nothing on Windows while the code says it
  does (F3). Its effect on this OS is not covered by any vendor document.
- Setting it now needs a restart, which would end the suite the operator just
  started (F9).
- The variable stops being a blind removal only when a measured,
  League-aware, physical-memory guard that RC owns replaces it (Alternative 5).
  That is the re-open condition.

## RE-OPEN (the condition that reverses "do not set")

Set it, per launch only, when ALL of these hold:
(a) the Alternative 5 physical STOP and game-process STOP are live in the
    landing-run sampler;
(b) the reaper kills the ruled landing suite again while that sampler's last
    read was above its physical STOP line and no game process was running
    (that is, the reaper fired while RC's own measured guard said safe);
(c) the operator asks for the landing suite, no game is running or planned
    during the run, and lanes are paused.
Also reverses: a vendor doc or changelog that documents the Windows trigger
and threshold (re-adjudicate on it), or a MAIN ruling.

## OPERATOR STEPS (only once Re-open (a)-(c) hold; none are needed now)

1. Do not restart the current session. Open a NEW PowerShell window outside
   Claude Code.
2. In it run, one line at a time:
     $env:CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP = '1'
     Set-Location '<repo>'      (the RC checkout root)
     claude
3. In that window type: run the landing suite
   (Make sure no other suite is running in this tree, since the gate allows
   one per tree.)
4. Do not start League until it reports.
5. When it reports, type /exit and close the window. The variable goes away
   with that process. Do not use setx, the registry or any settings file.
