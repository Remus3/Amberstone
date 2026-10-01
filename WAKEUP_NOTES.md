# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-30, the lane-refs / anomalies / channel-drain wrap (relocated `2026-09-21a` via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1038" - read off the tool's own output, never off a recollection; newest 3 = `2026-09-30c` this wrap, `2026-09-30b` the repo tidy-up, `2026-09-30` the weekly-routines repair). The prior relocation was 2026-10-01, the repo tidy-up wrap (relocated `2026-09-20c` and `2026-09-20b` via `scripts/wakeup_prune.py --keep 3`, which reported "moving 2 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1037" - read off the tool's own output, never off a recollection; newest 3 = `2026-09-30b` this wrap, `2026-09-30` the weekly-routines repair, `2026-09-21a` the RM-480 wrap). The prior relocation was 2026-09-21, the 16.18.1 / ENGINE 1.282.0 wrap (relocated `2026-09-19d` the lane-widget audit via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1034" - read off the tool's own output; newest 3 = `2026-09-20c` this wrap, `2026-09-20b`, `2026-09-20`). The prior relocation was 2026-09-20, the ROUND B / bucket-scan / RM-477 wrap (relocated `2026-09-19c` the lane widget ship, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1033" - both figures read off the tool's own output, never off a recollection; newest 3 = `2026-09-20b` this wrap, `2026-09-20` the NOW-block drain, `2026-09-19d` the lane-widget audit). **One claim in the `2026-09-20` block below is SUPERSEDED and is called out here so it is not inherited: it says the 67 MB `laning_scenarios` JSONs "were ruled out: LFS, blob is 133 bytes". REFUTED 2026-09-20 - `collect_tree_blobs` reads the WORKING TREE, so a smudged LFS file is scanned at its full 66,961,895 bytes and those seven files were the dominant term; see the `2026-09-20b` block.** The prior relocation was 2026-09-20, the NOW-block drain wrap (relocated `2026-09-19b` the idle filesystem walker, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1032" - those two figures are read off the tool's own output, never off a recollection; newest 3 = `2026-09-20` this wrap, `2026-09-19d` the lane-widget audit, `2026-09-19c` the lane widget ship). **One superseded claim rides in the relocated block and is called out here so a reader of the archive does not inherit it: `2026-09-19b` says LL has NO `docs/CHANNEL.md`. FALSE - LL carries it at `third_party/rc_channel/docs/CHANNEL.md`; see the 2026-09-20 block.** The prior relocation was 2026-09-19, the lane-widget UI fixture audit + live acceptance wrap (relocated `2026-09-19` the RM-239 / RM-242 QA pass, VERBATIM - moved with the Edit tool because Bash writes to tracked files are banned, and the verbatim property was checked the strong way rather than asserted: the SAME text was typed into `docs/history_notes.md` and then used as the `old_string` that removed it from here, so the removal could only have succeeded on an exact byte match, and it was then re-confirmed by diffing the archived block against `git show HEAD:WAKEUP_NOTES.md`. **`scripts/wakeup_prune.py` was NOT run this pass, so NO tool-reported move count is quoted here** - do not read one into this note; newest 3 = `2026-09-19d` this wrap, `2026-09-19c` the lane widget ship, `2026-09-19b` the idle filesystem walker). The prior relocation was 2026-09-18, the laned orchestrated loop wave 7 wrap (relocated `2026-09-17b` the wave 4 block, via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1027"; newest 3 = `2026-09-18b` this wave, `2026-09-18` wave 6, `2026-09-17c` wave 5). **THIS WAS THE FIRST REAL PRUNE AFTER THE RM-276 FIX, and the insertion-only property was verified on the REAL archive rather than inherited from the slice's scratch-copy measurement: exactly ONE difflib opcode, kind `insert`, 21 lines inserted, ZERO deleted, at old line 41, with `new == old[:41] + inserted + old[41:]` reconstructing exactly.** That matters because the pre-fix pruner would have deleted 1335 lines of ordering from this archive on this very run - see the wave 7 block below. The prior relocation was 2026-09-17, the laned orchestrated loop wave 4 doc-sync (relocated `2026-09-16b` the laned-loop wrap, VERBATIM - moved with the Edit tool because Bash writes to tracked files are banned, then byte-compared equal to the output of `scripts/wakeup_prune.py --keep 3` run on scratch copies of both files, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 970"; newest 3 = `2026-09-17b` this wave, `2026-09-17` wave 3, `2026-09-16c` waves 1-2). The pass before this one, on 2026-09-17, was the laned orchestrated loop wave 3 doc-sync (relocated `2026-09-16` the acknowledge-path wrap, VERBATIM via the Edit tool, byte-compared equal to `scripts/wakeup_prune.py --keep 3` output on scratch copies, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 969"; newest 3 = `2026-09-17` that wave, `2026-09-16c` waves 1-2, `2026-09-16b` the laned-loop wrap). The pass before that, on 2026-09-16, was the laned orchestrated loop wave 1 doc-sync (relocated `2026-09-15` the moon-sync merge, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 968"; newest 3 = `2026-09-16c` this wave, `2026-09-16b` the laned-loop wrap, `2026-09-16` the acknowledge-path wrap). The pass before this one, on 2026-09-16, was the laned-loop doc wrap (relocated `2026-09-14` the public surface refresh, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 966"; newest 3 = `2026-09-16b` this wrap, `2026-09-16` the acknowledge-path wrap, `2026-09-15` the moon-sync merge). The pass before this one, on 2026-09-15, was the moon-sync five-slice merge wrap (relocated `2026-09-12e` the discovery-axis + inter-scorer lane and `2026-09-12d` the fleet tooling-tier lane, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 2 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 964" - read those counts off the tool's own output, never off a recollection; newest 3 = `2026-09-15` this wrap, `2026-09-14` the public surface refresh, `2026-09-12f` the calibration lane). The pass before this one, on 2026-09-12, relocated `2026-09-12c` the SESSION WRAP doc-sync and reported "moving 1 session(s)" / "archive now has 962". The pass before that relocated `2026-09-12b` the five-slice merge and `2026-09-12a` RM-412 C1 OSS extraction, and reported "moving 2 session(s)" / "archive now has 961". The pass before that relocated `2026-09-11d`, the one before that `2026-09-11c`, and the one before that `2026-09-11b` and `2026-09-11a`, the same way. The 2026-09-11k RELOCATION DUE note that sat here is DISCHARGED and deleted - the file is back at keep-3. The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired. The 2026-09-16 RELOCATION DUE note that sat here is DISCHARGED and deleted by the 2026-09-16b prune above.

