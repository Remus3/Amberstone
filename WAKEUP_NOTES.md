# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-08-30 - LANE 7 headless-repo: repo already clean, two doc fixes, two sweeps deferred

Outsider-clean audit in worktree `lane/repo`. Pre-flight caught that the launcher had
dropped the session in the MAIN tree with the `lane/repo` worktree ABSENT - created it
from main HEAD `2be9603c` and worked only there. `core.hooksPath` is the shared absolute
`.githooks` (reported, unchanged per 1b). Every standing guard was green on arrival
(drift_guard 0, archmap + state_schema up to date, ruff clean, worktree clean, the
byte-identical pair matching its pins), so the repo is clean at every machine-checkable
level; the value was in the uncovered surfaces.

**Shipped (LEDGER 1275, Tier-0 docs):**
- `docs/DAEMON_SLAYER.md:40` `cast_rates.` -> `ult_rates.` (the fn is defined only in
  `ult_rates.py:201`; line 50 already said so - a self-contradiction a stranger would grep and fail on).
- `docs/OPERATIONS.md:309` stale absolute rotation date ("~2026-08-01", a month past)
  replaced with a derive-from-mtime instruction.
- RM-227 filed (BACKLOG Reliability/hardening); DS_SWEEP_TRACKER pointer advanced to RM-228.

**Deferred, NOT executed (both filed under RM-227, anti-rediscovery):**
- Dead code: NO file dead to a HIGH bar. Five MED candidates (`ops/_scheduler_client.py`
  plus four re-runnable Phase-3 seeders), each with a retention rationale - a headless delete
  would be a wrong deletion. RM-195 already covers dead FUNCTIONS; this is files.
- Glyphs: 3,017 grandfathered U+2192/U+00D7/U+00B7/U+2248, already blocked NET-NEW by the
  `precommit_gate.py` catch-all (2026-07-28); population is deep-archive / DS-mirrored / frozen /
  FUNCTIONAL-delimiter (the coach arrow is a `_re.split` delimiter), so a rewrite is behaviour
  change, not hygiene. Outsider-facing living docs already clean.

**Out-of-repo: ZERO deletions executed** (67 GB 2026-07-30 snapshot fully stale on re-measure):
- `.gemini` 99 MB - distinct adjudicator APPROVED the purge on clean evidence (no live
  filesystem reader of `~/.gemini`), PROPOSED-ready but NOT deleted (permanent file deletion is
  operator territory under the standing safety rule).
- `Temp/claude/C--Sibling-A` 0.29 GB (was 35.5) - sibling repo, UNTOUCHED, propose-only.
- `.claude/projects` 1.19 GB - EVIDENCE, UNTOUCHED. `.cache` 13.8 GB - propose-only.
  RC Temp scratch 0.2 MB total - nothing older than 30d, no prune worthwhile.

**Gates:** doc guards green; full `tests/` from the worktree root **19131 passed / 144 skipped /
1 failed** - the one failure is the pre-existing fenced `test_subagent_prompt_flag.py::test_cli_version_still_matches_the_pin`
(PINNED_CLI 2.1.220 vs live CLI 2.1.251, needs `claude login`), 0 in this diff. No `.py` touched,
no `ENGINE_VERSION`, no Share mirror, no frozen-file edit. Branch `lane/repo` ready for the merger;
NOT merged to main from the worktree.
