# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-08-29c - a cross-project port collision, found by answering a question

Operator asked which ports are reserved for Amberstone, DS, Sibling-E, Sibling-D,
Sibling-A and Sibling-C. `core/ports.py` could only answer for FOUR: the 2026-08-01
negotiation predates both Sibling-D and Sibling-E, so `BLOCKS` had no `ll` or `cs`
key and `block_for(8810)` returned None.

**Answering it turned up a live collision.** Sibling-E claimed band **8900-8911** with
its dashboard on **8901** - wholly inside Sibling-A's reserved 8900-8919, where
8901 is LW's `MONITOR` and 8900 its `RUNDASH`. Cause is the exact method `core/ports.py`
warns about in capitals: CS picked the band by SCANNING for a free listener, and LW's
monitor is an operator-launched GUI that is unbound most of the time, so the scan
reported a reserved block as free. CS names Sibling-A in zero files. It had already
met the symptom and mis-filed it - its BACKLOG blamed "an unrelated process" holding 8901
since 2026-08-16.

**Shipped:** RC `533d4f97` - `LL_BLOCK` + `CS_BLOCK` registered, `BLOCKS` now six, the
collision recorded in the docstring, two new guards (CS/LW disjointness pinned by NUMBER;
LL's widened 8815-8819). Mutation-proved RED three ways, `core/ports.py` restored
byte-identical. LEDGER 1274. Sibling-E moved to **8920-8939** base **8920** across 6
files; its `verify_env.py` went from a soft failure on every run since 2026-08-16 to
**PASS, ports free 20/20**.

**Do NOT redo:** Sibling-D was already correct (8810-8819) and already carried the
identical six-row table - it independently settled a one-digit ambiguity in the operator's
own message (prose said 8820-8839, the table said 8920-8939). It has uncommitted work from
its own session; leave it alone.

**BLOCKED, and it is not ours to clear:** the Sibling-E commit `67b00b2` exists and is
byte-identical to the intended content, but **the push is blocked by that repo's own
`pre-push` hook** (`pytest tests -q -x`). Its suite is red from ANOTHER session's in-flight
surface-contract work - an untracked `sibling_e/surface/api/contract.py` that its staged
`tests/surface/test_contract.py` imports. Two of the three failures name that file
directly; the third passes in isolation. `main` there is ahead 1, remote still `4ac5c3e`.
Never `--no-verify` it. It goes up when that session's work lands green.

**Process note worth keeping:** I edited a sibling repo another session was concurrently
working in. It resolved cleanly, but I checked Sibling-D for in-flight work and did NOT
check Sibling-E before writing. Check every sibling tree's `git status` first.
