# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-10-01, the repo tidy-up wrap (relocated `2026-09-20c` and `2026-09-20b` via `scripts/wakeup_prune.py --keep 3`, which reported "moving 2 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1037" - read off the tool's own output, never off a recollection; newest 3 = `2026-09-30b` this wrap, `2026-09-30` the weekly-routines repair, `2026-09-21a` the RM-480 wrap). The prior relocation was 2026-09-21, the 16.18.1 / ENGINE 1.282.0 wrap (relocated `2026-09-19d` the lane-widget audit via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1034" - read off the tool's own output; newest 3 = `2026-09-20c` this wrap, `2026-09-20b`, `2026-09-20`). The prior relocation was 2026-09-20, the ROUND B / bucket-scan / RM-477 wrap (relocated `2026-09-19c` the lane widget ship, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1033" - both figures read off the tool's own output, never off a recollection; newest 3 = `2026-09-20b` this wrap, `2026-09-20` the NOW-block drain, `2026-09-19d` the lane-widget audit). **One claim in the `2026-09-20` block below is SUPERSEDED and is called out here so it is not inherited: it says the 67 MB `laning_scenarios` JSONs "were ruled out: LFS, blob is 133 bytes". REFUTED 2026-09-20 - `collect_tree_blobs` reads the WORKING TREE, so a smudged LFS file is scanned at its full 66,961,895 bytes and those seven files were the dominant term; see the `2026-09-20b` block.** The prior relocation was 2026-09-20, the NOW-block drain wrap (relocated `2026-09-19b` the idle filesystem walker, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1032" - those two figures are read off the tool's own output, never off a recollection; newest 3 = `2026-09-20` this wrap, `2026-09-19d` the lane-widget audit, `2026-09-19c` the lane widget ship). **One superseded claim rides in the relocated block and is called out here so a reader of the archive does not inherit it: `2026-09-19b` says LL has NO `docs/CHANNEL.md`. FALSE - LL carries it at `third_party/rc_channel/docs/CHANNEL.md`; see the 2026-09-20 block.** The prior relocation was 2026-09-19, the lane-widget UI fixture audit + live acceptance wrap (relocated `2026-09-19` the RM-239 / RM-242 QA pass, VERBATIM - moved with the Edit tool because Bash writes to tracked files are banned, and the verbatim property was checked the strong way rather than asserted: the SAME text was typed into `docs/history_notes.md` and then used as the `old_string` that removed it from here, so the removal could only have succeeded on an exact byte match, and it was then re-confirmed by diffing the archived block against `git show HEAD:WAKEUP_NOTES.md`. **`scripts/wakeup_prune.py` was NOT run this pass, so NO tool-reported move count is quoted here** - do not read one into this note; newest 3 = `2026-09-19d` this wrap, `2026-09-19c` the lane widget ship, `2026-09-19b` the idle filesystem walker). The prior relocation was 2026-09-18, the laned orchestrated loop wave 7 wrap (relocated `2026-09-17b` the wave 4 block, via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 1027"; newest 3 = `2026-09-18b` this wave, `2026-09-18` wave 6, `2026-09-17c` wave 5). **THIS WAS THE FIRST REAL PRUNE AFTER THE RM-276 FIX, and the insertion-only property was verified on the REAL archive rather than inherited from the slice's scratch-copy measurement: exactly ONE difflib opcode, kind `insert`, 21 lines inserted, ZERO deleted, at old line 41, with `new == old[:41] + inserted + old[41:]` reconstructing exactly.** That matters because the pre-fix pruner would have deleted 1335 lines of ordering from this archive on this very run - see the wave 7 block below. The prior relocation was 2026-09-17, the laned orchestrated loop wave 4 doc-sync (relocated `2026-09-16b` the laned-loop wrap, VERBATIM - moved with the Edit tool because Bash writes to tracked files are banned, then byte-compared equal to the output of `scripts/wakeup_prune.py --keep 3` run on scratch copies of both files, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 970"; newest 3 = `2026-09-17b` this wave, `2026-09-17` wave 3, `2026-09-16c` waves 1-2). The pass before this one, on 2026-09-17, was the laned orchestrated loop wave 3 doc-sync (relocated `2026-09-16` the acknowledge-path wrap, VERBATIM via the Edit tool, byte-compared equal to `scripts/wakeup_prune.py --keep 3` output on scratch copies, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 969"; newest 3 = `2026-09-17` that wave, `2026-09-16c` waves 1-2, `2026-09-16b` the laned-loop wrap). The pass before that, on 2026-09-16, was the laned orchestrated loop wave 1 doc-sync (relocated `2026-09-15` the moon-sync merge, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 968"; newest 3 = `2026-09-16c` this wave, `2026-09-16b` the laned-loop wrap, `2026-09-16` the acknowledge-path wrap). The pass before this one, on 2026-09-16, was the laned-loop doc wrap (relocated `2026-09-14` the public surface refresh, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 966"; newest 3 = `2026-09-16b` this wrap, `2026-09-16` the acknowledge-path wrap, `2026-09-15` the moon-sync merge). The pass before this one, on 2026-09-15, was the moon-sync five-slice merge wrap (relocated `2026-09-12e` the discovery-axis + inter-scorer lane and `2026-09-12d` the fleet tooling-tier lane, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 2 session(s)" and "WAKEUP_NOTES now has 3 session(s); archive now has 964" - read those counts off the tool's own output, never off a recollection; newest 3 = `2026-09-15` this wrap, `2026-09-14` the public surface refresh, `2026-09-12f` the calibration lane). The pass before this one, on 2026-09-12, relocated `2026-09-12c` the SESSION WRAP doc-sync and reported "moving 1 session(s)" / "archive now has 962". The pass before that relocated `2026-09-12b` the five-slice merge and `2026-09-12a` RM-412 C1 OSS extraction, and reported "moving 2 session(s)" / "archive now has 961". The pass before that relocated `2026-09-11d`, the one before that `2026-09-11c`, and the one before that `2026-09-11b` and `2026-09-11a`, the same way. The 2026-09-11k RELOCATION DUE note that sat here is DISCHARGED and deleted - the file is back at keep-3. The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired. The 2026-09-16 RELOCATION DUE note that sat here is DISCHARGED and deleted by the 2026-09-16b prune above.

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
**Whether those are live HEAD bytes or historical versions was NOT settled - the `--tree` arm was
still running at wrap. Do not assume either answer.** **And CI cannot settle it:
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

