# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-01 - lane 5 Headless-Research REFILL (lane/research, docs-only)

Branch `lane/research`, NOT merged - left ready for the merger per the standing
worktree rule (an interactive session holds `C:/Riot Commander`).

**Which lanes were starved was MEASURED, not guessed.** `LANE N` tag counts across
ROADMAP + BACKLOG at run start: lane 8 = 103, lane 7 = 47, lane 4 = 10, lane 6 = 8.
So the refill targeted 4 and 6. Seven rows filed or corrected, **RM-322 through
RM-328**; next free id is now **RM-329** (`docs/DS_SWEEP_TRACKER.md:72`).

**The recall gate changed the run's shape and that is the headline.** A dispatched
census of unrun test trees was REDIRECTED mid-flight because `perseus_recall`
surfaced LEDGER 1215 / RM-170 (CLOSED 2026-08-06), which had already measured that
exact population into `docs/OPERATIONS.md`. Re-tasking the slice from "derive the
census" to "is the recorded census still true" is where the real defect was.

**Filed (bodies + acceptance in `BACKLOG.md`, compact pointers in `ROADMAP.md`):**
- **RM-322** (LANE 7) - the self-labelled AUTHORITATIVE test-scope table at
  `docs/OPERATIONS.md:27` is stale 4 ways. Re-measured: `tests` 18820 -> 20410,
  DS 10463 -> 10687, agent3 360 -> 359, root 29998 -> 31811. Its own invariant
  still closes exactly. `benchmarks` IS run by `codspeed.yml:51`, so CI-unrun is
  TWO trees / 707, not three; CI has NINE pytest sites, not two. **Acceptance
  deliberately FORBIDS a count guard** and points at the existing structural guard
  (`test_skip_condition_hygiene.py:1431`).
- **RM-323 / 324 / 325** (LANE 6, DS) - Arena mirrors `223118`/`224646`/`226655`
  credit 0.00 magic burst while their own notes state the SR magnitudes their twins
  return; `level: Infinity` returns HTTP 500 where the float sibling returns 400;
  `mode="ARAM"` gives multiplier 0.87 but `mode="aram"` gives 0.92 and `"FOO"` is
  accepted with 200. All three PROBED live or in-process by the merger.
- **RM-326 / 327 / 328** (LANE 4, UI) - the lobby view is the only polled panel with
  no idempotent-render gate (2 s timer, two unconditional `innerHTML` clears, focus
  dies invisibly); Top-8 reorder buttons re-index on click so a second click undoes
  the first; `renderTeamContext` returns at its second line every call because
  `cs-team-context-block` is in no HTML. RM-328 is DECIDE-THEN-ACT with no
  prescribed resolution.

**Corrected in place, not struck:**
- **RM-314** constructor census 12 -> **17**. A verifier reached 17 independently,
  and `tests/test_anthropic_base_url_pin.py:23-40` already lists exactly those 17
  behind a passing exhaustiveness guard - the repo had said 17 all along. The row's
  substantive claim (no client sets `timeout=`) is UNAFFECTED and true. My own
  opening hypothesis, that RM-314 and RM-302 were duplicate mints, was WRONG and is
  recorded as refuted.
- **RM-294b** DOWNGRADED. Its discovery is a rediscovery of what OPERATIONS.md:41
  and ROADMAP_HISTORY.md:128 recorded 25 days earlier, and 3 of its cites are wrong.
  Its ACTION half survives, re-scoped to two trees. Striking it entirely would have
  destroyed real lane-7 work.

**New closed negatives (do NOT re-run these sweeps):** undefined-CSS-custom-property
is EXHAUSTED at RM-209's seven; the banned non-ASCII glyph set is EMPTY across
`web/**` and `rc-shell/**`; DS route-seam transport-vs-flag is well guarded by
`test_ds_parity_map.py`; all 32 route-facing DEFAULT-OFF seams ARE exercised ON;
per-map `ITEM_EFFECTS` coverage complete on all 6 live maps; `DAEMON_SLAYER.md`'s
108/89 CC and 34-route claims both re-measure CORRECT.

