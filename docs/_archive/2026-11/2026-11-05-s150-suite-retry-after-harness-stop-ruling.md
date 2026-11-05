# s150 adjudicator ruling: after the harness stopped the gated suite

Distinct adjudicator under FLEET-COMMON item 1. Measured 2026-11-05 11:12-11:19 local.
Read-only on the tree. No suite, no commit, no kill, no setting change.

Archive note: `ruling :N` is line N of 2026-11-05-s150-suite-gate-landing-margin-ruling.md beside this file; `gate :N` is ops/fleet_kit/fleet_suite_gate.py. Every other file:line is as read at `3f66ffe0e`, and docs/LEDGER.md lines move as entries are added (:104 = LEDGER 2050, :106 = 2049, :112 = 2046, :126 = 2039). Scrubbed for the tracked copy: one home-relative path reworded in section 11, and this note added. Nothing else differs from the ruling as written.

## 1. Decision

A. NO FURTHER SUITE RUN until the operator asks for one.

- Option B is refused, at any worker count.
- The 19:40 window lapses unused.
- Origin stays red at `e21b4391b`. Local main stays `3f66ffe0e`, unpushed.
- Lanes resume at 20:11:45 as scheduled. Nothing is done to them.
- This stop rests on the harness's own words (section 2), not on the main session's limit.

## 2. The controlling fact

The stop notification carries this text. Read from the installed CLI 2.1.318 (byte offset 294100022 of `bin/claude.exe`; package.json:3). LEDGER 2050 (docs/LEDGER.md:104) quotes two of its phrases and says "the harness says not to restart it unasked".

    "This is not a failure of the command. Claude Code stopped it because the system was
    critically low on memory while the session was idle ... Do not start it again on your own,
    even if the work seems to need it: memory may still be short. Report what was stopped and
    why, and start it again only when asked."

- Nobody with standing has asked. An agent's message, including this ruling, is not that ask.
- "Full access approved" (RC-NEXT-SESSION.txt:4) does not lift it.
- `-n 6` or `-n 4` is the same whole suite with fewer workers. Calling it a different command to get past "start it again" is the reasoning I was told not to do.

## 3. Did the void run use the retry?

The ruling has TWO retries, and they are separate.

- Exit-3 branch (ruling :117): "then ONE retry at this same command". USED. The 10:52:12 run was it (docs/LEDGER.md:104, "the one retry of the ruled command of LEDGER 2047").
- Harness-stop branch (ruling :125): "One retry; a second stop goes to the operator line above". NOT used on its words. docs/LEDGER.md:104 says the same.
- I SUSPEND the second. The ruling predates the notification text and does not quote it. Its own forecast (:126) names this class as most likely, and the same command on the same box invites the same stop.
- Narrowing is within this call. A MAIN ruling still outranks both adjudications (ruling :16).

## 4. Option B, on its merits

Even without section 2, B would be weak.

Is `-n 8` binding? YES on the words.

- MAIN ORDER 2026-10-25 2045, moon_sync_inbox/2026-10-25-2045-from-MAIN-ORDER-to-RC-suite-speed-durations-and-24gb-commit-ONE-ANSWER.md:27 "Pin -n 8 (not -n auto)". FLEET item 6 (CLAUDE.md:59) gives it the operator's weight.
- CLAUDE.md:350 Tier-2 and :389; tools/done.md:83; guard tests/test_command_docs_suite_gate.py:98-105, :154-158 (it pins command docs, not runs).
- Against: the order's stated reason is -n auto oversubscribing (:39-40), and s135 and s142 ran `-n 6` (BACKLOG.md:1021-1024; s142 is after the order).
- BACKLOG.md:1031-1034: "A lane cannot reconcile them", the decision goes to MAIN. Ruling :164 and :117 also refuse another count or a re-spell. I do not reconcile it here.

Is a lower count still a whole suite? YES. Same paths, same collection. CLAUDE.md:350 forbids serial and slices, not fewer workers.

Admission: no gain. A new hash takes the tree median, 33265.9 (gate :98-100, :945-963; ruling :109; durations.jsonl window 31199.4, 34859.9, 33265.9, 33345.2, 25518.4), so need is still 35313.9. Free commit read 35980 at 11:13.

Time: no obstacle.

- The gate has no run-time limit. `--timeout` is the wait only (gate :34, :685-692), and the run is a bare `p.wait()` (:1480). The pytest cap is per test.
- `-n 8`: 1073 s to 94 percent, so about 1141 s. Recent plain holds 1192-1366 s (durations.jsonl).
- `-n 6`: +29 to +32 percent on unpaired runs (BACKLOG.md:1026-1027), about 1470-1800 s. It fits before 19:40 and before 20:11:45.
- `-n 4`: NO measured row. By worker ratio about 38-46 min, inferred.

Would it clear the reaper? PLAUSIBLE, NOT KNOWN.

- `-n 6` saves 15-17 percent of tree peak (BACKLOG.md:1028, estimates). On 22175 MB that is 3326-3770 MB, so a physical floor near 7200-7600 MB, inferred and assuming 1:1.
- `-n 4`: no data.
- Without a threshold (section 5) neither figure can be called clear.

## 5. The reaper: threshold UNKNOWN on Windows

LEDGER and logs do not measure it. I read the CLI's logic, read-only (offsets 300718744, 300723843, 300728183). A background shell is reaped only when ALL of these hold:

1. The runtime's pressure event says "critical".
2. The operator's last interaction is at least 30 min old (`$Xn=1800000`; `om()` is `userPresence.lastInteractionTime`).
3. No main-loop turn is running.
4. No delegated agent is in a live state.
5. NOT (the shell started under 30 min after an earlier reap with no terminal input since) (`FDs=1800000`).
6. Host memory is scarce. The 10 percent and 4 GiB figures are Linux and WSL ONLY. Everything else returns `{scarce:true, "kernel verdict taken as is"}`.

So on this box the trigger is a native verdict and I have no number for it.

Data points, none a threshold (s150r_sampler.jsonl, re-read, 108 rows):

- Last read 11:09:58: physical available 4136 MB, free commit 14110 MB, tree 21912 MB.
- Floors at 11:09:38: 3850 MB, 13709 MB, tree 22175 MB. All three match LEDGER 2050.
- Earlier stops read 96, 99 and about 92 percent (BACKLOG.md:1037). This one is 87-88.
- The 05:11 run reached 1252 MB with no stop (ruling :103). It does not bound anything: clauses 2-4 or a detached launch could explain it. Not checked.
- Clauses 3 and 4 can hold a reap back after the event is already critical, so 11:10:05 may be when the gates opened, not when memory crossed a line.

Clause 5 breaks B's premise. A launch before 11:40:05 with no terminal input since is EXEMPT. "With the reaper still armed" would be false for it. The window is not a reason to hurry or to wait.

## 6. Do not

Same class as the routes rejected in advance. Each is a path chosen so the reaper does not fire:

- launching inside the clause 5 window on purpose;
- keeping a turn or a delegated agent alive to hold clauses 3 or 4 open;
- `ops/runtime/drive_rc/run_suite.py`, which RC-NEXT-SESSION.txt:56 names as launching the suite DETACHED. It stays off for this landing.

## 7. Alternatives

- A: TAKEN. The cost is a red CI on the public repo for some hours. Nothing is lost: main keeps the landing, LEDGER 2049 (docs/LEDGER.md:106) moved the markers, and the snapshot holds.
- B `-n 6` / `-n 4`: refused, sections 2 and 4.
- The ruled `-n 8` retry: suspended, section 3.
- Push main on touched-file reads, CI as the whole-suite read (precedent LEDGER 2010): REFUSED. 2047's push terms need gate exit 0 and a durations row (ruling :142-145). The partial log holds 3 unnamed F marks (docs/LEDGER.md:104), 101 commits and 400 files would go public, and an earlier push with no rc 0 suite preceded today's red (docs/LEDGER.md:126, :112). A push is irreversible and the halt boundary binds (CLAUDE.md:370).
- Branch plus PR, so Linux CI reads the fixes off the box: REFUSED. "Push main only" (RC-NEXT-SESSION.txt:20, :28-31). A `--ref main` dispatch tests origin main, not these fixes (tools/done.md:219).
- Whole suite by slices: forbidden (CLAUDE.md:350).
- Rejected in advance and not considered: detached launch, the env var or any harness setting, restarting Claude Code, stopping apps or lanes, a margin under 2048.

## 8. Allowed now

Light, no suite:

- Record this ruling: archive copy and a LEDGER entry, Tier-0, local commit, no push.
- Read nightly `ci` 42062228822 when it ends (schedule, on `e21b4391b`, in progress at 11:13). It reads origin's red tip, NOT the folds.
- Carry the hand-off items: the 3 unnamed F marks, RM-1506 OPEN, RM-1657 PARTIAL, the unsent note to MAIN (ruling :153-157), plus sections 5 and 9 of this file.

## 9. For the operator, one ask

- Say "run the landing suite" while at the terminal. Then the ruled command of LEDGER 2047 runs, same words, margin, preconditions and stops (ruling :20, :36-44, :115-131). Clause 2 then holds the reap off by the harness's own design, because a person is present. That is not a bypass.
- After 20:11:45 lanes will be up, which fails precondition :40. Pausing them is the operator's call.
- A second harness stop on that run ends it. Back to the operator; no retry.
- Choose or send: a lower worker count needs the operator or MAIN. OK the note to MAIN (ruling :153-157), which should now carry this question and section 5.

The env var, for the record: `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1`.

- The agent that proposed it said "likely". Now READ in CLI 2.1.318: it guards the listener's install (offset ~300728183), and the notification says it works only when set at Claude Code's start.
- UNVERIFIED by any run. NOT set, not proposed as the fix.
- It removes the protection on a box where commit pressure preceded a lane crash, cause inferred (docs/LEDGER.md:126). The operator's choice alone.

## 10. Reversal

Reverses if:

- the operator asks for the run in chat (section 9 applies);
- a MAIN note naming a landing worker count, margin or retry arrives: it goes to the main session, and CLAUDE.md's confirmation line for attended sessions applies;
- a later CLI drops the "do not start it again" text or changes the clauses in section 5: re-read, then re-adjudicate.

A reap on an operator-asked run does not reopen this. It ends that run.

## 11. Limits of this reading

- I went beyond the listed files, all read-only: the CLI binary, the landing agent's scratchpad logs, durations.jsonl, the hand-off, `gh run list`.
- CLI logic is minified code read as text. Not run, not debug-logged (the CLI's debug folder listed nothing).
- That the running session uses this exact binary is inferred from the matching notification wording.
- Git tree read clean after my reads.