---

# 2026-09-30c - the six halted lane refs DELETED with no bypass, all three session-start anomalies closed at the source, 56-note channel drain, and a sibling corrected RC's published advice in 20 minutes

**The lane refs are GONE from origin and NO bypass was used.** The operator chose deletion
from the three options item 1456 framed. The deciding fact was measured BEFORE the ask, not
after: a delete push does not trip the sweep at all - the pre-push range parser returns `None`
on an all-zero local sha, and its own comment says treating that as an error "blocks every
branch cleanup". Also measured first: all six `origin/lane/*` SHAs were ALREADY ancestors of
`origin/main`, so deletion orphaned nothing. The sweep ran ARMED and returned `clean: 0 bytes`,
which is the correct verdict for a deletion - and note that a 0-byte `clean:` line IS a verdict
while NO `clean:` line is not. `origin` now carries exactly one head.

**Three session-start anomalies, and only ONE was a real defect.** The `RC-WeeklyHygiene` disarm
was a DELIBERATE operator decision of 2026-09-11 (`docs/history_notes.md:1033-1035`), so nothing
was re-armed; the fix was to stop the detector reporting a decision as a fault. `rc_facts.py` now
prints `0 anomaly(s), 3 acknowledged disarm(s)`, keeps the three VISIBLE rather than suppressing
them, and INVERTS the check for `RC-InboxResponder` - finding it ENABLED is now the anomaly. The
real defect was `rewind_catchup`'s `last_run_at`, whose fix landed in HEAD two days after the last
run and so had never executed; the stale row was BACKFILLED per the standing data-fix rule.
**My brief to that slice was WRONG and the slice refuted it** - I specified `04:00:00Z`, which
appends `Z` to a LOCAL time; the field is UTC, so `09:00:00Z` is correct. The third line was a
DETECTOR BUG twice over: the stale window equalled the log reaper's retention, so STALE was
unreachable, and one task could fire two anomalies.