**Method trap that cost real time twice in one run:** `grep -P` aborts under this
Git Bash locale ("supports only unibyte and UTF-8 locales") and with stderr unread
that reads as a clean sweep. It produced a false zero for the merger AND for one
slice independently. A `git ls-files | xargs grep` also returned empty for its
CONTROL as well as its target (exit 123) and was discarded rather than believed.
Every sweep here was re-run with a proven control. See
`feedback_empty_grep_is_a_claim_about_the_pattern`.

**Next session:** `C:/Users/Administrator/Desktop/RC-NEXT-SESSION.txt`.

---


# 2026-09-01 - merger: lane 8 true-audit (61 commits) LANDED on main

Operator was given the framed decision (review+merge vs resume the loop) and chose
**merge**. lane/true-audit was the LAST unmerged lane (lane/repo already on main;
lane/ds + lane/research empty), so the "ships last" precondition was met.

**Landed: `main` @ `a41a2ad9`** (was `0779188f`). Two commits: the merge `e2a8f960`
(main folded into the branch in the worktree, then main FF'd to it) + a doc fix
`a41a2ad9`. Pushed to `Remus3/amberstone`.

- **Code: zero code conflicts.** Branch hardening vs main's advances (DS 16.17.1,
  ports, run_lane, dead-ops) are disjoint by file.
- **Docs: 6 conflicts, parallel-landing renumber.** LEDGER branch 1270-1306 -> +7 ->
  1277-1313; RM-221/222/223/227/228 (dual-allocations) -> 317-321; next-free = RM-322
  (authoritative in `docs/DS_SWEEP_TRACKER.md`). WAKEUP+history took main's canonical.
- **Review: 6 parallel adversarial slices, ZERO MUST-FIX.** SHOULDs all pre-existing/
  filed (RM-302/314 TFT timeouts, RM-294 warm_session lock).