---

# 2026-09-21a - RM-480 ratio-field ability overrides (ENGINE 1.283.0), nightly breaker flake root-caused, os.environ assert leaks closed, channel correction delivered

**LEDGER 1453 and 1454.** Commits, all pushed: `49c665b5c` RM-480 (ENGINE 1.283.0, DS :8860 bounced, /health 1.283.0); `5df0233a9` LEDGER 1453; `19ede4154` breaker boundary test float-exact; `d1d4bb089` environ-leak asserts + `empty_parameter_set_mark = fail_at_collect`; `77dff441a` CI collect fix for that ini change.

**RM-480 IS SHIPPED BUT MOVES NO DEFAULT SCORING.** The flag `apply_ability_base_overrides` is DEFAULT-OFF and parsed by only 4 routes (/ability-dps, /rank-mage, /burst, /rank-assassin) - NOT /rank-tank, and Poppy / Thresh / ChoGath are tanks. LeBlanc R's override hits block 3 while the engine reads block 0. The hand-off premise was wrong in places ("HIGH" is in no data file; Qiyana Q and ChoGath E had no ratio drift; the wiki column is wrong for Cassiopeia E Total Enhanced and Kennen R cooldown). `stale_champions` deliberately still lists all 7 - the ABSENT/STALE/CURRENT status reads it and the default engine still reads stale values.

**CI TRAP, and it bit this session:** `d1d4bb089` verified "collect counts unchanged, zero errors" LOCALLY, where the gitignored sibling config exists; on CI it is absent, `_sibling_roots()` is empty, and `test_channel_doc_rc_gate` errored at collect. A collect count measured on this host is a HOST fact. Fixed in `77dff441a` (one named skip), verified by collecting with the config resolver patched to a missing path.

**CHANNEL:** one RC note delivered 6 of 6, digest `679cfbab` (retracts RC 2130's two temp figures, answers the environ + empty-parametrize threads). It went to MAIN via the path in MAIN's README, which is NOT in `ops/moon_sync_repos.json`. Two SS notes (1900, 1930) arrived after and are UNREAD - 1930 answers RC 1030 and says a subscript is SAFE and the leak axis is the attribute.

**Operator research note closed:** `lol-scouting-replay-kit` is REFERENCE-ONLY (MIT code, Riot-owned PNGs, GRID esports data RC cannot reach).

## NEXT SESSION

See `RC-NEXT-SESSION.txt`.