**A CITATION THAT RESOLVES IS NOT A CITATION THAT IS RIGHT.** Three cites in CLAUDE.md were stale
by 26, 97 and about 140 lines. All three still RESOLVED, which is why nobody caught them, and a
FOURTH in the same paragraph was CORRECT - so a spot check of one would have passed the paragraph.
Sampling does not work on this class. The first pass refreshed the numbers; that was the weaker
fix, because `ROADMAP.md` already carried RC's own doctrine - cite the pin by SYMBOL, never by
line - having recorded the same drift twice before. Both paragraphs now cite by symbol. **RC has
NO gate on this and said so to the fleet as a negative rather than quietly shipping the instance.**

**A sibling corrected RC's published advice within 20 minutes and it changed RC's code.** RC had
offered its empty-parametrize close as an ini line plus a test reading the value back. SS replied
that this proves the STRING IS PRESENT, not that the BEHAVIOUR HOLDS - and RC's own guard from
item 1454 was exactly that weaker half. Now hardened with a real subprocess probe requiring a
COLLECTION ERROR plus the negative control that overrides the mark to `skip` and requires a SKIP.
Three ablations; the third was the slice's own and the best - flipping the REAL ini value reddens
both the assertion and the probe while the control stays green, proving the probe is driven by the
configured value and not a literal. Isolation is ASSERTED, not reasoned about. **And a third
failure mode neither tree had named: an ambient `PYTEST_ADDOPTS` would decide BOTH arms while the
pair still looked consistent** - the child env is stripped.

**Channel: 386 notes seen. Two RC notes delivered, each REACHED 5 of 5, destinations re-hashed
digest-equal, both swept before leaving the tree.** Eight findings triaged, filed as RM-490..RM-497.
**TWO intake cites did not survive re-derivation and are filed as REFUTED rather than dropped** -
and one of them got STRONGER in substance while its evidence collapsed. RM-497 is a measured
NEGATIVE kept so nobody re-opens it: RC forces `eol=lf` for every text class, so the sibling's
two-digest trap does not reach RC.

**The baseline earned its cost, and it caught my own mistake.** Full dual suite first: DS `10933
passed`; RC `4 failed, 24711 passed` in 1:46:58. **I attributed THREE of those four to my own
orchestration - a straddled tree - and that was WRONG.** A slice did write a live file during the
baseline, and the three do pass in isolation (`121 passed`), both true; the conclusion did not
follow. A second full run on the FINAL tree, quiescent and single-process, reproduced the same
three: `4 failed, 24727 passed` in 1:42:33. **They are FULL-SUITE-ONLY failures - cross-test
pollution, reproducible, and PRE-EXISTING at HEAD.** Passing in isolation is what a pollution looks
like; it is not evidence of a straddle. Root cause OPEN, two hypotheses already eliminated (no
warn-once guard in the subject; the noisy-logger override never touches `rc.*`), and CI is GREEN on
the same commit, so it does not reproduce on the runner. Filed as ROADMAP NOW-6. Post-merge was
tier-scoped per R5 (Tier-0 docs, Tier-1 tooling, no engine): affected modules `77 passed`, doc and
hygiene guards `128 passed / 2 skipped / 216 subtests`, ruff and `py_compile` clean.