- **Suite on merged tree:** DS 10687/0; RC 20272 pass + the known CLI-pin fail only.
  Fixed one net-new broken citation (BACKLOG -> WAKEUP:174, from main's shorter WAKEUP).
- **Follow-ups DONE:** RC restarted (pid 29904, code live); match_db repair dry-run
  0/8395 (already backfilled during the loop; `--apply` is a no-op; DB backed up).

**NEXT (do first):**
1. **ROADMAP size-budget relocation.** ROADMAP is 81757 bytes = 99.7 pct of the 81920
   budget (drift_guard WARN; main was a clean 86.7 pct before this merge). The branch
   carried it at 99.6 pct. Relocate CLOSED-row stubs from the active ROADMAP to
   `docs/ROADMAP_HISTORY.md` (their bodies are already there) to get back under 90 pct.
   NOT done inline at merge because the active list interleaves open rows with
   load-bearing do-not-re-open fences - it is the recurring operator-gated pass.
2. `restart_trigger.txt` did NOT self-clear after the restart (pid stable, no loop, so
   benign - the supervisor is content-keyed), but confirm it is gone / harmless.
3. `data/match_history.db.premerge-bak-20260901` (16.5 MB, gitignored) can be deleted.
4. Confirm the `a41a2ad9` CI `ci` job went green (docs-guards/CodSpeed already green).

Loop tooling was ephemeral (prior session scratchpad); to resume lane 8, restart via
Mission Control. ~27 orphaned claude.exe from the loop still linger (reboot or reap).

---

# 2026-08-31 - lane-8 true-audit loop: run_lane.ps1 opus-5 + bg-ceiling, 61 branch commits

Ran the Headless-True-Audit lane (lane 8) as a continuous autonomous loop from an
interactive session. Two main-tree fixes shipped + pushed:
- `a9ff183e` run_lane.ps1 reads the model from `ops/loop/config.json:executor_model`
  (claude-opus-5), not the hardcoded `claude-opus-4-8`. Governs all 7 lanes.
- `40f2a45d` run_lane.ps1 sets `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=2400000` (40 min)
  so a worker's background verifier gate finishes before the CLI reaps it. MEASURED:
  at the default 600s the verifier was killed mid-run and the worker exited 0 having
  committed NOTHING - a lost cycle.

Loop produced 61 commits on `lane/true-audit` (`39b63ebb` -> `246af97d`), ~41 spawn
cycles, 14+ files hardened (riot_api, _handler, match_db, polled_json, routes_state/
diag, snapshot_normalizer, performance_tracker, sr_user_builds, _supervisor_http,
decision_detector, vision_server). Branch is UNMERGED - lane ships last, merger's
call. Independently re-verified `2eed2421` (polled_json per-writer scratch-name
concurrency fix) myself: 33 tests pass, and reverting the fix reds 4 guard tests.

Loop tooling lives in the session scratchpad (loop_driver.py + loop_spawn.py +
watch_lane8.py + lane8_loop_state.json), NOT committed - to resume, restart
loop_driver.py. Loop is STOPPED (operator wrapped).

Do NOT redo: the run_lane.ps1 fixes are shipped; lane commits are real (verify by
merge/file/test, never a worktree slice hash). Watch: headless workers can
hang-after-commit (~27 subagent children; taskkill /F /T reaps; the driver
auto-reaps on commit+clean+idle now); ~26 orphaned claude.exe subagents linger.

---

# 2026-08-30b - merger: lane/repo merged to main, then RM-227(a) executed

The merger session picked up `lane/repo` @ `0c1eaa1b` (LEDGER 1275, Tier-0 docs,
docs-guards green) and fast-forward-merged it to main - a clean FF (main was 0
ahead, no conflict possible). `ci` correctly skipped (docs-only paths-ignore);
docs-guards green on the main push. Then the operator approved continuing with
RM-227(a).

**RM-227(a) - five dead ops scripts removed and pinned (commit `b5e10a7d`, LEDGER
1276, Tier-1).** Prove-it-dead was re-verified from scratch, NOT trusted from
lane-7's filed row. The decisive catch: `ops/_scheduler_client.py` looked alive
only because its `file_task` shares a name with `Scheduler.file_task` - every hit
is a call to the SCHEDULER METHOD (`agents/agent1_lead/scheduler.py:416`), never
the `ops._scheduler_client.file_task` wrapper FUNCTION, whose HTTP-first design no
caller ever adopted; its only importer was one self-test, removed with it. The
four Phase-3 seeders (`phase3_file_audit_proposals`, `phase3_file_rc_audit_proposals`,
`phase3_queue_first_audit`, `phase3_summary`) had zero code references at all; no
`.ps1`, scheduled task, or dynamic `ops/phase3_*` loader reaches them
(`RC-Phase3-PeriodicAudit` runs `-m ops.phase3_file_audit`, a KEPT sibling).
Pinned by `tests/test_orphan_scripts_rm227.py`, red-first proven (it failed
listing all five while present, passed once gone). Removed the orphaned self-test
`test_client_fallback_when_supervisor_unreachable` + its now-unused `Path` import
from `test_file_task_api.py`; that file still collects its 6 live-endpoint tests.

**Deliberately left:** the five appear as decorative HEXCORE dust particles -
guard-safe residue, because no test asserts dust-entry-to-disk correspondence and
`drift_guard` sweeps HEXCORE for versions/ASCII only. Editing that fragile
multi-count DUST contract for cosmetic gain is higher-risk than leaving it.
RM-227(b) (grandfathered glyphs) and the `.gemini` purge remain operator-gated and
untouched.

**Gates:** `pytest tests` 19132 passed / 144 skipped / 1 failed - the one failure
is the pre-existing fenced `test_cli_version_still_matches_the_pin` (CLI 2.1.251 vs
PINNED_CLI 2.1.220, needs `claude login`, outside this diff, LEDGER 1273),
confirmed twice (once foreground for direct evidence). On the main push `b5e10a7d`:
**ci = success, docs-guards = success, CodSpeed = success** (ci ran ~45min on a slow
runner but completed green; the local CLI-pin failure SKIPS on CI). doc-content
guards 74 passed; `drift_guard` 0 breaches; ruff clean. No `ENGINE_VERSION`, no
Share mirror, no `:8860` bounce, no frozen-file edit.

**One process note worth keeping:** the `stop_claim_gate` (RM-226, known-defective)
blocked the first stop on the `19132` count because it reached me via a background
task's OUTPUT FILE (read with the Read tool), which the gate never admits as
evidence - exactly the RM-226 defect. Resolved the RM-226-compliant way: re-ran the
suite in the FOREGROUND so the count is direct runner output. Did NOT edit the gate
(it must not be edited by a session it is blocking).

**NEXT:** RM-227(b) glyphs + the `.gemini` purge stay operator-gated. RM-192/193/225/226
open in BACKLOG. CLI-pin still needs `claude login` (unchanged, LEDGER 1273).