**ONE genuine red remains and is FILED, not papered over (ROADMAP NOW-5):** the Claude CLI moved
to `2.1.285` from pinned `2.1.251`. Machine-local, not a CI red - the test skips when the CLI is
off PATH. It must NOT be silently re-pinned; the flag is undocumented and the test demands a
codeword negative control first, or the wire goes inert while the constant survives.

**One correction of my own:** I read a `tasklist` filter returning nothing as the suite having
died. Thirteen python processes were running and free RAM was 13.1 GB - the static output file was
pytest block-buffering. The probe was the fault, not the suite.

**PARKED for the operator, flagged not rewritten:** CLAUDE.md calls the channel "RC plus two
sibling checkouts" while config carries FIVE sibling codes and `docs/CHANNEL.md` says six. That may
be carriers-versus-participants rather than an error. Also left alone: one pre-existing non-ASCII
byte in `BACKLOG.md`, since the smart-quote sweep is a separate operator-gated pass. And the
`grep -P` glyph check in `.claude/commands/headless-upgrade.md` was a FALSE CLEAN (exit 2, scans
nothing) and is fixed - but that file is gitignored, so the fix exists only on this box.

---

# 2026-09-30b - PR #1 MERGED, branch and worktree estate cleared, ddragon 16.19.1 landed, lane pushes HALTED by the sibling sweep

**PR #1 is MERGED** as `eed3f8849`. CI was the gate, per the hand-off's own acceptance clause.
It was RED first, and NOT flaky: `test_no_test_asserts_against_the_whole_environment` caught
three assertions `fix/weekly-routines` added at `tests/test_supervisor_ephemeral_auth_env.py`
117/118/131 that would have printed every env KEY AND VALUE into the public CI log on failure.
Fixed in `72b973780` with helpers that return key NAMES only. **Note the shape: item 1454 added
that guard and fixed five hits; item 1455 then added three more in a new file.** My first helper
was weaker than the set equality it replaced (missed invented keys) - caught before commit.
Then green: **35456 passed, 282 skipped, 18723 subtests, 20m35s.**

**RM-486 is ANSWERED, not fixed.** CI ran the same dual suite clean twice, so the suite is sound
and the local exit-127 is a Legion harness fault. A local run was abandoned at 16 percent after
~50 minutes. Root cause still OPEN - do not re-run `pytest tests` here expecting a verdict.

**Estate:** 50 agent worktrees removed, 53 branches deleted, `fix/weekly-routines` gone local and
remote, orphan ref `refs/remotes/local/main` dropped. 19 branches looked unmerged; `git cherry`
proved every commit patch-equivalent upstream. **`git diff main..<branch>` is the wrong instrument
on a stale branch** - it reports main's content missing from THEM. Use `git cherry`.

**ddragon 16.18.1 -> 16.19.1** committed (`199fe7d40`) from the uncommitted `RC-PatchRefresh`
output. Pre-existing and NOT fixed: `test_meta_build_cache_retention.py` says current+previous,
but nine patch dirs are tracked - it guards the helper, not the tree.

**LANE PUSHES HALTED AND STAYED HALTED.** The six `lane/*` refs were fast-forwarded to main
locally; all six pushes were refused by `tools/sibling_name_sweep.py` - 10 findings across
BACKLOG / RC-NEXT-SESSION / CLAUDE / WAKEUP_NOTES / CONCURRENT_HEADLESS_CONTRACT / LEDGER /
`ops/loop/slots.py` / `tests/test_loop_concurrency.py` plus one commit message. **Nothing was
pushed, no bypass used, `origin/lane/*` unchanged.** The pre-push arm scans the DELTA and each
lane was 528-674 commits behind, so it re-read the whole history since that lane last pushed.
**SETTLED: they are HISTORICAL.** All 8 flagged paths scan clean at HEAD via `--scan-file`, and
the `--tree` arm finished CLEAN (650,644,164 bytes / 4968 files / exit 0; 482 binary-LFS blobs
not content-scanned, its stated blind spot). Also measured: all 675 lane-delta commits are
already ancestors of origin/main, so the push would send ZERO new objects - the sweep's delta is
per-REF, not per-repo. **Not acted on; no bypass used; the call is the operator's.** **And CI cannot settle it:
`sibling-sweep-tree` passed green on the same push, because the sweep loads its names from
gitignored per-host `ops/moon_sync_repos.json` and CI has no such file - CI's sweep is armed with
NOTHING. Never cite that green as evidence about sibling names.**

---

# 2026-09-30 - weekly scheduled routines repaired (PR #1, NOT merged), and the tests/ suite cannot complete locally

**Branch `fix/weekly-routines` pushed, PR #1 OPEN, NOT merged.** Four commits: `fb05d3488`
S1-S6, `ba4bb74be` S7, `6044a9ee1` S8 (FROZEN file, operator-approved in chat), `8e1ab5566`
citation repoint. Merge to main deliberately deferred - see the blocker below.

**What was actually wrong.** The weekly Agent-6 audit (`RC-Phase3-PeriodicAudit`) had failed 7
consecutive times since 2026-08-02, last success 2026-07-27, with `LastTaskResult 0` every
time. Two real faults: (a) `ANTHROPIC_API_KEY` is machine-wide, the supervisor inherits it,
`agents/_supervisor_ephemeral.py` `subprocess.run` passed no `env=`, so the spawned `claude -p`
used an org-scoped key and died 400 "not scoped to a workspace" - the CLI itself warns the key
outranks the claude.ai login; (b) `agents/agent1_lead/scheduler.py` read its queue ONCE at
construction, so a cron-filed task could not dispatch until a restart. Both fixed. Operator
re-logged in on Legion, verified `PONG` with the key stripped.

**Four reporting defects hid it for 7 weeks** and are all fixed: `tools/rc_facts.py` read
`267009` (SCHED_S_TASK_RUNNING) as success, suppressed Disabled tasks, never checked artifact
staleness; `ops/phase3_file_audit.py` ran under pythonw with no redirection so its filed/skip
decision went nowhere; `scripts/rewind_catchup.py` wrote `last_run_at` only on the hydrate path
(a healthy no-op week read 16 weeks dead - it fooled a reviewer AND me) and exited 0 on an API
403; `ops/run_postmortem_with_restart.ps1` had a WaitForExit-before-ReadToEnd pipe deadlock.

**Key precedence trap, found because the operator's rotation half-landed.** Seven consumers
disagreed on env-vs-file; five preferred the file, so rotating the env var left them on the
revoked key. `API-Key-Claude.txt` is now DELETED, machine env is the single source, and all
five are env-first. `dashboard/routes_coach.py` was a LIVE bug (file-only, no env path - it was
passing `api_key=""`). Deliberately NOT unified behind a shared helper: `app/_game_lifecycle.py`
is frozen and could never join, so a helper would guarantee a permanent 1-of-5 divergence while
advertising convergence.

**THE BLOCKER, and it is the top next-session item.** `pytest tests` CANNOT COMPLETE on this
box: exit **127**, no traceback, no summary, three runs aborting at DIFFERENT points (60%, 32%,
25%), in BOTH the live tree AND an isolated worktree. My "the live tree is hostile" theory was
REFUTED by the worktree run - do not re-pitch it. `agents/daemon_slayer` is green on the final
tree (`10933` passed, `13669` subtests, exit 0, 147.84s). It is NOT established whether the 127
pre-dates this branch; the cheap discriminator is to run `pytest tests` at `main` vs at
`8e1ab5566`. Do NOT merge PR #1 until CI's ubuntu runner gives a real full-suite verdict.

**Do NOT redo:** the auth diagnosis (confirmed in production - the stuck task dispatched and
failed with the exact 400), the OAuth login (done, PONG), the key rotation (done, file deleted),
or the 5 slice verifications (4 adversarial passes, every fix mutation-killed).
